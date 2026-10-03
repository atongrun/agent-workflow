#requires -Version 5.1
<#
.SYNOPSIS
Fresh-installs the published Go AWF release for the current Windows user.
.DESCRIPTION
Downloads only official GitHub release assets. The release ZIP is verified and
validated before its awf.exe is executed. This script does not start the runtime,
edit the firewall, pair credentials, run init, or change execution policy.
An existing AWF root is refused; this bootstrap never repairs or migrates it.
.PARAMETER Version
Optional exact stable or RC tag. Omit to use the official go-v1 channel.
.PARAMETER AllowPrerelease
Explicitly approve preview use for unattended installs; otherwise asks once.
.PARAMETER Sha256
Optional independently obtained SHA-256 for this architecture's release ZIP.
#>
[CmdletBinding()]
param(
    [string] $Version,
    [string] $Sha256,
    [switch] $AllowPrerelease
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:Repository = 'atongrun/agent-workflow'
$script:MaxReleaseBytes = 100MB
$script:ChannelUrl = 'https://raw.githubusercontent.com/atongrun/agent-workflow/awf/go-v1/distribution/go-v1.json'

function Assert-AwfArchivePin([string] $Digest) {
    # Optional parameter attributes are also variable validation under IEX;
    # an omitted string can be validated as empty before the script even starts.
    # Validate explicitly at the entrypoint instead, before any side effects.
    if ($Digest -and $Digest -cnotmatch '\A[0-9A-Fa-f]{64}\z') {
        throw 'Sha256 must be exactly 64 hexadecimal digits when supplied.'
    }
}

function Assert-AwfReleaseVersion([string] $Tag, [switch] $AllowPrerelease) {
    if ($Tag -cmatch '\Av(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\z') { return }
    if ($Tag -cmatch '\Av(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)-rc\.(?:0|[1-9][0-9]*)\z') {
        if (-not $AllowPrerelease) { throw 'Release candidate tags require -AllowPrerelease and an exact -Version.' }
        return
    }
    throw 'Version must be an exact tag vX.Y.Z or vX.Y.Z-rc.N without leading zeros.'
}

function Read-AwfChannelManifest([string] $Text) {
    # Flat, deliberately tiny JSON contract shared with the native updater.
    # Reject duplicate/unknown/escaped keys and coercions before JSON parsing.
    $keys = 'schema|channel|version|sourceCommit|cliProtocol|windowsAMD64SHA256|windowsARM64SHA256'
    $pair = '"(?:' + $keys + ')"[ \t\r\n]*:[ \t\r\n]*"[^"\\\x00-\x1F]*"'
    if ($Text.Length -gt 4096 -or
        $Text -cnotmatch ('\A[ \t\r\n]*\{[ \t\r\n]*' + $pair + '(?:[ \t\r\n]*,[ \t\r\n]*' + $pair + '){6}[ \t\r\n]*\}[ \t\r\n]*\z')) {
        throw 'Invalid Go channel manifest schema.'
    }
    $values = @{}
    foreach ($match in [regex]::Matches($Text, '"(' + $keys + ')"[ \t\r\n]*:[ \t\r\n]*"([^"\\\x00-\x1F]*)"')) {
        $key = $match.Groups[1].Value
        if ($values.ContainsKey($key)) { throw 'Duplicate Go channel manifest field.' }
        $values[$key] = $match.Groups[2].Value
    }
    if ($values.schema -cne '1' -or $values.channel -cne 'go-v1' -or
        $values.cliProtocol -cnotin @('1', '2', '3') -or
        $values.version -cnotmatch '\Av1\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-rc\.(?:0|[1-9][0-9]*))?\z' -or
        $values.sourceCommit -cnotmatch '\A[0-9a-f]{40}\z' -or
        $values.windowsAMD64SHA256 -cnotmatch '\A[0-9a-f]{64}\z' -or
        $values.windowsARM64SHA256 -cnotmatch '\A[0-9a-f]{64}\z') {
        throw 'Unsupported or invalid Go v1 channel metadata.'
    }
    return $values
}

function Assert-AwfFreshChannel($Channel) {
    if ($Channel.cliProtocol -cne '3') {
        throw 'The published Go channel does not yet provide the fresh-install CLI (protocol 3). Nothing was installed. Wait for the reviewed fresh-install release; this bootstrap does not install historical releases.'
    }
}

function Test-AwfInteractive {
    if (-not [Environment]::UserInteractive -or [Console]::IsInputRedirected) { return $false }
    foreach ($argument in [Environment]::GetCommandLineArgs()) {
        if ($argument -like '-NonI*') { return $false }
    }
    return $true
}

function New-AwfBootstrapProgress {
    # Progress is an observer only. Never use Write-Progress/Write-Host here:
    # their host streams can contaminate redirected output in PowerShell 5.1.
    $interactive = $false
    try {
        $interactive = $Host.Name -eq 'ConsoleHost' -and
            -not [Console]::IsErrorRedirected -and (Test-AwfInteractive)
    } catch { }
    return @{
        Interactive = $interactive; Disabled = $false; Stage = ''
        LineLength = 0; LastUpdateMs = -250
        Clock = [Diagnostics.Stopwatch]::StartNew()
    }
}

function Close-AwfBootstrapProgress($Progress) {
    if ($null -eq $Progress -or $Progress.Disabled) { return }
    try {
        if ($Progress.LineLength -gt 0) { [Console]::Error.WriteLine() }
        $Progress.LineLength = 0
    } catch { $Progress.Disabled = $true }
}

function Write-AwfBootstrapProgressLine($Progress, [string] $Text) {
    if ($null -eq $Progress -or $Progress.Disabled -or -not $Progress.Interactive) { return }
    try {
        # Plain CR works in both native Windows PowerShell 5.1 and PS7;
        # no ANSI support, console color, or additional module is required.
        $padding = [Math]::Max(0, $Progress.LineLength - $Text.Length)
        [Console]::Error.Write("`r" + $Text + (' ' * $padding))
        $Progress.LineLength = $Text.Length
    } catch {
        # A closed progress stream must not change install/security behavior.
        $Progress.Disabled = $true
    }
}

function Set-AwfBootstrapStage($Progress, [string] $Stage) {
    Close-AwfBootstrapProgress $Progress
    $Progress.Stage = $Stage
    $Progress.LastUpdateMs = -250
    Write-AwfBootstrapProgressLine $Progress ('AWF: ' + $Stage + '...')
}

function Write-AwfDownloadProgress($Progress, [long] $Received, [long] $Length, [switch] $Complete) {
    if ($null -eq $Progress -or $Progress.Disabled -or -not $Progress.Interactive) { return }
    $now = $Progress.Clock.ElapsedMilliseconds
    if (-not $Complete -and ($now - $Progress.LastUpdateMs) -lt 250) { return }
    $Progress.LastUpdateMs = $now
    $text = 'AWF: Downloading ' + $Received + ' bytes (total unknown)'
    if ($Length -gt 0) {
        # A final full-sized read is not EOF and may still fail on the next read
        # or file close. Reserve 100% for a successfully closed download.
        $ceiling = 99
        if ($Complete) { $ceiling = 100 }
        $percent = [Math]::Min($ceiling, [Math]::Floor(100.0 * $Received / $Length))
        $filled = [int] [Math]::Floor($percent / 5)
        $bar = '[' + ('#' * $filled) + ('-' * (20 - $filled)) + ']'
        $text = 'AWF: Downloading ' + $bar + ' ' + $Received + '/' + $Length + ' bytes (' + $percent + '%)'
    }
    Write-AwfBootstrapProgressLine $Progress $text
}

function Stop-AwfBootstrapProgress($Progress) {
    Close-AwfBootstrapProgress $Progress
    if ($null -eq $Progress -or $Progress.Disabled -or -not $Progress.Interactive -or -not $Progress.Stage) { return }
    # Report only a caller-owned stage label, never request URLs, redirect
    # tokens, exception details, or an unverified success/completion marker.
    try { [Console]::Error.WriteLine('AWF: Failed during ' + $Progress.Stage.ToLowerInvariant() + '.') }
    catch { $Progress.Disabled = $true }
}

function Confirm-AwfPreview([string] $Tag, [bool] $Approved, [bool] $Interactive) {
    Assert-AwfReleaseVersion $Tag -AllowPrerelease
    if (-not $Tag.Contains('-rc.')) { return $Approved }
    if ($Approved) { return $true }
    if (-not $Interactive) {
        throw 'The Go channel currently selects a preview. Run interactively to review it, or explicitly pass -AllowPrerelease for unattended installation.'
    }
    $question = "AWF $Tag is a preview release. Install it and allow preview updates in the Go v1 channel? [y/N]"
    $answer = Read-Host $question
    if ($answer -isnot [string] -or $answer -cnotmatch '\A(?i:y|yes)\z') { throw 'Preview installation cancelled. Nothing was installed.' }
    return $true
}

function Assert-AwfReleaseSource($Release, $TagRef, [string] $Tag, [string] $ExpectedCommit) {
    if ($Release -isnot [pscustomobject] -or $TagRef -isnot [pscustomobject] -or
        $TagRef.object -isnot [pscustomobject] -or $TagRef.ref -isnot [string] -or
        $TagRef.object.type -isnot [string] -or $TagRef.object.sha -isnot [string]) {
        throw 'Release source and tag metadata require scalar objects and strings.'
    }
    $commit = $Release.target_commitish
    if ($commit -isnot [string] -or $commit -cnotmatch '\A[0-9a-f]{40}\z' -or
        ($ExpectedCommit -and $commit -cne $ExpectedCommit) -or
        $TagRef.ref -cne ('refs/tags/' + $Tag) -or
        $TagRef.object.type -cne 'commit' -or $TagRef.object.sha -cne $commit) {
        throw 'Go channel, release source, and pinned tag commit do not agree.'
    }
}

function Assert-AwfChannelRelease($Channel, $Release, $TagRef) {
    Assert-AwfReleaseSource $Release $TagRef $Channel.version $Channel.sourceCommit
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

function Initialize-AwfInstallContextNative {
    if (-not ('AwfBootstrap.InstallContext' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;
namespace AwfBootstrap {
    public static class InstallContext {
        [DllImport("shell32.dll", ExactSpelling = true)]
        private static extern int SHGetKnownFolderPath(ref Guid folder, uint flags,
            IntPtr token, out IntPtr path);
        [DllImport("kernel32.dll", ExactSpelling = true)]
        private static extern int GetCurrentPackageFullName(ref uint length, IntPtr name);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true, SetLastError = true)]
        private static extern SafeFileHandle CreateFileW(string path, uint access,
            uint share, IntPtr security, uint disposition, uint flags, IntPtr template);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true, SetLastError = true)]
        private static extern uint GetFinalPathNameByHandleW(SafeFileHandle handle,
            StringBuilder path, uint capacity, uint flags);
        public static int PackageIdentityStatus() {
            uint length = 0;
            // Query only: no package-name buffer or caller-controlled identity.
            return GetCurrentPackageFullName(ref length, IntPtr.Zero);
        }
        public static string UserProgramFiles() {
            Guid folder = new Guid("5CD7AEE2-2219-4A67-B85D-6C9CE15660CB");
            IntPtr path = IntPtr.Zero;
            try {
                // FOLDERID_UserProgramFiles, current user. KF_FLAG_DONT_VERIFY
                // permits an absent Programs directory; never use KF_FLAG_CREATE.
                int result = SHGetKnownFolderPath(ref folder, 0x00004000,
                    IntPtr.Zero, out path);
                if (result < 0) Marshal.ThrowExceptionForHR(result);
                return Marshal.PtrToStringUni(path);
            } finally {
                if (path != IntPtr.Zero) Marshal.FreeCoTaskMem(path);
            }
        }
        public static string FinalPath(string path) {
            // OPEN_EXISTING and zero access: never creates or changes a file.
            // BACKUP_SEMANTICS permits directory handles; no backup privilege is enabled.
            using (SafeFileHandle handle = CreateFileW(path, 0, 7, IntPtr.Zero,
                    3, 0x02000000, IntPtr.Zero)) {
                if (handle.IsInvalid) throw new Win32Exception(Marshal.GetLastWin32Error());
                uint capacity = 512;
                while (capacity <= 32768) {
                    StringBuilder result = new StringBuilder((int)capacity);
                    // FILE_NAME_NORMALIZED | VOLUME_NAME_DOS, not FILE_NAME_OPENED.
                    uint length = GetFinalPathNameByHandleW(handle, result, capacity, 0);
                    if (length == 0) throw new Win32Exception(Marshal.GetLastWin32Error());
                    if (length < capacity) return result.ToString();
                    if (length >= 32768) break;
                    capacity = length + 1;
                }
                throw new InvalidOperationException("Resolved installation path is too long.");
            }
        }
    }
}
'@
    }
}

