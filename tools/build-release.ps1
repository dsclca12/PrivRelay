param(
    [ValidateSet('dev', 'prod')][string]$Flavor = 'dev',
    [switch]$SkipChecks
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$client = Join-Path $root 'android_client'
if ($Flavor -eq 'prod' -and !(Test-Path -LiteralPath (Join-Path $client 'android/key.properties'))) {
    throw 'Production release requires android_client/android/key.properties and your private signing key.'
}
$expected = (Get-Content -Raw (Join-Path $root '.fvmrc') | ConvertFrom-Json).flutter
$version = (& flutter --version --machine | ConvertFrom-Json)
if ($LASTEXITCODE -ne 0 -or $version.frameworkVersion -ne $expected) {
    throw "Use Flutter $expected from .fvmrc before creating a release."
}
$destination = Join-Path $root ("artifacts/releases/{0}-{1}" -f $Flavor, (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Path $destination | Out-Null
$symbols = Join-Path $destination 'symbols'
Push-Location $client
try {
    & flutter pub get --enforce-lockfile
    if ($LASTEXITCODE -ne 0) { throw 'Dependency resolution failed.' }
    if (!$SkipChecks) {
        & flutter analyze
        if ($LASTEXITCODE -ne 0) { throw 'Static analysis failed.' }
        & flutter test
        if ($LASTEXITCODE -ne 0) { throw 'Flutter tests failed.' }
    }
    & flutter build apk --release --flavor $Flavor --obfuscate "--split-debug-info=$symbols/apk"
    if ($LASTEXITCODE -ne 0) { throw 'APK build failed.' }
    Copy-Item -LiteralPath "build/app/outputs/flutter-apk/app-$Flavor-release.apk" -Destination $destination
    $apkMapping = "build/app/outputs/mapping/${Flavor}Release/mapping.txt"
    if (Test-Path -LiteralPath $apkMapping) {
        Copy-Item -LiteralPath $apkMapping -Destination (Join-Path $destination 'apk-r8-mapping.txt')
    }
    & flutter build appbundle --release --flavor $Flavor --obfuscate "--split-debug-info=$symbols/aab"
    if ($LASTEXITCODE -ne 0) { throw 'AAB build failed.' }
    Copy-Item -LiteralPath "build/app/outputs/bundle/${Flavor}Release/app-$Flavor-release.aab" -Destination $destination
    $mapping = "build/app/outputs/mapping/${Flavor}Release/mapping.txt"
    if (Test-Path -LiteralPath $mapping) {
        Copy-Item -LiteralPath $mapping -Destination (Join-Path $destination 'aab-r8-mapping.txt')
    }
    Copy-Item -LiteralPath 'pubspec.lock' -Destination $destination
    $files = @(Get-ChildItem -LiteralPath $destination -Recurse -File | ForEach-Object {
        @{ path = [IO.Path]::GetRelativePath($destination, $_.FullName); sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
    })
    $manifest = @{
        flavor = $Flavor
        created_at = (Get-Date).ToUniversalTime().ToString('o')
        flutter = $version.frameworkVersion
        dart = $version.dartSdkVersion
        package_version = ((Get-Content pubspec.yaml | Select-String '^version:').Line -replace '^version:\s*', '')
        revision = (& git rev-parse HEAD)
        working_tree_dirty = [bool](& git status --porcelain)
        checks_skipped = [bool]$SkipChecks
        distribution = $(if ($Flavor -eq 'prod') { 'operator-signed' } else { 'internal-test-only' })
        files = $files
    }
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $destination 'manifest.json') -Encoding utf8
    Write-Host "Release files and private symbols: $destination"
    if ($Flavor -eq 'dev') { Write-Host 'Dev artifacts are for internal testing; they are not production releases.' }
} finally {
    Pop-Location
}
