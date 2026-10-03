#requires -Version 5.1
<#
Native Windows unit tests for install-only package and physical-path guards.
Detector/result shims below are test-local only. They are not evidence of a real
packaged process or real MSIX redirection. No downloads, installed AWF paths,
PATH, registry, runtime, credentials or environment variables are changed.
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'Run these tests in native Windows PowerShell 5.1 or PowerShell 7.'
}
. (Join-Path $PSScriptRoot 'install.ps1') -Version 'v1.2.3'
function Assert-ContextTrue([bool] $Condition, [string] $Message) {
    if (-not $Condition) { throw "TEST FAILED: $Message" }
}
function Assert-ContextRejected([scriptblock] $Action, [string] $Expected) {
    $rejected = $false
    try { & $Action } catch {
        $rejected = $true
        Assert-ContextTrue ($_.Exception.Message -like $Expected) ("unexpected error: " + $_.Exception.Message)
    }
    Assert-ContextTrue $rejected "expected rejection: $Expected"
}

# The unmodified entry still executes real architecture and profile guards.
# Stop rather than silently changing the environment to make this fixture pass.
$local = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
if (-not $env:LOCALAPPDATA -or [IO.Path]::GetFullPath($env:LOCALAPPDATA).TrimEnd('\') -ine $local.TrimEnd('\')) {
    throw 'Context fixture needs LOCALAPPDATA to match the actual known folder; environment was not changed.'
}
foreach ($case in @(
    @{ Status = 15700; Expected = 'TEST_STAGE_BOUNDARY'; Stages = 1; Markers = 4 },
    @{ Status = 122; Expected = 'This terminal is running inside a packaged app*'; Stages = 0; Markers = 0 },
    @{ Status = 0; Expected = 'This terminal is running inside a packaged app*'; Stages = 0; Markers = 0 },
    @{ Status = 5; Expected = 'Unable to verify the Windows installation context*'; Stages = 0; Markers = 0 },
    @{ Status = -1; Expected = 'Unable to verify the Windows installation context*'; Stages = 0; Markers = 0 },
    @{ Status = 'throw'; Expected = 'Unable to verify the Windows installation context*'; Stages = 0; Markers = 0 }
)) {
    & {
        # Mutable counter object avoids function-local scalar assignment scope.
        $counts = @{ Stage = 0; Markers = 0; Download = 0; Path = 0; Expand = 0 }
        function Get-AwfPackageIdentityStatus {
            if ($case.Status -is [string] -and $case.Status -ceq 'throw') { throw 'fixture API failure' }
            return $case.Status
        }
        function Test-Path { $counts.Markers++; return $false }
        function New-AwfPrivateStage { $counts.Stage++; throw 'TEST_STAGE_BOUNDARY' }
        function Save-AwfOfficialDownload { $counts.Download++; throw 'TEST_DOWNLOAD_REACHED' }
        function Add-AwfUserPath { $counts.Path++; throw 'TEST_PATH_REACHED' }
        function Expand-AwfVerifiedArchive { $counts.Expand++; throw 'TEST_EXPAND_REACHED' }
        Assert-ContextRejected { Invoke-AwfBootstrap } $case.Expected
        Assert-ContextTrue ($counts.Stage -eq $case.Stages -and $counts.Markers -eq $case.Markers) 'identity gate precedes staging and installed-marker inspection'
        Assert-ContextTrue ($counts.Download -eq 0 -and $counts.Path -eq 0 -and $counts.Expand -eq 0) 'identity fixture has no network, extraction, or PATH effects'
    }
}

foreach ($case in @(
    @('C:\Users\Example\AppData\Local\AWF\', 'C:\Users\Example\AppData\Local\AWF'),
    @('\\?\C:\Users\Example\AppData\Local\AWF', 'C:\Users\Example\AppData\Local\AWF'),
    @('c:/Users/Example/AppData/Local/./AWF/../AWF', 'c:\Users\Example\AppData\Local\AWF'),
    @('\\?\UNC\server.example\share\dir\', '\\server.example\share\dir'),
    @('\\server.example\share\dir\..\next', '\\server.example\share\next'),
    @('C:\', 'C:\'),
    @('C:\..\AWF', 'C:\AWF'),
    @('\\?\UNC\server\share\..\AWF', '\\server\share\AWF')
)) {
    Assert-ContextTrue ((ConvertTo-AwfCanonicalWindowsPath $case[0]) -ceq $case[1]) 'canonical Windows path conversion'
}
foreach ($path in @('', 'relative\AWF', 'C:AWF', '\AWF', '\\server', '\\.\C:\AWF',
    '\\?\Volume{1234}\AWF', 'C:\AWF\file:stream', 'C:\AWF.\file', 'C:\AWF \file',
    '\\server\share.\file', 'C:\AWF\*.exe')) {
    Assert-ContextRejected { ConvertTo-AwfCanonicalWindowsPath $path } 'Installation path*'
}
& {
    function Get-AwfFinalPath { return '\\?\c:\users\example\appdata\local\AWF\' }
    Assert-AwfNativePath 'C:\Users\Example\AppData\Local\AWF'
}
& {
    function Get-AwfFinalPath { return '\\?\C:\Users\Example\AppData\Local\Packages\Example\LocalCache\Local\AWF\bin\awf.exe' }
    Assert-ContextRejected { Assert-AwfNativePath 'C:\Users\Example\AppData\Local\AWF\bin\awf.exe' } 'Windows redirected an installation path*'
}
& {
    function Get-AwfFinalPath { throw 'fixture handle query failure' }
    Assert-ContextRejected { Assert-AwfNativePath 'C:\Users\Example\AppData\Local\AWF\bin\awf.exe' } 'Unable to verify the physical installation path*'
}

# Real disposable directories, real private ACL creation, and real handles. This
# fixture does not use an installed AWF directory or execute fixture bytes.
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('awf-context-test-' + [Guid]::NewGuid().ToString('N'))
[void] [IO.Directory]::CreateDirectory($temporary)
try {
    Assert-AwfNativePath $temporary
    $file = Join-Path $temporary 'fixture.txt'
    [IO.File]::WriteAllText($file, 'fixture')
    Assert-AwfNativePath $file
    [IO.File]::Delete($file)
    & {
        $counts = @{ Stage = 0; Download = 0; Path = 0 }
        # Actual NO_PACKAGE can coexist with redirected filesystem writes.
        # This explicit case proves the physical gate runs independently.
        function Get-AwfPackageIdentityStatus { return 15700 }
        function Test-Path { return $false }
        $realStage = (Get-Item Function:\New-AwfPrivateStage).ScriptBlock
        function New-AwfPrivateStage { $counts.Stage++; return & $realStage $temporary }
        function Get-AwfFinalPath { return '\\?\C:\redirected\fixture-stage' }
        function Save-AwfOfficialDownload { $counts.Download++; throw 'TEST_DOWNLOAD_REACHED' }
        function Add-AwfUserPath { $counts.Path++; throw 'TEST_PATH_REACHED' }
        Assert-ContextRejected { Invoke-AwfBootstrap } 'Windows redirected an installation path*'
        Assert-ContextTrue ($counts.Stage -eq 1 -and $counts.Download -eq 0 -and $counts.Path -eq 0) 'NO_PACKAGE plus redirected stage rejects before network or PATH'
        Assert-ContextTrue ((@(Get-ChildItem -LiteralPath $temporary -Force)).Count -eq 0) 'rejected private stage is removed'
    }
    $installedRoot = Join-Path $temporary 'inert-installed-fixture'
    $installedBin = Join-Path $installedRoot 'bin'
    [void] [IO.Directory]::CreateDirectory($installedBin)
    [IO.File]::WriteAllText((Join-Path $installedBin 'awf.exe'), 'inert fixture, never executed')
    & {
        $counts = @{ Path = 0; Channel = 0 }
        function Get-AwfFinalPath { return '\\?\C:\redirected\fixture-launcher.exe' }
        function Add-AwfUserPath { $counts.Path++ }
        function Save-AwfLegacyChannel { $counts.Channel++ }
        $legacy = @{ cliProtocol = '1' }
        Assert-ContextRejected { Register-AwfInstalledLauncher $installedRoot $legacy $false } 'Windows redirected an installation path*'
        Assert-ContextTrue ($counts.Path -eq 0 -and $counts.Channel -eq 0) 'redirected installed launcher blocks actual registration helper before PATH/channel effects'
    }
    & {
        $counts = @{ Path = 0; Bin = '' }
        function Add-AwfUserPath([string] $Bin) { $counts.Path++; $counts.Bin = $Bin }
        Register-AwfInstalledLauncher $installedRoot $null $false
        Assert-ContextTrue ($counts.Path -eq 1 -and $counts.Bin -ceq $installedBin) 'real native launcher path permits mocked PATH registration'
    }
} finally { Remove-Item -LiteralPath $temporary -Recurse -Force }
Write-Host 'Install-context unit tests passed: mocked identity/errors, NO_PACKAGE with redirected stage, canonical paths, real disposable handles. Real package identity is a separate read-only gate.'
