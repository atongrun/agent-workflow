#!/usr/bin/env python3
"""One approved disposable-VM /opt adjustment around the native harness.

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

OPT=Path('/opt')
STATE=Path('/tmp/awf-native-parent-'+os.environ.get('GITHUB_SHA','invalid'))


def inode(info):
    return dict(dev=info.st_dev,ino=info.st_ino,type=stat.S_IFMT(info.st_mode))


def open_opt(modes):
    info=OPT.lstat()
    native.require(stat.S_ISDIR(info.st_mode) and info.st_uid==0 and info.st_gid==0
                   and stat.S_IMODE(info.st_mode) in modes
                   and str(OPT.resolve(strict=True))=='/opt',
                   'approved /opt metadata differs; no permission adjustment')
    fd=os.open('/opt',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        verify_opt(fd,inode(info),stat.S_IMODE(info.st_mode))
        return fd,info
    except Exception:
        os.close(fd)
        raise


def verify_opt(fd,saved,mode):
    current=os.fstat(fd)
    native.require(inode(current)==saved and inode(OPT.lstat())==saved
                   and current.st_uid==0 and current.st_gid==0
                   and stat.S_IMODE(current.st_mode)==mode,
                   '/opt identity, owner or mode changed')


def prepare(context):
    native.require(not os.path.lexists(STATE),'existing parent-preparation control; no adoption')
    fd,info=open_opt({0o777})
    try:
        STATE.mkdir(mode=0o700)
        context['stateCreated']=True
        record=dict(schema=1,path='/opt',workflowCommit=os.environ['GITHUB_SHA'],
                    controlIdentity=native.identity(STATE),identity=inode(info),
                    uid=0,gid=0,originalMode=0o777,testMode=0o755,applied=False)
        # This atomic private receipt MUST precede the sole permission write.
        native.private_file(STATE/'parent.json',record)
        verify_opt(fd,record['identity'],0o777)
        os.fchmod(fd,0o755)
        verify_opt(fd,record['identity'],0o755)
        record['applied']=True
        native.private_file(STATE/'parent.json',record)
        return record
    finally:
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
    native.require(record['schema']==1 and record['path']=='/opt'
                   and record['workflowCommit']==os.environ['GITHUB_SHA']
                   and record['controlIdentity']==inode(info)
                   and record['uid']==0 and record['gid']==0
                   and record['originalMode']==0o777 and record['testMode']==0o755,
                   'parent receipt differs from this approved run')
    return record


def restore(record):
    fd,info=open_opt({0o755,0o777})
    before=stat.S_IMODE(info.st_mode)
    try:
        native.require(inode(info)==record['identity'],'/opt inode differs; restoration blocked')
        verify_opt(fd,record['identity'],before)
        if before==0o755:
            os.fchmod(fd,0o777)
        verify_opt(fd,record['identity'],0o777)
        return dict(passed=True,path='/opt',restoredMode='0777',identityPreserved=True,
                    observedBeforeRestoreMode=format(before,'04o'),
                    permissionWritePerformed=before==0o755,
                    uid=0,gid=0,recursive=False,ownershipChanged=False)
    finally:
        os.close(fd)


def protect_retry(record):
    fd,info=open_opt({0o755,0o777})
    try:
        native.require(inode(info)==record['identity'],'/opt identity differs before cleanup')
        verify_opt(fd,record['identity'],stat.S_IMODE(info.st_mode))
        # Path-based owned cleanup requires the trusted parent again. A prior
        # failed/cancelled main attempt may already have restored its 0777 mode.
        # No native control means there is no native cleanup and no second write.
        needed=os.path.lexists(native.CONTROL) and stat.S_IMODE(info.st_mode)==0o777
        if needed:
            os.fchmod(fd,0o755)
            verify_opt(fd,record['identity'],0o755)
        return needed
    finally:
        os.close(fd)


def remove_state(record):
    native.require(load_state()==record and sorted(p.name for p in STATE.iterdir())==['parent.json'],
                   'unknown parent-control contents; no recursive cleanup')
    (STATE/'parent.json').unlink()
    STATE.rmdir()


def call_native(args):
    previous=sys.argv
    sys.argv=['native_acceptance','--expected-release',args.expected_release,'--report',str(args.report)]
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
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--prepare-ci-opt',action='store_true')
    modes.add_argument('--cleanup-only',action='store_true')
    args=parser.parse_args()
    native.probe.ci_guard(os.environ,os.getuid(),os.geteuid())
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
            context['cleanupParentReacquired']=protect_retry(record)
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
                report['parentRestoration']=restore(record)
                report['parentRestoration']['cleanupParentReacquired']=context.get('cleanupParentReacquired',False)
                observed=record['applied'] or report['parentRestoration']['observedBeforeRestoreMode']=='0755' \
                    or report.get('parentPreparation',{}).get('applied') is True
                report['parentPreparation']=dict(path='/opt',originalMode='0777',testMode='0755',
                    applied=True if observed else None,completedReceipt=record['applied'],
                    uid=0,gid=0,recursive=False,ownershipChanged=False)
                if args.cleanup_only and code==0:
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
