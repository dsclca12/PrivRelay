param(
    [string]$Listen = '127.0.0.1:8787',
    [string]$Classifier = $env:CLASSIFIER_URL
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$goCommand = Get-Command go -ErrorAction SilentlyContinue
$goExe = if ($goCommand) { $goCommand.Source } else { Join-Path $root '.tools/go/bin/go.exe' }
if (!(Test-Path -LiteralPath $goExe)) { throw 'Install Go 1.25 or add go to PATH.' }
Push-Location $root
try {
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
    $serverArgs = @('-listen', $Listen, '-data', (Join-Path $root 'server/data/privrelay.enc'), '-web', (Join-Path $root 'web_client/dist'))
    if ($Classifier) { $serverArgs += @('-classifier', $Classifier) }
    & ./artifacts/privrelay-server.exe @serverArgs
} finally { Pop-Location }
