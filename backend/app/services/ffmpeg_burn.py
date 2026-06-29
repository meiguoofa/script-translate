from __future__ import annotations

import logging
import subprocess

from app.services.srt_utils import safe_area_height

logger = logging.getLogger("ffmpeg_burn")


def probe_video_size(video_path: str) -> tuple[int, int]:
    """用 ffprobe 获取视频宽高。返回 (width, height)。"""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            video_path,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    w, h = result.stdout.strip().split(",")
    return int(w), int(h)


def burn_subtitles(
    input_video: str,
    ass_path: str,
    output_video: str,
    *,
    placement_mode: str,
    video_w: int,
    video_h: int,
) -> None:
    """FFmpeg 把 ASS 字幕硬嵌到视频。

    safe_bottom: 缩小原画面 + 底部 pad 黑边，字幕放在黑边里。
    simple_bottom: 直接烧到原画面底部。
    """
    if placement_mode == "safe_bottom":
        sa = safe_area_height(video_h)
        content_h = video_h - sa
        vf = f"scale={video_w}:{content_h},pad={video_w}:{video_h}:0:0:black,ass={ass_path}"
    else:  # simple_bottom
        vf = f"ass={ass_path}"

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_video,
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "copy",
        output_video,
    ]
    logger.info("ffmpeg burn: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg 烧字幕失败 (code={result.returncode}): {result.stderr[-2000:]}"
        )
