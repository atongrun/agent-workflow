#!/usr/bin/env python3
"""Verify fixed candidate bytes; mark only these two new previews after acceptance."""
import argparse
import json
import os
from pathlib import Path
import re

import native_acceptance as native
import publish_linux_preview as publish


def verify_built_assets(root):
    for version,pins in native.PINS_BY_VERSION.items():
        output=root/version
        native.require({p.name for p in output.iterdir()}==set(pins),'candidate asset inventory differs')
        for name,(size,sha) in pins.items():
            path=output/name
            native.require(path.is_file() and not path.is_symlink() and path.stat().st_size==size and native.package.digest_file(path)==sha,'candidate bytes differ from independently fixed pins')


def verify_reports(reports,sha):
    for mode,version in [('upgrade','v1.0.1-rc.4'),('default',native.TARGET_VERSION)]:
        r=reports[mode]
        native.require(r['schema']==1 and r['sourceCommit']==native.probe.SOURCE and r['workflowCommit']==sha and r['version']==version and r['mode']==mode,'acceptance identity differs')
        native.require(r['acceptancePassed'] is True and r['cleanup']['passed'] is True and r['parentRestoration']['passed'] is True and r['parentRestoration']['privateReceiptRemoved'] is True,'acceptance or cleanup incomplete')
        native.require(r['modelCalls']==0 and r['providerAuthenticationPerformed'] is False and r['preinstalledRuntimePreserved'] is True,'acceptance isolation differs')
        b=r['publicBootstrap']
        native.require(b['passed'] is True and b['localManifestOverride'] is False and b['localArchiveOverride'] is False and b['source']==('release' if mode=='upgrade' else 'channel'),'public bootstrap not established')
    r=reports['upgrade']
    p=r['piUpdate']
    native.require(p['passed'] is True and p['officialCommand']=='pi update' and p['solePrefix']=='/opt/pi-cli' and p['postinstallScriptsEnabled'] is False and p['inheritedShellUmask']==p['shellUmaskAfter']=='0002' and r['piPermissionCheck']['passed'] is True,'official same-prefix safe Pi update not established')
    a=r['awfUpdate']
    native.require(a['passed'] is True and a['fromVersion']=='v1.0.1-rc.4' and a['toVersion']==native.TARGET_VERSION and a['currentPiTreePreserved'] is True and r['businessStatePreserved']['passed'] is True,'cross-version preservation not established')
    native.require(reports['default']['noOp']['passed'] is True and reports['default']['noOp']['command']=='awf update','bare update no-op not established')


def release_inventory(api,version):
    base='/repos/'+native.probe.REPOSITORY+'/'
    release=api.request('GET',base+'releases/tags/'+version)
    native.require(isinstance(release['id'],int) and release['id']>0 and release['tag_name']==version and release['draft'] is False and release['prerelease'] is True,'candidate release identity differs')
    tag=api.request('GET',base+'git/ref/tags/'+version)
    native.require(tag['object'].get('type')=='commit' and tag['object'].get('sha')==native.probe.SOURCE,'candidate tag differs')
    assets=api.request('GET',base+'releases/'+str(release['id'])+'/assets?per_page=100')
    pins=native.PINS_BY_VERSION[version]
    native.require(len(assets)==len(pins) and {a['name'] for a in assets}==set(pins),'candidate release inventory differs')
    for a in assets:
        size,sha=pins[a['name']]
        native.require(a['size']==size and a['state']=='uploaded' and a['digest']=='sha256:'+sha,'candidate release digest differs')
    return release,assets


def complete(api,reports,sha,run_id):
    verify_reports(reports,sha)
    native.require(re.fullmatch('[0-9]{1,20}',run_id) is not None,'run identity invalid')
    # Check both complete inventories before the first release metadata mutation.
    releases=[(v,*release_inventory(api,v)) for v in native.PINS_BY_VERSION]
    pending='Linux amd64 preview. Native public bootstrap, cross-version AWF update and actual same-prefix Pi update are pending for these candidate bytes. Linux channel promotion requires separate successful Ubuntu 24.04 acceptance.'
    native.require(all(r['body'].startswith(pending) for _,r,_ in releases),'candidate description differs')
    link='https://github.com/'+native.probe.REPOSITORY+'/actions/runs/'+run_id
    text='\n\nUbuntu 24.04 native acceptance passed: public RC4 fresh install, official sole-prefix `pi update`, RC4 to RC5 AWF upgrade with config/state/Pi preservation, fresh default channel install, bare `awf update` no-op, owned cleanup and both parent directories restored. Evidence: '+link+'.\n\nUbuntu 22.04 native acceptance remains pending. RC2/RC3 upgrades are unsupported; use these candidates for fresh installations. This remains a Linux prerelease; Windows RC9 is unchanged.\n'
    for version,release,assets in releases:
        body='Linux amd64 preview. Ubuntu 24.04 native acceptance passed.'+release['body'][len(pending):]+text
        result=api.request('PATCH','/repos/'+native.probe.REPOSITORY+'/releases/'+str(release['id']),dict(body=body,prerelease=True,make_latest='false'))
        native.require(result['id']==release['id'] and result['draft'] is False and result['prerelease'] is True and result['tag_name']==version,'accepted release confirmation differs')
        after,inventory=release_inventory(api,version)
        native.require(inventory==assets and after['body']==body,'immutable assets or release evidence changed')
    return dict(nativeAcceptance=True,run=link,sourceCommit=native.probe.SOURCE,workflowCommit=sha)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--verify-assets',type=Path)
    modes.add_argument('--reports',type=Path)
    args=parser.parse_args()
    if args.verify_assets:
        verify_built_assets(args.verify_assets)
        print('AWF candidate: all 18 fixed asset pins matched')
        return
    sha=publish.ci_identity(os.environ)
    reports={mode:json.loads((args.reports/(mode+'-report.json')).read_text()) for mode in ('upgrade','default')}
    print(json.dumps(complete(publish.GitHub(os.environ.get('GH_TOKEN')),reports,sha,os.environ.get('GITHUB_RUN_ID','')),indent=2))


if __name__=='__main__':
    main()
