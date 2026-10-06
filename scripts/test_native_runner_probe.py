#!/usr/bin/env python3
"""Guard and parser tests without root, machine changes or resource waiting."""
import contextlib
import copy
import io
import json
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import call, patch

import probe_native_runner as probe


class RunnerProbeTests(unittest.TestCase):
    def setUp(self):
        self.env=dict(GITHUB_ACTIONS='true',RUNNER_ENVIRONMENT='github-hosted',
                      RUNNER_OS='Linux',GITHUB_REPOSITORY=probe.REPOSITORY,
                      GITHUB_REF='refs/heads/'+probe.BRANCH,GITHUB_EVENT_NAME='push',
                      GITHUB_SHA='c'*40)

    def test_go_parent_predicate_distinguishes_write_bits_owner_and_type(self):
        info=SimpleNamespace(st_uid=0,st_gid=1234,st_mode=stat.S_IFDIR|0o755)
        self.assertTrue(probe.parent_predicate(info)['passed'])
        for uid,mode,failed in [
            (0,stat.S_IFDIR|0o777,{'noGroupWrite','noOtherWrite'}),
            (1001,stat.S_IFDIR|0o755,{'rootOwned'}),
            (0,stat.S_IFDIR|0o2755,{'noSetGID'}),
            (0,stat.S_IFDIR|0o4755,{'noSetUID'}),
            (0,stat.S_IFREG|0o755,{'directory'}),
            (0,stat.S_IFLNK|0o777,{'noGroupWrite','noOtherWrite','notPhysicalSymlink','directory'}),
        ]:
            with self.subTest(uid=uid,mode=oct(mode)):
                info.st_uid,info.st_mode=uid,mode
                result=probe.parent_predicate(info)
                self.assertFalse(result['passed'])
                self.assertEqual(set(result['failedPredicates']),failed)

    def test_diagnostics_keep_lstat_separate_and_do_not_expose_link_target(self):
        link=SimpleNamespace(st_uid=0,st_gid=42,st_mode=stat.S_IFLNK|0o777)
        directory=SimpleNamespace(st_uid=0,st_gid=0,st_mode=stat.S_IFDIR|0o755)
        with patch.object(probe,'Path') as paths:
            opt=paths.return_value
            opt.lstat.side_effect=[link,directory]
            opt.stat.return_value=directory
            opt.resolve.side_effect=['/private-target-never-report','/']
            report=probe.opt_parent_diagnostics()
            self.assertEqual([c.args[0] for c in paths.call_args_list],['/opt','/'])
            self.assertEqual(opt.method_calls,[call.lstat(),
                call.resolve(strict=True),call.stat(),
                call.lstat(),call.resolve(strict=True),call.stat()])
        row=report['paths'][0]
        self.assertTrue(row['lstat']['physicalSymlink'])
        self.assertFalse(row['stat']['physicalSymlink'])
        self.assertEqual(row['lstat']['gid'],42)
        self.assertEqual(row['lstat']['octalMode'],'0777')
        self.assertFalse(row['goParentTrustPredicate']['passed'])
        self.assertFalse(row['physicalPathMatchesRequestedPath'])
        self.assertNotIn('/private-target-never-report',json.dumps(report))
        self.assertFalse(report['mutationsPerformed'])

    def test_metadata_error_is_sanitized_and_does_not_skip_root(self):
        directory=SimpleNamespace(st_uid=0,st_gid=0,st_mode=stat.S_IFDIR|0o755)
        with patch.object(probe,'Path') as paths:
            paths.return_value.lstat.side_effect=[FileNotFoundError(2,'private-error-detail'),directory]
            paths.return_value.stat.return_value=directory
            paths.return_value.resolve.return_value='/'
            report=probe.opt_parent_diagnostics()
        self.assertEqual(report['paths'][0]['metadataError'],dict(type='FileNotFoundError',errno=2))
        self.assertTrue(report['paths'][1]['goParentTrustPredicate']['passed'])
        self.assertNotIn('private-error-detail',json.dumps(report))

    def test_all_source_parents_and_components_report_every_failure(self):
        names=probe.INSTALL_PARENTS+('/usr/bin','/usr/sbin')
        seen=[]
        def fixed(name):
            seen.append(name)
            mode=0o777 if name in ('/opt','/usr/local/bin') else 0o755
            uid=1001 if name=='/usr/local/bin' else 0
            info=SimpleNamespace(st_uid=uid,st_gid=0,st_mode=stat.S_IFDIR|mode)
            return SimpleNamespace(lstat=lambda:info,stat=lambda:info,resolve=lambda strict:name)
        with patch.object(probe,'Path',side_effect=fixed):
            report=probe.parent_diagnostics(names)
        expected={'/','/opt','/etc','/etc/systemd','/etc/systemd/system','/var','/var/lib','/var/cache',
                  '/usr','/usr/local','/usr/local/bin','/usr/bin','/usr/sbin'}
        self.assertEqual(set(seen),expected)
        self.assertEqual(len(seen),len(expected))
        failed={row['path']:set(row['failedPredicates']) for row in report['failedPaths']}
        self.assertEqual(failed,{'/opt':{'noGroupWrite','noOtherWrite'},
                                '/usr/local/bin':{'rootOwned','noGroupWrite','noOtherWrite'}})
        self.assertFalse(report['allParentsMeetGoTrustPredicate'])
        self.assertEqual(report['metadataErrors'],[])

    def test_all_fixed_conflicts_are_collected_without_parent_failfast(self):
        present={'/opt/node','/etc/awf','/root/.pi/agent'}
        info=SimpleNamespace(st_uid=0,st_gid=0,st_mode=stat.S_IFDIR|0o755)
        units=dict(units=[],conflicts=[dict(kind='loadedUnitOrOverrides',unit=u) for u in probe.UNITS],
                   metadataErrors=[dict(target=probe.UNITS[0],errorType='OSError')],passed=False)
        tcp='sl local_address rem_address st\n0: 0100007F:1B9E 00000000:0000 0A\n1: 00000000:0D61 00000000:0000 0A\n'
        def fixed_stat(path):
            if str(path) in present:
                return info
            raise FileNotFoundError(2,'fixture absent')
        with patch.object(probe.Path,'lstat',autospec=True,side_effect=fixed_stat), \
             patch.object(probe.Path,'read_text',side_effect=[tcp,'sl local_address rem_address st\n']), \
             patch.object(probe.pwd,'getpwnam',return_value=SimpleNamespace(pw_dir='/root')), \
             patch.object(probe.grp,'getgrnam',return_value=SimpleNamespace()), \
             patch.object(probe.shutil,'which',side_effect=lambda name,path:'/usr/local/bin/pi' if name=='pi' else None), \
             patch.object(probe,'unit_diagnostics',return_value=units):
            report=probe.object_diagnostics()
        self.assertEqual(len(report['fixedPaths']),len(probe.FIXED_PATHS))
        kinds=[r['kind'] for r in report['conflicts']]
        self.assertEqual(kinds.count('existingFixedPath'),2)
        self.assertIn('existingAWFAccount',kinds)
        self.assertIn('existingAWFGroup',kinds)
        self.assertIn('rootPiAgentExists',kinds)
        self.assertIn('existingCommand',kinds)
        self.assertEqual(kinds.count('loadedUnitOrOverrides'),2)
        self.assertEqual(kinds.count('occupiedPort'),2)
        self.assertFalse(report['passed'])
        self.assertFalse(report['mutationsPerformed'])

    def test_one_unreadable_unit_does_not_hide_the_other(self):
        with patch.object(probe,'trusted'),patch.object(probe,'UNIT_PATHS',()), \
             patch.object(probe,'run',side_effect=[OSError('private-error-detail'),
                 'LoadState=not-found\nFragmentPath=\nDropInPaths=\n']) as command:
            report=probe.unit_diagnostics()
        self.assertEqual(command.call_count,2)
        self.assertEqual(report['units'][0]['unit'],probe.UNITS[1])
        self.assertFalse(report['passed'])
        self.assertNotIn('private-error-detail',json.dumps(report))

    def test_unreadable_fixed_object_is_unknown_and_later_objects_still_collected(self):
        def fixed_stat(path):
            if str(path)=='/opt/node':
                raise PermissionError(13,'private-error-detail')
            if str(path)=='/opt/pi-cli':
                return SimpleNamespace(st_uid=0,st_gid=0,st_mode=stat.S_IFDIR|0o755)
            raise FileNotFoundError(2,'fixture absent')
        def lookup(name):
            if name=='root':
                return SimpleNamespace(pw_dir='/root')
            raise KeyError(name)
        with patch.object(probe.Path,'lstat',autospec=True,side_effect=fixed_stat), \
             patch.object(probe.Path,'read_text',return_value='sl local_address rem_address st\n'), \
             patch.object(probe.pwd,'getpwnam',side_effect=lookup), \
             patch.object(probe.grp,'getgrnam',side_effect=KeyError),patch.object(probe.shutil,'which',return_value=None), \
             patch.object(probe,'unit_diagnostics',return_value={'units':[],'conflicts':[],'metadataErrors':[],'passed':True}):
            report=probe.object_diagnostics()
        rows={row['path']:row for row in report['fixedPaths']}
        self.assertIsNone(rows['/opt/node']['present'])
        self.assertTrue(rows['/opt/pi-cli']['present'])
        self.assertFalse(rows['/opt/awf']['present'])
        self.assertFalse(report['passed'])
        self.assertNotIn('private-error-detail',json.dumps(report))

    def test_bad_unit_entry_does_not_hide_later_conflicts_in_same_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp)
            (directory/'bad.wants').write_text('fixture file instead of directory')
            (directory/'awf-host.service').write_text('fixture')
            (directory/'awf-magpie.service.d').mkdir()
            with patch.object(probe,'trusted'),patch.object(probe,'UNIT_PATHS',(temp,)), \
                 patch.object(probe,'run',return_value='LoadState=not-found\nFragmentPath=\nDropInPaths=\n'):
                report=probe.unit_diagnostics()
        paths={row['path'] for row in report['conflicts']}
        self.assertIn(str(directory/'awf-host.service'),paths)
        self.assertIn(str(directory/'awf-magpie.service.d'),paths)
        self.assertEqual(report['metadataErrors'][0]['target'],str(directory/'bad.wants'))
        self.assertFalse(report['passed'])

    def test_non_hosted_pr_or_unapproved_branch_is_refused(self):
        probe.ci_guard(self.env,0,0)
        for key,value in [('RUNNER_ENVIRONMENT','self-hosted'),('GITHUB_EVENT_NAME','pull_request'),
                          ('GITHUB_REF','refs/heads/main'),('GITHUB_REPOSITORY','foreign/repo'),
                          ('GITHUB_SHA','bad'),('RUNNER_OS','Windows')]:
            env=copy.deepcopy(self.env)
            env[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                probe.ci_guard(env,0,0)
        for uid,euid in [(1000,0),(0,1000),(1000,1000)]:
            with self.assertRaises(ValueError):
                probe.ci_guard(self.env,uid,euid)

    def test_refusal_precedes_all_host_reads_and_resource_waiting(self):
        with patch('sys.argv',['probe','--expected-release','24.04']), \
             patch.dict(probe.os.environ,{},clear=True), \
             patch.object(probe,'inspect') as inspect, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(probe.main(),2)
            inspect.assert_not_called()
            self.assertIn('"nativeInstallationPerformed": false',output.getvalue())

    def test_full_60_second_memory_window_is_required(self):
        sample=dict(availableBytes=512<<20,swapUsedBytes=0,fullPSIAvg10Percent=0.0)
        samples=[copy.deepcopy(sample) for _ in range(probe.RESOURCE_SAMPLES)]
        probe.resource_gate(samples)
        with self.assertRaisesRegex(ValueError,'complete'):
            probe.resource_gate(samples[:-1])
        samples[15]['availableBytes']-=1
        with self.assertRaisesRegex(ValueError,'512 MiB'):
            probe.resource_gate(samples)

    def test_pressure_never_becomes_an_install_or_code_failure(self):
        samples=[dict(availableBytes=600<<20,fullPSIAvg10Percent=0.0) for _ in range(probe.RESOURCE_SAMPLES)]
        samples[10]['fullPSIAvg10Percent']=11.0
        with self.assertRaisesRegex(ValueError,'resource gate failed'):
            probe.resource_gate(samples)

    def test_memory_and_pressure_units_are_checked(self):
        text='MemAvailable: 524288 kB\nSwapTotal: 1024 kB\nSwapFree: 512 kB\n'
        sample=probe.memory_sample(text,'some avg10=0.1\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=0\n')
        self.assertEqual(sample['availableBytes'],512<<20)
        self.assertEqual(sample['swapUsedBytes'],512<<10)
        for changed in (text.replace('kB','MB'),text.replace('SwapFree: 512','SwapFree: 2048')):
            with self.assertRaises(ValueError):
                probe.memory_sample(changed,'full avg10=0.00')
        with self.assertRaises(ValueError):
            probe.memory_sample(text,'full avg10=nan')

    def test_ipv4_and_ipv6_busy_ports_are_not_adopted(self):
        header='sl local_address rem_address st\n'
        rows='0: 0100007F:1B9E 00000000:0000 0A\n1: 00000000:0D61 00000000:0000 0A\n2: 0100007F:1234 00000000:0000 0A\n'
        found=probe.listeners(header+rows)
        self.assertEqual([r['port'] for r in found],[7070,3425])
        self.assertTrue(found[0]['fixedIPv4Loopback'])
        self.assertFalse(found[1]['fixedIPv4Loopback'])
        ipv6=probe.listeners(header+'0: '+('0'*32)+':1B9E '+('0'*32)+':0000 0A\n',True)
        self.assertEqual(ipv6[0]['port'],7070)
        self.assertFalse(ipv6[0]['fixedIPv4Loopback'])

    def test_mount_selection_uses_path_boundaries(self):
        text='1 0 8:1 / / rw,relatime - ext4 /dev/sda rw\n2 1 0:1 / /tmp rw,nosuid - tmpfs tmpfs rw\n3 1 0:2 / /sys/fs/cgroup rw - cgroup2 cgroup rw\n'
        rows=probe.mount_records(text)
        self.assertEqual(probe.mount_for(rows,'/tmp')['fs'],'tmpfs')
        self.assertEqual(probe.mount_for(rows,'/tmp-suffix')['fs'],'ext4')
        self.assertEqual(probe.mount_for(rows,'/sys/fs/cgroup')['fs'],'cgroup2')

    def test_non_root_cgroup_memory_events_path(self):
        self.assertEqual(probe.self_cgroup('0::/system.slice/runner.service\n'),Path('/sys/fs/cgroup/system.slice/runner.service'))
        for text in ('0::/../../tmp\n','0:://tmp\n','0::/a/./b\n','0::/a\n0::/b\n','1:name=/bad\n'):
            with self.subTest(text=text),self.assertRaises(ValueError):
                probe.self_cgroup(text)


if __name__=='__main__':
    unittest.main()
