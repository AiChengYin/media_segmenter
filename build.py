"""
MediaSegmenter PyInstaller 单文件自解压打包脚本
遵循 python-exe-build 工业级规范，全量适配 Windows Sandbox 纯净无依赖环境
"""
import os
import sys
import time
import shutil
import subprocess
import PyInstaller.__main__

# 解决 Windows 控制台输出编码问题
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

APP_NAME = "MediaSegmenter"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


def locate_ffmpeg_binaries() -> list:
    """
    多级探测 FFmpeg 所在的 bin 目录并收集 ffmpeg.exe, ffprobe.exe 及配套动态链接库 DLL (排除 ffplay 以瘦身)
    """
    candidates = []

    # 1. 环境变量
    env_path = os.environ.get('FFMPEG_PATH') or os.environ.get('FFMPEG_HOME')
    if env_path:
        if os.path.isfile(env_path):
            candidates.append(os.path.dirname(env_path))
        else:
            candidates.append(env_path)
            candidates.append(os.path.join(env_path, 'bin'))

    # 2. PATH 自动探测
    which_ffmpeg = shutil.which('ffmpeg')
    if which_ffmpeg:
        candidates.append(os.path.dirname(os.path.abspath(which_ffmpeg)))

    # 3. 常见候选路径
    candidates.extend([
        r"C:\sofware\ffmpeg\ffmpeg-master-latest-win64-gpl-shared\bin",
        r"C:\sofware\ffmpeg\ffmpeg-7.1.1-full_build\bin",
        r"C:\ffmpeg\bin",
        os.path.join(BASE_DIR, 'bin', 'ffmpeg'),
        os.path.join(BASE_DIR, 'ffmpeg_bin'),
    ])

    for c in candidates:
        if not c or not os.path.isdir(c):
            continue
        ffmpeg_exe = os.path.join(c, 'ffmpeg.exe')
        ffprobe_exe = os.path.join(c, 'ffprobe.exe')
        if os.path.isfile(ffmpeg_exe) and os.path.isfile(ffprobe_exe):
            files = [os.path.abspath(ffmpeg_exe), os.path.abspath(ffprobe_exe)]
            # 收集配套 DLL，排除无需使用的 ffplay.exe 瘦身
            for item in os.listdir(c):
                item_lower = item.lower()
                if item_lower == "ffplay.exe" or item_lower in ("ffmpeg.exe", "ffprobe.exe"):
                    continue
                full_p = os.path.join(c, item)
                if os.path.isfile(full_p) and item_lower.endswith('.dll'):
                    files.append(os.path.abspath(full_p))
            return files

    return []


def collect_vc_runtime_dlls() -> list:
    """
    自动收集 VC++ 核心运行时 DLL，确保在脱机、无任何预装运行库的纯净 Windows Sandbox 中稳定启动
    """
    dll_names = [
        "vcruntime140.dll",
        "vcruntime140_1.dll",
        "msvcp140.dll",
        "msvcp140_1.dll",
        "msvcp140_2.dll",
        "msvcp140_atomic_wait.dll",
        "msvcp140_codecvt_ids.dll",
    ]
    search_dirs = [
        os.path.dirname(sys.executable),
        r"C:\Windows\System32",
    ]
    found = {}
    for d in search_dirs:
        if not os.path.exists(d):
            continue
        for name in dll_names:
            if name not in found:
                p = os.path.join(d, name)
                if os.path.isfile(p):
                    found[name] = os.path.abspath(p)
    return list(found.values())


