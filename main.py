import os
import sys
import shutil
import tempfile
import subprocess
import threading
import multiprocessing
import tkinter as tk
from tkinter import filedialog, messagebox, font as tkfont
import customtkinter as ctk

# -------------------------------------------------------------
# 0. 任务栏专属进程标识注入 (Win32 AppUserModelID)
# -------------------------------------------------------------
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("company.mediasegmenter.client.2026")
    except Exception:
        pass

# -------------------------------------------------------------
# 1. 无控制台与标准流安全保护 (针对 PyInstaller --windowed 模式)
# -------------------------------------------------------------
class SafeNullWriter:
    def write(self, s): pass
    def flush(self): pass

if sys.stdout is None:
    sys.stdout = SafeNullWriter()
if sys.stderr is None:
    sys.stderr = SafeNullWriter()

def safe_log(*args, **kwargs):
    """仅在 stderr 可用时输出调试信息，杜绝 NoneType write 崩溃"""
    try:
        if sys.stderr and not isinstance(sys.stderr, SafeNullWriter):
            print(*args, file=sys.stderr, **kwargs)
    except Exception:
        pass

# -------------------------------------------------------------
# 2. 系统可用字体自适应检测 (跨中英 Windows / 精简沙盒环境)
# -------------------------------------------------------------
def get_best_font():
    try:
        root_tmp = tk.Tk()
        root_tmp.withdraw()
        families = set(tkfont.families(root_tmp))
        root_tmp.destroy()
    except Exception:
        families = set()

    for candidate in ["Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "Segoe UI", "Arial"]:
        if candidate in families:
            return candidate
    return "Arial"

FONT_FAMILY = get_best_font()

# -------------------------------------------------------------
# 3. 内置二进制路径解析与 DLL 搜索路径注入
# -------------------------------------------------------------
CREATE_NO_WINDOW = 0x08000000

def get_binary_path(bin_name):
    """
    多级定位 ffmpeg.exe / ffprobe.exe 绝对路径：
    1. PyInstaller 单文件解压目录 (sys._MEIPASS/ffmpeg_bin)
    2. 程序所在目录及 ffmpeg_bin 子目录
    3. 系统 PATH 回退
    """
    exe_name = f"{bin_name}.exe" if sys.platform == "win32" and not bin_name.lower().endswith(".exe") else bin_name
    
    # 1. PyInstaller 单文件解压临时目录
    if hasattr(sys, '_MEIPASS'):
        p = os.path.join(sys._MEIPASS, 'ffmpeg_bin', exe_name)
        if os.path.isfile(p):
            return os.path.abspath(p)

    # 2. 本地可执行文件所在目录
    if getattr(sys, 'frozen', False):
        app_dir = os.path.dirname(sys.executable)
    else:
        app_dir = os.path.dirname(os.path.abspath(__file__))

    p = os.path.join(app_dir, 'ffmpeg_bin', exe_name)
    if os.path.isfile(p):
        return os.path.abspath(p)

    p = os.path.join(app_dir, exe_name)
    if os.path.isfile(p):
        return os.path.abspath(p)

    # 3. 系统 PATH
    w = shutil.which(bin_name)
    if w and os.path.isfile(w):
        return os.path.abspath(w)

    return bin_name

def get_resource_path(relative_path):
    """获取程序静态资源路径（兼容源码直接运行与 PyInstaller 打包环境）"""
    if hasattr(sys, '_MEIPASS'):
        p = os.path.join(sys._MEIPASS, relative_path)
        if os.path.exists(p):
            return os.path.abspath(p)
    app_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(app_dir, relative_path)
    if os.path.exists(p):
        return os.path.abspath(p)
    return p

def setup_runtime_environment():
    """将内置 ffmpeg_bin 注入 PATH 并调用 os.add_dll_directory 加载伴随 DLL"""
    bin_dirs = []
    if hasattr(sys, '_MEIPASS'):
        bin_dirs.append(os.path.join(sys._MEIPASS, 'ffmpeg_bin'))
    if getattr(sys, 'frozen', False):
        app_dir = os.path.dirname(sys.executable)
    else:
        app_dir = os.path.dirname(os.path.abspath(__file__))
    bin_dirs.append(os.path.join(app_dir, 'ffmpeg_bin'))

    for d in bin_dirs:
        if os.path.isdir(d):
            cur_path = os.environ.get("PATH", "")
            if d not in cur_path:
                os.environ["PATH"] = d + os.pathsep + cur_path
            if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(d)
                except Exception as e:
                    safe_log(f"os.add_dll_directory failed: {e}")
            break

setup_runtime_environment()

# -------------------------------------------------------------
# 4. 子进程安全调用封装 run_media_cmd 与错误提取
# -------------------------------------------------------------
def run_media_cmd(cmd, cwd=None):
    """
    统一安全调用 ffmpeg / ffprobe：
    - 首项替换为绝对路径；
    - 针对 ffmpeg 自动注入 -nostdin；
    - 强制 stdin=DEVNULL, utf-8 编码且 errors='replace'，防止挂起与解码异常；
    - CREATE_NO_WINDOW 隐藏黑框控制台。
    """
    cmd = list(cmd)
    if cmd:
        first = cmd[0]
        if first in ('ffmpeg', 'ffprobe', 'ffmpeg.exe', 'ffprobe.exe'):
            cmd[0] = get_binary_path(first)
        
        bin_lower = os.path.basename(cmd[0]).lower()
        if 'ffmpeg' in bin_lower and '-nostdin' not in cmd:
            cmd.insert(1, '-nostdin')

        # 若未指定 cwd，显式设为二进制文件所在目录，确保 Windows 动态链接器命中同级伴生 DLL
        if cwd is None and os.path.isfile(cmd[0]):
            cwd = os.path.dirname(os.path.abspath(cmd[0]))

    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
        text=True,
        encoding='utf-8',
        errors='replace',
        cwd=cwd
    )

def extract_error_detail(stderr_text, default_msg="处理失败"):
    """从 FFmpeg stderr 中提取关键错误描述摘要"""
    if not stderr_text:
        return default_msg
    lines = [line.strip() for line in stderr_text.strip().splitlines() if line.strip()]
    if not lines:
        return default_msg
    meaningful = []
    for line in reversed(lines):
        if not line.startswith('[') and not line.startswith('Input #') and not line.startswith('Output #'):
            meaningful.append(line)
        else:
            meaningful.append(line)
        if len(meaningful) >= 2:
            break
    if meaningful:
        return " | ".join(reversed(meaningful))
    return lines[-1]

def get_audio_duration(file_path):
    cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path]
    try:
        result = run_media_cmd(cmd)
        if result.returncode != 0:
            err = extract_error_detail(result.stderr, "无法读取音频时长")
            raise Exception(err)
        return float(result.stdout.strip())
    except Exception as e:
        raise Exception(f"无法获取媒体时长: {e}")

def process_audio(input_file, output_dir, num_parts, overlap, progress_callback, status_callback, complete_callback):
    try:
        duration = get_audio_duration(input_file)
        if duration <= 0:
            raise Exception("媒体时长无效或为 0。")

        base_length = duration / num_parts
        base_name, ext = os.path.splitext(os.path.basename(input_file))
        if not ext:
            ext = '.mp3'
        
        for i in range(1, num_parts + 1):
            status_callback(f"正在分割: 第 {i}/{num_parts} 段...")
            
            end_time = i * base_length
            start_time = max(0.0, (i - 1) * base_length - overlap)
            segment_duration = end_time - start_time
            
            part_name = f"{base_name}_part{i:02d}{ext}"
            output_file = os.path.join(output_dir, part_name)
            
            # 1. 优先尝试无损分割 (-c copy)
            cmd_copy = [
                'ffmpeg', '-y', 
                '-ss', f"{start_time:.3f}", 
                '-i', input_file, 
                '-t', f"{segment_duration:.3f}", 
                '-c', 'copy',
                '-avoid_negative_ts', 'make_zero',
                output_file
            ]
            result = run_media_cmd(cmd_copy)
            
            success_copy = (result.returncode == 0 and os.path.exists(output_file) and os.path.getsize(output_file) > 0)
            if not success_copy:
                safe_log(f"Part {i} lossless audio split failed, falling back to re-encode...")
                status_callback(f"第 {i} 段无损分割失败，正在重新编码...")
                
                cmd_re = [
                    'ffmpeg', '-y', 
                    '-ss', f"{start_time:.3f}", 
                    '-i', input_file, 
                    '-t', f"{segment_duration:.3f}", 
                    output_file
                ]
                result_re = run_media_cmd(cmd_re)
                success_re = (result_re.returncode == 0 and os.path.exists(output_file) and os.path.getsize(output_file) > 0)
                
                if not success_re:
                    # 如果原容器格式不支持重编码，最终兜底重编码为 .mp3
                    mp3_part_name = f"{base_name}_part{i:02d}.mp3"
                    mp3_output_file = os.path.join(output_dir, mp3_part_name)
                    cmd_mp3 = [
                        'ffmpeg', '-y', 
                        '-ss', f"{start_time:.3f}", 
                        '-i', input_file, 
                        '-t', f"{segment_duration:.3f}", 
                        mp3_output_file
                    ]
                    result_mp3 = run_media_cmd(cmd_mp3)
                    if result_mp3.returncode != 0 or not os.path.exists(mp3_output_file) or os.path.getsize(mp3_output_file) == 0:
                        err = extract_error_detail(result_re.stderr or result_mp3.stderr, f"FFmpeg 处理第 {i} 段时出错。")
                        raise Exception(err)
            
            progress_callback(i / num_parts)
            
        status_callback("处理完成！全部片段已成功生成！")
        complete_callback(True, "")
        
    except Exception as e:
        status_callback(f"错误: {str(e)}")
        complete_callback(False, str(e))

