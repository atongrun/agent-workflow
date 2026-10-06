#!/usr/bin/env python3
"""Bounded native test of immutable public AWF bytes; no provider/model calls.

Only a small allowlisted report is public. Raw output, tokens and the ownership
ledger stay in a new root-private /tmp directory and are never artifact inputs.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import grp
import re
import shutil
import signal
import select
import stat
import sys
import subprocess
import tarfile
import tempfile
import time
import urllib.request

import package_linux_preview as package
import probe_native_runner as probe
package.configure(probe.RELEASE)

ROOTS = ['/opt/node','/opt/pi-cli','/opt/awf','/opt/magpie','/etc/awf',
         '/var/lib/awf','/var/cache/awf','/var/cache/awf-installer']
LINKS = {'/usr/local/bin/awf':'/opt/awf/awf',
         '/usr/local/bin/pi':'/opt/pi-cli/awf-launcher.mjs',
         '/usr/local/bin/magpie':'/opt/magpie/magpie'}
UNIT_FILES = ['/etc/systemd/system/'+u for u in probe.UNITS]
SCOPE = 'awf-native-ci-install.scope'
CONTROL = Path('/tmp/awf-native-ci-'+os.environ.get('GITHUB_SHA','invalid'))
ENV = {'PATH':'/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C'}
# Filled from independently verified published metadata before any VM trigger.
PINS_BY_VERSION = {
    "v1.0.2-rc.1": {
        "PREVIEW.txt": [
            294,
            "13e9c20fe764090b66ed7718306e36f15c8f57508d62fa8e9f89160aed2a5249"
        ],
        "PROVENANCE.json": [
            2272,
            "c344dfe6c31113c62d77819268969887e76bfcf485c7487eee167dfc8fdf950a"
        ],
        "SHA256SUMS": [
            714,
            "2cbb329074aa45c7db78863c30e88b056e6e43f727f22a263a370cf1dd02b53f"
        ],
        "THIRD_PARTY_NOTICES.txt": [
            16007,
            "f042097d5f0b7cb89fd3997ecc9abb469770d4e15e4dadaaf59f1f0eb143e41a"
        ],
        "awf-extension_v1.0.2-rc.1.tar.gz": [
            2006,
            "572efb6864f90010e601728d5bf066abaa1308317412d0b19d70fdbc0d224b81"
        ],
        "awf-source_v1.0.2-rc.1.tar.gz": [
            429209,
            "24dffb2a854d9fce1002a894df0d7d10f9699e7b319e2b07b99db046d7e8cea6"
        ],
        "awf_v1.0.2-rc.1_linux_amd64.tar.gz": [
            3458263,
            "d2baa5b35ae08b2dff9e845a97f9cbf17ae08940427afb849afe6b920977a619"
        ],
        "install-linux.sh": [
            11366,
            "53d3c080b10d9e57d5f55e7f1a13f56794fa2f720f9c6c496c4cef0afd2692fe"
        ],
        "linux-host-v1.json": [
            2737,
            "3e8e0c52231b12ff88c2c6092fee0c30d17f6fc0457eef3f00d440e518f9e264"
        ]
    },
    "v1.0.2-rc.2": {
        "PREVIEW.txt": [
            294,
            "13e9c20fe764090b66ed7718306e36f15c8f57508d62fa8e9f89160aed2a5249"
        ],
        "PROVENANCE.json": [
            2272,
            "f8c72237a184f9807ab131f2b976b64b7dea5264b9317ebf89627f2d706e5353"
        ],
        "SHA256SUMS": [
            714,
            "f57fbf870d83881ce6ce6ce75a61a52197f18faa9c97db2b3aa85623f1ad66ee"
        ],
        "THIRD_PARTY_NOTICES.txt": [
            16007,
            "f042097d5f0b7cb89fd3997ecc9abb469770d4e15e4dadaaf59f1f0eb143e41a"
        ],
        "awf-extension_v1.0.2-rc.2.tar.gz": [
            2005,
            "4f0cf64d88c14472b18eaeceeffa225cdd4531610a599648afc67c44b4591331"
        ],
        "awf-source_v1.0.2-rc.2.tar.gz": [
            429209,
            "24dffb2a854d9fce1002a894df0d7d10f9699e7b319e2b07b99db046d7e8cea6"
        ],
        "awf_v1.0.2-rc.2_linux_amd64.tar.gz": [
            3458263,
            "c72fbc8094575961c2a1c4d3f899f78bda5f170c40b819eca2623441def20b9e"
        ],
        "install-linux.sh": [
            11366,
            "041113b4bb10d7d974a264f9daf92191cd152cb3cb48c5833f6c776a04f7089d"
        ],
        "linux-host-v1.json": [
            2737,
            "c83ebabaeca915545e4dea9cd484a1b1fc3514b10c1e3a91c039b0158cfb7eec"
        ]
    }
}
PACKAGING_COMMIT = '8f7f06defad8b61c7ac215d2319d6b1aadfe230e'
PINS = PINS_BY_VERSION.get(probe.RELEASE, {})
TARGET_VERSION = 'v1.0.2-rc.2'
CHANNEL_BOOTSTRAP = 'https://raw.githubusercontent.com/atongrun/agent-workflow/awf/linux-v1/scripts/install-linux.sh'
CHANNEL_MANIFEST = 'https://raw.githubusercontent.com/atongrun/agent-workflow/awf/linux-v1/distribution/linux-host-v1.json'
CHANNEL_COMMIT = 'd0e1cae121921bc718c93c56941e6ef8ccef658b'
CHANNEL_BOOTSTRAP_PIN = [11377, '0e295c8458a728c26dfd54dad70b2839e0d5e4431d59d3c3f85b1218fdb3f158']
PI_UPDATE_SHELL = 'umask 0002; printf "AWF_PI_MASK_BEFORE=%s\\n" "$(umask)"; /usr/local/bin/pi update; result=$?; printf "AWF_PI_MASK_AFTER=%s\\n" "$(umask)"; exit "$result"'


class TestFailure(Exception):
    pass


def require(value, message):
    if not value:
        raise TestFailure(message)


def native_deadline():
    now=time.monotonic()
    deadline=now+22*60
    if os.environ.get('AWF_NATIVE_DEADLINE_EPOCH'):
        remaining=int(os.environ['AWF_NATIVE_DEADLINE_EPOCH'])-time.time()-180
        require(9*60<=remaining<=35*60,'whole-job cleanup reserve unavailable')
        deadline=min(deadline,now+remaining)
    return deadline


def manifest_digest(manifest):
    # Exact Go struct field order; all manifest strings are fixed ASCII.
    keys = ('schema','channel','version','sourceCommit','installerProtocol','hostProtocol','extensionProtocol','piRPCVersion','os','arch','libc','components')
    result = {key:manifest[key] for key in keys}
    result['components'] = [dict(id=c['id'], version=c['version'], artifacts=[{key:a[key] for key in ('name','url','sha256','bytes','format')} for a in c['artifacts']]) for c in manifest['components']]
    return hashlib.sha256(json.dumps(result,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def tree_fingerprint(path):
    base = Path(path)
    require(base.is_dir() and not base.is_symlink(),'runtime fingerprint requires a physical program root')
    rows = []
    for root,dirs,files in os.walk(base,followlinks=False):
        for entry in [Path(root)]+[Path(root)/n for n in dirs+files]:
            info = entry.lstat()
            row = [str(entry.relative_to(base)),info.st_mode,info.st_uid,info.st_gid]
            if stat.S_ISREG(info.st_mode):
                row += [info.st_size,package.digest_file(entry)]
            elif stat.S_ISLNK(info.st_mode):
                row += [os.readlink(entry)]
            elif not stat.S_ISDIR(info.st_mode):
                raise TestFailure('special file in Pi runtime')
            rows.append(row)
    return hashlib.sha256(json.dumps(sorted(rows),separators=(',',':')).encode()).hexdigest()


def identity(path):
    s=Path(path).lstat()
    return dict(dev=s.st_dev,ino=s.st_ino,type=stat.S_IFMT(s.st_mode))


def same(path, saved):
    return identity(path)==saved


AWF_FAILURE_CODES = {
    'native receipt invalid':'receipt_invalid',
    'installed command link changed':'command_link_changed',
    'program command link changed':'program_link_changed',
    'system path ownership, type or permissions require inspection':'system_path_untrusted',
    'fixed program mode differs from install provenance':'fixed_program_mode_changed',
    'fixed program differs from install provenance':'fixed_program_bytes_changed',
    'current official Pi package identity invalid':'pi_package_identity_invalid',
    'stable Pi launcher changed; upstream npm owns only its package tree':'pi_launcher_changed',
    'stable Pi launcher must be executable':'pi_launcher_mode_changed',
    'Pi prefix has an external link':'pi_external_link',
    'Pi prefix link escapes':'pi_link_escape',
    'current Pi package and executable version disagree':'pi_executable_identity_disagrees',
    'Magpie private state ownership/type changed':'magpie_state_untrusted',
    'Magpie LAN must be false or omitted':'magpie_lan_invalid',
    'invalid Magpie settings':'magpie_settings_invalid',
    'stopped maintenance target differs from installed receipt':'maintenance_target_changed',
    'stopped maintenance owner/seal changed':'maintenance_owner_changed',
    'systemd shutdown is not established':'shutdown_unverified',
    'partially running service pair requires awf stop before start':'partial_service_pair',
    'systemd unit ownership, overrides or control-group contract changed':'unit_contract_changed',
    'loopback Host maintenance unavailable':'host_maintenance_unavailable',
    'native command systemctl failed':'systemctl_failed',
    'native command awf-launcher.mjs failed':'pi_version_command_failed',
}


def awf_failure_diagnostic(log):
    # Never export raw command output, paths, tokens, HTTP bodies or npm logs.
    with log.open('rb') as stream:
        stream.seek(0,os.SEEK_END)
        stream.seek(max(0,stream.tell()-65536))
        lines=stream.read(65536).decode('utf-8',errors='replace').splitlines()
    codes=sorted({AWF_FAILURE_CODES[line] for line in lines if line in AWF_FAILURE_CODES})
    progress=[]
    for line in lines:
        match=re.fullmatch(r'AWF (bundle|awf-host|magpie) (service-start|health|service-stop|service-stop-retry): (started|completed|failed)',line)
        if match:
            progress.append(dict(component=match[1],stage=match[2],state=match[3]))
    return dict(errorCodes=codes or ['unclassified'],progress=progress[-32:])


def private_file(path, data):
    # Ledger/control files are created or replaced only inside a held, trusted
    # root-private directory. No remote text or token becomes a filename.
    fd,temp=tempfile.mkstemp(prefix='.ledger-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as out:
            os.fchmod(out.fileno(),0o600)
            json.dump(data,out)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp,path)
        parent=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def safe_tree(path, owners):
    base=Path(path)
    require(base.is_dir() and not base.is_symlink(),'owned root is not a directory')
    for root,dirs,files in os.walk(base,followlinks=False):
        for entry in [Path(root)]+[Path(root)/n for n in dirs+files]:
            s=entry.lstat()
            require(s.st_uid in owners and s.st_gid in owners.values(), 'foreign ownership in owned tree')
            require(stat.S_ISDIR(s.st_mode) or stat.S_ISREG(s.st_mode) or stat.S_ISLNK(s.st_mode), 'special file in owned tree')
            require(s.st_dev==base.lstat().st_dev,'foreign device in owned tree')
    for row in probe.mount_records(Path('/proc/self/mountinfo').read_text()):
        require(not (row['target']==str(base) or row['target'].startswith(str(base)+'/')), 'mounted content in owned tree')


def capture_existing_runtime():
    result={}
    for name in ('node','npm','npx'):
        path=shutil.which(name,path=ENV['PATH'])
        require(path is not None,'preinstalled runtime command missing')
        target=Path(path).resolve(strict=True)
        entry_stat=Path(path).lstat()
        target_stat=target.stat()
        result[name]=dict(path=path,target=str(target),entry=identity(path),
                          entryMode=entry_stat.st_mode,entryUID=entry_stat.st_uid,entryGID=entry_stat.st_gid,
                          targetMode=target_stat.st_mode,targetUID=target_stat.st_uid,targetGID=target_stat.st_gid,
                          sha256=package.digest_file(target))
    return result


def unit_status(unit):
    return probe.properties(probe.run('/usr/bin/systemctl','show',unit,
        '--property=LoadState,FragmentPath,DropInPaths,ActiveState,MainPID,ControlGroup,User,Group,KillMode','--no-pager'))


def cgroup_pids(unit):
    root=Path('/sys/fs/cgroup/system.slice')/unit
    if not root.exists():
        return set()
    files=list(root.rglob('cgroup.procs'))
    require(len(files)<=4096,'cgroup traversal limit')
    return {int(p) for f in files for p in f.read_text().split()}


def stopped(unit):
    values=unit_status(unit)
    require(values.get('ActiveState') in ('inactive','failed') and values.get('MainPID')=='0' and not cgroup_pids(unit),'owned service shutdown not verified')


def source_units(archive):
    with tarfile.open(archive,'r:gz') as tar:
        content=tar.extractfile('internal/hostinstall/initplan.go').read().decode()
    return {unit:re.search(r'const '+name+r' = `([^`]+)`',content).group(1)
            for unit,name in [('awf-host.service','hostUnitProposal'),('awf-magpie.service','magpieUnitProposal')]}


class Acceptance:
    def __init__(self, report, initial_runtime):
        self.report=report
        self.ledger=dict(paths={},transitions=[],account=None,group=None,unitHashes={},initialRuntime=initial_runtime)
        self.deadline=native_deadline()
        self.ledger['scratchBefore']={parent:sorted(p.name for pattern in patterns for p in Path(parent).glob(pattern))
            for parent,patterns in [('/tmp',('awf-bootstrap-*','awf-linux-install-*')),('/opt',('.awf-install-*','.awf-update-*'))]}
        self.ledger['controlIdentity']=identity(CONTROL)
        self.save()

    def save(self):
        private_file(CONTROL/'ledger.json',self.ledger)

    def observe(self):
        changed=False
        candidates=ROOTS+list(LINKS)+UNIT_FILES
        for path in candidates:
            if path not in self.ledger['paths'] and os.path.lexists(path):
                self.ledger['paths'][path]=identity(path)
                changed=True
        if self.ledger['account'] is None:
            try:
                account=pwd.getpwnam('awf')
                self.ledger['account']=dict(uid=account.pw_uid,gid=account.pw_gid,home=account.pw_dir,shell=account.pw_shell)
                changed=True
            except KeyError:
                pass
        if self.ledger['group'] is None:
            try:
                group=grp.getgrnam('awf')
                self.ledger['group']=dict(gid=group.gr_gid,members=group.gr_mem)
                changed=True
            except KeyError:
                pass
        if changed:
            self.save()

    def resources(self):
        data=probe.memory_sample(Path('/proc/meminfo').read_text(),Path('/proc/pressure/memory').read_text())
        values=self.report.setdefault('resources',dict(minimumAvailableBytes=data['availableBytes'],installerPeakBytes=0,combinedServicesPeakBytes=0,cloudConeLowMemoryProof=False))
        values['minimumAvailableBytes']=min(values['minimumAvailableBytes'],data['availableBytes'])
        sizes={}
        for unit in (SCOPE,*probe.UNITS):
            path=Path('/sys/fs/cgroup/system.slice')/unit
            if not path.exists():
                continue
            if unit==SCOPE and not self.ledger.get('scopeIdentity'):
                self.ledger['scopeIdentity']=identity(path)
                self.save()
            current=path/'memory.current'
            if current.is_file():
                sizes[unit]=int(current.read_text())
            events=path/'memory.events'
            if events.is_file():
                counters=dict(row.split() for row in events.read_text().splitlines())
                require(int(counters.get('oom',0))==0 and int(counters.get('oom_kill',0))==0,'native test cgroup OOM observed')
        values['installerPeakBytes']=max(values['installerPeakBytes'],sizes.get(SCOPE,0))
        services=sum(sizes.get(u,0) for u in probe.UNITS)
        values['combinedServicesPeakBytes']=max(values['combinedServicesPeakBytes'],services)
        require(services<=2<<30,'combined test service memory budget exceeded')
        self.low_available=getattr(self,'low_available',0)+1 if data['availableBytes']<192<<20 else 0
        require(self.low_available<3,'host resource abort; not an installer code failure')

    def command(self, name, args, seconds, capture=False, environment=None, input_data=None):
        start=time.monotonic()
        require(start+seconds<self.deadline,'overall native test deadline')
        print('AWF native test: '+name+' started',flush=True)
        log=CONTROL/(name+'.log')
        bounded=name=='pi-update' and (getattr(self,'pi_update_diagnostic',False) or getattr(self,'acl_full_acceptance',False))
        with log.open('xb') as out:
            os.chmod(log,0o600)
            require(input_data is None or input_data==b'y\n','unexpected native command input')
            process=subprocess.Popen(args,stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,stdout=subprocess.PIPE if bounded else out,stderr=subprocess.STDOUT if bounded else out,env=environment or ENV,start_new_session=True)
            if bounded:os.set_blocking(process.stdout.fileno(),False)
            def drain_output():
                if not bounded:return True
                while True:
                    try:block=os.read(process.stdout.fileno(),65536)
                    except BlockingIOError:return True
                    if not block:return True
                    remaining=max(0,(1<<20)-out.tell())
                    out.write(block[:remaining])
                    if len(block)>remaining:
                        self.report.setdefault('piObservation',{}).setdefault('after',{})['outputLimitExceeded']=True
                        return False
            if name=='pi-update':
                self.report['piUpdateExecuted']=True
                self.report['piUpdate']=dict(executionStarted=True,passed=False)
            try:
                if input_data is not None:
                    try:
                        process.stdin.write(input_data)
                        process.stdin.close()
                    except BrokenPipeError:
                        pass  # Preserve the actual early child exit as the failure.
                while process.poll() is None:
                    require(drain_output(),'Pi update output limit')
                    self.observe()
                    self.resources()
                    if time.monotonic()-start>seconds:
                        os.killpg(process.pid,signal.SIGTERM)
                        try:
                            process.wait(timeout=8)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid,signal.SIGKILL)
                            process.wait(timeout=8)
                        raise TestFailure('stage timeout: '+name)
                    time.sleep(0.5)
            finally:
                if input_data is not None and not process.stdin.closed:
                    try:
                        process.stdin.close()
                    except BrokenPipeError:
                        pass
                if process.poll() is None:
                    os.killpg(process.pid,signal.SIGTERM)
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid,signal.SIGKILL)
                        process.wait(timeout=8)
                if bounded:
                    drain_output();process.stdout.close()
                    self.report['stages'].append(dict(name=name,exitCode=process.returncode,signal=-process.returncode if process.returncode is not None and process.returncode<0 else None,elapsedSeconds=round(time.monotonic()-start,2)))
                primary=sys.exc_info()[0]
                try:self.observe()
                except Exception as error:
                    if primary is None:raise
                    if bounded:self.report.setdefault('piObservation',{}).setdefault('after',{})['finalObservationUnavailable']=type(error).__name__
        if not bounded:self.report['stages'].append(dict(name=name,exitCode=process.returncode,elapsedSeconds=round(time.monotonic()-start,2)))
        print('AWF native test: '+name+' exit '+str(process.returncode),flush=True)
        if process.returncode and args[0]=='/usr/local/bin/awf':
            try:
                import native_startup_diagnostics as startup
                diagnostic=startup.classify(log)
                diagnostic['units']=self.failure_unit_status()
                diagnostic['startupChecks']=startup.collect(self)
                diagnostic['firstUnsafePiEntry']=startup.first_unsafe_pi_entry()
                self.report['awfFailureDiagnostic']=diagnostic
            except Exception:
                self.report['awfFailureDiagnostic']=dict(errorCodes=['diagnostic_unavailable'],progress=[])
        require(process.returncode==0,'stage failed: '+name)
        return log.read_bytes() if capture else None

    def failure_unit_status(self):
        results=[]
        choices={'LoadState':{'loaded','not-found','error','masked','bad-setting'},
                 'ActiveState':{'active','inactive','failed','activating','deactivating','reloading','maintenance','refreshing'},
                 'SubState':{'running','dead','failed','start-pre','start','start-post','stop','stop-sigterm','stop-sigkill','stop-post','auto-restart','exited'},
                 'Result':{'success','exit-code','signal','core-dump','timeout','resources','start-limit-hit','watchdog','protocol','oom-kill'}}
        for unit,path in zip(probe.UNITS,UNIT_FILES):
            row=dict(unit=unit,observed=False)
            try:
                require(path in self.ledger['paths'] and same(path,self.ledger['paths'][path]),'unit identity unverified')
                values=probe.properties(probe.run('/usr/bin/systemctl','show',unit,'--property=LoadState,ActiveState,SubState,Result,MainPID','--no-pager'))
                require(set(values)==set(choices)|{'MainPID'} and
                        all(values[k] in allowed for k,allowed in choices.items()) and
                        re.fullmatch('[0-9]{1,10}',values['MainPID']),'unit diagnostic outside bounded enums')
                row.update(observed=True,status=values)
            except Exception:
                pass
            results.append(row)
        return results

    def download(self):
        downloads=CONTROL/'assets'
        downloads.mkdir(mode=0o700)
        opener=urllib.request.build_opener(package.OfficialRedirects())
        for name,(size,sha) in PINS.items():
            path=downloads/name
            url='https://github.com/'+probe.REPOSITORY+'/releases/download/'+probe.RELEASE+'/'+name
            with opener.open(url,timeout=45) as response,path.open('xb') as out:
                received=0
                while block:=response.read(1<<20):
                    received+=len(block)
                    require(received<=size,'public asset size limit')
                    out.write(block)
            require(received==size and package.digest_file(path)==sha,'immutable public asset mismatch')
        package.verify(downloads,PACKAGING_COMMIT)
        self.ledger['unitHashes']={u:hashlib.sha256(text.encode()).hexdigest()
                                  for u,text in source_units(downloads/package.NAMES[2]).items()}
        self.save()
        self.report['publicAssetsVerified']=len(PINS)
        if getattr(self,'pi_update_diagnostic',False):
            pass
        elif probe.RELEASE != TARGET_VERSION:
            target = downloads/'target'
            target.mkdir(mode=0o700)
            for name in ('linux-host-v1.json',):
                self.download_pinned(TARGET_VERSION,name,target/name)
        else:
            require(CHANNEL_BOOTSTRAP_PIN is not None,'channel bootstrap pin absent')
            self.download_url(CHANNEL_BOOTSTRAP,downloads/'channel-install-linux.sh',*CHANNEL_BOOTSTRAP_PIN)
        if getattr(self,'default_entry_acceptance',False):
            self.verify_channel_manifest('before')
        self.current_version=probe.RELEASE
        return downloads

    def verify_channel_manifest(self,stage):
        require(stage in ('before','after'),'invalid channel observation stage')
        size,sha=PINS_BY_VERSION[TARGET_VERSION]['linux-host-v1.json']
        self.download_url(CHANNEL_MANIFEST,CONTROL/('channel-'+stage+'.json'),size,sha)
        self.report.setdefault('channelManifest',dict(expectedCommit=CHANNEL_COMMIT,version=TARGET_VERSION,sha256=sha))[stage+'Verified']=True

    def verify_pi_update_diagnostic(self):
        import native_pi_update_observation as observation
        import native_startup_diagnostics as startup
        self.verify_rpc('initial')
        self.command('stop-for-pi',['/usr/local/bin/awf','stop'],120)
        for unit in probe.UNITS: stopped(unit)
        home=CONTROL/'pi-root-home';home.mkdir(mode=0o700)
        trace=CONTROL/'pi-process-observation.jsonl';trace.touch(mode=0o600)
        observer=CONTROL/'pi-observer.mjs'
        observer.write_text(observation.observer_source(trace,Path.cwd()))
        observer.chmod(0o600)
        before=dict(objects=[observation.object_metadata(p) for p in observation.OBJECTS],
                    packageVersion=observation.trusted_package_version(),cwd=observation.safe_path(str(Path.cwd())),
                    uid=os.getuid(),gid=os.getgid(),prefixIdentity=identity('/opt/pi-cli'),
                    launcherSHA256=package.digest_file(Path('/opt/pi-cli/awf-launcher.mjs')),
                    nodeSHA256=package.digest_file(Path('/opt/node/bin/node')),
                    npmCLISHA256=package.digest_file(Path('/opt/node/lib/node_modules/npm/bin/npm-cli.js')))
        npm=self.command('npm-version',['/opt/node/bin/node','/opt/node/lib/node_modules/npm/bin/npm-cli.js','--version'],30,True,dict(ENV,HOME=str(home)))
        require(npm.strip()==b'10.9.3','private npm version differs')
        before['npmVersion']='10.9.3';before['nodeVersion']='22.19.0'
        effective=self.command('npm-effective-mask',['/opt/node/bin/node','/opt/node/lib/node_modules/npm/bin/npm-cli.js','config','get','umask'],30,True,dict(ENV,HOME=str(home))).decode().strip()
        require(re.fullmatch('[0-9]{1,4}',effective) and 0<=int(effective)<=511,'effective npm mask unavailable')
        before['effectiveNpmUmaskDecimal']=int(effective)
        import native_acl_observation as acl
        before['aclChain']=acl.collect()
        self.report['piObservation']=dict(before=before,after={})
        report_write(self.diagnostic_report_path,self.report)
        environment=dict(ENV,HOME=str(home),NODE_OPTIONS='--import='+str(observer))
        # The finally runs even for a failing child command or signal and writes
        # observations before any version, mask, type or trust assertion.
        try:
            self.command('pi-update',['/bin/sh','-c',PI_UPDATE_SHELL],8*60,False,environment)
        finally:
            limited=self.report.get('piObservation',{}).get('after',{}).get('outputLimitExceeded',False)
            after=dict(aclChain=acl.collect(),objects=[observation.object_metadata(p) for p in observation.OBJECTS],
                       **observation.load_trace(trace),**observation.update_output(CONTROL/'pi-update.log'),
                       **observation.trusted_package_version())
            if limited:after.update(outputLimitExceeded=True,outputUnavailable='output_limit')
            trust=startup.first_unsafe_pi_entry()
            if isinstance(trust.get('path'),str):after['firstUnsafeObject']=observation.object_metadata(trust['path'])
            self.report['piPermissionCheck']=trust
            self.report['piObservation']['after']=after
            self.report['piObservation']['updateStage']=next((s for s in reversed(self.report['stages']) if s['name']=='pi-update'),dict(unavailable=True))
            self.report['piDiagnosticObserved']=bool(after.get('processObservations'))
            report_write(self.diagnostic_report_path,self.report)
        require(not after.get('outputLimitExceeded'),'Pi update output limit')
        require(after.get('shellMaskMarkers')==[dict(point='BEFORE',umask='0002'),dict(point='AFTER',umask='0002')],'root updater shell umask changed')
        spawns=[r for r in after.get('processObservations',[]) if r['kind']=='npm-spawn' and 'install' in r.get('argv',[])]
        children=[r for r in after.get('processObservations',[]) if r['kind']=='node-start' and 'install' in r.get('argv',[])]
        require(len(spawns)==1 and len(children)==1,'actual npm update spawn/child observation unavailable')
        require(all(r['uid']==0 and r['gid']==0 and r['umask']=='0022' for r in children),'actual root npm safe process mask unavailable')
        require('--ignore-scripts' in spawns[0]['argv'] and '--prefix' in spawns[0]['argv'] and '/opt/pi-cli' in spawns[0]['argv'],'official single-prefix scripts-disabled contract differs')
        require(trust.get('passed') is True,'updated Pi prefix permissions unsafe')
        require(after.get('installedPackageVersion') is not None,'updated Pi version unavailable from trusted physical package')
        require(after['objects'][0].get('objectType')=='directory' and after['objects'][2].get('objectType')=='file','updated Pi package root or launcher type unsafe')
        require(package.digest_file(Path('/opt/pi-cli/awf-launcher.mjs'))==before['launcherSHA256'],'stable Pi launcher changed')
        require(same('/opt/pi-cli',before['prefixIdentity']),'sole Pi prefix inode changed')
        version=self.command('pi-version-updated',['/usr/local/bin/pi','--version'],20,True,dict(ENV,HOME=str(home))).decode().strip()
        require(re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',version) and version==after['installedPackageVersion'] and tuple(map(int,version.split('.')))>(1,0,2),'trusted updated Pi versions disagree')
        require(after.get('updaterReportedVersion')==version,'updater and trusted installed version disagree')
        self.report['piUpdate'].update(passed=True,initialVersion='1.0.2',actualVersion=version,prefixPermissionsPassed=True)
        self.command('start-after-pi',['/usr/local/bin/awf','start'],120)
        self.health(2);self.verify_rpc('after-pi')

    def verify_install(self):
        require(json.loads(self.command('build-identity',['/opt/awf/awf','linux-build-identity'],20,True))==
                dict(schema=1,version=self.current_version,sourceCommit=probe.SOURCE,os='linux',arch='amd64',hostProtocol='v1'),'installed Host identity differs')
        require(self.command('version',['/usr/local/bin/awf','version'],20,True).decode().strip()==self.current_version,'AWF version differs')
        require(self.command('pi-version',['/usr/local/bin/pi','--version'],20,True).decode().strip()=='1.0.2','Pi version differs')
        require(self.command('node-version',['/opt/node/bin/node','--version'],20,True).decode().strip()=='v22.19.0','Node version differs')
        require(capture_existing_runtime()==self.ledger['initialRuntime'],'preinstalled Node/npm/npx changed')
        for path,target in LINKS.items():
            require(Path(path).is_symlink() and os.readlink(path)==target,'installed command link differs')
        require(not os.path.lexists('/root/.pi/agent'),'ordinary root Pi agent directory modified')
        self.report['preinstalledRuntimePreserved']=True

    def download_url(self,url,target,size,sha):
        require(isinstance(size,int) and 0<size<256<<20 and re.fullmatch('[0-9a-f]{64}',sha),'public pin missing')
        opener=urllib.request.build_opener(package.OfficialRedirects())
        with opener.open(url,timeout=45) as response,target.open('xb') as out:
            received=0
            while block:=response.read(1<<20):
                received+=len(block)
                require(received<=size,'public download exceeded pin')
                out.write(block)
        require(received==size and package.digest_file(target)==sha,'public bytes differ from pin')

    def download_pinned(self,version,name,target):
        require(version in PINS_BY_VERSION and name in PINS_BY_VERSION[version],'unapproved candidate asset')
        self.download_url('https://github.com/'+probe.REPOSITORY+'/releases/download/'+version+'/'+name,
                          target,*PINS_BY_VERSION[version][name])

    def local_api(self,path,body=None):
        credentials=probe.properties(Path('/etc/awf/host.env').read_text())
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        request=urllib.request.Request('http://127.0.0.1:7070'+path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization':'Bearer '+credentials['AWF_HOST_TOKEN'],'Content-Type':'application/json'})
        with opener.open(request,timeout=5) as response:
            data=response.read(1<<20)
            require(not response.read(1),'local fixture API size limit')
        return json.loads(data)

    def begin_replacement(self,target):
        require(target['version']==TARGET_VERSION and target['sourceCommit']==probe.SOURCE,'upgrade target identity differs')
        roots=[]
        for path in ('/opt/node','/opt/awf','/opt/magpie'):
            require(path in self.ledger['paths'] and same(path,self.ledger['paths'][path]),'old program identity changed before upgrade')
            backup=path+'.before-'+manifest_digest(target)
            require(not os.path.lexists(backup),'existing upgrade backup; no adoption')
            roots.append(dict(path=path,backup=backup,oldIdentity=self.ledger['paths'][path]))
        # Persist every old inode and exact destination before the first rename.
        self.ledger['transitions'].append(dict(target=target,roots=roots,completed=False))
        self.save()

    def finish_replacement(self):
        transition=self.ledger['transitions'][-1]
        receipt=json.loads(Path('/etc/awf/install.json').read_text())
        require(receipt['manifest']==transition['target'] and receipt['programsInstalled'] is True and
                receipt['preparation']['manifestSHA256']==manifest_digest(transition['target']),
                'updated receipt differs from the verified immutable target')
        require(not os.path.lexists('/etc/awf/update-pending.json'),'upgrade still pending')
        replacement={}
        for row in transition['roots']:
            require(same(row['backup'],row['oldIdentity']),'retained backup is not the recorded old root')
            require(not same(row['path'],row['oldIdentity']),'program root was not replaced')
            for path in (row['path'],row['backup']):
                safe_tree(path,{0:0})
            replacement[row['path']]=identity(row['path'])
            replacement[row['backup']]=row['oldIdentity']
        # Validate the complete new receipt inventory before recording new roots.
        components=receipt['preparation']['components']
        expected={c['id']:c['version'] for c in transition['target']['components']}
        require(len(components)==5 and {c['id'] for c in components}==set(expected) and
                all(c['version']==expected[c['id']] for c in components),'updated component inventory incomplete')
        prefixes={'node':'/opt/node/','awf-host':'/opt/awf/','awf-extension':'/opt/awf/','magpie':'/opt/magpie/'}
        files=set()
        directories={'/opt/node','/opt/awf','/opt/magpie'}
        for component in components:
            if component['id']=='pi':
                continue
            require(bool(component['files']),'updated component file inventory empty')
            for file in component['files']:
                path=Path('/'+file['path'])
                require(str(path).startswith(prefixes[component['id']]) and '..' not in path.parts and
                        str(path) not in files,'unexpected or duplicate upgrade receipt path')
                files.add(str(path))
                parent=path.parent
                while str(parent) not in ('/opt','/'):
                    directories.add(str(parent))
                    parent=parent.parent
                info=path.lstat()
                if file.get('linkTarget'):
                    require(path.is_symlink() and os.readlink(path)==file['linkTarget'],'updated link differs from receipt')
                else:
                    require(stat.S_ISREG(info.st_mode) and info.st_size==file['bytes'] and
                            stat.S_IMODE(info.st_mode)==file['mode'] and package.digest_file(path)==file['sha256'],
                            'updated runtime inventory differs from receipt')
        actual_files=set()
        actual_directories=set()
        for root in ('/opt/node','/opt/awf','/opt/magpie'):
            for current,dirs,leaves in os.walk(root,followlinks=False):
                actual_directories.add(current)
                for name in dirs+leaves:
                    path=Path(current)/name
                    if path.is_symlink() or path.is_file():
                        actual_files.add(str(path))
                    elif path.is_dir():
                        actual_directories.add(str(path))
        require(actual_files==files and actual_directories==directories,'new program trees differ from the complete receipt inventory')
        self.ledger['paths'].update(replacement)
        transition['completed']=True
        self.save()

    def verify_rpc(self,phase):
        account=self.ledger['account']
        directory=Path('/var/lib/awf/native-ci-rpc')
        if not directory.exists():
            directory.mkdir(mode=0o700)
            os.chown(directory,account['uid'],account['gid'])
            diagnostic=directory/'diagnostic.mjs'
            diagnostic.write_text('import {writeFileSync} from "node:fs";\nexport default function(pi){pi.on("session_start",async()=>{writeFileSync(process.env.NATIVE_PI_DIAGNOSTIC_FILE,JSON.stringify({tools:pi.getAllTools().map(t=>t.name).filter(n=>n.startsWith("awf_")).sort(),activeTools:pi.getActiveTools().sort()}),{mode:0o600});});}\n')
            diagnostic.chmod(0o600)
            os.chown(diagnostic,account['uid'],account['gid'])
        diagnostic=directory/'diagnostic.mjs'
        result=directory/(phase+'.json')
        args=['/usr/sbin/runuser','--user','awf','--','/usr/bin/env','-i',
            'PATH='+ENV['PATH'],'LC_ALL=C','HOME=/var/lib/awf','PI_CODING_AGENT_DIR=/var/lib/awf/pi-agent',
            'AWF_HOST_URL=http://127.0.0.1:7070','AWF_EXTENSION_TOKEN=synthetic-unused-tool-token',
            'AWF_TASK_ID=native-ci-rpc-fixture','AWF_ROLE=architect','AWF_LIFECYCLE_REVISION=0',
            'NATIVE_PI_DIAGNOSTIC_FILE='+str(result),'/usr/local/bin/pi','--offline','--mode','rpc',
            '--session-dir',str(directory),'--session-id','11111111-1111-4111-8111-111111111111',
            '--no-extensions','--no-skills','--no-prompt-templates','--no-context-files','--no-approve',
            '--tools','awf_task,awf_plan,awf_execution,awf_finish',
            '--extension','/opt/awf/extensions/awf.ts','--extension',str(diagnostic)]
        with (CONTROL/('rpc-'+phase+'.log')).open('xb') as err:
            process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,env=ENV,cwd=directory,start_new_session=True)
            try:
                process.stdin.write(b'{"type":"get_state","id":"native-state"}\n{"type":"get_commands","id":"native-commands"}\n')
                process.stdin.flush()
                responses={}
                deadline=time.monotonic()+45
                buffer=b''
                while len(responses)<2 and time.monotonic()<deadline:
                    ready,_,_=select.select([process.stdout],[],[],1)
                    if not ready:
                        require(process.poll() is None,'official Pi RPC exited before read-only responses')
                        continue
                    chunk=os.read(process.stdout.fileno(),65536)
                    require(bool(chunk) and len(buffer)+len(chunk)<1<<20,'official Pi RPC response bound')
                    buffer+=chunk
                    while b'\n' in buffer:
                        line,buffer=buffer.split(b'\n',1)
                        data=json.loads(line)
                        if data.get('type')=='response' and data.get('id') in ('native-state','native-commands'):
                            require(data.get('success') is True,'official Pi read-only RPC refused')
                            responses[data['id']]=data
                require(len(responses)==2 and result.is_file(),'official Pi RPC or production tool diagnostic missing')
                tools=json.loads(result.read_text())
                expected=['awf_execution','awf_finish','awf_plan','awf_task']
                require(tools['tools']==expected and sorted(tools['activeTools'])==expected,'production AWF extension tools differ')
                self.report.setdefault('rpcCompatibility',[]).append(dict(phase=phase,passed=True,productionExtensionLoaded=True,toolNames=expected,readOnlyCommands=['get_state','get_commands'],modelRequests=0))
            finally:
                if process.poll() is None:
                    os.killpg(process.pid,signal.SIGTERM)
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid,signal.SIGKILL)
                        process.wait(timeout=8)

    def verify_upgrades(self,assets,default_entry=False):
        fixture=self.local_api('/v1/tasks',dict(requestId='linux-native-upgrade-fixture',title='Synthetic installer persistence fixture; no model turn'))['task']
        task_path='/v1/tasks/'+fixture['id']
        snapshot=self.local_api(task_path)['task']
        preserved={path:package.digest_file(Path(path)) for path in
            ('/etc/awf/host.env','/etc/awf/host.json','/etc/awf/magpie-settings.json')}
        agent_identity=identity('/var/lib/awf/pi-agent')
        if default_entry:
            self.verify_rpc('initial')
        else:
            self.verify_pi_update_diagnostic()
        pi_tree=tree_fingerprint('/opt/pi-cli')
        home=CONTROL/'pi-root-home'
        agent=self.command('pi-root-agent-default',['/opt/node/bin/node','--input-type=module','-e','import {getAgentDir} from "file:///opt/pi-cli/lib/node_modules/@earendil-works/pi-coding-agent/dist/config.js"; process.stdout.write(getAgentDir());'],20,True,dict(ENV,HOME=str(home))).decode()
        require(agent==str(home/'.pi/agent') and not os.path.lexists('/root/.pi/agent'),'ordinary root Pi default HOME state isolation')
        target=json.loads((assets/'target/linux-host-v1.json').read_text())
        self.begin_replacement(target)
        if default_entry:
            self.command('awf-update',['/usr/local/bin/awf','update'],8*60,True,input_data=b'y\n')
        else:
            self.command('awf-update',['/usr/local/bin/awf','update','--version',TARGET_VERSION,'--yes'],8*60)
        self.finish_replacement()
        self.current_version=TARGET_VERSION
        self.health(3)
        self.verify_rpc('after-awf')
        require(tree_fingerprint('/opt/pi-cli')==pi_tree and same('/var/lib/awf/pi-agent',agent_identity),'AWF upgrade modified current Pi or service agent root')
        require(all(package.digest_file(Path(path))==digest for path,digest in preserved.items()),'upgrade changed config or generated credentials')
        require(self.local_api(task_path)['task']==snapshot,'upgrade changed persisted fixture task')
        require(capture_existing_runtime()==self.ledger['initialRuntime'],'upgrades changed preinstalled runtime')
        import native_acl_observation as acl
        self.report['aclEvidence']=dict(afterAWF=acl.collect())
        self.report['awfUpdate']=dict(passed=True,fromVersion=probe.RELEASE,toVersion=TARGET_VERSION,explicitImmutableVersion=not default_entry,defaultChannelSelection=default_entry,retainedBackupCount=3,currentPiTreePreserved=True)
        self.report['businessStatePreserved']=dict(passed=True,config=True,credentials=True,syntheticTask=True,serviceAgentRoot=True,modelRequests=0)
        if default_entry:
            self.verify_default_noop()

    def verify_default_noop(self):
        paths=('/opt/node','/opt/pi-cli','/opt/awf','/opt/magpie','/etc/awf/install.json')
        before={path:identity(path) for path in paths}
        program_bytes={path:tree_fingerprint(path) for path in paths[:-1]}
        receipt=Path('/etc/awf/install.json').read_bytes()
        pids={unit:unit_status(unit)['MainPID'] for unit in probe.UNITS}
        output=self.command('awf-default-update',['/usr/local/bin/awf','update'],90,True)
        require(b'AWF bundle verify-current: completed' in output and ('AWF '+TARGET_VERSION+' verified.').encode() in output,'bare update did not report current release')
        require(before=={path:identity(path) for path in paths} and Path('/etc/awf/install.json').read_bytes()==receipt,'default no-op replaced programs or receipt')
        require(program_bytes=={path:tree_fingerprint(path) for path in paths[:-1]},'default no-op changed program contents')
        require(pids=={unit:unit_status(unit)['MainPID'] for unit in probe.UNITS},'default no-op restarted services')
        require(not os.path.lexists('/etc/awf/update-pending.json'),'default no-op created pending update')
        self.health(2)
        self.report['noOp']=dict(passed=True,command='awf update',version=TARGET_VERSION,programRootsPreserved=True,receiptPreserved=True,servicePIDsPreserved=True)

    def retain_failed_start(self):
        # Preserve only this already diagnosed stopped installation until the
        # immediately following safe report upload. No remote continuation.
        require(self.report.get('failure')=='stage failed: start-after-pi'
                and self.report.get('piUpdate',{}).get('passed') is True,
                'only actual post-Pi startup failure may be retained')
        require(same(CONTROL,self.ledger['controlIdentity']),'native control inode changed')
        for unit in probe.UNITS:
            self.trusted_unit(unit)
            stopped(unit)
        self.report['retainedForDiagnosis']=True
        self.report['firstAttemptFailure']=self.report['failure']

    def health(self, round_number):
        tokens=probe.properties(Path('/etc/awf/host.env').read_text())
        require(set(tokens)=={'AWF_HOST_TOKEN','AWF_EXTENSION_TOKEN'} and len(set(tokens.values()))==2 and
                all(re.fullmatch('[0-9a-f]{64}',v) for v in tokens.values()),'generated local credential contract')
        require(stat.S_IMODE(Path('/etc/awf/host.env').stat().st_mode)==0o600,'local credentials are not private')
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),package.OfficialRedirects())
        request=urllib.request.Request('http://127.0.0.1:7070/v1/maintenance',headers={'Authorization':'Bearer '+tokens['AWF_HOST_TOKEN']})
        with opener.open(request,timeout=5) as response:
            status=json.loads(response.read(1<<20))
        require(status['build']['version']==self.current_version and status['build']['sourceCommit']==probe.SOURCE and status['maintenance']['phase']=='open','Host identity/maintenance health')
        with opener.open('http://127.0.0.1:3425/',timeout=5) as response:
            magpie=json.loads(response.read(65536))
        require(magpie['name']=='magpie' and magpie['version'].lstrip('v')=='0.1.855','Magpie identity health')
        sockets={}
        for unit,exe in [('awf-host.service','/opt/awf/awf'),('awf-magpie.service','/opt/magpie/magpie')]:
            state=unit_status(unit)
            pid=int(state['MainPID'])
            require(state['ActiveState']=='active' and state['User']=='awf' and state['Group']=='awf' and state['DropInPaths']=='' and
                    state['FragmentPath']=='/etc/systemd/system/'+unit and pid in cgroup_pids(unit) and
                    os.readlink('/proc/'+str(pid)+'/exe')==exe,'fixed native service identity')
            require(Path('/proc/'+str(pid)+'/status').read_text().split('Uid:\t')[1].split()[0]==str(self.ledger['account']['uid']),'non-root service account')
            inode_set=set()
            for member in cgroup_pids(unit):
                for fd in Path('/proc/'+str(member)+'/fd').iterdir():
                    try:
                        link=os.readlink(fd)
                    except FileNotFoundError:
                        continue
                    if link.startswith('socket:['):
                        inode_set.add(link[8:-1])
            sockets[unit]=inode_set
            if unit=='awf-magpie.service':
                rows=probe.mount_records(Path('/proc/'+str(pid)+'/mountinfo').read_text())
                mount=probe.mount_for(rows,'/var/lib/awf/magpie-config/magpie/settings.json')
                require(mount['target']=='/var/lib/awf/magpie-config/magpie/settings.json' and 'ro' in mount['flags'],'real read-only Magpie settings mount')
                require(os.path.samestat(Path('/etc/awf/magpie-settings.json').stat(),Path('/proc/'+str(pid)+'/root/var/lib/awf/magpie-config/magpie/settings.json').stat()),'settings bind inode')
        seen=set()
        for path in ('/proc/net/tcp','/proc/net/tcp6'):
            for line in Path(path).read_text().splitlines()[1:]:
                fields=line.split()
                address,port=fields[1].split(':')
                if fields[3]!='0A' or int(port,16) not in (7070,3425):
                    continue
                unit='awf-host.service' if int(port,16)==7070 else 'awf-magpie.service'
                require(path=='/proc/net/tcp' and address=='0100007F' and fields[9] in sockets[unit],'owned IPv4 loopback listener required')
                seen.add(int(port,16))
        require(seen=={7070,3425},'both owned loopback listeners required')
        config=json.loads(Path('/etc/awf/host.json').read_text())
        require(config['projects']=={} and config['nodes']=={} and config['piAgentDir']=='/var/lib/awf/pi-agent','empty independent service state')
        self.report['healthRounds'].append(dict(round=round_number,ownedLoopbackPorts=[7070,3425],realReadOnlyMount=True,nonRootServiceIdentity=True,emptyProjectsAndNodes=True))

    def trusted_unit(self,unit):
        path='/etc/systemd/system/'+unit
        require(path in self.ledger['paths'] and same(path,self.ledger['paths'][path]),'unit ledger identity changed')
        s=Path(path).lstat()
        require(stat.S_ISREG(s.st_mode) and s.st_uid==0 and stat.S_IMODE(s.st_mode)==0o644 and
                package.digest_file(Path(path))==self.ledger['unitHashes'].get(unit),'literal owned unit changed')
        state=unit_status(unit)
        require(state.get('DropInPaths')=='' and state.get('FragmentPath') in ('',path),'unit override/alias changed')

    def cleanup(self):
        # Cleanup consumes the sealed command-observation ledger. It never
        # adopts new paths/accounts, including directories matched by a glob.
        scope=Path('/sys/fs/cgroup/system.slice')/SCOPE
        if scope.exists():
            require(self.ledger.get('scopeIdentity') and same(scope,self.ledger['scopeIdentity']),'installer scope ownership unknown')
            state=probe.properties(probe.run('/usr/bin/systemctl','show',SCOPE,'--property=Transient,ControlGroup','--no-pager'))
            require(state==dict(Transient='yes',ControlGroup='/system.slice/'+SCOPE),'installer scope identity changed')
            probe.run('/usr/bin/systemctl','stop',SCOPE)
            require(not cgroup_pids(SCOPE),'installer descendant processes remain')
        # Verify all trust boundaries before stopping/deleting any owned item.
        for unit in probe.UNITS:
            path='/etc/systemd/system/'+unit
            if os.path.lexists(path):
                self.trusted_unit(unit)
        for unit in probe.UNITS:
            if os.path.lexists('/etc/systemd/system/'+unit):
                probe.run('/usr/bin/systemctl','stop',unit)
                stopped(unit)
        account=self.ledger['account']
        current_account=None
        if account:
            try:
                current_account=pwd.getpwnam('awf')
            except KeyError:
                pass
            if current_account:
                require(dict(uid=current_account.pw_uid,gid=current_account.pw_gid,home=current_account.pw_dir,shell=current_account.pw_shell)==account and
                        current_account.pw_dir=='/var/lib/awf' and current_account.pw_shell=='/usr/sbin/nologin','account ledger changed')
            for status in Path('/proc').glob('[0-9]*/status'):
                try:
                    ids=[int(x) for x in status.read_text().split('Uid:\t')[1].splitlines()[0].split()]
                except FileNotFoundError:
                    continue
                require(account['uid'] not in ids,'service identity still has processes')
        owners={0:0}
        if account:
            owners[account['uid']]=account['gid']
        paths=self.ledger['paths']
        for path,saved in paths.items():
            if not os.path.lexists(path):
                continue
            require(same(path,saved),'owned path inode/device/type changed')
            if path in LINKS:
                require(Path(path).is_symlink() and os.readlink(path)==LINKS[path],'owned command link changed')
            elif path in UNIT_FILES:
                continue
            else:
                require(path in ROOTS or any(path==row['backup'] for transition in self.ledger.get('transitions',[]) for row in transition['roots']),'cleanup path outside ledger scope')
                safe_tree(path,owners)
        if self.ledger['group']:
            try:
                g=grp.getgrnam('awf')
            except KeyError:
                g=None
            if g:
                require(dict(gid=g.gr_gid,members=g.gr_mem)==self.ledger['group'] and not g.gr_mem,'group ledger changed')
                require(all(u.pw_gid!=g.gr_gid or (account and u.pw_uid==account['uid']) for u in pwd.getpwall()),'group used by another account')
        for path in list(LINKS)+UNIT_FILES:
            if path in paths and os.path.lexists(path):
                Path(path).unlink()
        probe.run('/usr/bin/systemctl','daemon-reload')
        for path in sorted(paths,key=len,reverse=True):
            if path not in LINKS and path not in UNIT_FILES and os.path.lexists(path):
                shutil.rmtree(path)
        if current_account:
            probe.run('/usr/sbin/userdel','awf')
        if self.ledger['group']:
            try:
                grp.getgrnam('awf')
            except KeyError:
                pass  # userdel may remove the private empty group itself.
            else:
                probe.run('/usr/sbin/groupdel','awf')
        require(all(not os.path.lexists(p) for p in ROOTS+list(LINKS)+UNIT_FILES+[row['backup'] for transition in self.ledger.get('transitions',[]) for row in transition['roots']]),'owned cleanup left fixed paths')
        require(capture_existing_runtime()==self.ledger['initialRuntime'],'cleanup changed existing Node/npm/npx')
        # Immutable installer hardcodes these temporary roots. Its own defers
        # should remove them; name/UID alone cannot prove they are ours. Residue
        # is reported as unknown cleanup, never recursively removed by glob.
        for parent,patterns in [('/tmp',('awf-bootstrap-*','awf-linux-install-*')),('/opt',('.awf-install-*','.awf-update-*'))]:
            require(all(p.name in self.ledger['scratchBefore'][parent] for pattern in patterns for p in Path(parent).glob(pattern)),
                    'unverified installer scratch remains; no glob cleanup')
        self.report['cleanup']=dict(passed=True,ledgerOwnedPathsRemoved=len(paths),serviceProcessesGone=True,preinstalledRuntimePreserved=True)


def report_write(path, report):
    # Public output is built exclusively from fixed fields, integer measurements,
    # sanitized stage outcomes and read-only preflight. Never copy raw log bodies.
    require(not path.is_symlink() and path.parent.is_dir(),'report path invalid')
    fd,temp=tempfile.mkstemp(prefix='.awf-native-report-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as out:
            os.fchmod(out.fileno(),0o644)
            json.dump(report,out,sort_keys=True,indent=2)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def previous_report(path, default):
    # Public report availability must never authorize or block owned cleanup.
    try:
        info=path.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022,'untrusted previous report')
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd) as stream:
            payload=json.load(stream)
        require(payload['sourceCommit']==probe.SOURCE and payload['workflowCommit']==os.environ['GITHUB_SHA'],'previous report identity differs')
        allowed={'schema','sourceCommit','version','workflowCommit','stages','healthRounds','acceptancePassed','cleanup',
                 'modelCalls','providerAuthenticationPerformed','piUpdateExecuted','CloudConeAcceptance',
                 'preflight','failure','publicAssetsVerified','preinstalledRuntimePreserved','resources',
                 'parentPreparation','parentRestoration','piUpdate','awfUpdate','businessStatePreserved','rpcCompatibility','publicBootstrap','noOp','mode','awfFailureDiagnostic','aclEvidence',
                 'retainedForDiagnosis','firstAttemptFailure','piPermissionCheck','failureDetails',
                 'piObservation','piDiagnosticObserved','piDiagnosticPassed','channelManifest','defaultEntryAcceptance'}
        default.update({key:value for key,value in payload.items() if key in allowed})
    except Exception:
        default['failure']='previous public report unavailable; cleanup uses private ledger only'
    return default


def install_args(assets):
    bootstrap=assets/('channel-install-linux.sh' if probe.RELEASE==TARGET_VERSION else 'install-linux.sh')
    # No local manifest or archive override: both public downloads execute.
    return ['/usr/bin/systemd-run','--scope','--unit='+SCOPE,
            '-p','MemoryHigh=1G','-p','MemoryMax=2G','-p','MemorySwapMax=256M','-p','TasksMax=256','-p','CPUQuota=200%',
            '/bin/sh',str(bootstrap),'--allow-prerelease']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-release',required=True,choices=('22.04','24.04'))
    parser.add_argument('--report',required=True,type=Path)
    parser.add_argument('--phase',choices=('upgrade','default'))
    parser.add_argument('--cleanup-only',action='store_true')
    parser.add_argument('--diagnostic-only',action='store_true')
    parser.add_argument('--retain-post-pi-failure',action='store_true')
    parser.add_argument('--pi-update-diagnostic',action='store_true')
    parser.add_argument('--acl-full-acceptance',action='store_true')
    parser.add_argument('--default-entry-acceptance',action='store_true')
    args=parser.parse_args()
    probe.ci_guard(os.environ,os.getuid(),os.geteuid())
    require(args.cleanup_only or args.diagnostic_only or args.pi_update_diagnostic or args.acl_full_acceptance or args.default_entry_acceptance,'approved native acceptance mode required')
    if args.default_entry_acceptance:
        require(args.phase in ('upgrade','default') and not any((args.diagnostic_only,args.pi_update_diagnostic,args.acl_full_acceptance,args.retain_post_pi_failure)),'default-entry acceptance requires one exact phase')
    require(not args.acl_full_acceptance or (not args.phase and not args.diagnostic_only and not args.pi_update_diagnostic and not args.retain_post_pi_failure), 'one ACL full upgrade phase only')
    if args.pi_update_diagnostic:
        require(args.phase!='default' and not args.diagnostic_only and not args.retain_post_pi_failure,'Pi diagnostic mode only; no default or retention phase')
    if args.retain_post_pi_failure:
        require(os.environ.get('GITHUB_REF')=='refs/heads/'+probe.POST_PI_BRANCH and args.phase!='default' and not args.cleanup_only and not args.diagnostic_only,
                'retention requires the separately approved post-Pi diagnostic VM')
    if args.phase:
        # Separate fresh processes in one approved VM may run the two phases.
        # The real GitHub branch/commit guard stays unchanged.
        global PINS
        probe.RELEASE=TARGET_VERSION if args.phase=='default' else 'v1.0.2-rc.1'
        package.configure(probe.RELEASE)
        PINS=PINS_BY_VERSION[probe.RELEASE]
    require(not (args.cleanup_only and args.diagnostic_only),'diagnostic and cleanup modes are exclusive')
    report=dict(schema=1,sourceCommit=probe.SOURCE,version=probe.RELEASE,workflowCommit=os.environ['GITHUB_SHA'],
                stages=[],healthRounds=[],acceptancePassed=False,cleanup={'passed':False},
                modelCalls=0,providerAuthenticationPerformed=False,piUpdateExecuted=False,CloudConeAcceptance=False)
    if args.cleanup_only:
        if not CONTROL.exists():
            return 0
        require(CONTROL.is_dir() and not CONTROL.is_symlink() and CONTROL.stat().st_uid==0 and stat.S_IMODE(CONTROL.stat().st_mode)==0o700,'private control identity invalid')
        ledger=json.loads((CONTROL/'ledger.json').read_text())
        require(same(CONTROL,ledger['controlIdentity']),'private control inode changed')
        runner=Acceptance.__new__(Acceptance)
        runner.ledger,runner.report=ledger,report
        previous_report(args.report,report)
        try:
            runner.cleanup()
            report['retainedForDiagnosis']=False
            report_write(args.report,report)
            shutil.rmtree(CONTROL)
            print('AWF native test: owned cleanup completed',flush=True)
            return 0
        except Exception:
            print('AWF native test: cleanup blocked; private ledger retained',flush=True)
            return 1
    report['preflight']=probe.inspect(args.expected_release)
    if args.diagnostic_only:
        report['diagnosticOnly']=True
        report['cleanup']=dict(passed=True,noSystemMutation=True)
        if not report['preflight']['preflightPassed']:
            report['failure']='native prerequisites failed; read-only diagnostics captured'
        report_write(args.report,report)
        print('AWF native test: read-only diagnostics completed; no installation',flush=True)
        return 0 if report['preflight']['preflightPassed'] else 1
    if not report['preflight']['preflightPassed']:
        report['failure']='native prerequisites failed before installation'
        report['cleanup']=dict(passed=True,noSystemMutation=True)
        report_write(args.report,report)
        print('AWF native test: preflight failed; no installation',flush=True)
        return 1
    require(not CONTROL.exists(),'existing private native-test control directory')
    try:
        initial_runtime=capture_existing_runtime()
    except Exception:
        report['failure']='preinstalled runtime baseline unavailable; no native writes'
        report['cleanup']=dict(passed=True,noSystemMutation=True)
        report_write(args.report,report)
        return 1
    # No real namespace/mount test is fabricated: actual units exercise these.
    CONTROL.mkdir(mode=0o700)
    try:
        runner=Acceptance(report,initial_runtime)
        runner.pi_update_diagnostic=args.pi_update_diagnostic
        runner.acl_full_acceptance=args.acl_full_acceptance
        runner.default_entry_acceptance=args.default_entry_acceptance
        runner.diagnostic_report_path=args.report
    except Exception:
        report['failure']='private ledger initialization failed before any native command'
        # A failure may have persisted only ledger metadata. We do not guess
        # ownership or delete a nonempty directory without a completed ledger.
        report['cleanup']=dict(passed=False,reason='private control retained for inspection; no native commands started')
        report_write(args.report,report)
        return 1
    def cancelled(signum, frame):
        raise TestFailure('native test cancelled')
    signal.signal(signal.SIGTERM,cancelled)
    signal.signal(signal.SIGINT,cancelled)
    try:
        assets=runner.download()
        scope=probe.properties(probe.run('/usr/bin/systemctl','show',SCOPE,'--property=LoadState,FragmentPath,DropInPaths','--no-pager'))
        require(scope==dict(LoadState='not-found',FragmentPath='',DropInPaths=''),'existing installer scope')
        require(all(not os.path.lexists(path) for path in probe.FIXED_PATHS),'fresh targets changed before installation')
        runner.command('install',install_args(assets),8*60)
        runner.verify_install()
        runner.command('init',['/usr/local/bin/awf','init','--yes'],60)
        report['mode']='pi-update-diagnostic' if args.pi_update_diagnostic else 'default' if probe.RELEASE==TARGET_VERSION else 'upgrade'
        if args.default_entry_acceptance:
            report['defaultEntryAcceptance']=True
        report['publicBootstrap']=dict(passed=True,localManifestOverride=False,localArchiveOverride=False,source='channel' if probe.RELEASE==TARGET_VERSION else 'release')
        runner.command('start-1',['/usr/local/bin/awf','start'],120)
        runner.health(1)
        if args.pi_update_diagnostic:
            runner.verify_pi_update_diagnostic()
        elif probe.RELEASE==TARGET_VERSION:
            runner.verify_rpc('default')
            runner.verify_default_noop()
        else:
            runner.verify_upgrades(assets,default_entry=args.default_entry_acceptance)
        if args.default_entry_acceptance:
            runner.verify_channel_manifest('after')
        runner.command('stop-final',['/usr/local/bin/awf','stop'],120)
        for unit in probe.UNITS:
            stopped(unit)
        if args.pi_update_diagnostic:report['piDiagnosticPassed']=True
        else:report['acceptancePassed']=True
    except Exception as error:
        # Only our controlled TestFailure strings are public. Upstream exception
        # details, output and HTTP bodies remain private, including credentials.
        report['failure']=str(error) if isinstance(error,TestFailure) else 'native verification exception: '+type(error).__name__
        report['failureDetails']=dict(type=type(error).__name__,lastStage=report['stages'][-1]['name'] if report['stages'] else 'preflight-or-download')
        from urllib.error import HTTPError, URLError
        if isinstance(error,HTTPError): report['failureDetails']['httpStatus']=error.code
        elif isinstance(error,URLError) and isinstance(getattr(error.reason,'errno',None),int): report['failureDetails']['errno']=error.reason.errno
        if args.retain_post_pi_failure and report['failure']=='stage failed: start-after-pi' and report.get('piUpdate',{}).get('passed') is True:
            try:
                runner.retain_failed_start()
            except Exception:
                report['retainedForDiagnosis']=False
    finally:
        if not report.get('retainedForDiagnosis'):
            try:
                runner.cleanup()
            except Exception:
                report['cleanup']=dict(passed=False,reason='owned cleanup blocked; private ledger retained')
        report_write(args.report,report)
        if report['cleanup']['passed']:
            shutil.rmtree(CONTROL)
    print('AWF native test: acceptance '+str(report['acceptancePassed'])+', cleanup '+str(report['cleanup']['passed']),flush=True)
    return 0 if (report.get('piDiagnosticPassed') if args.pi_update_diagnostic else report['acceptancePassed']) and report['cleanup']['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
