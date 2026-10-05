#!/usr/bin/env python3
"""Publish only this approved TEST ONLY release from its isolated CI job."""
import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
import urllib.request

from package_linux import INPUTS, NAMES, REPOSITORY, SOURCE_COMMIT, TEST_BRANCH, VERSION, digest_file, verify


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
        headers={'Authorization':'Bearer '+self.token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','User-Agent':'AWF-Linux-Test-Release'}
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
    if api.optional(base+'git/ref/tags/'+VERSION) is not None or api.optional(base+'releases/tags/'+VERSION) is not None:
        raise ValueError('tag/release already exists; never overwrite or reuse it')
    # The tag endpoint only returns published releases. Writers must also check
    # paginated authenticated listings, which include drafts, before mutation.
    for page in range(1,11):
        releases=api.request('GET',base+'releases?per_page=100&page='+str(page))
        if not isinstance(releases,list) or any(r.get('tag_name')==VERSION for r in releases):
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
    api.request('POST',base+'git/refs',dict(ref='refs/tags/'+VERSION,sha=SOURCE_COMMIT))
    tag=api.request('GET',base+'git/ref/tags/'+VERSION)
    if tag.get('object',{}).get('type')!='commit' or tag['object']['sha']!=SOURCE_COMMIT:
        raise ValueError('new tag source differs; inspect without draft or publication')
    body='TEST ONLY — Linux amd64 installer prerelease.\n\nNative Ubuntu/Debian installation, CloudCone acceptance, actual same-prefix pi update and model-backed E2E remain unverified. No production secrets or model calls were used in CI.\n\nSource commit: `'+SOURCE_COMMIT+'`\nWorkflow/packaging commit: `'+workflow_commit+'`\n\nThis release redistributes AWF Host/extension/bootstrap/source and necessary embedded Go notices. Node/npm, Pi and Magpie are downloaded separately from the canonical official URLs and fixed hashes in `linux-host-v1.json`. AWF own copyright/license status remains unchanged. The private kit is not distributed. Windows RC9 and existing channels remain unchanged.\n\nUse this release-specific manifest explicitly with `--allow-prerelease`. The default Linux channel remains unpublished. Verify `SHA256SUMS` and retain the companion `THIRD_PARTY_NOTICES.txt` with the Host archive.\n'
    release=api.request('POST',base+'releases',dict(tag_name=VERSION,target_commitish=SOURCE_COMMIT,name='AWF Linux TEST ONLY '+VERSION,body=body,draft=True,prerelease=True,make_latest='false'))
    release_id=release['id']
    if not isinstance(release_id,int) or release_id<=0 or release.get('tag_name')!=VERSION or release.get('draft') is not True or release.get('prerelease') is not True:
        raise ValueError('unexpected draft release response; inspect without automatic cleanup')
    upload=urlparse(release['upload_url'].split('{',1)[0])
    wanted=base+'releases/'+str(release_id)+'/assets'
    if upload.scheme!='https' or upload.netloc!='uploads.github.com' or upload.path!=wanted or upload.query or upload.fragment:
        raise ValueError('unexpected release upload destination')
    tag=api.request('GET',base+'git/ref/tags/'+VERSION)
    if tag.get('object',{}).get('type')!='commit' or tag['object']['sha']!=SOURCE_COMMIT:
        raise ValueError('draft tag source differs; inspect without publication')
    for name in NAMES:
        p=output/name
        result=api.request('POST',wanted+'?name='+quote(name,safe=''),p.read_bytes(),upload=True)
        if result.get('name')!=name or result.get('size')!=p.stat().st_size or result.get('state')!='uploaded' or result.get('digest') not in (None,'sha256:'+digest_file(p)):
            raise ValueError('uploaded asset metadata differs; draft requires inspection')
    uploaded=api.request('GET',wanted+'?per_page=100')
    if len(uploaded)!=len(NAMES) or {r.get('name') for r in uploaded}!=set(NAMES):
        raise ValueError('release asset inventory differs; draft requires inspection')
    tag=api.request('GET',base+'git/ref/tags/'+VERSION)
    if tag.get('object',{}).get('type')!='commit' or tag['object']['sha']!=SOURCE_COMMIT:
        raise ValueError('tag source changed; draft requires inspection')
    final=api.request('PATCH',base+'releases/'+str(release_id),dict(draft=False,prerelease=True,make_latest='false'))
    if final.get('draft') is not False or final.get('prerelease') is not True or final.get('tag_name')!=VERSION:
        raise ValueError('publication confirmation differs; inspect release state')
    tag=api.request('GET',base+'git/ref/tags/'+VERSION)
    if tag.get('object',{}).get('type')!='commit' or tag['object']['sha']!=SOURCE_COMMIT:
        raise ValueError('public release tag source differs')
    return dict(release=final.get('html_url'),tag=VERSION,sourceCommit=SOURCE_COMMIT,workflowCommit=workflow_commit,assets=[dict(name=n,bytes=(output/n).stat().st_size,sha256=digest_file(output/n)) for n in NAMES],nativeAcceptance=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets',required=True,type=Path)
    args=parser.parse_args()
    sha=ci_identity(os.environ)
    result=publish(args.assets,GitHub(os.environ.get('GH_TOKEN')),sha)
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