def merge_audio(input_dir, output_file, progress_callback, status_callback, complete_callback, safe_mode=False):
    temp_dir = None
    try:
        valid_extensions = ('.mp3', '.wav', '.m4a', '.aac', '.flac', '.wma', '.mp4', '.mkv', '.avi', '.mov', '.flv', '.wmv')
        audio_files = [f for f in os.listdir(input_dir) if f.lower().endswith(valid_extensions)]
        
        # 过滤输出文件本身，防止自吞噬递归合并 (大小写不敏感且绝对路径规范化)
        norm_output = os.path.normcase(os.path.abspath(output_file))
        audio_files = [f for f in audio_files if os.path.normcase(os.path.abspath(os.path.join(input_dir, f))) != norm_output]
        
        audio_files.sort()
        
        if not audio_files:
            raise Exception("该文件夹下没有找到支持的音视频文件！")

        temp_dir = tempfile.mkdtemp(prefix="media_seg_merge_audio_")

        if safe_mode:
            temp_files = []
            for idx, af in enumerate(audio_files):
                progress_callback(idx / len(audio_files) * 0.8)
                status_callback(f"正在统一格式: {idx+1}/{len(audio_files)}")
                in_path = os.path.join(input_dir, af)
                out_path = os.path.join(temp_dir, f"temp_{idx:04d}.wav")
                cmd_cnv = ['ffmpeg', '-y', '-i', in_path, '-ar', '44100', '-ac', '2', out_path]
                res_cnv = run_media_cmd(cmd_cnv)
                if res_cnv.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
                    err = extract_error_detail(res_cnv.stderr, f"文件 {af} 格式转码失败")
                    raise Exception(f"安全合并预转码失败 ({af}): {err}")
                temp_files.append(out_path)
            
            concat_file_path = os.path.join(temp_dir, "concat_list.txt")
            with open(concat_file_path, 'w', encoding='utf-8') as f:
                for tf in temp_files:
                    safe_p = os.path.abspath(tf).replace('\\', '/').replace("'", "'\\''")
                    f.write(f"file '{safe_p}'\n")
                    
            status_callback("正在合并已统一的音频...")
            progress_callback(0.9)
            
            cmd_merge = [
                'ffmpeg', '-y',
                '-f', 'concat',
                '-safe', '0',
                '-i', concat_file_path,
                output_file
            ]
            result = run_media_cmd(cmd_merge, cwd=temp_dir)
            if result.returncode != 0 or not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
                err = extract_error_detail(result.stderr, "安全合并失败")
                raise Exception(f"安全合并失败: {err}")
                
            progress_callback(1.0)
            status_callback("合并完成！")
            complete_callback(True, "")
            return

        # 普通合并模式 (优先无损，失败回退重编码)
        concat_file_path = os.path.join(temp_dir, "concat_list.txt")
        with open(concat_file_path, 'w', encoding='utf-8') as f:
            for audio_file in audio_files:
                in_path = os.path.join(input_dir, audio_file)
                safe_p = os.path.abspath(in_path).replace('\\', '/').replace("'", "'\\''")
                f.write(f"file '{safe_p}'\n")

        status_callback(f"找到 {len(audio_files)} 个媒体文件，正在尝试无损合并...")
        progress_callback(0.3)

        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat',
            '-safe', '0',
            '-i', concat_file_path,
            '-c', 'copy',
            output_file
        ]
        
        result = run_media_cmd(cmd, cwd=temp_dir)
        success = (result.returncode == 0 and os.path.exists(output_file) and os.path.getsize(output_file) > 0)
        
        if not success:
            safe_log("Copy codec failed, trying re-encoding...")
            status_callback("无损合并失败，正在重新编码合并...")
            progress_callback(0.5)
            
            cmd_reencode = [
                'ffmpeg', '-y',
                '-f', 'concat',
                '-safe', '0',
                '-i', concat_file_path,
                output_file
            ]
            result_reencode = run_media_cmd(cmd_reencode, cwd=temp_dir)
            
            if result_reencode.returncode != 0 or not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
                err = extract_error_detail(result_reencode.stderr, "FFmpeg 合并时出错。")
                raise Exception(err)

        progress_callback(1.0)
        status_callback("合并完成！")
        complete_callback(True, "")

    except Exception as e:
        status_callback(f"错误: {str(e)}")
        complete_callback(False, str(e))
    finally:
        if temp_dir and os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

def process_video(input_file, output_dir, num_parts, overlap, progress_callback, status_callback, complete_callback):
    try:
        duration = get_audio_duration(input_file)
        if duration <= 0:
            raise Exception("媒体时长无效或为 0。")

        base_length = duration / num_parts
        base_name, ext = os.path.splitext(os.path.basename(input_file))
        if not ext:
            ext = '.mp4'
        
        for i in range(1, num_parts + 1):
            status_callback(f"正在分割: 第 {i}/{num_parts} 段...")
            
            end_time = i * base_length
            start_time = max(0.0, (i - 1) * base_length - overlap)
            segment_duration = end_time - start_time
            
            part_name = f"{base_name}_part{i:02d}{ext}"
            output_file = os.path.join(output_dir, part_name)
            
            cmd = [
                'ffmpeg', '-y', 
                '-ss', f"{start_time:.3f}",
                '-i', input_file, 
                '-t', f"{segment_duration:.3f}", 
                '-c', 'copy',
                '-avoid_negative_ts', 'make_zero',
                output_file
            ]
            
            result = run_media_cmd(cmd)
            success = (result.returncode == 0 and os.path.exists(output_file) and os.path.getsize(output_file) > 0)
            if not success:
                safe_log(f"Part {i} lossless video split failed, falling back to re-encode...")
                status_callback(f"无损分割失败，尝试重新编码...")
                cmd_re = [
                    'ffmpeg', '-y', 
                    '-ss', f"{start_time:.3f}",
                    '-i', input_file, 
                    '-t', f"{segment_duration:.3f}", 
                    '-avoid_negative_ts', 'make_zero',
                    output_file
                ]
                result_re = run_media_cmd(cmd_re)
                if result_re.returncode != 0 or not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
                    err = extract_error_detail(result_re.stderr, f"FFmpeg 处理第 {i} 段时出错。")
                    raise Exception(err)
                
            progress_callback(i / num_parts)
            
        status_callback("处理完成！全部片段已成功生成！")
        complete_callback(True, "")
        
    except Exception as e:
        status_callback(f"错误: {str(e)}")
        complete_callback(False, str(e))

def merge_video(input_dir, output_file, progress_callback, status_callback, complete_callback):
    temp_dir = None
    try:
        valid_extensions = ('.mp4', '.mkv', '.avi', '.mov', '.flv', '.wmv', '.webm', '.ts')
        video_files = [f for f in os.listdir(input_dir) if f.lower().endswith(valid_extensions)]
        
        norm_output = os.path.normcase(os.path.abspath(output_file))
        video_files = [f for f in video_files if os.path.normcase(os.path.abspath(os.path.join(input_dir, f))) != norm_output]
        
        video_files.sort()
        
        if not video_files:
            raise Exception("该文件夹下没有找到支持的视频文件！")

        temp_dir = tempfile.mkdtemp(prefix="media_seg_merge_video_")

        concat_file_path = os.path.join(temp_dir, "concat_list.txt")
        with open(concat_file_path, 'w', encoding='utf-8') as f:
            for video_file in video_files:
                in_path = os.path.join(input_dir, video_file)
                safe_p = os.path.abspath(in_path).replace('\\', '/').replace("'", "'\\''")
                f.write(f"file '{safe_p}'\n")

        status_callback(f"找到 {len(video_files)} 个视频文件，正在尝试无损合并...")
        progress_callback(0.3)

        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat',
            '-safe', '0',
            '-i', concat_file_path,
            '-c', 'copy',
            output_file
        ]
        
        result = run_media_cmd(cmd, cwd=temp_dir)
        success = (result.returncode == 0 and os.path.exists(output_file) and os.path.getsize(output_file) > 0)
        
        if not success:
            safe_log("Copy codec failed, trying re-encoding...")
            status_callback("无损合并失败，正在重新编码合并...")
            progress_callback(0.5)
            
            cmd_reencode = [
                'ffmpeg', '-y',
                '-f', 'concat',
                '-safe', '0',
                '-i', concat_file_path,
                output_file
            ]
            result_reencode = run_media_cmd(cmd_reencode, cwd=temp_dir)
            
            if result_reencode.returncode != 0 or not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
                err = extract_error_detail(result_reencode.stderr, "FFmpeg 合并视频时出错。")
                raise Exception(err)

        progress_callback(1.0)
        status_callback("合并完成！")
        complete_callback(True, "")

    except Exception as e:
        status_callback(f"错误: {str(e)}")
        complete_callback(False, str(e))
    finally:
        if temp_dir and os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

def parse_time_input(time_str):
    """Parse time string like '37.30' or '00:00:37.30' to seconds."""
    time_str = time_str.strip()
    if ':' in time_str:
        parts = time_str.split(':')
        if len(parts) == 3:
            h, m, s = parts
            return float(h) * 3600 + float(m) * 60 + float(s)
        elif len(parts) == 2:
            m, s = parts
            return float(m) * 60 + float(s)
        else:
            raise ValueError("时间格式不正确")
    else:
        return float(time_str)

def get_video_info(file_path):
    """Get video duration, resolution, and file size."""
    cmd = [
        'ffprobe', '-v', 'error',
        '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height,duration',
        '-show_entries', 'format=duration,size',
        '-of', 'json', file_path
    ]
    try:
        result = run_media_cmd(cmd)
        if result.returncode != 0:
            err = extract_error_detail(result.stderr, "无法读取视频信息")
            raise Exception(err)
        import json
        data = json.loads(result.stdout)
        stream = data.get('streams', [{}])[0] if data.get('streams') else {}
        fmt = data.get('format', {})
        duration = float(stream.get('duration', 0) or fmt.get('duration', 0))
        width = int(stream.get('width', 0))
        height = int(stream.get('height', 0))
        size_bytes = int(fmt.get('size', 0))
        return duration, width, height, size_bytes
    except Exception as e:
        raise Exception(f"无法获取视频信息: {e}")

def get_audio_info(file_path):
    """Get audio duration and file size."""
    cmd = [
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration,size',
        '-of', 'json', file_path
    ]
    try:
        result = run_media_cmd(cmd)
        if result.returncode != 0:
            err = extract_error_detail(result.stderr, "无法读取音频信息")
            raise Exception(err)
        import json
        data = json.loads(result.stdout)
        fmt = data.get('format', {})
        duration = float(fmt.get('duration', 0))
        size_bytes = int(fmt.get('size', 0))
        return duration, size_bytes
    except Exception as e:
        raise Exception(f"无法获取音频信息: {e}")

