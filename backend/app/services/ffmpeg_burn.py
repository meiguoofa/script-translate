from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass

from app.services.srt_utils import safe_area_height

logger = logging.getLogger("ffmpeg_burn")

_CROP_RE = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")
_CROP_PROBE_ATTEMPTS = 2


class VideoLayoutProbeError(RuntimeError):
    """Raised when remote video layout probing cannot produce a reliable result."""


@dataclass(frozen=True, slots=True)
class VideoLayout:
    """编码画布及其中稳定的有效画面边界。"""

    canvas_width: int
    canvas_height: int
    content_x: int
    content_y: int
    content_width: int
    content_height: int

    @classmethod
    def full_frame(cls, width: int, height: int) -> VideoLayout:
        return cls(
            canvas_width=width,
            canvas_height=height,
            content_x=0,
            content_y=0,
            content_width=width,
            content_height=height,
        )


def probe_video_size(video_path: str) -> tuple[int, int]:
    """用 ffprobe 获取视频宽高。返回 (width, height)。"""
    timeout_seconds = (
        60 if video_path.startswith(("http://", "https://")) else 30
    )
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
        timeout=timeout_seconds,
    )
    w, h = result.stdout.strip().split(",")
    return int(w), int(h)


def _parse_cropdetect_output(output: str) -> tuple[int, int, int, int] | None:
    """返回最后一个累计 cropdetect 结果，格式为 (w, h, x, y)。"""
    matches = _CROP_RE.findall(output)
    if not matches:
        return None
    return tuple(int(value) for value in matches[-1])


def _probe_crop_sample(
    video_path: str,
    timestamp_seconds: float,
) -> tuple[int, int, int, int] | None:
    """对一个短片段运行 cropdetect；瞬时失败时重试一次。"""
    timeout_seconds = (
        45 if video_path.startswith(("http://", "https://")) else 15
    )
    command = [
        "ffmpeg",
        "-hide_banner",
        "-ss",
        f"{max(0.0, timestamp_seconds):.3f}",
        "-i",
        video_path,
        "-t",
        "0.5",
        "-vf",
        "cropdetect=limit=24:round=2:reset=0",
        "-an",
        "-sn",
        "-f",
        "null",
        "-",
    ]
    last_error: Exception | None = None
    for attempt in range(1, _CROP_PROBE_ATTEMPTS + 1):
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning(
                "cropdetect sample failed: path=%s timestamp=%.3f attempt=%d/%d",
                video_path,
                timestamp_seconds,
                attempt,
                _CROP_PROBE_ATTEMPTS,
                exc_info=True,
            )
            continue

        if result.returncode == 0:
            return _parse_cropdetect_output(f"{result.stdout}\n{result.stderr}")

        last_error = RuntimeError(f"ffmpeg exited with code {result.returncode}")
        logger.warning(
            "cropdetect returned code=%s: path=%s timestamp=%.3f "
            "attempt=%d/%d stderr=%s",
            result.returncode,
            video_path,
            timestamp_seconds,
            attempt,
            _CROP_PROBE_ATTEMPTS,
            result.stderr[-500:],
        )

    raise VideoLayoutProbeError(
        f"cropdetect sample failed after {_CROP_PROBE_ATTEMPTS} attempts: "
        f"timestamp={timestamp_seconds:.3f}"
    ) from last_error


def _is_pillarbox_crop(
    crop: tuple[int, int, int, int],
    canvas_width: int,
    canvas_height: int,
) -> bool:
    """只接受居中、近乎满高且确实存在明显左右黑边的裁剪。"""
    width, height, x, y = crop
    if (
        width <= 0
        or height <= 0
        or x < 0
        or y < 0
        or x + width > canvas_width
        or y + height > canvas_height
    ):
        return False

    # 过窄通常是黑场/局部亮物体误判；过宽则没有修正价值。
    if width < canvas_width * 0.25 or width > canvas_width * 0.95:
        return False

    vertical_tolerance = max(8, int(canvas_height * 0.02))
    if y > vertical_tolerance:
        return False
    if canvas_height - (y + height) > vertical_tolerance:
        return False

    crop_center = x + width / 2
    center_tolerance = max(8, int(canvas_width * 0.01))
    return abs(crop_center - canvas_width / 2) <= center_tolerance


