#requires -Version 5.1
# Pure channel/consent fixtures plus private-directory tests on native Windows.
# No downloads, executables, installs, PATH changes, or credentials.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'install.ps1')
function Assert-True([bool] $Condition, [string] $Message) {
    if (-not $Condition) { throw "TEST FAILED: $Message" }
}
function Assert-Rejected([scriptblock] $Action, [string] $Message) {
    $rejected = $false
    try { & $Action | Out-Null } catch { $rejected = $true }
    Assert-True $rejected $Message
}
foreach ($pin in @('', $null, ('a' * 64), ('A' * 64))) { Assert-AwfArchivePin $pin }
foreach ($pin in @(' ', 'bad', ('a' * 63), ('g' * 64), (('a' * 64) + "`n"))) {
    Assert-Rejected { Assert-AwfArchivePin $pin } 'malformed optional pin rejected'
}
$manifestPath = Join-Path (Split-Path $PSScriptRoot -Parent) 'distribution\go-v1.json'
$text = [IO.File]::ReadAllText($manifestPath)
$published = Read-AwfChannelManifest $text
Assert-True ($published.version -ceq 'v1.0.0-rc.3') 'distribution selects published RC3'
Assert-True ($published.cliProtocol -ceq '2') 'RC3 supports guided init and channel updates'
Assert-True ($published.sourceCommit -ceq 'c251c9de639352b529f4705fcd1d2b4881cd20bf') 'distribution pins exact RC3 source'
Assert-True ($published.windowsAMD64SHA256 -ceq 'e8610c429dfdfb791ac647a56d7992eda82e4cdbe13bdc866e646e024f49ea22') 'distribution pins published AMD64 bytes'
Assert-True ($published.windowsARM64SHA256 -ceq '767eaff26618d2a5c8d86a7aa5bc04e27925537f62eb67575eff51fd06a370f4') 'distribution pins published ARM64 bytes'

# Retain protocol-1 RC2 parser/compatibility coverage independently of promotion.
$text = @'
{
  "schema": "1",
  "channel": "go-v1",
  "version": "v1.0.0-rc.2",
  "sourceCommit": "5e7e85df0891888c21d8a4a7af4d2329f7b2b9a5",
  "cliProtocol": "1",
  "windowsAMD64SHA256": "165c6290b83d6ec12c5b1dece198c661963c3ad9ab6cddf8f813e7a7edd7432a",
  "windowsARM64SHA256": "7c6b07e9b1fb3ff2f9bfa60151d94e25da0e91ac96af4ae5a5a7a481f80dd951"
}
'@
$channel = Read-AwfChannelManifest $text
Assert-True ($channel.version -ceq 'v1.0.0-rc.2') 'fixture retains actual published RC2'
Assert-True ($channel.cliProtocol -ceq '1') 'RC2 must not claim new CLI capabilities'
foreach ($bad in @(
    $text.Replace('"schema": "1"', '"schema": 1'),
    $text.Replace('"schema": "1"', '"schema": "2"'),
    $text.Replace('"schema": "1"', '"schema": "1", "extra": "x"'),
    $text.Replace('"schema": "1"', '"schema": "1", "schema": "1"'),
    $text.Replace('"schema": "1"', '"schema": null'),
    $text.Replace('"schema": "1"', '"schema": {}'),
    $text.Replace('"schema": "1"', '"schema": "1",'),
    $text.Replace('"schema"', '"schem\u0061"'),
    $text.Replace('"sourceCommit"', '"schema"'),
    $text.Replace('"cliProtocol": "1"', '"cliProtocol": "3"'),
    $text.Replace('"channel": "go-v1"', '"channel": "python"'),
    $text.Replace('v1.0.0-rc.2', 'v0.3.0'),
    $text.Replace('v1.0.0-rc.2', 'v2.0.0'),
    $text.Replace('v1.0.0-rc.2', 'v1.0.0-rc.02'),
    $text.Replace('v1.0.0-rc.2', 'v1.0.0-beta.2'),
    $text.Replace('v1.0.0-rc.2', 'v1.0.0\u002drc.2'),
    $text.Replace($channel.sourceCommit, 'awf/go-v1'),
    $text.Replace($channel.sourceCommit, $channel.sourceCommit.ToUpperInvariant()),
    $text.Replace($channel.windowsAMD64SHA256, 'a' * 63),
    $text.Replace($channel.windowsARM64SHA256, $channel.windowsARM64SHA256.ToUpperInvariant()),
    ($text + '{}'), (' ' * 4097 + $text)
)) { Assert-Rejected { Read-AwfChannelManifest $bad } 'invalid/unknown/ambiguous channel rejected' }
foreach ($version in @('v1.0.0-rc.0', 'v1.0.0', 'v1.999999999999999999999.0')) {
    [void] (Read-AwfChannelManifest ($text.Replace('v1.0.0-rc.2', $version)))
}
[void] (Read-AwfChannelManifest ($text.Replace('"cliProtocol": "1"', '"cliProtocol": "2"')))