function Get-AwfPackageIdentityStatus {
    Initialize-AwfInstallContextNative
    return [AwfBootstrap.InstallContext]::PackageIdentityStatus()
}

function Get-AwfUserProgramFiles {
    Initialize-AwfInstallContextNative
    try {
        $path = [AwfBootstrap.InstallContext]::UserProgramFiles()
        return ConvertTo-AwfCanonicalWindowsPath $path
    } catch {
        throw 'Current-user Programs known folder is unavailable or invalid. No fallback installation path is supported.'
    }
}

function Assert-AwfUnpackagedProcess {
    try { $status = Get-AwfPackageIdentityStatus }
    catch { throw 'Unable to verify the Windows installation context. Open a normal Windows PowerShell directly from Windows and run the installer there.' }
    # Only APPMODEL_ERROR_NO_PACKAGE permits installation. Success or a required
    # name-buffer size identifies a package; every other result fails closed.
    if ($status -eq 15700) { return }
    if ($status -eq 0 -or $status -eq 122) {
        throw 'This terminal is running inside a packaged app that may redirect installation files. Open a normal Windows PowerShell directly from Windows and run the installer there.'
    }
    throw "Unable to verify the Windows installation context (Windows error $status). Open a normal Windows PowerShell directly from Windows and run the installer there."
}

