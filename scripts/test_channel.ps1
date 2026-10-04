#requires -Version 5.1
# Pure channel/source/consent fixtures. No legacy-install support.
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
Assert-True ($published.schema -ceq '1' -and $published.channel -ceq 'go-v1') 'distribution uses the exact Go channel schema'
Assert-True ($published.cliProtocol -ceq '3') 'published fresh installer requires protocol 3'
# Parser validation requires exact version, source SHA and architecture digests.
# Check lossless parsing against the current file instead of a retired release.
$raw = $text | ConvertFrom-Json
foreach ($key in @('schema', 'channel', 'version', 'sourceCommit', 'cliProtocol', 'windowsAMD64SHA256', 'windowsARM64SHA256')) {
    Assert-True ($published[$key] -ceq $raw.$key) "distribution preserves exact $key"
}

# The current channel declares the reviewed fresh-install capability.
# Historical protocol refusal remains covered by the synthetic fixtures below.
Assert-AwfFreshChannel $published
# Well-formed forged source pins must still fail against release/tag evidence.
$publishedRelease = [pscustomobject] @{ target_commitish = $published.sourceCommit }
$publishedRef = [pscustomobject] @{ ref = ('refs/tags/' + $published.version); object = [pscustomobject] @{ type = 'commit'; sha = $published.sourceCommit } }
Assert-AwfChannelRelease $published $publishedRelease $publishedRef
$forgedSource = 'a' * 40
if ($forgedSource -ceq $published.sourceCommit) { $forgedSource = 'b' * 40 }
$forged = Read-AwfChannelManifest ($text.Replace($published.sourceCommit, $forgedSource))
Assert-Rejected { Assert-AwfChannelRelease $forged $publishedRelease $publishedRef } 'well-formed forged current source rejected'
# Synthetic protocol-3 metadata for parser/source fixtures only.
$text = @'
{
  "schema": "1",
  "channel": "go-v1",
  "version": "v1.2.3-rc.1",
  "sourceCommit": "5e7e85df0891888c21d8a4a7af4d2329f7b2b9a5",
  "cliProtocol": "3",
  "windowsAMD64SHA256": "165c6290b83d6ec12c5b1dece198c661963c3ad9ab6cddf8f813e7a7edd7432a",
  "windowsARM64SHA256": "7c6b07e9b1fb3ff2f9bfa60151d94e25da0e91ac96af4ae5a5a7a481f80dd951"
}
'@
$channel = Read-AwfChannelManifest $text
Assert-True ($channel.version -ceq 'v1.2.3-rc.1') 'synthetic fresh release version'
Assert-True ($channel.cliProtocol -ceq '3') 'fresh release declares public install capability'
Assert-True ($channel.sourceCommit -ceq '5e7e85df0891888c21d8a4a7af4d2329f7b2b9a5') 'synthetic source pin preserved exactly'
Assert-True ($channel.windowsAMD64SHA256 -ceq '165c6290b83d6ec12c5b1dece198c661963c3ad9ab6cddf8f813e7a7edd7432a') 'synthetic AMD64 pin preserved exactly'
Assert-True ($channel.windowsARM64SHA256 -ceq '7c6b07e9b1fb3ff2f9bfa60151d94e25da0e91ac96af4ae5a5a7a481f80dd951') 'synthetic ARM64 pin preserved exactly'
Assert-AwfFreshChannel $channel
foreach ($protocol in @('1', '2')) {
    Assert-Rejected { Assert-AwfFreshChannel @{ cliProtocol = $protocol } } 'historical protocol cannot fresh-install'
}
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
    $text.Replace('"cliProtocol": "3"', '"cliProtocol": "4"'),
    $text.Replace('"channel": "go-v1"', '"channel": "python"'),
    $text.Replace('v1.2.3-rc.1', 'v0.3.0'),
    $text.Replace('v1.2.3-rc.1', 'v2.0.0'),
    $text.Replace('v1.2.3-rc.1', 'v1.0.0-rc.02'),
    $text.Replace('v1.2.3-rc.1', 'v1.0.0-beta.2'),
    $text.Replace('v1.2.3-rc.1', 'v1.0.0\u002drc.2'),
    $text.Replace($channel.sourceCommit, 'awf/go-v1'),
    $text.Replace($channel.sourceCommit, $channel.sourceCommit.ToUpperInvariant()),
    $text.Replace($channel.windowsAMD64SHA256, 'a' * 63),
    $text.Replace($channel.windowsARM64SHA256, $channel.windowsARM64SHA256.ToUpperInvariant()),
    ($text + '{}'), (' ' * 4097 + $text)
)) { Assert-Rejected { Read-AwfChannelManifest $bad } 'invalid/unknown/ambiguous channel rejected' }
foreach ($version in @('v1.0.0-rc.0', 'v1.0.0', 'v1.999999999999999999999.0')) {
    [void] (Read-AwfChannelManifest ($text.Replace('v1.2.3-rc.1', $version)))
}
[void] (Read-AwfChannelManifest ($text.Replace('"cliProtocol": "3"', '"cliProtocol": "2"')))

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
Assert-True (Confirm-AwfPreview 'v1.2.3-rc.1' $true $false) 'explicit noninteractive preview opt-in'
Assert-Rejected { Confirm-AwfPreview 'v1.2.3-rc.1' $false $false } 'noninteractive preview fails closed'
Assert-True ($script:questions.Count -eq 0) 'no unexpected prompt in noninteractive mode'
foreach ($answer in @($null, '', 'n', 'no', 'yes please')) {
    $script:answers = @($answer)
    Assert-Rejected { Confirm-AwfPreview 'v1.2.3-rc.1' $false $true } 'preview decline cancels'
}
$script:questions = @(); $script:answers = @('YES')
Assert-True (Confirm-AwfPreview 'v1.2.3-rc.1' $false $true) 'one affirmative preview answer accepted'
Assert-True ($script:questions.Count -eq 1) 'exactly one preview prompt'
Assert-True ($script:questions[0].Contains('preview updates in the Go v1 channel')) 'durable preview scope disclosed'
$release = [pscustomobject] @{ target_commitish = $channel.sourceCommit }
$ref = [pscustomobject] @{ ref = 'refs/tags/v1.2.3-rc.1'; object = [pscustomobject] @{ type = 'commit'; sha = $channel.sourceCommit } }
Assert-AwfChannelRelease $channel $release $ref
$release.target_commitish = 'awf/go-v1'
Assert-Rejected { Assert-AwfChannelRelease $channel $release $ref } 'branch target is not exact source'
$release.target_commitish = $channel.sourceCommit; $ref.object.type = 'tag'
Assert-Rejected { Assert-AwfChannelRelease $channel $release $ref } 'unknown annotated-tag semantics rejected'
$ref.object.type = 'commit'; $ref.object.sha = 'a' * 40
Assert-Rejected { Assert-AwfChannelRelease $channel $release $ref } 'moved tag rejected'
$ref.object.sha = $channel.sourceCommit; $ref.ref = 'refs/tags/v1.0.0-rc.1'
Assert-Rejected { Assert-AwfChannelRelease $channel $release $ref } 'different tag rejected'
$ref.ref = 'refs/tags/v1.2.3-rc.1'
foreach ($value in @(@(), @('refs/tags/v1.2.3-rc.1'), $null, [pscustomobject] @{})) {
    $ref.ref = $value
    Assert-Rejected { Assert-AwfChannelRelease $channel $release $ref } 'tag ref must be a scalar string'
}
$ref.ref = 'refs/tags/v1.2.3-rc.1'
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

Write-Host 'Go channel schema, fresh-only protocol, exact source and preview consent tests passed.'
