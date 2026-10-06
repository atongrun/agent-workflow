#!/usr/bin/env python3
"""Startup probes use substituted I/O/commands; no root or native operations."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import native_startup_diagnostics as diagnostics


def info(mode=stat.S_IFREG|0o644,uid=0,gid=0,ino=17,size=12):
    return SimpleNamespace(st_mode=mode,st_uid=uid,st_gid=gid,st_dev=1,st_ino=ino,st_size=size)


def unit_output(unit,**overrides):
    values=dict(LoadState='loaded',ActiveState='failed',SubState='failed',Result='exit-code',
                MainPID='0',ExecMainCode='1',ExecMainStatus='1',
                FragmentPath='/etc/systemd/system/'+unit,DropInPaths='')
    values.update(overrides)
    return ('\n'.join(key+'='+value for key,value in values.items())+'\n').encode()


class StartupDiagnosticsTests(unittest.TestCase):
    def test_static_errors_cover_reviewed_source_without_exporting_runtime_text(self):
        root=Path(__file__).resolve().parents[1]
        sources=['internal/hostinstall/'+name for name in
                 ('native_linux.go','native_service_linux.go','native_guard_linux.go',
                  'native_update_linux.go','native_channel_linux.go','manifest.go')]
        sources.append('internal/core/maintenance.go')
        for source in sources:
            for literal in re.findall(r'errors.New\("((?:\\.|[^"\\])*)"\)',(root/source).read_text()):
                self.assertIn(json.loads('"'+literal+'"'),diagnostics.ERROR_CODES,source)
        self.assertTrue(all(re.fullmatch('[a-z0-9_]{1,180}',code) for code in diagnostics.ERROR_CODES.values()))

    def test_classify_exact_lines_rejects_tokens_context_paths_and_unknown_output(self):
        secret='secret-private-provider-value'
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'failure.log'
            path.write_text('x'*70000+'\n'+
                'Magpie snapshot permissions changed\n'+
                'awf-host.service: installed systemd unit changed\n'+
                'native command systemctl failed '+secret+'\n'+
                'open /private/'+secret+': permission denied\n'+
                'AWF bundle failed-start-stop: completed\n'+
                'AWF awf-host health: failed '+secret+'\n')
            path.chmod(0o600)
            result=diagnostics.classify(path)
        self.assertEqual(result['errorCodes'],['installed_systemd_unit_changed','magpie_snapshot_permissions_changed'])
        self.assertEqual(result['progress'],[dict(component='bundle',stage='failed-start-stop',state='completed')])
        self.assertNotIn(secret,json.dumps(result))
        self.assertNotIn('/private/',json.dumps(result))

    def test_classify_bounds_codes_and_progress_and_rejects_link(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'failure.log'
            path.write_text('\n'.join(diagnostics.SOURCE_ERRORS)+
                            '\nAWF bundle service-start: started'*100)
            path.chmod(0o600)
            result=diagnostics.classify(path)
            self.assertEqual(len(result['errorCodes']),32)
            self.assertEqual(len(result['progress']),32)
            self.assertTrue(result['truncatedCodes'])
            link=Path(temp)/'link'
            link.symlink_to(path)
            with self.assertRaises(diagnostics.Unavailable):
                diagnostics.classify(link)

    def test_metadata_matches_native_uid_and_mode_predicate_without_gid_confusion(self):
        for mode,uid,gid,trusted in ((0o755,0,123,True),(0o777,0,0,False),
                                    (0o775,0,0,False),(0o755,123,0,False),
                                    (0o4755,0,0,False)):
            with self.subTest(mode=mode,uid=uid,gid=gid),patch.object(diagnostics.Path,'lstat',
                    return_value=info(stat.S_IFDIR|mode,uid,gid)):
                result=diagnostics.metadata('/opt',directory=True)
                self.assertEqual(result['rootTrusted'],trusted)
                self.assertEqual(result['mode'],format(mode,'04o'))
        with patch.object(diagnostics.Path,'lstat',return_value=info(stat.S_IFREG|0o600,42,43)):
            result=diagnostics.metadata('/var/lib/awf/magpie-config/magpie/settings.json',service=(42,43))
            self.assertTrue(result['serviceOwned'])

    def test_metadata_errors_never_export_os_exception_text(self):
        with patch.object(diagnostics.Path,'lstat',side_effect=PermissionError('secret-path-and-token')):
            result=diagnostics.metadata('/opt')
        self.assertEqual(result,dict(path='/opt',observed=False,error='permission_denied'))
        self.assertNotIn('secret',json.dumps(result))

    def test_private_reader_never_opens_links_special_files_or_changed_inode(self):
        for mode in (stat.S_IFLNK|0o777,stat.S_IFIFO|0o600):
            with patch.object(diagnostics,'_parents'),patch.object(diagnostics.Path,'lstat',return_value=info(mode)),patch.object(diagnostics.os,'open') as opened:
                with self.assertRaises(diagnostics.Unavailable):
                    diagnostics._read('/etc/awf/host.json',100)
                opened.assert_not_called()
        with patch.object(diagnostics,'_parents'),patch.object(diagnostics.Path,'lstat',return_value=info()),patch.object(diagnostics.os,'open',return_value=7),patch.object(diagnostics.os,'fstat',return_value=info(ino=18)),patch.object(diagnostics.os,'close') as close,patch.object(diagnostics.os,'read') as read:
            with self.assertRaises(diagnostics.Unavailable):
                diagnostics._read('/etc/awf/host.json',100)
            read.assert_not_called()
            close.assert_called_once_with(7)

    def test_unit_query_requires_original_inode_literal_hash_and_trusted_mode(self):
        unit=diagnostics.UNITS[0]
        path='/etc/systemd/system/'+unit
        ledger=dict(paths={path:diagnostics._identity(info())},unitHashes={unit:hashlib.sha256(b'fixed-unit').hexdigest()})
        for changed in ('inode','hash','mode'):
            fixture=info(ino=18 if changed=='inode' else 17,mode=stat.S_IFREG|(0o666 if changed=='mode' else 0o644))
            bad=dict(ledger)
            if changed=='hash':
                bad['unitHashes']={unit:'0'*64}
            with patch.object(diagnostics.Path,'lstat',return_value=fixture),patch.object(diagnostics,'_read',return_value=b'fixed-unit'),patch.object(diagnostics,'_executable') as executable,patch.object(diagnostics,'_run') as command:
                result=diagnostics._attempt(lambda:diagnostics._unit(unit,bad))
            self.assertFalse(result['observed'])
            executable.assert_not_called()
            command.assert_not_called()

    def test_unit_report_only_exports_enums_numbers_and_path_match_booleans(self):
        unit=diagnostics.UNITS[0]
        path='/etc/systemd/system/'+unit
        ledger=dict(paths={path:diagnostics._identity(info())},unitHashes={unit:hashlib.sha256(b'fixed-unit').hexdigest()})
        secret='secret-private-token'
        with patch.object(diagnostics.Path,'lstat',return_value=info()),patch.object(diagnostics,'_read',return_value=b'fixed-unit'),patch.object(diagnostics,'_executable'),patch.object(diagnostics,'_run',return_value=(0,unit_output(unit,FragmentPath='/private/'+secret,DropInPaths='/private/'+secret))) as command:
            result=diagnostics._unit(unit,ledger)
        self.assertTrue(result['observed'])
        self.assertFalse(result['fragmentMatches'])
        self.assertFalse(result['dropInsAbsent'])
        self.assertEqual(result['status']['ExecMainStatus'],1)
        self.assertNotIn(secret,json.dumps(result))
        self.assertEqual(command.call_args.args[0],['/usr/bin/systemctl','show',unit,
            '--property='+','.join(diagnostics.UNIT_KEYS),'--no-pager'])

    def test_unit_unknown_fields_values_duplicate_or_out_of_range_are_unavailable(self):
        unit=diagnostics.UNITS[0]
        path='/etc/systemd/system/'+unit
        ledger=dict(paths={path:diagnostics._identity(info())},unitHashes={unit:hashlib.sha256(b'fixed-unit').hexdigest()})
        invalid=[unit_output(unit,Result='private-token'),unit_output(unit,ExecMainStatus='999'),
                 unit_output(unit,MainPID='9999999999'),unit_output(unit)+b'Private=secret\n',
                 unit_output(unit)+b'Result=success\n']
        for output in invalid:
            with patch.object(diagnostics.Path,'lstat',return_value=info()),patch.object(diagnostics,'_read',return_value=b'fixed-unit'),patch.object(diagnostics,'_executable'),patch.object(diagnostics,'_run',return_value=(0,output)):
                result=diagnostics._attempt(lambda:diagnostics._unit(unit,ledger))
            self.assertEqual(result,dict(observed=False,error='unavailable'))

    def pi_fixture(self,output,external=False):
        ledger=dict(paths={diagnostics.PI_ROOT:diagnostics._identity(info(stat.S_IFDIR|0o755))})
        secret='secret-private-output'
        def lookup(path):
            if str(path)==diagnostics.PI_ROOT:
                return info(stat.S_IFDIR|0o755)
            return info((stat.S_IFLNK|0o777) if external else stat.S_IFREG|0o644)
        with patch.object(diagnostics.Path,'lstat',lookup),patch.object(diagnostics,'_json',return_value=dict(name='@earendil-works/pi-coding-agent',version='1.0.4',auth=secret)),patch.object(diagnostics.os,'walk',return_value=[(diagnostics.PI_ROOT,[],['package-file'])]),patch.object(diagnostics.os,'readlink',return_value='/private/'+secret),patch.object(diagnostics,'_read',return_value=b'launcher'),patch.object(diagnostics,'LAUNCHER_SHA256',hashlib.sha256(b'launcher').hexdigest()),patch.object(diagnostics,'_executable'),patch.object(diagnostics,'_run',return_value=(0,output)) as command:
            result=diagnostics._pi(ledger)
        self.assertNotIn(secret,json.dumps(result))
        return result,command

    def test_pi_exact_version_only_and_no_external_link_execution(self):
        result,command=self.pi_fixture(b'1.0.4\n')
        self.assertTrue(result['executableMatchesPackage'])
        self.assertEqual(command.call_args.args[0],[diagnostics.PI_LAUNCHER,'--version'])
        result,command=self.pi_fixture(b'1.0.4\nsecret-private-output\n')
        self.assertFalse(result['executableVersionValid'])
        self.assertNotIn('executableVersion',result)
        result,command=self.pi_fixture(b'1.0.4\n',external=True)
        self.assertEqual(result['prefixTrustViolations']['externalLink'],1)
        command.assert_not_called()

    def test_version_subprocess_has_exact_native_env_without_home_or_secrets(self):
        process=SimpleNamespace(pid=314,returncode=None,stdout=SimpleNamespace(fileno=lambda:8))
        def wait(timeout):
            process.returncode=0
            return 0
        process.wait=wait
        with patch.dict(os.environ,{'HOME':'/private/home','PROVIDER_TOKEN':'secret'}),patch.object(diagnostics.subprocess,'Popen',return_value=process) as popen,patch.object(diagnostics.select,'select',return_value=([process.stdout],[],[])),patch.object(diagnostics.os,'read',side_effect=[b'1.0.4\n',b'']),patch.object(diagnostics.os,'killpg') as kill:
            self.assertEqual(diagnostics._run([diagnostics.PI_LAUNCHER,'--version']),(0,b'1.0.4\n'))
        self.assertEqual(popen.call_args.kwargs['env'],diagnostics.NATIVE_ENV)
        self.assertEqual(set(popen.call_args.kwargs['env']),{'PATH','LC_ALL','PI_CODING_AGENT_DIR'})
        self.assertEqual(popen.call_args.kwargs['stderr'],diagnostics.subprocess.DEVNULL)
        kill.assert_not_called()

    def test_command_output_bound_kills_only_its_substituted_process_group(self):
        process=SimpleNamespace(pid=314,returncode=None,stdout=SimpleNamespace(fileno=lambda:8),wait=lambda timeout:0)
        with patch.object(diagnostics.subprocess,'Popen',return_value=process),patch.object(diagnostics.select,'select',return_value=([process.stdout],[],[])),patch.object(diagnostics.os,'read',return_value=b'x'*4096),patch.object(diagnostics.os,'killpg') as kill:
            with self.assertRaises(diagnostics.Unavailable):
                diagnostics._run([diagnostics.PI_LAUNCHER,'--version'])
        kill.assert_called_once_with(314,diagnostics.signal.SIGKILL)

    def test_host_settings_and_lease_never_export_private_fields(self):
        secret='private-provider-token-and-task-body'
        manifest=dict(zip(('schema','channel','version','sourceCommit','installerProtocol','hostProtocol','extensionProtocol','piRPCVersion','os','arch','libc'),
                          (1,'linux-host-v1','v1.0.1-rc.2',diagnostics.SOURCE,1,'v1',1,'1.0.2','linux','amd64','glibc')),components=[])
        lease=dict(phase='sealed',ownerRequestId=secret,targetManifestSHA256=diagnostics._manifest_digest(manifest),token=secret)
        def read(path,*args):
            if path.endswith('stopped-lease.json'):
                return lease
            if path.endswith('install.json'):
                return dict(manifest=manifest,private=secret)
            if path.endswith('host.json'):
                return dict(diagnostics.HOST_FIELDS,projects={},nodes={},private=secret)
            return dict(lan=False,noAutoUpdate=True,noStats=True,auth=secret)
        with patch.object(diagnostics,'_json',side_effect=read):
            result=dict(host=diagnostics._host(),lease=diagnostics._lease(),settings=diagnostics._settings('/etc/awf/magpie-settings.json',0))
        self.assertTrue(result['host']['configurationMatches'])
        self.assertTrue(result['lease']['targetMatches'])
        self.assertNotIn(secret,json.dumps(result))
        self.assertNotIn('ownerRequestId',json.dumps(result))

    def test_collect_no_credentials_state_journal_or_real_command_and_continues_errors(self):
        runner=SimpleNamespace(ledger=dict(paths={},account=None))
        with patch.object(diagnostics.Path,'lstat',side_effect=PermissionError('private-path-and-token')),patch.object(diagnostics,'_json',side_effect=PermissionError('secret-body')) as read,patch.object(diagnostics.subprocess,'Popen') as command,patch.object(diagnostics.os,'open') as opened:
            result=diagnostics.collect(runner)
        command.assert_not_called()
        opened.assert_not_called()
        paths={call.args[0] for call in read.call_args_list}
        self.assertNotIn('/etc/awf/host.env',paths)
        self.assertFalse(any('auth' in path or 'state.json' in path or 'journal' in path for path in paths))
        encoded=json.dumps(result)
        self.assertLess(len(encoded),32768)
        self.assertNotIn('private-path-and-token',encoded)
        self.assertNotIn('secret-body',encoded)
        self.assertEqual(len(result['units']),2)
        self.assertTrue(result['metadataReadOnly'])
        self.assertTrue(result['noModels'])
        self.assertTrue(result['pi']['versionProbeMayCreateTemporarySettingsLock'])
        self.assertNotIn('readOnlyProbes',result)
        self.assertFalse(result['pi']['observed'])
        self.assertFalse(result['maintenanceLease']['observed'])

    def test_duplicate_json_keys_and_non_json_numbers_are_refused(self):
        for data in (b'{"lan":false,"lan":true}',b'{"lan":NaN}'):
            with patch.object(diagnostics,'_read',return_value=data):
                with self.assertRaises(diagnostics.Unavailable):
                    diagnostics._json('/etc/awf/magpie-settings.json')


if __name__=='__main__':
    unittest.main()
