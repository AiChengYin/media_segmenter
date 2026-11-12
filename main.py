import os
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

CREATE_NO_WINDOW = 0x08000000

def get_audio_duration(file_path):
    cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW, text=True, encoding='utf-8')
        if result.returncode != 0:
            raise Exception(result.stderr.strip())
        return float(result.stdout.strip())
    except Exception as e:
        raise Exception(f"无法获取媒体时长: {e}")

def process_audio(input_file, output_dir, num_parts, overlap, progress_callback, status_callback, complete_callback):
    try:
        duration = get_audio_duration(input_file)
        base_length = duration / num_parts
        
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        
        for i in range(1, num_parts + 1):
            status_callback(f"正在分割: 第 {i}/{num_parts} 段...")
            
            end_time = i * base_length
            start_time = max(0, (i - 1) * base_length - overlap)
            segment_duration = end_time - start_time
            
            part_name = f"{base_name}_part{i:02d}.mp3"
            output_file = os.path.join(output_dir, part_name)
            
            cmd = [
                'ffmpeg', '-y', 
                '-i', input_file, 
                '-ss', str(start_time), 
                '-t', str(segment_duration), 
                output_file
            ]
            
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW, text=True, encoding='utf-8')
            if result.returncode != 0:
                print(result.stderr)
                raise Exception(f"FFmpeg 处理第 {i} 段时出错。")
                
            progress_callback(i / num_parts)
            
        status_callback("处理完成！全部片段已成功生成！")
        complete_callback(True)
        
    except Exception as e:
        status_callback(f"错误: {str(e)}")
        complete_callback(False)

def merge_audio(input_dir, output_file, progress_callback, status_callback, complete_callback, safe_mode=False):
    try:
        valid_extensions = ('.mp3', '.wav', '.m4a', '.aac', '.flac', '.wma', '.mp4', '.mkv', '.avi', '.mov', '.flv', '.wmv')
        audio_files = [f for f in os.listdir(input_dir) if f.lower().endswith(valid_extensions)]
        
        # Filter out the output file itself if it exists in the directory
        output_filename = os.path.basename(output_file)
        audio_files = [f for f in audio_files if f != output_filename]
        
        audio_files.sort()
        
        if not audio_files:
            raise Exception("该文件夹下没有找到支持的音视频文件！")
            
        if safe_mode:
            import shutil
            temp_dir = os.path.join(input_dir, "temp_safe_merge")
            os.makedirs(temp_dir, exist_ok=True)
            temp_files = []
            
            try:
                for idx, af in enumerate(audio_files):
                    progress_callback(idx / len(audio_files) * 0.8)
                    status_callback(f"正在统一格式: {idx+1}/{len(audio_files)}")
                    in_path = os.path.join(input_dir, af)
                    out_path = os.path.join(temp_dir, f"temp_{idx:04d}.wav")
                    cmd_cnv = ['ffmpeg', '-y', '-i', in_path, '-ar', '44100', '-ac', '2', out_path]
                    subprocess.run(cmd_cnv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW)
                    temp_files.append(out_path)
                
                concat_file_path = os.path.join(temp_dir, "concat_list.txt")
                with open(concat_file_path, 'w', encoding='utf-8') as f:
                    for tf in temp_files:
                        f.write(f"file '{os.path.basename(tf)}'\n")
                        
                status_callback("正在合并已统一的音频...")
                progress_callback(0.9)
                
                cmd_merge = [
                    'ffmpeg', '-y',
                    '-f', 'concat',
                    '-safe', '0',
                    '-i', concat_file_path,
                    output_file
                ]
                result = subprocess.run(cmd_merge, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW, text=True, encoding='utf-8', cwd=temp_dir)
                if result.returncode != 0:
                    raise Exception("安全合并失败！")
                    
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)
                
            progress_callback(1.0)
            status_callback("合并完成！")
            complete_callback(True)
            return

        concat_file_path = os.path.join(input_dir, "concat_list.txt")
        with open(concat_file_path, 'w', encoding='utf-8') as f:
            for audio_file in audio_files:
                f.write(f"file '{audio_file}'\n")

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
        
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW, text=True, encoding='utf-8', cwd=input_dir)
        
        if result.returncode != 0:
            print("Copy codec failed, trying re-encoding...", result.stderr)
            status_callback("无损合并失败，正在重新编码合并...")
            progress_callback(0.5)
            
            # Re-encode command
            cmd_reencode = [
                'ffmpeg', '-y',
                '-f', 'concat',
                '-safe', '0',
                '-i', concat_file_path,
                output_file
            ]
            result_reencode = subprocess.run(cmd_reencode, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW, text=True, encoding='utf-8', cwd=input_dir)
            
            if result_reencode.returncode != 0:
                print(result_reencode.stderr)
                raise Exception("FFmpeg 合并时出错。")

        try:
            os.remove(concat_file_path)
        except:
            pass

        progress_callback(1.0)
        status_callback("合并完成！")
        complete_callback(True)

    except Exception as e:
        status_callback(f"错误: {str(e)}")
        complete_callback(False)

