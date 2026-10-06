#!/usr/bin/env python3
"""Publish one new approved Linux preview from its isolated CI job."""
import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
import urllib.request

import package_linux_preview as package

from package_linux_preview import INPUTS, REPOSITORY, SOURCE_COMMIT, TEST_BRANCH, digest_file, verify


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise ValueError('authenticated GitHub API redirect refused')


def ci_identity(environment):
    if environment.get('GITHUB_ACTIONS')!='true' or environment.get('GITHUB_REPOSITORY')!=REPOSITORY or environment.get('GITHUB_EVENT_NAME')!='push' or environment.get('GITHUB_REF')!='refs/heads/'+TEST_BRANCH:
        raise ValueError('publication requires the exact approved repository/branch push CI job')
    sha=environment.get('GITHUB_SHA','')
    import re
    if not re.fullmatch('[0-9a-f]{40}',sha):
        raise ValueError('exact workflow SHA required')
    return sha


class GitHub:
    def __init__(self, token):
        if not token:
            raise ValueError('short-lived CI token missing')
        self.token=token
        self.opener=urllib.request.build_opener(NoRedirect())

    def request(self, method, path, data=None, upload=False):
        base='https://uploads.github.com' if upload else 'https://api.github.com'
        if not path.startswith('/repos/'+REPOSITORY+'/'):
            raise ValueError('GitHub repository boundary refused')
        headers={'Authorization':'Bearer '+self.token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','User-Agent':'AWF-Linux-Preview-Release'}
        if isinstance(data,dict):
            data=json.dumps(data).encode()
            headers['Content-Type']='application/json'
        elif data is not None:
            headers['Content-Type']='application/octet-stream'
        request=urllib.request.Request(base+path,data=data,headers=headers,method=method)
        with self.opener.open(request,timeout=120) as response:
            payload=response.read(4<<20)
            if response.read(1):
                raise ValueError('GitHub response size limit')
            return json.loads(payload)

    def optional(self,path):
        try:
            return self.request('GET',path)
        except HTTPError as error:
            if error.code==404:
                return None
            raise


def publish(output, api, workflow_commit):
    provenance=verify(output,workflow_commit)
    expected=[dict(component=c,version=v,name=n,url=u,bytes=s,sha256=h) for c,v,n,u,s,h,f in INPUTS]
    if provenance['upstreamInputsVerified']!=expected:
        raise ValueError('all pinned official inputs must be verified before publication')
    base='/repos/'+REPOSITORY+'/'
    if api.optional(base+'git/ref/tags/'+package.VERSION) is not None or api.optional(base+'releases/tags/'+package.VERSION) is not None:
        raise ValueError('tag/release already exists; never overwrite or reuse it')
    # The tag endpoint only returns published releases. Writers must also check
    # paginated authenticated listings, which include drafts, before mutation.
    for page in range(1,11):
        releases=api.request('GET',base+'releases?per_page=100&page='+str(page))
        if not isinstance(releases,list) or any(r.get('tag_name')==package.VERSION for r in releases):
            raise ValueError('draft/release collision or invalid listing; never reuse it')
        if len(releases)<100:
            break
    else:
        raise ValueError('release listing exceeds bounded collision check; inspect first')
    source=api.request('GET',base+'commits/'+SOURCE_COMMIT)
    if source.get('sha')!=SOURCE_COMMIT:
        raise ValueError('reviewed source is unavailable on GitHub')
    # Draft releases may defer tag creation. Create this one new lightweight
    # reference explicitly; failures leave only our new ref for inspection.
    api.request('POST',base+'git/refs',dict(ref='refs/tags/'+package.VERSION,sha=SOURCE_COMMIT))
    tag=api.request('GET',base+'git/ref/tags/'+package.VERSION)
    if tag.get('object',{}).get('type')!='commit' or tag['object']['sha']!=SOURCE_COMMIT:
        raise ValueError('new tag source differs; inspect without draft or publication')
    body='Linux amd64 preview. Native public bootstrap, cross-version AWF update and actual same-prefix Pi update are pending for these candidate bytes. Linux channel promotion requires separate successful Ubuntu 24.04 acceptance.\n\nSource: `'+SOURCE_COMMIT+'`\nPackaging workflow: `'+workflow_commit+'`\n\nUse the release-specific public install-linux.sh with --allow-prerelease. AWF owns machine lifecycle; official Pi owns its sole /opt/pi-cli update. Initial Node/Pi/Magpie inputs remain fixed official downloads. No model calls, production credentials or private kit. Windows RC9 and existing releases remain unchanged. Companion Go notices and SHA256SUMS are supplied.\n'
    release=api.request('POST',base+'releases',dict(tag_name=package.VERSION,target_commitish=SOURCE_COMMIT,name='AWF Linux preview '+package.VERSION,body=body,draft=True,prerelease=True,make_latest='false'))
    release_id=release['id']
    if not isinstance(release_id,int) or release_id<=0 or release.get('tag_name')!=package.VERSION or release.get('draft') is not True or release.get('prerelease') is not True:
        raise ValueError('unexpected draft release response; inspect without automatic cleanup')
    upload=urlparse(release['upload_url'].split('{',1)[0])
    wanted=base+'releases/'+str(release_id)+'/assets'
    if upload.scheme!='https' or upload.netloc!='uploads.github.com' or upload.path!=wanted or upload.query or upload.fragment:
        raise ValueError('unexpected release upload destination')
    tag=api.request('GET',base+'git/ref/tags/'+package.VERSION)
    if tag.get('object',{}).get('type')!='commit' or tag['object']['sha']!=SOURCE_COMMIT:
        raise ValueError('draft tag source differs; inspect without publication')
    for name in package.NAMES:
        p=output/name
        result=api.request('POST',wanted+'?name='+quote(name,safe=''),p.read_bytes(),upload=True)
        if result.get('name')!=name or result.get('size')!=p.stat().st_size or result.get('state')!='uploaded' or result.get('digest') not in (None,'sha256:'+digest_file(p)):
            raise ValueError('uploaded asset metadata differs; draft requires inspection')
    uploaded=api.request('GET',wanted+'?per_page=100')
    if len(uploaded)!=len(package.NAMES) or {r.get('name') for r in uploaded}!=set(package.NAMES):
        raise ValueError('release asset inventory differs; draft requires inspection')
    tag=api.request('GET',base+'git/ref/tags/'+package.VERSION)
    if tag.get('object',{}).get('type')!='commit' or tag['object']['sha']!=SOURCE_COMMIT:
        raise ValueError('tag source changed; draft requires inspection')
    final=api.request('PATCH',base+'releases/'+str(release_id),dict(draft=False,prerelease=True,make_latest='false'))
    if final.get('draft') is not False or final.get('prerelease') is not True or final.get('tag_name')!=package.VERSION:
        raise ValueError('publication confirmation differs; inspect release state')
    tag=api.request('GET',base+'git/ref/tags/'+package.VERSION)
    if tag.get('object',{}).get('type')!='commit' or tag['object']['sha']!=SOURCE_COMMIT:
        raise ValueError('public release tag source differs')
    return dict(release=final.get('html_url'),tag=package.VERSION,sourceCommit=SOURCE_COMMIT,workflowCommit=workflow_commit,assets=[dict(name=n,bytes=(output/n).stat().st_size,sha256=digest_file(output/n)) for n in package.NAMES],nativeAcceptance=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True, choices=package.VERSIONS)
    parser.add_argument('--assets',required=True,type=Path)
    args=parser.parse_args()
    package.configure(args.version)
    sha=ci_identity(os.environ)
    # Build/publication use the same frozen packaging checkout; the CI job
    # identity is checked separately so one approved VM can also run acceptance.
    packaging_commit=package.git(Path(__file__).resolve().parent.parent,'rev-parse','HEAD').decode().strip()
    result=publish(args.assets,GitHub(os.environ.get('GH_TOKEN')),packaging_commit)
    result['executionWorkflowCommit']=sha
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
