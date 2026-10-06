#!/usr/bin/env python3
"""Read-only AWF prerequisites on an explicitly approved standard Actions VM.

Writes only JSON to stdout. Never installs, starts services, mounts namespaces,
changes accounts, downloads runtime inputs, cleans system paths or calls models.
"""
import argparse
import grp
import json
import os
from pathlib import Path, PurePosixPath
import platform
import pwd
import re
import shutil
import stat
import subprocess
import time

REPOSITORY = 'atongrun/agent-workflow'
BRANCH = 'awf/linux-default-native-once-20261006'
DEFAULT_BRANCH = 'awf/linux-default-ci-v1'
POST_PI_BRANCH = 'awf/linux-post-pi-diagnostic-ci-v1'
SOURCE = '77735d2a94d1bda3bcd0e979d71fac643709f2f4'
RELEASE = 'v1.0.2-rc.2' if os.environ.get('GITHUB_REF') == 'refs/heads/'+DEFAULT_BRANCH else 'v1.0.2-rc.1'
MIN_AVAILABLE_BYTES = 512 << 20
MIN_DISK_BYTES = 4 << 30
RESOURCE_SAMPLES = 31
RESOURCE_INTERVAL = 2
UNITS = ('awf-host.service', 'awf-magpie.service')
FIXED_PATHS = (
    '/opt/node', '/opt/pi-cli', '/opt/awf', '/opt/magpie', '/etc/awf',
    '/var/lib/awf', '/var/cache/awf', '/var/cache/awf-installer',
    '/usr/local/bin/awf', '/usr/local/bin/pi', '/usr/local/bin/magpie',
    '/etc/systemd/system/awf-host.service',
    '/etc/systemd/system/awf-magpie.service',
)
INSTALL_PARENTS=('/opt','/etc','/var/lib','/var/cache','/usr/local/bin','/etc/systemd/system')
UNIT_PATHS = (
    '/etc/systemd/system.control', '/run/systemd/system.control',
    '/run/systemd/transient', '/run/systemd/generator.early',
    '/etc/systemd/system', '/etc/systemd/system.attached',
    '/run/systemd/system', '/run/systemd/system.attached',
    '/run/systemd/generator', '/usr/local/lib/systemd/system',
    '/usr/lib/systemd/system', '/lib/systemd/system',
    '/run/systemd/generator.late',
)


def ci_guard(env, uid, euid):
    branches=(BRANCH,)
    branch = next((b for b in branches if env.get('GITHUB_REF')=='refs/heads/'+b),BRANCH)
    expected = dict(GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted',
                    RUNNER_OS='Linux', GITHUB_REPOSITORY=REPOSITORY,
                    GITHUB_REF='refs/heads/'+branch, GITHUB_EVENT_NAME='push')
    if uid != 0 or euid != 0 or any(env.get(k) != v for k, v in expected.items()):
        raise ValueError('approved GitHub-hosted Linux push and root test required')
    if not re.fullmatch('[0-9a-f]{40}', env.get('GITHUB_SHA', '')):
        raise ValueError('exact workflow commit required')


def properties(text):
    return dict(line.split('=', 1) for line in text.splitlines() if '=' in line)


def memory_sample(meminfo, pressure):
    values = {}
    for line in meminfo.splitlines():
        key, value = line.split(':', 1)
        if key in ('MemAvailable', 'SwapTotal', 'SwapFree'):
            number, unit = value.split()
            if unit != 'kB':
                raise ValueError('unexpected memory unit')
            values[key] = int(number) * 1024
    if set(values) != {'MemAvailable', 'SwapTotal', 'SwapFree'}:
        raise ValueError('incomplete memory counters')
    full = next(line for line in pressure.splitlines() if line.startswith('full '))
    psi = dict(item.split('=', 1) for item in full.split()[1:])
    avg10 = float(psi['avg10'])
    if not 0 <= avg10 <= 100 or values['SwapFree'] > values['SwapTotal']:
        raise ValueError('invalid memory pressure/counters')
    return dict(availableBytes=values['MemAvailable'],
                swapUsedBytes=values['SwapTotal']-values['SwapFree'],
                fullPSIAvg10Percent=avg10)


def listeners(text, ipv6=False):
    occupied = []
    for line in text.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 4:
            raise ValueError('invalid TCP table')
        address, port = fields[1].split(':')
        if fields[3] == '0A' and int(port, 16) in (7070, 3425):
            occupied.append(dict(port=int(port, 16), ipv6=ipv6,
                                 fixedIPv4Loopback=not ipv6 and address == '0100007F'))
    return occupied