def process_video(input_file, output_dir, num_parts, overlap, progress_callback, status_callback, complete_callback):
    try:
        duration = get_audio_duration(input_file)
        base_length = duration / num_parts
        
        base_name, ext = os.path.splitext(os.path.basename(input_file))
        if not ext:
            ext = '.mp4'
        
        for i in range(1, num_parts + 1):
            status_callback(f"正在分割: 第 {i}/{num_parts} 段...")
            
            end_time = i * base_length
            start_time = max(0, (i - 1) * base_length - overlap)
            segment_duration = end_time - start_time
            
            part_name = f"{base_name}_part{i:02d}{ext}"
            output_file = os.path.join(output_dir, part_name)
            
            cmd = [
                'ffmpeg', '-y', 
                '-ss', str(start_time),
                '-i', input_file, 
                '-t', str(segment_duration), 
                '-c', 'copy',
                '-avoid_negative_ts', 'make_zero',
                output_file
            ]
            
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW, text=True, encoding='utf-8')
            if result.returncode != 0:
                print(result.stderr)
                status_callback(f"无损分割失败，尝试重新编码...")
                cmd_re = [
                    'ffmpeg', '-y', 
                    '-ss', str(start_time),
                    '-i', input_file, 
                    '-t', str(segment_duration), 
                    '-avoid_negative_ts', 'make_zero',
                    output_file
                ]
                result_re = subprocess.run(cmd_re, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW, text=True, encoding='utf-8')
                if result_re.returncode != 0:
                    raise Exception(f"FFmpeg 处理第 {i} 段时出错。")
                
            progress_callback(i / num_parts)
            
        status_callback("处理完成！全部片段已成功生成！")
        complete_callback(True)
        
    except Exception as e:
        status_callback(f"错误: {str(e)}")
        complete_callback(False)

def merge_video(input_dir, output_file, progress_callback, status_callback, complete_callback):
    try:
        valid_extensions = ('.mp4', '.mkv', '.avi', '.mov', '.flv', '.wmv', '.webm', '.ts')
        video_files = [f for f in os.listdir(input_dir) if f.lower().endswith(valid_extensions)]
        
        output_filename = os.path.basename(output_file)
        video_files = [f for f in video_files if f != output_filename]
        
        video_files.sort()
        
        if not video_files:
            raise Exception("该文件夹下没有找到支持的视频文件！")

        concat_file_path = os.path.join(input_dir, "concat_list.txt")
        with open(concat_file_path, 'w', encoding='utf-8') as f:
            for video_file in video_files:
                f.write(f"file '{video_file}'\n")

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
        
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW, text=True, encoding='utf-8', cwd=input_dir)
        
        if result.returncode != 0:
            print("Copy codec failed, trying re-encoding...", result.stderr)
            status_callback("无损合并失败，正在重新编码合并...")
            progress_callback(0.5)
            
            cmd_reencode = [
                'ffmpeg', '-y',
                '-f', 'concat',
                '-safe', '0',
                '-i', concat_file_path,
                output_file
            ]
            result_reencode = subprocess.run(cmd_reencode, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW, text=True, encoding='utf-8', cwd=input_dir)
            
            if result_reencode.returncode != 0:
                print(result_reencode.stderr)
                raise Exception("FFmpeg 合并时出错。")

        try:
            os.remove(concat_file_path)
        except:
            pass

        progress_callback(1.0)
        status_callback("合并完成！")
        complete_callback(True)

    except Exception as e:
        status_callback(f"错误: {str(e)}")
        complete_callback(False)


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
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                creationflags=CREATE_NO_WINDOW, text=True, encoding='utf-8')
        if result.returncode != 0:
            raise Exception(result.stderr.strip())
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
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                creationflags=CREATE_NO_WINDOW, text=True, encoding='utf-8')
        if result.returncode != 0:
            raise Exception(result.stderr.strip())
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
            '-ss', str(start_time),
            '-i', input_file,
            '-t', str(duration),
            '-c', 'copy',
            '-avoid_negative_ts', 'make_zero',
            output_file
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                creationflags=CREATE_NO_WINDOW, text=True, encoding='utf-8')
        if result.returncode != 0:
            status_callback("无损截取失败，正在重新编码...")
            progress_callback(0.4)
            cmd_re = [
                'ffmpeg', '-y',
                '-ss', str(start_time),
                '-i', input_file,
                '-t', str(duration),
                '-avoid_negative_ts', 'make_zero',
                output_file
            ]
            result_re = subprocess.run(cmd_re, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       creationflags=CREATE_NO_WINDOW, text=True, encoding='utf-8')
            if result_re.returncode != 0:
                print(result_re.stderr)
                raise Exception("FFmpeg 截取视频时出错。")
        progress_callback(1.0)
        status_callback("截取完成！")
        complete_callback(True)
    except Exception as e:
        status_callback(f"错误: {str(e)}")
        complete_callback(False)