function ConvertTo-AwfCanonicalWindowsPath([string] $Path) {
    # Compare lexical intended paths with handle-resolved paths. Resolving both
    # through the filesystem would hide the redirection being detected.
    if ([string]::IsNullOrWhiteSpace($Path)) { throw 'Installation path is empty.' }
    $pathValue = $Path.Replace('/', '\')
    if ($pathValue.StartsWith('\\?\UNC\', [StringComparison]::OrdinalIgnoreCase)) {
        $pathValue = '\\' + $pathValue.Substring(8)
    } elseif ($pathValue.StartsWith('\\?\', [StringComparison]::Ordinal)) {
        $pathValue = $pathValue.Substring(4)
    }
    $drive = $pathValue -cmatch '\A[A-Za-z]:\\'
    if ($drive) {
        $rootPart = $pathValue.Substring(0, 3)
        $parts = @($pathValue.Substring(3) -split '\\')
        $toValidate = $parts
    } else {
        if (-not $pathValue.StartsWith('\\', [StringComparison]::Ordinal)) {
            throw 'Installation path must be an absolute Windows drive or UNC path.'
        }
        $unc = @($pathValue.Substring(2) -split '\\')
        if ($unc.Count -lt 2 -or -not $unc[0] -or -not $unc[1] -or
            $unc[0] -cin @('.', '..') -or $unc[1] -cin @('.', '..')) {
            throw 'Installation path must have an explicit UNC server and share.'
        }
        $rootPart = '\\' + $unc[0] + '\' + $unc[1] + '\'
        $toValidate = $unc
        $parts = @()
        if ($unc.Count -gt 2) { $parts = @($unc[2..($unc.Count - 1)]) }
    }
    foreach ($part in $toValidate) {
        if ($part -and $part -cnotin @('.', '..') -and
            ($part.EndsWith('.') -or $part.EndsWith(' ') -or
                $part.IndexOfAny([char[]] '\"<>|:*?') -ge 0 -or $part -match '[\x00-\x1f]')) {
            throw 'Installation path contains an ambiguous Windows component.'
        }
    }
    # Deliberately lexical: .NET Framework GetFullPath may expand short names
    # through filesystem queries. Never resolve the intended path that way.
    $segments = New-Object 'System.Collections.Generic.List[string]'
    foreach ($part in $parts) {
        if (-not $part -or $part -ceq '.') { continue }
        if ($part -ceq '..') {
            if ($segments.Count -gt 0) { $segments.RemoveAt($segments.Count - 1) }
        } else { $segments.Add($part) }
    }
    $full = $rootPart + [string]::Join('\', $segments.ToArray())
    if ($segments.Count -eq 0 -and $drive) { return $full }
    return $full.TrimEnd('\')
}

function Get-AwfFinalPath([string] $Path) {
    Initialize-AwfInstallContextNative
    return [AwfBootstrap.InstallContext]::FinalPath($Path)
}

function Assert-AwfNativePath([string] $Path) {
    $expected = ConvertTo-AwfCanonicalWindowsPath $Path
    try { $actual = ConvertTo-AwfCanonicalWindowsPath (Get-AwfFinalPath $Path) }
    catch { throw 'Unable to verify the physical installation path. Installation stopped; this shell PATH was not changed.' }
    if (-not [string]::Equals($expected, $actual, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Windows redirected an installation path away from the intended user profile. Installation stopped; this shell PATH was not changed. Open a normal Windows PowerShell directly from Windows. Do not rerun bootstrap over a partial installation; review it first.'
    }
}

function Assert-AwfDirectoryPath([string] $Path) {
    $item = Get-Item -LiteralPath $Path -Force
    while ($null -ne $item) {
        # Parent returns a plain DirectoryInfo without the PowerShell provider's
        # PSIsContainer property. Check the actual type at every ancestor.
        if ($item -isnot [IO.DirectoryInfo] -or
            ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Bootstrap directories must be real directories, not reparse points.'
        }
        $item = $item.Parent
    }
}

function Assert-AwfProgramsPath([string] $Programs) {
    # Read-only planning, even on a profile where Programs has never existed.
    # Check Programs or its existing direct parent without changing anything.
    # Native installation revalidates and owns creation after install consent.
    $current = ConvertTo-AwfCanonicalWindowsPath $Programs
    try { $null = Get-Item -LiteralPath $current -Force -ErrorAction Stop }
    catch [Management.Automation.ItemNotFoundException] {
        $parent = [IO.Path]::GetDirectoryName($current)
        if (-not $parent -or $parent -ceq $current) {
            throw 'Current-user Programs has no accessible existing parent.'
        }
        $current = $parent
        try { $null = Get-Item -LiteralPath $current -Force -ErrorAction Stop }
        catch { throw 'Current-user Programs requires an accessible existing direct parent.' }
    }
    catch { throw 'Current-user Programs path state could not be verified.' }
    Assert-AwfDirectoryPath $current
    Assert-AwfNativePath $current
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
        Assert-AwfNativePath $path
        return $directory.FullName
    } catch {
        [IO.Directory]::Delete($directory.FullName)
        throw
    }
}

function Save-AwfOfficialDownload {
    param([string] $Url, [string] $Destination, [long] $Limit, [switch] $Metadata, [switch] $Channel,
        $Progress = $null)
    $uri = [Uri] $Url
    if ($Channel -and $Url -cne $script:ChannelUrl) { throw 'Unexpected Go channel URL.' }
    if ($Metadata -and $Channel) { throw 'Ambiguous metadata request.' }
    $elapsed = [Diagnostics.Stopwatch]::StartNew()
    for ($redirects = 0; $redirects -le 5; $redirects++) {
        if ($uri.Scheme -cne 'https' -or $uri.Port -ne 443 -or
            $uri.UserInfo -or $uri.Fragment) {
            throw 'Release requests must use uncredentialed HTTPS.'
        }
        $hosts = @('github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com')
        if ($Metadata) { $hosts = @('api.github.com') }
        if ($Channel) { $hosts = @('raw.githubusercontent.com') }
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
                if ($Metadata -or $Channel -or $redirects -eq 5) { throw 'Unexpected release redirect.' }
                $location = $response.Headers['Location']
                if (-not $location) { throw 'Release redirect has no destination.' }
                $uri = New-Object Uri($uri, $location)
                continue
            }
            if ($status -ne 200) { throw "Official release returned HTTP $status." }
            if ($response.ContentLength -gt $Limit) { throw 'Release download exceeds allowed size.' }
            [long] $length = $response.ContentLength
            $input = $response.GetResponseStream()
            $output = $null
            try {
                $output = [IO.File]::Open($Destination, [IO.FileMode]::CreateNew,
                    [IO.FileAccess]::Write, [IO.FileShare]::None)
                $buffer = New-Object byte[] 65536
                [long] $total = 0
                Write-AwfDownloadProgress $Progress $total $length
                while (($count = $input.Read($buffer, 0, $buffer.Length)) -gt 0) {
                    if ($elapsed.Elapsed.TotalSeconds -gt 120) { throw 'Release download timed out.' }
                    $total += $count
                    if ($total -gt $Limit) { throw 'Release download exceeds allowed size.' }
                    $output.Write($buffer, 0, $count)
                    Write-AwfDownloadProgress $Progress $total $length
                }
            } finally {
                if ($null -ne $output) { $output.Dispose() }
                $input.Dispose()
            }
        } finally {
            if ($null -ne $response) { $response.Dispose() }
        }
        Write-AwfDownloadProgress $Progress $total $length -Complete
        return
    }
    throw 'Too many release redirects.'
}

function Get-AwfReleaseUrls($Release, [string] $Tag, [string] $Asset, [switch] $AllowPrerelease) {
    Assert-AwfReleaseVersion $Tag -AllowPrerelease:$AllowPrerelease
    $isPrerelease = $Tag.Contains('-rc.')
    if ($Release -isnot [pscustomobject] -or $Release.tag_name -isnot [string] -or
        $Release.assets -isnot [Array]) { throw 'Invalid official release metadata shape.' }
    if ($Release.tag_name -cne $Tag -or $Release.draft -isnot [bool] -or
        $Release.prerelease -isnot [bool] -or $Release.draft -or
        $Release.prerelease -ne $isPrerelease) {
        throw 'Official release must be the requested non-draft pinned tag with matching prerelease status.'
    }
    foreach ($item in $Release.assets) {
        if ($item -isnot [pscustomobject] -or $item.name -isnot [string] -or
            $item.browser_download_url -isnot [string]) { throw 'Invalid official release asset shape.' }
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

function Move-AwfPathEntryFirst([string] $Path, [string] $Bin) {
    # Text transformation only. Remove only entries that normalize to this exact
    # AWF bin; preserve every other entry (including its spelling) and its order.
    $wanted = ConvertTo-AwfCanonicalWindowsPath $Bin
    if (-not $Path) { return $wanted }
    $remaining = New-Object 'System.Collections.Generic.List[string]'
    foreach ($part in ($Path -split ';')) {
        $entry = $part.Trim()
        if ($entry.Length -ge 2 -and $entry.StartsWith('"') -and $entry.EndsWith('"')) {
            $entry = $entry.Substring(1, $entry.Length - 2)
        }
        $matches = $false
        try {
            $normalized = ConvertTo-AwfCanonicalWindowsPath ([Environment]::ExpandEnvironmentVariables($entry))
            $matches = [string]::Equals($wanted, $normalized, [StringComparison]::OrdinalIgnoreCase)
        } catch {
            # Empty, relative, or unusual existing entries are retained verbatim.
            # This installer is not a general PATH repair or cleanup tool.
        }
        if (-not $matches) { $remaining.Add($part) }
    }
    if ($remaining.Count -eq 0) { return $wanted }
    return $wanted + ';' + [string]::Join(';', $remaining.ToArray())
}

function Add-AwfProcessPath([string] $Bin) {
    # The native installer owns persistent user PATH registration. Refresh only
    # this PowerShell process after verifying the completed installation.
    $process = [Environment]::GetEnvironmentVariable('Path', 'Process')
    $updated = Move-AwfPathEntryFirst $process $Bin
    if ($updated -cne $process) { [Environment]::SetEnvironmentVariable('Path', $updated, 'Process') }
}

function Warn-AwfCommandShadowing([string] $Launcher) {
    # Function-local preference: exact-name command lookup must not auto-import
    # a module and execute its initialization merely to produce a warning.
    $PSModuleAutoLoadingPreference = 'None'
    $command = Get-Command -Name 'awf' -ErrorAction SilentlyContinue
    if ($null -ne $command -and $command.CommandType -eq [Management.Automation.CommandTypes]::Application) {
        try {
            $actual = ConvertTo-AwfCanonicalWindowsPath $command.Path
            $expected = ConvertTo-AwfCanonicalWindowsPath $Launcher
            if ([string]::Equals($actual, $expected, [StringComparison]::OrdinalIgnoreCase)) { return }
        } catch { }
    }
    # Read command resolution only. Never remove or overwrite aliases/functions
    # or other executables, and never rewrite machine PATH to win precedence.
    Write-Warning "This shell still does not resolve 'awf' to the installed launcher. Run '$Launcher' directly and review any alias, function, or earlier machine PATH entry."
}

function Assert-AwfFreshRoot([string] $Root) {
    try { $null = Get-Item -LiteralPath $Root -Force -ErrorAction Stop }
    catch [Management.Automation.ItemNotFoundException] { return }
    catch { throw 'AWF root state could not be verified. No installation was attempted.' }
    throw 'AWF root already exists, including empty, partial, or credentials-only roots. Fresh install does not migrate, adopt, repair, or overwrite it. Use awf update for a healthy installation; otherwise review it explicitly.'
}

function Confirm-AwfInstalledLauncher([string] $Root) {
    $launcher = Join-Path $Root 'bin\awf.exe'
    Assert-AwfDirectoryPath (Join-Path $Root 'bin')
    $installed = Get-Item -LiteralPath $launcher -Force
    if ($installed -isnot [IO.FileInfo] -or ($installed.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Installed launcher must be a regular file, not a reparse point. Process PATH was not changed.'
    }
    Assert-AwfNativePath $launcher
    try { Add-AwfProcessPath (Join-Path $Root 'bin') }
    catch {
        throw "AWF was installed, but this shell's PATH could not be refreshed. Run '$launcher' directly; do not rerun bootstrap. $($_.Exception.Message)"
    }
}

function Invoke-AwfBootstrap {
    Assert-AwfArchivePin $Sha256
    if ($Version) { Assert-AwfReleaseVersion $Version -AllowPrerelease }
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
    Assert-AwfUnpackagedProcess
    # LocalAppData above is only the private download-stage parent. The sole
    # installation destination is the actual Windows per-user Programs folder.
    $programs = Get-AwfUserProgramFiles
    Assert-AwfProgramsPath $programs
    $root = Join-Path $programs 'AWF'
    Assert-AwfFreshRoot $root
    $stage = New-AwfPrivateStage $local
    $oldTls = [Net.ServicePointManager]::SecurityProtocol
    $progress = New-AwfBootstrapProgress
    try {
        Set-AwfBootstrapStage $progress 'Downloading release metadata'
        # Session-only TLS minimum. Certificate validation remains enabled.
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $channel = $null
        if (-not $Version) {
            $channelPath = Join-Path $stage 'go-channel.json'
            Save-AwfOfficialDownload -Url $script:ChannelUrl -Destination $channelPath -Limit 4096 -Channel
            $utf8 = New-Object Text.UTF8Encoding($false, $true)
            $channel = Read-AwfChannelManifest ($utf8.GetString([IO.File]::ReadAllBytes($channelPath)))
            Assert-AwfFreshChannel $channel
            $Version = $channel.version
        }
        # A preview prompt may write to the same console. Do not leave an
        # unfinished redraw line in front of it.
        Close-AwfBootstrapProgress $progress
        $AllowPrerelease = Confirm-AwfPreview $Version ([bool] $AllowPrerelease) (Test-AwfInteractive)
        $asset = "awf_${Version}_windows_${architecture}.zip"
        $metadataPath = Join-Path $stage 'release.json'
        Save-AwfOfficialDownload -Url "https://api.github.com/repos/$script:Repository/releases/tags/$Version" `
            -Destination $metadataPath -Limit 2MB -Metadata
        $release = [IO.File]::ReadAllText($metadataPath) | ConvertFrom-Json
        $urls = Get-AwfReleaseUrls $release $Version $asset -AllowPrerelease:$AllowPrerelease
        $tagPath = Join-Path $stage 'tag.json'
        Save-AwfOfficialDownload -Url "https://api.github.com/repos/$script:Repository/git/ref/tags/$Version" `
            -Destination $tagPath -Limit 64KB -Metadata
        $tagRef = [IO.File]::ReadAllText($tagPath) | ConvertFrom-Json
        $channelDigest = ''
        if ($null -ne $channel) {
            Assert-AwfChannelRelease $channel $release $tagRef
            $channelDigest = $channel.windowsAMD64SHA256
            if ($architecture -ceq 'arm64') { $channelDigest = $channel.windowsARM64SHA256 }
        } else { Assert-AwfReleaseSource $release $tagRef $Version '' }
        $sumsPath = Join-Path $stage 'SHA256SUMS'
        Save-AwfOfficialDownload -Url $urls['SHA256SUMS'] -Destination $sumsPath -Limit 1MB
        $digest = Get-AwfChecksum ([IO.File]::ReadAllText($sumsPath)) $asset
        if ($channelDigest -and $digest -cne $channelDigest) { throw 'Release checksum differs from the Go channel SHA-256.' }
        if ($Sha256 -and $digest -ine $Sha256) { throw 'Release checksum differs from the independently pinned SHA-256.' }
        $archive = Join-Path $stage $asset
        Set-AwfBootstrapStage $progress 'Downloading release archive'
        Save-AwfOfficialDownload -Url $urls[$asset] -Destination $archive -Limit $script:MaxReleaseBytes -Progress $progress
        Set-AwfBootstrapStage $progress 'Verifying release archive'
        $actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -cne $digest) { throw 'Release SHA-256 verification failed. No downloaded executable was run.' }
        $expanded = Join-Path $stage 'verified'
        Set-AwfBootstrapStage $progress 'Extracting bootstrap'
        Expand-AwfVerifiedArchive -Archive $archive -Destination $expanded -Tag $Version -Architecture $architecture
        $executable = Join-Path $expanded 'awf.exe'
        Set-AwfBootstrapStage $progress 'Launching installer'
        # Finish the bootstrap line before native stderr writes. The native
        # installer owns all subsequent verify/extract/install/PATH progress.
        Close-AwfBootstrapProgress $progress
        # Exact-version pins bypass channel selection, so verify the public
        # fresh-install capability on every downloaded executable as well.
        $protocol = @(& $executable install-protocol)
        if ($LASTEXITCODE -ne 0 -or $protocol.Count -ne 1 -or $protocol[0] -cne '3') {
            throw 'This verified release does not support fresh installation (protocol 3). No AWF installation was attempted; historical installers are not supported.'
        }
        $installArguments = @('install', '--yes', '--archive', $archive, '--version', $Version, '--sha256', $digest)
        if ($AllowPrerelease) { $installArguments += '--allow-prerelease' }
        $installArguments += @('--channel', 'go-v1')
        # The native installer owns root creation, final ACLs, channel state and
        # persistent user PATH. Report success only after physical verification.
        $null = & $executable @installArguments
        if ($LASTEXITCODE -ne 0) { throw "Verified AWF fresh installer failed (exit $LASTEXITCODE). If an AWF root was created, inspect it; do not rerun bootstrap or change its ACLs." }
        $launcher = Join-Path $root 'bin\awf.exe'
        Set-AwfBootstrapStage $progress 'Checking installed launcher and refreshing shell PATH'
        Confirm-AwfInstalledLauncher $root
        Close-AwfBootstrapProgress $progress
        Warn-AwfCommandShadowing $launcher
        Write-Host "Installed AWF $Version ($architecture)."
        Write-Host 'Next, run awf init to review configuration and optional pairing.'
        Write-Host 'Use awf start and awf stop when ready; use awf update for future releases.'
        Write-Host 'A child PowerShell cannot refresh its parent terminal. Open a new terminal if awf is not found.'
    } catch {
        Stop-AwfBootstrapProgress $progress
        throw
    } finally {
        Close-AwfBootstrapProgress $progress
        [Net.ServicePointManager]::SecurityProtocol = $oldTls
        Remove-Item -LiteralPath $stage -Recurse -Force
    }
}

# Dot-sourcing only loads helpers for the native test suite; execution still has
# one fixed official repository and cannot accept an alternate download source.
if ($MyInvocation.InvocationName -ne '.') { Invoke-AwfBootstrap }
