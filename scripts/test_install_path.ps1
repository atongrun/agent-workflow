#requires -Version 5.1
# Pure PATH text and mocked command-resolution tests. Never calls the environment
# setter, touches registry/PATH, or invokes an installed command or executable.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'install.ps1')
function Assert-PathText([string] $Actual, [string] $Expected, [string] $Label) {
    if ($Actual -cne $Expected) { throw "TEST FAILED: $Label`nExpected: $Expected`nActual: $Actual" }
}
$bin = 'C:\Users\Example\AppData\Local\AWF\bin'
$other = 'C:\Python\Scripts;C:\Windows\System32'
foreach ($case in @(
    @{ Label = 'missing'; Before = $other; After = "$bin;$other" },
    @{ Label = 'empty'; Before = ''; After = $bin },
    @{ Label = 'already first'; Before = "$bin;$other"; After = "$bin;$other" },
    @{ Label = 'existing late'; Before = "$other;$bin"; After = "$bin;$other" },
    @{ Label = 'quoted'; Before = ('C:\Python\Scripts;"' + $bin + '";C:\Windows\System32'); After = "$bin;$other" },
    @{ Label = 'case variant'; Before = ($other + ';' + $bin.ToUpperInvariant()); After = "$bin;$other" },
    @{ Label = 'trailing separator'; Before = ($other + ';' + $bin + '\'); After = "$bin;$other" },
    @{ Label = 'slash and dot components'; Before = ('C:\Python\Scripts;' + $bin.Replace('\', '/') + '/./;C:\Windows\System32'); After = "$bin;$other" },
    @{ Label = 'all exact duplicates'; Before = ($bin + ';C:\Python\Scripts;"' + $bin.ToUpperInvariant() + '\";C:\Windows\System32;' + $bin); After = "$bin;$other" },
    @{ Label = 'same prefix is preserved'; Before = "$bin-other;$bin\child;$other;$bin"; After = "$bin;$bin-other;$bin\child;$other" },
    @{ Label = 'other formatting preserved'; Before = (' "C:\Other Dir" ;relative-dir;;C:\Python\Scripts;' + $bin + ';'); After = ($bin + '; "C:\Other Dir" ;relative-dir;;C:\Python\Scripts;') },
    @{ Label = 'invalid absolute entry preserved'; Before = ('C:\Bad?Entry;' + $bin); After = ($bin + ';C:\Bad?Entry') },
    @{ Label = 'unrelated duplicates preserved'; Before = ('C:\Python\Scripts;' + $bin + ';C:\Python\Scripts'); After = ($bin + ';C:\Python\Scripts;C:\Python\Scripts') }
)) {
    $result = Move-AwfPathEntryFirst $case.Before $bin
    Assert-PathText $result $case.After $case.Label
    Assert-PathText (Move-AwfPathEntryFirst $result $bin) $result ($case.Label + ' is idempotent')
}

# Read an existing environment variable only. No fixture changes environment.
if ($env:LOCALAPPDATA) {
    $environmentBin = [Environment]::ExpandEnvironmentVariables('%LOCALAPPDATA%\AWF\bin')
    $expectedBin = ConvertTo-AwfCanonicalWindowsPath $environmentBin
    $withVariable = 'C:\Python\Scripts;"%LOCALAPPDATA%\AWF\bin\";C:\Windows\System32'
    Assert-PathText (Move-AwfPathEntryFirst $withVariable $environmentBin) ($expectedBin + ';' + $other) 'quoted environment equivalent'
}

$launcher = $bin + '\awf.exe'
foreach ($case in @(
    @{ Type = 'Application'; Path = $launcher; Warn = 0 },
    @{ Type = 'Application'; Path = $launcher.ToUpperInvariant(); Warn = 0 },
    @{ Type = 'Application'; Path = 'C:\Python\Scripts\awf.exe'; Warn = 1 },
    @{ Type = 'Alias'; Path = ''; Warn = 1 },
    @{ Type = 'Function'; Path = ''; Warn = 1 },
    @{ Type = 'Missing'; Path = ''; Warn = 1 }
)) {
    & {
        $PSModuleAutoLoadingPreference = 'All'
        $counts = @{ Warning = 0; AutoLoad = '' }
        function Get-Command {
            $counts.AutoLoad = $PSModuleAutoLoadingPreference
            if ($case.Type -ceq 'Missing') { return $null }
            return [pscustomobject] @{ CommandType = $case.Type; Path = $case.Path }
        }
        function Write-Warning { $counts.Warning++ }
        Warn-AwfCommandShadowing $launcher
        Assert-PathText $counts.AutoLoad 'None' 'lookup disables module auto-import'
        Assert-PathText $PSModuleAutoLoadingPreference 'All' 'caller module preference is preserved'
        if ($counts.Warning -ne $case.Warn) { throw "TEST FAILED: shadow warning for $($case.Type)" }
    }
}
Write-Host 'Pure AWF-only PATH promotion, preservation, duplicate, idempotence, and mocked shadow-warning tests passed. No PATH or registry changes were made.'
