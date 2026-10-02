#!/usr/bin/env python3
"""Build deterministic AWF Windows release assets locally; never publish them."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile

REPOSITORY = Path(__file__).resolve().parents[1]
VERSION_RE = re.compile(r"v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
ARCHITECTURES = ("amd64", "arm64")
MAX_RELEASE_BYTES = 100 << 20
MEMBERS = ("awf.exe", "awf-node.exe", "manifest.json")


def validate_version(version: str) -> str:
    if not VERSION_RE.fullmatch(version):
        raise ValueError("version must be an exact stable tag vX.Y.Z without leading zeros")
    return version


def asset_name(version: str, arch: str) -> str:
    validate_version(version)
    if arch not in ARCHITECTURES:
        raise ValueError("architecture must be amd64 or arm64")
    return f"awf_{version}_windows_{arch}.zip"


def validate_pe(data: bytes, arch: str) -> None:
    """Catch wrong-target or placeholder inputs before producing a release ZIP."""
    machine = {"amd64": 0x8664, "arm64": 0xAA64}[arch]
    if len(data) < 88 or data[:2] != b"MZ":
        raise ValueError("executable is not a native Windows PE")
    offset = int.from_bytes(data[0x3C:0x40], "little")
    if not 64 <= offset <= len(data) - 26:
        raise ValueError("invalid PE header offset")
    if data[offset:offset + 4] != b"PE\0\0" or int.from_bytes(data[offset + 4:offset + 6], "little") != machine:
        raise ValueError("PE machine does not match release architecture")
    if data[offset + 24:offset + 26] != b"\x0b\x02":
        raise ValueError("release requires native 64-bit PE executables")


def write_archive(destination: Path, version: str, arch: str, binaries: dict[str, bytes]) -> None:
    asset_name(version, arch)
    if set(binaries) != {"awf.exe", "awf-node.exe"}:
        raise ValueError("exactly awf.exe and awf-node.exe are required")
    for binary in binaries.values():
        validate_pe(binary, arch)
    manifest = (json.dumps({"version": version, "os": "windows", "arch": arch},
                           separators=(",", ":")) + "\n").encode("utf-8")
    contents = {**binaries, "manifest.json": manifest}
    if sum(map(len, contents.values())) > MAX_RELEASE_BYTES:
        raise ValueError("uncompressed release exceeds 100 MiB")
    # ZIP_STORED deliberately avoids compression-library-dependent output.
    # Stable order, timestamp, permissions, JSON, and Go flags make repeated
    # builds reproducible when source and exact Go toolchain are unchanged.
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_STORED,
                         allowZip64=False) as archive:
        for name in MEMBERS:
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = (stat.S_IFREG | 0o755) << 16
            if name == "manifest.json":
                entry.external_attr = (stat.S_IFREG | 0o644) << 16
            entry.compress_type = zipfile.ZIP_STORED
            archive.writestr(entry, contents[name])
    if destination.stat().st_size > MAX_RELEASE_BYTES:
        destination.unlink()
        raise ValueError("release archive exceeds 100 MiB")


def build_assets(version: str, output: Path, go: str) -> list[Path]:
    validate_version(version)
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    names = [asset_name(version, arch) for arch in ARCHITECTURES] + ["install.ps1", "SHA256SUMS"]
    if any((output / name).exists() for name in names):
        raise ValueError("output contains release assets already; use a fresh output directory")
    env = os.environ.copy()
    # The caller chooses the installed Go toolchain. Never auto-download one.
    env.update(GOOS="windows", CGO_ENABLED="0", GOTOOLCHAIN="local", GOFLAGS="",
               GOAMD64="v1", GOARM64="v8.0", GOEXPERIMENT="")
    with tempfile.TemporaryDirectory(prefix="awf-release-", dir=output) as temporary:
        staging = Path(temporary)
        for arch in ARCHITECTURES:
            env["GOARCH"] = arch
            binaries = {}
            for executable, command in (("awf.exe", "awf"), ("awf-node.exe", "awf-node")):
                path = staging / executable
                subprocess.run([go, "build", "-trimpath", "-buildvcs=false",
                                "-ldflags", "-s -w -buildid= -X github.com/atongrun/agent-workflow/internal/lifecycle.Version=" + version,
                                "-o", str(path), "./cmd/" + command],
                               cwd=REPOSITORY, env=env, check=True)
                binaries[executable] = path.read_bytes()
                path.unlink()
            write_archive(staging / asset_name(version, arch), version, arch, binaries)
        shutil.copyfile(REPOSITORY / "scripts" / "install.ps1", staging / "install.ps1")
        checksum_names = names[:-1]
        sums = "".join(f"{hashlib.sha256((staging / name).read_bytes()).hexdigest()}  {name}\n"
                       for name in checksum_names)
        (staging / "SHA256SUMS").write_text(sums, encoding="ascii", newline="\n")
        # All builds and validation succeed before final assets become visible.
        # Exclusive creation also prevents accidental clobber in a racing build.
        created = []
        try:
            for name in names:
                with (output / name).open("xb") as target:
                    created.append(output / name)
                    with (staging / name).open("rb") as source:
                        shutil.copyfileobj(source, target)
        except BaseException:
            for path in created:
                path.unlink()
            raise
    return [output / name for name in names]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="exact stable release tag, e.g. v1.2.3")
    parser.add_argument("--output", type=Path, required=True, help="local directory with no existing release assets")
    parser.add_argument("--go", default="go", help="installed Go executable; no toolchain is downloaded")
    args = parser.parse_args()
    try:
        paths = build_assets(args.version, args.output, args.go)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Packaging failed: {error}\n")
    for path in paths:
        print(path)
    print("Local assets only. No release was created, uploaded, tagged, or pushed.")


if __name__ == "__main__":
    main()
