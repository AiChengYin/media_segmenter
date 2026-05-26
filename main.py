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
            
            part_name = f"{base_name}_part{i:02d}.wav"
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

def merge_audio(input_dir, output_file, progress_callback, status_callback, complete_callback):
    try:
        valid_extensions = ('.mp3', '.wav', '.m4a', '.aac', '.flac', '.wma', '.mp4', '.mkv', '.avi', '.mov', '.flv', '.wmv')
        audio_files = [f for f in os.listdir(input_dir) if f.lower().endswith(valid_extensions)]
        
        # Filter out the output file itself if it exists in the directory
        output_filename = os.path.basename(output_file)
        audio_files = [f for f in audio_files if f != output_filename]
        
        audio_files.sort()
        
        if not audio_files:
            raise Exception("该文件夹下没有找到支持的音视频文件！")

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


class MediaSegmenterApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("音视频处理工具 (分割 / 合并)")
        self.geometry("450x550")
        self.resizable(False, False)
        
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(padx=20, pady=(10, 20), fill="both", expand=True)
        
        self.tab_segment = self.tabview.add("分割")
        self.tab_merge = self.tabview.add("合并")
        
        self.setup_segment_tab()
        self.setup_merge_tab()

    def setup_segment_tab(self):
        # Audio File Selection
        self.lbl_file = ctk.CTkLabel(self.tab_segment, text="未选择媒体文件", font=("Microsoft YaHei UI", 13), text_color="gray")
        self.lbl_file.pack(pady=(15, 5), padx=10, anchor="w")
        
        self.btn_select_file = ctk.CTkButton(self.tab_segment, text="选择媒体文件", command=self.select_file, height=36)
        self.btn_select_file.pack(pady=(0, 10), padx=10, fill="x")
        
        # Parameters Frame
        self.frm_params = ctk.CTkFrame(self.tab_segment, fg_color="transparent")
        self.frm_params.pack(pady=5, padx=10, fill="x")
        self.frm_params.columnconfigure(0, weight=1)
        self.frm_params.columnconfigure(1, weight=1)
        
        self.lbl_parts = ctk.CTkLabel(self.frm_params, text="分割数量 (每段):", font=("Microsoft YaHei UI", 13))
        self.lbl_parts.grid(row=0, column=0, padx=(0, 10), pady=10, sticky="e")
        self.entry_parts = ctk.CTkEntry(self.frm_params, width=120, height=32)
        self.entry_parts.insert(0, "8")
        self.entry_parts.grid(row=0, column=1, pady=10, sticky="w")
        
        self.lbl_overlap = ctk.CTkLabel(self.frm_params, text="前置重叠时间(秒):", font=("Microsoft YaHei UI", 13))
        self.lbl_overlap.grid(row=1, column=0, padx=(0, 10), pady=10, sticky="e")
        self.entry_overlap = ctk.CTkEntry(self.frm_params, width=120, height=32)
        self.entry_overlap.insert(0, "3")
        self.entry_overlap.grid(row=1, column=1, pady=10, sticky="w")
        
        # Output Dir Selection
        self.lbl_outdir = ctk.CTkLabel(self.tab_segment, text="输出文件夹: 默认与源文件同目录", font=("Microsoft YaHei UI", 13), text_color="gray")
        self.lbl_outdir.pack(pady=(10, 5), padx=10, anchor="w")
        
        self.btn_select_outdir = ctk.CTkButton(self.tab_segment, text="选择输出文件夹", command=self.select_outdir, height=36, fg_color="#6c757d", hover_color="#5a6268")
        self.btn_select_outdir.pack(pady=(0, 10), padx=10, fill="x")
        
        # Action
        self.btn_start_segment = ctk.CTkButton(self.tab_segment, text="开始分割", command=self.start_processing, height=45, font=("Microsoft YaHei UI", 15, "bold"), fg_color="#28a745", hover_color="#218838")
        self.btn_start_segment.pack(pady=(10, 10), padx=10, fill="x")
        
        # Progress
        self.progress_bar = ctk.CTkProgressBar(self.tab_segment, height=10)
        self.progress_bar.pack(pady=(5, 5), padx=10, fill="x")
        self.progress_bar.set(0)
        
        self.lbl_status = ctk.CTkLabel(self.tab_segment, text="等待开始...", text_color="gray", font=("Microsoft YaHei UI", 12))
        self.lbl_status.pack(pady=5)
        
        self.input_file = None
        self.output_dir = None

    def setup_merge_tab(self):
        # Input Dir Selection
        self.lbl_merge_indir = ctk.CTkLabel(self.tab_merge, text="未选择需要合并的媒体文件夹", font=("Microsoft YaHei UI", 13), text_color="gray")
        self.lbl_merge_indir.pack(pady=(20, 5), padx=10, anchor="w")
        
        self.btn_select_merge_indir = ctk.CTkButton(self.tab_merge, text="选择输入文件夹", command=self.select_merge_indir, height=36)
        self.btn_select_merge_indir.pack(pady=(0, 15), padx=10, fill="x")
        
        # Output File Selection (or Dir)
        self.lbl_merge_outfile = ctk.CTkLabel(self.tab_merge, text="输出文件: 默认保存在输入文件夹内", font=("Microsoft YaHei UI", 13), text_color="gray")
        self.lbl_merge_outfile.pack(pady=(15, 5), padx=10, anchor="w")
        
        # Options
        self.frm_merge_params = ctk.CTkFrame(self.tab_merge, fg_color="transparent")
        self.frm_merge_params.pack(pady=10, padx=10, fill="x")
        
        self.lbl_merge_name = ctk.CTkLabel(self.frm_merge_params, text="合并后文件名:", font=("Microsoft YaHei UI", 13))
        self.lbl_merge_name.pack(side="left", padx=(0, 10))
        self.entry_merge_name = ctk.CTkEntry(self.frm_merge_params, width=150, height=32)
        self.entry_merge_name.insert(0, "merged_output.wav")
        self.entry_merge_name.pack(side="left")
        
        # Action
        self.btn_start_merge = ctk.CTkButton(self.tab_merge, text="开始合并", command=self.start_merging, height=45, font=("Microsoft YaHei UI", 15, "bold"), fg_color="#28a745", hover_color="#218838")
        self.btn_start_merge.pack(pady=(30, 10), padx=10, fill="x")
        
        # Progress
        self.merge_progress_bar = ctk.CTkProgressBar(self.tab_merge, height=10)
        self.merge_progress_bar.pack(pady=(5, 5), padx=10, fill="x")
        self.merge_progress_bar.set(0)
        
        self.lbl_merge_status = ctk.CTkLabel(self.tab_merge, text="等待开始...", text_color="gray", font=("Microsoft YaHei UI", 12))
        self.lbl_merge_status.pack(pady=5)
        
        self.merge_input_dir = None

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
            self.lbl_file.configure(text=f"已选择: {short_name}", text_color=("black", "white"))
            
            if not self.output_dir:
                self.output_dir = os.path.dirname(file_path)
                out_short = self.output_dir
                if len(out_short) > 35:
                    out_short = out_short[:15] + "..." + out_short[-15:]
                self.lbl_outdir.configure(text=f"输出文件夹: {out_short}", text_color=("black", "white"))

    def select_outdir(self):
        dir_path = filedialog.askdirectory(title="选择输出文件夹")
        if dir_path:
            self.output_dir = dir_path
            out_short = self.output_dir
            if len(out_short) > 35:
                out_short = out_short[:15] + "..." + out_short[-15:]
            self.lbl_outdir.configure(text=f"输出文件夹: {out_short}", text_color=("black", "white"))

    def select_merge_indir(self):
        dir_path = filedialog.askdirectory(title="选择输入文件夹 (包含要合并的音视频)")
        if dir_path:
            self.merge_input_dir = dir_path
            in_short = self.merge_input_dir
            if len(in_short) > 35:
                in_short = in_short[:15] + "..." + in_short[-15:]
            self.lbl_merge_indir.configure(text=f"输入文件夹: {in_short}", text_color=("black", "white"))

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
            
        self.btn_start_segment.configure(state="disabled", text="处理中...")
        self.btn_select_file.configure(state="disabled")
        self.btn_select_outdir.configure(state="disabled")
        self.entry_parts.configure(state="disabled")
        self.entry_overlap.configure(state="disabled")
        
        self.progress_bar.set(0)
        self.lbl_status.configure(text="正在获取媒体信息...", text_color="#17a2b8")
        
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
            output_name = "merged_output.wav"
            self.entry_merge_name.delete(0, 'end')
            self.entry_merge_name.insert(0, output_name)
            
        output_file = os.path.join(self.merge_input_dir, output_name)
        
        self.btn_start_merge.configure(state="disabled", text="处理中...")
        self.btn_select_merge_indir.configure(state="disabled")
        self.entry_merge_name.configure(state="disabled")
        
        self.merge_progress_bar.set(0)
        self.lbl_merge_status.configure(text="正在获取媒体列表...", text_color="#17a2b8")
        
        threading.Thread(target=merge_audio, args=(
            self.merge_input_dir, output_file,
            self.update_merge_progress, self.update_merge_status, self.on_merge_complete
        ), daemon=True).start()

    def update_progress(self, value):
        self.after(0, lambda: self.progress_bar.set(value))
        
    def update_status(self, text):
        self.after(0, lambda: self.lbl_status.configure(text=text))
        
    def on_complete(self, success):
        def _reset_ui():
            self.btn_start_segment.configure(state="normal", text="开始分割")
            self.btn_select_file.configure(state="normal")
            self.btn_select_outdir.configure(state="normal")
            self.entry_parts.configure(state="normal")
            self.entry_overlap.configure(state="normal")
            
            if success:
                self.lbl_status.configure(text_color="#28a745")
                messagebox.showinfo("成功", "分割已完成！")
            else:
                self.lbl_status.configure(text_color="#dc3545")
                messagebox.showerror("错误", "处理过程中发生错误，请查看提示。")
        self.after(0, _reset_ui)

    def update_merge_progress(self, value):
        self.after(0, lambda: self.merge_progress_bar.set(value))
        
    def update_merge_status(self, text):
        self.after(0, lambda: self.lbl_merge_status.configure(text=text))
        
    def on_merge_complete(self, success):
        def _reset_ui():
            self.btn_start_merge.configure(state="normal", text="开始合并")
            self.btn_select_merge_indir.configure(state="normal")
            self.entry_merge_name.configure(state="normal")
            
            if success:
                self.lbl_merge_status.configure(text_color="#28a745")
                messagebox.showinfo("成功", "合并已完成！")
            else:
                self.lbl_merge_status.configure(text_color="#dc3545")
                messagebox.showerror("错误", "合并过程中发生错误，请查看提示。")
        self.after(0, _reset_ui)

if __name__ == "__main__":
    app = MediaSegmenterApp()
    app.mainloop()
