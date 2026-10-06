#!/usr/bin/env python3
"""Build the two reviewed Linux preview releases; never install or publish."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.request

VERSIONS = ('v1.0.2-rc.1', 'v1.0.2-rc.2')
SOURCE_COMMIT = '77735d2a94d1bda3bcd0e979d71fac643709f2f4'
REPOSITORY = 'atongrun/agent-workflow'
TEST_BRANCH = 'awf/linux-acl-native-once-20261006'
GO_VERSION = 'go1.25.14'
BOOTSTRAP_TEMPLATE_SHA256 = '0e295c8458a728c26dfd54dad70b2839e0d5e4431d59d3c3f85b1218fdb3f158'
CHANNEL_STAMP = b"CHANNEL = 'https://raw.githubusercontent.com/atongrun/agent-workflow/awf/linux-v1/distribution/linux-host-v1.json'"


def configure(version):
    # A one-shot packaging process selects exactly one of these new tags.
    if version not in VERSIONS:
        raise ValueError('only the approved new ACL TEST ONLY preview tags are allowed')
    global VERSION, BOOTSTRAP_MANIFEST_URL, BOOTSTRAP_STAMPS, NAMES
    VERSION = version
    BOOTSTRAP_MANIFEST_URL = 'https://github.com/'+REPOSITORY+'/releases/download/'+VERSION+'/linux-host-v1.json'
    BOOTSTRAP_STAMPS = [(CHANNEL_STAMP, ("CHANNEL = '"+BOOTSTRAP_MANIFEST_URL+"'").encode())]
    NAMES = ['awf_'+VERSION+'_linux_amd64.tar.gz', 'awf-extension_'+VERSION+'.tar.gz', 'awf-source_'+VERSION+'.tar.gz', 'install-linux.sh', 'linux-host-v1.json', 'THIRD_PARTY_NOTICES.txt', 'PROVENANCE.json', 'PREVIEW.txt', 'SHA256SUMS']


configure(VERSIONS[0])
GO_ARCHIVE = dict(url='https://go.dev/dl/go1.25.14.linux-amd64.tar.gz', bytes=59909419, sha256='a21ae5633a269bcd7e90cf767e48225633795e99d831742cbf3397064fee7712')
INPUTS = [
    ('node', 'v22.19.0', 'node-v22.19.0-linux-x64.tar.gz', 'https://nodejs.org/dist/v22.19.0/node-v22.19.0-linux-x64.tar.gz', 54907188, 'd36e56998220085782c0ca965f9d51b7726335aed2f5fc7321c6c0ad233aa96d', 'tar.gz'),
    ('pi', '1.0.2', 'package.json', 'https://github.com/earendil-works/pi/releases/download/v1.0.2/pi-coding-agent-install-package.json', 317, '491cb1ec4fba98d9547b037cd9dea48ae0bba651a0a80d67dd1660705b60f1c5', 'json'),
    ('pi', '1.0.2', 'package-lock.json', 'https://github.com/earendil-works/pi/releases/download/v1.0.2/pi-coding-agent-install-package-lock.json', 63566, 'b8e9e6a191bcf1e6e3ff8dafe5c0c9042b48e0087cd6d6816dcaa051222ba680', 'json'),
    ('magpie', '0.1.855', 'magpie-cli-linux-amd64', 'https://github.com/yetone/magpie-releases/releases/download/v0.1.855/magpie-cli-linux-amd64', 31375522, 'f79df4bd90aa81371eff4386740b1fdcb557cf272d395494948c15b9f4f8ff10', 'elf'),
]



def digest_file(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def encode(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def release_bootstrap(template):
    if hashlib.sha256(template).hexdigest()!=BOOTSTRAP_TEMPLATE_SHA256:
        raise ValueError('reviewed bootstrap template differs')
    for old,new in BOOTSTRAP_STAMPS:
        if template.count(old)!=1:
            raise ValueError('bootstrap release stamp differs')
        template=template.replace(old,new)
    return template


def verify_bootstrap(payload):
    for old,new in reversed(BOOTSTRAP_STAMPS):
        if payload.count(new)!=1:
            raise ValueError('bootstrap release binding differs')
        payload=payload.replace(new,old)
    if hashlib.sha256(payload).hexdigest()!=BOOTSTRAP_TEMPLATE_SHA256:
        raise ValueError('bootstrap code differs from reviewed template')


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root)


def archive(path, rows):
    with path.open('xb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w', format=tarfile.USTAR_FORMAT) as tar:
            for name, data, mode in rows:
                entry = tarfile.TarInfo(name)
                entry.size, entry.mode, entry.mtime = len(data), mode, 0
                tar.addfile(entry, io.BytesIO(data))


class OfficialRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        from urllib.parse import urlparse
        old, new = urlparse(request.full_url), urlparse(new_url)
        if old.netloc != 'github.com' or new.scheme != 'https' or new.netloc not in ('release-assets.githubusercontent.com', 'objects.githubusercontent.com') or new.username or new.fragment:
            raise ValueError('official runtime redirect refused')
        return super().redirect_request(request, response, code, message, headers, new_url)


def verify_inputs(cache):
    cache.mkdir(parents=True, exist_ok=True)
    rows = []
    for component, version, name, url, size, expected, form in INPUTS:
        path = cache / (component + '-' + name)
        if not path.exists():
            try:
                opener = urllib.request.build_opener(OfficialRedirects())
                with opener.open(url, timeout=120) as response, path.open('xb') as target:
                    received = 0
                    while chunk := response.read(1 << 20):
                        received += len(chunk)
                        if received > size:
                            raise ValueError('official runtime download exceeded pinned bytes')
                        target.write(chunk)
            except Exception:
                path.unlink(missing_ok=True)
                raise
        if path.is_symlink() or not path.is_file() or path.stat().st_size != size or digest_file(path) != expected:
            raise ValueError('official runtime pin mismatch: ' + component + '/' + name)
        rows.append(dict(component=component, version=version, name=name, url=url, bytes=size, sha256=expected))
    return rows


def safe_snapshot(data, target):
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        seen = set()
        for entry in tar:
            path = PurePosixPath(entry.name.rstrip('/'))
            if not path.parts or path.is_absolute() or '..' in path.parts or str(path) != entry.name.rstrip('/') or str(path) in seen or not (entry.isdir() or entry.isfile()):
                raise ValueError('unexpected source archive entry')
            seen.add(str(path))
            out = target / str(path)
            if entry.isdir():
                out.mkdir(parents=True, exist_ok=True)
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                with out.open('xb') as stream:
                    shutil.copyfileobj(tar.extractfile(entry), stream)
                out.chmod(entry.mode & 0o777)


def build(root, output, go, verified_inputs):
    if output.exists():
        raise ValueError('fresh output directory required; preserve previous assets')
    workflow_commit = git(root, 'rev-parse', 'HEAD').decode().strip()
    if not re.fullmatch('[0-9a-f]{40}', workflow_commit):
        raise ValueError('exact workflow commit required')
    subprocess.run(['git', 'merge-base', '--is-ancestor', SOURCE_COMMIT, workflow_commit], cwd=root, check=True)
    if git(root, 'ls-tree', '-r', '--name-only', SOURCE_COMMIT, '.github/workflows'):
        raise ValueError('reviewed release source must not add workflows')
    go = go.resolve()
    version = subprocess.check_output([str(go), 'version']).decode().strip()
    if version != 'go version ' + GO_VERSION + ' linux/amd64':
        raise ValueError('pinned Linux amd64 Go toolchain required')
    goroot = Path(subprocess.check_output([str(go), 'env', 'GOROOT']).decode().strip())
    output.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='awf-linux-package-') as temporary:
        work = Path(temporary)
        source = work / 'source'
        source.mkdir()
        snapshot = git(root, 'archive', '--format=tar', SOURCE_COMMIT)
        safe_snapshot(snapshot, source)
        env = os.environ.copy()
        env.update(CGO_ENABLED='0', GOOS='linux', GOARCH='amd64', GOAMD64='v1', GOTOOLCHAIN='local', GOEXPERIMENT='', GOFLAGS='')
        flags = '-s -w -X github.com/atongrun/agent-workflow/internal/host.BuildVersion=' + VERSION + ' -X github.com/atongrun/agent-workflow/internal/host.BuildSourceCommit=' + SOURCE_COMMIT
        binaries = []
        for i in range(2):
            binary = work / ('awf-' + str(i))
            subprocess.run([str(go), 'build', '-trimpath', '-buildvcs=false', '-ldflags', flags, '-o', str(binary), './cmd/awf'], cwd=source, env=env, check=True)
            binaries.append(binary)
        if digest_file(binaries[0]) != digest_file(binaries[1]):
            raise ValueError('repeated Host build differed')
        host_sha256 = digest_file(binaries[0])
        identity = dict(schema=1, version=VERSION, sourceCommit=SOURCE_COMMIT, os='linux', arch='amd64', hostProtocol='v1')
        if json.loads(subprocess.check_output([str(binaries[0]), 'linux-build-identity'])) != identity:
            raise ValueError('compiled Host identity differs')
        archive(output / NAMES[0], [('awf', binaries[0].read_bytes(), 0o755), ('build.json', encode(identity), 0o644)])
        extension = dict(schema=1, version=VERSION, sourceCommit=SOURCE_COMMIT, extensionProtocol=1, piRPCVersion='1.0.2')
        archive(output / NAMES[1], [('awf.ts', (source / 'extensions/awf.ts').read_bytes(), 0o644), ('extension.json', encode(extension), 0o644)])
        with (output / NAMES[2]).open('xb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as stream:
            stream.write(snapshot)
        (output / 'install-linux.sh').write_bytes(release_bootstrap((source / 'scripts/install-linux.sh').read_bytes()))
    notices = 'THIRD-PARTY NOTICES\n\nApplies only to identified Go components linked into the AWF Host.\nNo license is selected or granted for AWF itself.\nNode/npm, Pi and Magpie are not redistributed in these release assets; the installer downloads their pinned official inputs.\n\n'
    for label, path in [('Go ' + GO_VERSION + ' LICENSE', goroot / 'LICENSE'), ('Go PATENTS', goroot / 'PATENTS')] + [(name + '/' + leaf, goroot / 'src/vendor/golang.org/x' / name / leaf) for name in ('crypto', 'net', 'sys', 'text') for leaf in ('LICENSE', 'PATENTS')] + [('fiat-crypto README', goroot / 'src/crypto/internal/fips140/nistec/fiat/README')]:
        notices += '\n===== ' + label + ' =====\n' + path.read_text() + '\n'
    (output / 'THIRD_PARTY_NOTICES.txt').write_text(notices)
    components = []
    for component in ('node', 'pi', 'awf-host', 'awf-extension', 'magpie'):
        rows = [dict(name=n, url=u, bytes=s, sha256=h, format=f) for c,v,n,u,s,h,f in INPUTS if c == component]
        version = next((v for c,v,*_ in INPUTS if c == component), VERSION)
        if component in ('awf-host', 'awf-extension'):
            name = NAMES[0 if component == 'awf-host' else 1]
            rows = [dict(name=name, url='https://github.com/' + REPOSITORY + '/releases/download/' + VERSION + '/' + name, bytes=(output/name).stat().st_size, sha256=digest_file(output/name), format='tar.gz')]
        components.append(dict(id=component, version=version, artifacts=rows))
    manifest = dict(schema=1, channel='linux-host-v1', version=VERSION, sourceCommit=SOURCE_COMMIT, installerProtocol=1, hostProtocol='v1', extensionProtocol=1, piRPCVersion='1.0.2', os='linux', arch='amd64', libc='glibc', components=components)
    (output / 'linux-host-v1.json').write_bytes(encode(manifest))
    provenance = dict(schema=1, kind='awf-linux-preview-release', version=VERSION, repository=REPOSITORY, sourceCommit=SOURCE_COMMIT, sourceTree=git(root, 'rev-parse', SOURCE_COMMIT+'^{tree}').decode().strip(), workflowCommit=workflow_commit, goVersion=GO_VERSION, goArchive=GO_ARCHIVE, bootstrapTemplateSHA256=BOOTSTRAP_TEMPLATE_SHA256, bootstrapManifestURL=BOOTSTRAP_MANIFEST_URL, hostBinarySHA256=host_sha256, repeatedHostBuildIdentical=True, upstreamInputsVerified=verified_inputs, nativeAcceptance=False, publicBootstrapAcceptance=False, privateKitReused=False)
    (output / 'PROVENANCE.json').write_bytes(encode(provenance))
    (output / 'PREVIEW.txt').write_text('Linux amd64 preview. Native acceptance for this release is not yet verified at packaging time.\nSource: '+SOURCE_COMMIT+'\nNo private kit, production credentials or model calls. Linux channel promotion requires separate native upgrade acceptance. Windows RC9 is unchanged.\n')
    (output / 'SHA256SUMS').write_text(''.join(digest_file(output/n)+'  '+n+'\n' for n in sorted(NAMES) if n!='SHA256SUMS'))
    return manifest


def verify(output, workflow_commit=None):
    if set(p.name for p in output.iterdir()) != set(NAMES):
        raise ValueError('release asset boundary differs')
    for name in NAMES:
        p = output / name
        if p.is_symlink() or not stat.S_ISREG(p.stat().st_mode) or not 0 < p.stat().st_size < 256 << 20:
            raise ValueError('unexpected release asset type/size')
    sums = {}
    for line in (output/'SHA256SUMS').read_text().splitlines():
        h,n = line.split('  ',1)
        if n in sums or n not in NAMES or n=='SHA256SUMS' or not re.fullmatch('[0-9a-f]{64}',h):
            raise ValueError('invalid checksum inventory')
        sums[n] = h
    if set(sums) != set(NAMES)-{'SHA256SUMS'} or any(digest_file(output/n)!=h for n,h in sums.items()):
        raise ValueError('release checksum mismatch')
    provenance = json.loads((output/'PROVENANCE.json').read_bytes())
    if provenance['sourceCommit']!=SOURCE_COMMIT or provenance['version']!=VERSION or provenance['repository']!=REPOSITORY or provenance['goVersion']!=GO_VERSION or provenance['goArchive']!=GO_ARCHIVE or provenance['privateKitReused'] is not False or provenance['nativeAcceptance'] is not False or not provenance['repeatedHostBuildIdentical'] or (workflow_commit and provenance['workflowCommit']!=workflow_commit):
        raise ValueError('release provenance mismatch')
    if provenance.get('bootstrapTemplateSHA256')!=BOOTSTRAP_TEMPLATE_SHA256 or provenance.get('bootstrapManifestURL')!=BOOTSTRAP_MANIFEST_URL:
        raise ValueError('bootstrap provenance differs')
    verify_bootstrap((output/'install-linux.sh').read_bytes())
    manifest = json.loads((output/'linux-host-v1.json').read_bytes())
    identity=dict(schema=1,channel='linux-host-v1',version=VERSION,sourceCommit=SOURCE_COMMIT,installerProtocol=1,hostProtocol='v1',extensionProtocol=1,piRPCVersion='1.0.2',os='linux',arch='amd64',libc='glibc')
    if {k:v for k,v in manifest.items() if k!='components'}!=identity:
        raise ValueError('manifest release identity differs')
    if {c['id'] for c in manifest['components']} != {'node','pi','awf-host','awf-extension','magpie'} or len(manifest['components'])!=5:
        raise ValueError('manifest component boundary differs')
    for component in manifest['components']:
        if component['id'] not in ('awf-host','awf-extension'):
            expected=[dict(name=n,url=u,bytes=s,sha256=h,format=f) for c,v,n,u,s,h,f in INPUTS if c==component['id']]
            if component['artifacts']!=expected or component['version']!=next(v for c,v,*_ in INPUTS if c==component['id']):
                raise ValueError('manifest official source pins differ')
        for artifact in component['artifacts']:
            if component['id'] in ('awf-host','awf-extension') and ((output/artifact['name']).stat().st_size!=artifact['bytes'] or digest_file(output/artifact['name'])!=artifact['sha256']):
                raise ValueError('manifest payload pin differs')
        if component['id'] in ('awf-host','awf-extension'):
            name=NAMES[0 if component['id']=='awf-host' else 1]
            expected=dict(id=component['id'],version=VERSION,artifacts=[dict(name=name,url='https://github.com/'+REPOSITORY+'/releases/download/'+VERSION+'/'+name,bytes=(output/name).stat().st_size,sha256=digest_file(output/name),format='tar.gz')])
            if component!=expected:
                raise ValueError('manifest owned asset source differs')
    for name,wanted in [(NAMES[0],{'awf','build.json'}),(NAMES[1],{'awf.ts','extension.json'})]:
        with tarfile.open(output/name,'r:gz') as tar:
            entries=tar.getmembers()
            if len(entries)!=2 or {e.name for e in entries}!=wanted or any(not e.isfile() for e in entries):
                raise ValueError('release archive topology differs')
            metadata=json.load(tar.extractfile('build.json' if 'awf' in wanted else 'extension.json'))
            expected=dict(schema=1,version=VERSION,sourceCommit=SOURCE_COMMIT,os='linux',arch='amd64',hostProtocol='v1') if 'awf' in wanted else dict(schema=1,version=VERSION,sourceCommit=SOURCE_COMMIT,extensionProtocol=1,piRPCVersion='1.0.2')
            if metadata!=expected:
                raise ValueError('archived release identity differs')
            if 'awf' in wanted and hashlib.sha256(tar.extractfile('awf').read()).hexdigest()!=provenance['hostBinarySHA256']:
                raise ValueError('Host binary provenance differs')
    return provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True, choices=VERSIONS)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--go', default=shutil.which('go'), type=Path)
    parser.add_argument('--upstream-cache', type=Path)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    configure(args.version)
    if args.verify:
        verify(args.output)
    else:
        rows = verify_inputs(args.upstream_cache) if args.upstream_cache else []
        build(Path(__file__).resolve().parent.parent, args.output, args.go, rows)
        verify(args.output)
    print(json.dumps(dict(version=VERSION, sourceCommit=SOURCE_COMMIT, assets=NAMES, nativeAcceptance=False)))


if __name__ == '__main__':
    main()
