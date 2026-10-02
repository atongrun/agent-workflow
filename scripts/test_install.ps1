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
function Assert-Rejected([scriptblock] $Action, [string] $Message) {
    $rejected = $false
    try { & $Action } catch { $rejected = $true }
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
    $release.prerelease = $true
    Assert-Rejected { Get-AwfReleaseUrls $release 'v1.2.3' $asset } 'prerelease'
    $release.prerelease = $false
    $release.assets[0].browser_download_url = 'https://example.invalid/download.zip'
    Assert-Rejected { Get-AwfReleaseUrls $release 'v1.2.3' $asset } 'unofficial URL'
    $release.assets[0].browser_download_url = "https://github.com/atongrun/agent-workflow/releases/download/v1.2.3/$asset"
    $release.assets += $release.assets[0]
    Assert-Rejected { Get-AwfReleaseUrls $release 'v1.2.3' $asset } 'duplicate release asset'

    $pe = New-TestPE 'amd64'
    $valid = @((New-Fixture 'awf.exe' $pe), (New-Fixture 'awf-node.exe' $pe),
        (New-Fixture 'manifest.json' ([Text.Encoding]::UTF8.GetBytes($manifest))))
    $zipPath = Join-Path $temporary 'valid.zip'
    New-TestZip $zipPath $valid
    Expand-AwfVerifiedArchive $zipPath (Join-Path $temporary 'valid') 'v1.2.3' 'amd64'
    Assert-True (Test-Path -LiteralPath (Join-Path $temporary 'valid\awf.exe')) 'valid archive extracted'
    Assert-Rejected { Assert-AwfNativeExecutable (Join-Path $temporary 'valid\awf.exe') 'arm64' } 'wrong PE machine'
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
    Write-Host 'Checksum, metadata, manifest, PE, and malicious ZIP tests passed.'
    if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
        Write-Host ('Native system architecture: ' + (Get-AwfNativeArchitecture))
    }
} finally { Remove-Item -LiteralPath $temporary -Recurse -Force }
