$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$PyInstaller = Join-Path $Root ".venv\Scripts\pyinstaller.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "未找到 .venv。请先在项目根目录运行 run.bat 或创建虚拟环境。"
}
if (-not (Test-Path -LiteralPath $PyInstaller)) {
    throw "未安装 PyInstaller。请先运行: .\.venv\Scripts\python.exe -m pip install -e .[build]"
}

Push-Location $Root
try {
    & $PyInstaller --noconfirm --clean "packaging\paperflow.spec"
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败" }
    $Exe = Join-Path $Root "dist\PaperFlow\PaperFlow.exe"
    if (-not (Test-Path -LiteralPath $Exe)) { throw "构建完成但未找到 $Exe" }
    Write-Host ""
    Write-Host "构建完成：$Exe" -ForegroundColor Green
    Write-Host "整个 dist\PaperFlow 目录即为便携版；不要只复制 exe。"
} finally {
    Pop-Location
}