def trusted(path, directory=False):
    p = Path(path)
    for item in [p] + list(p.parents):
        info = item.lstat()
        if info.st_uid != 0 or info.st_mode & 0o022 or stat.S_ISLNK(info.st_mode):
            raise ValueError('untrusted fixed executable or parent: '+str(item))
        is_directory = directory if item == p else True
        if is_directory != stat.S_ISDIR(info.st_mode):
            raise ValueError('unexpected fixed path type: '+str(item))
        if not is_directory and (not stat.S_ISREG(info.st_mode) or not info.st_mode & 0o111):
            raise ValueError('fixed executable unavailable: '+str(item))


def parent_predicate(info):
    """The published Go trusted(parent, true) condition, including special bits."""
    tests = dict(rootOwned=info.st_uid == 0,
                 noGroupWrite=not bool(info.st_mode & stat.S_IWGRP),
                 noOtherWrite=not bool(info.st_mode & stat.S_IWOTH),
                 notPhysicalSymlink=not stat.S_ISLNK(info.st_mode),
                 noSetUID=not bool(info.st_mode & stat.S_ISUID),
                 noSetGID=not bool(info.st_mode & stat.S_ISGID),
                 directory=stat.S_ISDIR(info.st_mode))
    return dict(passed=all(tests.values()), predicates=tests,
                failedPredicates=[name for name, passed in tests.items() if not passed])


def metadata(info):
    return dict(uid=info.st_uid,gid=info.st_gid,
                octalMode=format(stat.S_IMODE(info.st_mode),'04o'),
                directory=stat.S_ISDIR(info.st_mode),physicalSymlink=stat.S_ISLNK(info.st_mode))


def parent_diagnostics(names):
    # Source-derived parents and their exact ancestors only. No home/auth/env
    # scanning, file contents or resolved symlink targets are collected.
    paths=list(dict.fromkeys(str(p) for name in names
               for p in (PurePosixPath(name),*PurePosixPath(name).parents)))
    rows=[]
    for name in paths:
        path=Path(name)
        row=dict(path=name)
        try:
            link_info=path.lstat()
            row['lstat']=metadata(link_info)
            row['goParentTrustPredicate']=parent_predicate(link_info)
            row['physicalPathMatchesRequestedPath']=str(path.resolve(strict=True))==name
            row['stat']=metadata(path.stat())
        except (OSError,RuntimeError) as error:
            row['metadataError']=dict(type=type(error).__name__,errno=getattr(error,'errno',None))
        rows.append(row)
    failed=[dict(path=r['path'],failedPredicates=r['goParentTrustPredicate']['failedPredicates'])
            for r in rows if 'goParentTrustPredicate' in r and not r['goParentTrustPredicate']['passed']]
    errors=[dict(path=r['path'],**r['metadataError']) for r in rows if 'metadataError' in r]
    return dict(paths=rows,requestedParents=list(names),failedPaths=failed,metadataErrors=errors,
                allParentsMeetGoTrustPredicate=not failed and not errors,sourceCommit=SOURCE,
                sourceLocation='internal/hostinstall/native_linux.go:160',
                predicateLocation='internal/hostinstall/native_linux.go:166',
                parentTraversalLocation='internal/hostinstall/native_linux.go:171',
                expectedSupportedMachine=dict(rootOwnedDirectory=True,
                    groupAndOtherWriteBitsClear=True,physicalSymlink=False,
                    setUIDAndSetGIDBitsClear=True,exampleOctalMode='0755',
                    gidIsMetadataNotATrustPredicate=True),
                mutationsPerformed=False)


def opt_parent_diagnostics():
    return parent_diagnostics(('/opt',))


def run(*args):
    result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, timeout=20,
                            env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL':'C'})
    if result.returncode or len(result.stdout) > 1 << 20:
        raise ValueError('read-only command failed: '+Path(args[0]).name)
    return result.stdout


