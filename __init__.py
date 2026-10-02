"""Disk-backed long-video output for MieLoop / MiniMax H3 ComfyUI workflows."""

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import folder_paths


_RUN_ID = re.compile(r"^[0-9a-f]{24}$")


def _ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as exc:
        raise RuntimeError("找不到 FFmpeg：请安装 FFmpeg 并加入 PATH，或安装 imageio-ffmpeg。") from exc


def _run_dir(ctx):
    if not isinstance(ctx, dict) or int(ctx.get("version", 0)) != 3:
        raise ValueError("需要 MieLoop v3 的 loop_ctx。")
    run_id = str(ctx.get("run_id", ""))
    if not _RUN_ID.fullmatch(run_id):
        raise ValueError("无效的 MieLoop run_id。")
    return Path(folder_paths.get_output_directory()) / "h3_long_video" / run_id


def _check_space(directory, minimum_gib=2):
    free = shutil.disk_usage(directory).free
    if free < minimum_gib * 1024**3:
        raise RuntimeError(f"可用磁盘空间不足 {minimum_gib} GiB：{directory}。已完成的分段会保留。")


def _audio_to_f32le(audio, path):
    waveform = audio["waveform"]
    rate = int(audio["sample_rate"])
    if rate <= 0 or waveform.ndim != 3 or waveform.shape[0] != 1:
        raise ValueError("音频必须是单批次 [1, 声道, 采样点]，且采样率大于 0。")
    channels = min(int(waveform.shape[1]), 2)
    if channels < 1 or waveform.shape[2] < 1:
        raise ValueError("音频为空。")
    with path.open("wb") as dst:
        for start in range(0, int(waveform.shape[2]), 65536):
            piece = waveform[0, :channels, start:start + 65536].detach().to("cpu").float().numpy()
            np.clip(piece, -1.0, 1.0, out=piece)
            dst.write(np.ascontiguousarray(piece.T, dtype="<f4").tobytes())
    return rate, channels


def _frame_bytes(frame):
    arr = frame.detach().to("cpu").float().numpy()
    return np.ascontiguousarray(np.clip(arr * 255.0 + 0.5, 0, 255).astype(np.uint8)).tobytes()


class H3DiskEncodeSegment:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "loop_ctx": ("MIE_LOOP_CTX",),
            "images": ("IMAGE",),
            "audio": ("AUDIO",),
            "fps": ("INT", {"default": 24, "min": 1, "max": 120}),
            "crf": ("INT", {"default": 19, "min": 0, "max": 51}),
            "preset": (["medium", "fast", "veryfast", "slow"],),
        }}

    RETURN_TYPES = ("MIE_LOOP_CTX", "STRING")
    RETURN_NAMES = ("loop_ctx", "segment_path")
    FUNCTION = "encode"
    CATEGORY = "Video Segment Writer/Output"

    def encode(self, loop_ctx, images, audio, fps=24, crf=19, preset="medium"):
        directory = _run_dir(loop_ctx)
        directory.mkdir(parents=True, exist_ok=True)
        _check_space(directory)
        index = int(loop_ctx["index"])
        count = int(loop_ctx["count"])
        if not 0 <= index < count:
            raise ValueError("MieLoop index 超出范围。")
        if images.ndim != 4 or images.shape[-1] != 3 or images.shape[0] < 1:
            raise ValueError("图像必须为非空 RGB IMAGE 批次 [帧, 高, 宽, 3]。")
        frames, height, width, _ = map(int, images.shape)
        if width % 2 or height % 2:
            raise ValueError("H.264 yuv420p 要求偶数宽高。")
        if preset not in {"medium", "fast", "veryfast", "slow"}:
            raise ValueError("无效的 H.264 preset。")
        manifest_path = directory / "manifest.json"
        if index == 0:
            if manifest_path.exists():
                raise RuntimeError("该 run_id 已有分段清单，拒绝覆盖。")
            manifest = {"run_id": loop_ctx["run_id"], "count": count, "fps": int(fps),
                        "width": width, "height": height, "segments": []}
        else:
            if not manifest_path.exists():
                raise RuntimeError("找不到前一段的清单。")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest["run_id"] != loop_ctx["run_id"] or manifest["count"] != count:
                raise RuntimeError("分段清单与当前循环不匹配。")
            if len(manifest["segments"]) != index:
                raise RuntimeError(f"期望第 {index} 段，清单只有 {len(manifest['segments'])} 段。")
            if (manifest["width"], manifest["height"], manifest["fps"]) != (width, height, int(fps)):
                raise RuntimeError("段间分辨率或帧率不一致，无法无损拼接。")

        name = f"segment_{index:05d}.mp4"
        final_path = directory / name
        partial_path = directory / f"{name}.part"
        audio_path = directory / f"audio_{index:05d}.f32le"
        log_path = directory / f"ffmpeg_{index:05d}.log"
        if final_path.exists():
            raise RuntimeError(f"分段文件已存在，拒绝覆盖：{final_path}")
        rate, channels = _audio_to_f32le(audio, audio_path)
        cmd = [_ffmpeg(), "-hide_banner", "-loglevel", "warning", "-y",
               "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", f"{width}x{height}",
               "-framerate", str(fps), "-i", "pipe:0",
               "-f", "f32le", "-ar", str(rate), "-ac", str(channels), "-i", str(audio_path),
               "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", preset,
               "-crf", str(crf), "-pix_fmt", "yuv420p", "-frames:v", str(frames),
               "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
               "-af", "apad", "-t", f"{frames / fps:.9f}", "-movflags", "+faststart",
               "-f", "mp4", str(partial_path)]
        try:
            with log_path.open("wb") as log:
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log)
                try:
                    for i in range(frames):
                        proc.stdin.write(_frame_bytes(images[i]))
                    proc.stdin.close()
                    code = proc.wait()
                except BaseException:
                    proc.kill()
                    proc.wait()
                    raise
            if code != 0 or not partial_path.exists() or partial_path.stat().st_size == 0:
                tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
                raise RuntimeError(f"FFmpeg 分段编码失败（退出码 {code}）：{tail}")
            os.replace(partial_path, final_path)
            manifest["segments"].append({"file": name, "frames": frames, "bytes": final_path.stat().st_size})
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=directory, suffix=".json", delete=False) as tmp:
                json.dump(manifest, tmp, ensure_ascii=False, indent=2)
                tmp_name = tmp.name
            os.replace(tmp_name, manifest_path)
            print(f"[H3DiskVideo] {index + 1}/{count}: {final_path} ({frames} frames)")
        finally:
            audio_path.unlink(missing_ok=True)
            partial_path.unlink(missing_ok=True)
        return (loop_ctx, str(final_path))


