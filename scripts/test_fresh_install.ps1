#requires -Version 5.1
# Fresh-only entry guards. Only disposable fixture paths are read/created;
# no downloads, executable runs, installed roots, ACLs, PATH, or registry writes.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'install.ps1')
function Assert-FreshTrue([bool] $Condition, [string] $Message) {
    if (-not $Condition) { throw "TEST FAILED: $Message" }
}
function Assert-FreshRejected([scriptblock] $Action, [string] $Expected, [string] $Label) {
    $rejected = $false
    try { & $Action } catch {
        $rejected = $true
        Assert-FreshTrue ($_.Exception.Message -like $Expected) ($Label + ': ' + $_.Exception.Message)
    }
    Assert-FreshTrue $rejected $Label
}
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('awf-fresh-test-' + [Guid]::NewGuid().ToString('N'))
[void] [IO.Directory]::CreateDirectory($temporary)
try {
    $root = Join-Path $temporary 'AWF'
    Assert-AwfFreshRoot $root
    Assert-FreshTrue (-not (Test-Path -LiteralPath $root)) 'absent root is not created'
    [void] [IO.Directory]::CreateDirectory($root)
    Assert-FreshRejected { Assert-AwfFreshRoot $root } 'AWF root already exists*' 'empty root'
    Assert-FreshTrue (@(Get-ChildItem -LiteralPath $root -Force).Count -eq 0) 'empty root unchanged'
    $credentials = Join-Path $root 'credentials'
    [void] [IO.Directory]::CreateDirectory($credentials)
    $inert = Join-Path $credentials 'fixture.txt'
    [IO.File]::WriteAllText($inert, 'inert fixture')
    Assert-FreshRejected { Assert-AwfFreshRoot $root } 'AWF root already exists*' 'credentials-only root'
    Assert-FreshTrue ([IO.File]::ReadAllText($inert) -ceq 'inert fixture') 'existing data preserved'
    $file = Join-Path $temporary 'root-file'
    [IO.File]::WriteAllText($file, 'inert root')
    Assert-FreshRejected { Assert-AwfFreshRoot $file } 'AWF root already exists*' 'root file'
    Assert-FreshTrue ([IO.File]::ReadAllText($file) -ceq 'inert root') 'root file preserved'
} finally { Remove-Item -LiteralPath $temporary -Recurse -Force }
& {
    function Get-Item { throw [UnauthorizedAccessException]::new('fixture denied') }
    Assert-FreshRejected { Assert-AwfFreshRoot 'unreadable-fixture' } 'AWF root state could not be verified*' 'unknown root state'
}
foreach ($protocol in @('1', '2', '4')) {
    Assert-FreshRejected { Assert-AwfFreshChannel @{ cliProtocol = $protocol } } 'The published Go channel does not yet provide*' 'historical protocol'
}
Assert-AwfFreshChannel @{ cliProtocol = '3' } # fresh protocol
if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
    & {
        # The profile and architecture checks are real; only root inspection is
        # redirected to an inert existing-root result, never the installed root.
        $counts = @{ Stage = 0; Download = 0 }
        function Assert-AwfUnpackagedProcess { }
        function Assert-AwfFreshRoot { throw 'TEST_EXISTING_ROOT' }
        function New-AwfPrivateStage { $counts.Stage++; throw 'STAGE_MUST_NOT_RUN' }
        function Save-AwfOfficialDownload { $counts.Download++; throw 'NETWORK_MUST_NOT_RUN' }
        Assert-FreshRejected { Invoke-AwfBootstrap } 'TEST_EXISTING_ROOT' 'existing root precedes staging'
        Assert-FreshTrue ($counts.Stage -eq 0 -and $counts.Download -eq 0) 'existing root makes no stage or download'
    }
}
Write-Host 'Fresh-only root refusal, historical protocol refusal and read-only guard tests passed.'