def clip_audio(input_file, output_file, start_time, end_time, progress_callback, status_callback, complete_callback):
    try:
        status_callback("正在截取音频 (无损模式)...")
        progress_callback(0.2)
        duration = end_time - start_time
        cmd = [
            'ffmpeg', '-y',
            '-ss', str(start_time),
            '-i', input_file,
            '-t', str(duration),
            '-c', 'copy',
            output_file
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                creationflags=CREATE_NO_WINDOW, text=True, encoding='utf-8')
        if result.returncode != 0:
            status_callback("无损截取失败，正在重新编码...")
            progress_callback(0.4)
            cmd_re = [
                'ffmpeg', '-y',
                '-ss', str(start_time),
                '-i', input_file,
                '-t', str(duration),
                output_file
            ]
            result_re = subprocess.run(cmd_re, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       creationflags=CREATE_NO_WINDOW, text=True, encoding='utf-8')
            if result_re.returncode != 0:
                print(result_re.stderr)
                raise Exception("FFmpeg 截取音频时出错。")
        progress_callback(1.0)
        status_callback("截取完成！")
        complete_callback(True)
    except Exception as e:
        status_callback(f"错误: {str(e)}")
        complete_callback(False)


class MediaSegmenterApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("Light")
        ctk.set_default_color_theme("blue")
        
        self.title("音视频处理工具 · Media Segmenter")
        self.geometry("640x730")
        self.resizable(False, False)
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
            segmented_button_font=("Microsoft YaHei UI", 13, "bold"),
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
            segmented_button_font=("Microsoft YaHei UI", 12, "bold"),
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
            segmented_button_font=("Microsoft YaHei UI", 12, "bold"),
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
        
        lbl_file_header = ctk.CTkLabel(card_file, text="源媒体文件", font=("Microsoft YaHei UI", 11, "bold"), text_color="#94A3B8")
        lbl_file_header.pack(anchor="w", padx=14, pady=(10, 2))
        
        self.lbl_file = ctk.CTkLabel(card_file, text="未选择媒体文件", font=("Microsoft YaHei UI", 12), text_color="#64748B")
        self.lbl_file.pack(padx=14, pady=(0, 6), anchor="w")
        
        self.btn_select_file = ctk.CTkButton(
            card_file, text="📁  选择媒体文件", command=self.select_file, height=36,
            fg_color="#F8FAFC", hover_color="#EEF2FF", border_width=1, border_color="#CBD5E1",
            text_color="#0F172A", font=("Microsoft YaHei UI", 12, "bold"), corner_radius=8
        )
        self.btn_select_file.pack(padx=14, pady=(0, 12), fill="x")
        
        # 2. Parameters Card
        card_params = ctk.CTkFrame(tab, fg_color="#FFFFFF", corner_radius=10, border_width=1, border_color="#E2E8F0")
        card_params.pack(fill="x", padx=12, pady=8)
        
        lbl_params_header = ctk.CTkLabel(card_params, text="分割参数设置", font=("Microsoft YaHei UI", 11, "bold"), text_color="#94A3B8")
        lbl_params_header.pack(anchor="w", padx=14, pady=(10, 4))
        
        self.frm_params = ctk.CTkFrame(card_params, fg_color="transparent")
        self.frm_params.pack(padx=14, pady=(0, 12), fill="x")
        self.frm_params.columnconfigure(0, weight=1)
        self.frm_params.columnconfigure(1, weight=0)
        
        self.lbl_parts = ctk.CTkLabel(self.frm_params, text="分割数量 (每段):", font=("Microsoft YaHei UI", 12), text_color="#1E293B")
        self.lbl_parts.grid(row=0, column=0, pady=6, sticky="w")
        self.entry_parts = ctk.CTkEntry(
            self.frm_params, width=110, height=32, font=("Consolas", 13, "bold"),
            text_color="#4F46E5", fg_color="#F8FAFC", border_color="#CBD5E1", border_width=1, corner_radius=6, justify="center"
        )
        self.entry_parts.insert(0, "8")
        self.entry_parts.grid(row=0, column=1, pady=6, sticky="e")
        
        self.lbl_overlap = ctk.CTkLabel(self.frm_params, text="前置重叠时间 (秒):", font=("Microsoft YaHei UI", 12), text_color="#1E293B")
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
        
        lbl_out_header = ctk.CTkLabel(card_outdir, text="输出位置", font=("Microsoft YaHei UI", 11, "bold"), text_color="#94A3B8")
        lbl_out_header.pack(anchor="w", padx=14, pady=(10, 2))
        
        self.lbl_outdir = ctk.CTkLabel(card_outdir, text="输出文件夹: 默认与源文件同目录", font=("Microsoft YaHei UI", 12), text_color="#64748B")
        self.lbl_outdir.pack(padx=14, pady=(0, 6), anchor="w")
        
        self.btn_select_outdir = ctk.CTkButton(
            card_outdir, text="📂  选择输出文件夹", command=self.select_outdir, height=36,
            fg_color="#F8FAFC", hover_color="#EEF2FF", border_width=1, border_color="#CBD5E1",
            text_color="#334155", font=("Microsoft YaHei UI", 12, "bold"), corner_radius=8
        )
        self.btn_select_outdir.pack(padx=14, pady=(0, 12), fill="x")
        
        # 4. Action & Progress
        self.btn_start_segment = ctk.CTkButton(
            tab, text="⚡  开始分割", command=self.start_processing, height=44,
            font=("Microsoft YaHei UI", 14, "bold"), fg_color="#10B981", hover_color="#059669",
            text_color="#FFFFFF", corner_radius=8
        )
        self.btn_start_segment.pack(padx=12, pady=(14, 8), fill="x")
        
        self.progress_bar = ctk.CTkProgressBar(tab, height=8, corner_radius=4, fg_color="#E2E8F0", progress_color="#10B981")
        self.progress_bar.pack(padx=12, pady=4, fill="x")
        self.progress_bar.set(0)
        
        self.lbl_status = ctk.CTkLabel(tab, text="就绪 · 等待任务开始", text_color="#64748B", font=("Microsoft YaHei UI", 12))
        self.lbl_status.pack(pady=(4, 8))
        
        self.input_file = None
        self.output_dir = None

    def setup_merge_tab(self):
        tab = self.tab_merge
        
        card_indir = ctk.CTkFrame(tab, fg_color="#FFFFFF", corner_radius=10, border_width=1, border_color="#E2E8F0")
        card_indir.pack(fill="x", padx=12, pady=(12, 8))
        
        lbl_in_header = ctk.CTkLabel(card_indir, text="待合并媒体源", font=("Microsoft YaHei UI", 11, "bold"), text_color="#94A3B8")
        lbl_in_header.pack(anchor="w", padx=14, pady=(10, 2))
        
        self.lbl_merge_indir = ctk.CTkLabel(card_indir, text="未选择需要合并的媒体文件夹", font=("Microsoft YaHei UI", 12), text_color="#64748B")
        self.lbl_merge_indir.pack(padx=14, pady=(0, 6), anchor="w")
        
        self.btn_select_merge_indir = ctk.CTkButton(
            card_indir, text="📁  选择输入文件夹", command=self.select_merge_indir, height=36,
            fg_color="#F8FAFC", hover_color="#EEF2FF", border_width=1, border_color="#CBD5E1",
            text_color="#0F172A", font=("Microsoft YaHei UI", 12, "bold"), corner_radius=8
        )
        self.btn_select_merge_indir.pack(padx=14, pady=(0, 12), fill="x")
        
        card_merge = ctk.CTkFrame(tab, fg_color="#FFFFFF", corner_radius=10, border_width=1, border_color="#E2E8F0")
        card_merge.pack(fill="x", padx=12, pady=8)
        
        lbl_merge_header = ctk.CTkLabel(card_merge, text="合并配置", font=("Microsoft YaHei UI", 11, "bold"), text_color="#94A3B8")
        lbl_merge_header.pack(anchor="w", padx=14, pady=(10, 2))
        
        self.lbl_merge_outfile = ctk.CTkLabel(card_merge, text="输出位置: 默认保存在输入文件夹内", font=("Microsoft YaHei UI", 12), text_color="#64748B")
        self.lbl_merge_outfile.pack(padx=14, pady=(0, 8), anchor="w")
        
        self.frm_merge_params = ctk.CTkFrame(card_merge, fg_color="transparent")
        self.frm_merge_params.pack(padx=14, pady=4, fill="x")
        self.frm_merge_params.columnconfigure(0, weight=1)
        self.frm_merge_params.columnconfigure(1, weight=0)
        
        self.lbl_merge_name = ctk.CTkLabel(self.frm_merge_params, text="合并后文件名:", font=("Microsoft YaHei UI", 12), text_color="#1E293B")
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
            variable=self.var_safe_merge, font=("Microsoft YaHei UI", 12),
            fg_color="#4F46E5", hover_color="#4338CA", text_color="#334155"
        )
        self.chk_safe_merge.pack(padx=14, pady=(8, 12), anchor="w")
        
        self.btn_start_merge = ctk.CTkButton(
            tab, text="⚡  开始合并", command=self.start_merging, height=44,
            font=("Microsoft YaHei UI", 14, "bold"), fg_color="#10B981", hover_color="#059669",
            text_color="#FFFFFF", corner_radius=8
        )
        self.btn_start_merge.pack(padx=12, pady=(18, 8), fill="x")
        
        self.merge_progress_bar = ctk.CTkProgressBar(tab, height=8, corner_radius=4, fg_color="#E2E8F0", progress_color="#10B981")
        self.merge_progress_bar.pack(padx=12, pady=4, fill="x")
        self.merge_progress_bar.set(0)
        
        self.lbl_merge_status = ctk.CTkLabel(tab, text="就绪 · 等待任务开始", text_color="#64748B", font=("Microsoft YaHei UI", 12))
        self.lbl_merge_status.pack(pady=(4, 8))
        
        self.merge_input_dir = None

    def setup_video_segment_tab(self):
        tab = self.tab_video_segment
        
        card_file = ctk.CTkFrame(tab, fg_color="#FFFFFF", corner_radius=10, border_width=1, border_color="#E2E8F0")
        card_file.pack(fill="x", padx=12, pady=(12, 8))
        
        lbl_file_header = ctk.CTkLabel(card_file, text="源视频文件", font=("Microsoft YaHei UI", 11, "bold"), text_color="#94A3B8")
        lbl_file_header.pack(anchor="w", padx=14, pady=(10, 2))
        
        self.lbl_vseg_file = ctk.CTkLabel(card_file, text="未选择视频文件", font=("Microsoft YaHei UI", 12), text_color="#64748B")
        self.lbl_vseg_file.pack(padx=14, pady=(0, 6), anchor="w")
        
        self.btn_select_vseg_file = ctk.CTkButton(
            card_file, text="📁  选择视频文件", command=self.select_vseg_file, height=36,
            fg_color="#F8FAFC", hover_color="#EEF2FF", border_width=1, border_color="#CBD5E1",
            text_color="#0F172A", font=("Microsoft YaHei UI", 12, "bold"), corner_radius=8
        )
        self.btn_select_vseg_file.pack(padx=14, pady=(0, 12), fill="x")
        
        card_params = ctk.CTkFrame(tab, fg_color="#FFFFFF", corner_radius=10, border_width=1, border_color="#E2E8F0")
        card_params.pack(fill="x", padx=12, pady=8)
        
        lbl_params_header = ctk.CTkLabel(card_params, text="分割参数设置", font=("Microsoft YaHei UI", 11, "bold"), text_color="#94A3B8")
        lbl_params_header.pack(anchor="w", padx=14, pady=(10, 4))
        
        self.frm_vseg_params = ctk.CTkFrame(card_params, fg_color="transparent")
        self.frm_vseg_params.pack(padx=14, pady=(0, 12), fill="x")
        self.frm_vseg_params.columnconfigure(0, weight=1)
        self.frm_vseg_params.columnconfigure(1, weight=0)
        
        self.lbl_vseg_parts = ctk.CTkLabel(self.frm_vseg_params, text="分割数量 (每段):", font=("Microsoft YaHei UI", 12), text_color="#1E293B")
        self.lbl_vseg_parts.grid(row=0, column=0, pady=6, sticky="w")
        self.entry_vseg_parts = ctk.CTkEntry(
            self.frm_vseg_params, width=110, height=32, font=("Consolas", 13, "bold"),
            text_color="#4F46E5", fg_color="#F8FAFC", border_color="#CBD5E1", border_width=1, corner_radius=6, justify="center"
        )
        self.entry_vseg_parts.insert(0, "8")
        self.entry_vseg_parts.grid(row=0, column=1, pady=6, sticky="e")
        
        self.lbl_vseg_overlap = ctk.CTkLabel(self.frm_vseg_params, text="前置重叠时间 (秒):", font=("Microsoft YaHei UI", 12), text_color="#1E293B")
        self.lbl_vseg_overlap.grid(row=1, column=0, pady=6, sticky="w")
        self.entry_vseg_overlap = ctk.CTkEntry(
            self.frm_vseg_params, width=110, height=32, font=("Consolas", 13, "bold"),
            text_color="#4F46E5", fg_color="#F8FAFC", border_color="#CBD5E1", border_width=1, corner_radius=6, justify="center"
        )
        self.entry_vseg_overlap.insert(0, "3")
        self.entry_vseg_overlap.grid(row=1, column=1, pady=6, sticky="e")
        
        card_outdir = ctk.CTkFrame(tab, fg_color="#FFFFFF", corner_radius=10, border_width=1, border_color="#E2E8F0")
        card_outdir.pack(fill="x", padx=12, pady=8)
        
        lbl_out_header = ctk.CTkLabel(card_outdir, text="输出位置", font=("Microsoft YaHei UI", 11, "bold"), text_color="#94A3B8")
        lbl_out_header.pack(anchor="w", padx=14, pady=(10, 2))
        
        self.lbl_vseg_outdir = ctk.CTkLabel(card_outdir, text="输出文件夹: 默认与源文件同目录", font=("Microsoft YaHei UI", 12), text_color="#64748B")
        self.lbl_vseg_outdir.pack(padx=14, pady=(0, 6), anchor="w")
        
        self.btn_select_vseg_outdir = ctk.CTkButton(
            card_outdir, text="📂  选择输出文件夹", command=self.select_vseg_outdir, height=36,
            fg_color="#F8FAFC", hover_color="#EEF2FF", border_width=1, border_color="#CBD5E1",
            text_color="#334155", font=("Microsoft YaHei UI", 12, "bold"), corner_radius=8
        )
        self.btn_select_vseg_outdir.pack(padx=14, pady=(0, 12), fill="x")
        
        self.btn_start_vseg = ctk.CTkButton(
            tab, text="⚡  开始分割", command=self.start_vseg_processing, height=44,
            font=("Microsoft YaHei UI", 14, "bold"), fg_color="#10B981", hover_color="#059669",
            text_color="#FFFFFF", corner_radius=8
        )
        self.btn_start_vseg.pack(padx=12, pady=(14, 8), fill="x")
        
        self.vseg_progress_bar = ctk.CTkProgressBar(tab, height=8, corner_radius=4, fg_color="#E2E8F0", progress_color="#10B981")
        self.vseg_progress_bar.pack(padx=12, pady=4, fill="x")
        self.vseg_progress_bar.set(0)
        
        self.lbl_vseg_status = ctk.CTkLabel(tab, text="就绪 · 等待任务开始", text_color="#64748B", font=("Microsoft YaHei UI", 12))
        self.lbl_vseg_status.pack(pady=(4, 8))
        
        self.vseg_input_file = None
        self.vseg_output_dir = None

    def setup_video_merge_tab(self):
        tab = self.tab_video_merge
        
        card_indir = ctk.CTkFrame(tab, fg_color="#FFFFFF", corner_radius=10, border_width=1, border_color="#E2E8F0")
        card_indir.pack(fill="x", padx=12, pady=(12, 8))
        
        lbl_in_header = ctk.CTkLabel(card_indir, text="待合并视频源", font=("Microsoft YaHei UI", 11, "bold"), text_color="#94A3B8")
        lbl_in_header.pack(anchor="w", padx=14, pady=(10, 2))
        
        self.lbl_vmerge_indir = ctk.CTkLabel(card_indir, text="未选择需要合并的视频文件夹", font=("Microsoft YaHei UI", 12), text_color="#64748B")
        self.lbl_vmerge_indir.pack(padx=14, pady=(0, 6), anchor="w")
        
        self.btn_select_vmerge_indir = ctk.CTkButton(
            card_indir, text="📁  选择输入文件夹", command=self.select_vmerge_indir, height=36,
            fg_color="#F8FAFC", hover_color="#EEF2FF", border_width=1, border_color="#CBD5E1",
            text_color="#0F172A", font=("Microsoft YaHei UI", 12, "bold"), corner_radius=8
        )
        self.btn_select_vmerge_indir.pack(padx=14, pady=(0, 12), fill="x")
        
        card_merge = ctk.CTkFrame(tab, fg_color="#FFFFFF", corner_radius=10, border_width=1, border_color="#E2E8F0")
        card_merge.pack(fill="x", padx=12, pady=8)
        
        lbl_merge_header = ctk.CTkLabel(card_merge, text="合并配置", font=("Microsoft YaHei UI", 11, "bold"), text_color="#94A3B8")
        lbl_merge_header.pack(anchor="w", padx=14, pady=(10, 2))
        
        self.lbl_vmerge_outfile = ctk.CTkLabel(card_merge, text="输出位置: 默认保存在输入文件夹内", font=("Microsoft YaHei UI", 12), text_color="#64748B")
        self.lbl_vmerge_outfile.pack(padx=14, pady=(0, 8), anchor="w")
        
        self.frm_vmerge_params = ctk.CTkFrame(card_merge, fg_color="transparent")
        self.frm_vmerge_params.pack(padx=14, pady=(0, 12), fill="x")
        self.frm_vmerge_params.columnconfigure(0, weight=1)
        self.frm_vmerge_params.columnconfigure(1, weight=0)
        
        self.lbl_vmerge_name = ctk.CTkLabel(self.frm_vmerge_params, text="合并后文件名:", font=("Microsoft YaHei UI", 12), text_color="#1E293B")
        self.lbl_vmerge_name.grid(row=0, column=0, sticky="w")
        self.entry_vmerge_name = ctk.CTkEntry(
            self.frm_vmerge_params, width=170, height=32, font=("Consolas", 12, "bold"),
            text_color="#4F46E5", fg_color="#F8FAFC", border_color="#CBD5E1", border_width=1, corner_radius=6
        )
        self.entry_vmerge_name.insert(0, "merged_output.mp4")
        self.entry_vmerge_name.grid(row=0, column=1, sticky="e")
        
        self.btn_start_vmerge = ctk.CTkButton(
            tab, text="⚡  开始合并", command=self.start_vmerge, height=44,
            font=("Microsoft YaHei UI", 14, "bold"), fg_color="#10B981", hover_color="#059669",
            text_color="#FFFFFF", corner_radius=8
        )
        self.btn_start_vmerge.pack(padx=12, pady=(24, 8), fill="x")
        
        self.vmerge_progress_bar = ctk.CTkProgressBar(tab, height=8, corner_radius=4, fg_color="#E2E8F0", progress_color="#10B981")
        self.vmerge_progress_bar.pack(padx=12, pady=4, fill="x")
        self.vmerge_progress_bar.set(0)
        
        self.lbl_vmerge_status = ctk.CTkLabel(tab, text="就绪 · 等待任务开始", text_color="#64748B", font=("Microsoft YaHei UI", 12))
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
        
    def on_complete(self, success):
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
                messagebox.showerror("错误", "处理过程中发生错误，请查看提示。")
        self.after(0, _reset_ui)

    def update_merge_progress(self, value):
        self.after(0, lambda: self.merge_progress_bar.set(value))
        
    def update_merge_status(self, text):
        self.after(0, lambda: self.lbl_merge_status.configure(text=text))
        
    def on_merge_complete(self, success):
        def _reset_ui():
            self.btn_start_merge.configure(state="normal", text="⚡  开始合并")
            self.btn_select_merge_indir.configure(state="normal")
            self.entry_merge_name.configure(state="normal")
            
            if success:
                self.lbl_merge_status.configure(text_color="#10B981")
                messagebox.showinfo("成功", "合并已完成！")
            else:
                self.lbl_merge_status.configure(text_color="#EF4444")
                messagebox.showerror("错误", "合并过程中发生错误，请查看提示。")
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
        
    def on_vseg_complete(self, success):
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
                messagebox.showerror("错误", "处理过程中发生错误，请查看提示。")
        self.after(0, _reset_ui)

    def update_vmerge_progress(self, value):
        self.after(0, lambda: self.vmerge_progress_bar.set(value))
        
    def update_vmerge_status(self, text):
        self.after(0, lambda: self.lbl_vmerge_status.configure(text=text))
        
    def on_vmerge_complete(self, success):
        def _reset_ui():
            self.btn_start_vmerge.configure(state="normal", text="⚡  开始合并")
            self.btn_select_vmerge_indir.configure(state="normal")
            self.entry_vmerge_name.configure(state="normal")
            
            if success:
                self.lbl_vmerge_status.configure(text_color="#10B981")
                messagebox.showinfo("成功", "合并已完成！")
            else:
                self.lbl_vmerge_status.configure(text_color="#EF4444")
                messagebox.showerror("错误", "合并过程中发生错误，请查看提示。")
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
        
        lbl_file_header = ctk.CTkLabel(card_file, text="视频文件及信息", font=("Microsoft YaHei UI", 11, "bold"), text_color="#94A3B8")
        lbl_file_header.pack(anchor="w", padx=14, pady=(10, 2))
        
        self.lbl_video_file = ctk.CTkLabel(card_file, text="未选择视频文件", font=("Microsoft YaHei UI", 12), text_color="#64748B")
        self.lbl_video_file.pack(padx=14, pady=(0, 6), anchor="w")
        
        self.btn_select_video = ctk.CTkButton(
            card_file, text="📁  选择视频文件", command=self.select_video_file, height=36,
            fg_color="#F8FAFC", hover_color="#EEF2FF", border_width=1, border_color="#CBD5E1",
            text_color="#0F172A", font=("Microsoft YaHei UI", 12, "bold"), corner_radius=8
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
        
        lbl_clip_header = ctk.CTkLabel(card_clip, text="截取区间设定", font=("Microsoft YaHei UI", 11, "bold"), text_color="#94A3B8")
        lbl_clip_header.pack(anchor="w", padx=14, pady=(10, 4))
        
        self.frm_clip_params = ctk.CTkFrame(card_clip, fg_color="transparent")
        self.frm_clip_params.pack(padx=14, pady=(0, 12), fill="x")
        self.frm_clip_params.columnconfigure(0, weight=1)
        self.frm_clip_params.columnconfigure(1, weight=0)

        ctk.CTkLabel(self.frm_clip_params, text="开始时间:", font=("Microsoft YaHei UI", 12), text_color="#1E293B").grid(row=0, column=0, pady=6, sticky="w")
        self.entry_clip_start = ctk.CTkEntry(
            self.frm_clip_params, width=170, height=32, font=("Consolas", 12, "bold"),
            text_color="#4F46E5", fg_color="#F8FAFC", border_color="#CBD5E1", border_width=1, corner_radius=6,
            placeholder_text="例: 37.30 或 00:00:37.30"
        )
        self.entry_clip_start.grid(row=0, column=1, pady=6, sticky="e")

        ctk.CTkLabel(self.frm_clip_params, text="结束时间:", font=("Microsoft YaHei UI", 12), text_color="#1E293B").grid(row=1, column=0, pady=6, sticky="w")
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
            font=("Microsoft YaHei UI", 14, "bold"), fg_color="#10B981", hover_color="#059669",
            text_color="#FFFFFF", corner_radius=8
        )
        self.btn_start_clip.pack(side="left", fill="x", expand=True, padx=(0, 6))
        
        self.btn_open_clip_dir = ctk.CTkButton(
            self.frm_clip_buttons, text="📂  打开输出目录", command=self.open_clip_output_dir, height=44,
            font=("Microsoft YaHei UI", 12, "bold"), fg_color="#FFFFFF", border_width=1, border_color="#CBD5E1",
            text_color="#334155", hover_color="#F1F5F9", corner_radius=8
        )
        self.btn_open_clip_dir.pack(side="left", fill="x", expand=True, padx=(6, 0))

        self.clip_progress_bar = ctk.CTkProgressBar(tab, height=8, corner_radius=4, fg_color="#E2E8F0", progress_color="#10B981")
        self.clip_progress_bar.pack(padx=12, pady=4, fill="x")
        self.clip_progress_bar.set(0)
        
        self.lbl_clip_status = ctk.CTkLabel(tab, text="就绪 · 等待任务开始", text_color="#64748B", font=("Microsoft YaHei UI", 12))
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
        target = self.video_output_dir or "."
        if os.path.isdir(target):
            os.startfile(target)
        else:
            messagebox.showinfo("提示", "输出目录不存在，请先选择视频文件。")

    def update_clip_progress(self, value):
        self.after(0, lambda: self.clip_progress_bar.set(value))

    def update_clip_status(self, text):
        self.after(0, lambda: self.lbl_clip_status.configure(text=text))

    def on_clip_complete(self, success):
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
                messagebox.showerror("错误", "截取过程中发生错误，请查看提示。")
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
        
        lbl_file_header = ctk.CTkLabel(card_file, text="音频文件及信息", font=("Microsoft YaHei UI", 11, "bold"), text_color="#94A3B8")
        lbl_file_header.pack(anchor="w", padx=14, pady=(10, 2))
        
        self.lbl_audio_clip_file = ctk.CTkLabel(card_file, text="未选择音频文件", font=("Microsoft YaHei UI", 12), text_color="#64748B")
        self.lbl_audio_clip_file.pack(padx=14, pady=(0, 6), anchor="w")
        
        self.btn_select_audio_clip = ctk.CTkButton(
            card_file, text="📁  选择音频文件", command=self.select_audio_clip_file, height=36,
            fg_color="#F8FAFC", hover_color="#EEF2FF", border_width=1, border_color="#CBD5E1",
            text_color="#0F172A", font=("Microsoft YaHei UI", 12, "bold"), corner_radius=8
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
        
        lbl_clip_header = ctk.CTkLabel(card_clip, text="截取区间设定", font=("Microsoft YaHei UI", 11, "bold"), text_color="#94A3B8")
        lbl_clip_header.pack(anchor="w", padx=14, pady=(10, 4))
        
        self.frm_aclip_params = ctk.CTkFrame(card_clip, fg_color="transparent")
        self.frm_aclip_params.pack(padx=14, pady=(0, 12), fill="x")
        self.frm_aclip_params.columnconfigure(0, weight=1)
        self.frm_aclip_params.columnconfigure(1, weight=0)

        ctk.CTkLabel(self.frm_aclip_params, text="开始时间:", font=("Microsoft YaHei UI", 12), text_color="#1E293B").grid(row=0, column=0, pady=6, sticky="w")
        self.entry_aclip_start = ctk.CTkEntry(
            self.frm_aclip_params, width=170, height=32, font=("Consolas", 12, "bold"),
            text_color="#4F46E5", fg_color="#F8FAFC", border_color="#CBD5E1", border_width=1, corner_radius=6,
            placeholder_text="例: 37.30 或 00:00:37.30"
        )
        self.entry_aclip_start.grid(row=0, column=1, pady=6, sticky="e")

        ctk.CTkLabel(self.frm_aclip_params, text="结束时间:", font=("Microsoft YaHei UI", 12), text_color="#1E293B").grid(row=1, column=0, pady=6, sticky="w")
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
            font=("Microsoft YaHei UI", 14, "bold"), fg_color="#10B981", hover_color="#059669",
            text_color="#FFFFFF", corner_radius=8
        )
        self.btn_start_aclip.pack(side="left", fill="x", expand=True, padx=(0, 6))
        
        self.btn_open_aclip_dir = ctk.CTkButton(
            self.frm_aclip_buttons, text="📂  打开输出目录", command=self.open_audio_clip_output_dir, height=44,
            font=("Microsoft YaHei UI", 12, "bold"), fg_color="#FFFFFF", border_width=1, border_color="#CBD5E1",
            text_color="#334155", hover_color="#F1F5F9", corner_radius=8
        )
        self.btn_open_aclip_dir.pack(side="left", fill="x", expand=True, padx=(6, 0))

        self.aclip_progress_bar = ctk.CTkProgressBar(tab, height=8, corner_radius=4, fg_color="#E2E8F0", progress_color="#10B981")
        self.aclip_progress_bar.pack(padx=12, pady=4, fill="x")
        self.aclip_progress_bar.set(0)
        
        self.lbl_aclip_status = ctk.CTkLabel(tab, text="就绪 · 等待任务开始", text_color="#64748B", font=("Microsoft YaHei UI", 12))
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
        target = self.audio_clip_output_dir or "."
        if os.path.isdir(target):
            os.startfile(target)
        else:
            messagebox.showinfo("提示", "输出目录不存在，请先选择音频文件。")

    def update_aclip_progress(self, value):
        self.after(0, lambda: self.aclip_progress_bar.set(value))

    def update_aclip_status(self, text):
        self.after(0, lambda: self.lbl_aclip_status.configure(text=text))

    def on_aclip_complete(self, success):
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
                messagebox.showerror("错误", "截取过程中发生错误，请查看提示。")
        self.after(0, _reset)

if __name__ == "__main__":
    app = MediaSegmenterApp()
    app.mainloop()
