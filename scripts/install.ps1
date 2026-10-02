#requires -Version 5.1
<#
.SYNOPSIS
Installs an exact published AWF release for the current Windows user.
.DESCRIPTION
Downloads only official GitHub release assets. The release ZIP is verified and
validated before its awf.exe is executed. This script does not configure or start
AWF, edit the firewall, pair credentials, or change execution policy.
.PARAMETER Version
An exact stable tag vX.Y.Z, or vX.Y.Z-rc.N with -AllowPrerelease. No aliases.
.PARAMETER AllowPrerelease
Explicitly allow the exact release candidate tag named by -Version.
.PARAMETER Sha256
Optional independently obtained SHA-256 for this architecture's release ZIP.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $Version,
    [ValidatePattern('\A[0-9A-Fa-f]{64}\z')]
    [string] $Sha256,
    [switch] $AllowPrerelease
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:Repository = 'atongrun/agent-workflow'
$script:MaxReleaseBytes = 100MB

function Assert-AwfReleaseVersion([string] $Tag, [switch] $AllowPrerelease) {
    if ($Tag -cmatch '\Av(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\z') { return }
    if ($Tag -cmatch '\Av(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)-rc\.(?:0|[1-9][0-9]*)\z') {
        if (-not $AllowPrerelease) { throw 'Release candidate tags require -AllowPrerelease and an exact -Version.' }
        return
    }
    throw 'Version must be an exact tag vX.Y.Z or vX.Y.Z-rc.N without leading zeros.'
}

