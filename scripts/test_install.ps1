#requires -Version 5.1
# Native Windows tests. No downloads, installs, PATH, registry, firewall, or
# credential changes. Fixture bytes are never executed. No Pester dependency.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'install.ps1') -Version 'v1.2.3'
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Assert-True([bool] $Condition, [string] $Message) {
    if (-not $Condition) { throw "TEST FAILED: $Message" }
}
function Assert-Rejected([scriptblock] $Action, [string] $Message, [string] $ExpectedError = '') {
    $rejected = $false
    try { & $Action } catch {
        $rejected = $true
        if ($ExpectedError) {
            Assert-True ($_.Exception.Message -like $ExpectedError) "$Message (unexpected error: $($_.Exception.Message))"
        }
    }
    Assert-True $rejected $Message
}
function New-TestPE([string] $Architecture) {
    $bytes = New-Object byte[] 256
    $bytes[0] = 0x4D; $bytes[1] = 0x5A; $bytes[0x3C] = 128
    $bytes[128] = 0x50; $bytes[129] = 0x45
    if ($Architecture -ceq 'amd64') { $bytes[132] = 0x64; $bytes[133] = 0x86 }
    else { $bytes[132] = 0x64; $bytes[133] = 0xAA }
    $bytes[152] = 0x0B; $bytes[153] = 0x02
    return ,$bytes
}
function New-TestZip([string] $Path, [object[]] $Entries) {
    $stream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew)
    $zip = New-Object IO.Compression.ZipArchive($stream, [IO.Compression.ZipArchiveMode]::Create)
    try {
        foreach ($fixture in $Entries) {
            $entry = $zip.CreateEntry($fixture.Name)
            $entry.ExternalAttributes = $fixture.Attributes
            $writer = $entry.Open()
            try { $writer.Write($fixture.Bytes, 0, $fixture.Bytes.Length) }
            finally { $writer.Dispose() }
        }
    } finally { $zip.Dispose(); $stream.Dispose() }
}
function New-Fixture([string] $Name, [byte[]] $Bytes, [int] $Attributes = 0) {
    return [pscustomobject] @{ Name = $Name; Bytes = $Bytes; Attributes = $Attributes }
}

