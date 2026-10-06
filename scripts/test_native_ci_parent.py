#!/usr/bin/env python3
"""Parent permission boundaries and recovery, without root or system mutation."""
import contextlib
import errno
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
    def test_phase_forwarding_preserves_real_branch_and_system_paths(self):
        from types import SimpleNamespace
        import sys
        arguments=SimpleNamespace(expected_release='24.04',report=Path('/tmp/report.json'),cleanup_only=False,phase='default')
        branch='refs/heads/awf/linux-pi-umask-native-ci-v1'
        seen=[]
        def capture():
            seen.extend(sys.argv)
            self.assertEqual(parent.os.environ['GITHUB_REF'],branch)
            return 0
        with patch.dict(parent.os.environ,{'GITHUB_REF':branch}),patch.object(parent.native,'main',side_effect=capture):
            self.assertEqual(parent.call_native(arguments),0)
        self.assertEqual(seen[-2:],['--phase','default'])
        self.assertEqual(parent.PARENTS,('/opt','/usr/local/bin'))

    def setUp(self):
        self.acl_snapshot={'access':{'status':'absent'},'default':{'status':'absent'}}
        acl_mock=patch.object(parent.acl,'snapshot',return_value=self.acl_snapshot)
        acl_mock.start();self.addCleanup(acl_mock.stop)
        self.record=dict(schema=1,path='/opt',workflowCommit='c'*40,
            controlIdentity={'dev':7,'ino':456,'type':stat.S_IFDIR},
            identity=parent.inode(info()),uid=0,gid=0,originalMode=0o777,testMode=0o755,applied=True,originalACL=self.acl_snapshot)
        self.pair=dict(schema=2,workflowCommit='c'*40,controlIdentity=self.record['controlIdentity'],
            parents=[self.record,dict(self.record,path='/usr/local/bin',identity=parent.inode(info(ino=124)))])
        self.restored=dict(passed=True,parents=[dict(path=name,passed=True,
            observedBeforeRestoreMode='0755',permissionWritePerformed=True) for name in parent.PARENTS])

    def test_different_initial_metadata_never_opens_or_changes_parent(self):
        rows=[info(mode=0o755),info(uid=1000),info(gid=1000),info(mode=0o1777),
              SimpleNamespace(st_mode=stat.S_IFLNK|0o777,st_uid=0,st_gid=0)]
        for row in rows:
            with self.subTest(row=row),patch.object(parent,'Path') as paths, \
                 patch.object(parent.os,'open') as opened,patch.object(parent.os,'fchmod') as chmod:
                paths.return_value.lstat.return_value=row
                paths.return_value.resolve.return_value='/opt'
                with self.assertRaisesRegex(parent.native.TestFailure,'metadata differs'):
                    parent.open_parent('/opt',{0o777})
                opened.assert_not_called()
                chmod.assert_not_called()

    def test_fd_owner_change_is_refused_even_when_inode_matches(self):
        with patch.object(parent,'Path') as paths,patch.object(parent.os,'open',return_value=7), \
             patch.object(parent.os,'fstat',return_value=info(uid=1000)), \
             patch.object(parent.os,'close') as closed,patch.object(parent.os,'fchmod') as chmod:
            paths.return_value.lstat.return_value=info()
            paths.return_value.resolve.return_value='/opt'
            with self.assertRaisesRegex(parent.native.TestFailure,'owner or mode changed'):
                parent.open_parent('/opt',{0o777})
            closed.assert_called_once_with(7)
            chmod.assert_not_called()

    def test_atomic_private_receipt_precedes_exact_descriptor_chmod(self):
        actual_fchmod,actual_close=parent.os.fchmod,parent.os.close
        with tempfile.TemporaryDirectory() as temp:
            state=Path(temp)/'state'
            context={}
            writes=[]
            def change(fd,mode):
                if mode==0o600:
                    actual_fchmod(fd,mode)
                    return
                self.assertEqual(mode,0o755)
                self.assertEqual(fd,100000+len(writes))
                path=state/'parent.json'
                self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)
                recorded=json.loads(path.read_text())
                self.assertEqual([r['path'] for r in recorded['parents']],list(parent.PARENTS))
                self.assertTrue(all(r['originalMode']==0o777 for r in recorded['parents']))
                self.assertEqual(recorded['parents'][0]['identity'],self.record['identity'])
                self.assertEqual([r['applied'] for r in recorded['parents']],[bool(writes),False])
                writes.append(fd)
            with patch.object(parent,'STATE',state),patch.dict(parent.os.environ,{'GITHUB_SHA':'c'*40}), \
                 patch.object(parent,'open_parent',side_effect=[(100000,info()),(100001,info(ino=124))]), \
                 patch.object(parent,'verify_parent'),patch.object(parent.os,'fchmod',side_effect=change) as chmod, \
                 patch.object(parent.os,'close',side_effect=lambda fd:None if fd>=100000 else actual_close(fd)):
                saved=parent.prepare(context)
            self.assertTrue(all(r['applied'] for r in saved['parents']))
            self.assertTrue(context['stateCreated'])
            self.assertEqual(stat.S_IMODE(state.stat().st_mode),0o700)
            self.assertEqual([c.args for c in chmod.call_args_list if c.args[1]!=0o600],[(100000,0o755),(100001,0o755)])

    def test_receipt_failure_prevents_permission_write(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(parent,'STATE',Path(temp)/'state'), \
             patch.dict(parent.os.environ,{'GITHUB_SHA':'c'*40}), \
             patch.object(parent,'open_parent',return_value=(7,info())), \
             patch.object(parent.native,'private_file',side_effect=OSError('fixture failure')), \
             patch.object(parent.os,'fchmod') as chmod,patch.object(parent.os,'close'):
            with self.assertRaises(OSError):
                parent.prepare({})
            chmod.assert_not_called()

    def test_restore_rejects_changed_inode_and_never_chmods_replacement(self):
        with patch.object(parent,'open_parent',return_value=(7,info(mode=0o755,ino=124))), \
             patch.object(parent.os,'fchmod') as chmod,patch.object(parent.os,'close'):
            with self.assertRaisesRegex(parent.native.TestFailure,'inode differs'):
                parent.restore_parent(self.record)
            chmod.assert_not_called()

    def test_restore_is_descriptor_only_and_idempotent(self):
        for mode in (0o755,0o777):
            current=info(mode=mode)
            def change(fd,new):
                self.assertEqual((fd,new),(7,0o777))
                current.st_mode=stat.S_IFDIR|new
            with self.subTest(mode=mode),patch.object(parent,'open_parent',return_value=(7,current)), \
                 patch.object(parent,'Path') as paths,patch.object(parent.os,'fstat',return_value=current), \
                 patch.object(parent.os,'fchmod',side_effect=change) as chmod,patch.object(parent.os,'close'):
                paths.return_value.lstat.return_value=current
                result=parent.restore_parent(self.record)
                self.assertTrue(result['passed'])
                self.assertEqual(result['observedBeforeRestoreMode'],format(mode,'04o'))
                self.assertEqual(result['permissionWritePerformed'],mode==0o755)
                if mode==0o755:
                    chmod.assert_called_once_with(7,0o777)
                else:
                    chmod.assert_not_called()

    def test_retry_requires_trusted_parent_for_any_remaining_native_control(self):
        for control_present in (True,False):
            for modes in ((0o755,0o755),(0o777,0o755),(0o755,0o777),(0o777,0o777)):
                current={name:info(mode=mode,ino=123+i) for i,(name,mode) in enumerate(zip(parent.PARENTS,modes))}
                names={7+i:name for i,name in enumerate(parent.PARENTS)}
                def change(fd,new):
                    self.assertEqual(new,0o755)
                    current[names[fd]].st_mode=stat.S_IFDIR|new
                def opened(name,allowed):
                    return 7+parent.PARENTS.index(name),current[name]
                with self.subTest(control=control_present,modes=modes), \
                     patch.object(parent,'open_parent',side_effect=opened), \
                     patch.object(parent,'Path',side_effect=lambda name:SimpleNamespace(lstat=lambda:current[name])), \
                     patch.object(parent.os,'fstat',side_effect=lambda fd:current[names[fd]]), \
                     patch.object(parent.os.path,'lexists',return_value=control_present), \
                     patch.object(parent.os,'fchmod',side_effect=change) as chmod,patch.object(parent.os,'close'):
                    changed=parent.protect_retry(self.pair)
                    expected=[name for name,mode in zip(parent.PARENTS,modes) if control_present and mode==0o777]
                    self.assertEqual(changed,expected)
                    self.assertEqual(chmod.call_count,len(expected))
                    if control_present:
                        self.assertTrue(all(stat.S_IMODE(row.st_mode)==0o755 for row in current.values()))

    def test_retry_acl_drift_or_read_failure_precedes_all_parent_permission_writes(self):
        changed=dict(self.acl_snapshot,default={'status':'present','entries':[
            dict(tag=tag,permissions=7,id=None) for tag in ('owner','group-owner','other')]})
        for failed in (0,1):
            for read_error in (False,True):
                def opened(name,allowed):
                    index=parent.PARENTS.index(name)
                    return 100000+index,info(mode=0o777,ino=123+index)
                def snapshot(fd):
                    if fd==100000+failed:
                        if read_error:raise OSError(errno.EIO,'private ACL failure')
                        return changed
                    return self.acl_snapshot
                with self.subTest(failed=failed,read_error=read_error), \
                     patch.object(parent,'open_parent',side_effect=opened),patch.object(parent,'verify_parent'), \
                     patch.object(parent.acl,'snapshot',side_effect=snapshot), \
                     patch.object(parent.os.path,'lexists',return_value=True), \
                     patch.object(parent.os,'fchmod') as chmod,patch.object(parent.os,'close') as close:
                    with self.assertRaises(OSError if read_error else parent.native.TestFailure):
                        parent.protect_retry(self.pair)
                    chmod.assert_not_called()
                    self.assertEqual([call.args[0] for call in close.call_args_list],
                        [100000+i for i in range(failed+1)])

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
                return self.pair
            def native(args):
                events.append('native')
                if isinstance(outcome,Exception):
                    raise outcome
                return outcome
            def restore(record):
                events.append('restore')
                return self.restored
            with self.subTest(outcome=outcome), \
                 patch('sys.argv',['parent','--expected-release','24.04','--report','/tmp/report.json','--prepare-ci-parents','--pi-update-diagnostic']), \
                 patch.dict(parent.os.environ,{'GITHUB_SHA':'c'*40},clear=True), \
                 patch.object(parent.native.probe,'ci_guard'),patch.object(parent.signal,'signal'), \
                 patch.object(parent,'prepare',side_effect=prepare),patch.object(parent,'call_native',side_effect=native), \
                 patch.object(parent,'load_state',return_value=self.pair),patch.object(parent,'restore',side_effect=restore), \
                 patch.object(parent.native,'previous_report',side_effect=lambda path,default:default), \
                 patch.object(parent.native,'report_write') as save,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(parent.main(),0 if outcome==0 else 1)
                self.assertEqual(events,['prepare','native','restore'])
                self.assertTrue(save.call_args.args[1]['parentRestoration']['passed'])

    def test_cleanup_failure_restores_but_keeps_private_receipt(self):
        with patch('sys.argv',['parent','--expected-release','24.04','--report','/tmp/report.json','--cleanup-only']), \
             patch.dict(parent.os.environ,{'GITHUB_SHA':'c'*40},clear=True), \
             patch.object(parent.native.probe,'ci_guard'),patch.object(parent.signal,'signal'), \
             patch.object(parent.os.path,'lexists',return_value=True),patch.object(parent,'load_state',return_value=self.pair), \
             patch.object(parent,'protect_retry',return_value=[]), \
             patch.object(parent,'call_native',return_value=1), \
             patch.object(parent,'restore',return_value=self.restored) as restore, \
             patch.object(parent,'remove_state') as remove, \
             patch.object(parent.native,'previous_report',side_effect=lambda path,default:default), \
             patch.object(parent.native,'report_write'),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(parent.main(),1)
            restore.assert_called_once_with(self.pair)
            remove.assert_not_called()

    def test_cleanup_acl_failures_restore_other_parent_fail_and_keep_receipt(self):
        # Exercise real cleanup-only main, restore(), restore_parent() and atomic
        # report writing. Substitute root metadata/native cleanup; no system paths.
        actual_fchmod,actual_close=parent.os.fchmod,parent.os.close
        for failed in (0,1):
            for failure in ('before','after','changed'):
                with self.subTest(failed=failed,failure=failure),tempfile.TemporaryDirectory() as temporary:
                    root=Path(temporary);state=root/'state';state.mkdir(mode=0o700)
                    receipt=state/'parent.json';receipt.write_text('private receipt remains')
                    report_path=root/'report.json'
                    names={100000+i:name for i,name in enumerate(parent.PARENTS)}
                    current={name:info(mode=0o755,ino=123+i) for i,name in enumerate(parent.PARENTS)}
                    snapshots={fd:0 for fd in names};changes=[];closed=[]
                    def opened(name,allowed):
                        return 100000+parent.PARENTS.index(name),current[name]
                    def verify(name,fd,identity,mode):
                        self.assertEqual(names[fd],name)
                        self.assertEqual(parent.inode(current[name]),identity)
                        self.assertEqual(stat.S_IMODE(current[name].st_mode),mode)
                    def snapshot(fd):
                        snapshots[fd]+=1
                        if fd==100000+failed:
                            if snapshots[fd]==(2 if failure=='after' else 1):
                                if failure=='changed':
                                    return dict(self.acl_snapshot,default={'status':'present','entries':[]})
                                raise OSError(errno.EIO,'secret exception must stay private')
                        return self.acl_snapshot
                    def chmod(fd,mode):
                        if fd not in names:return actual_fchmod(fd,mode)
                        self.assertEqual(mode,0o777);changes.append(fd)
                        current[names[fd]].st_mode=stat.S_IFDIR|mode
                    def close(fd):
                        if fd in names:closed.append(fd)
                        else:actual_close(fd)
                    def previous(path,default):
                        return dict(default,cleanup={'passed':True},failure='stage failed: awf-update')
                    # Python 3.12 bounds compiler block nesting. Keep the same
                    # ordered patches in one ExitStack, including unwind order.
                    with contextlib.ExitStack() as stack:
                        remove_patch = patch.object(parent,'remove_state')
                        contexts = [
                            patch('sys.argv',['parent','--expected-release','24.04','--report',str(report_path),'--cleanup-only']),
                            patch.dict(parent.os.environ,{'GITHUB_SHA':'c'*40},clear=True),
                            patch.object(parent.native.probe,'ci_guard'),patch.object(parent.signal,'signal'),
                            patch.object(parent,'STATE',state),patch.object(parent.os.path,'lexists',return_value=True),
                            patch.object(parent,'load_state',return_value=self.pair),patch.object(parent,'protect_retry',return_value=[]),
                            patch.object(parent,'call_native',return_value=0),remove_patch,
                            patch.object(parent,'open_parent',side_effect=opened),patch.object(parent,'verify_parent',side_effect=verify),
                            patch.object(parent.acl,'snapshot',side_effect=snapshot),patch.object(parent.os,'fchmod',side_effect=chmod),
                            patch.object(parent.os,'close',side_effect=close),patch.object(parent.native,'previous_report',side_effect=previous),
                            contextlib.redirect_stdout(io.StringIO()),
                        ]
                        for context in contexts:
                            entered = stack.enter_context(context)
                            if context is remove_patch:
                                remove = entered
                        self.assertEqual(parent.main(),1)
                    report=json.loads(report_path.read_text())
                    self.assertTrue(report['cleanup']['passed'])
                    self.assertFalse(report['parentRestoration']['passed'])
                    results=report['parentRestoration']['parents']
                    self.assertFalse(results[failed]['passed'])
                    self.assertTrue(results[1-failed]['passed']);self.assertTrue(results[1-failed]['aclRestored'])
                    self.assertEqual(current[parent.PARENTS[1-failed]].st_mode,stat.S_IFDIR|0o777)
                    self.assertEqual(report['failure'],'stage failed: awf-update')
                    self.assertNotIn('secret exception',report_path.read_text())
                    self.assertFalse(report['parentRestoration'].get('privateReceiptRemoved',False))
                    self.assertEqual(receipt.read_text(),'private receipt remains');remove.assert_not_called()
                    self.assertEqual(closed,[100000,100001])
                    self.assertIn(100001-failed,changes)
                    self.assertEqual(100000+failed in changes,failure=='after')

    def test_no_state_cleanup_does_not_create_report_or_run_native(self):
        with patch('sys.argv',['parent','--expected-release','24.04','--report','/tmp/report.json','--cleanup-only']), \
             patch.object(parent.native.probe,'ci_guard'),patch.object(parent.os.path,'lexists',return_value=False), \
             patch.object(parent,'call_native') as native,patch.object(parent.native,'report_write') as save:
            self.assertEqual(parent.main(),0)
            native.assert_not_called()
            save.assert_not_called()

    def test_second_bad_parent_prevents_first_permission_write(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(parent,'STATE',Path(temp)/'state'), \
             patch.object(parent,'open_parent',side_effect=[(7,info()),parent.native.TestFailure('second differs')]), \
             patch.object(parent.os,'fchmod') as chmod,patch.object(parent.os,'close'):
            with self.assertRaisesRegex(parent.native.TestFailure,'second differs'):
                parent.prepare({})
            self.assertFalse(parent.STATE.exists())
            chmod.assert_not_called()

    def test_one_blocked_restore_still_attempts_the_other(self):
        for failed in (0,1):
            results=[dict(path=name,passed=True) for name in parent.PARENTS]
            results[failed]=parent.native.TestFailure('fixture identity changed')
            with self.subTest(failed=failed),patch.object(parent,'restore_parent',side_effect=results) as restored:
                report=parent.restore(self.pair)
                self.assertEqual(restored.call_count,2)
                self.assertFalse(report['passed'])
                self.assertTrue(report['parents'][1-failed]['passed'])

    def test_unapproved_parent_path_never_reads_metadata(self):
        with patch.object(parent,'Path') as paths:
            with self.assertRaisesRegex(parent.native.TestFailure,'unapproved parent'):
                parent.open_parent('/tmp/foreign',{0o777})
            paths.assert_not_called()

    def test_second_permission_failure_preserves_both_originals_and_first_progress(self):
        actual_fchmod,actual_close=parent.os.fchmod,parent.os.close
        with tempfile.TemporaryDirectory() as temp:
            state=Path(temp)/'state'; context={}
            def change(fd,mode):
                if mode==0o600:
                    actual_fchmod(fd,mode)
                elif fd==100001:
                    raise OSError('fixture second permission failure')
                else:
                    self.assertEqual((fd,mode),(100000,0o755))
            with patch.object(parent,'STATE',state),patch.dict(parent.os.environ,{'GITHUB_SHA':'c'*40}), \
                 patch.object(parent,'open_parent',side_effect=[(100000,info()),(100001,info(ino=124))]), \
                 patch.object(parent,'verify_parent'),patch.object(parent.os,'fchmod',side_effect=change), \
                 patch.object(parent.os,'close',side_effect=lambda fd:None if fd>=100000 else actual_close(fd)):
                with self.assertRaises(OSError):
                    parent.prepare(context)
            record=json.loads((state/'parent.json').read_text())
            self.assertTrue(context['stateCreated'])
            self.assertEqual([r['applied'] for r in record['parents']],[True,False])
            self.assertTrue(all(r['originalMode']==0o777 for r in record['parents']))

    def test_cancel_during_first_permission_write_restores_both_without_false_no_change(self):
        record=dict(self.pair,parents=[dict(row,applied=False) for row in self.pair['parents']])
        restored=dict(passed=True,parents=[dict(self.restored['parents'][0]),
            dict(self.restored['parents'][1],observedBeforeRestoreMode='0777',permissionWritePerformed=False)])
        def prepare(context):
            context['stateCreated']=True
            raise parent.native.TestFailure('approved native test cancelled')
        with patch('sys.argv',['parent','--expected-release','24.04','--report','/tmp/report.json','--prepare-ci-parents','--pi-update-diagnostic']), \
             patch.dict(parent.os.environ,{'GITHUB_SHA':'c'*40},clear=True), \
             patch.object(parent.native.probe,'ci_guard'),patch.object(parent.signal,'signal'), \
             patch.object(parent,'prepare',side_effect=prepare),patch.object(parent,'call_native') as native, \
             patch.object(parent,'load_state',return_value=record),patch.object(parent,'restore',return_value=restored) as restore, \
             patch.object(parent.native,'previous_report',side_effect=lambda path,default:default), \
             patch.object(parent.native,'report_write') as save,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(parent.main(),1)
            native.assert_not_called()
            restore.assert_called_once_with(record)
            reported=save.call_args.args[1]['parentPreparation']['parents']
            self.assertTrue(reported[0]['applied'])
            self.assertIsNone(reported[1]['applied'])

    def test_any_restoration_failure_makes_successful_native_job_fail(self):
        def prepare(context):
            context['stateCreated']=True; return self.pair
        restored=dict(passed=False,parents=[dict(path='/opt',passed=False),self.restored['parents'][1]])
        with patch('sys.argv',['parent','--expected-release','24.04','--report','/tmp/report.json','--prepare-ci-parents','--pi-update-diagnostic']), \
             patch.dict(parent.os.environ,{'GITHUB_SHA':'c'*40},clear=True), \
             patch.object(parent.native.probe,'ci_guard'),patch.object(parent.signal,'signal'), \
             patch.object(parent,'prepare',side_effect=prepare),patch.object(parent,'call_native',return_value=0), \
             patch.object(parent,'load_state',return_value=self.pair),patch.object(parent,'restore',return_value=restored), \
             patch.object(parent.native,'previous_report',side_effect=lambda path,default:default), \
             patch.object(parent.native,'report_write') as save,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(parent.main(),1)
            self.assertFalse(save.call_args.args[1]['parentRestoration']['passed'])

    def test_retention_refuses_other_branch_before_parent_preparation(self):
        with patch('sys.argv',['parent','--expected-release','24.04','--report','/tmp/report.json',
                 '--prepare-ci-parents','--retain-post-pi-failure']), \
             patch.dict(parent.os.environ,{'GITHUB_REF':'refs/heads/'+parent.native.probe.BRANCH}), \
             patch.object(parent.native.probe,'ci_guard'),patch.object(parent,'prepare') as prepare:
            with self.assertRaisesRegex(parent.native.TestFailure,'approved native acceptance mode'):
                parent.main()
            prepare.assert_not_called()

    def test_retention_is_refused_before_parent_preparation(self):
        for extras in (['--retain-post-pi-failure'],['--pi-update-diagnostic','--retain-post-pi-failure'],['--pi-update-diagnostic','--phase','default']):
            with self.subTest(extras=extras),patch('sys.argv',['parent','--expected-release','24.04','--report','/tmp/report.json','--prepare-ci-parents']+extras), \
                 patch.object(parent.native.probe,'ci_guard'),patch.object(parent,'prepare') as prepare:
                with self.assertRaisesRegex(parent.native.TestFailure,'approved native acceptance mode'):
                    parent.main()
                prepare.assert_not_called()

    def test_missing_diagnostic_flag_refuses_before_parent_preparation(self):
        with patch('sys.argv',['parent','--expected-release','24.04','--report','/tmp/report.json','--prepare-ci-parents']), \
             patch.object(parent.native.probe,'ci_guard'),patch.object(parent,'prepare') as prepare:
            with self.assertRaisesRegex(parent.native.TestFailure,'approved native acceptance mode'):
                parent.main()
            prepare.assert_not_called()


if __name__=='__main__':
    unittest.main()