def _concat_escape(path):
    return "'" + str(path).replace("'", "'\\''") + "'"


class H3DiskConcat:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"loop_ctx": ("MIE_LOOP_CTX",), "done": ("BOOLEAN", {"forceInput": True})}}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("video_path",)
    FUNCTION = "concat"
    CATEGORY = "Video Segment Writer/Output"
    OUTPUT_NODE = True

    def concat(self, loop_ctx, done):
        if not done:
            return ("",)
        directory = _run_dir(loop_ctx)
        manifest_path = directory / "manifest.json"
        if not manifest_path.exists():
            raise RuntimeError(f"分段清单不存在：{manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["run_id"] != loop_ctx["run_id"] or manifest["count"] != loop_ctx["count"]:
            raise RuntimeError("分段清单与循环上下文不一致。")
        segments = manifest["segments"]
        if len(segments) != manifest["count"] or not segments:
            raise RuntimeError("分段未全部编码，拒绝输出不完整成片。")
        paths = [directory / f"segment_{i:05d}.mp4" for i in range(len(segments))]
        for index, path in enumerate(paths):
            if path.name != segments[index]["file"] or not path.is_file() or path.stat().st_size == 0:
                raise RuntimeError(f"第 {index} 段缺失或为空：{path}")
        total_bytes = sum(path.stat().st_size for path in paths)
        if shutil.disk_usage(directory).free < total_bytes + 1024**3:
            raise RuntimeError("剩余空间不足以写出最终 MP4；所有分段已保留，可清理磁盘后重新拼接。")
        list_path = directory / "concat.ffconcat"
        list_path.write_text("ffconcat version 1.0\n" + "".join(f"file {_concat_escape(p)}\n" for p in paths), encoding="utf-8")
        output = directory / "final.mp4"
        partial = directory / "final.mp4.part"
        log_path = directory / "concat.log"
        cmd = [_ffmpeg(), "-hide_banner", "-loglevel", "warning", "-y", "-f", "concat", "-safe", "0",
               "-i", str(list_path), "-map", "0:v:0", "-map", "0:a:0", "-c", "copy",
               "-movflags", "+faststart", "-f", "mp4", str(partial)]
        with log_path.open("wb") as log:
            code = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=log).returncode
        if code != 0 or not partial.exists() or partial.stat().st_size == 0:
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
            raise RuntimeError(f"FFmpeg 拼接失败（退出码 {code}）；分段已保留：{tail}")
        os.replace(partial, output)
        print(f"[H3DiskVideo] 完成：{output}")
        return {"ui": {
            "text": [str(output)],
            "gifs": [{"filename": output.name,
                      "subfolder": f"h3_long_video/{loop_ctx['run_id']}",
                      "type": "output", "format": "video/h264-mp4"}],
        }, "result": (str(output),)}


NODE_CLASS_MAPPINGS = {
    "H3DiskEncodeSegment": H3DiskEncodeSegment,
    "H3DiskConcat": H3DiskConcat,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "H3DiskEncodeSegment": "H3 分段编码到磁盘",
    "H3DiskConcat": "H3 无重编码拼接成片",
}


# Keep stable node IDs and socket keys for existing workflows.
from .node_metadata import apply_metadata
apply_metadata(NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS)
WEB_DIRECTORY = "./web"
