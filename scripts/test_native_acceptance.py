#!/usr/bin/env python3
"""Meaningful native-harness boundary tests with no root/system mutation."""
import copy
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

import native_acceptance as native


class NativeHarnessTests(unittest.TestCase):
    def runner(self,ledger):
        runner=native.Acceptance.__new__(native.Acceptance)
        runner.report={}
        runner.ledger=ledger
        runner.observe=lambda:None
        return runner

    def test_only_nine_immutable_public_assets(self):
        self.assertEqual(set(native.PINS),set(native.package.NAMES))
        known=json.loads(Path('/workspace/awf-contract-evidence/public-test-release-v1.0.1-rc.1/github-snapshot.json').read_text()) if Path('/workspace/awf-contract-evidence/public-test-release-v1.0.1-rc.1/github-snapshot.json').exists() else None
        if known:
            for row in known['release']['assets']:
                self.assertEqual(native.PINS[row['name']],(row['size'],row['digest'].removeprefix('sha256:')))
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

    def test_bootstrap_executes_only_the_pinned_manifest_and_host(self):
        assets=Path('/tmp/private/assets')
        args=native.install_args(assets)
        self.assertEqual(args[args.index('--manifest')+1],str(assets/'linux-host-v1.json'))
        self.assertEqual(args[args.index('--archive')+1],str(assets/native.package.NAMES[0]))
        self.assertIn('--allow-prerelease',args)

    def test_cleanup_does_not_adopt_late_scratch_or_call_observe(self):
        runner=self.runner(dict(paths={},account=None,group=None,initialRuntime={},scratchBefore={'/tmp':[],'/opt':[]}))
        runner.observe=lambda:self.fail('cleanup must consume its existing ledger')
        with patch.object(native.probe,'run',return_value=''),patch.object(native,'capture_existing_runtime',return_value={}), \
             patch.object(native.Path,'glob',return_value=iter([Path('/tmp/awf-linux-install-unproven')])):
            with self.assertRaisesRegex(native.TestFailure,'no glob cleanup'):
                runner.cleanup()
        self.assertEqual(runner.ledger['paths'],{})

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
