"""火山引擎 Starling（i18n_openapi）Adapter。

封装所有 Starling OpenAPI 调用，业务层永远只看到本模块暴露的 dataclass 与方法，
不直接依赖火山 SDK 字段名。Starling 字段变化只影响本文件。

SDK 使用方式（volcengine-python-sdk 5.x）:
    configuration = volcenginesdkcore.Configuration()
    configuration.ak = "..."
    configuration.sk = "..."
    configuration.region = "cn-beijing"
    api_client = volcenginesdkcore.ApiClient(configuration=configuration)
    api = I18NOPENAPIApi(api_client=api_client)
    api.video_project_create(VideoProjectCreateRequest(...))

SDK 是同步的，本 Adapter 每个方法用 asyncio.to_thread 包成 async。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

import volcenginesdkcore
from volcenginesdki18nopenapi import (
    EffectSubtitleForVideoProjectSerialTaskCreateInput,
    PureVideoForVideoProjectSerialTaskCreateInput,
    SerialInfoForVideoProjectSerialTaskCreateInput,
    SubtitleForVideoProjectSerialTaskCreateInput,
    SuppressionParamsForVideoProjectSerialTaskCreateInput,
    TaskInfoForVideoProjectSerialTaskCreateInput,
    UploadVideoInfoForVideoProjectVideoUploadInput,
    VideoEditorSubmitSubtaskRequest,
    VideoForVideoProjectSerialTaskCreateInput,
    VideoProjectCreateRequest,
    VideoProjectGetTaskProductRequest,
    VideoProjectGetVideoUploadStatusRequest,
    VideoProjectSerialTaskCreateRequest,
    VideoProjectSuppressionStartRequest,
    VideoProjectTaskBatchStartAIFlowRequest,
    VideoProjectTaskDetailRequest,
    VideoProjectVideoUploadRequest,
)
from volcenginesdki18nopenapi.api.i18_n_openapi_api import I18NOPENAPIApi
from volcenginesdkcore.rest import ApiException

from app.config import Settings

logger = logging.getLogger("starling_client")


class StarlingError(Exception):
    """Starling Adapter 抛出的基类错误。"""


class StarlingRetryableError(StarlingError):
    """可重试错误：网络超时、5xx、限流。"""


class StarlingFatalError(StarlingError):
    """不可重试错误：参数错、权限未开通、余额不足、任务配置冲突。"""


# SubTask.status int32 枚举的可读翻译（实现期通过 OpenAPI Explorer 校准）
# 这些是常见状态码的猜测值，运行时按返回的 Code 调整
_SUBTASK_STATUS_MAP: dict[int, str] = {
    0: "UNKNOWN",
    1: "PENDING",
    2: "PROCESSING",
    3: "SUCCEEDED",
    4: "FAILED",
    5: "CANCELED",
}

# SubTask.suppression_status int32 枚举
_SUPPRESSION_STATUS_MAP: dict[int, str] = {
    0: "NOT_STARTED",
    1: "PROCESSING",
    2: "SUCCEEDED",
    3: "FAILED",
}

# VideoUploadTask.status int32 枚举
_UPLOAD_STATUS_MAP: dict[int, str] = {
    0: "UNKNOWN",
    1: "PENDING",
    2: "PROCESSING",
    3: "READY",
    4: "FAILED",
}


def _status_text(value: int | None, mapping: dict[int, str]) -> str:
    if value is None:
        return "UNKNOWN"
    return mapping.get(value, f"UNKNOWN_{value}")


@dataclass
class CreateProjectResult:
    project_id: str


@dataclass
class UploadVideoResult:
    batch_id: str


@dataclass
class UploadStatus:
    status: int
    status_text: str
    video_id: str | None
    video_name: str | None


@dataclass
class CreateSerialTaskResult:
    task_ids: list[str]
    dub_task_ids: list[str] = field(default_factory=list)


@dataclass
class SubtaskInfo:
    """从 VideoProjectTaskDetail 提取的子任务信息。"""

    subtask_id: str
    episode_num: str
    source_language: str
    target_language: str
    status: int
    status_text: str
    op_status: int
    current_stage: int
    suppression_status: int
    suppression_status_text: str
    video_id: str | None
    vid_with_ai_remove: str | None


@dataclass
class ProductArtifact:
    """VideoProjectGetTaskProduct 返回的单个产物。"""

    subtask_id: str
    episode_num: str
    target_lang: str
    artifact_type: str  # final_video / clean_video / origin_video / dubbed_audio / source_subtitle / target_subtitle
    name: str
    url: str
    vid: str | None


@dataclass
class SerialEpisodeInput:
    """业务层传入的单集视频参数（用于 CreateSerialTask）。"""

    episode: int
    video_name: str
    video_url: str
    video_id: str | None  # Starling 视频 ID（upload 后获得）


class StarlingClient:
    """火山 Starling OpenAPI 客户端封装。

    所有方法 async；内部用 asyncio.to_thread 把同步 SDK 调用包成协程。
    错误分类：
    - 网络超时/5xx/限流 -> StarlingRetryableError
    - 4xx 业务错 -> StarlingFatalError
    """

    def __init__(self, settings: Settings):
        if not settings.starling_access_key_id or not settings.starling_secret_access_key:
            raise StarlingFatalError("Starling AK/SK 未配置，请检查 .env 中 STARLING_ACCESS_KEY_ID/SECRET_ACCESS_KEY")
        self._settings = settings
        configuration = volcenginesdkcore.Configuration()
        configuration.ak = settings.starling_access_key_id
        configuration.sk = settings.starling_secret_access_key
        configuration.region = settings.starling_region
        configuration.host = settings.starling_host
        # 默认 SDK 重试 3 次（已修复 4.0.1~4.0.42 的缺陷，5.x 版本无此问题）
        configuration.auto_retry = True
        configuration.num_max_retries = 3
        api_client = volcenginesdkcore.ApiClient(configuration=configuration)
        self._api = I18NOPENAPIApi(api_client=api_client)
        # ISO 语言代码 -> int32 枚举映射
        self._lang_map: dict[str, int] = {
            "en": settings.starling_lang_en,
            "es": settings.starling_lang_es,
            "pt": settings.starling_lang_pt,
            "th": settings.starling_lang_th,
            "id": settings.starling_lang_id,
            "vi": settings.starling_lang_vi,
            "ms": settings.starling_lang_ms,
            "ja": settings.starling_lang_ja,
            "ko": settings.starling_lang_ko,
        }

    def lang_to_int(self, iso_lang: str) -> int:
        """ISO 语言代码 -> Starling int32 枚举。"""
        v = self._lang_map.get(iso_lang)
        if v is None:
            raise StarlingFatalError(f"不支持的目标语言: {iso_lang}")
        return v

    @staticmethod
    def _classify_error(exc: Exception) -> StarlingError:
        """把 SDK 异常分类为可重试/不可重试。"""
        if isinstance(exc, ApiException):
            # ApiException 通常是业务错（4xx）
            body = getattr(exc, "body", "") or ""
            msg = f"{exc} | body={body}"
            # 限流或 5xx 也可能走 ApiException
            if exc.status and exc.status >= 500:
                return StarlingRetryableError(f"Starling 5xx: {msg}")
            if exc.status == 429 or "throttl" in msg.lower() or "rate" in msg.lower():
                return StarlingRetryableError(f"Starling 限流: {msg}")
            return StarlingFatalError(f"Starling 业务错: {msg}")
        # 网络/超时/连接错
        msg = str(exc).lower()
        if any(k in msg for k in ("timeout", "timed out", "connection", "network", "temporar")):
            return StarlingRetryableError(f"Starling 网络错: {exc}")
        return StarlingFatalError(f"Starling 调用失败: {exc}")

    async def create_project(self, name: str, comment: str = "") -> CreateProjectResult:
        """Action=VideoProjectCreate, projectType=1（短剧项目）。"""
        req = VideoProjectCreateRequest(name=name, project_type=1, comment=comment)
        try:
            resp = await asyncio.to_thread(self._api.video_project_create, req)
        except Exception as exc:
            raise self._classify_error(exc) from exc
        project_id = getattr(resp.data, "project_id", None) if resp.data else None
        if not project_id:
            raise StarlingFatalError(f"Starling create_project 未返回 project_id: {resp}")
        logger.info("Starling create_project name=%s -> project_id=%s", name, project_id)
        return CreateProjectResult(project_id=project_id)

    async def upload_video(self, project_id: str, video_url: str, video_name: str) -> UploadVideoResult:
        """Action=VideoProjectVideoUpload，传 URL 让 Starling 异步拉取。"""
        info = UploadVideoInfoForVideoProjectVideoUploadInput(
            video_name=video_name,
            video_url=video_url,
        )
        req = VideoProjectVideoUploadRequest(
            project_id=project_id,
            video_upload_type=self._settings.starling_video_upload_type_url,
            upload_video_infos=[info],
        )
        try:
            resp = await asyncio.to_thread(self._api.video_project_video_upload, req)
        except Exception as exc:
            raise self._classify_error(exc) from exc
        batch_id = getattr(resp.data, "batch_id", None) if resp.data else None
        if not batch_id:
            raise StarlingFatalError(f"Starling upload_video 未返回 batch_id: {resp}")
        logger.info("Starling upload_video project=%s url=%s -> batch=%s", project_id, video_url, batch_id)
        return UploadVideoResult(batch_id=batch_id)

    async def get_video_upload_status(self, project_id: str, batch_id: str) -> list[UploadStatus]:
        """Action=VideoProjectGetVideoUploadStatus。"""
        req = VideoProjectGetVideoUploadStatusRequest(project_id=project_id, batch_id=batch_id)
        try:
            resp = await asyncio.to_thread(self._api.video_project_get_video_upload_status, req)
        except Exception as exc:
            raise self._classify_error(exc) from exc
        tasks: list[Any] = getattr(resp.data, "video_upload_tasks", []) if resp.data else []
        result: list[UploadStatus] = []
        for t in tasks:
            status_val = getattr(t, "status", 0) or 0
            result.append(
                UploadStatus(
                    status=status_val,
                    status_text=_status_text(status_val, _UPLOAD_STATUS_MAP),
                    video_id=getattr(t, "video_id", None),
                    video_name=getattr(t, "video_name", None),
                )
            )
        return result

    async def create_serial_task(
        self,
        project_id: str,
        task_name: str,
        source_lang: str,
        target_langs: list[str],
        episodes: list[SerialEpisodeInput],
        *,
        dubbing_enabled: bool = True,
        subtitle_removal_mode: str = "BASIC",
    ) -> CreateSerialTaskResult:
        """Action=VideoProjectSerialTaskCreate，创建完整翻配任务。

        subtitle_removal_mode 映射到 task_info.ai_remove_type（具体 int32 值实现期校准）。
        """
        # 构造 serial_info 列表
        serial_info_list: list[SerialInfoForVideoProjectSerialTaskCreateInput] = []
        for ep in episodes:
            video = VideoForVideoProjectSerialTaskCreateInput(
                name=ep.video_name,
                vid=ep.video_id,
                video_url=ep.video_url,
            )
            serial_info_list.append(
                SerialInfoForVideoProjectSerialTaskCreateInput(
                    episode=ep.episode,
                    video=video,
                )
            )

        # ai_remove_type 枚举：0=None, 1=BASIC, 2=ADVANCED（实现期校准）
        ai_remove_type_map = {"NONE": 0, "BASIC": 1, "ADVANCED": 2}
        ai_remove_type = ai_remove_type_map.get(subtitle_removal_mode, 1)

        task_info = TaskInfoForVideoProjectSerialTaskCreateInput(
            task_name=task_name,
            source_lang=source_lang,
            target_langs=target_langs,
            is_dub=dubbing_enabled,
            use_mt=True,
            ai_remove_type=ai_remove_type,
            serial_number="1",
            asr_model=0,
            suppression_params=SuppressionParamsForVideoProjectSerialTaskCreateInput(
                exclude_subtitle=False
            ),
        )

        req = VideoProjectSerialTaskCreateRequest(
            project_id=project_id,
            serial_info=serial_info_list,
            task_info=task_info,
        )
        try:
            resp = await asyncio.to_thread(self._api.video_project_serial_task_create, req)
        except Exception as exc:
            raise self._classify_error(exc) from exc
        data = resp.data
        task_ids: list[str] = list(getattr(data, "task_ids", []) or [])
        dub_task_ids: list[str] = list(getattr(data, "dub_task_ids", []) or [])
        if not task_ids:
            base_resp = getattr(data, "base_resp", None)
            msg = getattr(base_resp, "msg", "") if base_resp else ""
            raise StarlingFatalError(f"Starling create_serial_task 未返回 task_ids, msg={msg}")
        logger.info(
            "Starling create_serial_task project=%s task_name=%s -> task_ids=%s",
            project_id, task_name, task_ids,
        )
        return CreateSerialTaskResult(task_ids=task_ids, dub_task_ids=dub_task_ids)

    async def start_ai_flow(self, project_id: str, subtask_ids: list[str]) -> None:
        """Action=VideoProjectTaskBatchStartAIFlow，项目级触发 AI 流程。

        经验证：必须先调 operate_type=1 再调 operate_type=2 才能真正启动 AI 处理。
        仅调 op=1 时 Starling 返回 success 但 subtask 仍停留在 status=2 op_status=0。
        """
        if not subtask_ids:
            return
        # op=1: 启动 AI 流程
        req1 = VideoProjectTaskBatchStartAIFlowRequest(
            project_id=project_id,
            operate_type=self._settings.starling_operate_type_start,
            subtask_ids=subtask_ids,
        )
        # op=2: 实际触发处理
        req2 = VideoProjectTaskBatchStartAIFlowRequest(
            project_id=project_id,
            operate_type=self._settings.starling_operate_type_start + 1,
            subtask_ids=subtask_ids,
        )
        try:
            await asyncio.to_thread(self._api.video_project_task_batch_start_ai_flow, req1)
            await asyncio.to_thread(self._api.video_project_task_batch_start_ai_flow, req2)
        except Exception as exc:
            raise self._classify_error(exc) from exc
        logger.info("Starling start_ai_flow project=%s subtask_ids=%s", project_id, subtask_ids)

    async def get_task_detail(self, project_id: str, task_id: str) -> list[SubtaskInfo]:
        """Action=VideoProjectTaskDetail，返回所有 subtask 状态。"""
        req = VideoProjectTaskDetailRequest(project_id=project_id, task_id=task_id)
        try:
            resp = await asyncio.to_thread(self._api.video_project_task_detail, req)
        except Exception as exc:
            raise self._classify_error(exc) from exc
        data = resp.data
        sub_tasks: list[Any] = getattr(data, "sub_tasks", []) if data else []
        result: list[SubtaskInfo] = []
        for st in sub_tasks:
            status_val = getattr(st, "status", 0) or 0
            supp_val = getattr(st, "suppression_status", 0) or 0
            result.append(
                SubtaskInfo(
                    subtask_id=getattr(st, "id", "") or "",
                    episode_num=getattr(st, "episode_num", "") or "",
                    source_language=getattr(st, "source_language", "") or "",
                    target_language=getattr(st, "target_language", "") or "",
                    status=status_val,
                    status_text=_status_text(status_val, _SUBTASK_STATUS_MAP),
                    op_status=getattr(st, "op_status", 0) or 0,
                    current_stage=getattr(st, "current_stage", 0) or 0,
                    suppression_status=supp_val,
                    suppression_status_text=_status_text(supp_val, _SUPPRESSION_STATUS_MAP),
                    video_id=getattr(st, "video_id", None),
                    vid_with_ai_remove=getattr(st, "vid_with_ai_remove", None),
                )
            )
        return result

    async def submit_subtask(self, subtask_id: str) -> None:
        """Action=VideoEditorSubmitSubtask，单 subtask 校对提交。"""
        req = VideoEditorSubmitSubtaskRequest(subtask_id=subtask_id)
        try:
            await asyncio.to_thread(self._api.video_editor_submit_subtask, req)
        except Exception as exc:
            raise self._classify_error(exc) from exc
        logger.info("Starling submit_subtask subtask_id=%s", subtask_id)

    async def start_suppression(
        self, project_id: str, lang_iso: str, subtask_ids: list[str]
    ) -> None:
        """Action=VideoProjectSuppressionStart，按目标语言批量压制。"""
        req = VideoProjectSuppressionStartRequest(
            project_id=project_id,
            lang=self.lang_to_int(lang_iso),
            arrange_ment=self._settings.starling_suppress_arrangement,
            encode=self._settings.starling_suppress_encode,
            format=self._settings.starling_suppress_format,
            subtask_ids=subtask_ids,
        )
        try:
            await asyncio.to_thread(self._api.video_project_suppression_start, req)
        except Exception as exc:
            raise self._classify_error(exc) from exc
        logger.info(
            "Starling start_suppression project=%s lang=%s subtask_count=%d",
            project_id, lang_iso, len(subtask_ids),
        )

    async def get_task_products(
        self, project_id: str, task_id: str
    ) -> list[ProductArtifact]:
        """Action=VideoProjectGetTaskProduct，返回所有 subtask 的产物。

        types 必填：1=source_subtitle, 2=target_subtitle, 3=ai_remove_video,
        4=finished_video, 5=finished_audio, 6=origin_video。
        """
        req = VideoProjectGetTaskProductRequest(
            project_id=project_id,
            task_id=task_id,
            types=[1, 2, 3, 4, 5, 6],
        )
        try:
            resp = await asyncio.to_thread(self._api.video_project_get_task_product, req)
        except Exception as exc:
            raise self._classify_error(exc) from exc
        data = resp.data
        products: list[Any] = getattr(data, "subtask_products", []) if data else None
        if not products:
            return []
        result: list[ProductArtifact] = []
        for p in products:
            subtask_id = getattr(p, "subtask_id", "") or ""
            episode_num = getattr(p, "episode_num", "") or ""
            target_lang = getattr(p, "target_lang", "") or ""
            # 6 种产物类型
            for artifact_type, attr_name, has_vid in [
                ("final_video", "finished_video", True),
                ("clean_video", "ai_remove_video", True),
                ("origin_video", "origin_video", True),
                ("dubbed_audio", "finished_audio", False),
                ("source_subtitle", "source_subtitle", False),
                ("target_subtitle", "target_subtitle", False),
            ]:
                sub_obj = getattr(p, attr_name, None)
                if sub_obj is None:
                    continue
                url = getattr(sub_obj, "url", None)
                if not url:
                    continue
                result.append(
                    ProductArtifact(
                        subtask_id=subtask_id,
                        episode_num=episode_num,
                        target_lang=target_lang,
                        artifact_type=artifact_type,
                        name=getattr(sub_obj, "name", "") or "",
                        url=url,
                        vid=getattr(sub_obj, "vid", None) if has_vid else None,
                    )
                )
        return result
