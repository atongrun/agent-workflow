#!/usr/bin/env python3
"""Approved disposable-VM /opt and /usr/local/bin preparation and restoration.

No recursive chmod, ownership change, child permission change or installer
exception exists here. A private write-ahead receipt survives cancellation.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import stat
import sys

import native_acceptance as native
import native_acl_observation as acl

PARENTS=('/opt','/usr/local/bin')
STATE=Path('/tmp/awf-native-parent-'+os.environ.get('GITHUB_SHA','invalid'))


def inode(info):
    return dict(dev=info.st_dev,ino=info.st_ino,type=stat.S_IFMT(info.st_mode))


def open_parent(name,modes):
    native.require(name in PARENTS,'unapproved parent path')
    path=Path(name)
    info=path.lstat()
    native.require(stat.S_ISDIR(info.st_mode) and info.st_uid==0 and info.st_gid==0
                   and stat.S_IMODE(info.st_mode) in modes
                   and str(path.resolve(strict=True))==name,
                   'approved parent metadata differs: '+name)
    fd=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        verify_parent(name,fd,inode(info),stat.S_IMODE(info.st_mode))
        return fd,info
    except Exception:
        os.close(fd)
        raise


def verify_parent(name,fd,saved,mode):
    current=os.fstat(fd)
    native.require(inode(current)==saved and inode(Path(name).lstat())==saved
                   and current.st_uid==0 and current.st_gid==0
                   and stat.S_IMODE(current.st_mode)==mode,
                   'parent identity, owner or mode changed: '+name)


def prepare(context):
    native.require(not os.path.lexists(STATE),'existing parent-preparation control; no adoption')
    handles={}
    try:
        # Validate BOTH VM objects before any parent permission changes.
        for name in PARENTS:
            handles[name]=open_parent(name,{0o777})
        STATE.mkdir(mode=0o700)
        context['stateCreated']=True
        record=dict(schema=2,workflowCommit=os.environ['GITHUB_SHA'],
                    controlIdentity=native.identity(STATE),parents=[
                        dict(path=name,identity=inode(handles[name][1]),uid=0,gid=0,
                             originalMode=0o777,testMode=0o755,applied=False,
                             originalACL=acl.snapshot(handles[name][0])) for name in PARENTS])
        # Persist BOTH original identities/modes before the first chmod.
        native.private_file(STATE/'parent.json',record)
        for row in record['parents']:
            name=row['path']; fd=handles[name][0]
            verify_parent(name,fd,row['identity'],0o777)
            os.fchmod(fd,0o755)
            verify_parent(name,fd,row['identity'],0o755)
            native.require(acl.snapshot(fd)==acl.after_chmod(row['originalACL'],0o755),'parent ACL changed beyond chmod mask')
            row['applied']=True
            native.private_file(STATE/'parent.json',record)
        return record
    finally:
        for fd,_ in handles.values():
            os.close(fd)


def load_state():
    info=STATE.lstat()
    native.require(stat.S_ISDIR(info.st_mode) and info.st_uid==0 and info.st_gid==0
                   and stat.S_IMODE(info.st_mode)==0o700,'parent control identity invalid')
    path=STATE/'parent.json'
    before=path.lstat()
    native.require(stat.S_ISREG(before.st_mode) and before.st_uid==0 and before.st_gid==0
                   and stat.S_IMODE(before.st_mode)==0o600,'parent receipt identity invalid')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    with os.fdopen(fd) as stream:
        native.require(inode(os.fstat(stream.fileno()))==inode(before),'parent receipt replaced')
        record=json.load(stream)
    native.require(record['schema']==2
                   and record['workflowCommit']==os.environ['GITHUB_SHA']
                   and record['controlIdentity']==inode(info)
                   and tuple(row['path'] for row in record['parents'])==PARENTS
                   and all(row['uid']==0 and row['gid']==0 and row['originalMode']==0o777
                           and row['testMode']==0o755 and isinstance(row['applied'],bool)
                           for row in record['parents']),
                   'parent receipt differs from this approved run')
    return record


def restore_parent(row):
    name=row['path']
    fd,info=open_parent(name,{0o755,0o777})
    before=stat.S_IMODE(info.st_mode)
    try:
        native.require(inode(info)==row['identity'],'parent inode differs; restoration blocked: '+name)
        verify_parent(name,fd,row['identity'],before)
        native.require(acl.snapshot(fd)==acl.after_chmod(row['originalACL'],before),'parent ACL differs; restoration blocked')
        if before==0o755:
            os.fchmod(fd,0o777)
        verify_parent(name,fd,row['identity'],0o777)
        native.require(acl.snapshot(fd)==row['originalACL'],'original parent ACL not restored')
        return dict(passed=True,path=name,restoredMode='0777',identityPreserved=True,
                    observedBeforeRestoreMode=format(before,'04o'),
                    permissionWritePerformed=before==0o755,
                    uid=0,gid=0,recursive=False,ownershipChanged=False,aclRestored=True)
    finally:
        os.close(fd)


def restore(record):
    results=[]
    for row in record['parents']:
        try:
            results.append(restore_parent(row))
        except Exception:
            # A failure on one parent never suppresses the other's restoration.
            results.append(dict(path=row['path'],passed=False,reason='parent restoration blocked'))
    return dict(passed=all(row['passed'] for row in results),parents=results)


def protect_retry(record):
    handles={}
    try:
        for row in record['parents']:
            name=row['path']; fd,info=open_parent(name,{0o755,0o777})
            handles[name]=(fd,info)
            native.require(inode(info)==row['identity'],'parent identity differs before cleanup: '+name)
            verify_parent(name,fd,row['identity'],stat.S_IMODE(info.st_mode))
            native.require(acl.snapshot(fd)==acl.after_chmod(row['originalACL'],stat.S_IMODE(info.st_mode)),
                           'parent ACL differs before cleanup: '+name)
        changed=[]
        if os.path.lexists(native.CONTROL):
            for row in record['parents']:
                name=row['path']; fd,info=handles[name]
                if stat.S_IMODE(info.st_mode)==0o777:
                    os.fchmod(fd,0o755)
                    changed.append(name)
                # BOTH parents must be trusted before path-based owned cleanup.
                verify_parent(name,fd,row['identity'],0o755)
                native.require(acl.snapshot(fd)==acl.after_chmod(row['originalACL'],0o755),
                               'parent ACL changed beyond cleanup chmod mask: '+name)
        return changed
    finally:
        for fd,_ in handles.values():
            os.close(fd)


def remove_state(record):
    native.require(load_state()==record and sorted(p.name for p in STATE.iterdir())==['parent.json'],
                   'unknown parent-control contents; no recursive cleanup')
    (STATE/'parent.json').unlink()
    STATE.rmdir()


def call_native(args):
    previous=sys.argv
    sys.argv=['native_acceptance','--expected-release',args.expected_release,'--report',str(args.report)]
    if getattr(args,'phase',None):
        sys.argv.extend(['--phase',args.phase])
    if getattr(args,'retain_post_pi_failure',False):
        sys.argv.append('--retain-post-pi-failure')
    if getattr(args,'pi_update_diagnostic',False):
        sys.argv.append('--pi-update-diagnostic')
    if getattr(args,'acl_full_acceptance',False):
        sys.argv.append('--acl-full-acceptance')
    if getattr(args,'default_entry_acceptance',False):
        sys.argv.append('--default-entry-acceptance')
    if args.cleanup_only:
        sys.argv.append('--cleanup-only')
    try:
        return native.main()
    finally:
        sys.argv=previous


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-release',required=True,choices=('24.04',))
    parser.add_argument('--report',required=True,type=Path)
    parser.add_argument('--phase',choices=('upgrade','default'))
    parser.add_argument('--retain-post-pi-failure',action='store_true')
    parser.add_argument('--pi-update-diagnostic',action='store_true')
    parser.add_argument('--acl-full-acceptance',action='store_true')
    parser.add_argument('--default-entry-acceptance',action='store_true')
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--prepare-ci-parents',action='store_true')
    modes.add_argument('--cleanup-only',action='store_true')
    args=parser.parse_args()
    native.probe.ci_guard(os.environ,os.getuid(),os.geteuid())
    default_mode=args.default_entry_acceptance and args.phase in ('upgrade','default') and not any((args.acl_full_acceptance,args.pi_update_diagnostic,args.retain_post_pi_failure))
    if args.default_entry_acceptance:
        native.require(default_mode,'default-entry acceptance requires one exact phase')
    native.require(args.cleanup_only or default_mode or ((args.acl_full_acceptance or args.pi_update_diagnostic) and args.phase is None and not args.retain_post_pi_failure and not (args.acl_full_acceptance and args.pi_update_diagnostic)),'approved native acceptance mode required')
    if args.retain_post_pi_failure:
        native.require(not args.cleanup_only and args.phase!='default' and os.environ.get('GITHUB_REF')=='refs/heads/'+native.probe.POST_PI_BRANCH,
                       'retention requires the separately approved post-Pi diagnostic VM')
    if args.cleanup_only and not os.path.lexists(STATE):
        native.require(not os.path.lexists(native.CONTROL),'native control without parent receipt; cleanup blocked')
        return 0
    context={}
    code=1
    failure=None
    record=None
    def cancelled(signum,frame):
        raise native.TestFailure('approved native test cancelled')
    signal.signal(signal.SIGTERM,cancelled)
    signal.signal(signal.SIGINT,cancelled)
    try:
        if args.cleanup_only:
            context['stateCreated']=True
            record=load_state()
            context['cleanupParentsReacquired']=protect_retry(record)
        else:
            record=prepare(context)
        code=call_native(args)
    except Exception as error:
        failure=str(error) if isinstance(error,native.TestFailure) else 'parent/native wrapper exception: '+type(error).__name__
    finally:
        fallback=dict(schema=1,sourceCommit=native.probe.SOURCE,version=native.probe.RELEASE,
            workflowCommit=os.environ['GITHUB_SHA'],stages=[],healthRounds=[],acceptancePassed=False,
            cleanup={'passed':False},modelCalls=0,providerAuthenticationPerformed=False,
            piUpdateExecuted=False,CloudConeAcceptance=False)
        report=native.previous_report(args.report,fallback)
        if failure:
            report['failure']=failure
        if context.get('stateCreated'):
            try:
                record=load_state()
                # Native main already attempted scoped cleanup in its finally.
                # This outer finally also covers preflight, download and signal failures.
                retained=args.retain_post_pi_failure and not args.cleanup_only and report.get('retainedForDiagnosis') is True
                if retained:
                    try:
                        for row in record['parents']:
                            fd,info=open_parent(row['path'],{0o755})
                            try:
                                verify_parent(row['path'],fd,row['identity'],0o755)
                            finally:
                                os.close(fd)
                        report['parentRestoration']=dict(passed=False,pending=True,parents=[])
                    except Exception:
                        retained=False
                        report['retainedForDiagnosis']=False
                        report['failure']='retained parent verification failed; cleanup required'
                        code=1
                if not retained:
                    report['parentRestoration']=restore(record)
                report['parentRestoration']['cleanupParentsReacquired']=context.get('cleanupParentsReacquired',[])
                previous={row['path']:row for row in report.get('parentPreparation',{}).get('parents',[])}
                prepared=[]
                for row,result in zip(record['parents'],report['parentRestoration']['parents'] if not retained else [{}]*2):
                    observed=row['applied'] or result.get('observedBeforeRestoreMode')=='0755' \
                        or previous.get(row['path'],{}).get('applied') is True
                    prepared.append(dict(path=row['path'],originalMode='0777',testMode='0755',
                        applied=True if observed else None,completedReceipt=row['applied'],
                        uid=0,gid=0,recursive=False,ownershipChanged=False,originalACL=row['originalACL']))
                report['parentPreparation']=dict(parents=prepared)
                if not retained and not report['parentRestoration']['passed']:
                    code=1
                if args.cleanup_only and code==0 and report['parentRestoration']['passed']:
                    remove_state(record)
                    report['parentRestoration']['privateReceiptRemoved']=True
            except Exception:
                code=1
                report['parentRestoration']=dict(passed=False,reason='parent restoration/control cleanup blocked; private receipt retained')
        else:
            report.setdefault('parentRestoration',dict(passed=True,adjustmentPerformed=False))
        native.report_write(args.report,report)
    print('AWF native test: parent restoration '+str(report['parentRestoration']['passed']),flush=True)
    return code


if __name__=='__main__':
    raise SystemExit(main())
