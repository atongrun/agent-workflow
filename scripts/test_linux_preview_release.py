#!/usr/bin/env python3
"""Artifact tampering and publication-boundary tests; no network or installation."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import package_linux_preview as package
import publish_linux_preview as publisher


class FakeGitHub:
    def __init__(self,existing=False,wrong_tag=False,draft=False):
        self.existing=existing
        self.wrong_tag=wrong_tag
        self.draft=draft
        self.created_tag=False
        self.writes=[]
        self.assets=[]

    def optional(self,path):
        return {'exists':True} if self.existing else None

    def request(self,method,path,data=None,upload=False):
        if method!='GET':
            self.writes.append((method,path))
        if method=='GET' and '/commits/' in path:
            return {'sha':package.SOURCE_COMMIT}
        if method=='GET' and '/releases?per_page=' in path:
            return [{'tag_name':package.VERSION,'draft':True}] if self.draft else []
        if method=='POST' and path.endswith('/git/refs'):
            self.created_tag=True
            self.asserted_tag=data
            return {'ref':data['ref'],'object':{'type':'commit','sha':data['sha']}}
        if '/git/ref/tags/' in path:
            if not self.created_tag:
                raise AssertionError('draft has no tag until explicitly created')
            return {'object':{'type':'commit','sha':'a'*40 if self.wrong_tag else package.SOURCE_COMMIT}}
        if method=='POST' and path.endswith('/releases'):
            if not self.created_tag:
                raise AssertionError('tag must be explicitly created before draft')
            self.release={'id':42,'tag_name':package.VERSION,'draft':True,'prerelease':True,'upload_url':'https://uploads.github.com/repos/'+package.REPOSITORY+'/releases/42/assets{?name,label}','html_url':'https://github.com/'+package.REPOSITORY+'/releases/tag/'+package.VERSION}
            return self.release
        if method=='POST' and '?name=' in path:
            from urllib.parse import parse_qs,urlparse
            name=parse_qs(urlparse(path).query)['name'][0]
            result={'name':name,'size':len(data),'state':'uploaded','digest':'sha256:'+hashlib.sha256(data).hexdigest()}
            self.assets.append(result)
            return result
        if method=='GET' and '/assets?' in path:
            return self.assets
        if method=='PATCH':
            self.release.update(data)
            return self.release
        raise AssertionError((method,path))


class ReleaseBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.root=Path(self.temporary.name)
        self.workflow='1'*40
        host=b'fixture ELF, never executed'
        package.archive(self.root/package.NAMES[0],[('awf',host,0o755),('build.json',package.encode(dict(schema=1,version=package.VERSION,sourceCommit=package.SOURCE_COMMIT,os='linux',arch='amd64',hostProtocol='v1')),0o644)])
        package.archive(self.root/package.NAMES[1],[('awf.ts',b'fixture source',0o644),('extension.json',package.encode(dict(schema=1,version=package.VERSION,sourceCommit=package.SOURCE_COMMIT,extensionProtocol=1,piRPCVersion='1.0.2')),0o644)])
        for name in package.NAMES:
            if not (self.root/name).exists():
                (self.root/name).write_bytes(b'fixture text')
        template=Path(package.__file__).parent.joinpath('install-linux.sh').read_bytes()
        (self.root/'install-linux.sh').write_bytes(package.release_bootstrap(template))
        components=[]
        for cid in ('node','pi','awf-host','awf-extension','magpie'):
            rows=[dict(name=n,url=u,bytes=s,sha256=h,format=f) for c,v,n,u,s,h,f in package.INPUTS if c==cid]
            version=next((v for c,v,*_ in package.INPUTS if c==cid),package.VERSION)
            if cid in ('awf-host','awf-extension'):
                name=package.NAMES[0 if cid=='awf-host' else 1]
                rows=[dict(name=name,url='https://github.com/'+package.REPOSITORY+'/releases/download/'+package.VERSION+'/'+name,bytes=(self.root/name).stat().st_size,sha256=package.digest_file(self.root/name),format='tar.gz')]
            components.append(dict(id=cid,version=version,artifacts=rows))
        self.manifest=dict(schema=1,channel='linux-host-v1',version=package.VERSION,sourceCommit=package.SOURCE_COMMIT,installerProtocol=1,hostProtocol='v1',extensionProtocol=1,piRPCVersion='1.0.2',os='linux',arch='amd64',libc='glibc',components=components)
        (self.root/'linux-host-v1.json').write_bytes(package.encode(self.manifest))
        self.provenance=dict(sourceCommit=package.SOURCE_COMMIT,version=package.VERSION,repository=package.REPOSITORY,goVersion=package.GO_VERSION,goArchive=package.GO_ARCHIVE,bootstrapTemplateSHA256=package.BOOTSTRAP_TEMPLATE_SHA256,bootstrapManifestURL=package.BOOTSTRAP_MANIFEST_URL,workflowCommit=self.workflow,hostBinarySHA256=hashlib.sha256(host).hexdigest(),privateKitReused=False,nativeAcceptance=False,repeatedHostBuildIdentical=True,upstreamInputsVerified=[dict(component=c,version=v,name=n,url=u,bytes=s,sha256=h) for c,v,n,u,s,h,f in package.INPUTS])
        (self.root/'PROVENANCE.json').write_bytes(package.encode(self.provenance))
        self.resum()

    def tearDown(self):
        self.temporary.cleanup()

    def resum(self):
        (self.root/'SHA256SUMS').write_text(''.join(package.digest_file(self.root/n)+'  '+n+'\n' for n in sorted(package.NAMES) if n!='SHA256SUMS'))

    def test_existing_tag_or_release_causes_no_writes(self):
        api=FakeGitHub(existing=True)
        with self.assertRaisesRegex(ValueError,'already exists'):
            publisher.publish(self.root,api,self.workflow)
        self.assertEqual(api.writes,[])

    def test_wrong_new_tag_cannot_create_draft_or_publish(self):
        api=FakeGitHub(wrong_tag=True)
        with self.assertRaisesRegex(ValueError,'new tag'):
            publisher.publish(self.root,api,self.workflow)
        self.assertEqual(len(api.writes),1)
        self.assertTrue(api.writes[0][1].endswith('/git/refs'))

    def test_existing_draft_collision_causes_no_writes(self):
        api=FakeGitHub(draft=True)
        with self.assertRaisesRegex(ValueError,'draft/release collision'):
            publisher.publish(self.root,api,self.workflow)
        self.assertEqual(api.writes,[])

    def test_private_kit_or_unexpected_asset_rejected(self):
        (self.root/'private-kit.zip').write_bytes(b'forbidden fixture')
        with self.assertRaisesRegex(ValueError,'asset boundary'):
            package.verify(self.root)

    def test_changed_official_url_rejected_even_with_new_checksums(self):
        self.manifest['components'][0]['artifacts'][0]['url']='https://example.invalid/node.tar.gz'
        (self.root/'linux-host-v1.json').write_bytes(package.encode(self.manifest))
        self.resum()
        with self.assertRaisesRegex(ValueError,'official source'):
            package.verify(self.root)

    def test_changed_bootstrap_binding_rejected_even_with_new_checksums(self):
        p=self.root/'install-linux.sh'
        p.write_bytes(p.read_bytes().replace(package.BOOTSTRAP_MANIFEST_URL.encode(),b'https://example.invalid/manifest.json'))
        self.resum()
        with self.assertRaisesRegex(ValueError,'bootstrap release binding'):
            package.verify(self.root)

    def test_replayed_workflow_artifact_rejected_before_api_writes(self):
        api=FakeGitHub()
        with self.assertRaisesRegex(ValueError,'provenance'):
            publisher.publish(self.root,api,'2'*40)
        self.assertEqual(api.writes,[])

    def test_corrupt_bytes_rejected(self):
        (self.root/'install-linux.sh').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError,'checksum'):
            package.verify(self.root)

    def test_non_ci_wrong_branch_and_pr_rejected(self):
        env=dict(GITHUB_ACTIONS='true',GITHUB_REPOSITORY=package.REPOSITORY,GITHUB_EVENT_NAME='push',GITHUB_REF='refs/heads/'+package.TEST_BRANCH,GITHUB_SHA=self.workflow)
        self.assertEqual(publisher.ci_identity(env),self.workflow)
        for key,value in [('GITHUB_ACTIONS','false'),('GITHUB_REPOSITORY','other/repo'),('GITHUB_EVENT_NAME','pull_request'),('GITHUB_REF','refs/heads/main')]:
            changed=copy.deepcopy(env);changed[key]=value
            with self.assertRaises(ValueError):
                publisher.ci_identity(changed)

    def test_only_two_explicit_new_release_profiles(self):
        original = package.VERSION
        try:
            for version in package.VERSIONS:
                package.configure(version)
                self.assertIn(version, package.NAMES[0])
                payload = package.release_bootstrap(Path(package.__file__).with_name('install-linux.sh').read_bytes())
                package.verify_bootstrap(payload)
                self.assertIn(package.BOOTSTRAP_MANIFEST_URL.encode(), payload)
            for version in ('v1.0.1-rc.1', 'v1.0.0-rc.9', 'v1.0.1', 'latest'):
                with self.assertRaises(ValueError):
                    package.configure(version)
        finally:
            package.configure(original)

    def test_verified_fixture_publishes_only_new_prerelease(self):
        api=FakeGitHub()
        result=publisher.publish(self.root,api,self.workflow)
        self.assertEqual(result['sourceCommit'],package.SOURCE_COMMIT)
        self.assertEqual(len(api.assets),len(package.NAMES))
        self.assertFalse(api.release['draft'])
        self.assertTrue(api.release['prerelease'])
        self.assertEqual(api.release['make_latest'],'false')
        self.assertEqual(api.asserted_tag,dict(ref='refs/tags/'+package.VERSION,sha=package.SOURCE_COMMIT))


if __name__=='__main__':
    unittest.main()
