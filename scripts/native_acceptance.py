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
import stat
import subprocess
import tarfile
import tempfile
import time
import urllib.request

import package_linux as package
import probe_native_runner as probe

ROOTS = ['/opt/node','/opt/pi-cli','/opt/awf','/opt/magpie','/etc/awf',
         '/var/lib/awf','/var/cache/awf','/var/cache/awf-installer']
LINKS = {'/usr/local/bin/awf':'/opt/awf/awf',
         '/usr/local/bin/pi':'/opt/pi-cli/awf-launcher.mjs',
         '/usr/local/bin/magpie':'/opt/magpie/magpie'}
UNIT_FILES = ['/etc/systemd/system/'+u for u in probe.UNITS]
SCOPE = 'awf-native-ci-install.scope'
CONTROL = Path('/tmp/awf-native-ci-'+os.environ.get('GITHUB_SHA','invalid'))
ENV = {'PATH':'/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C'}
PINS = {
    'awf_v1.0.1-rc.1_linux_amd64.tar.gz': (3449900,'0672f51ec3dd81bcda81970676bcfa6be3ecb0be65586aa8dc11e0bb526f8a7a'),
    'awf-extension_v1.0.1-rc.1.tar.gz': (2006,'7b0fac2b7965c7c6c564aedcd06c9729f36e920d60239f9b2ad8877b3d8a978a'),
    'awf-source_v1.0.1-rc.1.tar.gz': (411428,'209629500b981b0bd7b69ab97d570aef995b359a012a77aa57a5b47adc844a09'),
    'install-linux.sh': (10709,'67db0155da6b5d86ea86d0bff4a7b8f860615aebe88602ea37ad0a1ea34c0b5b'),
    'linux-host-v1.json': (2737,'5ea01d9872a25edfe8c87d7a626ce150f87f163f53764d262a7481ac830c2971'),
    'PROVENANCE.json': (2269,'bac5fcfe6f9e6b6a9373b6b2e8fe282c7577baf56cd382c34c1c508393d5a59d'),
    'SHA256SUMS': (716,'8e911196dfea4ee19de27b1c17175c95f53651e4ea45ab6fb8abb18e1590ecfd'),
    'TEST_ONLY.txt': (339,'ac0a96700dccf4292ff3ffb90638bdf7ba78906515667b975773d8e890de1b29'),
    'THIRD_PARTY_NOTICES.txt': (16007,'f042097d5f0b7cb89fd3997ecc9abb469770d4e15e4dadaaf59f1f0eb143e41a'),
}


class TestFailure(Exception):
    pass


def require(value, message):
    if not value:
        raise TestFailure(message)


def identity(path):
    s=Path(path).lstat()
    return dict(dev=s.st_dev,ino=s.st_ino,type=stat.S_IFMT(s.st_mode))


