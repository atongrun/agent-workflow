#!/usr/bin/env python3
"""Portable package and bootstrap contract tests; not a PowerShell runtime test."""
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SCRIPTS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("package_windows", SCRIPTS / "package_windows.py")
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


def fake_pe(arch):
    data = bytearray(256)
    data[:2] = b"MZ"
    data[0x3C:0x40] = (128).to_bytes(4, "little")
    data[128:132] = b"PE\0\0"
    data[132:134] = {"amd64": 0x8664, "arm64": 0xAA64}[arch].to_bytes(2, "little")
    data[152:154] = b"\x0b\x02"
    return bytes(data)


class PackageTests(unittest.TestCase):
    def test_exact_stable_version(self):
        for version in ("v0.0.0", "v1.2.3", "v123.456.789"):
            self.assertEqual(package.validate_version(version), version)
        for version in ("latest", "1.2.3", "v1.2", "v01.2.3", "v1.2.3-rc.1", "v1.2.3+build", "v1.2.3\n", "../v1.2.3"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                package.validate_version(version)

    def test_native_pe_architecture(self):
        for arch in package.ARCHITECTURES:
            package.validate_pe(fake_pe(arch), arch)
        for data in (b"MZ", b"not-an-executable", fake_pe("arm64")):
            with self.assertRaises(ValueError):
                package.validate_pe(data, "amd64")
        broken = bytearray(fake_pe("amd64"))
        broken[0x3C:0x40] = (0xFFFFFFFF).to_bytes(4, "little")
        with self.assertRaises(ValueError):
            package.validate_pe(broken, "amd64")

    def test_reproducible_archive_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for arch in package.ARCHITECTURES:
                binaries = {name: fake_pe(arch) for name in ("awf.exe", "awf-node.exe")}
                a, b = root / f"{arch}-a.zip", root / f"{arch}-b.zip"
                for path in (a, b):
                    package.write_archive(path, "v1.2.3", arch, binaries)
                self.assertEqual(a.read_bytes(), b.read_bytes())
                with zipfile.ZipFile(a) as archive:
                    self.assertEqual(tuple(archive.namelist()), package.MEMBERS)
                    self.assertEqual(json.loads(archive.read("manifest.json")),
                                     {"version": "v1.2.3", "os": "windows", "arch": arch})
                    for member in archive.infolist():
                        self.assertTrue(stat.S_ISREG(member.external_attr >> 16))
                        self.assertEqual(member.date_time, (1980, 1, 1, 0, 0, 0))
                        self.assertEqual(member.compress_type, zipfile.ZIP_STORED)

    def test_wrong_or_extra_members_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.zip"
            for binaries in ({}, {"awf.exe": fake_pe("amd64")},
                             {"awf.exe": fake_pe("amd64"), "awf-node.exe": fake_pe("arm64")},
                             {"awf.exe": fake_pe("amd64"), "awf-node.exe": fake_pe("amd64"), "extra": b"x"}):
                with self.assertRaises(ValueError):
                    package.write_archive(path, "v1.2.3", "amd64", binaries)
            self.assertFalse(path.exists())

    def test_size_limit(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(package, "MAX_RELEASE_BYTES", 300):
            with self.assertRaises(ValueError):
                package.write_archive(Path(temporary) / "oversize.zip", "v1.2.3", "amd64",
                                      {name: fake_pe("amd64") for name in ("awf.exe", "awf-node.exe")})

    def test_packager_flags_checksums_no_overwrite(self):
        calls = []

        def build(command, **kwargs):
            calls.append((command, kwargs["env"].copy()))
            self.assertEqual(kwargs["cwd"], package.REPOSITORY)
            Path(command[command.index("-o") + 1]).write_bytes(fake_pe(kwargs["env"]["GOARCH"]))

        with tempfile.TemporaryDirectory() as temporary, patch.object(package.subprocess, "run", side_effect=build):
            output = Path(temporary)
            paths = package.build_assets("v1.2.3", output, "test-go")
            self.assertEqual(len(calls), 4)
            self.assertEqual(len(paths), 4)
            for command, env in calls:
                self.assertIn("-trimpath", command)
                self.assertIn("-buildvcs=false", command)
                self.assertIn("-X github.com/atongrun/agent-workflow/internal/lifecycle.Version=v1.2.3", command[command.index("-ldflags") + 1])
                self.assertEqual(env["GOTOOLCHAIN"], "local")
                self.assertEqual(env["CGO_ENABLED"], "0")
                self.assertEqual(env["GOOS"], "windows")
            for line in (output / "SHA256SUMS").read_text().splitlines():
                digest, filename = line.split("  ")
                self.assertEqual(digest, hashlib.sha256((output / filename).read_bytes()).hexdigest())
            with self.assertRaises(ValueError):
                package.build_assets("v1.2.3", output, "test-go")
            self.assertEqual(len(calls), 4)

    def test_failed_build_leaves_no_release_assets(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(package.subprocess, "run", side_effect=OSError("failed")):
            with self.assertRaises(OSError):
                package.build_assets("v1.2.3", Path(temporary), "test-go")
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_bootstrap_static_trust_boundary(self):
        script = (SCRIPTS / "install.ps1").read_text()
        main = script[script.index("function Invoke-AwfBootstrap"):]
        stages = ["Get-AwfNativeArchitecture", "releases/tags/$Version", "Get-AwfReleaseUrls",
                  "Get-AwfChecksum", "Get-FileHash", "Expand-AwfVerifiedArchive", "& $executable", "Add-AwfUserPath"]
        positions = [main.index(stage) for stage in stages]
        self.assertEqual(positions, sorted(positions))
        for prohibited in ("Invoke-Expression", "Set-ExecutionPolicy", "Start-Process", "New-NetFirewallRule", "releases/latest", "-Verb RunAs"):
            self.assertNotIn(prohibited, script)
        self.assertIn("IsWow64Process2", script)
        self.assertIn("return nativeMachine;", script)
        self.assertIn("$Sha256 -and $digest -ine $Sha256", script)
        self.assertIn("'--archive' $archive '--version' $Version '--sha256' $digest", script)
        self.assertIn("$LASTEXITCODE -ne 0", script)


if __name__ == "__main__":
    unittest.main()