def format_file_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

def format_duration(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:05.2f}"
    else:
        return f"{m:02d}:{s:05.2f}"

def clip_video(input_file, output_file, start_time, end_time, progress_callback, status_callback, complete_callback):
    try:
        status_callback("正在截取视频 (无损模式)...")
        progress_callback(0.2)
        duration = end_time - start_time
        cmd = [
            'ffmpeg', '-y',
            '-ss', f"{start_time:.3f}",
            '-i', input_file,
            '-t', f"{duration:.3f}",
            '-c', 'copy',
            '-avoid_negative_ts', 'make_zero',
            output_file
        ]
        result = run_media_cmd(cmd)
        success = (result.returncode == 0 and os.path.exists(output_file) and os.path.getsize(output_file) > 0)
        if not success:
            status_callback("无损截取失败，正在重新编码...")
            progress_callback(0.4)
            cmd_re = [
                'ffmpeg', '-y',
                '-ss', f"{start_time:.3f}",
                '-i', input_file,
                '-t', f"{duration:.3f}",
                '-avoid_negative_ts', 'make_zero',
                output_file
            ]
            result_re = run_media_cmd(cmd_re)
            if result_re.returncode != 0 or not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
                err = extract_error_detail(result_re.stderr, "FFmpeg 截取视频时出错。")
                raise Exception(err)
        progress_callback(1.0)
        status_callback("截取完成！")
        complete_callback(True, "")
    except Exception as e:
        status_callback(f"错误: {str(e)}")
        complete_callback(False, str(e))

def clip_audio(input_file, output_file, start_time, end_time, progress_callback, status_callback, complete_callback):
    try:
        status_callback("正在截取音频 (无损模式)...")
        progress_callback(0.2)
        duration = end_time - start_time
        cmd = [
            'ffmpeg', '-y',
            '-ss', f"{start_time:.3f}",
            '-i', input_file,
            '-t', f"{duration:.3f}",
            '-c', 'copy',
            output_file
        ]
        result = run_media_cmd(cmd)
        success = (result.returncode == 0 and os.path.exists(output_file) and os.path.getsize(output_file) > 0)
        if not success:
            status_callback("无损截取失败，正在重新编码...")
            progress_callback(0.4)
            cmd_re = [
                'ffmpeg', '-y',
                '-ss', f"{start_time:.3f}",
                '-i', input_file,
                '-t', f"{duration:.3f}",
                output_file
            ]
            result_re = run_media_cmd(cmd_re)
            if result_re.returncode != 0 or not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
                err = extract_error_detail(result_re.stderr, "FFmpeg 截取音频时出错。")
                raise Exception(err)
        progress_callback(1.0)
        status_callback("截取完成！")
        complete_callback(True, "")
    except Exception as e:
        status_callback(f"错误: {str(e)}")
        complete_callback(False, str(e))




class MediaSegmenterApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("Light")
        ctk.set_default_color_theme("blue")
        
        self.title("音视频处理工具 · Media Segmenter")
        
        # 窗口与任务栏图标设置
        try:
            icon_path = get_resource_path(os.path.join("icon", "app.ico"))
            if os.path.isfile(icon_path):
                self.iconbitmap(icon_path)
        except Exception as e:
            safe_log(f"设置窗口图标失败: {e}")

        self.geometry("640x730")
        self.minsize(580, 620)
        self.resizable(True, True)
        self.after(500, self._check_binaries_health)
        self.configure(fg_color="#F8FAFC")
        
        # Outer main tabview
        self.main_tabview = ctk.CTkTabview(
            self,
            fg_color="#FFFFFF",
            border_width=1,
            border_color="#E2E8F0",
            corner_radius=12,
            segmented_button_fg_color="#F1F5F9",
            segmented_button_selected_color="#4F46E5",
            segmented_button_selected_hover_color="#4338CA",
            segmented_button_unselected_color="#FFFFFF",
            segmented_button_unselected_hover_color="#F8FAFC",
            segmented_button_font=(FONT_FAMILY, 13, "bold"),
        )
        self.main_tabview.pack(padx=18, pady=(14, 18), fill="both", expand=True)
        
        self.tab_audio = self.main_tabview.add("🎵  音频处理")
        self.tab_video = self.main_tabview.add("🎬  视频处理")
        self._style_tabview_buttons(self.main_tabview, is_outer=True)

        # Audio sub-tabview
        self.audio_tabview = ctk.CTkTabview(
            self.tab_audio,
            fg_color="#F8FAFC",
            border_width=1,
            border_color="#E2E8F0",
            corner_radius=10,
            segmented_button_fg_color="#FFFFFF",
            segmented_button_selected_color="#EEF2FF",
            segmented_button_selected_hover_color="#E0E7FF",
            segmented_button_unselected_color="#F8FAFC",
            segmented_button_unselected_hover_color="#F1F5F9",
            segmented_button_font=(FONT_FAMILY, 12, "bold"),
        )
        self.audio_tabview.pack(padx=12, pady=12, fill="both", expand=True)
        
        self.tab_segment = self.audio_tabview.add("音频分割")
        self.tab_merge = self.audio_tabview.add("音频合并")
        self.tab_audio_clip = self.audio_tabview.add("音频截取")
        self._style_tabview_buttons(self.audio_tabview, is_outer=False)
        
        # Video sub-tabview
        self.video_tabview = ctk.CTkTabview(
            self.tab_video,
            fg_color="#F8FAFC",
            border_width=1,
            border_color="#E2E8F0",
            corner_radius=10,
            segmented_button_fg_color="#FFFFFF",
            segmented_button_selected_color="#EEF2FF",
            segmented_button_selected_hover_color="#E0E7FF",
            segmented_button_unselected_color="#F8FAFC",
            segmented_button_unselected_hover_color="#F1F5F9",
            segmented_button_font=(FONT_FAMILY, 12, "bold"),
        )
        self.video_tabview.pack(padx=12, pady=12, fill="both", expand=True)
        
        self.tab_video_segment = self.video_tabview.add("视频分割")
        self.tab_video_merge = self.video_tabview.add("视频合并")
        self.tab_video_clip = self.video_tabview.add("视频截取")
        self._style_tabview_buttons(self.video_tabview, is_outer=False)
        
        self.setup_segment_tab()
        self.setup_merge_tab()
        self.setup_video_segment_tab()
        self.setup_video_merge_tab()
        self.setup_video_clip_tab()
        self.setup_audio_clip_tab()

    def _check_binaries_health(self):
        """启动自检：校验内置 ffmpeg 与 ffprobe 是否可正常运行"""
        try:
            res_ffmpeg = run_media_cmd(['ffmpeg', '-version'])
            ffmpeg_ok = (res_ffmpeg.returncode == 0)
        except Exception:
            ffmpeg_ok = False

        try:
            res_ffprobe = run_media_cmd(['ffprobe', '-version'])
            ffprobe_ok = (res_ffprobe.returncode == 0)
        except Exception:
            ffprobe_ok = False

        if not (ffmpeg_ok and ffprobe_ok):
            missing = []
            if not ffmpeg_ok:
                missing.append("FFmpeg 核心组件")
            if not ffprobe_ok:
                missing.append("FFprobe 探针组件")
            msg = f"注意：以下必要组件自检失败或不可用：\n{'、'.join(missing)}\n\n音视频处理功能可能无法正常执行。请检查安装或内置配置。"
            messagebox.showwarning("组件环境提示", msg)


    def _style_tabview_buttons(self, tv, is_outer=True):
        sb = tv._segmented_button
        sel_fg = "#4F46E5" if is_outer else "#EEF2FF"
        sel_txt = "#FFFFFF" if is_outer else "#4F46E5"
        unsel_fg = "#FFFFFF" if is_outer else "#F8FAFC"
        unsel_txt = "#64748B"

        orig_select = sb._select_button_by_value
        orig_unselect = sb._unselect_button_by_value

        def new_select(value):
            orig_select(value)
            if value in sb._buttons_dict:
                sb._buttons_dict[value].configure(fg_color=sel_fg, text_color=sel_txt)

        def new_unselect(value):
            orig_unselect(value)
            if value in sb._buttons_dict:
                sb._buttons_dict[value].configure(fg_color=unsel_fg, text_color=unsel_txt)

        sb._select_button_by_value = new_select
        sb._unselect_button_by_value = new_unselect

        for val, btn in sb._buttons_dict.items():
            if val == sb._current_value:
                btn.configure(fg_color=sel_fg, text_color=sel_txt)
            else:
                btn.configure(fg_color=unsel_fg, text_color=unsel_txt)

    def setup_segment_tab(self):
        tab = self.tab_segment
        
        # 1. File Selection Card
        card_file = ctk.CTkFrame(tab, fg_color="#FFFFFF", corner_radius=10, border_width=1, border_color="#E2E8F0")
        card_file.pack(fill="x", padx=12, pady=(12, 8))
        
        lbl_file_header = ctk.CTkLabel(card_file, text="源媒体文件", font=(FONT_FAMILY, 11, "bold"), text_color="#94A3B8")
        lbl_file_header.pack(anchor="w", padx=14, pady=(10, 2))
        
        self.lbl_file = ctk.CTkLabel(card_file, text="未选择媒体文件", font=(FONT_FAMILY, 12), text_color="#64748B")
        self.lbl_file.pack(padx=14, pady=(0, 6), anchor="w")
        
        self.btn_select_file = ctk.CTkButton(
            card_file, text="📁  选择媒体文件", command=self.select_file, height=36,
            fg_color="#F8FAFC", hover_color="#EEF2FF", border_width=1, border_color="#CBD5E1",
            text_color="#0F172A", font=(FONT_FAMILY, 12, "bold"), corner_radius=8
        )
        self.btn_select_file.pack(padx=14, pady=(0, 12), fill="x")
        
        # 2. Parameters Card
        card_params = ctk.CTkFrame(tab, fg_color="#FFFFFF", corner_radius=10, border_width=1, border_color="#E2E8F0")
        card_params.pack(fill="x", padx=12, pady=8)
        
        lbl_params_header = ctk.CTkLabel(card_params, text="分割参数设置", font=(FONT_FAMILY, 11, "bold"), text_color="#94A3B8")
        lbl_params_header.pack(anchor="w", padx=14, pady=(10, 4))
        
        self.frm_params = ctk.CTkFrame(card_params, fg_color="transparent")
        self.frm_params.pack(padx=14, pady=(0, 12), fill="x")
        self.frm_params.columnconfigure(0, weight=1)
        self.frm_params.columnconfigure(1, weight=0)
        
        self.lbl_parts = ctk.CTkLabel(self.frm_params, text="分割数量 (每段):", font=(FONT_FAMILY, 12), text_color="#1E293B")
        self.lbl_parts.grid(row=0, column=0, pady=6, sticky="w")
        self.entry_parts = ctk.CTkEntry(
            self.frm_params, width=110, height=32, font=("Consolas", 13, "bold"),
            text_color="#4F46E5", fg_color="#F8FAFC", border_color="#CBD5E1", border_width=1, corner_radius=6, justify="center"
        )
        self.entry_parts.insert(0, "8")
        self.entry_parts.grid(row=0, column=1, pady=6, sticky="e")
        
        self.lbl_overlap = ctk.CTkLabel(self.frm_params, text="前置重叠时间 (秒):", font=(FONT_FAMILY, 12), text_color="#1E293B")
        self.lbl_overlap.grid(row=1, column=0, pady=6, sticky="w")
        self.entry_overlap = ctk.CTkEntry(
            self.frm_params, width=110, height=32, font=("Consolas", 13, "bold"),
            text_color="#4F46E5", fg_color="#F8FAFC", border_color="#CBD5E1", border_width=1, corner_radius=6, justify="center"
        )
        self.entry_overlap.insert(0, "3")
        self.entry_overlap.grid(row=1, column=1, pady=6, sticky="e")
        
        # 3. Output Dir Card
        card_outdir = ctk.CTkFrame(tab, fg_color="#FFFFFF", corner_radius=10, border_width=1, border_color="#E2E8F0")
        card_outdir.pack(fill="x", padx=12, pady=8)
        
        lbl_out_header = ctk.CTkLabel(card_outdir, text="输出位置", font=(FONT_FAMILY, 11, "bold"), text_color="#94A3B8")
        lbl_out_header.pack(anchor="w", padx=14, pady=(10, 2))
        
        self.lbl_outdir = ctk.CTkLabel(card_outdir, text="输出文件夹: 默认与源文件同目录", font=(FONT_FAMILY, 12), text_color="#64748B")
        self.lbl_outdir.pack(padx=14, pady=(0, 6), anchor="w")
        
        self.btn_select_outdir = ctk.CTkButton(
            card_outdir, text="📂  选择输出文件夹", command=self.select_outdir, height=36,
            fg_color="#F8FAFC", hover_color="#EEF2FF", border_width=1, border_color="#CBD5E1",
            text_color="#334155", font=(FONT_FAMILY, 12, "bold"), corner_radius=8
        )
        self.btn_select_outdir.pack(padx=14, pady=(0, 12), fill="x")
        
        # 4. Action & Progress
        self.btn_start_segment = ctk.CTkButton(
            tab, text="⚡  开始分割", command=self.start_processing, height=44,
            font=(FONT_FAMILY, 14, "bold"), fg_color="#10B981", hover_color="#059669",
            text_color="#FFFFFF", corner_radius=8
        )
        self.btn_start_segment.pack(padx=12, pady=(14, 8), fill="x")
        
        self.progress_bar = ctk.CTkProgressBar(tab, height=8, corner_radius=4, fg_color="#E2E8F0", progress_color="#10B981")
        self.progress_bar.pack(padx=12, pady=4, fill="x")
        self.progress_bar.set(0)
        
        self.lbl_status = ctk.CTkLabel(tab, text="就绪 · 等待任务开始", text_color="#64748B", font=(FONT_FAMILY, 12))
        self.lbl_status.pack(pady=(4, 8))
        
        self.input_file = None
        self.output_dir = None

    def setup_merge_tab(self):
        tab = self.tab_merge
        
        card_indir = ctk.CTkFrame(tab, fg_color="#FFFFFF", corner_radius=10, border_width=1, border_color="#E2E8F0")
        card_indir.pack(fill="x", padx=12, pady=(12, 8))
        
        lbl_in_header = ctk.CTkLabel(card_indir, text="待合并媒体源", font=(FONT_FAMILY, 11, "bold"), text_color="#94A3B8")
        lbl_in_header.pack(anchor="w", padx=14, pady=(10, 2))
        
        self.lbl_merge_indir = ctk.CTkLabel(card_indir, text="未选择需要合并的媒体文件夹", font=(FONT_FAMILY, 12), text_color="#64748B")
        self.lbl_merge_indir.pack(padx=14, pady=(0, 6), anchor="w")
        
        self.btn_select_merge_indir = ctk.CTkButton(
            card_indir, text="📁  选择输入文件夹", command=self.select_merge_indir, height=36,
            fg_color="#F8FAFC", hover_color="#EEF2FF", border_width=1, border_color="#CBD5E1",
            text_color="#0F172A", font=(FONT_FAMILY, 12, "bold"), corner_radius=8
        )
        self.btn_select_merge_indir.pack(padx=14, pady=(0, 12), fill="x")
        
        card_merge = ctk.CTkFrame(tab, fg_color="#FFFFFF", corner_radius=10, border_width=1, border_color="#E2E8F0")
        card_merge.pack(fill="x", padx=12, pady=8)
        
        lbl_merge_header = ctk.CTkLabel(card_merge, text="合并配置", font=(FONT_FAMILY, 11, "bold"), text_color="#94A3B8")
        lbl_merge_header.pack(anchor="w", padx=14, pady=(10, 2))
        
        self.lbl_merge_outfile = ctk.CTkLabel(card_merge, text="输出位置: 默认保存在输入文件夹内", font=(FONT_FAMILY, 12), text_color="#64748B")
        self.lbl_merge_outfile.pack(padx=14, pady=(0, 8), anchor="w")
        
        self.frm_merge_params = ctk.CTkFrame(card_merge, fg_color="transparent")
        self.frm_merge_params.pack(padx=14, pady=4, fill="x")
        self.frm_merge_params.columnconfigure(0, weight=1)
        self.frm_merge_params.columnconfigure(1, weight=0)
        
        self.lbl_merge_name = ctk.CTkLabel(self.frm_merge_params, text="合并后文件名:", font=(FONT_FAMILY, 12), text_color="#1E293B")
        self.lbl_merge_name.grid(row=0, column=0, sticky="w")
        self.entry_merge_name = ctk.CTkEntry(
            self.frm_merge_params, width=170, height=32, font=("Consolas", 12, "bold"),
            text_color="#4F46E5", fg_color="#F8FAFC", border_color="#CBD5E1", border_width=1, corner_radius=6
        )
        self.entry_merge_name.insert(0, "merged_output.mp3")
        self.entry_merge_name.grid(row=0, column=1, sticky="e")
        
        self.var_safe_merge = ctk.BooleanVar(value=False)
        self.chk_safe_merge = ctk.CTkCheckBox(
            card_merge, text="安全合并模式 (强制统一编码，解决无声或加速问题)",
            variable=self.var_safe_merge, font=(FONT_FAMILY, 12),
            fg_color="#4F46E5", hover_color="#4338CA", text_color="#334155"
        )
        self.chk_safe_merge.pack(padx=14, pady=(8, 12), anchor="w")
        
        self.btn_start_merge = ctk.CTkButton(
            tab, text="⚡  开始合并", command=self.start_merging, height=44,
            font=(FONT_FAMILY, 14, "bold"), fg_color="#10B981", hover_color="#059669",
            text_color="#FFFFFF", corner_radius=8
        )
        self.btn_start_merge.pack(padx=12, pady=(18, 8), fill="x")
        
        self.merge_progress_bar = ctk.CTkProgressBar(tab, height=8, corner_radius=4, fg_color="#E2E8F0", progress_color="#10B981")
        self.merge_progress_bar.pack(padx=12, pady=4, fill="x")
        self.merge_progress_bar.set(0)
        
        self.lbl_merge_status = ctk.CTkLabel(tab, text="就绪 · 等待任务开始", text_color="#64748B", font=(FONT_FAMILY, 12))
        self.lbl_merge_status.pack(pady=(4, 8))
        
        self.merge_input_dir = None

    def setup_video_segment_tab(self):
        tab = self.tab_video_segment
        
        card_file = ctk.CTkFrame(tab, fg_color="#FFFFFF", corner_radius=10, border_width=1, border_color="#E2E8F0")
        card_file.pack(fill="x", padx=12, pady=(12, 8))
        
        lbl_file_header = ctk.CTkLabel(card_file, text="源视频文件", font=(FONT_FAMILY, 11, "bold"), text_color="#94A3B8")
        lbl_file_header.pack(anchor="w", padx=14, pady=(10, 2))
        
        self.lbl_vseg_file = ctk.CTkLabel(card_file, text="未选择视频文件", font=(FONT_FAMILY, 12), text_color="#64748B")
        self.lbl_vseg_file.pack(padx=14, pady=(0, 6), anchor="w")
        
        self.btn_select_vseg_file = ctk.CTkButton(
            card_file, text="📁  选择视频文件", command=self.select_vseg_file, height=36,
            fg_color="#F8FAFC", hover_color="#EEF2FF", border_width=1, border_color="#CBD5E1",
            text_color="#0F172A", font=(FONT_FAMILY, 12, "bold"), corner_radius=8
        )
        self.btn_select_vseg_file.pack(padx=14, pady=(0, 12), fill="x")
        
        card_params = ctk.CTkFrame(tab, fg_color="#FFFFFF", corner_radius=10, border_width=1, border_color="#E2E8F0")
        card_params.pack(fill="x", padx=12, pady=8)
        
        lbl_params_header = ctk.CTkLabel(card_params, text="分割参数设置", font=(FONT_FAMILY, 11, "bold"), text_color="#94A3B8")
        lbl_params_header.pack(anchor="w", padx=14, pady=(10, 4))
        
        self.frm_vseg_params = ctk.CTkFrame(card_params, fg_color="transparent")
        self.frm_vseg_params.pack(padx=14, pady=(0, 12), fill="x")
        self.frm_vseg_params.columnconfigure(0, weight=1)
        self.frm_vseg_params.columnconfigure(1, weight=0)
        
        self.lbl_vseg_parts = ctk.CTkLabel(self.frm_vseg_params, text="分割数量 (每段):", font=(FONT_FAMILY, 12), text_color="#1E293B")
        self.lbl_vseg_parts.grid(row=0, column=0, pady=6, sticky="w")
        self.entry_vseg_parts = ctk.CTkEntry(
            self.frm_vseg_params, width=110, height=32, font=("Consolas", 13, "bold"),
            text_color="#4F46E5", fg_color="#F8FAFC", border_color="#CBD5E1", border_width=1, corner_radius=6, justify="center"
        )
        self.entry_vseg_parts.insert(0, "8")
        self.entry_vseg_parts.grid(row=0, column=1, pady=6, sticky="e")
        
        self.lbl_vseg_overlap = ctk.CTkLabel(self.frm_vseg_params, text="前置重叠时间 (秒):", font=(FONT_FAMILY, 12), text_color="#1E293B")
        self.lbl_vseg_overlap.grid(row=1, column=0, pady=6, sticky="w")
        self.entry_vseg_overlap = ctk.CTkEntry(
            self.frm_vseg_params, width=110, height=32, font=("Consolas", 13, "bold"),
            text_color="#4F46E5", fg_color="#F8FAFC", border_color="#CBD5E1", border_width=1, corner_radius=6, justify="center"
        )
        self.entry_vseg_overlap.insert(0, "3")
        self.entry_vseg_overlap.grid(row=1, column=1, pady=6, sticky="e")
        
        card_outdir = ctk.CTkFrame(tab, fg_color="#FFFFFF", corner_radius=10, border_width=1, border_color="#E2E8F0")
        card_outdir.pack(fill="x", padx=12, pady=8)
        
        lbl_out_header = ctk.CTkLabel(card_outdir, text="输出位置", font=(FONT_FAMILY, 11, "bold"), text_color="#94A3B8")
        lbl_out_header.pack(anchor="w", padx=14, pady=(10, 2))
        
        self.lbl_vseg_outdir = ctk.CTkLabel(card_outdir, text="输出文件夹: 默认与源文件同目录", font=(FONT_FAMILY, 12), text_color="#64748B")
        self.lbl_vseg_outdir.pack(padx=14, pady=(0, 6), anchor="w")
        
        self.btn_select_vseg_outdir = ctk.CTkButton(
            card_outdir, text="📂  选择输出文件夹", command=self.select_vseg_outdir, height=36,
            fg_color="#F8FAFC", hover_color="#EEF2FF", border_width=1, border_color="#CBD5E1",
            text_color="#334155", font=(FONT_FAMILY, 12, "bold"), corner_radius=8
        )
        self.btn_select_vseg_outdir.pack(padx=14, pady=(0, 12), fill="x")
        
        self.btn_start_vseg = ctk.CTkButton(
            tab, text="⚡  开始分割", command=self.start_vseg_processing, height=44,
            font=(FONT_FAMILY, 14, "bold"), fg_color="#10B981", hover_color="#059669",
            text_color="#FFFFFF", corner_radius=8
        )
        self.btn_start_vseg.pack(padx=12, pady=(14, 8), fill="x")
        
        self.vseg_progress_bar = ctk.CTkProgressBar(tab, height=8, corner_radius=4, fg_color="#E2E8F0", progress_color="#10B981")
        self.vseg_progress_bar.pack(padx=12, pady=4, fill="x")
        self.vseg_progress_bar.set(0)
        
        self.lbl_vseg_status = ctk.CTkLabel(tab, text="就绪 · 等待任务开始", text_color="#64748B", font=(FONT_FAMILY, 12))
        self.lbl_vseg_status.pack(pady=(4, 8))
        
        self.vseg_input_file = None
        self.vseg_output_dir = None

    def setup_video_merge_tab(self):
        tab = self.tab_video_merge
        
        card_indir = ctk.CTkFrame(tab, fg_color="#FFFFFF", corner_radius=10, border_width=1, border_color="#E2E8F0")
        card_indir.pack(fill="x", padx=12, pady=(12, 8))
        
        lbl_in_header = ctk.CTkLabel(card_indir, text="待合并视频源", font=(FONT_FAMILY, 11, "bold"), text_color="#94A3B8")
        lbl_in_header.pack(anchor="w", padx=14, pady=(10, 2))
        
        self.lbl_vmerge_indir = ctk.CTkLabel(card_indir, text="未选择需要合并的视频文件夹", font=(FONT_FAMILY, 12), text_color="#64748B")
        self.lbl_vmerge_indir.pack(padx=14, pady=(0, 6), anchor="w")
        
        self.btn_select_vmerge_indir = ctk.CTkButton(
            card_indir, text="📁  选择输入文件夹", command=self.select_vmerge_indir, height=36,
            fg_color="#F8FAFC", hover_color="#EEF2FF", border_width=1, border_color="#CBD5E1",
            text_color="#0F172A", font=(FONT_FAMILY, 12, "bold"), corner_radius=8
        )
        self.btn_select_vmerge_indir.pack(padx=14, pady=(0, 12), fill="x")
        
        card_merge = ctk.CTkFrame(tab, fg_color="#FFFFFF", corner_radius=10, border_width=1, border_color="#E2E8F0")
        card_merge.pack(fill="x", padx=12, pady=8)
        
        lbl_merge_header = ctk.CTkLabel(card_merge, text="合并配置", font=(FONT_FAMILY, 11, "bold"), text_color="#94A3B8")
        lbl_merge_header.pack(anchor="w", padx=14, pady=(10, 2))
        
        self.lbl_vmerge_outfile = ctk.CTkLabel(card_merge, text="输出位置: 默认保存在输入文件夹内", font=(FONT_FAMILY, 12), text_color="#64748B")
        self.lbl_vmerge_outfile.pack(padx=14, pady=(0, 8), anchor="w")
        
        self.frm_vmerge_params = ctk.CTkFrame(card_merge, fg_color="transparent")
        self.frm_vmerge_params.pack(padx=14, pady=(0, 12), fill="x")
        self.frm_vmerge_params.columnconfigure(0, weight=1)
        self.frm_vmerge_params.columnconfigure(1, weight=0)
        
        self.lbl_vmerge_name = ctk.CTkLabel(self.frm_vmerge_params, text="合并后文件名:", font=(FONT_FAMILY, 12), text_color="#1E293B")
        self.lbl_vmerge_name.grid(row=0, column=0, sticky="w")
        self.entry_vmerge_name = ctk.CTkEntry(
            self.frm_vmerge_params, width=170, height=32, font=("Consolas", 12, "bold"),
            text_color="#4F46E5", fg_color="#F8FAFC", border_color="#CBD5E1", border_width=1, corner_radius=6
        )
        self.entry_vmerge_name.insert(0, "merged_output.mp4")
        self.entry_vmerge_name.grid(row=0, column=1, sticky="e")
        
        self.btn_start_vmerge = ctk.CTkButton(
            tab, text="⚡  开始合并", command=self.start_vmerge, height=44,
            font=(FONT_FAMILY, 14, "bold"), fg_color="#10B981", hover_color="#059669",
            text_color="#FFFFFF", corner_radius=8
        )
        self.btn_start_vmerge.pack(padx=12, pady=(24, 8), fill="x")
        
        self.vmerge_progress_bar = ctk.CTkProgressBar(tab, height=8, corner_radius=4, fg_color="#E2E8F0", progress_color="#10B981")
        self.vmerge_progress_bar.pack(padx=12, pady=4, fill="x")
        self.vmerge_progress_bar.set(0)
        
        self.lbl_vmerge_status = ctk.CTkLabel(tab, text="就绪 · 等待任务开始", text_color="#64748B", font=(FONT_FAMILY, 12))
        self.lbl_vmerge_status.pack(pady=(4, 8))
        
        self.vmerge_input_dir = None

    def select_file(self):
        file_path = filedialog.askopenfilename(
            title="选择音视频文件",
            filetypes=(("媒体文件", "*.mp3 *.wav *.m4a *.aac *.flac *.wma *.mp4 *.mkv *.avi *.mov *.flv *.wmv"), ("所有文件", "*.*"))
        )
        if file_path:
            self.input_file = file_path
            short_name = os.path.basename(file_path)
            if len(short_name) > 30:
                short_name = short_name[:15] + "..." + short_name[-10:]
            self.lbl_file.configure(text=f"已选择: {short_name}", text_color="#0F172A")
            
            if not self.output_dir:
                self.output_dir = os.path.dirname(file_path)
                out_short = self.output_dir
                if len(out_short) > 35:
                    out_short = out_short[:15] + "..." + out_short[-15:]
                self.lbl_outdir.configure(text=f"输出文件夹: {out_short}", text_color="#0F172A")

    def select_outdir(self):
        dir_path = filedialog.askdirectory(title="选择输出文件夹")
        if dir_path:
            self.output_dir = dir_path
            out_short = self.output_dir
            if len(out_short) > 35:
                out_short = out_short[:15] + "..." + out_short[-15:]
            self.lbl_outdir.configure(text=f"输出文件夹: {out_short}", text_color="#0F172A")

    def select_merge_indir(self):
        dir_path = filedialog.askdirectory(title="选择输入文件夹 (包含要合并的音视频)")
        if dir_path:
            self.merge_input_dir = dir_path
            in_short = self.merge_input_dir
            if len(in_short) > 35:
                in_short = in_short[:15] + "..." + in_short[-15:]
            self.lbl_merge_indir.configure(text=f"输入文件夹: {in_short}", text_color="#0F172A")

    def start_processing(self):
        if not self.input_file:
            messagebox.showwarning("提示", "请先选择一个音视频文件！")
            return
            
        try:
            num_parts = int(self.entry_parts.get())
            overlap = float(self.entry_overlap.get())
            if num_parts <= 0 or overlap < 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("提示", "分割数量需为正整数，重叠时间需为非负数！")
            return
            
        self.btn_start_segment.configure(state="disabled", text="⏳  处理中...")
        self.btn_select_file.configure(state="disabled")
        self.btn_select_outdir.configure(state="disabled")
        self.entry_parts.configure(state="disabled")
        self.entry_overlap.configure(state="disabled")
        
        self.progress_bar.set(0)
        self.lbl_status.configure(text="正在获取媒体信息...", text_color="#4F46E5")
        
        threading.Thread(target=process_audio, args=(
            self.input_file, self.output_dir, num_parts, overlap,
            self.update_progress, self.update_status, self.on_complete
        ), daemon=True).start()

    def start_merging(self):
        if not self.merge_input_dir:
            messagebox.showwarning("提示", "请先选择一个包含媒体文件的文件夹！")
            return
            
        output_name = self.entry_merge_name.get().strip()
        if not output_name:
            output_name = "merged_output.mp3"
            self.entry_merge_name.delete(0, 'end')
            self.entry_merge_name.insert(0, output_name)
            
        output_file = os.path.join(self.merge_input_dir, output_name)
        
        self.btn_start_merge.configure(state="disabled", text="⏳  处理中...")
        self.btn_select_merge_indir.configure(state="disabled")
        self.entry_merge_name.configure(state="disabled")
        
        self.merge_progress_bar.set(0)
        self.lbl_merge_status.configure(text="正在获取媒体列表...", text_color="#4F46E5")
        
        threading.Thread(target=merge_audio, args=(
            self.merge_input_dir, output_file,
            self.update_merge_progress, self.update_merge_status, self.on_merge_complete,
            self.var_safe_merge.get()
        ), daemon=True).start()

    def update_progress(self, value):
        self.after(0, lambda: self.progress_bar.set(value))
        
    def update_status(self, text):
        self.after(0, lambda: self.lbl_status.configure(text=text))
        
    def on_complete(self, success, error_msg=""):
        def _reset_ui():
            self.btn_start_segment.configure(state="normal", text="⚡  开始分割")
            self.btn_select_file.configure(state="normal")
            self.btn_select_outdir.configure(state="normal")
            self.entry_parts.configure(state="normal")
            self.entry_overlap.configure(state="normal")
            
            if success:
                self.lbl_status.configure(text_color="#10B981")
                messagebox.showinfo("成功", "分割已完成！")
            else:
                self.lbl_status.configure(text_color="#EF4444")
                err_detail = f"\n\n详情: {error_msg}" if error_msg else ""
                messagebox.showerror("错误", f"处理过程中发生错误。{err_detail}")
        self.after(0, _reset_ui)

    def update_merge_progress(self, value):
        self.after(0, lambda: self.merge_progress_bar.set(value))
        
    def update_merge_status(self, text):
        self.after(0, lambda: self.lbl_merge_status.configure(text=text))
        
    def on_merge_complete(self, success, error_msg=""):
        def _reset_ui():
            self.btn_start_merge.configure(state="normal", text="⚡  开始合并")
            self.btn_select_merge_indir.configure(state="normal")
            self.entry_merge_name.configure(state="normal")
            
            if success:
                self.lbl_merge_status.configure(text_color="#10B981")
                messagebox.showinfo("成功", "合并已完成！")
            else:
                self.lbl_merge_status.configure(text_color="#EF4444")
                err_detail = f"\n\n详情: {error_msg}" if error_msg else ""
                messagebox.showerror("错误", f"合并过程中发生错误。{err_detail}")
        self.after(0, _reset_ui)

    def select_vseg_file(self):
        file_path = filedialog.askopenfilename(
            title="选择视频文件",
            filetypes=(("视频文件", "*.mp4 *.mkv *.avi *.mov *.flv *.wmv *.webm *.ts"), ("所有文件", "*.*"))
        )
        if file_path:
            self.vseg_input_file = file_path
            short_name = os.path.basename(file_path)
            if len(short_name) > 30:
                short_name = short_name[:15] + "..." + short_name[-10:]
            self.lbl_vseg_file.configure(text=f"已选择: {short_name}", text_color="#0F172A")
            
            if not self.vseg_output_dir:
                self.vseg_output_dir = os.path.dirname(file_path)
                out_short = self.vseg_output_dir
                if len(out_short) > 35:
                    out_short = out_short[:15] + "..." + out_short[-15:]
                self.lbl_vseg_outdir.configure(text=f"输出文件夹: {out_short}", text_color="#0F172A")

    def select_vseg_outdir(self):
        dir_path = filedialog.askdirectory(title="选择输出文件夹")
        if dir_path:
            self.vseg_output_dir = dir_path
            out_short = self.vseg_output_dir
            if len(out_short) > 35:
                out_short = out_short[:15] + "..." + out_short[-15:]
            self.lbl_vseg_outdir.configure(text=f"输出文件夹: {out_short}", text_color="#0F172A")

    def select_vmerge_indir(self):
        dir_path = filedialog.askdirectory(title="选择输入文件夹 (包含要合并的视频)")
        if dir_path:
            self.vmerge_input_dir = dir_path
            in_short = self.vmerge_input_dir
            if len(in_short) > 35:
                in_short = in_short[:15] + "..." + in_short[-15:]
            self.lbl_vmerge_indir.configure(text=f"输入文件夹: {in_short}", text_color="#0F172A")

    def start_vseg_processing(self):
        if not self.vseg_input_file:
            messagebox.showwarning("提示", "请先选择一个视频文件！")
            return
            
        try:
            num_parts = int(self.entry_vseg_parts.get())
            overlap = float(self.entry_vseg_overlap.get())
            if num_parts <= 0 or overlap < 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("提示", "分割数量需为正整数，重叠时间需为非负数！")
            return
            
        self.btn_start_vseg.configure(state="disabled", text="⏳  处理中...")
        self.btn_select_vseg_file.configure(state="disabled")
        self.btn_select_vseg_outdir.configure(state="disabled")
        self.entry_vseg_parts.configure(state="disabled")
        self.entry_vseg_overlap.configure(state="disabled")
        
        self.vseg_progress_bar.set(0)
        self.lbl_vseg_status.configure(text="正在获取媒体信息...", text_color="#4F46E5")
        
        threading.Thread(target=process_video, args=(
            self.vseg_input_file, self.vseg_output_dir, num_parts, overlap,
            self.update_vseg_progress, self.update_vseg_status, self.on_vseg_complete
        ), daemon=True).start()

    def start_vmerge(self):
        if not self.vmerge_input_dir:
            messagebox.showwarning("提示", "请先选择一个包含视频文件的文件夹！")
            return
            
        output_name = self.entry_vmerge_name.get().strip()
        if not output_name:
            output_name = "merged_output.mp4"
            self.entry_vmerge_name.delete(0, 'end')
            self.entry_vmerge_name.insert(0, output_name)
            
        output_file = os.path.join(self.vmerge_input_dir, output_name)
        
        self.btn_start_vmerge.configure(state="disabled", text="⏳  处理中...")
        self.btn_select_vmerge_indir.configure(state="disabled")
        self.entry_vmerge_name.configure(state="disabled")
        
        self.vmerge_progress_bar.set(0)
        self.lbl_vmerge_status.configure(text="正在获取媒体列表...", text_color="#4F46E5")
        
        threading.Thread(target=merge_video, args=(
            self.vmerge_input_dir, output_file,
            self.update_vmerge_progress, self.update_vmerge_status, self.on_vmerge_complete
        ), daemon=True).start()

    def update_vseg_progress(self, value):
        self.after(0, lambda: self.vseg_progress_bar.set(value))
        
    def update_vseg_status(self, text):
        self.after(0, lambda: self.lbl_vseg_status.configure(text=text))
        
    def on_vseg_complete(self, success, error_msg=""):
        def _reset_ui():
            self.btn_start_vseg.configure(state="normal", text="⚡  开始分割")
            self.btn_select_vseg_file.configure(state="normal")
            self.btn_select_vseg_outdir.configure(state="normal")
            self.entry_vseg_parts.configure(state="normal")
            self.entry_vseg_overlap.configure(state="normal")
            
            if success:
                self.lbl_vseg_status.configure(text_color="#10B981")
                messagebox.showinfo("成功", "分割已完成！")
            else:
                self.lbl_vseg_status.configure(text_color="#EF4444")
                err_detail = f"\n\n详情: {error_msg}" if error_msg else ""
                messagebox.showerror("错误", f"处理过程中发生错误。{err_detail}")
        self.after(0, _reset_ui)

    def update_vmerge_progress(self, value):
        self.after(0, lambda: self.vmerge_progress_bar.set(value))
        
    def update_vmerge_status(self, text):
        self.after(0, lambda: self.lbl_vmerge_status.configure(text=text))
        
    def on_vmerge_complete(self, success, error_msg=""):
        def _reset_ui():
            self.btn_start_vmerge.configure(state="normal", text="⚡  开始合并")
            self.btn_select_vmerge_indir.configure(state="normal")
            self.entry_vmerge_name.configure(state="normal")
            
            if success:
                self.lbl_vmerge_status.configure(text_color="#10B981")
                messagebox.showinfo("成功", "合并已完成！")
            else:
                self.lbl_vmerge_status.configure(text_color="#EF4444")
                err_detail = f"\n\n详情: {error_msg}" if error_msg else ""
                messagebox.showerror("错误", f"合并过程中发生错误。{err_detail}")
        self.after(0, _reset_ui)

    # ============================================================
    # Video Clip Tab
    # ============================================================
    def setup_video_clip_tab(self):
        tab = self.tab_video_clip
        self.video_file = None
        self.video_duration = 0
        self.video_output_dir = None

        card_file = ctk.CTkFrame(tab, fg_color="#FFFFFF", corner_radius=10, border_width=1, border_color="#E2E8F0")
        card_file.pack(fill="x", padx=12, pady=(12, 8))
        
        lbl_file_header = ctk.CTkLabel(card_file, text="视频文件及信息", font=(FONT_FAMILY, 11, "bold"), text_color="#94A3B8")
        lbl_file_header.pack(anchor="w", padx=14, pady=(10, 2))
        
        self.lbl_video_file = ctk.CTkLabel(card_file, text="未选择视频文件", font=(FONT_FAMILY, 12), text_color="#64748B")
        self.lbl_video_file.pack(padx=14, pady=(0, 6), anchor="w")
        
        self.btn_select_video = ctk.CTkButton(
            card_file, text="📁  选择视频文件", command=self.select_video_file, height=36,
            fg_color="#F8FAFC", hover_color="#EEF2FF", border_width=1, border_color="#CBD5E1",
            text_color="#0F172A", font=(FONT_FAMILY, 12, "bold"), corner_radius=8
        )
        self.btn_select_video.pack(padx=14, pady=(0, 8), fill="x")
        
        self.frm_video_info = ctk.CTkFrame(card_file, fg_color="#F1F5F9", corner_radius=6, border_width=1, border_color="#E2E8F0")
        self.frm_video_info.pack(padx=14, pady=(0, 12), fill="x")
        self.lbl_vinfo_duration = ctk.CTkLabel(self.frm_video_info, text="时长: --", font=("Consolas", 12, "bold"), text_color="#4F46E5")
        self.lbl_vinfo_duration.pack(side="left", padx=10, pady=4)
        self.lbl_vinfo_resolution = ctk.CTkLabel(self.frm_video_info, text="分辨率: --", font=("Consolas", 12, "bold"), text_color="#4F46E5")
        self.lbl_vinfo_resolution.pack(side="left", padx=10, pady=4)
        self.lbl_vinfo_size = ctk.CTkLabel(self.frm_video_info, text="大小: --", font=("Consolas", 12, "bold"), text_color="#4F46E5")
        self.lbl_vinfo_size.pack(side="left", padx=10, pady=4)

        card_clip = ctk.CTkFrame(tab, fg_color="#FFFFFF", corner_radius=10, border_width=1, border_color="#E2E8F0")
        card_clip.pack(fill="x", padx=12, pady=8)
        
        lbl_clip_header = ctk.CTkLabel(card_clip, text="截取区间设定", font=(FONT_FAMILY, 11, "bold"), text_color="#94A3B8")
        lbl_clip_header.pack(anchor="w", padx=14, pady=(10, 4))
        
        self.frm_clip_params = ctk.CTkFrame(card_clip, fg_color="transparent")
        self.frm_clip_params.pack(padx=14, pady=(0, 12), fill="x")
        self.frm_clip_params.columnconfigure(0, weight=1)
        self.frm_clip_params.columnconfigure(1, weight=0)

        ctk.CTkLabel(self.frm_clip_params, text="开始时间:", font=(FONT_FAMILY, 12), text_color="#1E293B").grid(row=0, column=0, pady=6, sticky="w")
        self.entry_clip_start = ctk.CTkEntry(
            self.frm_clip_params, width=170, height=32, font=("Consolas", 12, "bold"),
            text_color="#4F46E5", fg_color="#F8FAFC", border_color="#CBD5E1", border_width=1, corner_radius=6,
            placeholder_text="例: 37.30 或 00:00:37.30"
        )
        self.entry_clip_start.grid(row=0, column=1, pady=6, sticky="e")

        ctk.CTkLabel(self.frm_clip_params, text="结束时间:", font=(FONT_FAMILY, 12), text_color="#1E293B").grid(row=1, column=0, pady=6, sticky="w")
        self.entry_clip_end = ctk.CTkEntry(
            self.frm_clip_params, width=170, height=32, font=("Consolas", 12, "bold"),
            text_color="#4F46E5", fg_color="#F8FAFC", border_color="#CBD5E1", border_width=1, corner_radius=6,
            placeholder_text="例: 47.90 或 00:00:47.90"
        )
        self.entry_clip_end.grid(row=1, column=1, pady=6, sticky="e")

        self.frm_clip_buttons = ctk.CTkFrame(tab, fg_color="transparent")
        self.frm_clip_buttons.pack(padx=12, pady=(12, 6), fill="x")
        
        self.btn_start_clip = ctk.CTkButton(
            self.frm_clip_buttons, text="⚡  开始截取", command=self.start_clipping, height=44,
            font=(FONT_FAMILY, 14, "bold"), fg_color="#10B981", hover_color="#059669",
            text_color="#FFFFFF", corner_radius=8
        )
        self.btn_start_clip.pack(side="left", fill="x", expand=True, padx=(0, 6))
        
        self.btn_open_clip_dir = ctk.CTkButton(
            self.frm_clip_buttons, text="📂  打开输出目录", command=self.open_clip_output_dir, height=44,
            font=(FONT_FAMILY, 12, "bold"), fg_color="#FFFFFF", border_width=1, border_color="#CBD5E1",
            text_color="#334155", hover_color="#F1F5F9", corner_radius=8
        )
        self.btn_open_clip_dir.pack(side="left", fill="x", expand=True, padx=(6, 0))

        self.clip_progress_bar = ctk.CTkProgressBar(tab, height=8, corner_radius=4, fg_color="#E2E8F0", progress_color="#10B981")
        self.clip_progress_bar.pack(padx=12, pady=4, fill="x")
        self.clip_progress_bar.set(0)
        
        self.lbl_clip_status = ctk.CTkLabel(tab, text="就绪 · 等待任务开始", text_color="#64748B", font=(FONT_FAMILY, 12))
        self.lbl_clip_status.pack(pady=(4, 8))

    def select_video_file(self):
        file_path = filedialog.askopenfilename(
            title="选择视频文件",
            filetypes=(("视频文件", "*.mp4 *.mkv *.avi *.mov *.flv *.wmv *.webm *.ts"), ("所有文件", "*.*"))
        )
        if not file_path:
            return
        self.video_file = file_path
        self.video_output_dir = os.path.dirname(file_path)
        short_name = os.path.basename(file_path)
        if len(short_name) > 35:
            short_name = short_name[:18] + "..." + short_name[-12:]
        self.lbl_video_file.configure(text=f"已选择: {short_name}", text_color="#0F172A")
        threading.Thread(target=self._load_video_info, args=(file_path,), daemon=True).start()

    def _load_video_info(self, file_path):
        try:
            duration, w, h, size = get_video_info(file_path)
            self.video_duration = duration
            self.after(0, lambda: self.lbl_vinfo_duration.configure(text=f"时长: {format_duration(duration)}"))
            res_text = f"{w}x{h}" if w and h else "未知"
            self.after(0, lambda: self.lbl_vinfo_resolution.configure(text=f"分辨率: {res_text}"))
            self.after(0, lambda: self.lbl_vinfo_size.configure(text=f"大小: {format_file_size(size)}"))
        except Exception as e:
            self.after(0, lambda: self.lbl_clip_status.configure(text=f"获取信息失败: {e}", text_color="#EF4444"))

    def start_clipping(self):
        if not self.video_file:
            messagebox.showwarning("提示", "请先选择一个视频文件！")
            return
        try:
            start_t = parse_time_input(self.entry_clip_start.get())
            end_t = parse_time_input(self.entry_clip_end.get())
        except (ValueError, IndexError):
            messagebox.showwarning("提示", "时间格式不正确！\n支持: 37.30 或 00:00:37.30")
            return
        if start_t < 0:
            messagebox.showwarning("提示", "开始时间不能为负数！")
            return
        if end_t <= start_t:
            messagebox.showwarning("提示", "结束时间必须大于开始时间！")
            return
        if self.video_duration > 0 and end_t > self.video_duration + 0.5:
            messagebox.showwarning("提示", f"结束时间不能超过视频总时长 ({format_duration(self.video_duration)})！")
            return

        base, ext = os.path.splitext(os.path.basename(self.video_file))
        start_str = f"{start_t:.2f}"
        end_str = f"{end_t:.2f}"
        out_name = f"{base}_clip_{start_str}_{end_str}{ext}"
        output_file = os.path.join(self.video_output_dir, out_name)

        self.btn_start_clip.configure(state="disabled", text="⏳  处理中...")
        self.btn_select_video.configure(state="disabled")
        self.entry_clip_start.configure(state="disabled")
        self.entry_clip_end.configure(state="disabled")
        self.clip_progress_bar.set(0)
        self.lbl_clip_status.configure(text="正在截取...", text_color="#4F46E5")

        threading.Thread(target=clip_video, args=(
            self.video_file, output_file, start_t, end_t,
            self.update_clip_progress, self.update_clip_status, self.on_clip_complete
        ), daemon=True).start()

    def open_clip_output_dir(self):
        target = self.video_output_dir
        if target and os.path.isdir(target):
            try:
                os.startfile(target)
            except Exception as e:
                messagebox.showerror("错误", f"无法打开输出目录: {e}")
        else:
            messagebox.showinfo("提示", "输出目录不存在，请先选择视频文件。")

    def update_clip_progress(self, value):
        self.after(0, lambda: self.clip_progress_bar.set(value))

    def update_clip_status(self, text):
        self.after(0, lambda: self.lbl_clip_status.configure(text=text))

    def on_clip_complete(self, success, error_msg=""):
        def _reset():
            self.btn_start_clip.configure(state="normal", text="⚡  开始截取")
            self.btn_select_video.configure(state="normal")
            self.entry_clip_start.configure(state="normal")
            self.entry_clip_end.configure(state="normal")
            if success:
                self.lbl_clip_status.configure(text_color="#10B981")
                messagebox.showinfo("成功", "视频截取已完成！")
            else:
                self.lbl_clip_status.configure(text_color="#EF4444")
                err_detail = f"\n\n详情: {error_msg}" if error_msg else ""
                messagebox.showerror("错误", f"截取过程中发生错误。{err_detail}")
        self.after(0, _reset)

    # ============================================================
    # Audio Clip Tab
    # ============================================================
    def setup_audio_clip_tab(self):
        tab = self.tab_audio_clip
        self.audio_clip_file = None
        self.audio_clip_duration = 0
        self.audio_clip_output_dir = None

        card_file = ctk.CTkFrame(tab, fg_color="#FFFFFF", corner_radius=10, border_width=1, border_color="#E2E8F0")
        card_file.pack(fill="x", padx=12, pady=(12, 8))
        
        lbl_file_header = ctk.CTkLabel(card_file, text="音频文件及信息", font=(FONT_FAMILY, 11, "bold"), text_color="#94A3B8")
        lbl_file_header.pack(anchor="w", padx=14, pady=(10, 2))
        
        self.lbl_audio_clip_file = ctk.CTkLabel(card_file, text="未选择音频文件", font=(FONT_FAMILY, 12), text_color="#64748B")
        self.lbl_audio_clip_file.pack(padx=14, pady=(0, 6), anchor="w")
        
        self.btn_select_audio_clip = ctk.CTkButton(
            card_file, text="📁  选择音频文件", command=self.select_audio_clip_file, height=36,
            fg_color="#F8FAFC", hover_color="#EEF2FF", border_width=1, border_color="#CBD5E1",
            text_color="#0F172A", font=(FONT_FAMILY, 12, "bold"), corner_radius=8
        )
        self.btn_select_audio_clip.pack(padx=14, pady=(0, 8), fill="x")
        
        self.frm_audio_info = ctk.CTkFrame(card_file, fg_color="#F1F5F9", corner_radius=6, border_width=1, border_color="#E2E8F0")
        self.frm_audio_info.pack(padx=14, pady=(0, 12), fill="x")
        self.lbl_ainfo_duration = ctk.CTkLabel(self.frm_audio_info, text="时长: --", font=("Consolas", 12, "bold"), text_color="#4F46E5")
        self.lbl_ainfo_duration.pack(side="left", padx=12, pady=4)
        self.lbl_ainfo_size = ctk.CTkLabel(self.frm_audio_info, text="大小: --", font=("Consolas", 12, "bold"), text_color="#4F46E5")
        self.lbl_ainfo_size.pack(side="left", padx=12, pady=4)

        card_clip = ctk.CTkFrame(tab, fg_color="#FFFFFF", corner_radius=10, border_width=1, border_color="#E2E8F0")
        card_clip.pack(fill="x", padx=12, pady=8)
        
        lbl_clip_header = ctk.CTkLabel(card_clip, text="截取区间设定", font=(FONT_FAMILY, 11, "bold"), text_color="#94A3B8")
        lbl_clip_header.pack(anchor="w", padx=14, pady=(10, 4))
        
        self.frm_aclip_params = ctk.CTkFrame(card_clip, fg_color="transparent")
        self.frm_aclip_params.pack(padx=14, pady=(0, 12), fill="x")
        self.frm_aclip_params.columnconfigure(0, weight=1)
        self.frm_aclip_params.columnconfigure(1, weight=0)

        ctk.CTkLabel(self.frm_aclip_params, text="开始时间:", font=(FONT_FAMILY, 12), text_color="#1E293B").grid(row=0, column=0, pady=6, sticky="w")
        self.entry_aclip_start = ctk.CTkEntry(
            self.frm_aclip_params, width=170, height=32, font=("Consolas", 12, "bold"),
            text_color="#4F46E5", fg_color="#F8FAFC", border_color="#CBD5E1", border_width=1, corner_radius=6,
            placeholder_text="例: 37.30 或 00:00:37.30"
        )
        self.entry_aclip_start.grid(row=0, column=1, pady=6, sticky="e")

        ctk.CTkLabel(self.frm_aclip_params, text="结束时间:", font=(FONT_FAMILY, 12), text_color="#1E293B").grid(row=1, column=0, pady=6, sticky="w")
        self.entry_aclip_end = ctk.CTkEntry(
            self.frm_aclip_params, width=170, height=32, font=("Consolas", 12, "bold"),
            text_color="#4F46E5", fg_color="#F8FAFC", border_color="#CBD5E1", border_width=1, corner_radius=6,
            placeholder_text="例: 47.90 或 00:00:47.90"
        )
        self.entry_aclip_end.grid(row=1, column=1, pady=6, sticky="e")

        self.frm_aclip_buttons = ctk.CTkFrame(tab, fg_color="transparent")
        self.frm_aclip_buttons.pack(padx=12, pady=(12, 6), fill="x")
        
        self.btn_start_aclip = ctk.CTkButton(
            self.frm_aclip_buttons, text="⚡  开始截取", command=self.start_audio_clipping, height=44,
            font=(FONT_FAMILY, 14, "bold"), fg_color="#10B981", hover_color="#059669",
            text_color="#FFFFFF", corner_radius=8
        )
        self.btn_start_aclip.pack(side="left", fill="x", expand=True, padx=(0, 6))
        
        self.btn_open_aclip_dir = ctk.CTkButton(
            self.frm_aclip_buttons, text="📂  打开输出目录", command=self.open_audio_clip_output_dir, height=44,
            font=(FONT_FAMILY, 12, "bold"), fg_color="#FFFFFF", border_width=1, border_color="#CBD5E1",
            text_color="#334155", hover_color="#F1F5F9", corner_radius=8
        )
        self.btn_open_aclip_dir.pack(side="left", fill="x", expand=True, padx=(6, 0))

        self.aclip_progress_bar = ctk.CTkProgressBar(tab, height=8, corner_radius=4, fg_color="#E2E8F0", progress_color="#10B981")
        self.aclip_progress_bar.pack(padx=12, pady=4, fill="x")
        self.aclip_progress_bar.set(0)
        
        self.lbl_aclip_status = ctk.CTkLabel(tab, text="就绪 · 等待任务开始", text_color="#64748B", font=(FONT_FAMILY, 12))
        self.lbl_aclip_status.pack(pady=(4, 8))

    def select_audio_clip_file(self):
        file_path = filedialog.askopenfilename(
            title="选择音频文件",
            filetypes=(("音频文件", "*.mp3 *.wav *.m4a *.aac *.flac *.wma"), ("所有文件", "*.*"))
        )
        if not file_path:
            return
        self.audio_clip_file = file_path
        self.audio_clip_output_dir = os.path.dirname(file_path)
        short_name = os.path.basename(file_path)
        if len(short_name) > 35:
            short_name = short_name[:18] + "..." + short_name[-12:]
        self.lbl_audio_clip_file.configure(text=f"已选择: {short_name}", text_color="#0F172A")
        threading.Thread(target=self._load_audio_info, args=(file_path,), daemon=True).start()

    def _load_audio_info(self, file_path):
        try:
            duration, size = get_audio_info(file_path)
            self.audio_clip_duration = duration
            self.after(0, lambda: self.lbl_ainfo_duration.configure(text=f"时长: {format_duration(duration)}"))
            self.after(0, lambda: self.lbl_ainfo_size.configure(text=f"大小: {format_file_size(size)}"))
        except Exception as e:
            self.after(0, lambda: self.lbl_aclip_status.configure(text=f"获取信息失败: {e}", text_color="#EF4444"))

    def start_audio_clipping(self):
        if not self.audio_clip_file:
            messagebox.showwarning("提示", "请先选择一个音频文件！")
            return
        try:
            start_t = parse_time_input(self.entry_aclip_start.get())
            end_t = parse_time_input(self.entry_aclip_end.get())
        except (ValueError, IndexError):
            messagebox.showwarning("提示", "时间格式不正确！\n支持: 37.30 或 00:00:37.30")
            return
        if start_t < 0:
            messagebox.showwarning("提示", "开始时间不能为负数！")
            return
        if end_t <= start_t:
            messagebox.showwarning("提示", "结束时间必须大于开始时间！")
            return
        if self.audio_clip_duration > 0 and end_t > self.audio_clip_duration + 0.5:
            messagebox.showwarning("提示", f"结束时间不能超过音频总时长 ({format_duration(self.audio_clip_duration)})！")
            return

        base, ext = os.path.splitext(os.path.basename(self.audio_clip_file))
        start_str = f"{start_t:.2f}"
        end_str = f"{end_t:.2f}"
        out_name = f"{base}_clip_{start_str}_{end_str}{ext}"
        output_file = os.path.join(self.audio_clip_output_dir, out_name)

        self.btn_start_aclip.configure(state="disabled", text="⏳  处理中...")
        self.btn_select_audio_clip.configure(state="disabled")
        self.entry_aclip_start.configure(state="disabled")
        self.entry_aclip_end.configure(state="disabled")
        self.aclip_progress_bar.set(0)
        self.lbl_aclip_status.configure(text="正在截取...", text_color="#4F46E5")

        threading.Thread(target=clip_audio, args=(
            self.audio_clip_file, output_file, start_t, end_t,
            self.update_aclip_progress, self.update_aclip_status, self.on_aclip_complete
        ), daemon=True).start()

    def open_audio_clip_output_dir(self):
        target = self.audio_clip_output_dir
        if target and os.path.isdir(target):
            try:
                os.startfile(target)
            except Exception as e:
                messagebox.showerror("错误", f"无法打开输出目录: {e}")
        else:
            messagebox.showinfo("提示", "输出目录不存在，请先选择音频文件。")

    def update_aclip_progress(self, value):
        self.after(0, lambda: self.aclip_progress_bar.set(value))

    def update_aclip_status(self, text):
        self.after(0, lambda: self.lbl_aclip_status.configure(text=text))

    def on_aclip_complete(self, success, error_msg=""):
        def _reset():
            self.btn_start_aclip.configure(state="normal", text="⚡  开始截取")
            self.btn_select_audio_clip.configure(state="normal")
            self.entry_aclip_start.configure(state="normal")
            self.entry_aclip_end.configure(state="normal")
            if success:
                self.lbl_aclip_status.configure(text_color="#10B981")
                messagebox.showinfo("成功", "音频截取已完成！")
            else:
                self.lbl_aclip_status.configure(text_color="#EF4444")
                err_detail = f"\n\n详情: {error_msg}" if error_msg else ""
                messagebox.showerror("错误", f"截取过程中发生错误。{err_detail}")
        self.after(0, _reset)

if __name__ == "__main__":
    multiprocessing.freeze_support()

    # 单例运行守护：防多开并置顶已有窗口
    try:
        from single_instance import SingleInstanceGuard
        _guard = SingleInstanceGuard("Local\\MediaSegmenter_SingleInstance_Mutex_2026")
        if _guard.is_already_running():
            _guard.restore_and_activate_existing_window("音视频处理工具 · Media Segmenter")
            sys.exit(0)
    except Exception as e:
        safe_log(f"SingleInstanceGuard warning: {e}")

    app = MediaSegmenterApp()
    app.mainloop()