def unit_diagnostics():
    rows = []
    conflicts=[]
    errors=[]
    try:
        trusted('/usr/bin/systemctl')
    except Exception:
        errors.append(dict(target='/usr/bin/systemctl',reason='untrusted fixed executable; not executed'))
    can_read_units=not errors
    for unit in UNITS:
        if can_read_units:
            try:
                found = properties(run('/usr/bin/systemctl', 'show', unit,
                                       '--property=LoadState,FragmentPath,DropInPaths', '--no-pager'))
                rows.append(dict(unit=unit, **found))
                if found != dict(LoadState='not-found', FragmentPath='', DropInPaths=''):
                    conflicts.append(dict(kind='loadedUnitOrOverrides',unit=unit))
            except Exception as error:
                errors.append(dict(target=unit,errorType=type(error).__name__))
    count = 0
    exceeded=False
    for directory in UNIT_PATHS:
        p = Path(directory)
        try:
            for entry in p.iterdir():
                count += 1
                if count > 65536:
                    errors.append(dict(target=directory,errorType='ScanBoundExceeded'))
                    exceeded=True
                    break
                try:
                    if entry.name in (*UNITS, *(u+'.d' for u in UNITS), 'awf-.service.d'):
                        conflicts.append(dict(kind='unitOrDropIn',path=str(entry)))
                    if stat.S_ISLNK(entry.lstat().st_mode) and PurePosixPath(os.readlink(entry)).name in UNITS:
                        conflicts.append(dict(kind='unitAlias',path=str(entry)))
                    if entry.name == 'service.d' or entry.name.endswith(('.wants', '.requires')):
                        for child in entry.iterdir():
                            count += 1
                            if count > 65536:
                                errors.append(dict(target=str(entry),errorType='ScanBoundExceeded'))
                                exceeded=True
                                break
                            try:
                                if entry.name == 'service.d' or child.name in UNITS:
                                    conflicts.append(dict(kind='globalOverrideOrDependency',path=str(child)))
                                if stat.S_ISLNK(child.lstat().st_mode) and PurePosixPath(os.readlink(child)).name in UNITS:
                                    conflicts.append(dict(kind='dependencyAlias',path=str(child)))
                            except Exception as error:
                                errors.append(dict(target=str(child),errorType=type(error).__name__))
                except Exception as error:
                    errors.append(dict(target=str(entry),errorType=type(error).__name__))
                if exceeded:
                    break
        except FileNotFoundError:
            continue
        except Exception as error:
            errors.append(dict(target=directory,errorType=type(error).__name__))
        if exceeded:
            break
    return dict(units=rows,conflicts=conflicts,metadataErrors=errors,
                passed=not conflicts and not errors,entriesExamined=count)


def fresh_units():
    data=unit_diagnostics()
    if not data['passed']:
        raise ValueError('existing or unreadable AWF unit/overrides; see fixed-object diagnostics')
    return data['units']


def object_diagnostics():
    rows=[]
    conflicts=[]
    errors=[]
    for name in FIXED_PATHS:
        try:
            info=Path(name).lstat()
            rows.append(dict(path=name,present=True,lstat=metadata(info)))
            conflicts.append(dict(kind='existingFixedPath',path=name,
                constraint='testIsolation' if name=='/var/cache/awf-installer' else 'nativeFresh'))
        except FileNotFoundError:
            rows.append(dict(path=name,present=False))
        except Exception as error:
            error_data=dict(errorType=type(error).__name__,errno=getattr(error,'errno',None))
            rows.append(dict(path=name,present=None,metadataError=error_data))
            errors.append(dict(target=name,**error_data))
    for kind,lookup in [('account',pwd.getpwnam),('group',grp.getgrnam)]:
        try:
            lookup('awf')
            conflicts.append(dict(kind='existingAWF'+kind.title(),constraint='nativeFresh'))
        except KeyError:
            pass
        except Exception as error:
            errors.append(dict(target='awf-'+kind,errorType=type(error).__name__))
    for command in ('awf','pi','magpie'):
        found=shutil.which(command,path='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin')
        if found:
            conflicts.append(dict(kind='existingCommand',command=command,path=found,constraint='nativeFresh'))
    try:
        root_agent=Path(pwd.getpwnam('root').pw_dir)/'.pi/agent'
        root_agent.lstat()
        conflicts.append(dict(kind='rootPiAgentExists',constraint='testIsolation'))
    except FileNotFoundError:
        pass
    except Exception as error:
        errors.append(dict(target='root-Pi-agent',errorType=type(error).__name__))
    units=unit_diagnostics()
    conflicts.extend(units['conflicts'])
    errors.extend(units['metadataErrors'])
    ports=[]
    for name,ipv6 in [('/proc/net/tcp',False),('/proc/net/tcp6',True)]:
        try:
            ports.extend(listeners(Path(name).read_text(),ipv6))
        except Exception as error:
            errors.append(dict(target=name,errorType=type(error).__name__))
    conflicts.extend(dict(kind='occupiedPort',**port) for port in ports)
    return dict(fixedPaths=rows,conflicts=conflicts,metadataErrors=errors,unitDiagnostics=units,
                portListeners=ports,passed=not conflicts and not errors,mutationsPerformed=False)


