param(
    [string]$Edition = ""
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# 切换到脚本所在目录，防止跨目录调用定位失败
Set-Location -Path $PSScriptRoot

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "       MediaSegmenter 自动化构建脚本" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1/3] 正在检查并安装必要的依赖..." -ForegroundColor Yellow
if (Test-Path "requirements.txt") {
    pip install -r requirements.txt
} else {
    Write-Host "未找到 requirements.txt，已跳过..." -ForegroundColor Yellow
}
pip install pyinstaller pefile

Write-Host "`n[2/3] 正在清理历史构建产物与临时缓存..." -ForegroundColor Yellow
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
Get-ChildItem -Path . -Filter "*.spec" | Remove-Item -Force

Write-Host "`n[3/3] 正在执行 Python 单文件自解压打包流程..." -ForegroundColor Yellow
python build.py

if ($LASTEXITCODE -ne 0) {
    Write-Host "`n=========================================" -ForegroundColor Red
    Write-Host "❌ 打包失败！请检查上述日志排查错误。" -ForegroundColor Red
    Write-Host "=========================================" -ForegroundColor Red
} else {
    Write-Host "`n=========================================" -ForegroundColor Green
    Write-Host "✅ 单文件打包完成！独立运行程序位于 dist 目录。" -ForegroundColor Green
    Write-Host "=========================================" -ForegroundColor Green
}

Read-Host -Prompt "按 Enter 键退出"
