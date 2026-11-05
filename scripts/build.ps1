<#
.SYNOPSIS
    Builds LOOP into dist\LOOP\LOOP.exe (a one-folder PyInstaller build).

.DESCRIPTION
    Creates .venv if needed, installs the project with build and test extras,
    runs the tests, then runs PyInstaller with loop.spec.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\build.ps1
    powershell -ExecutionPolicy Bypass -File scripts\build.ps1 -SkipTests -Zip
#>
param(
    [switch]$SkipTests,
    [switch]$Zip
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Creating virtual environment..."
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Python 3.12 is required (py -3.12 was not found)." }
}

Write-Host "Installing dependencies..."
& $python -m pip install --quiet --upgrade pip
& $python -m pip install --quiet -e ".[dev,build]"
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }

if (-not $SkipTests) {
    Write-Host "Running tests..."
    & $python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Tests failed; build aborted." }
}

$running = Get-Process LOOP -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path.StartsWith((Join-Path $root "dist\LOOP"), "OrdinalIgnoreCase") }
if ($running) { throw "LOOP is running from dist\LOOP. Close it first; Windows locks a running executable." }

Write-Host "Building with PyInstaller..."
& $python -m PyInstaller loop.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

$version = & $python -c "import loop; print(loop.__version__)"
if ($Zip) {
    $archive = Join-Path $root "dist\LOOP-$version-windows.zip"
    # Antivirus software often scans freshly built files for a few seconds, locking them.
    for ($attempt = 1; ; $attempt++) {
        try {
            Compress-Archive -Path (Join-Path $root "dist\LOOP") -DestinationPath $archive -Force -ErrorAction Stop
            break
        } catch {
            if ($attempt -ge 5) { throw }
            Write-Host "Archive attempt $attempt failed (files in use); retrying..."
            Start-Sleep -Seconds 3
        }
    }
    Write-Host "Archive: $archive"
}
Write-Host "Done: dist\LOOP\LOOP.exe (version $version)"
