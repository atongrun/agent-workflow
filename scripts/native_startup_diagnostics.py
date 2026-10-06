#!/usr/bin/env python3
"""Fixed metadata and official CLI version probes; never export private bodies.

collect(runner) consumes the existing ownership ledger without observing/adopting
anything. classify(log) emits only checked-in static errors and progress. This
module has no installer, network, write, account or service mutation entry.
The authorized Pi --version check uses the exact native environment and may
acquire/release an upstream temporary settings lock before printing its version.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import select
import signal
import stat
import subprocess
import time

SOURCE = '77735d2a94d1bda3bcd0e979d71fac643709f2f4'
PI_ROOT = '/opt/pi-cli'
PI_PACKAGE = PI_ROOT+'/lib/node_modules/@earendil-works/pi-coding-agent/package.json'
PI_LAUNCHER = PI_ROOT+'/awf-launcher.mjs'
LAUNCHER_SHA256 = '6f9e9e1ad3fb5b8ab6b0ba1d1744711eb3feaa46fa8463cfe53097ecd85bf79c'
NATIVE_ENV = {'PATH':'/opt/node/bin:/usr/sbin:/usr/bin:/sbin:/bin',
              'LC_ALL':'C','PI_CODING_AGENT_DIR':'/var/lib/awf/pi-agent'}
UNITS = ('awf-host.service','awf-magpie.service')
# All errors.New literals from the reviewed native lifecycle/channel/manifest and
# maintenance sources. Unknown OS/upstream strings are never rendered publicly.
SOURCE_ERRORS = [
    "--version requires an exact Linux v1 release tag",
    "AWF and Magpie owned listeners not both observed",
    "AWF or Magpie listener is not fixed IPv4 loopback",
    "AWF/Magpie listener belongs to another process",
    "AWF/Magpie ports are already occupied; inspect without stopping other applications",
    "Host and extension must share the manifest release",
    "Host did not establish the owned seal",
    "Host maintenance is sealed; only explicit owner release may change state",
    "Host maintenance listener belongs to another process",
    "Host native paths, loopback and maintenance configuration must be retained",
    "Host process changed during maintenance verification",
    "Host token file must remain private",
    "Host token unavailable",
    "Linux channel and immutable release manifest disagree",
    "Linux machine lifecycle requires root",
    "Linux manifest redirect refused",
    "Linux preview declined; no programs changed",
    "Linux preview requires --allow-prerelease or an earlier explicit linux-host-v1 preview approval",
    "Linux update platform differs from this installation",
    "Linux update refuses a version downgrade",
    "Magpie LAN must be false or omitted",
    "Magpie health version differs from installed artifact",
    "Magpie native safety settings changed",
    "Magpie portable configuration requires inspection",
    "Magpie private state ownership/type changed",
    "Magpie read-only identity health failed",
    "Magpie read-only settings bind is absent",
    "Magpie requires exact version",
    "Magpie settings mount is not read-only",
    "Magpie snapshot permissions changed",
    "Node requires exact version",
    "Pi prefix has an external link",
    "Pi prefix link escapes",
    "Pi requires Node at least 22.19.0",
    "Pi version is outside verified RPC compatibility",
    "artifact must use its exact official versioned source",
    "artifact requires exact format, size and SHA-256",
    "awf account lookup unavailable",
    "awf group lookup unavailable",
    "bundle exceeds staging size limit",
    "cgroup process bound",
    "cgroup traversal bound",
    "choose either --manifest or --version",
    "command output limit",
    "component has missing or extra artifacts",
    "current Pi package and executable version disagree",
    "current official Pi package identity invalid",
    "dedicated non-root service account required",
    "duplicate manifest component",
    "duplicate or invalid manifest key",
    "existing awf account requires inspection",
    "existing awf group requires inspection",
    "existing maintenance lease requires explicit owner release",
    "existing maintenance lease requires its explicit owner",
    "existing maintenance lease requires its explicit owner/target",
    "existing systemd AWF alias requires inspection",
    "existing systemd AWF definition requires inspection",
    "existing systemd AWF dependency alias requires inspection",
    "existing systemd AWF dependency requires inspection",
    "existing systemd unit or overrides require inspection",
    "fixed program differs from install provenance",
    "fixed program mode differs from install provenance",
    "global systemd service overrides require inspection",
    "installed command link changed",
    "installed systemd unit changed",
    "installer lock directory must be private",
    "invalid Linux Host manifest fields",
    "invalid Magpie settings",
    "invalid artifact source",
    "invalid cgroup process identity",
    "invalid maintenance drain identity",
    "invalid maintenance lease",
    "invalid maintenance response",
    "invalid manifest JSON",
    "invalid open maintenance state",
    "invalid owned maintenance response",
    "invalid persisted maintenance revision",
    "invalid service group",
    "invalid service identity",
    "kernel listener inode unavailable",
    "kernel listener snapshot unavailable",
    "local and immutable release manifests disagree",
    "loopback Host maintenance unavailable",
    "loopback Magpie health unavailable",
    "maintenance refused; settle work or inspect existing lease",
    "manifest exceeds bounded UTF-8 contract",
    "manifest must contain exactly one JSON value",
    "manifest nesting exceeds limit",
    "manifest requires exact Go v1 release and source commit",
    "manifest requires the five default components",
    "manifest unreadable",
    "native executable build identity differs from manifest",
    "native metadata bound",
    "native metadata invalid",
    "native read bound",
    "native receipt invalid",
    "new verified runtime preparation required",
    "official Linux update metadata refused; no programs changed",
    "official Linux update metadata unavailable; no programs changed",
    "official Linux update metadata unreadable; no programs changed",
    "owned Host maintenance listener unavailable",
    "partially running service pair requires awf stop before start",
    "private service state directory required",
    "program changed during copy",
    "program command link changed",
    "program update incomplete; services remain sealed/stopped, inspect pending marker and retained backups",
    "release manifest version differs from requested tag",
    "required native executable unavailable",
    "requires Ubuntu 22.04/24.04 or Debian 12 glibc systemd amd64; no machine changes made",
    "run awf init before start",
    "running Host build does not match installed identity",
    "same Linux version has different source or payload; inspect publisher metadata",
    "service descriptor bound",
    "service identity invalid",
    "service initialization state already exists; inspect partial initialization",
    "service process changed during health verification",
    "service socket ownership unavailable",
    "service state ownership requires inspection",
    "stable Pi launcher changed; upstream npm owns only its package tree",
    "stable Pi launcher must be executable",
    "started Host build identity differs",
    "startup/health failed and systemd cleanup is unverified; inspect services and retained maintenance lease",
    "stopped maintenance owner/seal changed",
    "stopped maintenance target differs from installed receipt",
    "system path ownership, type or permissions require inspection",
    "systemd control group still contains processes",
    "systemd dependency/drop-in directory unreadable",
    "systemd fresh-unit lookup unavailable",
    "systemd lookup bound",
    "systemd main process executable changed",
    "systemd main process missing from cgroup",
    "systemd service is not active in its fixed control group",
    "systemd shutdown is not established",
    "systemd unit ownership, overrides or control-group contract changed",
    "systemd unit permissions changed",
    "systemd unit search path unreadable",
    "trusted systemctl is required",
    "unified systemd cgroup v2 required for process shutdown verification",
    "unknown manifest component",
    "unknown native unit",
    "unknown service check",
    "unsupported Linux Host manifest or compatibility protocol",
    "unsupported manifest platform",
    "unsupported persisted maintenance phase",
    "update source changed during copy",
    "verified runtime preparation required"
]
ERROR_CODES = {line:re.sub('[^a-z0-9]+','_',line.lower()).strip('_') for line in SOURCE_ERRORS}
ERROR_CODES.update({'native command systemctl failed':'systemctl_failed',
                    'native command awf-launcher.mjs failed':'pi_version_command_failed'})
VERSION = re.compile(r'(0|[1-9][0-9]{0,11})\.(0|[1-9][0-9]{0,11})\.(0|[1-9][0-9]{0,11})')
PROGRESS = re.compile(r'AWF (bundle|awf-host|node|awf|magpie|pi-cli) (service-start|health|service-stop|service-stop-retry|failed-start-stop|verify-current|update|build-identity): (started|completed|failed)')
ROOT_DIRS = ('/','/opt','/opt/node','/opt/pi-cli','/opt/awf','/opt/magpie',
             '/etc','/etc/awf','/etc/systemd','/etc/systemd/system',
             '/usr','/usr/bin','/usr/sbin','/usr/local','/usr/local/bin',
             '/var','/var/lib','/var/cache','/var/cache/awf-installer')
ROOT_FILES = {'/etc/awf/install.json':0o600,'/etc/awf/host.json':0o640,
              '/etc/awf/host.env':0o600,'/etc/awf/native-initialized.json':0o600,
              '/etc/awf/stopped-lease.json':0o600,'/etc/awf/update-pending.json':0o600,
              '/etc/awf/magpie-settings.json':0o640,
              '/opt/node/bin/node':0o755,PI_LAUNCHER:0o755,
              '/opt/awf/awf':0o755,'/opt/magpie/magpie':0o755}
ROOT_FILES.update({'/etc/systemd/system/'+unit:0o644 for unit in UNITS})
SERVICE_PATHS = {'/var/lib/awf':True,'/var/lib/awf/pi-agent':True,
                '/var/lib/awf/magpie-config':True,'/var/lib/awf/magpie-config/magpie':True,
                '/var/lib/awf/magpie-config/magpie/settings.json':False}
HOST_FIELDS = {'listen':'127.0.0.1:7070','internalUrl':'http://127.0.0.1:7070',
               'dataDir':'/var/lib/awf','piAgentDir':'/var/lib/awf/pi-agent',
               'piBinary':PI_LAUNCHER,'piExtension':'/opt/awf/extensions/awf.ts',
               'enableMaintenance':True,'tokenEnv':'AWF_HOST_TOKEN',
               'extensionTokenEnv':'AWF_EXTENSION_TOKEN'}
UNIT_ENUMS = {'LoadState':{'loaded','not-found','error','masked','bad-setting'},
              'ActiveState':{'active','inactive','failed','activating','deactivating','reloading','maintenance','refreshing'},
              'SubState':{'running','dead','failed','start-pre','start','start-post','stop','stop-sigterm','stop-sigkill','stop-post','auto-restart','exited'},
              'Result':{'success','exit-code','signal','core-dump','timeout','resources','start-limit-hit','watchdog','protocol','oom-kill'}}
UNIT_KEYS = tuple(UNIT_ENUMS)+('MainPID','ExecMainCode','ExecMainStatus','FragmentPath','DropInPaths')


class Unavailable(Exception):
    pass


def _require(value):
    if not value:
        raise Unavailable()


def _error(error):
    if isinstance(error,FileNotFoundError):
        return 'missing'
    if isinstance(error,PermissionError):
        return 'permission_denied'
    if isinstance(error,subprocess.TimeoutExpired):
        return 'command_timeout'
    return 'unavailable'


def _attempt(fn):
    try:
        return fn()
    except Exception as error:
        return {'observed':False,'error':_error(error)}


def _raise(error):
    raise error


def _identity(info):
    return dict(dev=info.st_dev,ino=info.st_ino,type=stat.S_IFMT(info.st_mode))


def _root_trusted(info,directory):
    return (info.st_uid==0 and not info.st_mode&(stat.S_ISUID|stat.S_ISGID|0o022)
            and (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)))


def _parents(path,owners=(0,)):
    for parent in Path(path).parents:
        info=parent.lstat()
        _require(stat.S_ISDIR(info.st_mode) and info.st_uid in owners and
                 not info.st_mode&(stat.S_ISUID|stat.S_ISGID|0o022))


def _read(path,limit,owner=0):
    # Check ancestor links and the opened inode before reading; no file bodies
    # are emitted. Never call this on host.env, auth files, state or journals.
    _parents(path,(0,owner))
    before=Path(path).lstat()
    _require(stat.S_ISREG(before.st_mode) and before.st_uid==owner and
             not before.st_mode&(stat.S_ISUID|stat.S_ISGID|0o022))
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        current=os.fstat(fd)
        _require(_identity(current)==_identity(before) and current.st_uid==owner and
                 current.st_mode==before.st_mode and current.st_size<=limit)
        data=b''
        while len(data)<=limit:
            block=os.read(fd,min(65536,limit+1-len(data)))
            if not block:
                break
            data+=block
        _require(len(data)<=limit)
        return data
    finally:
        os.close(fd)


def _json(path,limit=65536,owner=0):
    def pairs(items):
        result={}
        for key,value in items:
            _require(key not in result)
            result[key]=value
        return result
    value=json.loads(_read(path,limit,owner),object_pairs_hook=pairs,
                     parse_constant=lambda _:(_ for _ in ()).throw(Unavailable()))
    _require(isinstance(value,dict))
    return value


def metadata(path,ledger=None,service=None,directory=False,mode=None):
    def inspect():
        info=Path(path).lstat()
        kind=('directory' if stat.S_ISDIR(info.st_mode) else 'regular' if stat.S_ISREG(info.st_mode)
              else 'symlink' if stat.S_ISLNK(info.st_mode) else 'special')
        row=dict(path=path,observed=True,type=kind,uid=info.st_uid,gid=info.st_gid,
                 mode=format(stat.S_IMODE(info.st_mode),'04o'),rootTrusted=_root_trusted(info,directory))
        if ledger is not None and path in ledger.get('paths',{}):
            row['ledgerIdentityMatches']=_identity(info)==ledger['paths'][path]
        if mode is not None:
            row['modeMatches']=stat.S_IMODE(info.st_mode)==mode
        if service is not None:
            row['serviceOwned']=info.st_uid==service[0] and info.st_gid==service[1] and not info.st_mode&(stat.S_ISUID|stat.S_ISGID|0o077) and (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
        return row
    result=_attempt(inspect)
    result.setdefault('path',path)
    return result


def _run(args):
    # Only callers with fixed argv may use this. Bound reads while the process
    # lives; never inherit HOME, proxy/provider credentials or transport secrets.
    process=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL,env=NATIVE_ENV,start_new_session=True)
    data=b''
    deadline=time.monotonic()+10
    try:
        while time.monotonic()<deadline:
            ready,_,_=select.select([process.stdout],[],[],min(0.1,max(0,deadline-time.monotonic())))
            if ready:
                block=os.read(process.stdout.fileno(),4096)
                if not block:
                    return process.wait(timeout=1),data
                data+=block
                _require(len(data)<=65536)
        raise subprocess.TimeoutExpired(args,10)
    finally:
        # Also kill a descendant holding stdout open after its parent exits.
        if process.returncode is None:
            try:
                os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait(timeout=1)


def _executable(path):
    _parents(path)
    info=Path(path).lstat()
    _require(_root_trusted(info,False) and info.st_mode&0o111)


def classify(log):
    """Consume a private CLI log; export only exact checked-in static lines."""
    before=Path(log).lstat()
    _require(stat.S_ISREG(before.st_mode) and before.st_uid==os.geteuid() and not before.st_mode&0o077)
    fd=os.open(log,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        _require(_identity(os.fstat(fd))==_identity(before))
        os.lseek(fd,max(0,before.st_size-65536),os.SEEK_SET)
        lines=os.read(fd,65536).decode('utf-8',errors='replace').splitlines()
    finally:
        os.close(fd)
    codes=set()
    progress=[]
    for line in lines:
        for unit in UNITS:
            if line.startswith(unit+': '):
                line=line[len(unit)+2:]
                break
        if line in ERROR_CODES:
            codes.add(ERROR_CODES[line])
        match=PROGRESS.fullmatch(line)
        if match:
            progress.append(dict(component=match[1],stage=match[2],state=match[3]))
    return dict(errorCodes=sorted(codes)[:32] or ['unclassified'],
                truncatedCodes=len(codes)>32,progress=progress[-32:])


def _unit(unit,ledger):
    path='/etc/systemd/system/'+unit
    info=Path(path).lstat()
    _require(path in ledger.get('paths',{}) and _identity(info)==ledger['paths'][path])
    row=dict(unit=unit,observed=True,metadata=metadata(path,mode=0o644))
    row['literalHashMatches']=hashlib.sha256(_read(path,65536)).hexdigest()==ledger.get('unitHashes',{}).get(unit)
    if not (row['metadata'].get('rootTrusted') and row['metadata'].get('modeMatches') and row['literalHashMatches']):
        row['observed']=False
        return row
    _executable('/usr/bin/systemctl')
    code,output=_run(['/usr/bin/systemctl','show',unit,'--property='+','.join(UNIT_KEYS),'--no-pager'])
    _require(code==0)
    values={}
    for line in output.decode('utf-8',errors='strict').splitlines():
        key,separator,value=line.partition('=')
        _require(separator and key in UNIT_KEYS and key not in values)
        values[key]=value
    _require(set(values)==set(UNIT_KEYS) and all(values[k] in allowed for k,allowed in UNIT_ENUMS.items()))
    numbers={}
    for key,limit in (('MainPID',2147483647),('ExecMainCode',3),('ExecMainStatus',255)):
        _require(re.fullmatch('[0-9]{1,10}',values[key]) is not None)
        numbers[key]=int(values[key])
        _require(numbers[key]<=limit)
    row['status']={key:values[key] for key in UNIT_ENUMS}
    row['status'].update(numbers)
    row['fragmentMatches']=values['FragmentPath']==path
    row['dropInsAbsent']=values['DropInPaths']==''
    return row


def first_unsafe_pi_entry():
    # Fixed program root only: no settings/auth contents or resolved link targets.
    entries=0
    deadline=time.monotonic()+15
    try:
        for parent,dirs,files in os.walk(PI_ROOT,followlinks=False,onerror=_raise):
            for path in ([Path(parent)] if parent==PI_ROOT else [])+[Path(parent)/name for name in sorted(dirs+files)]:
                entries+=1
                _require(entries<=100000 and time.monotonic()<deadline)
                st=path.lstat()
                if stat.S_ISLNK(st.st_mode):
                    target=os.readlink(path)
                    resolved=os.path.normpath(os.path.join(str(path.parent),target))
                    unsafe=os.path.isabs(target) or not resolved.startswith(PI_ROOT+'/')
                else:
                    unsafe=st.st_uid!=0 or bool(st.st_mode&(stat.S_ISUID|stat.S_ISGID|0o022)) or not (stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode))
                if unsafe:
                    _require(len(str(path))<=4096 and str(path).isascii() and '\n' not in str(path) and '\r' not in str(path))
                    return dict(passed=False,path=str(path),uid=st.st_uid,gid=st.st_gid,mode=format(stat.S_IMODE(st.st_mode),'04o'),entriesObserved=entries)
        _require(entries>0)
        return dict(passed=True,entriesObserved=entries)
    except Exception:
        return dict(passed=False,error='bounded_pi_inventory_unavailable',entriesObserved=entries)


def _pi(ledger):
    info=Path(PI_ROOT).lstat()
    _require(PI_ROOT in ledger.get('paths',{}) and _identity(info)==ledger['paths'][PI_ROOT] and _root_trusted(info,True))
    pkg=_json(PI_PACKAGE,1<<20)
    valid=pkg.get('name')=='@earendil-works/pi-coding-agent' and isinstance(pkg.get('version'),str) and VERSION.fullmatch(pkg['version']) is not None
    row=dict(observed=True,packageIdentityValid=valid)
    if valid:
        row['packageVersion']=pkg['version']
    counts=dict(owner=0,mode=0,type=0,externalLink=0)
    entries=0
    for parent,dirs,files in os.walk(PI_ROOT,followlinks=False,onerror=_raise):
        for path in ([Path(parent)] if parent==PI_ROOT else [])+[Path(parent)/name for name in dirs+files]:
            entries+=1
            _require(entries<=100000)
            st=path.lstat()
            if stat.S_ISLNK(st.st_mode):
                target=os.readlink(path)
                resolved=os.path.normpath(os.path.join(str(path.parent),target))
                counts['externalLink']+=int(os.path.isabs(target) or not resolved.startswith(PI_ROOT+'/'))
            else:
                counts['owner']+=int(st.st_uid!=0)
                counts['mode']+=int(bool(st.st_mode&(stat.S_ISUID|stat.S_ISGID|0o022)))
                counts['type']+=int(not (stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode)))
    row['prefixEntries']=entries
    row['prefixTrustViolations']=counts
    row['launcherMatches']=hashlib.sha256(_read(PI_LAUNCHER,4096)).hexdigest()==LAUNCHER_SHA256
    if valid and not any(counts.values()) and row['launcherMatches']:
        _executable(PI_LAUNCHER)
        _executable('/opt/node/bin/node')
        code,output=_run([PI_LAUNCHER,'--version'])
        row['versionProbeExecuted']=True
        row['versionProbeExitCode']=code if 0<=code<=255 else -1
        version=output.decode('ascii',errors='replace').strip()
        row['executableVersionValid']=VERSION.fullmatch(version) is not None
        row['executableMatchesPackage']=code==0 and version==pkg['version']
        if row['executableVersionValid']:
            row['executableVersion']=version
    return row


def _manifest_digest(manifest):
    keys=('schema','channel','version','sourceCommit','installerProtocol','hostProtocol','extensionProtocol','piRPCVersion','os','arch','libc','components')
    value={key:manifest[key] for key in keys}
    value['components']=[dict(id=c['id'],version=c['version'],artifacts=[{key:a[key] for key in ('name','url','sha256','bytes','format')} for a in c['artifacts']]) for c in manifest['components']]
    text=json.dumps(value,separators=(',',':'),ensure_ascii=False)
    # The immutable official manifest is ASCII. Reject HTML/Unicode forms whose
    # Go JSON escaping would differ rather than report a spurious target match.
    _require(text.isascii() and not any(char in text for char in '<>&'))
    return hashlib.sha256(text.encode()).hexdigest()


def _lease():
    lease=_json('/etc/awf/stopped-lease.json')
    receipt=_json('/etc/awf/install.json',32<<20)
    phase=lease.get('phase')
    return dict(observed=True,phase=phase if phase in ('open','draining','sealed') else 'invalid',
                targetMatches=lease.get('targetManifestSHA256')==_manifest_digest(receipt['manifest']),
                ownerWellFormed=isinstance(lease.get('ownerRequestId'),str) and re.fullmatch('[A-Za-z0-9._:-]{1,128}',lease['ownerRequestId']) is not None)


def _host():
    config=_json('/etc/awf/host.json')
    return dict(observed=True,configurationMatches=all(type(config.get(k)) is type(v) and config[k]==v for k,v in HOST_FIELDS.items()),
                emptyProjectsAndNodes=config.get('projects')=={} and config.get('nodes')=={})


def _settings(path,owner):
    values=_json(path,1<<20,owner)
    lan=values.get('lan',False)
    return dict(observed=True,lanFalse=type(lan) is bool and not lan,
                noAutoUpdate=values.get('noAutoUpdate') is True,noStats=values.get('noStats') is True)


def collect(runner):
    """Return bounded observations; never authorize or adopt installation writes."""
    ledger=runner.ledger
    account=ledger.get('account') or {}
    service=(account.get('uid'),account.get('gid'))
    if not all(type(value) is int and 0<value<=4294967295 for value in service):
        service=None
    result=dict(schema=1,sourceCommit=SOURCE,metadataReadOnly=True,noModels=True,
                metadata=[metadata(path,ledger,directory=True) for path in ROOT_DIRS]+
                         [metadata(path,ledger,mode=mode) for path,mode in ROOT_FILES.items()]+
                         [metadata(path,ledger,service,directory=directory) for path,directory in SERVICE_PATHS.items()],
                units=[{'unit':unit,**_attempt(lambda unit=unit:_unit(unit,ledger))} for unit in UNITS],
                pi=_attempt(lambda:_pi(ledger)),hostConfiguration=_attempt(_host),maintenanceLease=_attempt(_lease),
                magpieSnapshot=_attempt(lambda:_settings('/etc/awf/magpie-settings.json',0)),
                magpieServiceSettings=_attempt(lambda:_settings('/var/lib/awf/magpie-config/magpie/settings.json',service[0])) if service else dict(observed=False,error='service_identity_unavailable'))
    result['pi']['versionProbeMayCreateTemporarySettingsLock']=True
    return result
