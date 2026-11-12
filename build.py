import os
import sys
import shutil
import glob
import PyInstaller.__main__

def locate_ffmpeg_dir():
    """
    多级探测 FFmpeg 所在的 bin 目录：
    1. 环境变量 FFMPEG_PATH 或 FFMPEG_HOME
    2. shutil.which('ffmpeg') 推导
    3. 常见候选路径
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
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ffmpeg_bin'),
    ])

    for c in candidates:
        if not c or not os.path.isdir(c):
            continue
        ffmpeg_exe = os.path.join(c, 'ffmpeg.exe')
        ffprobe_exe = os.path.join(c, 'ffprobe.exe')
        if os.path.isfile(ffmpeg_exe) and os.path.isfile(ffprobe_exe):
            return os.path.abspath(c)

    return None

def main():
    print("=" * 60)
    print("  MediaSegmenter 打包构建程序 (Windows 沙盒全内置兼容模式)")
    print("=" * 60)

    ffmpeg_dir = locate_ffmpeg_dir()
    if not ffmpeg_dir:
        print("\n[错误] 未能定位到有效的 FFmpeg 目录（必须包含 ffmpeg.exe 和 ffprobe.exe）！")
        print("请确保已安装 FFmpeg，或通过环境变量设置 FFMPEG_HOME/FFMPEG_PATH。")
        sys.exit(1)

    print(f"\n[1/3] 找到 FFmpeg 目录: {ffmpeg_dir}")

    # 收集需要打包的二进制文件
    binary_files = []
    ffmpeg_exe = os.path.join(ffmpeg_dir, 'ffmpeg.exe')
    ffprobe_exe = os.path.join(ffmpeg_dir, 'ffprobe.exe')
    binary_files.append(ffmpeg_exe)
    binary_files.append(ffprobe_exe)

    # 收集所有伴随 DLL (排除无用的 ffplay.exe)
    for dll_file in glob.glob(os.path.join(ffmpeg_dir, '*.dll')):
        binary_files.append(dll_file)

    print(f"[2/3] 正在收集需要打包的二进制依赖 ({len(binary_files)} 个):")
    total_size = 0
    for bf in binary_files:
        sz = os.path.getsize(bf)
        total_size += sz
        print(f"  + {os.path.basename(bf)} ({sz / (1024*1024):.2f} MB)")
    print(f"  依赖总计大小: {total_size / (1024*1024):.2f} MB")

    # 配置 PyInstaller 参数
    options = [
        'main.py',
        '--name=MediaSegmenter',
        '--windowed',
        '--onefile',
        '--clean',
        '--noconfirm',
        '--collect-all', 'customtkinter',
    ]

    # 添加二进制文件到 ffmpeg_bin 虚拟目录
    for bf in binary_files:
        options.extend(['--add-binary', f"{bf};ffmpeg_bin"])

    # 配置应用程序图标 (若存在 icon/app.ico)
    icon_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'icon', 'app.ico')
    if os.path.isfile(icon_file):
        options.append(f'--icon={icon_file}')
        options.extend(['--add-data', f'{icon_file};icon'])
        print(f"  + 已挂载应用图标: {icon_file}")

    print(f"\n[3/3] 开始调用 PyInstaller 进行单文件打包...")
    PyInstaller.__main__.run(options)

    dist_exe = os.path.join('dist', 'MediaSegmenter.exe')
    if os.path.isfile(dist_exe):
        exe_size = os.path.getsize(dist_exe) / (1024 * 1024)
        print("\n" + "=" * 60)
        print(f"✅ 构建成功！单文件可执行文件生成于: {os.path.abspath(dist_exe)}")
        print(f"   最终产物体积: {exe_size:.2f} MB (已内嵌 FFmpeg/FFprobe 及核心 DLL)")
        print("=" * 60)
    else:
        print("\n[错误] 未在 dist 目录下找到生成的 MediaSegmenter.exe！")
        sys.exit(1)

if __name__ == '__main__':
    main()
