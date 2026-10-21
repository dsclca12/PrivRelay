param(
    [string]$Listen = '127.0.0.1:8787',
    [string]$Classifier = $env:CLASSIFIER_URL,
    [string]$Data = '',
    [switch]$WithoutClassifier
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$goCommand = Get-Command go -ErrorAction SilentlyContinue
$goExe = if ($goCommand) { $goCommand.Source } else { Join-Path $root '.tools/go/bin/go.exe' }
if (!(Test-Path -LiteralPath $goExe)) { throw 'Install Go 1.25 or add go to PATH.' }
Push-Location $root
$classifierProcess = $null
try {
    if ($WithoutClassifier) { $Classifier = '' }
    elseif (!$Classifier) {
        $Classifier = 'http://127.0.0.1:18788'
        $existing = $false
        try {
            $schema = Invoke-RestMethod "$Classifier/openapi.json" -TimeoutSec 2
            if (!$schema.paths.'/sms/score') { throw 'Existing classifier does not implement /sms/score.' }
            $existing = $true
        } catch {
            if ($_.Exception.Message -eq 'Existing classifier does not implement /sms/score.') { throw }
        }
        if (!$existing) { $classifierProcess = & "$PSScriptRoot/start-classifier.ps1" -Background }
    }
    if (!(Test-Path 'web_client/node_modules')) {
        & npm.cmd ci --prefix web_client
        if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
    }
    & npm.cmd run build --prefix web_client
    if ($LASTEXITCODE -ne 0) { throw 'Web build failed' }
    New-Item -ItemType Directory -Force artifacts | Out-Null
    Push-Location server
    try {
        & $goExe build -o ../artifacts/privrelay-server.exe .
        if ($LASTEXITCODE -ne 0) { throw 'Server build failed' }
    } finally { Pop-Location }
    Write-Host "Open http://$Listen in your browser. Pair using the code below."
    if (!$Data) { $Data = Join-Path $root 'server/data/privrelay.enc' }
    $serverArgs = @('-listen', $Listen, '-data', $Data, '-web', (Join-Path $root 'web_client/dist'))
    if ($Classifier) { $serverArgs += @('-classifier', $Classifier) }
    else { $serverArgs += @('-classifier', '') }
    & ./artifacts/privrelay-server.exe @serverArgs
} finally {
    if ($classifierProcess -and !$classifierProcess.HasExited) { Stop-Process -Id $classifierProcess.Id }
    Pop-Location
}
