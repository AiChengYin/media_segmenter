@echo off
chcp 65001 >nul
echo =========================================
echo       MediaSegmenter 打包脚本
echo =========================================

echo [1/3] 正在检查并安装必要的依赖...
pip install -r requirements.txt
pip install pyinstaller

echo.
echo [2/3] 正在清理旧的构建文件 (可选)...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

echo.
echo [3/3] 正在使用 PyInstaller 进行打包...
python build.py

echo.
echo =========================================
echo 打包完成！请在 dist 目录下查看生成的 .exe 文件。
echo =========================================
pause
