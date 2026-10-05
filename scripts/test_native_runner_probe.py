#!/usr/bin/env python3
"""Guard and parser tests without root, machine changes or resource waiting."""
import contextlib
import copy
import io
from pathlib import Path
import unittest
from unittest.mock import patch

import probe_native_runner as probe


class RunnerProbeTests(unittest.TestCase):
    def setUp(self):
        self.env=dict(GITHUB_ACTIONS='true',RUNNER_ENVIRONMENT='github-hosted',
                      RUNNER_OS='Linux',GITHUB_REPOSITORY=probe.REPOSITORY,
                      GITHUB_REF='refs/heads/'+probe.BRANCH,GITHUB_EVENT_NAME='push',
                      GITHUB_SHA='c'*40)

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
