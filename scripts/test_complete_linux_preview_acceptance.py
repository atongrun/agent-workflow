#!/usr/bin/env python3
"""Metadata mutation tests use only substituted API responses."""
import copy
import unittest

import complete_linux_preview_acceptance as finish

SHA='c'*40


def reports():
    data={}
    for mode,version in [('upgrade','v1.0.1-rc.4'),('default','v1.0.1-rc.5')]:
        data[mode]=dict(schema=1,sourceCommit=finish.native.probe.SOURCE,workflowCommit=SHA,version=version,mode=mode,
            acceptancePassed=True,cleanup=dict(passed=True),parentRestoration=dict(passed=True,privateReceiptRemoved=True),modelCalls=0,
            providerAuthenticationPerformed=False,preinstalledRuntimePreserved=True,
            publicBootstrap=dict(passed=True,localManifestOverride=False,localArchiveOverride=False,source='release' if mode=='upgrade' else 'channel'))
    data['upgrade'].update(piUpdate=dict(passed=True,officialCommand='pi update',solePrefix='/opt/pi-cli',postinstallScriptsEnabled=False,inheritedShellUmask='0002',shellUmaskAfter='0002'),piPermissionCheck=dict(passed=True),awfUpdate=dict(passed=True,fromVersion='v1.0.1-rc.4',toVersion='v1.0.1-rc.5',currentPiTreePreserved=True),businessStatePreserved=dict(passed=True))
    data['default']['noOp']=dict(passed=True,command='awf update')
    return data


class API:
    def __init__(self):
        self.writes=[]
        self.releases={}
        self.assets={}
        pending='Linux amd64 preview. Native public bootstrap, cross-version AWF update and actual same-prefix Pi update are pending for these candidate bytes. Linux channel promotion requires separate successful Ubuntu 24.04 acceptance.'
        for ident,(version,pins) in enumerate(finish.native.PINS_BY_VERSION.items(),1):
            self.releases[version]=dict(id=ident,tag_name=version,draft=False,prerelease=True,body=pending+'\n\nSource: fixture')
            self.assets[version]=[dict(name=n,size=s,state='uploaded',digest='sha256:'+h) for n,(s,h) in pins.items()]

    def request(self,method,path,data=None):
        if '/git/ref/tags/' in path:
            return dict(object=dict(type='commit',sha=finish.native.probe.SOURCE))
        if '/releases/tags/' in path:
            return copy.deepcopy(self.releases[path.rsplit('/',1)[1]])
        ident=int(path.split('/releases/',1)[1].split('/',1)[0])
        version=next(v for v,r in self.releases.items() if r['id']==ident)
        if method=='PATCH':
            self.writes.append((path,data))
            self.releases[version]['body']=data['body']
            return copy.deepcopy(self.releases[version])
        return copy.deepcopy(self.assets[version])


class CompletionTests(unittest.TestCase):
    def test_failed_phase_cleanup_or_identity_blocks_every_write(self):
        for mode,field in [('upgrade','acceptancePassed'),('default','acceptancePassed'),('upgrade','workflowCommit')]:
            data=reports()
            data[mode][field]=False
            api=API()
            with self.subTest(mode=mode,field=field),self.assertRaises(finish.native.TestFailure):
                finish.complete(api,data,SHA,'123')
            self.assertEqual(api.writes,[])
        for mode in ('upgrade','default'):
            data=reports()
            data[mode]['parentRestoration']['privateReceiptRemoved']=False
            api=API()
            with self.assertRaises(finish.native.TestFailure): finish.complete(api,data,SHA,'123')
            self.assertEqual(api.writes,[])

    def test_second_release_asset_drift_blocks_every_write(self):
        api=API()
        api.assets['v1.0.1-rc.5'][0]['digest']='sha256:'+'0'*64
        with self.assertRaisesRegex(finish.native.TestFailure,'digest differs'):
            finish.complete(api,reports(),SHA,'123')
        self.assertEqual(api.writes,[])

    def test_unsafe_pi_or_noop_failure_cannot_be_promoted(self):
        for mode,key in [('upgrade','piPermissionCheck'),('default','noOp')]:
            data=reports()
            data[mode][key]['passed']=False
            api=API()
            with self.assertRaises(finish.native.TestFailure): finish.complete(api,data,SHA,'123')
            self.assertEqual(api.writes,[])

    def test_success_changes_only_two_new_release_descriptions_and_keeps_assets(self):
        api=API()
        before=copy.deepcopy(api.assets)
        result=finish.complete(api,reports(),SHA,'123')
        self.assertTrue(result['nativeAcceptance'])
        self.assertEqual(len(api.writes),2)
        self.assertEqual(api.assets,before)
        for path,data in api.writes:
            self.assertIn('/releases/',path)
            self.assertEqual(set(data),{'body','prerelease','make_latest'})
            self.assertTrue(data['prerelease'])
            self.assertEqual(data['make_latest'],'false')
            self.assertIn('RC2/RC3 upgrades are unsupported',data['body'])
            self.assertNotIn('are pending for these candidate bytes',data['body'])


if __name__=='__main__': unittest.main()
