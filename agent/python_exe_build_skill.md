# 🤖 SKILL: Python EXE 打包构建标准流程

## 🎯 核心目标
指导 Agent 如何为 Python 应用程序（特别是 GUI 桌面应用）构建标准化、可复用的 `.exe` 打包流程。该流程基于 PyInstaller，并采用 `PowerShell 脚本 + Python 打包脚本` 的双层架构，以确保跨平台开发体验的流畅性、依赖收集的完整性以及构建过程的自动化。

## 🧩 标准架构设计
一个高复用性、标准的 Python 项目打包架构应包含以下核心组件：
1. **`build.ps1` (或 `build.bat`/`build.sh`)**: 顶层构建入口。负责环境准备、依赖安装、构建目录清理、触发打包，以及构建结果的校验与状态提示。
2. **`build.py`**: 核心打包配置。通过 Python 代码调用 `PyInstaller.__main__`，将原本极长且难以维护的命令行参数转化为易读、易扩展的代码结构。
3. **`requirements.txt`**: 明确的依赖列表。
4. **`.spec` 文件**: PyInstaller 自动生成（或后期自定义）的打包配置文件，用于处理更复杂的数据文件依赖和二进制文件挂载。

## 🚀 Agent 执行工作流 (SOP)

当面临“为这个 Python 项目打包成 exe”、“配置构建过程”或类似需求时，Agent 应严格遵循以下步骤：

### Step 1: 分析项目结构与依赖环境
- **确定入口**：识别项目的主入口文件（通常为 `main.py` 或 `app.py`）。
- **交互方式**：识别项目是否为 GUI 应用。如果是 GUI（如 Tkinter, PyQt, CustomTkinter 等），必须使用 `--windowed`（或 `--noconsole`）参数隐藏背后的黑色控制台窗口；如果是 CLI 工具，则保留控制台。
- **特殊资源识别**：分析代码中是否引入了包含静态资源的特殊第三方库（如 `customtkinter` 需要主题和字体，`mediapipe` 需要模型文件等）。这些库通常需要 `--collect-all` 或在 `.spec` 中通过 `datas` 处理。

### Step 2: 生成/更新打包配置脚本 (`build.py`)
不要让用户在终端手敲或复制又长又容易出错的 `pyinstaller ...` 命令，应始终创建或维护一个 `build.py` 文件。
**优势**: 配置可版本控制，参数结构清晰，便于动态计算路径。
**标准模板**:
```python
import os
import PyInstaller.__main__

# 配置打包选项
options = [
    'main.py',                 # 替换为实际的主入口文件
    '--name=YourAppName',      # 替换为期望的输出 exe 名称
    '--windowed',              # 如果是纯命令行工具，请务必移除此行
    '--onefile',               # 打包为单文件 (产物整洁，但启动略慢)
    '--clean',                 # 构建前清理 PyInstaller 的缓存
    
    # --- 特殊依赖和资源的收集 (根据项目情况添加) ---
    # '--collect-all', 'customtkinter', 
    # '--hidden-import', 'PIL._tkinter_finder',
    # '--add-data', 'assets;assets',  # 格式: 源路径;目标路径(Windows用分号)
]

PyInstaller.__main__.run(options)
```

### Step 3: 生成自动化构建脚本 (`build.ps1`)
提供对开发者友好的“一键式”构建脚本，负责统筹环境并提供明确的控制台反馈。
**标准模板**:
```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "       [应用名称] 自动化构建脚本" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1/3] 正在检查并安装必要的依赖..." -ForegroundColor Yellow
pip install -r requirements.txt
pip install pyinstaller

Write-Host "`n[2/3] 正在清理历史构建产物..." -ForegroundColor Yellow
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
if (Test-Path "[应用名称].spec") { Remove-Item -Force "[应用名称].spec" }

Write-Host "`n[3/3] 正在执行 Python 打包流程..." -ForegroundColor Yellow
python build.py

if ($LASTEXITCODE -ne 0) {
    Write-Host "`n=========================================" -ForegroundColor Red
    Write-Host "❌ 打包失败！请检查上述日志排查错误。" -ForegroundColor Red
    Write-Host "=========================================" -ForegroundColor Red
} else {
    Write-Host "`n=========================================" -ForegroundColor Green
    Write-Host "✅ 打包完成！请在 dist 目录下查看生成的 .exe 文件。" -ForegroundColor Green
    Write-Host "=========================================" -ForegroundColor Green
}

Read-Host -Prompt "按 Enter 键退出"
```

### Step 4: 规范化输出与项目清理
- **更新 `.gitignore`**：确保 `build/`, `dist/`, 和 `*.spec` 被加入忽略列表，避免将体积庞大且不必要的二进制产物提交到 Git。
- **环境隔离提示**：建议在虚拟环境 (venv, conda) 中执行该脚本，以避免系统级别冗余库被打包导致 `.exe` 体积臃肿。

## 💡 最佳实践与避坑指南 (Troubleshooting)

1. **资源路径错误 (找不到文件)**
   - **现象**: 在 IDE 里运行正常，打包成 exe 后报错 `FileNotFoundError`。
   - **原因**: `--onefile` 模式下，程序运行前会将内容解压到系统的临时目录（如 `%TEMP%\_MEIxxxxxx`），原本的相对路径将失效。
   - **解决方案 (Agent 应主动提供此代码块)**:
     ```python
     import sys
     import os
     
     def get_resource_path(relative_path):
         """ 获取打包后或开发中的绝对路径 """
         if hasattr(sys, '_MEIPASS'):
             # PyInstaller 运行时所在的临时目录
             return os.path.join(sys._MEIPASS, relative_path)
         # 开发时的当前目录
         return os.path.abspath(relative_path)
     ```

2. **隐式依赖缺失 (ModuleNotFoundError)**
   - **现象**: 运行时提示缺少某个模块。
   - **原因**: 某些库使用动态导入（如 `importlib`、反射等），PyInstaller 静态分析时无法发现。
   - **解决方案**: 在 `build.py` 的 options 中追加 `--hidden-import=模块名`。

3. **包体积过大 / 启动过慢**
   - **原因**: 打包了整个环境的无关库（如 Pandas, Torch 等），或 `--onefile` 解压耗时。
   - **解决方案**: 
     - 要求用户创建一个纯净的虚拟环境，仅安装 `requirements.txt`。
     - 若启动速度至关重要，可将 `--onefile` 替换为 `--onedir`（单目录模式）。

4. **第三方 UI 框架 (CustomTkinter) 挂载**
   - 包含复杂主题、字体资产的包，必须在 `build.py` 中添加 `'--collect-all', 'customtkinter'`，否则打包后界面将因丢失资产而无法渲染或报错。