def main():
    print("=" * 66)
    print(f"  {APP_NAME} 工业级单文件自解压打包程序 (--onefile)")
    print("  全量适配 Windows Sandbox 纯净沙盒环境")
    print("=" * 66)

    dist_dir = os.path.join(BASE_DIR, "dist")
    os.makedirs(dist_dir, exist_ok=True)
    target_exe_name = f"{APP_NAME}.exe"
    target_exe_path = os.path.join(dist_dir, target_exe_name)

    # 1. 终结可能处于运行状态的旧进程，并休眠等待操作系统完全释放文件句柄
    kill_targets = [target_exe_name, "MediaSegmenter_v1.exe", "ffmpeg.exe", "ffprobe.exe"]
    for proc in kill_targets:
        try:
            subprocess.run(["taskkill", "/F", "/IM", proc], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    time.sleep(1.2)

    # 2. 清理旧版本单文件产物
    for old_exe in [target_exe_path, os.path.join(dist_dir, "MediaSegmenter_v1.exe")]:
        if os.path.exists(old_exe):
            try:
                os.remove(old_exe)
                print(f">>> [CLEAN] 已清理旧版本单文件: {old_exe}")
            except Exception as e:
                print(f">>> [CLEAN 警告] 清理旧单文件失败: {e}")

    # 3. 清理历史 onedir 散装目录（防止用户混淆或拷错旧目录）
    legacy_dir = os.path.join(dist_dir, APP_NAME)
    if os.path.exists(legacy_dir):
        print(f">>> [CLEAN] 正在清理历史 onedir 散装目录: {legacy_dir} ...")
        for _ in range(5):
            try:
                shutil.rmtree(legacy_dir)
                break
            except Exception:
                time.sleep(0.5)

    spec_file = os.path.join(BASE_DIR, f"{APP_NAME}.spec")
    if os.path.exists(spec_file):
        try:
            os.remove(spec_file)
        except Exception:
            pass

    # 4. 探测并收集内嵌二进制依赖 (FFmpeg 套件)
    ffmpeg_files = locate_ffmpeg_binaries()
    if not ffmpeg_files:
        print("\n[错误] 未能定位到有效的 FFmpeg 运行套件（必须包含 ffmpeg.exe 和 ffprobe.exe）！")
        print("请确保已安装 FFmpeg，或通过环境变量设置 FFMPEG_HOME/FFMPEG_PATH。")
        sys.exit(1)

    print(f"\n[1/4] 成功收集内嵌 FFmpeg 套件 ({len(ffmpeg_files)} 个二进制组件):")
    total_ff_size = 0
    for bf in ffmpeg_files:
        sz = os.path.getsize(bf)
        total_ff_size += sz
        print(f"  + {os.path.basename(bf)} ({sz / (1024*1024):.2f} MB)")
    print(f"  FFmpeg 组件总计大小: {total_ff_size / (1024*1024):.2f} MB")

    # 5. 收集 VC++ 核心运行库 DLL
    vc_dlls = collect_vc_runtime_dlls()
    print(f"\n[2/4] 成功检索 VC++ 沙盒兜底运行库 ({len(vc_dlls)} 个 DLL):")
    for dll_p in vc_dlls:
        print(f"  + {os.path.basename(dll_p)} -> {dll_p}")

    # 6. 配置 PyInstaller 单文件打包参数
    options = [
        'main.py',                  # 主入口文件
        f'--name={APP_NAME}',       # 生成的单文件 exe 名称
        '--windowed',               # GUI 应用隐藏后台控制台
        '--onefile',                # 单文件自解压模式 (Windows Sandbox 独立运行核心)
        '--clean',                  # 清理 PyInstaller 缓存
        '--noconfirm',              # 覆盖已有构建目录时不进行交互提示

        # --- 源码路径注入 ---
        '--paths=.',

        # --- 第三方包资源全量收集 ---
        '--collect-all', 'customtkinter',

        # --- 模块剪枝排除 (排除未使用的重量级依赖，加快构建并减小体积) ---
        '--exclude-module', 'PySide6.QtWebEngineCore',
        '--exclude-module', 'PySide6.QtWebEngineWidgets',
        '--exclude-module', 'PySide6.Qt3DCore',
        '--exclude-module', 'PySide6.QtQml',
        '--exclude-module', 'PySide6.QtQuick',
        '--exclude-module', 'matplotlib',
        '--exclude-module', 'torch',
    ]

    # 挂载 FFmpeg 套件到 ffmpeg_bin 虚拟子目录
    for bf in ffmpeg_files:
        options.append(f'--add-binary={bf};ffmpeg_bin')

    # 挂载 VC++ 核心 DLL 到单文件解压根目录
    for dll_p in vc_dlls:
        options.append(f'--add-data={dll_p};.')

    # 挂载应用图标
    icon_file = os.path.join(BASE_DIR, 'icon', 'app.ico')
    if os.path.isfile(icon_file):
        options.append(f'--icon={icon_file}')
        options.append(f'--add-data={icon_file};icon')
        print(f"\n[3/4] 已挂载 7 级多分辨率专属应用图标: {icon_file}")
    else:
        print("\n[3/4 警告] 未找到 icon/app.ico！")

    # 7. 执行 PyInstaller 打包
    print(f"\n[4/4] 正在调用 PyInstaller 编译单文件自解压程序 ({target_exe_name})...\n")
    PyInstaller.__main__.run(options)

    # 8. 清理临时 build 缓存与 spec
    build_temp = os.path.join(BASE_DIR, "build")
    if os.path.exists(build_temp):
        for _ in range(3):
            try:
                shutil.rmtree(build_temp)
                break
            except Exception:
                time.sleep(0.5)

    if os.path.exists(spec_file):
        try:
            os.remove(spec_file)
        except Exception:
            pass

    # 9. 强制刷新 Windows 资源管理器图标缓存
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
        except Exception:
            pass

    # 10. 校验产物
    if os.path.isfile(target_exe_path):
        size_mb = os.path.getsize(target_exe_path) / (1024 * 1024)
        print("\n" + "=" * 66)
        print(f"✅ 单文件构建成功！独立程序位于: {target_exe_path}")
        print(f"📦 单文件产物体积: {size_mb:.2f} MB")
        print(f"🛡️  沙盒全量适配: 已内嵌 FFmpeg 套件及 VC++ 核心运行库，零外部依赖")
        print("=" * 66 + "\n")

        # 自动高亮选中生成的 exe
        if sys.platform == "win32":
            try:
                subprocess.Popen(['explorer', '/select,', os.path.normpath(target_exe_path)])
            except Exception:
                pass
    else:
        print(f"\n[错误] 未在 dist 目录下找到生成的 {target_exe_name}！")
        sys.exit(1)


if __name__ == "__main__":
    main()
