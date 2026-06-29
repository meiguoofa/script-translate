from __future__ import annotations

import json
import logging
import time
from collections import Counter
from dataclasses import dataclass, field

from alibabacloud_tea_openapi.models import Config as OpenApiConfig
from alibabacloud_tea_util.models import RuntimeOptions
from alibabacloud_videorecog20200320 import models as vr_models
from alibabacloud_videorecog20200320.client import Client as VideorecogClient

from app.config import Settings
from app.services.srt_utils import SrtEntry, build_srt

logger = logging.getLogger("video_ocr_client")


@dataclass
class SubtitleOcrSubmitResult:
    job_id: str  # = RequestId；作为 JobId 调 GetAsyncJobResult


@dataclass
class SubtitleOcrFinalResult:
    status: str
    srt_text: str = ""
    raw: dict = field(default_factory=dict)


class VideoOCRClient:
    """阿里云 VIAPI 视频字幕 OCR（videorecog SDK）。

    `recognize_video_cast_crew_list` 是**异步**接口：
      - 提交立即返回 `RequestId`，以 `RequestId` 作为 `jobId` 调
        `get_async_job_result_with_options` 轮询任务状态。
      - 成功时 `Data.Result` 是 JSON 字符串，结构：
        `{"SubtitlesResults":[{"SubtitlesChineseResultsUrl":"...","SubtitlesAllResultsUrl":"...","SubtitlesEnglishResultsUrl":"..."}]}`
    """

    def __init__(self, settings: Settings):
        if not settings.aliyun_access_key_id or not settings.aliyun_access_key_secret:
            raise RuntimeError("ALIBABA_CLOUD_ACCESS_KEY_ID / SECRET 未配置")
        self._settings = settings
        config = OpenApiConfig(
            access_key_id=settings.aliyun_access_key_id,
            access_key_secret=settings.aliyun_access_key_secret,
        )
        config.endpoint = settings.aliyun_videorecog_endpoint
        self._client = VideorecogClient(config)

    def submit_subtitle_ocr(self, video_url: str) -> SubtitleOcrSubmitResult:
        params = vr_models.RecognizeVideoCastCrewListRequestParams(type="subtitles")
        request = vr_models.RecognizeVideoCastCrewListRequest(
            video_url=video_url,
            params=[params],
        )
        runtime = RuntimeOptions()
        runtime.connect_timeout = 60_000
        runtime.read_timeout = 120_000

        response = self._client.recognize_video_cast_crew_list_with_options(
            request, runtime
        )
        request_id = response.body.request_id if response.body else None
        if not request_id:
            raw = response.body.to_map() if response.body else {}
            raise RuntimeError(
                f"VIAPI RecognizeVideoCastCrewList submit 未返回 RequestId: {raw}"
            )
        logger.info("Subtitle OCR submitted (url), jobId=%s", request_id)
        return SubtitleOcrSubmitResult(job_id=request_id)

    def submit_subtitle_ocr_from_file(self, video_path: str) -> SubtitleOcrSubmitResult:
        """用 advance 接口把本地视频文件流式上传到 VIAPI 内部 OSS。

        VIAPI videorecog 无法直接拉取火山 TOS URL（非上海 OSS），
        所以需要先把视频下载到本地，再用 advance 接口上传。
        """
        params = vr_models.RecognizeVideoCastCrewListAdvanceRequestParams(
            type="subtitles"
        )
        request = vr_models.RecognizeVideoCastCrewListAdvanceRequest(
            params=[params],
            video_url_object=open(video_path, "rb"),
        )
        runtime = RuntimeOptions()
        runtime.connect_timeout = 120_000
        runtime.read_timeout = 600_000

        try:
            response = self._client.recognize_video_cast_crew_list_advance(
                request, runtime
            )
        finally:
            request.video_url_object.close()

        request_id = response.body.request_id if response.body else None
        if not request_id:
            raw = response.body.to_map() if response.body else {}
            raise RuntimeError(
                f"VIAPI RecognizeVideoCastCrewList advance submit 未返回 RequestId: {raw}"
            )
        logger.info("Subtitle OCR submitted (file), jobId=%s", request_id)
        return SubtitleOcrSubmitResult(job_id=request_id)

    def poll_job(self, job_id: str) -> dict:
        request = vr_models.GetAsyncJobResultRequest(job_id=job_id)
        runtime = RuntimeOptions()
        runtime.connect_timeout = 10_000
        runtime.read_timeout = 15_000
        response = self._client.get_async_job_result_with_options(request, runtime)
        return response.body.to_map() if response.body else {}

    def wait_for_subtitle_ocr(
        self, job_id: str, *, poll_interval_seconds: int, timeout_seconds: int
    ) -> SubtitleOcrFinalResult:
        """Block until job reaches PROCESS_SUCCESS / PROCESS_FAILED or timeout."""

        deadline = time.monotonic() + max(60, timeout_seconds)
        last_raw: dict = {}
        last_status: str | None = None
        while True:
            if time.monotonic() > deadline:
                raise RuntimeError(
                    f"VIAPI 字幕 OCR 任务 {job_id} 等待超时（>{timeout_seconds}s），last={last_raw}"
                )
            try:
                raw = self.poll_job(job_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("poll job %s 出错: %s, retrying", job_id, exc)
                time.sleep(max(1, poll_interval_seconds))
                continue
            last_raw = raw
            data = raw.get("Data", {}) or {}
            status = data.get("Status")
            if status != last_status:
                logger.info("VIAPI 字幕 OCR job %s status=%s", job_id, status)
                last_status = status
            if status == "PROCESS_SUCCESS":
                result_str = data.get("Result") or "{}"
                try:
                    parsed = json.loads(result_str)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        f"VIAPI 字幕 OCR 任务 {job_id} 结果不是合法 JSON: {result_str!r}"
                    ) from exc
                srt_text = self._ocr_results_to_srt(parsed)
                if not srt_text:
                    raise RuntimeError(
                        f"VIAPI 字幕 OCR 任务 {job_id} 结果未包含任何字幕文本: {parsed}"
                    )
                logger.info(
                    "VIAPI 字幕 OCR job %s SUCCESS srt_lines=%d",
                    job_id,
                    srt_text.count("\n\n") + 1,
                )
                return SubtitleOcrFinalResult(status=status, srt_text=srt_text, raw=raw)
            if status == "PROCESS_FAILED":
                err = data.get("Result") or data.get("ErrorMessage") or str(raw)
                raise RuntimeError(f"VIAPI 字幕 OCR 任务 {job_id} 处理失败: {err}")
            time.sleep(max(1, poll_interval_seconds))

    @staticmethod
    def _ocr_results_to_srt(parsed: dict) -> str:
        """把 VIAPI 返回的 ocrResults（逐帧 OCR 框）聚合成 SRT。

        每个 ocrResult 是一帧，含 startTime/endTime 和 detailInfo[]。
        每个 detailInfo 是一行文本，含 text、trackId、timeStamp。
        同一 trackId 的帧聚合成一条 SRT：start=min(timeStamp), end=max(endTime),
        text=该 track 内最频繁出现的文本。

        若同一 trackId 内出现 >1.5 秒的帧间隔，拆成多条 SRT（字幕消失再出现）。
        """

        ocr_results = parsed.get("ocrResults") or parsed.get("OcrResults") or []
        if not ocr_results:
            return ""

        # 按 trackId 收集 (timeStamp_sec, endTime_sec, text)
        tracks: dict[int, list[tuple[float, float, str]]] = {}
        for frame in ocr_results:
            frame_end = float(frame.get("endTime") or frame.get("EndTime") or 0)
            for detail in frame.get("detailInfo") or frame.get("DetailInfo") or []:
                tid = detail.get("trackId", detail.get("TrackId", 0))
                ts = float(detail.get("timeStamp", detail.get("TimeStamp", 0)))
                text = (detail.get("text") or detail.get("Text") or "").strip()
                if not text:
                    continue
                tracks.setdefault(tid, []).append((ts, frame_end or ts, text))

        entries: list[SrtEntry] = []
        for tid in sorted(tracks.keys()):
            frames = sorted(tracks[tid], key=lambda x: x[0])
            # 按时间间隔拆分（>1.5s 视为字幕消失再出现）
            segments: list[list[tuple[float, float, str]]] = [[]]
            for i, fr in enumerate(frames):
                if i > 0 and fr[0] - frames[i - 1][0] > 1.5:
                    segments.append([])
                segments[-1].append(fr)
            for seg in segments:
                if not seg:
                    continue
                start_ms = int(seg[0][0] * 1000)
                end_ms = int(seg[-1][1] * 1000)
                if end_ms <= start_ms:
                    end_ms = start_ms + 1000
                text = Counter(f[2] for f in seg).most_common(1)[0][0]
                entries.append(
                    SrtEntry(
                        index=len(entries) + 1,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        text=text,
                    )
                )

        entries.sort(key=lambda e: e.start_ms)
        for i, e in enumerate(entries, start=1):
            e.index = i
        return build_srt(entries)
