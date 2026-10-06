#!/usr/bin/env python3
"""Exercise actual parent/main/download/upgrade entry flow with offline boundaries.

This is a wiring test, never native acceptance: HTTP is fed exact pinned assets;
root/systemctl/installation/RPC/replacement/cleanup are explicit substitutions.
Local child processes and bounded command output/observation persistence are real.
"""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import native_acceptance as native
import native_ci_parent as parent
import native_pi_update_observation as observation
import native_startup_diagnostics as startup

ASSETS = None


class OfflineEntryTests(unittest.TestCase):
    def test_actual_full_entry_and_primary_failure_survive_offline_boundaries(self):
        self.assertIsNotNone(ASSETS, 'exact local pinned assets required; no skip')
        for version, pins in native.PINS_BY_VERSION.items():
            self.assertEqual(set(p.name for p in (ASSETS/version).iterdir()),set(pins))
            native.package.configure(version)
            native.package.verify(ASSETS/version,native.PACKAGING_COMMIT)
            for name,(size,sha) in pins.items():
                p=ASSETS/version/name
                self.assertEqual(p.stat().st_size,size)
                self.assertEqual(native.package.digest_file(p),sha)
        native.package.configure(native.probe.RELEASE)
        for child_code in (0,7):
            with self.subTest(child_code=child_code), tempfile.TemporaryDirectory(prefix='awf-entry-offline-') as temp:
                root=Path(temp);control=root/'control';report=root/'report.json'
                fixture=root/'hash-fixture';fixture.write_bytes(b'private fixture')
                stub=root/'child.py'
                stub.write_text('''import json,pathlib,sys\nname,root,code=sys.argv[1:]\nroot=pathlib.Path(root)\nif name=='npm-version': print('10.9.3')\nelif name=='npm-effective-mask': print('0')\nelif name=='pi-version-updated': print('1.0.4')\nelif name=='pi-root-agent-default': print(str(root/'pi-root-home/.pi/agent'),end='')\nelif name=='pi-update':\n    base=dict(uid=0,gid=0,umask='0022',cwd=str(pathlib.Path.cwd()))\n    rows=[dict(base,pid=123,kind='npm-spawn',method='spawn',command='npm',argv=['--prefix','/opt/pi-cli','install','-g','--ignore-scripts','--min-release-age=0','@earendil-works/pi-coding-agent@1.0.4'],sourceType='registry-package',source='@earendil-works/pi-coding-agent@1.0.4'),dict(base,pid=124,kind='node-start',executable='/opt/node/bin/node',argv=['/opt/node/bin/node','/opt/node/bin/npm','install'])]\n    (root/'pi-process-observation.jsonl').write_text('\\n'.join(json.dumps(r) for r in rows));(root/'pi-process-observation.jsonl').chmod(0o600)\n    print('AWF_PI_MASK_BEFORE=0002\\nUpdated pi from 1.0.2 to 1.0.4\\nAWF_PI_MASK_AFTER=0002')\n    sys.exit(int(code))\n''')
                calls=[];requests=[];rpc=[];health=[];restorations=[]
                real_command=native.Acceptance.command
                real_digest=native.package.digest_file
                class Opener:
                    def open(self,url,timeout):
                        prefix='https://github.com/'+native.probe.REPOSITORY+'/releases/download/'
                        if not url.startswith(prefix):raise AssertionError('unexpected HTTP destination')
                        version,name=url[len(prefix):].split('/',1)
                        if version not in native.PINS_BY_VERSION or name not in native.PINS_BY_VERSION[version]:raise AssertionError('unexpected asset')
                        requests.append((version,name));return (ASSETS/version/name).open('rb')
                def digest(path):
                    # Only fixed installed system files are simulated. Downloaded
                    # assets still use the unmodified real digest implementation.
                    return real_digest(fixture if str(path).startswith(('/opt/','/etc/awf/')) else path)
                def command(runner,name,args,seconds,capture=False,environment=None):
                    calls.append((name,args))
                    if name=='install':self.assertIn('--allow-prerelease',args)
                    if name=='pi-update':self.assertEqual(args,['/bin/sh','-c',native.PI_UPDATE_SHELL])
                    if name=='awf-update':self.assertEqual(args,['/usr/local/bin/awf','update','--version','v1.0.2-rc.2','--yes'])
                    return real_command(runner,name,[sys.executable,str(stub),name,str(control),str(child_code)],seconds,capture,environment)
                def begin(runner,target):
                    self.assertEqual(target['sourceCommit'],native.probe.SOURCE)
                    self.assertEqual(target['version'],native.TARGET_VERSION)
                    runner.ledger['transitions'].append(dict(target=target,roots=[],completed=False))
                def finish(runner):runner.ledger['transitions'][-1]['completed']=True
                def cleanup(runner):
                    self.assertEqual(runner.ledger['paths'],{})
                    runner.report['cleanup']=dict(passed=True,offlineBoundarySubstitution=True)
                def prepare(context):context['stateCreated']=True;return record
                def restore(rec):
                    self.assertIs(rec,record);restorations.extend(parent.PARENTS)
                    return dict(passed=True,parents=[dict(path=p,passed=True,observedBeforeRestoreMode='0755') for p in parent.PARENTS])
                record=dict(parents=[dict(path=p,originalMode=0o777,testMode=0o755,applied=True,originalACL={'access':{'status':'absent'},'default':{'status':'absent'}}) for p in parent.PARENTS])
                metadata=lambda p:dict(path=p,objectType='directory' if p==observation.PACKAGE else 'file',mode='0755')
                versions=iter([{'installedPackageVersion':'1.0.2'},{'installedPackageVersion':'1.0.4'}])
                real_collect=parent.acl.collect
                def collect():
                    # Per-path ACL sampling failures must remain bounded metadata,
                    # even in the finally for a failing Pi child.
                    with patch.object(parent.acl,'snapshot',side_effect=ValueError('private fixture error')):
                        return real_collect()
                env=dict(GITHUB_SHA='c'*40,GITHUB_REF='refs/heads/'+native.probe.BRANCH)
                with contextlib.ExitStack() as stack:
                    patches=[
                        patch('sys.argv',['parent','--expected-release','24.04','--report',str(report),'--prepare-ci-parents','--acl-full-acceptance']),
                        patch.dict(os.environ,env),patch.object(native,'CONTROL',control),
                        patch.object(native.probe,'ci_guard'),patch.object(native.probe,'inspect',return_value={'preflightPassed':True,'offlineBoundarySubstitution':True}),
                        patch.object(native,'capture_existing_runtime',return_value={'offlineFixture':True}),
                        patch.object(native.probe,'run',return_value='LoadState=not-found\nFragmentPath=\nDropInPaths=\n'),
                        patch.object(parent,'prepare',side_effect=prepare),patch.object(parent,'load_state',return_value=record),patch.object(parent,'restore',side_effect=restore),
                        patch.object(native,'previous_report',side_effect=lambda p,d:json.loads(p.read_text()) if p.exists() else d),
                        patch.object(native.urllib.request,'build_opener',return_value=Opener()),patch.object(native.package,'digest_file',side_effect=digest),
                        patch.object(native.Acceptance,'command',command),patch.object(native.Acceptance,'observe'),patch.object(native.Acceptance,'resources'),
                        patch.object(native.Acceptance,'verify_install'),patch.object(native.Acceptance,'health',side_effect=health.append),patch.object(native.Acceptance,'verify_rpc',side_effect=rpc.append),
                        patch.object(native.Acceptance,'local_api',return_value={'task':{'id':'offline-fixture','title':'synthetic'}}),
                        patch.object(native.Acceptance,'begin_replacement',begin),patch.object(native.Acceptance,'finish_replacement',finish),patch.object(native.Acceptance,'cleanup',cleanup),
                        patch.object(native,'identity',return_value={'ino':1}),patch.object(native,'same',return_value=True),patch.object(native,'tree_fingerprint',return_value='offline-fixed'),patch.object(native,'stopped'),
                        patch.object(observation,'object_metadata',side_effect=metadata),patch.object(observation,'trusted_package_version',side_effect=lambda:next(versions)),
                        patch.object(startup,'first_unsafe_pi_entry',return_value={'passed':True}),patch.object(parent.acl,'collect',side_effect=collect),
                        patch.object(native.signal,'signal'),contextlib.redirect_stdout(io.StringIO()),
                    ]
                    for item in patches:stack.enter_context(item)
                    self.assertEqual(parent.main(),0 if child_code==0 else 1)
                result=json.loads(report.read_text())
                self.assertEqual(result['publicAssetsVerified'],9)
                self.assertEqual(len(requests),10)
                self.assertEqual(requests[-1],('v1.0.2-rc.2','linux-host-v1.json'))
                self.assertTrue(result['cleanup']['passed']);self.assertTrue(result['parentRestoration']['passed'])
                self.assertEqual(restorations,list(parent.PARENTS));self.assertFalse(control.exists())
                self.assertTrue(result['piDiagnosticObserved'])
                self.assertTrue(all('observationUnavailable' in row for row in result['piObservation']['after']['aclChain']))
                self.assertEqual(result['piObservation']['updateStage']['exitCode'],child_code)
                names=[name for name,args in calls]
                self.assertEqual(names.count('pi-update'),1)
                self.assertEqual(result['acceptancePassed'],child_code==0)
                if child_code:
                    self.assertEqual(result['failure'],'stage failed: pi-update')
                    self.assertNotIn('awf-update',names);self.assertNotIn('start-after-pi',names)
                else:
                    self.assertTrue(result['piUpdate']['passed']);self.assertTrue(result['awfUpdate']['passed'])
                    self.assertEqual(health,[1,2,3]);self.assertEqual(rpc,['initial','after-pi','after-awf'])
                    self.assertLess(names.index('pi-update'),names.index('awf-update'))
                    self.assertEqual(names[-1],'stop-final')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--assets-root',required=True,type=Path)
    arguments,rest=parser.parse_known_args();ASSETS=arguments.assets_root
    unittest.main(argv=[sys.argv[0],*rest])
