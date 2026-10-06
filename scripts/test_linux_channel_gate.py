#!/usr/bin/env python3
"""Publication readiness, denial and artifact naming boundaries; no network."""
import hashlib
import contextlib
import io
from pathlib import Path
import re
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

import wait_linux_channel as channel


class ChannelGateTests(unittest.TestCase):
    def test_unpublished_channel_waits_but_denials_never_retry(self):
        for status in (404,403,401):
            opener=Mock()
            opener.open.side_effect=HTTPError(channel.URL,status,'fixture',{},None)
            if status==404:
                self.assertFalse(channel.ready(opener))
            else:
                with self.assertRaises(HTTPError):
                    channel.ready(opener)
            opener.open.assert_called_once_with(channel.URL,timeout=15)

    def test_only_complete_exact_candidate_bytes_are_ready(self):
        wanted=b'fixture metadata'
        for data in (wanted,wanted+b'extra',b'changed metadata'):
            response=io.BytesIO(data)
            opener=Mock()
            opener.open.return_value=response
            with patch.object(channel,'SIZE',len(wanted)),patch.object(channel,'SHA256',hashlib.sha256(wanted).hexdigest()):
                if data==wanted:
                    self.assertTrue(channel.ready(opener))
                else:
                    with self.assertRaises(ValueError):
                        channel.ready(opener)

    def test_artifact_names_remain_valid_for_both_real_slash_branches(self):
        workflow=Path(__file__).parent.parent.joinpath('.github/workflows/linux-upgrade-acceptance.yml').read_text()
        names=re.findall(r'^\s+name: (linux-(?:upgrade|default)-[^\n]+)$',workflow,re.MULTILINE)
        self.assertEqual(len(names),2)
        for branch in ('awf/linux-pi-umask-native-ci-v1','awf/linux-default-ci-v1'):
            for value in names:
                value=value.replace('${{ github.sha }}','c'*40).replace('${{ github.ref_name }}',branch)
                self.assertFalse(re.search(r'["<>:|*?\r\n\\/]',value),value)

    def test_last_request_uses_only_remaining_time_and_never_sleeps_after_deadline(self):
        with patch.object(channel.urllib.request,'build_opener',return_value='fixture'),patch.object(channel.time,'monotonic',side_effect=[0,599,600]),patch.object(channel,'ready',return_value=False) as ready,patch.object(channel.time,'sleep') as sleep,contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError,'default phase not executed'):
                channel.main()
        ready.assert_called_once_with('fixture',1)
        sleep.assert_not_called()

    def test_no_request_starts_after_deadline(self):
        with patch.object(channel.urllib.request,'build_opener',return_value='fixture'),patch.object(channel.time,'monotonic',side_effect=[0,600]),patch.object(channel,'ready') as ready,contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):
                channel.main()
        ready.assert_not_called()

    def test_single_vm_workflow_env_and_artifact_names_are_safe(self):
        workflow=Path(__file__).parent.parent.joinpath('.github/workflows/linux-upgrade-acceptance.yml').read_text()
        # Job env cannot use the runner context; reject before allocating a VM.
        environment=workflow.split('    env:\n',1)[1].split('    steps:',1)[0]
        self.assertNotIn('${{ runner.',environment)
        self.assertIn('EVIDENCE: /tmp/awf-pi-umask-acceptance',environment)
        names=re.findall(r'^\s+name: (linux-(?:upgrade|default)-[^\n]+)$',workflow,re.MULTILINE)
        self.assertEqual(len(names),2)
        for name in names:
            self.assertFalse(re.search(r'["<>:|*?\r\n\\/]',name.replace('${{ github.sha }}','c'*40)))


if __name__=='__main__':
    unittest.main()