def mount_records(text):
    rows = []
    for line in text.splitlines():
        before, after = line.split(' - ', 1)
        a, b = before.split(), after.split()
        rows.append(dict(target=a[4], flags=a[5].split(','), fs=b[0]))
    return rows


def mount_for(rows, target):
    matches = [r for r in rows if target == r['target'] or
               target.startswith(r['target'].rstrip('/')+'/')]
    if not matches:
        raise ValueError('mount record unavailable')
    return max(matches, key=lambda r: len(r['target']))


def self_cgroup(text):
    rows = [line[3:] for line in text.splitlines() if line.startswith('0::')]
    if len(rows) != 1:
        raise ValueError('one unified process cgroup required')
    name = rows[0]
    path = PurePosixPath(name)
    if not name.startswith('/') or name.startswith('//') or '..' in path.parts or str(path) != name:
        raise ValueError('invalid process cgroup path')
    return Path('/sys/fs/cgroup')/name.lstrip('/')


def resource_gate(samples):
    if len(samples) != RESOURCE_SAMPLES:
        raise ValueError('complete 60-second sample window required')
    if min(s['availableBytes'] for s in samples) < MIN_AVAILABLE_BYTES:
        raise ValueError('MemAvailable below 512 MiB during 60-second observation')
    if max(s['fullPSIAvg10Percent'] for s in samples) != 0:
        raise ValueError('full memory PSI observed; resource gate failed')


