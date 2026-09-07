[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "       MediaSegmenter 打包脚本" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1/3] 正在检查并安装必要的依赖..." -ForegroundColor Yellow
pip install -r requirements.txt
pip install pyinstaller

Write-Host "`n[2/3] 正在清理旧的构建文件 (可选)..." -ForegroundColor Yellow
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
if (Test-Path "MediaSegmenter.spec") { Remove-Item -Force "MediaSegmenter.spec" }

Write-Host "`n[3/3] 正在使用 PyInstaller 进行打包..." -ForegroundColor Yellow
python build.py

if ($LASTEXITCODE -ne 0) {
    Write-Host "`n=========================================" -ForegroundColor Red
    Write-Host "打包失败！请检查上述报错信息。" -ForegroundColor Red
    Write-Host "=========================================" -ForegroundColor Red
} else {
    Write-Host "`n=========================================" -ForegroundColor Green
    Write-Host "打包完成！请在 dist 目录下查看生成的 .exe 文件。" -ForegroundColor Green
    Write-Host "=========================================" -ForegroundColor Green
}

Read-Host -Prompt "按 Enter 键退出"
