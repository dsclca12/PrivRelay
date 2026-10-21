param(
    [int]$Port = 18788,
    [string]$Python = 'python',
    [string]$FeedbackDb = '',
    [switch]$Background
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$source = Join-Path $root 'integrations/PrivateSMS-Classifier'
$runtime = Join-Path $root '.tools/classifier-runtime'
$runtimePython = Join-Path $runtime 'Scripts/python.exe'
if (!(Test-Path "$source/src/privatesms/api/app.py")) { throw 'Missing vendored PrivateSMS-Classifier source.' }
if (!(Test-Path $runtimePython)) {
    & $Python -c "import os; assert hasattr(os, 'fchmod'), 'Windows needs Python 3.13+ for the upstream API'"
    if ($LASTEXITCODE -ne 0) { throw 'Use Python 3.13+ on Windows (3.14 tested).' }
    & $Python -m venv $runtime
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create classifier environment.' }
}
$requirements = Join-Path $root 'requirements/classifier-runtime.txt'
$fingerprint = (Get-FileHash $requirements -Algorithm SHA256).Hash
$marker = Join-Path $runtime 'privrelay-runtime.sha256'
if (!(Test-Path $marker) -or (Get-Content $marker -Raw).Trim() -ne $fingerprint) {
    & $runtimePython -c "import pip" 2>$null
    if ($LASTEXITCODE -ne 0) {
        & $runtimePython -m ensurepip --upgrade | Out-Host
        if ($LASTEXITCODE -ne 0) { throw 'Cannot initialize pip in classifier environment.' }
    }
    & $runtimePython -m pip install -r $requirements | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Classifier dependencies failed to install.' }
    & $runtimePython -m pip install --no-deps --no-build-isolation -e $source | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Upstream package failed to install.' }
    Set-Content $marker $fingerprint -Encoding ascii
}
if (!$FeedbackDb) { $FeedbackDb = Join-Path $root 'data/classifier-feedback.sqlite3' }
$launcher = Join-Path $root 'tools/windows_classifier.py'
# The Go server uses CLASSIFIER_API_KEY; the upstream service uses PRIVATESMS_API_KEY.
if ($env:CLASSIFIER_API_KEY) { $env:PRIVATESMS_API_KEY = $env:CLASSIFIER_API_KEY }
if (!$Background) {
    & $runtimePython $launcher --port $Port --feedback-db $FeedbackDb
    exit $LASTEXITCODE
}
New-Item -ItemType Directory -Force (Join-Path $root 'artifacts') | Out-Null
$process = Start-Process -FilePath $runtimePython -ArgumentList @("`"$launcher`"", '--port', "$Port", '--feedback-db', "`"$FeedbackDb`"") -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $root "artifacts/classifier-$Port.stdout.log") -RedirectStandardError (Join-Path $root "artifacts/classifier-$Port.stderr.log")
try {
    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        if ($process.HasExited) { throw "Classifier exited; see artifacts/classifier-$Port.stderr.log" }
        try {
            $health = Invoke-RestMethod "http://127.0.0.1:$Port/healthz" -TimeoutSec 2
            if ($health.status -eq 'ok') { $ready = $true; break }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
    if (!$ready) { throw 'Classifier startup timed out.' }
    return $process
} catch {
    if (!$process.HasExited) { Stop-Process -Id $process.Id }
    throw
}
