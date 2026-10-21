param([switch]$SkipUpstreamUnit, [switch]$AuditDependencies)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$reportDirectory = Join-Path $root ('artifacts/non-android-tests-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Force $reportDirectory | Out-Null
$goCommand = Get-Command go -ErrorAction SilentlyContinue
$goExe = if ($goCommand) { $goCommand.Source } else { Join-Path $root '.tools/go/bin/go.exe' }
$pythonExe = Join-Path $root '.tools/classifier-runtime/Scripts/python.exe'
if (!(Test-Path $pythonExe)) { throw 'Run tools/start-classifier.ps1 once to prepare the pinned Python runtime.' }
$results = [System.Collections.Generic.List[object]]::new()
function Invoke-Check([string]$Name, [string]$Executable, [string[]]$Arguments, [string]$WorkingDirectory = $root) {
    $log = Join-Path $reportDirectory ($Name + '.log')
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $exitCode = 1
    Push-Location $WorkingDirectory
    try {
        & $Executable @Arguments *> $log
        $exitCode = $LASTEXITCODE
    } catch { $_ | Out-File -FilePath $log -Append -Encoding utf8 }
    finally { Pop-Location }
    $watch.Stop()
    $results.Add([pscustomobject]@{ name=$Name; passed=($exitCode -eq 0); exit_code=$exitCode; milliseconds=$watch.ElapsedMilliseconds; log=$log })
    Write-Host "$(if ($exitCode -eq 0) {'PASS'} else {'FAIL'}) $Name ($($watch.ElapsedMilliseconds) ms)"
    if ($exitCode -ne 0) { Get-Content $log -Tail 12 | Out-Host }
}
Invoke-Check 'source-integrity' $pythonExe @('tools/verify_upstream.py')
Invoke-Check 'go-race-coverage' $goExe @('test','-race','./...','-count=1','-timeout=45s',"-coverprofile=$reportDirectory/go.cover") (Join-Path $root 'server')
Invoke-Check 'go-vet' $goExe @('vet','./...') (Join-Path $root 'server')
Invoke-Check 'go-build' $goExe @('build','-o',(Join-Path $root 'artifacts/privrelay-server.exe'),'.') (Join-Path $root 'server')
if (!(Test-Path (Join-Path $root 'web_client/node_modules'))) { Invoke-Check 'web-dependencies' 'npm.cmd' @('ci','--prefix','web_client') }
Invoke-Check 'web-state' 'npm.cmd' @('test','--prefix','web_client')
Invoke-Check 'web-production-build' 'npm.cmd' @('run','build','--prefix','web_client')
Invoke-Check 'real-model-auth-load-recovery' $pythonExe @('tools/test_classifier.py')
Invoke-Check 'web-real-process' 'node' @('tools/smoke_web.mjs')
if ($AuditDependencies) {
    Invoke-Check 'npm-audit' 'npm.cmd' @('audit','--prefix','web_client','--json')
    Invoke-Check 'go-vulnerabilities' $goExe @('run','golang.org/x/vuln/cmd/govulncheck@v1.9.0','-json','./...') (Join-Path $root 'server')
    if (Get-Command uvx -ErrorAction SilentlyContinue) {
        Invoke-Check 'python-audit' 'uvx' @('pip-audit==2.10.1','-r','requirements/classifier-runtime.txt','--no-deps','--disable-pip','--format=json')
    } else {
        $results.Add([pscustomobject]@{ name='python-audit'; passed=$null; reason='uvx unavailable; Python vulnerability audit not run' })
    }
}
if (!$SkipUpstreamUnit) {
    $upstreamArgs = @('-m','pytest','integrations/PrivateSMS-Classifier/tests','-q',"--junitxml=$reportDirectory/upstream.xml")
    # The upstream benchmark imports POSIX resource at collection time.
    if ($env:OS -eq 'Windows_NT') { $upstreamArgs += '--ignore=integrations/PrivateSMS-Classifier/tests/test_benchmark.py' }
    Invoke-Check 'upstream-unit' $pythonExe $upstreamArgs
}
if (Get-Command docker -ErrorAction SilentlyContinue) {
    Invoke-Check 'compose-config' 'docker' @('compose','config','--quiet')
} else {
    $results.Add([pscustomobject]@{ name='docker-runtime'; passed=$null; reason='Docker not installed; image build/container tests not run' })
}
Invoke-Check 'diff-check' 'git' @('diff','--check')
$report = [pscustomobject]@{
    scope='non-Android, synthetic isolated data only';
    upstream_commit='87f5874057f12756c7c5a0cc2544b04320fbf591';
    results=$results;
    limitations=@('Windows upstream POSIX permission assertions may fail; failures are retained, never marked passed.', 'Windows cannot collect the resource-dependent upstream benchmark module.', 'Docker config validation, when available, does not prove image/container runtime correctness.')
}
$report | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $reportDirectory 'report.json') -Encoding utf8
Write-Host "Report: $reportDirectory/report.json"
if ($results | Where-Object { $_.passed -eq $false }) { exit 1 }
