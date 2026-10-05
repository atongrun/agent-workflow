#!/bin/sh
# Local candidate. The default Linux channel URL is intentionally unpublished.
# Shell/Python acquire the verified Go executable; Go owns all machine writes.
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
command -v python3 >/dev/null 2>&1 || { echo 'AWF bootstrap requires python3' >&2; exit 1; }
exec python3 - "$@" <<'AWF_BOOTSTRAP_PY'
import argparse
import hashlib
import gzip
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request

CHANNEL = 'https://raw.githubusercontent.com/atongrun/agent-workflow/awf/go-v1/distribution/linux-host-v1.json'

def progress(stage, state):
    print('AWF bootstrap ' + stage + ': ' + state, file=sys.stderr, flush=True)

class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urllib.parse.urlparse(req.full_url), urllib.parse.urlparse(newurl)
        if old.netloc != 'github.com' or new.scheme != 'https' or new.netloc not in ('release-assets.githubusercontent.com', 'objects.githubusercontent.com') or new.fragment:
            raise ValueError('bootstrap redirect refused')
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def download(url, target, limit, digest=None, expected=None):
    received = 0
    checksum = hashlib.sha256()
    opener = urllib.request.build_opener(Redirects())
    progress('download', 'started')
    with opener.open(url, timeout=120) as response, target.open('xb') as output:
        total = response.headers.get('Content-Length')
        total = int(total) if total and total.isdigit() else None
        while True:
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            received += len(chunk)
            if received > limit:
                raise ValueError('bootstrap download size limit')
            output.write(chunk)
            checksum.update(chunk)
            detail = str(received) + ' bytes'
            if total:
                detail += '/' + str(total) + ' (' + format(received * 100 / total, '.1f') + '%)'
            else:
                detail += ' (total unknown)'
            progress('download', detail)
    if expected is not None and received != expected:
        raise ValueError('bootstrap download length mismatch')
    if digest is not None and checksum.hexdigest() != digest:
        raise ValueError('bootstrap archive SHA256 mismatch')
    progress('download', 'completed')

def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate bootstrap metadata key')
        result[key] = value
    return result

def select_host(raw):
    if len(raw) > 64 * 1024:
        raise ValueError('bootstrap manifest size limit')
    manifest = json.loads(raw, object_pairs_hook=unique)
    version = manifest['version']
    if manifest['channel'] != 'linux-host-v1' or manifest['schema'] != 1 or manifest['installerProtocol'] != 1 or manifest['os'] != 'linux' or manifest['arch'] != 'amd64' or manifest['libc'] != 'glibc' or not re.fullmatch(r'v1\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-rc\.(0|[1-9][0-9]*))?', version) or not re.fullmatch('[0-9a-f]{40}', manifest['sourceCommit']):
        raise ValueError('bootstrap Linux manifest identity')
    hosts = [c for c in manifest['components'] if c['id'] == 'awf-host']
    if len(hosts) != 1 or hosts[0]['version'] != version or len(hosts[0]['artifacts']) != 1:
        raise ValueError('bootstrap Host selection')
    artifact = hosts[0]['artifacts'][0]
    name = 'awf_' + version + '_linux_amd64.tar.gz'
    if artifact['name'] != name or artifact['format'] != 'tar.gz' or artifact['url'] != 'https://github.com/atongrun/agent-workflow/releases/download/' + version + '/' + name or not re.fullmatch('[0-9a-f]{64}', artifact['sha256']) or type(artifact['bytes']) is not int or not 0 < artifact['bytes'] <= 256 * 1024 * 1024:
        raise ValueError('bootstrap Host artifact source/hash/length')
    return manifest, artifact

