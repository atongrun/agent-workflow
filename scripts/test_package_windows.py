#!/usr/bin/env python3
"""Portable package and bootstrap contract tests; not a PowerShell runtime test."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import subprocess
import sys
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

    def test_explicit_release_candidate_policy(self):
        for version in ("v0.0.0-rc.0", "v0.0.0-rc.1", "v12.34.56-rc.789"):
            with self.subTest(version=version):
                with self.assertRaisesRegex(ValueError, "--allow-prerelease"):
                    package.validate_version(version)
                self.assertEqual(package.validate_version(version, allow_prerelease=True), version)
        self.assertEqual(package.validate_version("v1.2.3", allow_prerelease=True), "v1.2.3")
        for version in ("latest", "", "v1.2.3-rc", "v1.2.3-rc.01", "v1.2.3-rc.-1",
                        "v01.2.3-rc.1", "v1.02.3-rc.1", "v1.2.03-rc.1", "v1.2.3-rc.1.2",
                        "v1.2.3-beta.1", "v1.2.3-rc.1+build", "v1.2.3+build", "v1.2.3-rc.1\n",
                        "V1.2.3", "v1.2.3-RC.1", "../v1.2.3-rc.1", "v1.2.3-rc.١"):
            for allow in (False, True):
                with self.subTest(version=version, allow=allow), self.assertRaises(ValueError):
                    package.validate_version(version, allow_prerelease=allow)

    def test_rejected_version_never_builds_or_changes_output(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(package.subprocess, "run") as build:
            root = Path(temporary)
            for version, allow in (("v0.0.0-rc.1", False), ("v0.0.0-rc.01", True), ("v0.0.0-beta.1", True)):
                for output in (root / "missing", root):
                    with self.subTest(version=version, output=output), self.assertRaises(ValueError):
                        package.build_assets(version, output, "test-go", allow_prerelease=allow)
                    self.assertEqual(list(root.iterdir()), [])
                path = root / "rejected.zip"
                with self.assertRaises(ValueError):
                    package.write_archive(path, version, "amd64",
                                          {name: fake_pe("amd64") for name in ("awf.exe", "awf-node.exe")},
                                          allow_prerelease=allow)
                self.assertFalse(path.exists())
            build.assert_not_called()

    def test_command_line_rejects_unapproved_or_invalid_rc_before_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "missing"
            for version, flags in (("v0.0.0-rc.1", []), ("v0.0.0-rc.01", ["--allow-prerelease"])):
                result = subprocess.run([sys.executable, str(SCRIPTS / "package_windows.py"),
                                         "--version", version, "--output", str(output),
                                         "--go", "compiler-must-not-run", *flags], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Packaging failed:", result.stderr)
                self.assertNotIn("compiler-must-not-run", result.stderr)
                self.assertFalse(output.exists())

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

    def test_command_line_passes_explicit_opt_in_only(self):
        for version, flags, allow in (("v1.2.3", [], False),
                                      ("v0.0.0-rc.1", ["--allow-prerelease"], True)):
            argv = ["package_windows.py", "--version", version, "--output", "local-fixture", *flags]
            with self.subTest(version=version), patch.object(sys, "argv", argv), \
                    patch.object(sys, "stdout", io.StringIO()), patch.object(package, "build_assets", return_value=[]) as build:
                package.main()
                build.assert_called_once_with(version, Path("local-fixture"), "go", allow_prerelease=allow)

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

    def test_opted_in_rc_package_preserves_exact_version_and_checksums(self):
        version = "v0.0.0-rc.1"

        def build(command, **kwargs):
            self.assertIn("-X github.com/atongrun/agent-workflow/internal/lifecycle.Version=" + version,
                          command[command.index("-ldflags") + 1])
            Path(command[command.index("-o") + 1]).write_bytes(fake_pe(kwargs["env"]["GOARCH"]))

        with tempfile.TemporaryDirectory() as temporary, patch.object(package.subprocess, "run", side_effect=build) as build_mock:
            output = Path(temporary)
            paths = package.build_assets(version, output, "test-go", allow_prerelease=True)
            self.assertEqual(build_mock.call_count, 4)
            self.assertEqual({path.name for path in paths},
                             {f"awf_{version}_windows_amd64.zip", f"awf_{version}_windows_arm64.zip",
                              "install.ps1", "SHA256SUMS"})
            self.assertEqual((output / "install.ps1").read_bytes(), (SCRIPTS / "install.ps1").read_bytes())
            for arch in package.ARCHITECTURES:
                with zipfile.ZipFile(output / f"awf_{version}_windows_{arch}.zip") as archive:
                    self.assertEqual(tuple(archive.namelist()), package.MEMBERS)
                    self.assertEqual(json.loads(archive.read("manifest.json")),
                                     {"version": version, "os": "windows", "arch": arch})
                    for name in ("awf.exe", "awf-node.exe"):
                        package.validate_pe(archive.read(name), arch)
            for line in (output / "SHA256SUMS").read_text().splitlines():
                digest, filename = line.split("  ")
                self.assertEqual(digest, hashlib.sha256((output / filename).read_bytes()).hexdigest())
            with self.assertRaises(ValueError):
                package.build_assets(version, output, "test-go", allow_prerelease=True)
            self.assertEqual(build_mock.call_count, 4)

    def test_failed_build_leaves_no_release_assets(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(package.subprocess, "run", side_effect=OSError("failed")):
            with self.assertRaises(OSError):
                package.build_assets("v1.2.3", Path(temporary), "test-go")
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_bootstrap_static_trust_boundary(self):
        script = (SCRIPTS / "install.ps1").read_text()
        main = script[script.index("function Invoke-AwfBootstrap"):]
        stages = ["Assert-AwfReleaseVersion", "Get-AwfNativeArchitecture", "releases/tags/$Version", "Get-AwfReleaseUrls",
                  "Get-AwfChecksum", "Get-FileHash", "Expand-AwfVerifiedArchive", "& $executable", "Confirm-AwfInstalledLauncher"]
        positions = [main.index(stage) for stage in stages]
        self.assertEqual(positions, sorted(positions))
        for prohibited in ("Invoke-Expression", "Set-ExecutionPolicy", "Start-Process", "New-NetFirewallRule", "releases/latest", "-Verb RunAs"):
            self.assertNotIn(prohibited, script)
        self.assertIn("IsWow64Process2", script)
        self.assertIn("return nativeMachine;", script)
        self.assertIn("$Sha256 -and $digest -ine $Sha256", script)
        self.assertIn("@('install', '--yes', '--archive', $archive, '--version', $Version, '--sha256', $digest)", script)
        self.assertIn("if ($AllowPrerelease) { $installArguments += '--allow-prerelease' }", script)
        self.assertIn("Get-AwfReleaseUrls $release $Version $asset -AllowPrerelease:$AllowPrerelease", script)
        self.assertIn("$Release.prerelease -ne $isPrerelease", script)
        self.assertIn("$Release.prerelease -isnot [bool] -or $Release.draft", script)
        self.assertIn("$LASTEXITCODE -ne 0", script)
        self.assertIn("$null = & $executable @installArguments", main)
        self.assertLess(main.index("$null = & $executable"), main.index("$LASTEXITCODE -ne 0", main.index("$null = & $executable")))
        self.assertLess(main.index("$LASTEXITCODE -ne 0", main.index("$null = & $executable")), main.index("Confirm-AwfInstalledLauncher"))

    def test_install_context_gates_before_effects(self):
        script = (SCRIPTS / "install.ps1").read_text()
        main = script[script.index("function Invoke-AwfBootstrap"):]
        stages = ["LOCALAPPDATA must match", "Assert-AwfUnpackagedProcess", "$programs = Get-AwfUserProgramFiles",
                  "Assert-AwfProgramsPath $programs", "$root = Join-Path $programs 'AWF'",
                  "New-AwfPrivateStage", "Save-AwfOfficialDownload", "& $executable",
                  "Confirm-AwfInstalledLauncher", "Write-Host \"Installed AWF"]
        positions = [main.index(stage) for stage in stages]
        self.assertEqual(positions, sorted(positions))
        registration = script[script.index("function Confirm-AwfInstalledLauncher"):script.index("function Invoke-AwfBootstrap")]
        gates = [registration.index(value) for value in ("Assert-AwfDirectoryPath", "[IO.FileInfo]", "Assert-AwfNativePath", "Add-AwfProcessPath")]
        self.assertEqual(gates, sorted(gates))
        stage = script[script.index("function New-AwfPrivateStage"):script.index("function Save-AwfOfficialDownload")]
        self.assertLess(stage.index("Set-Acl"), stage.index("Assert-AwfNativePath"))
        self.assertLess(stage.index("Assert-AwfNativePath"), stage.index("return $directory.FullName"))
        self.assertIn("[IO.Directory]::Delete($directory.FullName)", stage)
        for native in ("GetCurrentPackageFullName", "GetFinalPathNameByHandleW", "SafeFileHandle", "OPEN_EXISTING"):
            self.assertIn(native, script)
        self.assertIn("if ($status -eq 15700) { return }", script)
        self.assertIn("[StringComparison]::OrdinalIgnoreCase", script)
        self.assertIn("GetFinalPathNameByHandleW(handle, result, capacity, 0)", script)
        canonical = script[script.index("function ConvertTo-AwfCanonicalWindowsPath"):script.index("function Get-AwfFinalPath")]
        self.assertNotIn("[IO.Path]::GetFullPath", canonical)

        self.assertNotIn("$env:LOCALAPPDATA =", script)
        self.assertNotIn("$root = Join-Path $local", main)
        self.assertNotIn("--install-dir", script)
        self.assertIn('new Guid("5CD7AEE2-2219-4A67-B85D-6C9CE15660CB")', script)
        self.assertIn("SHGetKnownFolderPath(ref folder, 0x00004000,", script)
        self.assertIn("Marshal.FreeCoTaskMem(path)", script)
        self.assertIn("if (result < 0) Marshal.ThrowExceptionForHR(result)", script)
        resolver = script[script.index("function Get-AwfUserProgramFiles"):script.index("function Assert-AwfUnpackagedProcess")]
        self.assertIn("ConvertTo-AwfCanonicalWindowsPath $path", resolver)
        self.assertIn("No fallback installation path is supported", resolver)
        self.assertNotIn("LOCALAPPDATA", resolver)
        planning = script[script.index("function Assert-AwfProgramsPath"):script.index("function New-AwfPrivateStage")]
        for required in ("catch [Management.Automation.ItemNotFoundException]", "[IO.Path]::GetDirectoryName($current)",
                         "Assert-AwfDirectoryPath $current", "Assert-AwfNativePath $current"):
            self.assertIn(required, planning)
        for prohibited in ("CreateDirectory", "Set-Acl", "SetEnvironmentVariable"):
            self.assertNotIn(prohibited, planning)
        self.assertNotIn("SkipContext", script)
        native = (SCRIPTS / "test_install_context.ps1").read_text()
        for required in ("Status = 15700", "Status = 122", "Status = 0", "Status = 5", "Status = 'throw'",
                         "NO_PACKAGE plus redirected stage", "rejected private stage is removed", "Assert-AwfNativePath $file"):
            self.assertIn(required, native)
        identity = (SCRIPTS / "test_install_identity.ps1").read_text()
        self.assertIn("$ExpectedIdentity", identity)
        self.assertNotIn("Invoke-AwfBootstrap", identity)
        self.assertIn("not a filesystem-redirection or installation acceptance result", identity)

    def test_path_promotion_is_narrow_and_after_physical_verification(self):
        script = (SCRIPTS / "install.ps1").read_text()
        pure = script[script.index("function Move-AwfPathEntryFirst"):script.index("function Add-AwfProcessPath")]
        self.assertNotIn("SetEnvironmentVariable", pure)
        self.assertIn("OrdinalIgnoreCase", pure)
        self.assertIn("$remaining.Add($part)", pure)
        setters = script[script.index("function Add-AwfProcessPath"):script.index("function Warn-AwfCommandShadowing")]
        self.assertNotIn("'User'", setters)
        self.assertIn("Move-AwfPathEntryFirst $process $Bin", setters)
        self.assertNotIn("'Machine'", setters)
        main = script[script.index("function Invoke-AwfBootstrap"):]
        self.assertLess(main.index("Confirm-AwfInstalledLauncher"), main.index("Warn-AwfCommandShadowing"))
        warn = script[script.index("function Warn-AwfCommandShadowing"):script.index("function Confirm-AwfInstalledLauncher")]
        self.assertIn("Get-Command", warn)
        self.assertIn("Write-Warning", warn)
        self.assertIn("$PSModuleAutoLoadingPreference = 'None'", warn)
        for prohibited in ("Set-Alias", "Remove-Item", "Set-Item", "SetEnvironmentVariable"):
            self.assertNotIn(prohibited, warn)
        native = (SCRIPTS / "test_install_path.ps1").read_text()
        for label in ("quoted", "case variant", "trailing separator", "all exact duplicates", "already first",
                      "missing", "other formatting preserved", "unrelated duplicates preserved", "idempotent"):
            self.assertIn(label, native)
        self.assertNotIn("Add-AwfProcessPath", native)
        self.assertNotIn("SetEnvironmentVariable", native)

    def test_documented_simple_entry_and_trust_boundary(self):
        document = (SCRIPTS.parent / "docs" / "windows-cli.md").read_text()
        self.assertIn('powershell -NoProfile -Command "irm https://raw.githubusercontent.com/atongrun/agent-workflow/awf/go-v1/scripts/install.ps1 | iex"', document)
        self.assertIn("mutable official branch", document)
        self.assertIn("not independently authenticate", document)
        self.assertIn("not published or accepted on native Windows", document)
        self.assertIn("protocol 3", document)
        self.assertIn("FOLDERID_UserProgramFiles", document)
        self.assertIn(r"%LOCALAPPDATA%\Programs\AWF", document)
        self.assertIn("no LocalAppData fallback", document)
        self.assertNotIn("-SkipInit", document)
        self.assertNotIn("<INDEPENDENT_INSTALL_PS1_SHA256>", document)

    def test_optional_pin_and_real_entry_regressions(self):
        script = (SCRIPTS / "install.ps1").read_text()
        main = script[script.index("function Invoke-AwfBootstrap"):]
        self.assertNotIn("[ValidatePattern(", script)
        self.assertLess(main.index("Assert-AwfArchivePin"), main.index("Get-AwfNativeArchitecture"))
        self.assertIn("$answer -isnot [string] -or $answer -cnotmatch", script)
        native = (SCRIPTS / "test_entry.ps1").read_text()
        self.assertIn("$process.StandardInput.Close()", native)
        self.assertIn("function Invoke-RestMethod", native)
        self.assertIn("scripts/install.ps1' | iex", native)
        self.assertIn("$env:LOCALAPPDATA = ''", native)
        self.assertIn("AWF_REAL_READHOST_EOF_REJECTED", native)
        self.assertNotIn("function Read-Host", native)
        self.assertNotIn("Set-ExecutionPolicy", native)

    def test_bootstrap_is_fresh_only_and_native_owns_installation(self):
        script = (SCRIPTS / "install.ps1").read_text()
        main = script[script.index("function Invoke-AwfBootstrap"):]
        self.assertLess(main.index("Assert-AwfFreshRoot $root"), main.index("New-AwfPrivateStage"))
        root = script[script.index("function Assert-AwfFreshRoot"):script.index("function Confirm-AwfInstalledLauncher")]
        self.assertIn("Get-Item -LiteralPath $Root -Force -ErrorAction Stop", root)
        self.assertIn("catch [Management.Automation.ItemNotFoundException] { return }", root)
        self.assertIn("empty, partial, or credentials-only roots", root)
        self.assertIn("does not migrate, adopt, repair, or overwrite", root)
        for forbidden in ("_install", "Save-AwfLegacyChannel", "-SkipInit", "& $launcher init",
                          "SetEnvironmentVariable('Path', $new, 'User')"):
            self.assertNotIn(forbidden, script)
        self.assertEqual(script.count("Set-Acl"), 1)
        stage = script[script.index("function New-AwfPrivateStage"):script.index("function Save-AwfOfficialDownload")]
        self.assertIn("Set-Acl", stage)
        self.assertIn("$protocol = @(& $executable install-protocol)", main)
        self.assertIn("$protocol.Count -ne 1 -or $protocol[0] -cne '3'", main)
        self.assertLess(main.index("Expand-AwfVerifiedArchive"), main.index("& $executable install-protocol"))
        self.assertLess(main.index("& $executable install-protocol"), main.index("$null = & $executable @installArguments"))
        self.assertIn("$installArguments += @('--channel', 'go-v1')", main)
        self.assertIn("Confirm-AwfPreview $Version ([bool] $AllowPrerelease) (Test-AwfInteractive)", main)
        self.assertNotIn("$UseChannel", script)
        native = (SCRIPTS / "test_fresh_install.ps1").read_text()
        for label in ("empty root", "credentials-only root", "root file", "unknown root state",
                      "existing root precedes staging", "historical protocol", "fresh protocol",
                      "missing Programs planning does not create it", "missing parent is not recursively created",
                      "Programs file is refused", "redirected Programs ancestor is refused",
                      "historical sibling root is ignored", "existing Programs AWF root refused",
                      "historical sibling preserved on refusal", "unavailable known folder has no fallback"):
            self.assertIn(label, native)

    def test_distribution_manifest_names_only_verified_existing_release(self):
        manifest = json.loads((SCRIPTS.parent / "distribution" / "go-v1.json").read_text())
        self.assertEqual(manifest, {
            "schema": "1", "channel": "go-v1", "version": "v1.0.0-rc.6",
            "sourceCommit": "53f4906f453dbe5cb178ea18bcb5239d5d605427", "cliProtocol": "3",
            "windowsAMD64SHA256": "0d590b6616096bb16b5ca404810059d19687e5d5415bcef9a2696e9fd82ea174",
            "windowsARM64SHA256": "5472a4930bb2c9bc889da92ad4c070241c55737d57f63612ce4a8df78db23bcc",
        })

    def test_bootstrap_channel_contract(self):
        script = (SCRIPTS / "install.ps1").read_text()
        main = script[script.index("function Invoke-AwfBootstrap"):]
        self.assertNotIn("Mandatory = $true", script)
        self.assertIn("https://raw.githubusercontent.com/atongrun/agent-workflow/awf/go-v1/distribution/go-v1.json", script)
        stages = ["Read-AwfChannelManifest", "Assert-AwfFreshChannel", "Confirm-AwfPreview", "Get-AwfReleaseUrls",
                  "Assert-AwfChannelRelease", "$channelDigest -and $digest -cne $channelDigest",
                  "Get-FileHash", "Expand-AwfVerifiedArchive", "& $executable",
                  "Confirm-AwfInstalledLauncher", "Next, run awf init"]
        positions = [main.index(stage) for stage in stages]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("$Metadata -or $Channel -or $redirects -eq 5", script)
        self.assertIn("$Url -cne $script:ChannelUrl", script)
        self.assertIn("$Channel.cliProtocol -cne '3'", script)
        self.assertIn("this bootstrap does not install historical releases", script)
        self.assertIn("if (-not $Interactive)", script)
        self.assertNotIn("[IO.File]::WriteAllText($path", script)


if __name__ == "__main__":
    unittest.main()
