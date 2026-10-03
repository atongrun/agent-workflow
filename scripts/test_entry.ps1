#requires -Version 5.1
# Fresh-process native regressions for actual IEX binding and real Read-Host EOF.
# The initial irm transport reads the exact local script; IEX receives unmodified
# bytes. Child-only LOCALAPPDATA is empty, so real bootstrap must stop at its
# existing profile guard, before staging, network, install or PATH writes.
# No production installation/configuration/credential/registry is modified.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'Run this regression suite in native Windows PowerShell 5.1 or PowerShell 7.'
}
$installer = Join-Path $PSScriptRoot 'install.ps1'
$hostExecutable = Join-Path $PSHOME 'powershell.exe'
if (-not [IO.File]::Exists($hostExecutable)) { $hostExecutable = Join-Path $PSHOME 'pwsh.exe' }
if (-not [IO.File]::Exists($hostExecutable)) { throw 'Current native PowerShell executable is unavailable.' }
$quotedInstaller = "'" + $installer.Replace("'", "''") + "'"

function Invoke-FreshPowerShell([string] $Code, [string] $InputText = '') {
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Code))
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $hostExecutable
    $start.Arguments = '-NoLogo -NoProfile -EncodedCommand ' + $encoded
    $start.UseShellExecute = $false
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.CreateNoWindow = $true
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $start
    try {
        if (-not $process.Start()) { throw 'Cannot start isolated PowerShell fixture.' }
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if ($InputText) { $process.StandardInput.Write($InputText) }
        # Empty input closes without writing a byte: real EOF, not a Read-Host mock.
        $process.StandardInput.Close()
        if (-not $process.WaitForExit(30000)) {
            $process.Kill()
            $process.WaitForExit()
            throw 'Isolated PowerShell fixture timed out.'
        }
        $result = [pscustomobject] @{ ExitCode = $process.ExitCode; Out = $stdout.Result; Err = $stderr.Result }
        return $result
    } finally { $process.Dispose() }
}
function Assert-FreshResult($Result, [string] $Marker, [string] $Label) {
    if ($Result.ExitCode -ne 0 -or -not $Result.Out.Contains($Marker)) {
        throw "$Label failed (exit $($Result.ExitCode)). stdout: $($Result.Out) stderr: $($Result.Err)"
    }
}

$entry = @'
$ErrorActionPreference = 'Stop'
$fixtureInstaller = __INSTALLER__
function Invoke-RestMethod([string] $Uri) {
    if ($Uri -cne 'https://raw.githubusercontent.com/atongrun/agent-workflow/awf/go-v1/scripts/install.ps1') {
        throw 'Unexpected fixture request.'
    }
    return [IO.File]::ReadAllText($fixtureInstaller)
}
# Process-local only; the real native/profile checks remain in the unmodified
# script. Reaching the exact guard proves the no-argument IEX entry succeeded.
$env:LOCALAPPDATA = ''
try {
    irm 'https://raw.githubusercontent.com/atongrun/agent-workflow/awf/go-v1/scripts/install.ps1' | iex
} catch {
    if ($_.Exception.Message -ceq 'LOCALAPPDATA must match the current Windows user profile directory.') {
        [Console]::Out.WriteLine('AWF_IEX_ENTRY_REACHED')
        exit 0
    }
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 41
}
[Console]::Error.WriteLine('Unexpected bootstrap success; profile guard was not reached.')
exit 42
'@
Assert-FreshResult (Invoke-FreshPowerShell $entry.Replace('__INSTALLER__', $quotedInstaller)) 'AWF_IEX_ENTRY_REACHED' 'Unmodified no-argument irm | iex'

$badPin = @'
$ErrorActionPreference = 'Stop'
$fixtureCode = [IO.File]::ReadAllText(__INSTALLER__)
$env:LOCALAPPDATA = ''
try {
    & ([ScriptBlock]::Create($fixtureCode)) -Sha256 'invalid-pin'
} catch {
    if ($_.Exception.Message -ceq 'Sha256 must be exactly 64 hexadecimal digits when supplied.') {
        [Console]::Out.WriteLine('AWF_BAD_PIN_REJECTED')
        exit 0
    }
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 43
}
exit 44
'@
Assert-FreshResult (Invoke-FreshPowerShell $badPin.Replace('__INSTALLER__', $quotedInstaller)) 'AWF_BAD_PIN_REJECTED' 'Malformed pin before profile/staging'

$scriptCall = @'
$ErrorActionPreference = 'Stop'
$fixtureCode = [IO.File]::ReadAllText(__INSTALLER__)
$env:LOCALAPPDATA = ''
try {
    & ([ScriptBlock]::Create($fixtureCode)) __PIN_ARGUMENT__
} catch {
    if ($_.Exception.Message -ceq 'LOCALAPPDATA must match the current Windows user profile directory.') {
        [Console]::Out.WriteLine('AWF_OPTIONAL_PIN_ENTRY_REACHED')
        exit 0
    }
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 47
}
exit 48
'@
foreach ($pinArgument in @('', ("-Sha256 '" + ('a' * 64) + "'"), ("-Sha256 '" + ('A' * 64) + "'"))) {
    $code = $scriptCall.Replace('__INSTALLER__', $quotedInstaller).Replace('__PIN_ARGUMENT__', $pinArgument)
    Assert-FreshResult (Invoke-FreshPowerShell $code) 'AWF_OPTIONAL_PIN_ENTRY_REACHED' 'Omitted/valid pin reaches real entry'
}

$eof = @'
$ErrorActionPreference = 'Stop'
. __INSTALLER__
try {
    # Force only the helper's interactive branch to exercise actual Read-Host
    # EOF independently of the bootstrap's additional noninteractive guard.
    $answer = Confirm-AwfPreview 'v1.0.0-rc.2' $false $true
} catch {
    if ($_.Exception.Message -ceq 'Preview installation cancelled. Nothing was installed.') {
        [Console]::Out.WriteLine('AWF_REAL_READHOST_EOF_REJECTED')
        exit 0
    }
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 45
}
[Console]::Error.WriteLine('EOF unexpectedly returned preview approval.')
exit 46
'@
Assert-FreshResult (Invoke-FreshPowerShell $eof.Replace('__INSTALLER__', $quotedInstaller)) 'AWF_REAL_READHOST_EOF_REJECTED' 'Actual Read-Host with closed stdin'
$pipedApproval = @'
$ErrorActionPreference = 'Stop'
. __INSTALLER__
try {
    $answer = Confirm-AwfPreview 'v1.0.0-rc.2' $false (Test-AwfInteractive)
} catch {
    if ($_.Exception.Message.StartsWith('The Go channel currently selects a preview.')) {
        [Console]::Out.WriteLine('AWF_PIPED_APPROVAL_REJECTED')
        exit 0
    }
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 49
}
[Console]::Error.WriteLine('Redirected input unexpectedly authorized preview installation.')
exit 50
'@
Assert-FreshResult (Invoke-FreshPowerShell $pipedApproval.Replace('__INSTALLER__', $quotedInstaller) "yes`n") 'AWF_PIPED_APPROVAL_REJECTED' 'Piped affirmative input is not interactive consent'
Write-Host 'Fresh-process no-argument IEX, malformed pin, and actual Read-Host EOF tests passed.'
