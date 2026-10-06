"""Fixed, bounded Pi-update observations for the one approved diagnostic VM."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat

MAX_OUTPUT = 1 << 20
MAX_TRACE = 64 << 10
PACKAGE = '/opt/pi-cli/lib/node_modules/@earendil-works/pi-coding-agent'
OBJECTS = (PACKAGE, PACKAGE+'/package.json', '/opt/pi-cli/awf-launcher.mjs')


def safe_path(value):
    if isinstance(value,str) and 0<len(value)<=4096 and re.fullmatch(r'[A-Za-z0-9_@./ +\-]+',value) and not re.search(r'(^|/)(\.ssh|auth\.json|credentials|tokens?)(/|$)',value,re.I):
        return value
    raw=str(value).encode('utf-8',errors='replace')
    return dict(redacted=True,reason='path_not_allowlisted',sha256=hashlib.sha256(raw).hexdigest())


def read_private(path,limit):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    with os.fdopen(fd,'rb') as stream:
        s=os.fstat(stream.fileno())
        if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.geteuid() or stat.S_IMODE(s.st_mode)!=0o600:
            raise ValueError('private_file_metadata')
        return stream.read(limit+1)


def object_metadata(name):
    row=dict(path=safe_path(name))
    try:
        p=Path(name);s=p.lstat()
        kind='symlink' if stat.S_ISLNK(s.st_mode) else 'directory' if stat.S_ISDIR(s.st_mode) else 'file' if stat.S_ISREG(s.st_mode) else 'other'
        row.update(objectType=kind,mode=format(stat.S_IMODE(s.st_mode),'04o'),uid=s.st_uid,gid=s.st_gid,dev=s.st_dev,ino=s.st_ino,readlink=None)
        if kind=='symlink':
            target=os.readlink(p)
            row.update(readlink=safe_path(target),linkRelative=not os.path.isabs(target))
            lexical=os.path.normpath(os.path.join(str(p.parent),target))
            row['linkInsidePrefix']=lexical.startswith('/opt/pi-cli/')
        try:
            real=str(p.resolve(strict=True))
            row.update(realpath=safe_path(real),realpathInsidePrefix=real.startswith('/opt/pi-cli/'))
        except (OSError,RuntimeError) as error:
            row.update(realpath=None,realpathUnavailable=dict(type=type(error).__name__,errno=getattr(error,'errno',None)))
    except OSError as error:
        row['metadataUnavailable']=dict(type=type(error).__name__,errno=error.errno)
    return row


def update_output(path):
    row={}
    try:
        data=read_private(path,MAX_OUTPUT)
        if len(data)>MAX_OUTPUT:
            return dict(outputUnavailable='output_limit')
        masks=re.findall(rb'AWF_PI_MASK_(BEFORE|AFTER)=([0-7]{4})',data)
        if len(masks)==2:row['shellMaskMarkers']=[dict(point=p.decode(),umask=m.decode()) for p,m in masks]
        else:row['shellMaskMarkersUnavailable']='missing_or_duplicate_markers'
        version=re.findall(rb'^Updated pi from ([0-9]{1,12}\.[0-9]{1,12}\.[0-9]{1,12}) to ([0-9]{1,12}\.[0-9]{1,12}\.[0-9]{1,12})\r?$',data,re.MULTILINE)
        if len(version)==1:
            row.update(updaterInitialVersion=version[0][0].decode(),updaterReportedVersion=version[0][1].decode())
        else:
            row['updaterVersionUnavailable']='completion_marker_unavailable'
    except (OSError,ValueError) as error:
        row['outputUnavailable']=dict(type=type(error).__name__,errno=getattr(error,'errno',None))
    return row


def trusted_package_version():
    # Read only after nofollow physical-parent/regular-file checks; no CLI probe.
    try:
        p=Path(PACKAGE+'/package.json')
        for parent in p.parents:
            if str(parent)=='.':continue
            s=parent.lstat()
            if not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or s.st_mode&0o6022:
                return dict(installedVersionUnavailable='untrusted_physical_parent')
        s=p.lstat()
        if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or s.st_mode&0o6022:
            return dict(installedVersionUnavailable='untrusted_package_file')
        fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
        with os.fdopen(fd,'rb') as stream:
            current=os.fstat(stream.fileno())
            if (current.st_dev,current.st_ino)!=(s.st_dev,s.st_ino):
                return dict(installedVersionUnavailable='package_file_replaced')
            data=stream.read(MAX_OUTPUT+1)
        if len(data)>MAX_OUTPUT:return dict(installedVersionUnavailable='package_size_limit')
        v=json.loads(data)
        if not isinstance(v,dict):return dict(installedVersionUnavailable='package_identity_invalid')
        if v.get('name')=='@earendil-works/pi-coding-agent' and isinstance(v.get('version'),str) and re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',v['version']):
            return dict(installedPackageVersion=v['version'])
        return dict(installedVersionUnavailable='package_identity_invalid')
    except (OSError,ValueError,TypeError,RuntimeError) as error:
        return dict(installedVersionUnavailable=type(error).__name__)


def safe_arg(value,roots):
    if isinstance(value,str):
        if value in {'npm','root','-g','install','--prefix','--ignore-scripts','--min-release-age=0','update','--version'}:
            return value
        if re.fullmatch(r'@earendil-works/pi-coding-agent@[0-9]{1,12}\.[0-9]{1,12}\.[0-9]{1,12}',value):return value
        if any(value==p or value.startswith(p+'/') for p in roots):return safe_path(value)
        if value.startswith('file:') and any(value[5:]==p or value[5:].startswith(p+'/') for p in roots):
            clean=safe_path(value[5:])
            if isinstance(clean,str):return 'file:'+clean
        if len(value)<=4096 and re.fullmatch(r'(?:@earendil-works/pi-coding-agent@)?https://registry\.npmjs\.org/@earendil-works/pi-coding-agent/-/pi-coding-agent-[0-9a-zA-Z.+\-]+\.tgz',value):return value
    if isinstance(value,dict) and set(value)=={'redacted','sha256'} and value['redacted'] is True and re.fullmatch('[0-9a-f]{64}',str(value['sha256'])):return value
    return dict(redacted=True,sha256=hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest())


def load_trace(path,cwd=None):
    try:
        data=read_private(path,MAX_TRACE)
        if len(data)>MAX_TRACE:return dict(traceUnavailable='trace_limit')
        rows=[json.loads(line) for line in data.splitlines()]
        if len(rows)>32:return dict(traceUnavailable='trace_limit')
        roots=('/opt/node','/opt/pi-cli',str(Path(path).parent),str(cwd or Path.cwd()))
        base={'pid','uid','gid','umask','kind'}
        fields={'node-start':{'executable','argv','cwd'},'npm-spawn':{'method','command','argv','cwd','sourceType','source'},'npm-resolve':{'source','sourceType','destination','cwd'}}
        clean=[]
        for r in rows:
            if not isinstance(r,dict) or not isinstance(r.get('kind'),str) or r['kind'] not in fields or set(r)!=base|fields[r['kind']]:return dict(traceUnavailable='trace_schema')
            if not all(isinstance(r[n],int) and not isinstance(r[n],bool) and 0<=r[n]<=2147483647 for n in ('pid','uid','gid')) or r['pid']==0 or not re.fullmatch('[0-7]{4}',str(r['umask'])):return dict(traceUnavailable='trace_schema')
            row={n:r[n] for n in base}
            row['cwd']=safe_arg(r['cwd'],roots)
            if 'argv' in r:
                if not isinstance(r['argv'],list) or len(r['argv'])>16:return dict(traceUnavailable='trace_schema')
                row['argv']=[safe_arg(v,roots) for v in r['argv']]
            for n in ('executable','source','destination'):
                if n in r:row[n]=safe_arg(r[n],roots)
            if 'sourceType' in r:
                if r['sourceType'] not in ('registry-package','remote-tarball','directory','file-directory','other'):return dict(traceUnavailable='trace_schema')
                row['sourceType']=r['sourceType']
            if r['kind']=='npm-spawn':
                if r['command']!='npm' or r['method'] not in ('spawn','spawnSync'):return dict(traceUnavailable='trace_schema')
                row.update(command='npm',method=r['method'])
            clean.append(row)
        result=dict(processObservations=clean)
        installs=[r for r in clean if r['kind']=='npm-spawn' and 'install' in r['argv']]
        if len(installs)==1 and isinstance(installs[0]['source'],str):
            match=re.fullmatch(r'@earendil-works/pi-coding-agent@([0-9]+\.[0-9]+\.[0-9]+)',installs[0]['source'])
            if match:result['requestedPackageVersion']=match[1]
        return result
    except (OSError,ValueError,TypeError,RecursionError) as error:
        return dict(traceUnavailable=type(error).__name__)


def observer_source(trace,cwd):
    # No UID/umask/fetch/source replacement. Every original call receives the
    # unchanged command, arguments and options. Never records environment/config.
    return 'const tracePath='+json.dumps(str(trace))+';\nconst approvedCwd='+json.dumps(str(cwd))+';\n'+OBSERVER


OBSERVER = r'''
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import cp from 'node:child_process';
import {createRequire,syncBuiltinESMExports} from 'node:module';
const digest=v=>crypto.createHash('sha256').update(String(v)).digest('hex');
const redacted=v=>({redacted:true,sha256:digest(v)});
const safePath=v=>typeof v==='string'&&v.length>0&&v.length<=4096&&/^[A-Za-z0-9_@./ +\-]+$/.test(v)&&!/(^|\/)(\.ssh|auth\.json|credentials|tokens?)(\/|$)/i.test(v)?v:redacted(v);
const tokens=new Set(['npm','root','-g','install','--prefix','--ignore-scripts','--min-release-age=0','update','--version']);
function safeArg(v){
 if(tokens.has(v))return v;
 if(typeof v==='string'&&/^@earendil-works\/pi-coding-agent@[0-9]{1,12}\.[0-9]{1,12}\.[0-9]{1,12}$/.test(v))return v;
 if(typeof v==='string'&&(v==='/opt/pi-cli'||v.startsWith('/opt/pi-cli/')||v.startsWith('/opt/node/')||v===approvedCwd||v.startsWith(approvedCwd+'/')||v.startsWith(path.dirname(tracePath)+'/')))return safePath(v);
 if(typeof v==='string'&&v.startsWith('file:')){const p=v.slice(5);if(p===approvedCwd||p.startsWith(approvedCwd+'/')||p.startsWith(path.dirname(tracePath)+'/')){const clean=safePath(p);if(typeof clean==='string')return 'file:'+clean}}
 if(typeof v==='string'&&/^(?:@earendil-works\/pi-coding-agent@)?https:\/\/registry\.npmjs\.org\/@earendil-works\/pi-coding-agent\/-\/pi-coding-agent-[0-9a-zA-Z.+\-]+\.tgz$/.test(v))return v;
 return redacted(v);
}
function sourceType(v){
 if(typeof v!=='string')return 'other';
 if(v.startsWith('file:'))return 'file-directory';
 if(v.startsWith('/'))return 'directory';
 if(v.includes('https://'))return 'remote-tarball';
 if(/^@earendil-works\/pi-coding-agent@/.test(v))return 'registry-package';
 return 'other';
}
let writes=0;
function emit(row){
 try{
  if(writes++>=32)return;
  const line=JSON.stringify({pid:process.pid,uid:process.getuid(),gid:process.getgid(),umask:process.umask().toString(8).padStart(4,'0'),...row})+'\n';
  const fd=fs.openSync(tracePath,fs.constants.O_WRONLY|fs.constants.O_APPEND|fs.constants.O_NOFOLLOW);
  try{const s=fs.fstatSync(fd);if(s.uid===process.getuid()&&(s.mode&0o777)===0o600&&s.size+Buffer.byteLength(line)<=65536)fs.writeSync(fd,line)}finally{fs.closeSync(fd)}
 }catch{}
}
emit({kind:'node-start',executable:safeArg(process.execPath),argv:process.argv.map(safeArg),cwd:safePath(process.cwd())});
for(const method of ['spawn','spawnSync']){
 const original=cp[method];
 cp[method]=function(command,args,options){
  if(command==='npm')emit({kind:'npm-spawn',method,command,argv:(args||[]).map(safeArg),cwd:safePath(options?.cwd||process.cwd()),sourceType:sourceType(args?.at(-1)),source:safeArg(args?.at(-1))});
  return original.apply(this,arguments);
 };
}
syncBuiltinESMExports();
// Observe npm's actual root-package resolution only, not auth-bearing options.
if(process.argv[1]?.endsWith('/bin/npm')||process.argv[1]?.endsWith('/npm-cli.js')){
 try{
  const require=createRequire(path.join(path.dirname(process.execPath),'../lib/node_modules/npm/package.json'));
  const pacote=require('pacote');const original=pacote.extract;
  pacote.extract=function(spec,destination,options){
   const raw=typeof spec==='string'?spec:spec?.raw;
   if(String(raw).includes('pi-coding-agent'))emit({kind:'npm-resolve',source:safeArg(raw),sourceType:sourceType(raw),destination:safePath(destination),cwd:safePath(options?.where||process.cwd())});
   return original.apply(this,arguments);
  };
 }catch{}
}
'''