function Get-AwfNativeArchitecture {
    if (-not ('AwfBootstrap.NativeSystem' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
namespace AwfBootstrap {
    public static class NativeSystem {
        [DllImport("kernel32.dll")]
        private static extern IntPtr GetCurrentProcess();
        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool IsWow64Process2(IntPtr process,
            out ushort processMachine, out ushort nativeMachine);
        public static ushort NativeMachine() {
            ushort processMachine, nativeMachine;
            if (!IsWow64Process2(GetCurrentProcess(), out processMachine, out nativeMachine))
                throw new Win32Exception(Marshal.GetLastWin32Error());
            return nativeMachine;
        }
    }
}
'@
    }
    # GetNativeSystemInfo is intentionally not used: under ARM64 emulation it
    # can describe the emulated CPU. IsWow64Process2 identifies the host machine.
    try { $machine = [AwfBootstrap.NativeSystem]::NativeMachine() }
    catch { throw 'Cannot detect native architecture. Windows 10/Server version 1709 or newer is required.' }
    switch ($machine) {
        0x8664 { return 'amd64' }
        0xAA64 { return 'arm64' }
        default { throw 'AWF requires native Windows AMD64 or ARM64.' }
    }
}

function Assert-AwfDirectoryPath([string] $Path) {
    $item = Get-Item -LiteralPath $Path -Force
    while ($null -ne $item) {
        if (-not $item.PSIsContainer -or
            ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Bootstrap directories must be real directories, not reparse points.'
        }
        $item = $item.Parent
    }
}

function New-AwfPrivateStage([string] $Parent) {
    Assert-AwfDirectoryPath $Parent
    $path = Join-Path $Parent ('AWF-bootstrap-' + [Guid]::NewGuid().ToString('N'))
    # A random directory in the current user's profile, restricted before files
    # are written. Other processes of this same user are outside this boundary.
    $directory = [IO.Directory]::CreateDirectory($path)
    try {
        $acl = New-Object Security.AccessControl.DirectorySecurity
        $acl.SetAccessRuleProtection($true, $false)
        $user = [Security.Principal.WindowsIdentity]::GetCurrent().User
        $system = New-Object Security.Principal.SecurityIdentifier('S-1-5-18')
        $acl.SetOwner($user)
        foreach ($sid in @($user, $system)) {
            $rule = New-Object Security.AccessControl.FileSystemAccessRule(
                $sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
            [void] $acl.AddAccessRule($rule)
        }
        Set-Acl -LiteralPath $directory.FullName -AclObject $acl
        Assert-AwfDirectoryPath $directory.FullName
        return $directory.FullName
    } catch {
        [IO.Directory]::Delete($directory.FullName)
        throw
    }
}

function Save-AwfOfficialDownload {
    param([string] $Url, [string] $Destination, [long] $Limit, [switch] $Metadata)
    $uri = [Uri] $Url
    $elapsed = [Diagnostics.Stopwatch]::StartNew()
    for ($redirects = 0; $redirects -le 5; $redirects++) {
        if ($uri.Scheme -cne 'https' -or $uri.Port -ne 443 -or
            $uri.UserInfo -or $uri.Fragment) {
            throw 'Release requests must use uncredentialed HTTPS.'
        }
        $hosts = @('github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com')
        if ($Metadata) { $hosts = @('api.github.com') }
        if ($uri.DnsSafeHost -cnotin $hosts) { throw 'Unofficial release download host.' }
        if ($elapsed.Elapsed.TotalSeconds -gt 120) { throw 'Release download timed out.' }
        $request = [Net.HttpWebRequest]::Create($uri)
        $request.AllowAutoRedirect = $false
        $request.Timeout = 120000
        $request.ReadWriteTimeout = 120000
        $request.UserAgent = 'awf-windows-bootstrap'
        $request.Accept = 'application/octet-stream'
        if ($Metadata) { $request.Accept = 'application/vnd.github+json' }
        $response = $null
        try {
            $response = $request.GetResponse()
            $status = [int] $response.StatusCode
            if ($status -in @(301, 302, 303, 307, 308)) {
                if ($Metadata -or $redirects -eq 5) { throw 'Unexpected release redirect.' }
                $location = $response.Headers['Location']
                if (-not $location) { throw 'Release redirect has no destination.' }
                $uri = New-Object Uri($uri, $location)
                continue
            }
            if ($status -ne 200) { throw "Official release returned HTTP $status." }
            if ($response.ContentLength -gt $Limit) { throw 'Release download exceeds allowed size.' }
            $input = $response.GetResponseStream()
            $output = $null
            try {
                $output = [IO.File]::Open($Destination, [IO.FileMode]::CreateNew,
                    [IO.FileAccess]::Write, [IO.FileShare]::None)
                $buffer = New-Object byte[] 65536
                [long] $total = 0
                while (($count = $input.Read($buffer, 0, $buffer.Length)) -gt 0) {
                    if ($elapsed.Elapsed.TotalSeconds -gt 120) { throw 'Release download timed out.' }
                    $total += $count
                    if ($total -gt $Limit) { throw 'Release download exceeds allowed size.' }
                    $output.Write($buffer, 0, $count)
                }
            } finally {
                if ($null -ne $output) { $output.Dispose() }
                $input.Dispose()
            }
            return
        } finally {
            if ($null -ne $response) { $response.Dispose() }
        }
    }
    throw 'Too many release redirects.'
}

function Get-AwfReleaseUrls($Release, [string] $Tag, [string] $Asset, [switch] $AllowPrerelease) {
    Assert-AwfReleaseVersion $Tag -AllowPrerelease:$AllowPrerelease
    $isPrerelease = $Tag.Contains('-rc.')
    if ($Release.tag_name -cne $Tag -or $Release.draft -isnot [bool] -or
        $Release.prerelease -isnot [bool] -or $Release.draft -or
        $Release.prerelease -ne $isPrerelease) {
        throw 'Official release must be the requested non-draft pinned tag with matching prerelease status.'
    }
    $wanted = @{}
    foreach ($name in @($Asset, 'SHA256SUMS')) {
        $matches = @($Release.assets | Where-Object { $_.name -ceq $name })
        $expected = "https://github.com/$script:Repository/releases/download/$Tag/$name"
        if ($matches.Count -ne 1 -or $matches[0].browser_download_url -cne $expected) {
            throw "Official release must contain exactly one matching $name asset at its exact release URL. No install assets are assumed to exist."
        }
        $wanted[$name] = $expected
    }
    return $wanted
}

function Get-AwfChecksum([string] $Text, [string] $Asset) {
    $found = $null
    $seen = @{}
    foreach ($line in ($Text -split '\r?\n')) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $match = [regex]::Match($line, '\A([0-9A-Fa-f]{64}) [ *]([^\s/\\]+)\z')
        if (-not $match.Success) { throw 'Malformed SHA256SUMS.' }
        $name = $match.Groups[2].Value
        if ($seen.ContainsKey($name)) { throw 'Duplicate filename in SHA256SUMS.' }
        $seen[$name] = $true
        if ($name -ceq $Asset) { $found = $match.Groups[1].Value.ToLowerInvariant() }
    }
    if ($null -eq $found) { throw 'SHA256SUMS has no checksum for this architecture.' }
    return $found
}

function Assert-AwfManifest([string] $Text, [string] $Tag, [string] $Architecture) {
    # A deliberately small schema. Escaped keys/values, duplicate keys, nested
    # objects, extra fields and coercible non-string values are not accepted.
    $pair = '"(?:version|os|arch)"\s*:\s*"[^"\\\x00-\x1F]*"'
    if ($Text -cnotmatch ('\A\s*\{\s*' + $pair + '\s*,\s*' + $pair + '\s*,\s*' + $pair + '\s*\}\s*\z')) {
        throw 'Invalid release manifest schema.'
    }
    $values = @{}
    foreach ($match in [regex]::Matches($Text, '"(version|os|arch)"\s*:\s*"([^"\\\x00-\x1F]*)"')) {
        $key = $match.Groups[1].Value
        if ($values.ContainsKey($key)) { throw 'Duplicate release manifest field.' }
        $values[$key] = $match.Groups[2].Value
    }
    if ($values.version -cne $Tag -or $values.os -cne 'windows' -or $values.arch -cne $Architecture) {
        throw 'Release manifest does not match the pinned version and native architecture.'
    }
}

function Assert-AwfNativeExecutable([string] $Path, [string] $Architecture) {
    $stream = [IO.File]::OpenRead($Path)
    $reader = New-Object IO.BinaryReader($stream)
    try {
        if ($stream.Length -lt 88 -or $reader.ReadUInt16() -ne 0x5A4D) {
            throw 'Release executable is not a Windows PE file.'
        }
        $stream.Position = 0x3C
        $offset = $reader.ReadUInt32()
        if ($offset -lt 64 -or $offset -gt ($stream.Length - 26)) { throw 'Invalid PE header offset.' }
        $stream.Position = $offset
        $machine = 0x8664
        if ($Architecture -ceq 'arm64') { $machine = 0xAA64 }
        if ($reader.ReadUInt32() -ne 0x4550 -or $reader.ReadUInt16() -ne $machine) {
            throw 'Release executable does not match the native Windows architecture.'
        }
        $stream.Position = $offset + 24
        if ($reader.ReadUInt16() -ne 0x20B) { throw 'Release executable must be a native 64-bit PE.' }
    } finally { $reader.Dispose() }
}

function Expand-AwfVerifiedArchive {
    param([string] $Archive, [string] $Destination, [string] $Tag, [string] $Architecture)
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        if ($zip.Entries.Count -ne 3) {
            throw 'Release ZIP must contain exactly awf.exe, awf-node.exe, and manifest.json.'
        }
        $expected = @('awf.exe', 'awf-node.exe', 'manifest.json')
        $seen = @{}
        [long] $total = 0
        # Validate all central-directory entries before writing any file. Exact
        # root filenames exclude traversal, ADS, alternate separators and folders.
        foreach ($entry in $zip.Entries) {
            $name = $entry.FullName
            [long] $attributes = ([long] $entry.ExternalAttributes) -band 0xFFFFFFFFL
            [long] $kind = $attributes -band 0xF0000000L
            if ($name -cnotin $expected -or $seen.ContainsKey($name) -or
                ($kind -ne 0 -and $kind -ne 0x80000000L) -or
                ($attributes -band 0x410) -ne 0) {
                throw 'Release ZIP contains an unexpected, duplicate, linked, or non-regular entry.'
            }
            $seen[$name] = $true
            $total += $entry.Length
            if ($entry.Length -le 0 -or $entry.Length -gt $script:MaxReleaseBytes -or
                $entry.CompressedLength -gt $script:MaxReleaseBytes -or
                $total -gt $script:MaxReleaseBytes -or
                ($name -ceq 'manifest.json' -and $entry.Length -gt 4096)) {
                throw 'Release ZIP contains an empty or oversized entry.'
            }
        }
        [void] [IO.Directory]::CreateDirectory($Destination)
        foreach ($entry in $zip.Entries) {
            $path = Join-Path $Destination $entry.FullName
            $input = $entry.Open()
            $output = $null
            try {
                $output = [IO.File]::Open($path, [IO.FileMode]::CreateNew,
                    [IO.FileAccess]::Write, [IO.FileShare]::None)
                $buffer = New-Object byte[] 65536
                [long] $written = 0
                while (($count = $input.Read($buffer, 0, $buffer.Length)) -gt 0) {
                    $written += $count
                    if ($written -gt $entry.Length) { throw 'ZIP entry exceeds its declared size.' }
                    $output.Write($buffer, 0, $count)
                }
                if ($written -ne $entry.Length) { throw 'ZIP entry is truncated.' }
            } finally {
                if ($null -ne $output) { $output.Dispose() }
                $input.Dispose()
            }
        }
    } finally { $zip.Dispose() }
    $utf8 = New-Object Text.UTF8Encoding($false, $true)
    $manifest = $utf8.GetString([IO.File]::ReadAllBytes((Join-Path $Destination 'manifest.json')))
    Assert-AwfManifest $manifest $Tag $Architecture
    Assert-AwfNativeExecutable (Join-Path $Destination 'awf.exe') $Architecture
    Assert-AwfNativeExecutable (Join-Path $Destination 'awf-node.exe') $Architecture
}