def inspect(expected_release):
    report = dict(schema=1, kind='awf-standard-runner-readonly-preflight',
                  sourceCommit=SOURCE, release=RELEASE,
                  workflowCommit=os.environ['GITHUB_SHA'], expectedUbuntu=expected_release,
                  checks={}, preflightPassed=False, nativeInstallationPerformed=False,
                  actualNamespaceMountExecutionVerified=False, nativeAcceptance=False,
                  CloudConeAcceptance=False, modelCalls=0, piUpdateExecuted=False)
    # Collect every source-derived parent and object conflict before any
    # fail-fast freshness check can conceal later incompatible components.
    report['parentDiagnostics']=parent_diagnostics(INSTALL_PARENTS+('/usr/bin','/usr/sbin'))
    report['fixedObjectDiagnostics']=object_diagnostics()
    checks = report['checks']
    errors = []

    def check(name, fn):
        try:
            checks[name] = dict(passed=True, evidence=fn())
        except Exception as exc:
            checks[name] = dict(passed=False, reason=str(exc))
            errors.append(name)

    def platform_check():
        release = properties(Path('/etc/os-release').read_text())
        if release.get('ID','').strip('"') != 'ubuntu' or release.get('VERSION_ID','').strip('"') != expected_release or platform.machine() != 'x86_64':
            raise ValueError('expected standard Ubuntu amd64 VM required')
        if not run('/usr/bin/getconf', 'GNU_LIBC_VERSION').startswith('glibc '):
            raise ValueError('glibc unavailable')
        if Path('/proc/1/comm').read_text().strip() != 'systemd' or not Path('/run/systemd/system').is_dir():
            raise ValueError('PID1 systemd and live manager required')
        return dict(distribution='ubuntu', release=expected_release,
                    architecture='amd64', pid1='systemd', glibc=run('/usr/bin/getconf','GNU_LIBC_VERSION').strip(),
                    systemdVersion=run('/usr/bin/systemctl','--version').splitlines()[0])

    def privileges():
        for executable in ('/usr/bin/systemctl','/usr/sbin/useradd','/usr/sbin/userdel','/usr/sbin/groupdel','/usr/sbin/nologin','/usr/bin/unshare'):
            trusted(executable)
        caps = properties(Path('/proc/self/status').read_text().replace(':\t','='))
        effective = int(caps['CapEff'],16)
        required = {'SYS_ADMIN':21, 'SETUID':7, 'SETGID':6, 'CHOWN':0, 'DAC_OVERRIDE':1}
        if any(not effective & (1 << bit) for bit in required.values()):
            raise ValueError('required root capabilities unavailable')
        if not Path('/proc/self/ns/mnt').is_symlink():
            raise ValueError('mount namespace handle unavailable')
        return dict(requiredCapabilitiesPresent=sorted(required), namespaceHandlePresent=True,
                    namespaceOrMountCreated=False)

    def cgroup_check():
        controllers = Path('/sys/fs/cgroup/cgroup.controllers').read_text().split()
        if not {'memory','pids','cpu'} <= set(controllers):
            raise ValueError('unified cgroup memory/pids/cpu controllers required')
        mounts = mount_records(Path('/proc/self/mountinfo').read_text())
        mount = mount_for(mounts,'/sys/fs/cgroup')
        if mount['fs'] != 'cgroup2' or 'rw' not in mount['flags']:
            raise ValueError('writable cgroup v2 mount required')
        process_group = self_cgroup(Path('/proc/self/cgroup').read_text())
        if not all((process_group/f).is_file() for f in ('cgroup.procs','memory.events')):
            raise ValueError('cgroup shutdown/OOM counters unavailable')
        return dict(controllers=controllers, mount=mount,
                    processCgroup=str(process_group), writesPerformed=False)

    def fresh_paths():
        for path in FIXED_PATHS:
            if os.path.lexists(path):
                raise ValueError('existing fixed AWF path: '+path)
        for command in ('awf','pi','magpie'):
            if shutil.which(command, path='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'):
                raise ValueError('existing AWF/Pi/Magpie command')
        for lookup in (pwd.getpwnam, grp.getgrnam):
            try:
                lookup('awf')
            except KeyError:
                continue
            raise ValueError('existing awf account/group')
        root_agent = Path(pwd.getpwnam('root').pw_dir)/'.pi/agent'
        if os.path.lexists(root_agent):
            raise ValueError('preexisting root Pi agent directory')
        for parent in INSTALL_PARENTS:
            trusted(parent, directory=True)
        occupied = listeners(Path('/proc/net/tcp').read_text()) + listeners(Path('/proc/net/tcp6').read_text(),True)
        if occupied:
            raise ValueError('7070/3425 already occupied')
        return dict(fixedPathsAbsent=len(FIXED_PATHS), accountAndGroupAbsent=True,
                    rootAgentDirectoryAbsent=True, portsUnoccupied=[7070,3425], units=fresh_units())

    def resources():
        mounts=mount_records(Path('/proc/self/mountinfo').read_text())
        disks=[]
        for target in ('/tmp','/opt','/var/lib','/var/cache'):
            m=mount_for(mounts,target)
            if m['fs'] in ('tmpfs','ramfs') or 'rw' not in m['flags']:
                raise ValueError('disk-backed writable installer/program/state storage required')
            free=shutil.disk_usage(target).free
            if free < MIN_DISK_BYTES:
                raise ValueError('less than 4 GiB free disk')
            disks.append(dict(target=target,freeBytes=free,filesystem=m['fs']))
        samples=[]
        for index in range(RESOURCE_SAMPLES):
            if index:
                time.sleep(RESOURCE_INTERVAL)
            samples.append(memory_sample(Path('/proc/meminfo').read_text(),Path('/proc/pressure/memory').read_text()))
        evidence=dict(observationSeconds=(RESOURCE_SAMPLES-1)*RESOURCE_INTERVAL,samples=samples,disks=disks,
                      minimumAvailableBytes=min(s['availableBytes'] for s in samples),
                      maximumFullPSIAvg10Percent=max(s['fullPSIAvg10Percent'] for s in samples),
                      cloudConeResourceThresholdChanged=False)
        # Hosted-VM eligibility requires no observed full-memory stalls. This
        # conservative CI gate does not redefine the CloudCone approval window.
        try:
            resource_gate(samples)
        except ValueError:
            checks['resourceObservation']=dict(passed=False,evidence=evidence)
            raise
        return evidence

    check('platform',platform_check)
    check('rootAndNamespacePrerequisites',privileges)
    check('unifiedCgroup',cgroup_check)
    check('freshAWFPathsUnitsAndPorts',fresh_paths)
    # Fail fast on incompatible/non-fresh hosts. No 60-second wait is needed.
    if not errors:
        check('resources',resources)
    report['failedChecks']=errors
    report['preflightPassed']=not errors
    report['separateNativeAuthorizationRequired']=True
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-release',required=True,choices=('22.04','24.04'))
    args=parser.parse_args()
    try:
        ci_guard(os.environ,os.getuid(),os.geteuid())
    except ValueError as error:
        print(json.dumps(dict(preflightPassed=False,guardFailure=str(error),nativeInstallationPerformed=False)))
        return 2
    report=inspect(args.expected_release)
    print(json.dumps(report,sort_keys=True,indent=2))
    return 0 if report['preflightPassed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