def extract_host(archive, directory, manifest):
    progress('extract', 'started')
    found = {}
    expanded = 0
    with gzip.open(archive, 'rb') as stream:
        def read(size):
            nonlocal expanded
            data = stream.read(size)
            expanded += len(data)
            if expanded > 512 * 1024 * 1024:
                raise ValueError('bootstrap expanded archive limit')
            return data
        while True:
            header = read(512)
            if header == bytes(512):
                if read(512) != bytes(512):
                    raise ValueError('bootstrap tar footer')
                while True:
                    padding = read(32 * 1024)
                    if not padding:
                        break
                    if any(padding):
                        raise ValueError('bootstrap hidden trailing archive payload')
                break
            # Parse fixed headers only; extended/PAX/sparse records are never
            # handed to tarfile's automatic metadata reader or path extractor.
            entry = tarfile.TarInfo.frombuf(header, 'utf-8', 'strict')
            if entry.name not in ('awf', 'build.json') or entry.name in found or entry.type not in (tarfile.REGTYPE, tarfile.AREGTYPE) or entry.mode & 0o7000 or not 0 < entry.size <= 256 * 1024 * 1024:
                raise ValueError('bootstrap archive topology')
            if entry.name == 'build.json' and entry.size > 64 * 1024:
                raise ValueError('bootstrap build metadata bound')
            target = directory / entry.name
            with target.open('xb') as output:
                remaining = entry.size
                while remaining:
                    data = read(min(remaining, 256 * 1024))
                    if not data:
                        raise ValueError('bootstrap truncated payload')
                    output.write(data)
                    remaining -= len(data)
            padding = read((-entry.size) % 512)
            if len(padding) != (-entry.size) % 512 or any(padding):
                raise ValueError('bootstrap tar payload padding')
            found[entry.name] = target
    if set(found) != {'awf', 'build.json'}:
        raise ValueError('bootstrap archive missing identity/executable')
    identity = json.loads(found['build.json'].read_bytes(), object_pairs_hook=unique)
    expected = {'schema': 1, 'version': manifest['version'], 'sourceCommit': manifest['sourceCommit'], 'os': 'linux', 'arch': 'amd64', 'hostProtocol': 'v1'}
    if identity != expected:
        raise ValueError('bootstrap archive build identity mismatch')
    with found['awf'].open('rb') as binary:
        header = binary.read(20)
    if len(header) != 20 or header[:6] != b'\x7fELF\x02\x01' or header[18:20] != b'\x3e\x00':
        raise ValueError('bootstrap executable is not Linux amd64 ELF')
    found['awf'].chmod(0o700)
    progress('extract', 'completed')
    return found['awf']

def main():
    parser = argparse.ArgumentParser(description='AWF Linux bootstrap local candidate; default channel is unpublished')
    parser.add_argument('--manifest', help='explicit local reviewed Linux manifest')
    parser.add_argument('--archive', help='explicit local archive verified against that manifest')
    parser.add_argument('--allow-prerelease', action='store_true')
    options = parser.parse_args()
    if options.archive and not options.manifest:
        raise ValueError('local archive requires an explicit manifest')
    if os.geteuid() != 0 or platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise ValueError('bootstrap requires root on Linux amd64')
    release = dict(line.strip().split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    if release.get('ID', '').strip('"') != 'ubuntu' or release.get('VERSION_ID', '').strip('"') not in ('22.04', '24.04') or not Path('/run/systemd/system').is_dir() or not Path('/lib64/ld-linux-x86-64.so.2').is_file():
        raise ValueError('bootstrap requires Ubuntu 22.04/24.04 glibc systemd')
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix='awf-bootstrap-', dir='/tmp') as work:
        directory = Path(work)
        local_manifest = directory / 'manifest.json'
        if options.manifest:
            if Path(options.manifest).stat().st_size > 64 * 1024:
                raise ValueError('local manifest size limit')
            raw = Path(options.manifest).read_bytes()
            local_manifest.write_bytes(raw)
        else:
            download(CHANNEL, local_manifest, 64 * 1024)
            raw = local_manifest.read_bytes()
        manifest, artifact = select_host(raw)
        if '-rc.' in manifest['version'] and not options.allow_prerelease:
            raise ValueError('Linux prerelease requires --allow-prerelease')
        archive = directory / 'host.tar.gz'
        if options.archive:
            if Path(options.archive).stat().st_size != artifact['bytes']:
                raise ValueError('local archive length mismatch')
            shutil.copyfile(options.archive, archive)
            if hashlib.sha256(archive.read_bytes()).hexdigest() != artifact['sha256']:
                raise ValueError('local archive SHA256 mismatch')
        else:
            download(artifact['url'], archive, artifact['bytes'], artifact['sha256'], artifact['bytes'])
        executable = extract_host(archive, directory, manifest)
        protocol = subprocess.check_output([str(executable), 'linux-install-protocol'], timeout=10)
        identity = json.loads(subprocess.check_output([str(executable), 'linux-build-identity'], timeout=10), object_pairs_hook=unique)
        if protocol.strip() != b'1' or identity != json.loads((directory / 'build.json').read_bytes()):
            raise ValueError('bootstrap executable protocol/build mismatch')
        command = [str(executable), 'install', '--manifest', str(local_manifest), '--yes']
        if options.allow_prerelease:
            command.append('--allow-prerelease')
        progress('Go-install', 'started')
        subprocess.run(command, check=True)
        progress('Go-install', 'completed')

if __name__ == '__main__':
    try:
        main()
    except Exception:
        progress('failed', 'verified bootstrap/install did not complete; inspect reported Go stages or unavailable unpublished channel')
        sys.exit(1)
AWF_BOOTSTRAP_PY
