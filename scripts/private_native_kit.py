#!/usr/bin/env python3
"""Package/extract an explicitly approved private, unpublished native test kit.

No download, remote transfer, system installation or service activation occurs.
The separate Go test runner retains real machine guards when install is explicit.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tarfile
import tempfile
import zipfile

MAX_BYTES = 512 << 20
MAX_ENTRIES = 32768
VERSION = 'v1.999.999-rc.0'  # Private build identity, never a published release.
PINS = {
    'node-v22.19.0-linux-x64.tar.gz': (54907188, 'd36e56998220085782c0ca965f9d51b7726335aed2f5fc7321c6c0ad233aa96d'),
    'pi-official-package.json': (317, '491cb1ec4fba98d9547b037cd9dea48ae0bba651a0a80d67dd1660705b60f1c5'),
    'pi-official-package-lock.json': (63566, 'b8e9e6a191bcf1e6e3ff8dafe5c0c9042b48e0087cd6d6816dcaa051222ba680'),
    'magpie-cli-linux-amd64': (31375522, 'f79df4bd90aa81371eff4386740b1fdcb557cf272d395494948c15b9f4f8ff10'),
}


def sha256_stream(stream):
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1 << 20), b''):
        digest.update(chunk)
    return digest.hexdigest()


def sha256_file(path):
    with path.open('rb') as stream:
        return sha256_stream(stream)


def encode(value):
    return json.dumps(value, separators=(',', ':'), ensure_ascii=False).encode()


def archive(path, rows):
    with tarfile.open(path, 'w:gz', format=tarfile.USTAR_FORMAT) as stream:
        for name, payload, mode in rows:
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode = len(payload), mode
            stream.addfile(entry, io.BytesIO(payload))


def allowed_name(name):
    path = PurePosixPath(name)
    if not name or '\\' in name or '\x00' in name or path.is_absolute() or str(path) != name or '..' in path.parts:
        return False
    if name in ('kit.json', 'tools/awf', 'tools/native-acceptance.test', 'input/manifest.json', 'input/stage/stage.json'):
        return True
    return bool(re.fullmatch(r'input/stage/(node|pi|awf-host|awf-extension|magpie)/[a-zA-Z0-9_.-]+', name)
                or re.fullmatch(r'input/supplemental/registry-[a-z-]+\.json', name)
                or re.fullmatch(r'input/cache/_cacache/content-v2/sha512/[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{124}', name)
                or re.fullmatch(r'input/cache/_cacache/index-v5/[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{60}', name))


def pack(args):
    if not re.fullmatch('[0-9a-f]{40}', args.source_commit):
        raise ValueError('exact source commit required')
    expected = dict(schema=1, version=VERSION, sourceCommit=args.source_commit, os='linux', arch='amd64', hostProtocol='v1')
    identity = json.loads(subprocess.check_output([str(args.host.resolve()), 'linux-build-identity'], timeout=10))
    if identity != expected:
        raise ValueError('compiled Host identity differs from approved candidate')
    if args.output.exists():
        raise ValueError('output already exists; preserve previous kit')
    for name, (size, digest) in PINS.items():
        source = args.audit / name
        if source.is_symlink() or not source.is_file() or source.stat().st_size != size or sha256_file(source) != digest:
            raise ValueError('audited official bytes changed: ' + name)
    with tempfile.TemporaryDirectory(prefix='awf-private-kit-', dir='/tmp') as temporary:
        root = Path(temporary)
        artifacts = []
        host_archive = root / ('awf_' + VERSION + '_linux_amd64.tar.gz')
        extension_archive = root / ('awf-extension_' + VERSION + '.tar.gz')
        archive(host_archive, [('awf', args.host.read_bytes(), 0o755), ('build.json', encode(expected), 0o644)])
        extension_identity = dict(schema=1, version=VERSION, sourceCommit=args.source_commit, extensionProtocol=1, piRPCVersion='1.0.2')
        archive(extension_archive, [('awf.ts', args.extension.read_bytes(), 0o644), ('extension.json', encode(extension_identity), 0o644)])
        components = []
        def component(name, version, sources):
            rows = []
            for filename, source, url, form in sources:
                rows.append(dict(name=filename, url=url, sha256=sha256_file(source), bytes=source.stat().st_size, format=form))
                artifacts.append(('input/stage/' + name + '/' + filename, source))
            components.append(dict(id=name, version=version, artifacts=rows))
        node = 'node-v22.19.0-linux-x64.tar.gz'
        component('node', 'v22.19.0', [(node, args.audit / node, 'https://nodejs.org/dist/v22.19.0/' + node, 'tar.gz')])
        component('pi', '1.0.2', [(name, args.audit / ('pi-official-' + name), 'https://github.com/earendil-works/pi/releases/download/v1.0.2/pi-coding-agent-install-' + name, 'json') for name in ('package.json', 'package-lock.json')])
        for name, source in [('awf-host', host_archive), ('awf-extension', extension_archive)]:
            component(name, VERSION, [(source.name, source, 'https://github.com/atongrun/agent-workflow/releases/download/' + VERSION + '/' + source.name, 'tar.gz')])
        magpie = 'magpie-cli-linux-amd64'
        component('magpie', '0.1.855', [(magpie, args.audit / magpie, 'https://github.com/yetone/magpie-releases/releases/download/v0.1.855/' + magpie, 'elf')])
        manifest = dict(schema=1, channel='linux-host-v1', version=VERSION, sourceCommit=args.source_commit, installerProtocol=1, hostProtocol='v1', extensionProtocol=1, piRPCVersion='1.0.2', os='linux', arch='amd64', libc='glibc', components=components)
        manifest_bytes = encode(manifest)
        digest = hashlib.sha256(manifest_bytes).hexdigest()
        receipt = dict(schema=1, manifestSHA256=digest, sourceCommit=args.source_commit, artifactsVerified=True, installed=False)
        metadata = dict(schema=1, kind='private-unpublished-native-test', sourceCommit=args.source_commit, version=VERSION, manifestSHA256=digest, publicReleaseVerified=False, nativeAcceptance=False)
        files = [('kit.json', encode(metadata)), ('input/manifest.json', manifest_bytes), ('input/stage/stage.json', encode(receipt)), ('tools/awf', args.host), ('tools/native-acceptance.test', args.runner)] + artifacts
        files += [('input/supplemental/' + p.name, p) for p in sorted(args.audit.glob('registry-*.json'))]
        for part in ('content-v2', 'index-v5'):
            source = args.cache / '_cacache' / part
            if source.is_symlink() or not source.is_dir():
                raise ValueError('private verified cache missing')
            for current, directories, entries in os.walk(source, followlinks=False):
                if any((Path(current) / p).is_symlink() for p in directories):
                    raise ValueError('cache directory link refused')
                for entry in entries:
                    path = Path(current) / entry
                    if not path.is_file() or path.is_symlink():
                        raise ValueError('cache special entry refused')
                    files.append(('input/cache/' + path.relative_to(args.cache).as_posix(), path))
        names = set()
        total = 0
        try:
            with args.output.open('xb') as output:
                os.chmod(args.output, 0o600)
                with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as kit:
                    for name, source in files:
                        if not allowed_name(name) or name in names:
                            raise ValueError('unexpected or duplicate private kit path')
                        names.add(name)
                        size = len(source) if isinstance(source, bytes) else source.stat().st_size
                        total += size
                        if len(names) > MAX_ENTRIES or total > MAX_BYTES:
                            raise ValueError('private kit budget exceeded')
                        entry = zipfile.ZipInfo(name)
                        entry.create_system = 3
                        entry.compress_type = zipfile.ZIP_DEFLATED
                        entry.external_attr = (stat.S_IFREG | (0o700 if name.startswith('tools/') else 0o600)) << 16
                        with kit.open(entry, 'w') as target:
                            if isinstance(source, bytes):
                                target.write(source)
                            else:
                                with source.open('rb') as stream:
                                    for chunk in iter(lambda: stream.read(1 << 20), b''):
                                        target.write(chunk)
        except Exception:
            args.output.unlink(missing_ok=True)
            raise
    print(json.dumps(dict(file=str(args.output.resolve()), bytes=args.output.stat().st_size, sha256=sha256_file(args.output), manifestSHA256=digest, entries=len(names), expandedBytes=total, sourceCommit=args.source_commit, publicReleaseVerified=False, nativeAcceptance=False), indent=2))


def extract(source, destination, expected):
    if not re.fullmatch('[0-9a-f]{64}', expected):
        raise ValueError('independently approved kit SHA256 required')
    if not destination.is_absolute() or str(destination) != os.path.normpath(destination) or not str(destination).startswith('/tmp/') or destination.exists() or destination.is_symlink():
        raise ValueError('fresh absolute destination beneath /tmp required')
    descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > MAX_BYTES:
            raise ValueError('private same-owner regular source required')
        if sha256_stream(stream) != expected:
            raise ValueError('independently approved kit SHA256 required')
        stream.seek(0)
        with zipfile.ZipFile(stream) as kit:
            extract_entries(kit, destination)


def extract_entries(kit, destination):
    names, total = set(), 0
    for entry in kit.infolist():
        mode = entry.external_attr >> 16
        wanted = stat.S_IFREG | (0o700 if entry.filename.startswith('tools/') else 0o600)
        if not allowed_name(entry.filename) or entry.filename in names or entry.flag_bits & 1 or mode != wanted or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise ValueError('unexpected private kit entry')
        names.add(entry.filename)
        total += entry.file_size
        if len(names) > MAX_ENTRIES or total > MAX_BYTES:
            raise ValueError('private kit budget exceeded')
    required = {'kit.json', 'tools/awf', 'tools/native-acceptance.test', 'input/manifest.json', 'input/stage/stage.json'}
    if not required.issubset(names) or any(str(parent) in names for name in names for parent in PurePosixPath(name).parents):
        raise ValueError('missing kit controls or conflicting paths')
    destination_fd = create_private_destination(destination)
    try:
        for entry in kit.infolist():
            directory_fd = os.dup(destination_fd)
            try:
                parts = PurePosixPath(entry.filename).parts
                for part in parts[:-1]:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=directory_fd)
                    except FileExistsError:
                        pass
                    next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                    os.close(directory_fd)
                    directory_fd = next_fd
                    require_private_directory(directory_fd)
                descriptor = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
                with os.fdopen(descriptor, 'wb') as output, kit.open(entry) as payload:
                    remaining = entry.file_size
                    while remaining:
                        chunk = payload.read(min(1 << 20, remaining))
                        if not chunk:
                            raise ValueError('truncated private kit payload')
                        output.write(chunk)
                        remaining -= len(chunk)
                    if payload.read(1):
                        raise ValueError('private kit payload exceeded length')
                    os.fchmod(output.fileno(), 0o700 if entry.filename.startswith('tools/') else 0o600)
            finally:
                os.close(directory_fd)
    finally:
        os.close(destination_fd)


def require_private_directory(descriptor):
    info = os.fstat(descriptor)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('private same-owner destination ancestor required')


def create_private_destination(destination):
    # Keep all writes relative to held nofollow directory descriptors. Root
    # extraction also requires the shared /tmp base to be root-owned and sticky.
    current = os.open('/tmp', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(current)
        if not stat.S_ISDIR(info.st_mode) or not info.st_mode & stat.S_ISVTX or (os.getuid() == 0 and info.st_uid != 0):
            raise ValueError('trusted sticky /tmp required')
        parts = destination.relative_to('/tmp').parts
        if not parts:
            raise ValueError('fresh destination beneath /tmp required')
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            os.close(current)
            current = next_fd
            require_private_directory(current)
        os.mkdir(parts[-1], mode=0o700, dir_fd=current)
        result = os.open(parts[-1], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
        try:
            require_private_directory(result)
        except Exception:
            os.close(result)
            raise
        return result
    except OSError as error:
        raise ValueError('untrusted or unavailable destination ancestor') from error
    finally:
        os.close(current)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest='mode', required=True)
    package = modes.add_parser('pack')
    for name in ('host', 'runner', 'extension', 'audit', 'cache', 'output'):
        package.add_argument('--' + name, type=Path, required=True)
    package.add_argument('--source-commit', required=True)
    unpack = modes.add_parser('extract')
    unpack.add_argument('--source', type=Path, required=True)
    unpack.add_argument('--destination', type=Path, required=True)
    unpack.add_argument('--sha256', required=True)
    args = parser.parse_args()
    if args.mode == 'pack':
        pack(args)
    else:
        extract(args.source, args.destination, args.sha256)


if __name__ == '__main__':
    main()