def _crops_agree(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
    canvas_width: int,
    canvas_height: int,
) -> bool:
    horizontal_tolerance = max(8, int(canvas_width * 0.01))
    vertical_tolerance = max(8, int(canvas_height * 0.01))
    return (
        abs(first[0] - second[0]) <= horizontal_tolerance
        and abs(first[2] - second[2]) <= horizontal_tolerance
        and abs(first[1] - second[1]) <= vertical_tolerance
        and abs(first[3] - second[3]) <= vertical_tolerance
    )


def _intersect_crops(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    """取两次稳定探测的交集，避免字幕边缘落入任一次检测到的黑边。"""
    first_w, first_h, first_x, first_y = first
    second_w, second_h, second_x, second_y = second
    x = max(first_x, second_x)
    y = max(first_y, second_y)
    right = min(first_x + first_w, second_x + second_w)
    bottom = min(first_y + first_h, second_y + second_h)
    return right - x, bottom - y, x, y


def probe_video_layout(
    video_path: str,
    *,
    duration_seconds: float | None = None,
) -> VideoLayout:
    """探测画布中的稳定竖屏有效画面。

    先采样 10% 和 50% 位置；若结果不一致，再用 90% 位置仲裁。
    只有至少两个有效样本相互吻合时才采用 cropdetect 结果。
    成功样本不足时回退完整画布，避免因裁剪探测失败阻断整集。
    """
    try:
        canvas_width, canvas_height = probe_video_size(video_path)
    except Exception as exc:  # noqa: BLE001
        raise VideoLayoutProbeError(
            f"video size probe failed: path={video_path}"
        ) from exc
    full_frame = VideoLayout.full_frame(canvas_width, canvas_height)

    if canvas_width < canvas_height:
        logger.info(
            "portrait canvas uses full frame without crop detection: "
            "path=%s canvas=%sx%s",
            video_path,
            canvas_width,
            canvas_height,
        )
        return full_frame

    if duration_seconds is None or duration_seconds <= 0:
        duration_seconds = probe_video_duration_seconds(video_path)
    if duration_seconds > 0:
        latest_start = max(0.0, duration_seconds - 0.5)
        timestamps = [
            min(duration_seconds * ratio, latest_start)
            for ratio in (0.1, 0.5, 0.9)
        ]
    else:
        timestamps = [0.0, 5.0, 10.0]

    samples: list[tuple[int, int, int, int] | None] = []
    successful_samples = 0
    chosen: tuple[int, int, int, int] | None = None
    for timestamp in timestamps:
        try:
            crop = _probe_crop_sample(video_path, timestamp)
        except Exception:  # noqa: BLE001
            # 保留失败样本，成功样本不足时降级使用完整画布。
            logger.warning(
                "cropdetect sample raised unexpectedly: path=%s timestamp=%.3f",
                video_path,
                timestamp,
                exc_info=True,
            )
            crop = None
        else:
            successful_samples += 1
        if crop is not None and _is_pillarbox_crop(
            crop, canvas_width, canvas_height
        ):
            samples.append(crop)
        else:
            samples.append(None)

        if len(samples) == 2:
            first, second = samples
            if (
                first is not None
                and second is not None
                and _crops_agree(
                    first, second, canvas_width, canvas_height
                )
            ):
                chosen = _intersect_crops(first, second)
                break

    if chosen is None and len(samples) == 3:
        valid_samples = [sample for sample in samples if sample is not None]
        for index, first in enumerate(valid_samples):
            for second in valid_samples[index + 1 :]:
                if _crops_agree(
                    first, second, canvas_width, canvas_height
                ):
                    chosen = _intersect_crops(first, second)
                    break
            if chosen is not None:
                break

    if successful_samples < 2:
        logger.warning(
            "insufficient successful samples; falling back to full frame: "
            "path=%s successful=%d samples=%s",
            video_path,
            successful_samples,
            samples,
        )
        return full_frame

    if chosen is None:
        logger.info(
            "effective picture fallback to full frame: path=%s canvas=%sx%s samples=%s",
            video_path,
            canvas_width,
            canvas_height,
            samples,
        )
        return full_frame

    width, height, x, y = chosen
    layout = VideoLayout(
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        content_x=x,
        content_y=y,
        content_width=width,
        content_height=height,
    )
    logger.info("effective picture detected: path=%s layout=%s", video_path, layout)
    return layout


def probe_video_duration_seconds(video_path: str) -> float:
    """用 ffprobe 获取视频时长(秒)。失败返回 0。"""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                video_path,
            ],
            check=True, capture_output=True, text=True, timeout=30,
        )
        return float(result.stdout.strip())
    except Exception:  # noqa: BLE001
        logger.warning("probe_video_duration failed for %s", video_path)
        return 0.0


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
