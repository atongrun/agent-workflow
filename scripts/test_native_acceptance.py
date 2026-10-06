#!/usr/bin/env python3
"""Meaningful native-harness boundary tests with no root/system mutation."""
import copy
import contextlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock
from types import SimpleNamespace

import native_acceptance as native


class NativeHarnessTests(unittest.TestCase):
    def test_diagnostic_mode_never_enters_native_code_even_on_pass(self):
        for passed in (True,False):
            with self.subTest(preflightPassed=passed), \
                 patch('sys.argv',['native','--expected-release','24.04','--report','/tmp/report.json','--diagnostic-only']), \
                 patch.dict(native.os.environ,{'GITHUB_SHA':'c'*40},clear=True), \
                 patch.object(native.probe,'ci_guard'), \
                 patch.object(native.probe,'inspect',return_value={'preflightPassed':passed,'nativeInstallationPerformed':False}), \
                 patch.object(native,'CONTROL') as control, \
                 patch.object(native,'Acceptance') as acceptance, \
                 patch.object(native,'capture_existing_runtime') as baseline, \
                 patch.object(native.probe,'run') as command, \
                 patch.object(native.urllib.request,'urlopen') as download, \
                 patch.object(native,'report_write') as save, \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(native.main(),0 if passed else 1)
                self.assertEqual(control.method_calls,[])
                acceptance.assert_not_called()
                baseline.assert_not_called()
                command.assert_not_called()
                download.assert_not_called()
                save.assert_called_once()
                report=save.call_args.args[1]
                self.assertTrue(report['diagnosticOnly'])
                self.assertFalse(report['acceptancePassed'])
                self.assertFalse(report['preflight']['nativeInstallationPerformed'])
                self.assertEqual(report['stages'],[])
                self.assertEqual(report['healthRounds'],[])
                self.assertEqual(report['cleanup'],dict(passed=True,noSystemMutation=True))

    def test_diagnostic_and_cleanup_modes_cannot_be_combined(self):
        with patch('sys.argv',['native','--expected-release','24.04','--report','/tmp/report.json','--diagnostic-only','--cleanup-only']), \
             patch.object(native.probe,'ci_guard'), \
             patch.object(native.probe,'inspect') as inspect, \
             patch.object(native,'CONTROL') as control:
            with self.assertRaisesRegex(native.TestFailure,'exclusive'):
                native.main()
            inspect.assert_not_called()
            self.assertEqual(control.method_calls,[])

    def runner(self,ledger):
        runner=native.Acceptance.__new__(native.Acceptance)
        runner.report={}
        runner.ledger=ledger
        runner.observe=lambda:None
        return runner

    def test_only_nine_immutable_public_assets(self):
        self.assertEqual(set(native.PINS),set(native.package.NAMES))
        for version,pins in native.PINS_BY_VERSION.items():
            self.assertEqual(len(pins),9)
            self.assertIn('awf_'+version+'_linux_amd64.tar.gz',pins)
            self.assertTrue(all(isinstance(size,int) and len(sha)==64 for size,sha in pins.values()))
        self.assertNotIn('private.zip',native.PINS)

    def test_changed_inode_stops_cleanup_before_any_deletion(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)/'owned'
            base.mkdir()
            saved=native.identity(base)
            base.rename(base.with_name('moved'))
            base.mkdir()
            ledger=dict(paths={str(base):saved},account=None,group=None,scratchBefore={temp:[]})
            runner=self.runner(ledger)
            with patch.object(native.probe,'run',return_value=''),patch.object(native.shutil,'rmtree') as remove:
                with self.assertRaisesRegex(native.TestFailure,'inode/device/type changed'):
                    runner.cleanup()
                remove.assert_not_called()

    def test_foreign_owner_prevents_recursive_removal(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)/'owned'
            base.mkdir()
            with self.assertRaisesRegex(native.TestFailure,'foreign ownership'):
                native.safe_tree(base,{os.getuid()+12345:os.getgid()+12345})

    def test_special_file_prevents_recursive_removal(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)/'owned'
            base.mkdir()
            os.mkfifo(base/'fifo')
            with self.assertRaisesRegex(native.TestFailure,'special file'):
                native.safe_tree(base,{os.getuid():os.getgid()})

    def test_matching_path_outside_ledger_scope_is_not_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)/'unknown'
            base.mkdir()
            runner=self.runner(dict(paths={str(base):native.identity(base)},account=None,group=None,scratchBefore={}))
            with patch.object(native.probe,'run',return_value=''),patch.object(native.shutil,'rmtree') as remove:
                with self.assertRaisesRegex(native.TestFailure,'outside ledger scope'):
                    runner.cleanup()
                remove.assert_not_called()

    def test_private_ledger_has_no_group_other_access(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'ledger.json'
            native.private_file(path,{'account':None})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)

    def test_orphaned_interrupted_save_does_not_block_ledger_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'ledger.json'
            native.private_file(path,{'paths':{}})
            orphan=path.with_name('ledger.json.new')
            orphan.write_text('{incomplete')
            native.private_file(path,{'paths':{'fixed':{'ino':1}}})
            self.assertEqual(json.loads(path.read_text())['paths']['fixed']['ino'],1)
            self.assertEqual(orphan.read_text(),'{incomplete')
            native.private_file(path,{'account':{'uid':12345}})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)

    def test_changed_unit_blocks_stop_before_any_systemctl_mutation(self):
        runner=self.runner(dict(paths={'/etc/systemd/system/awf-host.service':{}},unitHashes={}))
        with patch.object(native,'same',return_value=False),patch.object(native.probe,'run') as command:
            with self.assertRaisesRegex(native.TestFailure,'unit ledger identity changed'):
                runner.trusted_unit('awf-host.service')
            command.assert_not_called()

    def test_report_rejects_symlink_output(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'existing'
            target.write_text('preserved')
            link=Path(temp)/'report.json'
            link.symlink_to(target)
            with self.assertRaisesRegex(native.TestFailure,'report path invalid'):
                native.report_write(link,{'acceptancePassed':False})
            self.assertEqual(target.read_text(),'preserved')

    def test_bootstrap_uses_public_manifest_and_archive(self):
        assets=Path('/tmp/private/assets')
        for version,bootstrap in [('v1.0.1-rc.2','install-linux.sh'),('v1.0.1-rc.3','channel-install-linux.sh')]:
            with patch.object(native.probe,'RELEASE',version):
                args=native.install_args(assets)
            self.assertNotIn('--manifest',args)
            self.assertNotIn('--archive',args)
            self.assertIn(str(assets/bootstrap),args)
            self.assertIn('--allow-prerelease',args)

    def test_manifest_digest_is_independent_of_channel_json_key_order(self):
        manifest=dict(schema=1,channel='linux-host-v1',version='v1.0.1-rc.3',sourceCommit=native.probe.SOURCE,
            installerProtocol=1,hostProtocol='v1',extensionProtocol=1,piRPCVersion='1.0.2',os='linux',arch='amd64',libc='glibc',
            components=[dict(id='awf-host',version='v1.0.1-rc.3',artifacts=[dict(name='fixture.tar.gz',url='https://github.com/fixture',sha256='f'*64,bytes=1,format='tar.gz')])])
        shuffled={key:manifest[key] for key in reversed(manifest)}
        self.assertEqual(native.manifest_digest(manifest),native.manifest_digest(shuffled))

    def test_noop_uses_genuine_bare_command_and_blocks_service_restart(self):
        runner=self.runner({})
        runner.health=lambda _:None
        runner.command=lambda name,args,*_: self.assertEqual(args,['/usr/local/bin/awf','update']) or b'AWF bundle verify-current: completed\nAWF v1.0.1-rc.3 verified.'
        with patch.object(native,'identity',return_value={'ino':123}),patch.object(native,'tree_fingerprint',return_value='fixture bytes'),patch.object(native.Path,'read_bytes',return_value=b'fixture receipt'),patch.object(native,'unit_status',side_effect=[{'MainPID':'123'},{'MainPID':'124'},{'MainPID':'999'},{'MainPID':'124'}]),patch.object(native.os.path,'lexists',return_value=False):
            with self.assertRaisesRegex(native.TestFailure,'restarted services'):
                runner.verify_default_noop()
        self.assertNotIn('noOp',runner.report)

    def test_upgrade_records_all_old_backup_identities_before_execution(self):
        paths={'/opt/node':{'ino':1},'/opt/awf':{'ino':2},'/opt/magpie':{'ino':3}}
        runner=self.runner(dict(paths=paths,transitions=[]))
        saves=[]
        runner.save=lambda:saves.append(copy.deepcopy(runner.ledger))
        target=dict(version=native.TARGET_VERSION,sourceCommit=native.probe.SOURCE)
        with patch.object(native,'manifest_digest',return_value='d'*64),patch.object(native,'same',return_value=True),patch.object(native.os.path,'lexists',return_value=False):
            runner.begin_replacement(target)
        self.assertEqual(len(saves),1)
        roots=saves[0]['transitions'][0]['roots']
        self.assertEqual([row['oldIdentity'] for row in roots],list(paths.values()))
        self.assertEqual([row['backup'] for row in roots],[path+'.before-'+'d'*64 for path in paths])
        self.assertFalse(saves[0]['transitions'][0]['completed'])
        self.assertEqual(saves[0]['paths'],paths)

    def test_existing_backup_cannot_be_adopted_for_upgrade(self):
        runner=self.runner(dict(paths={p:{} for p in ('/opt/node','/opt/awf','/opt/magpie')},transitions=[]))
        with patch.object(runner,'save') as save,patch.object(native,'manifest_digest',return_value='d'*64),patch.object(native,'same',return_value=True),patch.object(native.os.path,'lexists',return_value=True):
            with self.assertRaisesRegex(native.TestFailure,'no adoption'):
                runner.begin_replacement(dict(version=native.TARGET_VERSION,sourceCommit=native.probe.SOURCE))
        save.assert_not_called()
        self.assertEqual(runner.ledger['transitions'],[])

    def test_failed_upgrade_never_adopts_new_roots_from_receipt(self):
        runner=self.runner(dict(paths={'/opt/awf':{'ino':1}},transitions=[dict(target={},roots=[],completed=False)]))
        with patch.object(native.Path,'read_text',return_value='{"manifest":{"changed":true}}'),patch.object(runner,'save') as save:
            with self.assertRaisesRegex(native.TestFailure,'immutable target'):
                runner.finish_replacement()
        save.assert_not_called()
        self.assertEqual(runner.ledger['paths'],{'/opt/awf':{'ino':1}})

    def test_incomplete_duplicate_or_extra_runtime_inventory_never_adopted(self):
        ids=('node','pi','awf-host','awf-extension','magpie')
        target={'components':[{'id':cid,'version':'fixture'} for cid in ids]}
        file_paths={'node':'opt/node/node','awf-host':'opt/awf/awf','awf-extension':'opt/awf/extension.ts','magpie':'opt/magpie/magpie'}
        original=[dict(id=cid,version='fixture',files=[dict(path=file_paths[cid],mode=0o644,bytes=1,sha256='f'*64)] if cid!='pi' else []) for cid in ids]
        for kind in ('empty','missing','duplicate-component','duplicate-path','empty-files','extra-tree-file'):
            components=copy.deepcopy(original)
            if kind=='empty': components=[]
            if kind=='missing': components.pop()
            if kind=='duplicate-component': components[-1]=components[0]
            if kind=='duplicate-path': components[0]['files']*=2
            if kind=='empty-files': components[0]['files']=[]
            paths={p:{'ino':i} for i,p in enumerate(('/opt/node','/opt/awf','/opt/magpie'))}
            roots=[dict(path=p,backup=p+'.before-'+'d'*64,oldIdentity=saved) for p,saved in paths.items()]
            transition=dict(target=target,roots=roots,completed=False)
            runner=self.runner(dict(paths=copy.deepcopy(paths),transitions=[transition]))
            receipt=dict(manifest=target,programsInstalled=True,preparation=dict(manifestSHA256='d'*64,components=components))
            extra=['unclaimed'] if kind=='extra-tree-file' else []
            actual=[('/opt/node',[],['node']+extra),('/opt/awf',[],['awf','extension.ts']),('/opt/magpie',[],['magpie'])]
            with self.subTest(kind=kind),patch.object(native.Path,'read_text',return_value=json.dumps(receipt)),patch.object(native,'same',side_effect=lambda path,_:'.before-' in str(path)),patch.object(native.os.path,'lexists',return_value=False),patch.object(native,'manifest_digest',return_value='d'*64),patch.object(native,'safe_tree'),patch.object(native,'identity',return_value={'ino':999}),patch.object(native.Path,'lstat',return_value=SimpleNamespace(st_mode=stat.S_IFREG|0o644,st_size=1)),patch.object(native.Path,'is_symlink',return_value=False),patch.object(native.Path,'is_file',return_value=True),patch.object(native.package,'digest_file',return_value='f'*64),patch.object(native.os,'walk',return_value=actual),patch.object(runner,'save') as save:
                with self.assertRaises(native.TestFailure):
                    runner.finish_replacement()
            save.assert_not_called()
            self.assertEqual(runner.ledger['paths'],paths)
            self.assertFalse(transition['completed'])

    def test_pi_execution_marker_survives_nonzero_exit(self):
        runner=self.runner({})
        runner.report={'stages':[],'piUpdateExecuted':False}
        runner.deadline=native.time.monotonic()+120
        runner.resources=lambda:None
        process=Mock(returncode=1)
        process.poll.return_value=1
        with tempfile.TemporaryDirectory() as temp,patch.object(native,'CONTROL',Path(temp)),patch.object(native.subprocess,'Popen',return_value=process),contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(native.TestFailure,'stage failed: pi-update'):
                runner.command('pi-update',['/usr/local/bin/pi','update'],30)
        self.assertTrue(runner.report['piUpdateExecuted'])
        self.assertTrue(runner.report['piUpdate']['executionStarted'])
        self.assertFalse(runner.report['piUpdate']['passed'])

    def test_pi_execution_marker_survives_timeout(self):
        runner=self.runner({})
        runner.report={'stages':[],'piUpdateExecuted':False}
        runner.deadline=120
        runner.resources=lambda:None
        process=Mock(pid=12345,returncode=1)
        process.poll.side_effect=[None,1]
        with tempfile.TemporaryDirectory() as temp,patch.object(native,'CONTROL',Path(temp)),patch.object(native.subprocess,'Popen',return_value=process),patch.object(native.time,'monotonic',side_effect=[0,31]),patch.object(native.os,'killpg'),contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(native.TestFailure,'stage timeout: pi-update'):
                runner.command('pi-update',['/usr/local/bin/pi','update'],30)
        self.assertTrue(runner.report['piUpdateExecuted'])
        self.assertTrue(runner.report['piUpdate']['executionStarted'])
        self.assertFalse(runner.report['piUpdate']['passed'])

    def test_noop_cannot_claim_program_bytes_preserved_after_inplace_change(self):
        runner=self.runner({})
        runner.command=lambda *_:b'AWF bundle verify-current: completed\nAWF v1.0.1-rc.3 verified.'
        with patch.object(native,'identity',return_value={'ino':123}),patch.object(native,'tree_fingerprint',side_effect=['same']*4+['changed']+['same']*3),patch.object(native.Path,'read_bytes',return_value=b'fixture receipt'),patch.object(native,'unit_status',return_value={'MainPID':'123'}):
            with self.assertRaisesRegex(native.TestFailure,'changed program contents'):
                runner.verify_default_noop()
        self.assertNotIn('noOp',runner.report)

    def test_cleanup_does_not_adopt_late_scratch_or_call_observe(self):
        runner=self.runner(dict(paths={},account=None,group=None,initialRuntime={},scratchBefore={'/tmp':[],'/opt':[]}))
        runner.observe=lambda:self.fail('cleanup must consume its existing ledger')
        with patch.object(native.probe,'run',return_value=''),patch.object(native,'capture_existing_runtime',return_value={}), \
             patch.object(native.Path,'glob',return_value=iter([Path('/tmp/awf-linux-install-unproven')])):
            with self.assertRaisesRegex(native.TestFailure,'no glob cleanup'):
                runner.cleanup()
        self.assertEqual(runner.ledger['paths'],{})

    def test_awf_failure_diagnostic_exports_only_exact_static_lines(self):
        with tempfile.TemporaryDirectory() as temp:
            log=Path(temp)/'failure.log'
            secret='synthetic-private-token'
            log.write_text('x'*70000+'\n'+secret+'\ncurrent Pi package and executable version disagree\n'+
                           'current Pi package and executable version disagree '+secret+'\n'+
                           'AWF bundle service-start: started\nAWF awf-host health: failed\n'+
                           'AWF bundle service-start: failed '+secret+'\n')
            result=native.awf_failure_diagnostic(log)
        self.assertEqual(result['errorCodes'],['pi_executable_identity_disagrees'])
        self.assertEqual(result['progress'],[dict(component='bundle',stage='service-start',state='started'),dict(component='awf-host',stage='health',state='failed')])
        self.assertNotIn(secret,json.dumps(result))
        self.assertNotIn('current Pi',json.dumps(result))

    def test_awf_failure_diagnostic_does_not_export_unknown_output(self):
        with tempfile.TemporaryDirectory() as temp:
            log=Path(temp)/'failure.log'
            log.write_text('secret=/private/credential\nHTTP upstream response private-body\n')
            self.assertEqual(native.awf_failure_diagnostic(log),dict(errorCodes=['unclassified'],progress=[]))

    def test_failure_unit_status_never_queries_an_unrecorded_or_changed_unit(self):
        runner=self.runner(dict(paths={native.UNIT_FILES[0]:{'ino':1}}))
        with patch.object(native,'same',return_value=False),patch.object(native.probe,'run') as run:
            result=runner.failure_unit_status()
        run.assert_not_called()
        self.assertEqual(result,[dict(unit=u,observed=False) for u in native.probe.UNITS])

    def test_failed_restart_records_diagnostic_without_replacing_the_original_failure(self):
        runner=self.runner(dict(paths={}))
        runner.report={'stages':[]}
        runner.deadline=float('inf')
        process=SimpleNamespace(returncode=1,poll=lambda:1)
        def launch(*args,**kwargs):
            kwargs['stdout'].write(b'native command systemctl failed\nprivate-body-token\n')
            kwargs['stdout'].flush()
            return process
        with tempfile.TemporaryDirectory() as temp,patch.object(native,'CONTROL',Path(temp)),patch.object(native.subprocess,'Popen',side_effect=launch),patch.object(native.probe,'run') as command,contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(native.TestFailure,'stage failed: start-after-pi'):
                runner.command('start-after-pi',['/usr/local/bin/awf','start'],30)
        command.assert_not_called()
        self.assertEqual(runner.report['stages'][0]['exitCode'],1)
        self.assertEqual(runner.report['awfFailureDiagnostic']['errorCodes'],['systemctl_failed'])
        self.assertNotIn('private-body-token',json.dumps(runner.report))

    def test_cleanup_report_preserves_bounded_failure_diagnostic(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'report.json'
            payload=dict(sourceCommit=native.probe.SOURCE,workflowCommit='c'*40,
                         awfFailureDiagnostic=dict(errorCodes=['systemctl_failed'],progress=[]))
            path.write_text(json.dumps(payload))
            with patch.dict(native.os.environ,{'GITHUB_SHA':'c'*40}),patch.object(native.Path,'lstat',return_value=SimpleNamespace(st_mode=stat.S_IFREG|0o644,st_uid=0)):
                result=native.previous_report(path,{})
        self.assertEqual(result['awfFailureDiagnostic'],payload['awfFailureDiagnostic'])

    def test_failure_unit_status_rejects_unknown_values_and_only_reads_fixed_units(self):
        runner=self.runner(dict(paths={p:{'ino':1} for p in native.UNIT_FILES}))
        valid='LoadState=loaded\nActiveState=failed\nSubState=failed\nResult=exit-code\nMainPID=0\n'
        with patch.object(native,'same',return_value=True),patch.object(native.probe,'run',side_effect=[valid,valid.replace('exit-code','synthetic-private-token')]) as run:
            result=runner.failure_unit_status()
        self.assertTrue(result[0]['observed'])
        self.assertEqual(result[0]['status']['Result'],'exit-code')
        self.assertFalse(result[1]['observed'])
        self.assertNotIn('synthetic-private-token',json.dumps(result))
        self.assertEqual([c.args for c in run.call_args_list],[('/usr/bin/systemctl','show',u,'--property=LoadState,ActiveState,SubState,Result,MainPID','--no-pager') for u in native.probe.UNITS])

    def test_truncated_public_report_cannot_block_private_ledger_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'report.json'
            path.write_text('{"acceptancePassed":')
            with patch.object(native.Path,'lstat',return_value=type('Info',(),{'st_mode':stat.S_IFREG|0o644,'st_uid':0})()):
                report=native.previous_report(path,{'acceptancePassed':False})
            self.assertFalse(report['acceptancePassed'])
            self.assertIn('cleanup uses private ledger',report['failure'])
            runner=self.runner(dict(paths={},account=None,group=None,initialRuntime={},scratchBefore={'/tmp':[],'/opt':[]}))
            runner.report=report
            with patch.object(native.probe,'run',return_value=''),patch.object(native,'capture_existing_runtime',return_value={}), \
                 patch.object(native.Path,'glob',return_value=iter([])):
                runner.cleanup()
            self.assertTrue(report['cleanup']['passed'])


if __name__=='__main__':
    unittest.main()
