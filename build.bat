@echo off
chcp 65001 >nul
title MediaSegmenter 打包构建

cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1" %*
if errorlevel 1 (
    echo.
    echo 执行过程中发生错误！
    pause
)