def same(path, saved):
    return identity(path)==saved


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
        self.ledger=dict(paths={},account=None,group=None,unitHashes={},initialRuntime=initial_runtime)
        self.deadline=time.monotonic()+22*60
        self.ledger['scratchBefore']={parent:sorted(p.name for pattern in patterns for p in Path(parent).glob(pattern))
            for parent,patterns in [('/tmp',('awf-bootstrap-*','awf-linux-install-*')),('/opt',('.awf-install-*',))]}
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

    def command(self, name, args, seconds, capture=False):
        start=time.monotonic()
        require(start+seconds<self.deadline,'overall native test deadline')
        print('AWF native test: '+name+' started',flush=True)
        log=CONTROL/(name+'.log')
        with log.open('xb') as out:
            os.chmod(log,0o600)
            process=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=out,stderr=out,env=ENV,start_new_session=True)
            try:
                while process.poll() is None:
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
                if process.poll() is None:
                    os.killpg(process.pid,signal.SIGTERM)
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid,signal.SIGKILL)
                        process.wait(timeout=8)
                self.observe()
        self.report['stages'].append(dict(name=name,exitCode=process.returncode,elapsedSeconds=round(time.monotonic()-start,2)))
        print('AWF native test: '+name+' exit '+str(process.returncode),flush=True)
        require(process.returncode==0,'stage failed: '+name)
        return log.read_bytes() if capture else None

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
        package.verify(downloads,'ced23b8baa3a5096caf64daa3396c648d936ab3d')
        self.ledger['unitHashes']={u:hashlib.sha256(text.encode()).hexdigest()
                                  for u,text in source_units(downloads/package.NAMES[2]).items()}
        self.save()
        self.report['publicAssetsVerified']=len(PINS)
        return downloads

    def verify_install(self):
        require(json.loads(self.command('build-identity',['/opt/awf/awf','linux-build-identity'],20,True))==
                dict(schema=1,version=probe.RELEASE,sourceCommit=probe.SOURCE,os='linux',arch='amd64',hostProtocol='v1'),'installed Host identity differs')
        require(self.command('version',['/usr/local/bin/awf','version'],20,True).decode().strip()==probe.RELEASE,'AWF version differs')
        require(self.command('pi-version',['/usr/local/bin/pi','--version'],20,True).decode().strip()=='1.0.2','Pi version differs')
        require(self.command('node-version',['/opt/node/bin/node','--version'],20,True).decode().strip()=='v22.19.0','Node version differs')
        require(capture_existing_runtime()==self.ledger['initialRuntime'],'preinstalled Node/npm/npx changed')
        for path,target in LINKS.items():
            require(Path(path).is_symlink() and os.readlink(path)==target,'installed command link differs')
        require(not os.path.lexists('/root/.pi/agent'),'ordinary root Pi agent directory modified')
        self.report['preinstalledRuntimePreserved']=True

    def health(self, round_number):
        tokens=probe.properties(Path('/etc/awf/host.env').read_text())
        require(set(tokens)=={'AWF_HOST_TOKEN','AWF_EXTENSION_TOKEN'} and len(set(tokens.values()))==2 and
                all(re.fullmatch('[0-9a-f]{64}',v) for v in tokens.values()),'generated local credential contract')
        require(stat.S_IMODE(Path('/etc/awf/host.env').stat().st_mode)==0o600,'local credentials are not private')
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),package.OfficialRedirects())
        request=urllib.request.Request('http://127.0.0.1:7070/v1/maintenance',headers={'Authorization':'Bearer '+tokens['AWF_HOST_TOKEN']})
        with opener.open(request,timeout=5) as response:
            status=json.loads(response.read(1<<20))
        require(status['build']['version']==probe.RELEASE and status['build']['sourceCommit']==probe.SOURCE and status['maintenance']['phase']=='open','Host identity/maintenance health')
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
                require(path in ROOTS,'cleanup path outside ledger scope')
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
        require(all(not os.path.lexists(p) for p in ROOTS+list(LINKS)+UNIT_FILES),'owned cleanup left fixed paths')
        require(capture_existing_runtime()==self.ledger['initialRuntime'],'cleanup changed existing Node/npm/npx')
        # Immutable installer hardcodes these temporary roots. Its own defers
        # should remove them; name/UID alone cannot prove they are ours. Residue
        # is reported as unknown cleanup, never recursively removed by glob.
        for parent,patterns in [('/tmp',('awf-bootstrap-*','awf-linux-install-*')),('/opt',('.awf-install-*',))]:
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
                 'parentPreparation','parentRestoration'}
        default.update({key:value for key,value in payload.items() if key in allowed})
    except Exception:
        default['failure']='previous public report unavailable; cleanup uses private ledger only'
    return default


def install_args(assets):
    return ['/usr/bin/systemd-run','--scope','--unit='+SCOPE,
            '-p','MemoryHigh=1G','-p','MemoryMax=2G','-p','MemorySwapMax=256M','-p','TasksMax=256','-p','CPUQuota=200%',
            '/bin/sh',str(assets/'install-linux.sh'),
            '--manifest',str(assets/'linux-host-v1.json'),
            '--archive',str(assets/package.NAMES[0]),'--allow-prerelease']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-release',required=True,choices=('22.04','24.04'))
    parser.add_argument('--report',required=True,type=Path)
    parser.add_argument('--cleanup-only',action='store_true')
    parser.add_argument('--diagnostic-only',action='store_true')
    args=parser.parse_args()
    probe.ci_guard(os.environ,os.getuid(),os.geteuid())
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
        for i in (1,2):
            runner.command('start-'+str(i),['/usr/local/bin/awf','start'],120)
            runner.health(i)
            runner.command('stop-'+str(i),['/usr/local/bin/awf','stop'],120)
            for unit in probe.UNITS:
                stopped(unit)
        report['acceptancePassed']=True
    except Exception as error:
        # Only our controlled TestFailure strings are public. Upstream exception
        # details, output and HTTP bodies remain private, including credentials.
        report['failure']=str(error) if isinstance(error,TestFailure) else 'native verification exception: '+type(error).__name__
    finally:
        try:
            runner.cleanup()
        except Exception:
            report['cleanup']=dict(passed=False,reason='owned cleanup blocked; private ledger retained')
        report_write(args.report,report)
        if report['cleanup']['passed']:
            shutil.rmtree(CONTROL)
    print('AWF native test: acceptance '+str(report['acceptancePassed'])+', cleanup '+str(report['cleanup']['passed']),flush=True)
    return 0 if report['acceptancePassed'] and report['cleanup']['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