$script:answers = @()
$script:questions = @()
function Read-Host([string] $Prompt) {
    $script:questions += $Prompt
    if ($script:answers.Count -eq 0) { throw 'Fixture has no interactive answer.' }
    $answer = $script:answers[0]
    $script:answers = @($script:answers | Select-Object -Skip 1)
    return $answer
}
Assert-True (-not (Confirm-AwfPreview 'v1.0.0' $false $false)) 'stable requires no preview consent'
Assert-True (Confirm-AwfPreview 'v1.0.0-rc.2' $true $false) 'explicit noninteractive preview opt-in'
Assert-Rejected { Confirm-AwfPreview 'v1.0.0-rc.2' $false $false } 'noninteractive preview fails closed'
Assert-True ($script:questions.Count -eq 0) 'no unexpected prompt in noninteractive mode'
foreach ($answer in @($null, '', 'n', 'no', 'yes please')) {
    $script:answers = @($answer)
    Assert-Rejected { Confirm-AwfPreview 'v1.0.0-rc.2' $false $true } 'preview decline cancels'
}
$script:questions = @(); $script:answers = @('YES')
Assert-True (Confirm-AwfPreview 'v1.0.0-rc.2' $false $true) 'one affirmative preview answer accepted'
Assert-True ($script:questions.Count -eq 1) 'exactly one preview prompt'
Assert-True ($script:questions[0].Contains('preview updates in the Go v1 channel')) 'durable preview scope disclosed'
$script:questions = @(); $script:answers = @('y')
[void] (Confirm-AwfPreview 'v1.0.0-rc.2' $false $true $false)
Assert-True (-not $script:questions[0].Contains('preview updates')) 'advanced pin does not promise durable channel approval'
$release = [pscustomobject] @{ target_commitish = $channel.sourceCommit }
$ref = [pscustomobject] @{ ref = 'refs/tags/v1.0.0-rc.2'; object = [pscustomobject] @{ type = 'commit'; sha = $channel.sourceCommit } }
Assert-AwfChannelRelease $channel $release $ref
$release.target_commitish = 'awf/go-v1'
Assert-Rejected { Assert-AwfChannelRelease $channel $release $ref } 'branch target is not exact source'
$release.target_commitish = $channel.sourceCommit; $ref.object.type = 'tag'
Assert-Rejected { Assert-AwfChannelRelease $channel $release $ref } 'unknown annotated-tag semantics rejected'
$ref.object.type = 'commit'; $ref.object.sha = 'a' * 40
Assert-Rejected { Assert-AwfChannelRelease $channel $release $ref } 'moved tag rejected'
$ref.object.sha = $channel.sourceCommit; $ref.ref = 'refs/tags/v1.0.0-rc.1'
Assert-Rejected { Assert-AwfChannelRelease $channel $release $ref } 'different tag rejected'
$ref.ref = 'refs/tags/v1.0.0-rc.2'
foreach ($value in @(@(), @('refs/tags/v1.0.0-rc.2'), $null, [pscustomobject] @{})) {
    $ref.ref = $value
    Assert-Rejected { Assert-AwfChannelRelease $channel $release $ref } 'tag ref must be a scalar string'
}
$ref.ref = 'refs/tags/v1.0.0-rc.2'
foreach ($value in @(@(), @('commit'), $null, [pscustomobject] @{})) {
    $ref.object.type = $value
    Assert-Rejected { Assert-AwfChannelRelease $channel $release $ref } 'tag type must be a scalar string'
}
$ref.object.type = 'commit'
foreach ($value in @(@(), @($channel.sourceCommit), $null, [pscustomobject] @{})) {
    $ref.object.sha = $value
    Assert-Rejected { Assert-AwfChannelRelease $channel $release $ref } 'tag commit must be a scalar string'
}
$ref.object.sha = $channel.sourceCommit
foreach ($value in @(@(), @($channel.sourceCommit), $null, [pscustomobject] @{})) {
    $release.target_commitish = $value
    Assert-Rejected { Assert-AwfChannelRelease $channel $release $ref } 'release source must be a scalar string'
}
$release.target_commitish = $channel.sourceCommit
Assert-Rejected { Assert-AwfChannelRelease $channel $release @($ref) } 'tag response must be one object'
Assert-Rejected { Assert-AwfChannelRelease $channel @($release) $ref } 'release response must be one object'
$ref.object = @()
Assert-Rejected { Assert-AwfChannelRelease $channel $release $ref } 'tag object cannot be an array'
Assert-Rejected { Save-AwfOfficialDownload -Url 'https://example.invalid/go-v1.json' -Destination 'must-not-exist' -Limit 4096 -Channel } 'channel source cannot be overridden'
Assert-Rejected { Save-AwfOfficialDownload -Url ($script:ChannelUrl + '?other=1') -Destination 'must-not-exist' -Limit 4096 -Channel } 'channel query cannot be overridden'

if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
    $local = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
    $root = New-AwfPrivateStage $local
    try {
        Save-AwfLegacyChannel $root $true
        $saved = [IO.File]::ReadAllText((Join-Path $root 'channel.json')) | ConvertFrom-Json
        Assert-True ($saved.schema -ceq '1' -and $saved.channel -ceq 'go-v1' -and $saved.previewApproved -eq $true) 'protected legacy channel persists consent'
        Assert-Rejected { Save-AwfLegacyChannel $root $false } 'existing consent marker is not overwritten'
        $saved = [IO.File]::ReadAllText((Join-Path $root 'channel.json')) | ConvertFrom-Json
        Assert-True ($saved.previewApproved -eq $true) 'failed write preserves old marker'
        Assert-True (@(Get-ChildItem -LiteralPath $root -Filter '.awf-channel-*').Count -eq 0) 'failed write cleans temporary marker'
    } finally { Remove-Item -LiteralPath $root -Recurse -Force }
}
Write-Host 'Go channel schema, exact source, preview consent and marker tests passed.'