$temporary = Join-Path ([IO.Path]::GetTempPath()) ('awf-bootstrap-test-' + [Guid]::NewGuid().ToString('N'))
[void] [IO.Directory]::CreateDirectory($temporary)
try {
    # Use real filesystem objects: DirectoryInfo.Parent does not carry the
    # provider-added PSIsContainer property that Get-Item supplies initially.
    # StrictMode must remain enabled while walking all the way to the root.
    $nested = Join-Path $temporary 'directory-chain\one\two'
    [void] [IO.Directory]::CreateDirectory($nested)
    Assert-AwfDirectoryPath $nested
    Assert-AwfDirectoryPath $temporary
    Assert-AwfDirectoryPath ([IO.Path]::GetPathRoot($temporary))
    $missing = Join-Path $nested 'missing\child'
    Assert-Rejected { Assert-AwfDirectoryPath $missing } 'missing nested directory is rejected'
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $nested 'missing'))) 'directory validation does not create missing paths'
    $regularFile = Join-Path $nested 'regular-file'
    [IO.File]::WriteAllText($regularFile, 'fixture')
    Assert-Rejected { Assert-AwfDirectoryPath $regularFile } 'regular file is not a directory' 'Bootstrap directories must be real directories*'
    $stage = New-AwfPrivateStage $nested
    try {
        Assert-True ([IO.Directory]::Exists($stage)) 'private bootstrap stage is created under a real nested parent'
        Assert-AwfDirectoryPath $stage
    } finally { [IO.Directory]::Delete($stage) }
    if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
        # Junctions need no symlink privilege and exercise a real reparse point
        # both as the supplied directory and as a plain DirectoryInfo ancestor.
        $target = Join-Path $temporary 'junction-target'
        [void] [IO.Directory]::CreateDirectory((Join-Path $target 'child\leaf'))
        $sentinel = Join-Path $target 'sentinel'
        [IO.File]::WriteAllText($sentinel, 'preserve')
        $junction = Join-Path $temporary 'junction'
        [void] (New-Item -ItemType Junction -Path $junction -Target $target)
        try {
            Assert-True (([IO.File]::GetAttributes($junction) -band [IO.FileAttributes]::ReparsePoint) -ne 0) 'fixture is an actual reparse point'
            Assert-Rejected { Assert-AwfDirectoryPath $junction } 'junction directory rejected' 'Bootstrap directories must be real directories*'
            Assert-Rejected { Assert-AwfDirectoryPath (Join-Path $junction 'child\leaf') } 'junction ancestor rejected' 'Bootstrap directories must be real directories*'
            Assert-Rejected { New-AwfPrivateStage (Join-Path $junction 'child\leaf') } 'staging through a junction ancestor rejected' 'Bootstrap directories must be real directories*'
            Assert-True ((@(Get-ChildItem -LiteralPath (Join-Path $target 'child\leaf') -Force)).Count -eq 0) 'rejected staging leaves target unchanged'
        } finally {
            # Remove the link itself, never recursively traverse its target.
            [IO.Directory]::Delete($junction)
        }
        Assert-True ([IO.File]::ReadAllText($sentinel) -ceq 'preserve') 'junction cleanup preserves target'
    }
    Write-Host 'Real directory, root, missing-path, file, private-stage, and junction-ancestor tests passed.'

    foreach ($tag in @('v0.0.0', 'v1.2.3', 'v123.456.789')) {
        Assert-AwfReleaseVersion $tag
        Assert-AwfReleaseVersion $tag -AllowPrerelease
    }
    foreach ($tag in @('v0.0.0-rc.0', 'v0.0.0-rc.1', 'v12.34.56-rc.789')) {
        Assert-Rejected { Assert-AwfReleaseVersion $tag } 'RC requires opt-in' 'Release candidate tags require*'
        Assert-AwfReleaseVersion $tag -AllowPrerelease
    }
    foreach ($tag in @('', 'latest', '1.2.3', 'v1.2', 'v01.2.3', 'V1.2.3', 'v1.2.3-RC.1',
        'v1.2.3-rc', 'v1.2.3-rc.01', 'v1.2.3-rc.-1', 'v01.2.3-rc.1', 'v1.02.3-rc.1',
        'v1.2.03-rc.1', 'v1.2.3-rc.1.2', 'v1.2.3-beta.1', 'v1.2.3-rc.1+build',
        'v1.2.3+build', "v1.2.3-rc.1`n", '../v1.2.3-rc.1', ('v1.2.3-rc.' + [char]0x0661))) {
        Assert-Rejected { Assert-AwfReleaseVersion $tag } 'noncanonical tag' 'Version must be an exact tag*'
        Assert-Rejected { Assert-AwfReleaseVersion $tag -AllowPrerelease } 'opt-in does not relax tag grammar' 'Version must be an exact tag*'
    }
    # Explicit pins and channel previews both require consent. The helper is
    # called before release assets or downloaded code are reached.
    Assert-Rejected { Confirm-AwfPreview 'v0.0.0-rc.1' $false $false } `
        'noninteractive RC without opt-in' 'The Go channel currently selects a preview*'

    $asset = 'awf_v1.2.3_windows_amd64.zip'
    $digest = 'a' * 64
    Assert-True ((Get-AwfChecksum "$digest  $asset`n" $asset) -ceq $digest) 'GNU checksum'
    Assert-True ((Get-AwfChecksum "$digest *$asset`n" $asset) -ceq $digest) 'binary checksum'
    foreach ($bad in @("abc  $asset", "$digest  other.zip", "$digest  ../$asset", "$digest  $asset`n$digest  $asset")) {
        Assert-Rejected { Get-AwfChecksum $bad $asset } 'bad or duplicate checksum'
    }
    $manifest = '{"version":"v1.2.3","os":"windows","arch":"amd64"}'
    Assert-AwfManifest $manifest 'v1.2.3' 'amd64'
    foreach ($bad in @(
        '{"version":"v1.2.3","os":"windows","arch":"arm64"}',
        '{"version":"v9.9.9","os":"windows","arch":"amd64"}',
        '{"version":"v1.2.3","version":"v1.2.3","arch":"amd64"}',
        '{"version":"v1.2.3","os":"windows","arch":"amd64","extra":true}',
        '{"version":"v1.2.3","os":"windows","arch":64}',
        '{"version":"v1.2.3","os":"windows","arch":"AMD64"}'
    )) { Assert-Rejected { Assert-AwfManifest $bad 'v1.2.3' 'amd64' } 'manifest mismatch/schema' }
    $release = [pscustomobject] @{
        tag_name = 'v1.2.3'; draft = $false; prerelease = $false
        assets = @(
            [pscustomobject] @{ name = $asset; browser_download_url = "https://github.com/atongrun/agent-workflow/releases/download/v1.2.3/$asset" },
            [pscustomobject] @{ name = 'SHA256SUMS'; browser_download_url = 'https://github.com/atongrun/agent-workflow/releases/download/v1.2.3/SHA256SUMS' }
        )
    }
    [void] (Get-AwfReleaseUrls $release 'v1.2.3' $asset)
    [void] (Get-AwfReleaseUrls $release 'v1.2.3' $asset -AllowPrerelease)
    foreach ($field in @('tag_name', 'assets')) {
        $original = $release.$field
        $release.$field = [pscustomobject] @{}
        Assert-Rejected { Get-AwfReleaseUrls $release 'v1.2.3' $asset } 'malformed release field shape'
        $release.$field = $original
    }
    foreach ($field in @('name', 'browser_download_url')) {
        $original = $release.assets[0].$field
        $release.assets[0].$field = @($original)
        Assert-Rejected { Get-AwfReleaseUrls $release 'v1.2.3' $asset } 'asset values cannot be arrays'
        $release.assets[0].$field = $original
    }
    $release.prerelease = $true
    Assert-Rejected { Get-AwfReleaseUrls $release 'v1.2.3' $asset } 'stable tag rejects prerelease metadata'
    Assert-Rejected { Get-AwfReleaseUrls $release 'v1.2.3' $asset -AllowPrerelease } 'stable tag still rejects prerelease metadata with opt-in'
    $release.prerelease = $false
    $release.draft = $true
    Assert-Rejected { Get-AwfReleaseUrls $release 'v1.2.3' $asset -AllowPrerelease } 'draft stable release'
    $release.draft = $false
    $release.assets[0].browser_download_url = 'https://example.invalid/download.zip'
    Assert-Rejected { Get-AwfReleaseUrls $release 'v1.2.3' $asset } 'unofficial URL'
    $release.assets[0].browser_download_url = "https://github.com/atongrun/agent-workflow/releases/download/v1.2.3/$asset"
    $release.assets += $release.assets[0]
    Assert-Rejected { Get-AwfReleaseUrls $release 'v1.2.3' $asset } 'duplicate release asset'

    $rcTag = 'v0.0.0-rc.1'
    $rcAsset = "awf_${rcTag}_windows_amd64.zip"
    $rcRelease = [pscustomobject] @{
        tag_name = $rcTag; draft = $false; prerelease = $true
        assets = @(
            [pscustomobject] @{ name = $rcAsset; browser_download_url = "https://github.com/atongrun/agent-workflow/releases/download/$rcTag/$rcAsset" },
            [pscustomobject] @{ name = 'SHA256SUMS'; browser_download_url = "https://github.com/atongrun/agent-workflow/releases/download/$rcTag/SHA256SUMS" }
        )
    }
    Assert-Rejected { Get-AwfReleaseUrls $rcRelease $rcTag $rcAsset } 'RC metadata requires opt-in'
    [void] (Get-AwfReleaseUrls $rcRelease $rcTag $rcAsset -AllowPrerelease)
    $rcRelease.prerelease = $false
    Assert-Rejected { Get-AwfReleaseUrls $rcRelease $rcTag $rcAsset -AllowPrerelease } 'RC metadata must be prerelease'
    $rcRelease.prerelease = 'true'
    Assert-Rejected { Get-AwfReleaseUrls $rcRelease $rcTag $rcAsset -AllowPrerelease } 'RC metadata requires a boolean'
    $rcRelease.prerelease = $true
    $rcRelease.draft = $true
    Assert-Rejected { Get-AwfReleaseUrls $rcRelease $rcTag $rcAsset -AllowPrerelease } 'draft RC'
    $rcRelease.draft = $false
    $rcRelease.tag_name = 'v0.0.0-rc.2'
    Assert-Rejected { Get-AwfReleaseUrls $rcRelease $rcTag $rcAsset -AllowPrerelease } 'RC tag mismatch'
    $rcRelease.tag_name = $rcTag
    $rcRelease.assets[0].browser_download_url = 'https://example.invalid/download.zip'
    Assert-Rejected { Get-AwfReleaseUrls $rcRelease $rcTag $rcAsset -AllowPrerelease } 'RC unofficial URL'

    $pe = New-TestPE 'amd64'
    $valid = @((New-Fixture 'awf.exe' $pe), (New-Fixture 'awf-node.exe' $pe),
        (New-Fixture 'manifest.json' ([Text.Encoding]::UTF8.GetBytes($manifest))))
    $zipPath = Join-Path $temporary 'valid.zip'
    New-TestZip $zipPath $valid
    Expand-AwfVerifiedArchive $zipPath (Join-Path $temporary 'valid') 'v1.2.3' 'amd64'
    Assert-True (Test-Path -LiteralPath (Join-Path $temporary 'valid\awf.exe')) 'valid archive extracted'
    Assert-Rejected { Assert-AwfNativeExecutable (Join-Path $temporary 'valid\awf.exe') 'arm64' } 'wrong PE machine'
    $rcManifest = '{"version":"v0.0.0-rc.1","os":"windows","arch":"amd64"}'
    $rcZipPath = Join-Path $temporary 'rc-valid.zip'
    New-TestZip $rcZipPath @($valid[0], $valid[1], (New-Fixture 'manifest.json' ([Text.Encoding]::UTF8.GetBytes($rcManifest))))
    Expand-AwfVerifiedArchive $rcZipPath (Join-Path $temporary 'rc-valid') $rcTag 'amd64'
    Assert-True (Test-Path -LiteralPath (Join-Path $temporary 'rc-valid\awf.exe')) 'exact RC archive extracted'
    Assert-Rejected { Assert-AwfManifest $rcManifest 'v0.0.0-rc.2' 'amd64' } 'RC manifest must match exact candidate'
    $cases = @(
        @((New-Fixture '../awf.exe' $pe), $valid[1], $valid[2]),
        @((New-Fixture 'folder/awf.exe' $pe), $valid[1], $valid[2]),
        @((New-Fixture 'awf.exe:evil' $pe), $valid[1], $valid[2]),
        @((New-Fixture 'AWF.EXE' $pe), $valid[1], $valid[2]),
        @($valid[0], $valid[0], $valid[2]),
        @((New-Fixture 'awf.exe' $pe -1610612736), $valid[1], $valid[2]),
        @((New-Fixture 'awf.exe' $pe 1024), $valid[1], $valid[2]),
        @((New-Fixture 'awf.exe' $pe 16), $valid[1], $valid[2]),
        @($valid[0], $valid[1]),
        @($valid[0], $valid[1], $valid[2], (New-Fixture 'extra' $pe)),
        @($valid[0], $valid[1], (New-Fixture 'manifest.json' ([Text.Encoding]::UTF8.GetBytes('{"version":"v9.9.9","os":"windows","arch":"amd64"}')))),
        @((New-Fixture 'awf.exe' (New-TestPE 'arm64')), $valid[1], $valid[2])
    )
    $i = 0
    foreach ($entries in $cases) {
        $i++
        $path = Join-Path $temporary "bad-$i.zip"
        $destination = Join-Path $temporary "bad-$i"
        New-TestZip $path $entries
        Assert-Rejected { Expand-AwfVerifiedArchive $path $destination 'v1.2.3' 'amd64' } "malicious ZIP $i"
    }
    $script:MaxReleaseBytes = 300
    Assert-Rejected { Expand-AwfVerifiedArchive $zipPath (Join-Path $temporary 'oversize') 'v1.2.3' 'amd64' } 'oversized archive'
    Write-Host 'Stable/RC policy, checksum, metadata, manifest, PE, and malicious ZIP tests passed.'
    if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
        Write-Host ('Native system architecture: ' + (Get-AwfNativeArchitecture))
    }
} finally { Remove-Item -LiteralPath $temporary -Recurse -Force }
