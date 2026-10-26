$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = Join-Path $root ".venv"
$python = Join-Path $venv "Scripts\python.exe"
$marker = Join-Path $venv ".paperflow-installed"

if (-not (Test-Path -LiteralPath $python)) {
    Write-Host "Creating Python 3.12 virtual environment..."
    py -3.12 -m venv $venv
}

if (-not (Test-Path -LiteralPath $marker)) {
    Write-Host "Installing PaperFlow and dependencies (first run only)..."
    $env:UV_CACHE_DIR = Join-Path $root ".uv-cache"
    $uv = Join-Path $venv "Scripts\uv.exe"
    if (-not (Test-Path -LiteralPath $uv)) {
        Write-Host "Installing uv package manager..."
        & $python -m pip install --disable-pip-version-check --no-deps uv
        if ($LASTEXITCODE -ne 0) {
            throw "Could not install uv."
        }
    }
    & $uv pip install --python $python -e $root
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed."
    }
    New-Item -ItemType File -Path $marker -Force | Out-Null
}

& $python -m paperflow @args
exit $LASTEXITCODE