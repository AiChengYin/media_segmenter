import os
import sys
import shutil
import tempfile
import unittest
import subprocess

import main

class TestMediaSegmenterRobustness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work_dir = tempfile.mkdtemp(prefix="mediaseg_test_")
        cls.audio_wav = os.path.join(cls.work_dir, "test_audio.wav")
        cls.audio_mp3 = os.path.join(cls.work_dir, "test_audio.mp3")
        cls.video_mp4 = os.path.join(cls.work_dir, "test_video.mp4")

        # 1. 生成 6 秒测试音频 (.wav 与 .mp3)
        res1 = main.run_media_cmd(['ffmpeg', '-y', '-f', 'lavfi', '-i', 'sine=frequency=1000:duration=6', cls.audio_wav])
        assert res1.returncode == 0, f"Failed to generate test wav: {res1.stderr}"

        res2 = main.run_media_cmd(['ffmpeg', '-y', '-f', 'lavfi', '-i', 'sine=frequency=800:duration=6', cls.audio_mp3])
        assert res2.returncode == 0, f"Failed to generate test mp3: {res2.stderr}"

        # 2. 生成 5 秒测试视频 320x240 (.mp4，关键帧间隔 25 帧即 1 秒)
        res3 = main.run_media_cmd([
            'ffmpeg', '-y',
            '-f', 'lavfi', '-i', 'testsrc=duration=5:size=320x240:rate=25',
            '-f', 'lavfi', '-i', 'sine=frequency=1000:duration=5',
            '-c:v', 'libx264', '-g', '25', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
            cls.video_mp4
        ])
        assert res3.returncode == 0, f"Failed to generate test mp4: {res3.stderr}"

    @classmethod
    def tearDownClass(cls):
        if os.path.isdir(cls.work_dir):
            shutil.rmtree(cls.work_dir, ignore_errors=True)

    def test_ac1_binary_resolution(self):
        """AC-1: 二进制解析与绝对路径调用自检"""
        ffmpeg_p = main.get_binary_path('ffmpeg')
        ffprobe_p = main.get_binary_path('ffprobe')
        self.assertTrue(os.path.isfile(ffmpeg_p) or shutil.which('ffmpeg'), f"ffmpeg binary not resolved: {ffmpeg_p}")
        self.assertTrue(os.path.isfile(ffprobe_p) or shutil.which('ffprobe'), f"ffprobe binary not resolved: {ffprobe_p}")

        res = main.run_media_cmd(['ffmpeg', '-version'])
        self.assertEqual(res.returncode, 0)
        self.assertIn("ffmpeg version", res.stdout.lower() + res.stderr.lower())

        res_probe = main.run_media_cmd(['ffprobe', '-version'])
        self.assertEqual(res_probe.returncode, 0)
        self.assertIn("ffprobe version", res_probe.stdout.lower() + res_probe.stderr.lower())

    def test_ac2_audio_segmentation_and_merging(self):
        """AC-2: 音频分割（保留原扩展名无损优先）、特殊字符路径音频合并与截取"""
        out_dir = os.path.join(self.work_dir, "audio_seg_out")
        os.makedirs(out_dir, exist_ok=True)

        # 1. 音频分割 (.wav 3 段，重叠 1s)
        results = []
        def on_complete(success, err=""):
            results.append((success, err))

        main.process_audio(
            self.audio_wav, out_dir, num_parts=3, overlap=1.0,
            progress_callback=lambda v: None,
            status_callback=lambda s: None,
            complete_callback=on_complete
        )
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0][0], f"process_audio failed: {results[0][1]}")

        # 验证生成的文件
        parts = [os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.endswith('.wav')]
        self.assertEqual(len(parts), 3)
        for p in parts:
            self.assertGreater(os.path.getsize(p), 0)
            dur = main.get_audio_duration(p)
            # base = 6/3 = 2s. Part 1: [0, 2] (2s). Part 2: [1, 4] (3s). Part 3: [3, 6] (3s)
            self.assertGreater(dur, 1.5)

        # 2. 音频合并：包含单引号、空格与中文的特殊文件名
        special_dir = os.path.join(self.work_dir, "audio_special_merge")
        os.makedirs(special_dir, exist_ok=True)
        f1 = os.path.join(special_dir, "part '1' 测试 片段.wav")
        f2 = os.path.join(special_dir, "part '2' 测试 片段.wav")
        shutil.copyfile(parts[0], f1)
        shutil.copyfile(parts[1], f2)

        merged_out = os.path.join(special_dir, "merged_output.wav")
        merge_results = []
        main.merge_audio(
            special_dir, merged_out,
            progress_callback=lambda v: None,
            status_callback=lambda s: None,
            complete_callback=lambda s, err="": merge_results.append((s, err)),
            safe_mode=False
        )
        self.assertTrue(merge_results[0][0], f"Normal merge failed: {merge_results[0][1]}")
        self.assertTrue(os.path.exists(merged_out))
        self.assertGreater(os.path.getsize(merged_out), 0)
        # 验证源目录下无 concat_list.txt 残留
        self.assertFalse(os.path.exists(os.path.join(special_dir, "concat_list.txt")))

        # 3. 安全合并模式 (safe_mode=True)
        safe_merged_out = os.path.join(special_dir, "safe_merged.mp3")
        safe_merge_results = []
        main.merge_audio(
            special_dir, safe_merged_out,
            progress_callback=lambda v: None,
            status_callback=lambda s: None,
            complete_callback=lambda s, err="": safe_merge_results.append((s, err)),
            safe_mode=True
        )
        self.assertTrue(safe_merge_results[0][0], f"Safe merge failed: {safe_merge_results[0][1]}")
        self.assertTrue(os.path.exists(safe_merged_out))
        self.assertGreater(os.path.getsize(safe_merged_out), 0)
        self.assertFalse(os.path.exists(os.path.join(special_dir, "concat_list.txt")))

        # 4. 音频截取
        clip_out = os.path.join(self.work_dir, "clip_audio_out.wav")
        clip_results = []
        main.clip_audio(
            self.audio_wav, clip_out, 1.0, 3.5,
            progress_callback=lambda v: None,
            status_callback=lambda s: None,
            complete_callback=lambda s, err="": clip_results.append((s, err))
        )
        self.assertTrue(clip_results[0][0], f"Audio clip failed: {clip_results[0][1]}")
        self.assertTrue(os.path.exists(clip_out))
        dur_clip = main.get_audio_duration(clip_out)
        self.assertAlmostEqual(dur_clip, 2.5, delta=0.25)

    def test_ac3_video_full_flow(self):
        """AC-3: 视频信息探针、视频分割、合并与截取"""
        # 1. 视频信息读取
        dur, w, h, sz = main.get_video_info(self.video_mp4)
        self.assertAlmostEqual(dur, 5.0, delta=0.2)
        self.assertEqual(w, 320)
        self.assertEqual(h, 240)
        self.assertGreater(sz, 0)

        # 2. 视频分割 (2 段，重叠 1s)
        vseg_out_dir = os.path.join(self.work_dir, "vseg_out")
        os.makedirs(vseg_out_dir, exist_ok=True)
        vseg_results = []
        main.process_video(
            self.video_mp4, vseg_out_dir, num_parts=2, overlap=1.0,
            progress_callback=lambda v: None,
            status_callback=lambda s: None,
            complete_callback=lambda s, err="": vseg_results.append((s, err))
        )
        self.assertTrue(vseg_results[0][0], f"Video split failed: {vseg_results[0][1]}")
        parts = [os.path.join(vseg_out_dir, f) for f in os.listdir(vseg_out_dir) if f.endswith('.mp4')]
        self.assertEqual(len(parts), 2)
        for p in parts:
            self.assertGreater(os.path.getsize(p), 0)

        # 3. 视频合并 (含特殊字符目录与文件)
        vmerge_dir = os.path.join(self.work_dir, "vmerge 'test' 目录")
        os.makedirs(vmerge_dir, exist_ok=True)
        vf1 = os.path.join(vmerge_dir, "part 'A' 视频.mp4")
        vf2 = os.path.join(vmerge_dir, "part 'B' 视频.mp4")
        shutil.copyfile(parts[0], vf1)
        shutil.copyfile(parts[1], vf2)

        vmerged_out = os.path.join(vmerge_dir, "video_merged.mp4")
        vmerge_results = []
        main.merge_video(
            vmerge_dir, vmerged_out,
            progress_callback=lambda v: None,
            status_callback=lambda s: None,
            complete_callback=lambda s, err="": vmerge_results.append((s, err))
        )
        self.assertTrue(vmerge_results[0][0], f"Video merge failed: {vmerge_results[0][1]}")
        self.assertTrue(os.path.exists(vmerged_out))
        self.assertGreater(os.path.getsize(vmerged_out), 0)
        self.assertFalse(os.path.exists(os.path.join(vmerge_dir, "concat_list.txt")))

        # 4. 视频截取
        vclip_out = os.path.join(self.work_dir, "vclip_out.mp4")
        vclip_results = []
        main.clip_video(
            self.video_mp4, vclip_out, 1.0, 3.5,
            progress_callback=lambda v: None,
            status_callback=lambda s: None,
            complete_callback=lambda s, err="": vclip_results.append((s, err))
        )
        self.assertTrue(vclip_results[0][0], f"Video clip failed: {vclip_results[0][1]}")
        self.assertTrue(os.path.exists(vclip_out))
        vclip_dur, _, _, _ = main.get_video_info(vclip_out)
        self.assertAlmostEqual(vclip_dur, 2.5, delta=0.25)

    def test_ac4_error_and_edge_cases(self):
        """AC-4: 异常与逆向边界分支验证"""
        # 1. 损坏或不存在的文件
        bad_file = os.path.join(self.work_dir, "non_existent.mp3")
        res_list = []
        main.process_audio(
            bad_file, self.work_dir, num_parts=2, overlap=0,
            progress_callback=lambda v: None,
            status_callback=lambda s: None,
            complete_callback=lambda s, err="": res_list.append((s, err))
        )
        self.assertFalse(res_list[0][0])
        self.assertIn("无法获取媒体时长", res_list[0][1])

        # 2. 空目录合并
        empty_dir = os.path.join(self.work_dir, "empty_dir")
        os.makedirs(empty_dir, exist_ok=True)
        res_merge = []
        main.merge_audio(
            empty_dir, os.path.join(empty_dir, "out.mp3"),
            progress_callback=lambda v: None,
            status_callback=lambda s: None,
            complete_callback=lambda s, err="": res_merge.append((s, err))
        )
        self.assertFalse(res_merge[0][0])
        self.assertIn("没有找到支持的音视频文件", res_merge[0][1])

        # 3. 时间解析测试
        self.assertAlmostEqual(main.parse_time_input("37.30"), 37.30)
        self.assertAlmostEqual(main.parse_time_input("01:05.5"), 65.5)
        self.assertAlmostEqual(main.parse_time_input("01:02:03.50"), 3723.5)
        with self.assertRaises(Exception):
            main.parse_time_input("invalid_time")
        with self.assertRaises(Exception):
            main.parse_time_input("1:2:3:4")

    def test_ac5_isolated_packaged_exe(self):
        """AC-5: 单文件打包产物在清空外部 FFmpeg PATH 的隔离环境下端到端验证"""
        import time
        exe_path = os.path.abspath(os.path.join("dist", "MediaSegmenter.exe"))
        self.assertTrue(os.path.isfile(exe_path), f"打包产物不存在: {exe_path}")
        self.assertGreater(os.path.getsize(exe_path), 50 * 1024 * 1024, "EXE 体积过小，未包含 FFmpeg 二进制")

        # 仅保留基础 Windows System32 路径，彻底移除外部 Python 与 FFmpeg
        clean_env = {
            'PATH': r'C:\Windows\System32;C:\Windows',
            'SYSTEMROOT': r'C:\Windows',
            'TEMP': os.environ.get('TEMP', r'C:\Temp'),
            'TMP': os.environ.get('TMP', r'C:\Temp')
        }

        # 启动单文件 EXE
        proc = subprocess.Popen([exe_path], env=clean_env)
        try:
            # 等待 4 秒，确保解压完成且主窗口启动就绪
            time.sleep(4)
            poll_code = proc.poll()
            self.assertIsNone(poll_code, f"MediaSegmenter.exe 在隔离环境下启动失败，退出码: {poll_code}")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()

if __name__ == '__main__':
    unittest.main()
