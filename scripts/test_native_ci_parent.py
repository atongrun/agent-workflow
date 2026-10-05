#!/usr/bin/env python3
"""Parent permission boundaries and recovery, without root or system mutation."""
import contextlib
import io
import json
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import native_ci_parent as parent


def info(mode=0o777,uid=0,gid=0,ino=123):
    return SimpleNamespace(st_mode=stat.S_IFDIR|mode,st_uid=uid,st_gid=gid,st_dev=7,st_ino=ino)


class ParentTests(unittest.TestCase):
    def setUp(self):
        self.record=dict(schema=1,path='/opt',workflowCommit='c'*40,
            controlIdentity={'dev':7,'ino':456,'type':stat.S_IFDIR},
            identity=parent.inode(info()),uid=0,gid=0,originalMode=0o777,testMode=0o755,applied=True)

    def test_different_initial_metadata_never_opens_or_changes_parent(self):
        rows=[info(mode=0o755),info(uid=1000),info(gid=1000),info(mode=0o1777),
              SimpleNamespace(st_mode=stat.S_IFLNK|0o777,st_uid=0,st_gid=0)]
        for row in rows:
            with self.subTest(row=row),patch.object(parent,'OPT') as opt, \
                 patch.object(parent.os,'open') as opened,patch.object(parent.os,'fchmod') as chmod:
                opt.lstat.return_value=row
                opt.resolve.return_value='/opt'
                with self.assertRaisesRegex(parent.native.TestFailure,'metadata differs'):
                    parent.open_opt({0o777})
                opened.assert_not_called()
                chmod.assert_not_called()

    def test_fd_owner_change_is_refused_even_when_inode_matches(self):
        with patch.object(parent,'OPT') as opt,patch.object(parent.os,'open',return_value=7), \
             patch.object(parent.os,'fstat',return_value=info(uid=1000)), \
             patch.object(parent.os,'close') as closed,patch.object(parent.os,'fchmod') as chmod:
            opt.lstat.return_value=info()
            opt.resolve.return_value='/opt'
            with self.assertRaisesRegex(parent.native.TestFailure,'owner or mode changed'):
                parent.open_opt({0o777})
            closed.assert_called_once_with(7)
            chmod.assert_not_called()

    def test_atomic_private_receipt_precedes_exact_descriptor_chmod(self):
        actual_fchmod,actual_close=parent.os.fchmod,parent.os.close
        with tempfile.TemporaryDirectory() as temp:
            state=Path(temp)/'state'
            context={}
            def change(fd,mode):
                if mode==0o600:
                    actual_fchmod(fd,mode)
                    return
                self.assertEqual((fd,mode),(100000,0o755))
                path=state/'parent.json'
                self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)
                recorded=json.loads(path.read_text())
                self.assertEqual(recorded['originalMode'],0o777)
                self.assertEqual(recorded['identity'],self.record['identity'])
                self.assertFalse(recorded['applied'])
            with patch.object(parent,'STATE',state),patch.dict(parent.os.environ,{'GITHUB_SHA':'c'*40}), \
                 patch.object(parent,'open_opt',return_value=(100000,info())), \
                 patch.object(parent,'verify_opt'),patch.object(parent.os,'fchmod',side_effect=change) as chmod, \
                 patch.object(parent.os,'close',side_effect=lambda fd:None if fd==100000 else actual_close(fd)):
                saved=parent.prepare(context)
            self.assertTrue(saved['applied'])
            self.assertTrue(context['stateCreated'])
            self.assertEqual(stat.S_IMODE(state.stat().st_mode),0o700)
            self.assertEqual([c.args for c in chmod.call_args_list if c.args[1]!=0o600],[(100000,0o755)])

    def test_receipt_failure_prevents_permission_write(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(parent,'STATE',Path(temp)/'state'), \
             patch.dict(parent.os.environ,{'GITHUB_SHA':'c'*40}), \
             patch.object(parent,'open_opt',return_value=(7,info())), \
             patch.object(parent.native,'private_file',side_effect=OSError('fixture failure')), \
             patch.object(parent.os,'fchmod') as chmod,patch.object(parent.os,'close'):
            with self.assertRaises(OSError):
                parent.prepare({})
            chmod.assert_not_called()

    def test_restore_rejects_changed_inode_and_never_chmods_replacement(self):
        with patch.object(parent,'open_opt',return_value=(7,info(mode=0o755,ino=124))), \
             patch.object(parent.os,'fchmod') as chmod,patch.object(parent.os,'close'):
            with self.assertRaisesRegex(parent.native.TestFailure,'inode differs'):
                parent.restore(self.record)
            chmod.assert_not_called()

    def test_restore_is_descriptor_only_and_idempotent(self):
        for mode in (0o755,0o777):
            current=info(mode=mode)
            def change(fd,new):
                self.assertEqual((fd,new),(7,0o777))
                current.st_mode=stat.S_IFDIR|new
            with self.subTest(mode=mode),patch.object(parent,'open_opt',return_value=(7,current)), \
                 patch.object(parent,'OPT') as opt,patch.object(parent.os,'fstat',return_value=current), \
                 patch.object(parent.os,'fchmod',side_effect=change) as chmod,patch.object(parent.os,'close'):
                opt.lstat.return_value=current
                result=parent.restore(self.record)
                self.assertTrue(result['passed'])
                self.assertEqual(result['observedBeforeRestoreMode'],format(mode,'04o'))
                self.assertEqual(result['permissionWritePerformed'],mode==0o755)
                if mode==0o755:
                    chmod.assert_called_once_with(7,0o777)
                else:
                    chmod.assert_not_called()

    def test_retry_requires_trusted_parent_for_any_remaining_native_control(self):
        for control_present in (True,False):
            for mode in (0o755,0o777):
                current=info(mode=mode)
                def change(fd,new):
                    self.assertEqual((fd,new),(7,0o755))
                    current.st_mode=stat.S_IFDIR|new
                with self.subTest(control=control_present,mode=mode), \
                     patch.object(parent,'open_opt',return_value=(7,current)),patch.object(parent,'OPT') as opt, \
                     patch.object(parent.os,'fstat',return_value=current),patch.object(parent.os.path,'lexists',return_value=control_present), \
                     patch.object(parent.os,'fchmod',side_effect=change) as chmod,patch.object(parent.os,'close'):
                    opt.lstat.return_value=current
                    changed=parent.protect_retry(self.record)
                    self.assertEqual(changed,control_present and mode==0o777)
                    if changed:
                        chmod.assert_called_once_with(7,0o755)
                    else:
                        chmod.assert_not_called()

    def test_unknown_control_contents_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            state=Path(temp)
            (state/'parent.json').write_text('{}')
            (state/'unknown').write_text('preserved')
            with patch.object(parent,'STATE',state),patch.object(parent,'load_state',return_value=self.record):
                with self.assertRaisesRegex(parent.native.TestFailure,'unknown parent-control'):
                    parent.remove_state(self.record)
            self.assertTrue((state/'parent.json').exists())
            self.assertEqual((state/'unknown').read_text(),'preserved')

    def test_native_failure_and_cancellation_still_restore_after_native_attempt(self):
        for outcome in (0,1,parent.native.TestFailure('approved native test cancelled')):
            events=[]
            def prepare(context):
                context['stateCreated']=True
                events.append('prepare')
                return self.record
            def native(args):
                events.append('native')
                if isinstance(outcome,Exception):
                    raise outcome
                return outcome
            def restore(record):
                events.append('restore')
                return {'passed':True,'observedBeforeRestoreMode':'0755','permissionWritePerformed':True}
            with self.subTest(outcome=outcome), \
                 patch('sys.argv',['parent','--expected-release','24.04','--report','/tmp/report.json','--prepare-ci-opt']), \
                 patch.dict(parent.os.environ,{'GITHUB_SHA':'c'*40},clear=True), \
                 patch.object(parent.native.probe,'ci_guard'),patch.object(parent.signal,'signal'), \
                 patch.object(parent,'prepare',side_effect=prepare),patch.object(parent,'call_native',side_effect=native), \
                 patch.object(parent,'load_state',return_value=self.record),patch.object(parent,'restore',side_effect=restore), \
                 patch.object(parent.native,'previous_report',side_effect=lambda path,default:default), \
                 patch.object(parent.native,'report_write') as save,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(parent.main(),0 if outcome==0 else 1)
                self.assertEqual(events,['prepare','native','restore'])
                self.assertTrue(save.call_args.args[1]['parentRestoration']['passed'])

    def test_cleanup_failure_restores_but_keeps_private_receipt(self):
        with patch('sys.argv',['parent','--expected-release','24.04','--report','/tmp/report.json','--cleanup-only']), \
             patch.dict(parent.os.environ,{'GITHUB_SHA':'c'*40},clear=True), \
             patch.object(parent.native.probe,'ci_guard'),patch.object(parent.signal,'signal'), \
             patch.object(parent.os.path,'lexists',return_value=True),patch.object(parent,'load_state',return_value=self.record), \
             patch.object(parent,'protect_retry',return_value=False), \
             patch.object(parent,'call_native',return_value=1), \
             patch.object(parent,'restore',return_value={'passed':True,'observedBeforeRestoreMode':'0755','permissionWritePerformed':True}) as restore, \
             patch.object(parent,'remove_state') as remove, \
             patch.object(parent.native,'previous_report',side_effect=lambda path,default:default), \
             patch.object(parent.native,'report_write'),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(parent.main(),1)
            restore.assert_called_once_with(self.record)
            remove.assert_not_called()

    def test_no_state_cleanup_does_not_create_report_or_run_native(self):
        with patch('sys.argv',['parent','--expected-release','24.04','--report','/tmp/report.json','--cleanup-only']), \
             patch.object(parent.native.probe,'ci_guard'),patch.object(parent.os.path,'lexists',return_value=False), \
             patch.object(parent,'call_native') as native,patch.object(parent.native,'report_write') as save:
            self.assertEqual(parent.main(),0)
            native.assert_not_called()
            save.assert_not_called()


if __name__=='__main__':
    unittest.main()
