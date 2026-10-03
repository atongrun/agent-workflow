#requires -Version 5.1
# Disposable progress fixtures, no network or installed-root/PATH/registry writes.
# Run in both Windows PowerShell 5.1 and PowerShell 7. Pure reporter/download
# fixtures also work on PS7 outside Windows; no bootstrap/native code is run.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'install.ps1')

function Assert-Progress([bool] $Condition, [string] $Message) {
    if (-not $Condition) { throw "TEST FAILED: $Message" }
}
function New-ProgressFixture([bool] $Interactive) {
    $progress = New-AwfBootstrapProgress
    $progress.Interactive = $Interactive
    # Deterministic clock: tests never sleep or depend on machine speed.
    $progress.Clock = [pscustomobject] @{ ElapsedMilliseconds = [long] 0 }
    return $progress
}

$oldError = [Console]::Error
$captured = New-Object IO.StringWriter
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('awf-progress-test-' + [Guid]::NewGuid().ToString('N'))
[void] [IO.Directory]::CreateDirectory($temporary)
try {
    [Console]::SetError($captured)
    $progress = New-ProgressFixture $false
    $stdout = @(
        Set-AwfBootstrapStage $progress 'Downloading release metadata'
        Set-AwfBootstrapStage $progress 'Downloading release archive'
        for ($i = 0; $i -le 1000; $i++) { Write-AwfDownloadProgress $progress $i 1000 }
        Write-AwfDownloadProgress $progress 1000 1000 -Complete
        Set-AwfBootstrapStage $progress 'Verifying release archive'
        Set-AwfBootstrapStage $progress 'Extracting bootstrap'
        Set-AwfBootstrapStage $progress 'Launching installer'
        Close-AwfBootstrapProgress $progress
    )
    Assert-Progress ($stdout.Count -eq 0) 'all progress leaves the success/stdout pipeline untouched'
    Assert-Progress ($captured.ToString() -ceq '') 'non-TTY progress stays quiet without redraw spam'
    Assert-Progress ($progress.Stage -ceq 'Launching installer') 'non-TTY still retains stage context for errors'
    Stop-AwfBootstrapProgress $progress
    Assert-Progress ($captured.ToString() -ceq '') 'non-TTY failure feedback stays quiet and leaves the genuine error to the caller'

    $progress = New-ProgressFixture $true
    $stages = @('Downloading release metadata', 'Downloading release archive', 'Verifying release archive',
        'Extracting bootstrap', 'Launching installer', 'Checking installed launcher and refreshing shell PATH')
    foreach ($stage in $stages) { Set-AwfBootstrapStage $progress $stage }
    Close-AwfBootstrapProgress $progress
    $expected = ($stages | ForEach-Object { "`rAWF: " + $_ + '...' + [Environment]::NewLine }) -join ''
    Assert-Progress ($captured.ToString() -ceq $expected) 'TTY stage order includes post-native shell verification'

    [void] $captured.GetStringBuilder().Clear()
    $progress = New-ProgressFixture $true
    Set-AwfBootstrapStage $progress 'Downloading release archive'
    Write-AwfDownloadProgress $progress 250 1000
    Assert-Progress ($captured.ToString().Contains('250/1000 bytes (25%)')) 'known Content-Length reports bytes and percentage'
    Assert-Progress ($captured.ToString().Contains('[#####---------------]')) 'known Content-Length shows a compact ASCII bar'
    $before = $captured.ToString()
    for ($i = 251; $i -lt 500; $i++) { Write-AwfDownloadProgress $progress $i 1000 }
    Assert-Progress ($captured.ToString() -ceq $before) 'rapid chunk reports are throttled'
    $progress.Clock.ElapsedMilliseconds = 250
    Write-AwfDownloadProgress $progress 500 1000
    Assert-Progress ($captured.ToString().Contains('500/1000 bytes (50%)')) 'redraw resumes after 250 ms'
    $progress.Clock.ElapsedMilliseconds = 500
    Write-AwfDownloadProgress $progress 1000 1000
    Assert-Progress ($captured.ToString().Contains('(99%)') -and -not $captured.ToString().Contains('(100%)')) '100 percent is withheld until EOF and successful close'
    Write-AwfDownloadProgress $progress 1000 1000 -Complete
    Assert-Progress ($captured.ToString().Contains('1000/1000 bytes (100%)')) 'successful final update is not throttled'
    Assert-Progress ($captured.ToString().Contains('[####################]')) 'complete download fills its bar'
    Set-AwfBootstrapStage $progress 'Verifying release archive'
    Close-AwfBootstrapProgress $progress
    $before = $captured.ToString()
    Close-AwfBootstrapProgress $progress
    Assert-Progress ($captured.ToString() -ceq $before) 'closing the progress line twice emits no extra newline'
    Assert-Progress ($before.Contains('(100%)' + [Environment]::NewLine + "`rAWF: Verifying")) 'new stage does not overwrite the completed download'

    [void] $captured.GetStringBuilder().Clear()
    $progress = New-ProgressFixture $true
    Write-AwfDownloadProgress $progress 100MB 100MB -Complete
    Assert-Progress ($captured.ToString().TrimStart("`r").Length -lt 80) 'maximum allowed download size fits an 80-column terminal'
    Close-AwfBootstrapProgress $progress

    foreach ($length in @(-1, 0)) {
        [void] $captured.GetStringBuilder().Clear()
        $progress = New-ProgressFixture $true
        Set-AwfBootstrapStage $progress 'Downloading release archive'
        Write-AwfDownloadProgress $progress 65536 $length
        Write-AwfDownloadProgress $progress 131072 $length -Complete
        Close-AwfBootstrapProgress $progress
        Assert-Progress ($captured.ToString().Contains('131072 bytes')) 'unknown/zero length still reports bytes'
        Assert-Progress ($captured.ToString().Contains('(total unknown)')) 'unknown length is labeled explicitly'
        Assert-Progress (-not $captured.ToString().Contains('%')) 'unknown/zero length never fabricates a percentage'
    }

    foreach ($stage in @('Downloading release metadata', 'Downloading release archive', 'Verifying release archive', 'Extracting bootstrap', 'Launching installer')) {
        [void] $captured.GetStringBuilder().Clear()
        $progress = New-ProgressFixture $true
        Set-AwfBootstrapStage $progress $stage
        Stop-AwfBootstrapProgress $progress
        $text = $captured.ToString()
        Assert-Progress ($text.Contains('AWF: Failed during ' + $stage.ToLowerInvariant() + '.')) 'failure identifies the current stage'
        Assert-Progress ($text -notmatch '(?i)100%|completed|installed|done|https?://') 'failure adds no success marker or request details'
    }

    # A registered exact fake URL is intercepted entirely in this process. The
    # production downloader still executes its real origin/size/streaming checks.
    # No alternate download endpoint or injected client is added to production.
    if (-not ('AwfProgressFixture.Request' -as [type])) {
        Add-Type -TypeDefinition @'
#pragma warning disable
using System;
using System.IO;
using System.Net;
namespace AwfProgressFixture {
    public class Request : WebRequest, IWebRequestCreate {
        public static long DeclaredLength = 131072;
        public static long FailAt = -1;
        public static bool FailClose;
        public bool AllowAutoRedirect { get; set; }
        public int ReadWriteTimeout { get; set; }
        public string UserAgent { get; set; }
        public string Accept { get; set; }
        public override int Timeout { get; set; }
        public WebRequest Create(Uri uri) { return new Request(); }
        public override WebResponse GetResponse() { return new Response(); }
    }
    public class Response : WebResponse {
        public HttpStatusCode StatusCode { get { return HttpStatusCode.OK; } }
        public override long ContentLength { get { return Request.DeclaredLength; } set { } }
        public override Stream GetResponseStream() { return new Body(); }
        protected override void Dispose(bool disposing) {
            if (disposing && Request.FailClose) throw new IOException("fixture response close failed");
            base.Dispose(disposing);
        }
    }
    public class Body : MemoryStream {
        public Body() : base(new byte[131072], false) { }
        public override int Read(byte[] bytes, int offset, int count) {
            if (Request.FailAt >= 0 && Position >= Request.FailAt)
                throw new IOException("fixture stream interrupted");
            return base.Read(bytes, offset, count);
        }
    }
}
'@
    }
    $url = 'https://github.com/awf-progress-fixture-' + [Guid]::NewGuid().ToString('N') + '?token=DO_NOT_LOG'
    Assert-Progress ([Net.WebRequest]::RegisterPrefix($url, (New-Object AwfProgressFixture.Request))) 'exact isolated request fixture registered'
    foreach ($case in @('known', 'unknown', 'interrupted', 'size-limit', 'close-failure')) {
        [void] $captured.GetStringBuilder().Clear()
        $progress = New-ProgressFixture $true
        Set-AwfBootstrapStage $progress 'Downloading release archive'
        [AwfProgressFixture.Request]::DeclaredLength = 131072
        [AwfProgressFixture.Request]::FailAt = -1
        [AwfProgressFixture.Request]::FailClose = $false
        $limit = 1MB
        if ($case -ceq 'unknown') { [AwfProgressFixture.Request]::DeclaredLength = -1 }
        if ($case -ceq 'interrupted') { [AwfProgressFixture.Request]::FailAt = 65536 }
        if ($case -ceq 'size-limit') { $limit = 65536 }
        if ($case -ceq 'close-failure') { [AwfProgressFixture.Request]::FailClose = $true }
        $path = Join-Path $temporary ($case + '.bin')
        $failed = $false
        $stdout = @(
            try { Save-AwfOfficialDownload -Url $url -Destination $path -Limit $limit -Progress $progress }
            catch { $failed = $true; Stop-AwfBootstrapProgress $progress }
        )
        Close-AwfBootstrapProgress $progress
        Assert-Progress ($stdout.Count -eq 0) ('real download progress keeps stdout empty: ' + $case)
        $text = $captured.ToString()
        Assert-Progress (-not $text.Contains($url) -and -not $text.Contains('DO_NOT_LOG')) 'progress never exposes request URLs or tokens'
        if ($case -in @('known', 'unknown')) {
            Assert-Progress (-not $failed) ('fixture download succeeds: ' + $case)
            Assert-Progress ((Get-Item -LiteralPath $path).Length -eq 131072) 'progress does not change downloaded bytes'
            if ($case -ceq 'known') {
                Assert-Progress ($text.Contains('131072/131072 bytes (100%)')) 'real known-size download final count'
            } else {
                Assert-Progress ($text.Contains('131072 bytes') -and -not $text.Contains('%')) 'real unknown-size download has no invented percent'
            }
        } else {
            Assert-Progress $failed ('download error propagates: ' + $case)
            Assert-Progress ($text.Contains('Failed during downloading release archive.')) 'interrupted download identifies its stage'
            Assert-Progress (-not $text.Contains('(100%)')) 'failed download never reports full completion'
        }
    }

    # Broken stderr is observational only: it cannot turn installation into a
    # failure or cause stdout fallback. Restore the usable writer afterward.
    $closed = New-Object IO.StringWriter
    $closed.Dispose()
    [Console]::SetError($closed)
    $progress = New-ProgressFixture $true
    $stdout = @(Set-AwfBootstrapStage $progress 'Downloading release archive')
    Assert-Progress ($progress.Disabled -and $stdout.Count -eq 0) 'closed stderr disables progress without failing or falling back to stdout'
} finally {
    [Console]::SetError($oldError)
    $captured.Dispose()
    Remove-Item -LiteralPath $temporary -Recurse -Force
}
Write-Host 'Bootstrap stderr stages, throttling, known/unknown length, failure and stream-isolation fixtures passed.'
