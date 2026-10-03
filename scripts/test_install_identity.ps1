#requires -Version 5.1
<#
Read-only native identity gate. Run with the independently expected API identity
in each real host; NO_PACKAGE does NOT establish absence of filesystem
redirection. This never invokes bootstrap, creates a stage, or touches AWF.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('NoPackage', 'Packaged')]
    [string] $ExpectedIdentity
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'Run this read-only identity gate in native Windows PowerShell.'
}
. (Join-Path $PSScriptRoot 'install.ps1')
$status = Get-AwfPackageIdentityStatus
if ($ExpectedIdentity -ceq 'NoPackage') {
    if ($status -ne 15700) { throw "Expected APPMODEL_ERROR_NO_PACKAGE; observed Windows status $status." }
    Assert-AwfUnpackagedProcess
} else {
    if ($status -ne 0 -and $status -ne 122) { throw "Expected actual package identity; observed Windows status $status." }
    $rejected = $false
    try { Assert-AwfUnpackagedProcess } catch {
        if (-not $_.Exception.Message.StartsWith('This terminal is running inside a packaged app')) { throw }
        $rejected = $true
    }
    if (-not $rejected) { throw 'Actual package identity was not rejected.' }
}
Write-Host "Real read-only identity gate passed: $ExpectedIdentity (status $status). This is not a filesystem-redirection or installation acceptance result."
