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
    if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
        $programs = Join-Path $temporary 'Programs'
        Assert-AwfProgramsPath $programs
        Assert-FreshTrue (-not (Test-Path -LiteralPath $programs)) 'missing Programs planning does not create it'
        Assert-FreshRejected { Assert-AwfProgramsPath (Join-Path $programs 'nested') } 'Current-user Programs requires an accessible existing direct parent*' 'missing parent is not recursively created'
        Assert-FreshRejected { Assert-AwfProgramsPath $file } 'Bootstrap directories must be real directories*' 'Programs file is refused'
        & {
            function Get-AwfFinalPath { return '\\?\C:\redirected\parent' }
            Assert-FreshRejected { Assert-AwfProgramsPath $programs } 'Windows redirected an installation path*' 'redirected Programs ancestor is refused'
        }
        & {
            $counts = @{ Stage = 0; Download = 0 }
            function Assert-AwfUnpackagedProcess { }
            # Known-folder shim only; production has no directory override.
            function Get-AwfUserProgramFiles { return $programs }
            function New-AwfPrivateStage { $counts.Stage++; throw 'TEST_STAGE_BOUNDARY' }
            function Save-AwfOfficialDownload { $counts.Download++; throw 'NETWORK_MUST_NOT_RUN' }
            Assert-FreshRejected { Invoke-AwfBootstrap } 'TEST_STAGE_BOUNDARY' 'historical sibling root is ignored'
            Assert-FreshTrue ($counts.Stage -eq 1 -and $counts.Download -eq 0) 'missing Programs reaches stage without download'
            Assert-FreshTrue (-not (Test-Path -LiteralPath $programs)) 'bootstrap leaves Programs creation to native installer'
            Assert-FreshTrue ([IO.File]::ReadAllText($inert) -ceq 'inert fixture') 'historical sibling contents remain unchanged'
        }
        [void] [IO.Directory]::CreateDirectory($programs)
        Assert-AwfProgramsPath $programs
        $programsRoot = Join-Path $programs 'AWF'
        [void] [IO.Directory]::CreateDirectory($programsRoot)
        & {
            $counts = @{ Stage = 0 }
            function Assert-AwfUnpackagedProcess { }
            function Get-AwfUserProgramFiles { return $programs }
            function New-AwfPrivateStage { $counts.Stage++; throw 'STAGE_MUST_NOT_RUN' }
            Assert-FreshRejected { Invoke-AwfBootstrap } 'AWF root already exists*' 'existing Programs AWF root refused'
            Assert-FreshTrue ($counts.Stage -eq 0) 'existing Programs AWF root stops before stage'
            Assert-FreshTrue (@(Get-ChildItem -LiteralPath $programsRoot -Force).Count -eq 0) 'existing Programs AWF root unchanged'
            Assert-FreshTrue ([IO.File]::ReadAllText($inert) -ceq 'inert fixture') 'historical sibling preserved on refusal'
        }
    }
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
        # The staging profile and architecture checks are real; root inspection is
        # redirected to an inert existing-root result, never the installed root.
        $counts = @{ Stage = 0; Download = 0 }
        function Assert-AwfUnpackagedProcess { }
        function Get-AwfUserProgramFiles { return 'C:\Users\Example\AppData\Local\Programs' }
        function Assert-AwfProgramsPath { }
        function Assert-AwfFreshRoot { throw 'TEST_EXISTING_ROOT' }
        function New-AwfPrivateStage { $counts.Stage++; throw 'STAGE_MUST_NOT_RUN' }
        function Save-AwfOfficialDownload { $counts.Download++; throw 'NETWORK_MUST_NOT_RUN' }
        Assert-FreshRejected { Invoke-AwfBootstrap } 'TEST_EXISTING_ROOT' 'existing root precedes staging'
        Assert-FreshTrue ($counts.Stage -eq 0 -and $counts.Download -eq 0) 'existing root makes no stage or download'
    }
    & {
        $counts = @{ Stage = 0; Root = 0 }
        function Assert-AwfUnpackagedProcess { }
        function Get-AwfUserProgramFiles { throw 'TEST_KNOWN_FOLDER_UNAVAILABLE' }
        function Assert-AwfFreshRoot { $counts.Root++ }
        function New-AwfPrivateStage { $counts.Stage++; throw 'STAGE_MUST_NOT_RUN' }
        Assert-FreshRejected { Invoke-AwfBootstrap } 'TEST_KNOWN_FOLDER_UNAVAILABLE' 'unavailable known folder has no fallback'
        Assert-FreshTrue ($counts.Stage -eq 0 -and $counts.Root -eq 0) 'known-folder failure does not inspect a fallback root'
    }
}
Write-Host 'Fresh-only root refusal, historical protocol refusal and read-only guard tests passed.'
