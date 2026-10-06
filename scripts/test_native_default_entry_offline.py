#!/usr/bin/env python3
"""Actual default-entry wiring with exact assets and explicit offline boundaries.

HTTP/root/systemd/RPC/replacement are substituted; local child processes,
stdin, downloads, pinned-asset verification and atomic reports are real.
This fixture never establishes native acceptance.
"""
import argparse
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import native_acceptance as native
import native_ci_parent as parent

ASSETS = None
CHANNEL_SOURCE = None


def verify_report(r,phase,offline=False):
    native.require(phase in ('upgrade','default'),'unknown default-entry phase')
    native.require(r['sourceCommit']==native.probe.SOURCE and r['workflowCommit']==os.environ['GITHUB_SHA'],'report identity differs')
    native.require(r['defaultEntryAcceptance'] is True and r['acceptancePassed'] is True and r['mode']==phase,'actual default-entry acceptance absent')
    native.require(r['cleanup']['passed'] and r['parentRestoration']['passed'] and r['parentRestoration']['privateReceiptRemoved'],'complete cleanup/restoration absent')
    native.require(all(p['passed'] and p['aclRestored'] and p['identityPreserved'] for p in r['parentRestoration']['parents']) and {p['path'] for p in r['parentRestoration']['parents']}==set(parent.PARENTS),'exact parent ACL restoration absent')
    native.require(r['modelCalls']==0 and r['providerAuthenticationPerformed'] is False and r['piUpdateExecuted'] is False,'unexpected provider or Pi update execution')
    native.require(r['publicAssetsVerified']==9 and r['preinstalledRuntimePreserved'],'pinned assets or existing runtime preservation absent')
    channel=r['channelManifest']
    native.require(channel['expectedCommit']==native.CHANNEL_COMMIT and channel['version']==native.TARGET_VERSION and channel['sha256']==native.PINS_BY_VERSION[native.TARGET_VERSION]['linux-host-v1.json'][1] and channel['beforeVerified'] and channel['afterVerified'],'frozen channel observations absent')
    bootstrap=r['publicBootstrap']
    native.require(bootstrap['passed'] and bootstrap['localManifestOverride'] is False and bootstrap['localArchiveOverride'] is False and bootstrap['source']==('release' if phase=='upgrade' else 'channel'),'actual bootstrap source differs')
    noop=r['noOp']
    native.require(noop['passed'] and noop['command']=='awf update' and noop['version']==native.TARGET_VERSION and all(noop[k] for k in ('programRootsPreserved','receiptPreserved','servicePIDsPreserved')),'bare same-version no-op absent')
    native.require(r['rpcCompatibility'] and all(p['passed'] and p['productionExtensionLoaded'] and p['modelRequests']==0 for p in r['rpcCompatibility']),'production extension RPC absent')
    if phase=='upgrade':
        update=r['awfUpdate']
        native.require(update['passed'] and update['fromVersion']=='v1.0.2-rc.1' and update['toVersion']==native.TARGET_VERSION and update['defaultChannelSelection'] is True and update['explicitImmutableVersion'] is False and update['currentPiTreePreserved'] and update['retainedBackupCount']==3 and r['businessStatePreserved']['passed'],'bare cross-version update absent')
    else:
        native.require(r['version']==native.TARGET_VERSION,'default bootstrap selected wrong version')
    if not offline:
        native.require(r['preflight']['kind']=='awf-standard-runner-readonly-preflight' and r['preflight']['preflightPassed'] and not r['cleanup'].get('offlineBoundarySubstitution'),'fixture is not native acceptance')


