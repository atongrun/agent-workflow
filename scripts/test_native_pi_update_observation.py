#!/usr/bin/env python3
"""Real local subprocess and diagnostic failure-persistence checks; no system install."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import native_acceptance as native
import native_pi_update_observation as obs
import native_startup_diagnostics as startup


def private(path,data):
    path.write_text(data);path.chmod(0o600)


def trace_rows(cwd):
    base=dict(pid=123,uid=os.getuid(),gid=os.getgid(),umask='0022')
    return [dict(base,kind='npm-spawn',method='spawn',command='npm',argv=['--prefix','/opt/pi-cli','install','-g','--ignore-scripts','--min-release-age=0','@earendil-works/pi-coding-agent@1.0.4'],cwd=str(cwd),sourceType='registry-package',source='@earendil-works/pi-coding-agent@1.0.4'),
            dict(base,pid=124,kind='node-start',executable='/opt/node/bin/node',argv=['/opt/node/bin/node','/opt/node/bin/npm','install'],cwd=str(cwd))]


class ObservationTests(unittest.TestCase):
    def test_trace_import_resanitizes_and_rejects_unknown_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'trace'; rows=trace_rows(tmp)
            rows[0]['argv'].append('secret-value-do-not-save')
            private(p,'\n'.join(json.dumps(r) for r in rows))
            result=obs.load_trace(p,Path(tmp))
            self.assertEqual(result['requestedPackageVersion'],'1.0.4')
            self.assertNotIn('secret-value-do-not-save',json.dumps(result))
            self.assertTrue(result['processObservations'][0]['argv'][-1]['redacted'])
            for value in ({'kind':[]},dict(rows[0],environment='secret-value-do-not-save'),dict(rows[0],umask='9999')):
                private(p,json.dumps(value));result=obs.load_trace(p,Path(tmp))
                self.assertEqual(result,{'traceUnavailable':'trace_schema'})

    def test_trace_symlink_and_size_limit_do_not_read_uncontrolled_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'target';private(target,'secret-value-do-not-save')
            linked=Path(tmp)/'link';linked.symlink_to(target)
            self.assertIn('traceUnavailable',obs.load_trace(linked))
            private(target,'x'*(obs.MAX_TRACE+1))
            self.assertEqual(obs.load_trace(target),{'traceUnavailable':'trace_limit'})

    def test_symlink_loop_preserves_lstat_and_readlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'loop';p.symlink_to('loop')
            row=obs.object_metadata(str(p))
            self.assertEqual((row['objectType'],row['mode'],row['readlink']),('symlink','0777','loop'))
            self.assertIsNone(row['realpath']);self.assertIn('realpathUnavailable',row)

    def test_non_object_package_json_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg=Path(tmp)/'pkg';pkg.mkdir();p=pkg/'package.json';private(p,'[]')
            actual=Path.lstat
            def root_stat(path):
                s=actual(path)
                return SimpleNamespace(st_mode=s.st_mode&~0o6022,st_uid=0,st_dev=s.st_dev,st_ino=s.st_ino)
            with patch.object(obs,'PACKAGE',str(pkg)),patch.object(Path,'lstat',root_stat):
                self.assertEqual(obs.trusted_package_version(),{'installedVersionUnavailable':'package_identity_invalid'})

    def test_real_method_persists_after_observations_before_trust_or_child_failure(self):
        for child_fails,limited in ((False,False),(True,False),(False,True)):
            with self.subTest(child_fails=child_fails,limited=limited),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);runner=native.Acceptance.__new__(native.Acceptance)
                runner.report=dict(stages=[]);runner.diagnostic_report_path=root/'report.json'
                runner.verify_rpc=lambda phase:None
                calls=[];saved=[]
                metadata=lambda p:dict(path=p,objectType='symlink' if p==obs.PACKAGE else 'file',mode='0777',uid=0,gid=0,ino=1,dev=1,readlink='../../outside',realpath='/tmp/outside',realpathInsidePrefix=False)
                def command(name,args,seconds,capture=False,environment=None):
                    calls.append(name)
                    if name=='npm-version':return b'10.9.3\n'
                    if name!='pi-update':return None
                    self.assertIn('--import=',environment['NODE_OPTIONS'])
                    private(root/'pi-update.log','AWF_PI_MASK_BEFORE=0002\nUpdated pi from 1.0.2 to 1.0.4\nAWF_PI_MASK_AFTER=0002\n')
                    private(root/'pi-process-observation.jsonl','\n'.join(json.dumps(r) for r in trace_rows(Path.cwd())))
                    runner.report['stages'].append(dict(name=name,exitCode=7 if child_fails else 0))
                    runner.report['piUpdate']=dict(executionStarted=True,passed=False)
                    if limited:runner.report['piObservation']['after']['outputLimitExceeded']=True
                    if child_fails:raise native.TestFailure('stage failed: pi-update')
                runner.command=command
                def save(path,report):
                    saved.append(copy.deepcopy(report));private(path,json.dumps(report))
                with patch.object(native,'CONTROL',root),patch.object(native,'stopped'),patch.object(native,'identity',return_value={'ino':1}), \
                     patch.object(native.package,'digest_file',return_value='a'*64),patch.object(obs,'object_metadata',side_effect=metadata), \
                     patch.object(obs,'trusted_package_version',return_value={'installedVersionUnavailable':'untrusted_physical_parent'}), \
                     patch.object(startup,'first_unsafe_pi_entry',return_value=dict(passed=False,path=obs.PACKAGE,mode='0777')),patch.object(native,'report_write',side_effect=save):
                    with self.assertRaisesRegex(native.TestFailure,'stage failed: pi-update' if child_fails else 'Pi update output limit' if limited else 'updated Pi prefix permissions unsafe'):
                        runner.verify_pi_update_diagnostic()
                self.assertEqual(len(saved),2)
                result=json.loads(runner.diagnostic_report_path.read_text())
                after=result['piObservation']['after']
                self.assertEqual(after['firstUnsafeObject']['objectType'],'symlink')
                self.assertEqual(after['requestedPackageVersion'],'1.0.4')
                self.assertEqual(result['piObservation']['updateStage']['exitCode'],7 if child_fails else 0)
                self.assertTrue(result['piDiagnosticObserved'])
                if limited:self.assertTrue(after['outputLimitExceeded'])
                self.assertNotIn('pi-version-updated',calls);self.assertNotIn('start-after-pi',calls)

    def test_already_exited_child_final_drain_records_overflow(self):
        with tempfile.TemporaryDirectory() as tmp,tempfile.TemporaryFile() as output:
            output.write(b'x'*(2<<20));output.seek(0)
            child=SimpleNamespace(stdout=output,returncode=0,poll=lambda:0)
            runner=native.Acceptance.__new__(native.Acceptance)
            runner.pi_update_diagnostic=True;runner.deadline=time.monotonic()+30
            runner.report=dict(stages=[]);runner.observe=lambda:None;runner.resources=lambda:None
            with patch.object(native,'CONTROL',Path(tmp)),patch.object(native.subprocess,'Popen',return_value=child),contextlib.redirect_stdout(io.StringIO()):
                runner.command('pi-update',[sys.executable,'-c','pass'],3)
            self.assertEqual((Path(tmp)/'pi-update.log').stat().st_size,obs.MAX_OUTPUT)
            self.assertTrue(runner.report['piObservation']['after']['outputLimitExceeded'])
            self.assertEqual(runner.report['stages'][-1]['exitCode'],0)

    def test_actual_local_child_failure_output_cap_and_timeout_keep_stages(self):
        cases=[('import sys;sys.exit(7)',3,'stage failed: pi-update',7),
               ('import sys;sys.stdout.write("x"*(2<<20));sys.stdout.flush()',3,'Pi update output limit',None),
               ('import time;time.sleep(5)',0.1,'stage timeout: pi-update',None)]
        for code,seconds,error,exitcode in cases:
            with self.subTest(error=error),tempfile.TemporaryDirectory() as tmp:
                runner=native.Acceptance.__new__(native.Acceptance)
                runner.pi_update_diagnostic=True;runner.deadline=time.monotonic()+30
                runner.report=dict(stages=[]);runner.observe=lambda:None;runner.resources=lambda:None
                with patch.object(native,'CONTROL',Path(tmp)),contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaisesRegex(native.TestFailure,error):
                        runner.command('pi-update',[sys.executable,'-c',code],seconds)
                stage=runner.report['stages'][-1]
                self.assertEqual(stage['name'],'pi-update')
                if exitcode is not None:self.assertEqual(stage['exitCode'],exitcode)
                else:self.assertEqual(stage['signal'],15)
                self.assertTrue(runner.report['piUpdateExecuted']);self.assertFalse(runner.report['piUpdate']['passed'])
                self.assertLessEqual((Path(tmp)/'pi-update.log').stat().st_size,obs.MAX_OUTPUT)
                if 'limit' in error:self.assertEqual((Path(tmp)/'pi-update.log').stat().st_size,obs.MAX_OUTPUT)

    def test_cleanup_report_import_keeps_diagnostic_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'report';payload=dict(sourceCommit=native.probe.SOURCE,workflowCommit='c'*40,piObservation={'after':{'traceUnavailable':'fixture'}},piDiagnosticObserved=True,piDiagnosticPassed=False)
            private(p,json.dumps(payload));actual=p.lstat()
            claimed=SimpleNamespace(st_mode=actual.st_mode,st_uid=0)
            with patch.object(Path,'lstat',return_value=claimed),patch.dict(os.environ,{'GITHUB_SHA':'c'*40}):
                result=native.previous_report(p,{})
            self.assertEqual(result,payload)


if __name__=='__main__':unittest.main()