function Add-AwfUserPath([string] $Bin) {
    $old = [Environment]::GetEnvironmentVariable('Path', 'User')
    $present = $false
    foreach ($part in ($old -split ';')) {
        $expanded = [Environment]::ExpandEnvironmentVariables($part.Trim().Trim('"')).TrimEnd('\', '/')
        if ($expanded -ieq $Bin.TrimEnd('\', '/')) { $present = $true }
    }
    if (-not $present) {
        $new = $Bin
        if (-not [string]::IsNullOrWhiteSpace($old)) { $new = $old.TrimEnd(';') + ';' + $Bin }
        [Environment]::SetEnvironmentVariable('Path', $new, 'User')
    }
    # Make the same verified launcher usable immediately in this PowerShell
    # process; persistent user PATH above covers future shells.
    $process = [Environment]::GetEnvironmentVariable('Path', 'Process')
    $inProcess = $false
    foreach ($part in ($process -split ';')) {
        if ([Environment]::ExpandEnvironmentVariables($part.Trim().Trim('"')).TrimEnd('\', '/') -ieq $Bin.TrimEnd('\', '/')) { $inProcess = $true }
    }
    if (-not $inProcess) {
        $updated = $Bin
        if (-not [string]::IsNullOrWhiteSpace($process)) { $updated = $process.TrimEnd(';') + ';' + $Bin }
        [Environment]::SetEnvironmentVariable('Path', $updated, 'Process')
    }
}

function Invoke-AwfBootstrap {
    Assert-AwfReleaseVersion $Version -AllowPrerelease:$AllowPrerelease
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
        throw 'This bootstrap requires native Windows PowerShell 5.1 or PowerShell 7 on Windows.'
    }
    $architecture = Get-AwfNativeArchitecture
    $local = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
    if (-not $local -or -not [IO.Path]::IsPathRooted($local)) { throw 'Current-user LocalAppData is unavailable.' }
    if (-not $env:LOCALAPPDATA -or
        [IO.Path]::GetFullPath($env:LOCALAPPDATA).TrimEnd('\') -ine $local.TrimEnd('\')) {
        throw 'LOCALAPPDATA must match the current Windows user profile directory.'
    }
    $root = Join-Path $local 'AWF'
    foreach ($marker in @('current.json', 'config.json', 'bin\awf.exe')) {
        if (Test-Path -LiteralPath (Join-Path $root $marker)) {
            throw 'AWF already exists. Use awf update; an incomplete install requires explicit recovery.'
        }
    }
    $stage = New-AwfPrivateStage $local
    $oldTls = [Net.ServicePointManager]::SecurityProtocol
    try {
        # Session-only TLS minimum. Certificate validation remains enabled.
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $asset = "awf_${Version}_windows_${architecture}.zip"
        $metadataPath = Join-Path $stage 'release.json'
        Save-AwfOfficialDownload -Url "https://api.github.com/repos/$script:Repository/releases/tags/$Version" `
            -Destination $metadataPath -Limit 2MB -Metadata
        $release = [IO.File]::ReadAllText($metadataPath) | ConvertFrom-Json
        $urls = Get-AwfReleaseUrls $release $Version $asset -AllowPrerelease:$AllowPrerelease
        $sumsPath = Join-Path $stage 'SHA256SUMS'
        Save-AwfOfficialDownload -Url $urls['SHA256SUMS'] -Destination $sumsPath -Limit 1MB
        $digest = Get-AwfChecksum ([IO.File]::ReadAllText($sumsPath)) $asset
        if ($Sha256 -and $digest -ine $Sha256) { throw 'Release checksum differs from the independently pinned SHA-256.' }
        $archive = Join-Path $stage $asset
        Save-AwfOfficialDownload -Url $urls[$asset] -Destination $archive -Limit $script:MaxReleaseBytes
        $actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -cne $digest) { throw 'Release SHA-256 verification failed. No downloaded executable was run.' }
        $expanded = Join-Path $stage 'verified'
        Expand-AwfVerifiedArchive -Archive $archive -Destination $expanded -Tag $Version -Architecture $architecture
        $executable = Join-Path $expanded 'awf.exe'
        $installArguments = @('_install', '--archive', $archive, '--version', $Version, '--sha256', $digest)
        if ($AllowPrerelease) { $installArguments += '--allow-prerelease' }
        & $executable @installArguments
        if ($LASTEXITCODE -ne 0) { throw "Verified AWF installer failed (exit $LASTEXITCODE). User PATH was not changed." }
        try { Add-AwfUserPath (Join-Path $root 'bin') }
        catch {
            throw "AWF was installed, but user PATH could not be updated. Run '$root\bin\awf.exe' directly; do not rerun bootstrap. $($_.Exception.Message)"
        }
        Write-Host "Installed AWF $Version ($architecture). Run awf init to review configuration."
    } finally {
        [Net.ServicePointManager]::SecurityProtocol = $oldTls
        Remove-Item -LiteralPath $stage -Recurse -Force
    }
}

# Dot-sourcing only loads helpers for the native test suite; execution still has
# one fixed official repository and cannot accept an alternate download source.
if ($MyInvocation.InvocationName -ne '.') { Invoke-AwfBootstrap }