class DefaultEntryTests(unittest.TestCase):
    def test_mixed_or_missing_phase_refused_before_parent_preparation(self):
        for flags in ([],['--phase','default','--acl-full-acceptance'],['--phase','upgrade','--pi-update-diagnostic']):
            args=['parent','--expected-release','24.04','--report','/tmp/fixture-report','--prepare-ci-parents','--default-entry-acceptance',*flags]
            with self.subTest(flags=flags),patch('sys.argv',args),patch.object(native.probe,'ci_guard'),patch.object(parent,'prepare') as prepare:
                with self.assertRaisesRegex(native.TestFailure,'one exact phase'):parent.main()
                prepare.assert_not_called()

    def test_new_guard_rejects_previous_execution_branch(self):
        env=dict(GITHUB_ACTIONS='true',RUNNER_ENVIRONMENT='github-hosted',RUNNER_OS='Linux',GITHUB_REPOSITORY=native.probe.REPOSITORY,GITHUB_REF='refs/heads/'+native.probe.BRANCH,GITHUB_EVENT_NAME='push',GITHUB_SHA='c'*40)
        native.probe.ci_guard(env,0,0)
        env['GITHUB_REF']='refs/heads/awf/linux-acl-native-once-20261006'
        with self.assertRaises(ValueError):native.probe.ci_guard(env,0,0)

    def test_real_parent_native_download_cross_and_default_entries(self):
        self.assertIsNotNone(ASSETS);self.assertIsNotNone(CHANNEL_SOURCE)
        for version,pins in native.PINS_BY_VERSION.items():
            native.package.configure(version);native.package.verify(ASSETS/version,native.PACKAGING_COMMIT)
            for name,(size,sha) in pins.items():
                p=ASSETS/version/name
                self.assertEqual((p.stat().st_size,native.package.digest_file(p)),(size,sha))
        self.assertEqual((CHANNEL_SOURCE.stat().st_size,native.package.digest_file(CHANNEL_SOURCE)),tuple(native.CHANNEL_BOOTSTRAP_PIN))
        cases=[(phase,code,False) for phase in ('upgrade','default') for code in (0,7)]+[('upgrade',0,True)]
        for phase,child_code,bad_channel in cases:
                passed=not child_code and not bad_channel
                with self.subTest(phase=phase,child_code=child_code,bad_channel=bad_channel),tempfile.TemporaryDirectory(prefix='awf-default-entry-') as temp:
                    root=Path(temp);control=root/'control';state=root/'parent';report=root/'report.json'
                    fixture=root/'installed';fixture.write_bytes(b'installed fixture')
                    child=root/'child.py'
                    child.write_text("""import pathlib,sys
name,root,code=sys.argv[1:];root=pathlib.Path(root)
if name=='awf-update':
    assert sys.stdin.buffer.read()==b'y\\n'
    print('AWF Linux update: v1.0.2-rc.1 -> v1.0.2-rc.2')
    sys.exit(int(code))
elif name=='awf-default-update':
    print('AWF bundle verify-current: completed\\nAWF v1.0.2-rc.2 verified.')
    sys.exit(int(code) if (root/'fail-default').exists() else 0)
elif name=='pi-root-agent-default':print(str(root/'pi-root-home/.pi/agent'),end='')
""")
                    calls=[];requests=[];restored=[]
                    real_command=native.Acceptance.command;real_digest=native.package.digest_file;real_read=Path.read_bytes
                    record=dict(parents=[dict(path=p,applied=True,originalACL={'access':{'status':'absent'},'default':{'status':'absent'}}) for p in parent.PARENTS])
                    class Opener:
                        def open(self,url,timeout):
                            requests.append(url)
                            if url==native.CHANNEL_BOOTSTRAP:return CHANNEL_SOURCE.open('rb')
                            if url==native.CHANNEL_MANIFEST:
                                return io.BytesIO(b'wrong channel') if bad_channel else (ASSETS/native.TARGET_VERSION/'linux-host-v1.json').open('rb')
                            prefix='https://github.com/'+native.probe.REPOSITORY+'/releases/download/'
                            if not url.startswith(prefix):raise AssertionError('unexpected URL')
                            version,name=url[len(prefix):].split('/',1)
                            if version not in native.PINS_BY_VERSION or name not in native.PINS_BY_VERSION[version]:raise AssertionError('unexpected asset')
                            return (ASSETS/version/name).open('rb')
                    def command(runner,name,args,seconds,capture=False,environment=None,input_data=None):
                        calls.append((name,args))
                        if name=='install':
                            self.assertIn('--allow-prerelease',args)
                            self.assertFalse(any(a in args for a in ('--manifest','--archive','--version')))
                            self.assertEqual(Path(args[-2]).name,'install-linux.sh' if phase=='upgrade' else 'channel-install-linux.sh')
                            if phase=='default' and child_code:(control/'fail-default').touch()
                        if name=='awf-update':
                            self.assertEqual(args,['/usr/local/bin/awf','update']);self.assertEqual(input_data,b'y\n')
                        if name=='awf-default-update':
                            self.assertEqual(args,['/usr/local/bin/awf','update']);self.assertIsNone(input_data)
                        return real_command(runner,name,[sys.executable,str(child),name,str(control),str(child_code)],seconds,capture,environment,input_data)
                    def prepare(context):
                        state.mkdir(mode=0o700);(state/'parent.json').write_text(json.dumps(record));context['stateCreated']=True
                        return record
                    def restore(rec):
                        restored.extend(parent.PARENTS)
                        return dict(passed=True,parents=[dict(path=p,passed=True,aclRestored=True,identityPreserved=True,observedBeforeRestoreMode='0755') for p in parent.PARENTS])
                    def begin(runner,target):runner.ledger['transitions'].append(dict(target=target,roots=[],completed=False))
                    def finish(runner):runner.ledger['transitions'][-1]['completed']=True
                    def cleanup(runner):runner.report['cleanup']=dict(passed=True,offlineBoundarySubstitution=True)
                    def rpc(runner,name):runner.report.setdefault('rpcCompatibility',[]).append(dict(phase=name,passed=True,productionExtensionLoaded=True,modelRequests=0))
                    def installed(runner):runner.report['preinstalledRuntimePreserved']=True
                    previous=lambda p,d:json.loads(p.read_text()) if p.exists() else d
                    env=dict(GITHUB_SHA='c'*40,GITHUB_REF='refs/heads/'+native.probe.BRANCH)
                    args=['parent','--expected-release','24.04','--report',str(report),'--prepare-ci-parents','--default-entry-acceptance','--phase',phase]
                    with contextlib.ExitStack() as stack:
                        patches=[patch('sys.argv',args),patch.dict(os.environ,env),patch.object(native,'CONTROL',control),patch.object(parent,'STATE',state),
                            patch.object(native.probe,'ci_guard'),patch.object(native.probe,'inspect',return_value={'preflightPassed':True,'offlineBoundarySubstitution':True}),
                            patch.object(native,'capture_existing_runtime',return_value={'fixture':True}),patch.object(native.probe,'run',return_value='LoadState=not-found\nFragmentPath=\nDropInPaths=\n'),
                            patch.object(parent,'prepare',side_effect=prepare),patch.object(parent,'load_state',return_value=record),patch.object(parent,'restore',side_effect=restore),patch.object(parent,'protect_retry',return_value=[]),
                            patch.object(native,'previous_report',side_effect=previous),patch.object(native.urllib.request,'build_opener',return_value=Opener()),
                            patch.object(native.package,'digest_file',side_effect=lambda p:real_digest(fixture if str(p).startswith(('/opt/','/etc/awf/')) else p)),
                            patch.object(Path,'read_bytes',autospec=True,side_effect=lambda p: b'fixed receipt' if str(p)=='/etc/awf/install.json' else real_read(p)),
                            patch.object(native.Acceptance,'command',command),patch.object(native.Acceptance,'observe'),patch.object(native.Acceptance,'resources'),
                            patch.object(native.Acceptance,'verify_install',installed),patch.object(native.Acceptance,'health'),patch.object(native.Acceptance,'verify_rpc',rpc),
                            patch.object(native.Acceptance,'local_api',return_value={'task':{'id':'fixture','title':'synthetic'}}),patch.object(native.Acceptance,'begin_replacement',begin),patch.object(native.Acceptance,'finish_replacement',finish),patch.object(native.Acceptance,'cleanup',cleanup),
                            patch.object(native,'identity',return_value={'ino':1}),patch.object(native,'same',return_value=True),patch.object(native,'tree_fingerprint',return_value='fixed'),patch.object(native,'stopped'),patch.object(native,'unit_status',return_value={'MainPID':'123'}),
                            patch.object(parent.acl,'collect',return_value=[]),patch.object(native.signal,'signal'),contextlib.redirect_stdout(io.StringIO())]
                        for item in patches:stack.enter_context(item)
                        self.assertEqual(parent.main(),0 if passed else 1)
                        with patch('sys.argv',['parent','--expected-release','24.04','--report',str(report),'--cleanup-only']):self.assertEqual(parent.main(),0)
                        result=json.loads(report.read_text())
                        self.assertEqual(result['acceptancePassed'],passed)
                        self.assertTrue(result['parentRestoration']['privateReceiptRemoved']);self.assertFalse(control.exists());self.assertFalse(state.exists())
                        self.assertEqual(restored,list(parent.PARENTS)*2)
                        self.assertEqual(result['publicAssetsVerified'],9)
                        self.assertFalse(result['piUpdateExecuted']);self.assertNotIn('pi-update',[name for name,args in calls])
                        if bad_channel:
                            self.assertEqual(result['failure'],'public bytes differ from pin')
                            self.assertEqual(calls,[])
                        elif child_code:
                            self.assertEqual(result['failure'],'stage failed: '+('awf-update' if phase=='upgrade' else 'awf-default-update'))
                            self.assertNotIn('afterVerified',result['channelManifest'])
                            with self.assertRaises((native.TestFailure,KeyError)):verify_report(result,phase,offline=True)
                        else:
                            self.assertEqual(requests.count(native.CHANNEL_MANIFEST),2)
                            self.assertEqual(requests.count(native.CHANNEL_BOOTSTRAP),int(phase=='default'))
                            verify_report(result,phase,offline=True)
                            with self.assertRaises((native.TestFailure,KeyError)):verify_report(result,phase)
                            for key in ('acceptancePassed','defaultEntryAcceptance'):
                                bad=copy.deepcopy(result);bad[key]=False
                                with self.assertRaises(native.TestFailure):verify_report(bad,phase,offline=True)
                            if phase=='upgrade':
                                bad=copy.deepcopy(result);bad['awfUpdate'].update(defaultChannelSelection=False,explicitImmutableVersion=True)
                                with self.assertRaisesRegex(native.TestFailure,'bare cross-version'):verify_report(bad,phase,offline=True)
                    native.package.configure('v1.0.2-rc.1')
                    native.probe.RELEASE='v1.0.2-rc.1';native.PINS=native.PINS_BY_VERSION[native.probe.RELEASE]


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--assets-root',type=Path);parser.add_argument('--channel-source',type=Path)
    parser.add_argument('--verify-report',type=Path);parser.add_argument('--phase',choices=('upgrade','default'))
    args,rest=parser.parse_known_args()
    if args.verify_report:
        verify_report(json.loads(args.verify_report.read_text()),args.phase)
    else:
        ASSETS=args.assets_root;CHANNEL_SOURCE=args.channel_source
        unittest.main(argv=[sys.argv[0],*rest])
