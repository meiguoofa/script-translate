"""Starling 短剧全链路翻配 Runner。

编排流程（参考 starling-huoshan.md 第六/二十一章）:
1. ensure_starling_project     - 按 drama_name 复用或新建 VideoProjectCreate
2. upload_episodes             - VideoProjectVideoUpload 传 OSS 公开 URL
3. wait_for_uploads            - 轮询 VideoProjectGetVideoUploadStatus
4. create_serial_task          - VideoProjectSerialTaskCreate
5. ensure_ai_flow_started      - 条件触发 VideoProjectTaskBatchStartAIFlow
6. wait_for_ai_result          - 轮询 VideoProjectTaskDetail
7. submit_subtasks             - 每集每语言 VideoEditorSubmitSubtask
8. start_suppression           - 按目标语言 VideoProjectSuppressionStart
9. wait_for_suppression        - 轮询 VideoProjectTaskDetail 的 SuppressionStatus
10. fetch_and_archive_products - VideoProjectGetTaskProduct + OSS 异步拉取归档

并发控制：全局 asyncio.Semaphore 限制同时跑的 job 数；单 job 内分集上传/产物下载也限并发。
状态持久化：复用 _persist_locks + _persist_items 模式。
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.config import Settings
from app.db import Database
from app.models import StarlingDramaJob
from app.services.ffmpeg_burn import probe_video_size, probe_video_duration_seconds
from app.services.starling_client import (
    ProductArtifact,
    SerialEpisodeInput,
    StarlingClient,
    StarlingError,
    StarlingFatalError,
    StarlingRetryableError,
    SubtaskInfo,
)
from app.services.tos_starling_client import TOSStarlingClient

logger = logging.getLogger("starling_drama_runner")


# 全局并发 semaphore（惰性初始化，避免模块加载时无 event loop）
_global_semaphore: asyncio.Semaphore | None = None

# 每个 job 一把持久化锁，防止并发写 items_json 互相覆盖
_persist_locks: dict[str, asyncio.Lock] = {}


def _get_semaphore(settings: Settings) -> asyncio.Semaphore:
    global _global_semaphore
    if _global_semaphore is None:
        _global_semaphore = asyncio.Semaphore(settings.starling_max_concurrent_jobs)
    return _global_semaphore


def _get_persist_lock(job_id: str) -> asyncio.Lock:
    lock = _persist_locks.get(job_id)
    if lock is None:
        lock = asyncio.Lock()
        _persist_locks[job_id] = lock
    return lock


async def _persist_items(db: Database, job_id: str, items: list[dict]) -> None:
    async with _get_persist_lock(job_id):
        async with await db.session() as session:
            job = await session.get(StarlingDramaJob, job_id)
            if job is None:
                return
            job.items_json = json.dumps(items, ensure_ascii=False)
            await session.commit()


async def _set_job_fields(
    db: Database,
    job_id: str,
    *,
    status: str | None = None,
    progress_message: str | None = None,
    error_message: str | None = None,
    submitted_at: datetime | None = None,
    completed_at: datetime | None = None,
    starling_project_id: str | None = None,
    starling_task_id: str | None = None,
) -> None:
    async with await db.session() as session:
        job = await session.get(StarlingDramaJob, job_id)
        if job is None:
            return
        if status is not None:
            job.status = status
        if progress_message is not None:
            job.progress_message = progress_message
        if error_message is not None:
            job.error_message = error_message
        if submitted_at is not None:
            job.submitted_at = submitted_at
        if completed_at is not None:
            job.completed_at = completed_at
        if starling_project_id is not None:
            job.starling_project_id = starling_project_id
        if starling_task_id is not None:
            job.starling_task_id = starling_task_id
        await session.commit()


async def _load_snapshot(db: Database, job_id: str) -> dict | None:
    async with await db.session() as session:
        job = await session.get(StarlingDramaJob, job_id)
        if job is None:
            return None
        target_langs: list[str] = []
        if job.target_langs_json:
            try:
                lst = json.loads(job.target_langs_json)
                if isinstance(lst, list):
                    target_langs = [str(x) for x in lst if str(x).strip()]
            except json.JSONDecodeError:
                pass
        return {
            "id": job.id,
            "title": job.title,
            "drama_name": job.drama_name,
            "source_lang": job.source_lang,
            "target_langs": target_langs,
            "starling_project_id": job.starling_project_id,
            "starling_task_id": job.starling_task_id,
            "subtitle_removal_mode": job.subtitle_removal_mode,
            "burn_target_subtitle": job.burn_target_subtitle,
            "subtitle_style_template": job.subtitle_style_template,
            "dubbing_enabled": job.dubbing_enabled,
            "dubbing_speaker_mode": job.dubbing_speaker_mode,
            "dubbing_emotion_mode": job.dubbing_emotion_mode,
            "dubbing_preserve_bg_audio": job.dubbing_preserve_bg_audio,
            "workflow_mode": job.workflow_mode,
            "max_retry_count": job.max_retry_count,
            "items": json.loads(job.items_json or "[]"),
            "output_oss_prefix": job.output_oss_prefix,
            "output_tos_prefix": job.output_tos_prefix,
        }


def _is_aborted(db: Database, job_id: str) -> bool:
    """同步快速检查 job 是否被标记为 failed（用户停止）。"""
    # 用同步只读连接避免和 runner 的写锁竞争
    import sqlite3
    from app.config import Settings as _S
    s = _S()
    db_path = s.database_url.replace("sqlite+aiosqlite:///", "")
    try:
        con = sqlite3.connect(db_path, timeout=2)
        row = con.execute(
            "SELECT status FROM starling_drama_jobs WHERE id=?", (job_id,)
        ).fetchone()
        con.close()
        return bool(row and row[0] == "failed")
    except Exception:  # noqa: BLE001
        return False


# SubTask.status int32 -> 是否完成态（实现期校准，先用 _SUBTASK_STATUS_MAP 的猜测值）
_SUBTASK_STATUS_SUCCEEDED = 3
_SUBTASK_STATUS_FAILED = 4
_SUPPRESSION_STATUS_SUCCEEDED = 2
_SUPPRESSION_STATUS_FAILED = 3


async def run_starling_drama_job(
    db: Database, settings: Settings, job_id: str
) -> None:
    """Runner 主入口，由 BackgroundTasks 调用。"""
    semaphore = _get_semaphore(settings)
    async with semaphore:
        try:
            await _set_job_fields(
                db, job_id,
                status="running",
                submitted_at=datetime.now(timezone.utc),
                progress_message="开始处理",
            )
            snapshot = await _load_snapshot(db, job_id)
            if snapshot is None:
                logger.error("Starling job %s 不存在", job_id)
                return

            client = StarlingClient(settings)
            tos = TOSStarlingClient(settings)

            await _ensure_project(db, job_id, snapshot, client)
            await _upload_episodes(db, job_id, snapshot, client, settings, tos)
            await _wait_for_uploads(db, job_id, snapshot, client, settings)

            # retry 时 starling_task_id 可能已存在，跳过创建避免「任务目标语种已存在」错误
            if not snapshot.get("starling_task_id"):
                await _create_serial_task(db, job_id, snapshot, client)
            await _ensure_ai_flow_started(db, job_id, snapshot, client)
            await _wait_for_ai_result(db, job_id, snapshot, client, settings)

            if snapshot["workflow_mode"] == "FULLY_AUTOMATIC":
                await _submit_subtasks(db, job_id, snapshot, client)

            await _start_suppression(db, job_id, snapshot, client)
            await _wait_for_suppression(db, job_id, snapshot, client, settings)
            await _fetch_and_archive_products(db, job_id, snapshot, client, settings, tos)

            await _set_job_fields(
                db, job_id,
                status="completed",
                completed_at=datetime.now(timezone.utc),
                progress_message="全部产物已归档",
            )
            logger.info("Starling drama job %s completed", job_id)
        except StarlingFatalError as exc:
            logger.exception("Starling job %s fatal error", job_id)
            await _set_job_fields(
                db, job_id, status="failed",
                error_message=f"[FATAL] {exc}"[:4000],
            )
        except StarlingRetryableError as exc:
            logger.exception("Starling job %s retryable error exhausted", job_id)
            await _set_job_fields(
                db, job_id, status="failed",
                error_message=f"[RETRY_EXHAUSTED] {exc}"[:4000],
            )
        except Exception as exc:
            logger.exception("Starling job %s unexpected error", job_id)
            await _set_job_fields(
                db, job_id, status="failed",
                error_message=f"[ERROR] {exc}"[:4000],
            )


async def _ensure_project(
    db: Database, job_id: str, snapshot: dict, client: StarlingClient
) -> None:
    """按 drama_name 复用或新建 Starling Project。"""
    if snapshot["starling_project_id"]:
        await _set_job_fields(
            db, job_id, progress_message=f"复用 Starling Project {snapshot['starling_project_id']}"
        )
        return
    # 查同 drama_name 历史 job 是否已有 project_id
    async with await db.session() as session:
        from sqlalchemy import select
        stmt = select(StarlingDramaJob.starling_project_id).where(
            StarlingDramaJob.drama_name == snapshot["drama_name"],
            StarlingDramaJob.starling_project_id.isnot(None),
            StarlingDramaJob.id != job_id,
        ).limit(1)
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
    if existing:
        await _set_job_fields(
            db, job_id,
            starling_project_id=existing,
            progress_message=f"复用 Starling Project {existing}",
        )
        snapshot["starling_project_id"] = existing
        return
    # 新建
    await _set_job_fields(db, job_id, progress_message="创建 Starling Project...")
    result = await client.create_project(
        name=snapshot["drama_name"],
        comment=f"script-translate: {snapshot['title']}",
    )
    await _set_job_fields(
        db, job_id,
        starling_project_id=result.project_id,
        progress_message=f"已创建 Starling Project {result.project_id}",
    )
    snapshot["starling_project_id"] = result.project_id


async def _upload_episodes(
    db: Database,
    job_id: str,
    snapshot: dict,
    client: StarlingClient,
    settings: Settings,
    tos: TOSStarlingClient,
) -> None:
    """VideoProjectVideoUpload 传 TOS 公开 URL，并发 starling_upload_concurrency。"""
    items: list[dict] = snapshot["items"]
    project_id = snapshot["starling_project_id"]
    await _set_job_fields(db, job_id, progress_message=f"上传 {len(items)} 集视频到 Starling...")

    async def _upload_one(idx: int) -> None:
        item = items[idx]
        if item.get("upload_batch_id"):
            return  # 已上传
        source_url = item.get("source_video_url") or _tos_uri_to_public_url(
            item.get("source_tos_uri"), settings
        )
        if not source_url:
            item["status"] = "failed"
            item["error"] = "缺少 source_video_url"
            await _persist_items(db, job_id, items)
            return
        # FFprobe 预检（best-effort，失败不阻断，Starling 自己会校验）
        try:
            w, h = await asyncio.to_thread(probe_video_size, source_url)
            item["width"], item["height"] = w, h
        except Exception as exc:  # noqa: BLE001
            logger.warning("FFprobe size 失败 %s: %s", source_url, exc)
        try:
            dur = await asyncio.to_thread(probe_video_duration_seconds, source_url)
            item["duration_ms"] = int(dur * 1000) if dur else 0
        except Exception as exc:  # noqa: BLE001
            logger.warning("FFprobe duration 失败 %s: %s", source_url, exc)

        try:
            upload_result = await client.upload_video(
                project_id=project_id,
                video_url=source_url,
                video_name=item.get("source_filename") or f"episode_{item['episode_number']}.mp4",
            )
            item["upload_batch_id"] = upload_result.batch_id
            item["upload_status"] = "PENDING"
            await _persist_items(db, job_id, items)
        except StarlingError as exc:
            item["status"] = "failed"
            item["error"] = f"upload_video: {exc}"
            await _persist_items(db, job_id, items)
            logger.exception("upload_video failed for item %d", idx)

    sem = asyncio.Semaphore(settings.starling_upload_concurrency)

    async def _guarded(idx: int) -> None:
        async with sem:
            await _upload_one(idx)

    await asyncio.gather(*[_guarded(i) for i in range(len(items))])


def _tos_uri_to_public_url(tos_uri: str | None, settings: Settings) -> str | None:
    """tos://bucket/key -> 公开 HTTPS URL（TOS 北京 starling 桶）。"""
    if not tos_uri or not tos_uri.startswith("tos://"):
        return None
    rest = tos_uri[len("tos://"):]
    parts = rest.split("/", 1)
    if len(parts) < 2 or not parts[1]:
        return None
    key = parts[1]
    encoded = "/".join(quote(p, safe="") for p in key.split("/"))
    return f"https://{settings.tos_starling_bucket}.{settings.tos_starling_public_endpoint}/{encoded}"


async def _wait_for_uploads(
    db: Database, job_id: str, snapshot: dict, client: StarlingClient, settings: Settings
) -> None:
    """轮询 VideoProjectGetVideoUploadStatus，直到所有 item 拿到 video_id。"""
    items: list[dict] = snapshot["items"]
    project_id = snapshot["starling_project_id"]
    interval = settings.starling_poll_interval_upload_seconds
    deadline = asyncio.get_event_loop().time() + settings.starling_poll_timeout_seconds

    while asyncio.get_event_loop().time() < deadline:
        if _is_aborted(db, job_id):
            raise StarlingFatalError("任务已被停止")
        pending_idxs = [
            i for i, it in enumerate(items)
            if it.get("upload_batch_id") and not it.get("starling_video_id")
        ]
        if not pending_idxs:
            break
        await _set_job_fields(
            db, job_id,
            progress_message=f"等待 Starling 拉取视频 ({len(pending_idxs)} 集未就绪)...",
        )
        # 按 batch_id 分组轮询
        batch_to_idxs: dict[str, list[int]] = defaultdict(list)
        for i in pending_idxs:
            batch_to_idxs[items[i]["upload_batch_id"]].append(i)
        for batch_id, idxs in batch_to_idxs.items():
            try:
                statuses = await client.get_video_upload_status(project_id, batch_id)
            except StarlingRetryableError as exc:
                logger.warning("轮询 upload status 重试: %s", exc)
                continue
            for st in statuses:
                if not st.video_id:
                    continue
                # 用 video_name 匹配回 item
                for i in idxs:
                    if items[i].get("source_filename") and st.video_name and (
                        items[i]["source_filename"] in st.video_name
                        or st.video_name in items[i]["source_filename"]
                    ):
                        items[i]["starling_video_id"] = st.video_id
                        items[i]["upload_status"] = st.status_text
                        break
                else:
                    # 没匹配到 video_name，按顺序填第一个未填的 idx
                    for i in idxs:
                        if not items[i].get("starling_video_id"):
                            items[i]["starling_video_id"] = st.video_id
                            items[i]["upload_status"] = st.status_text
                            break
            await _persist_items(db, job_id, items)
        await asyncio.sleep(interval)
    else:
        raise StarlingRetryableError("Starling 视频上传轮询超时")

    # 检查所有 item 是否都拿到 video_id
    missing = [it for it in items if it.get("upload_batch_id") and not it.get("starling_video_id")]
    if missing:
        raise StarlingRetryableError(f"{len(missing)} 集视频上传未就绪")


async def _create_serial_task(
    db: Database, job_id: str, snapshot: dict, client: StarlingClient
) -> None:
    """VideoProjectSerialTaskCreate。"""
    items: list[dict] = snapshot["items"]
    project_id = snapshot["starling_project_id"]
    await _set_job_fields(db, job_id, progress_message="创建 Starling 完整翻配任务...")

    episodes: list[SerialEpisodeInput] = []
    for it in items:
        if it.get("status") == "failed":
            continue
        if not it.get("starling_video_id"):
            it["status"] = "failed"
            it["error"] = "create_serial_task: 缺少 starling_video_id"
            continue
        source_url = it.get("source_video_url") or _tos_uri_to_public_url(
            it.get("source_tos_uri"), _settings_for_snapshot(snapshot)
        )
        episodes.append(
            SerialEpisodeInput(
                episode=it["episode_number"],
                video_name=it.get("source_filename") or f"ep{it['episode_number']}.mp4",
                video_url=source_url or "",
                video_id=it["starling_video_id"],
            )
        )
    await _persist_items(db, job_id, items)
    if not episodes:
        raise StarlingFatalError("没有可处理的分集（全部上传失败）")

    result = await client.create_serial_task(
        project_id=project_id,
        task_name=f"{snapshot['drama_name']}-{','.join(snapshot['target_langs'])}-{job_id[:8]}",
        source_lang=snapshot["source_lang"],
        target_langs=snapshot["target_langs"],
        episodes=episodes,
        dubbing_enabled=snapshot["dubbing_enabled"],
        subtitle_removal_mode=snapshot["subtitle_removal_mode"],
    )
    # Starling 可能返回多个 task_id（按目标语言分），MVP 取第一个作为主 task_id
    main_task_id = result.task_ids[0]
    await _set_job_fields(
        db, job_id,
        starling_task_id=main_task_id,
        progress_message=f"已创建 Starling 任务 {main_task_id}（共 {len(result.task_ids)} 个）",
    )
    snapshot["starling_task_id"] = main_task_id
    # 把 task_id 写入每个 item 的每个语言 translations
    for it in items:
        if it.get("status") == "failed":
            continue
        it.setdefault("translations", {})
        for lang in snapshot["target_langs"]:
            it["translations"].setdefault(lang, {
                "starling_subtask_id": None,
                "ai_flow_status": "PENDING",
                "submit_status": None,
                "suppression_status": None,
                "products": {},
                "error_message": None,
            })
    await _persist_items(db, job_id, items)


def _settings_for_snapshot(snapshot: dict) -> Settings:
    """快照无法访问 settings，临时获取。"""
    from app.config import Settings as _S
    return _S()


async def _ensure_ai_flow_started(
    db: Database, job_id: str, snapshot: dict, client: StarlingClient
) -> None:
    """条件触发 VideoProjectTaskBatchStartAIFlow。

    先 get_task_detail 判断 subtask 是否已运行；未运行才触发，避免重复计费。
    """
    project_id = snapshot["starling_project_id"]
    task_id = snapshot["starling_task_id"]
    if not task_id:
        return

    subtasks = await client.get_task_detail(project_id, task_id)
    # 不论 subtask 当前状态如何，都尝试触发 AI 流程（Starling 创建后 status=2 但 op_status=0，
    # 需要显式触发才会真正开始处理）。重复触发 Starling 会返回 success，不会重复计费。
    await _set_job_fields(db, job_id, progress_message="触发 Starling AI 流程...")
    subtask_ids = [s.subtask_id for s in subtasks if s.subtask_id]
    if subtask_ids:
        try:
            await client.start_ai_flow(project_id, subtask_ids)
        except StarlingFatalError as exc:
            # 如果是因为已经在运行导致 4xx，忽略
            if "already" in str(exc).lower() or "running" in str(exc).lower():
                logger.info("AI flow already running, skip")
            else:
                raise


async def _wait_for_ai_result(
    db: Database, job_id: str, snapshot: dict, client: StarlingClient, settings: Settings
) -> None:
    """轮询 VideoProjectTaskDetail 直到所有 subtask 到达终态。"""
    project_id = snapshot["starling_project_id"]
    task_id = snapshot["starling_task_id"]
    if not task_id:
        return
    interval = settings.starling_poll_interval_ai_seconds
    deadline = asyncio.get_event_loop().time() + settings.starling_poll_timeout_seconds

    while asyncio.get_event_loop().time() < deadline:
        if _is_aborted(db, job_id):
            raise StarlingFatalError("任务已被停止")
        subtasks: list[SubtaskInfo] = await client.get_task_detail(project_id, task_id)
        # 更新 items 的 translations 状态
        items: list[dict] = snapshot["items"]
        _sync_subtasks_to_items(items, subtasks, snapshot["target_langs"])
        await _persist_items(db, job_id, items)

        terminal = [s for s in subtasks if s.status in (_SUBTASK_STATUS_SUCCEEDED, _SUBTASK_STATUS_FAILED)]
        running = [s for s in subtasks if s.status not in (_SUBTASK_STATUS_SUCCEEDED, _SUBTASK_STATUS_FAILED)]
        await _set_job_fields(
            db, job_id,
            progress_message=f"AI 处理中（{len(terminal)}/{len(subtasks)} 完成）",
        )
        if running:
            await asyncio.sleep(interval)
            continue
        # 全部终态
        failed = [s for s in subtasks if s.status == _SUBTASK_STATUS_FAILED]
        if failed and not any(s.status == _SUBTASK_STATUS_SUCCEEDED for s in subtasks):
            raise StarlingFatalError(f"全部 {len(failed)} 个 subtask AI 处理失败")
        # 至少有一个成功，继续后续步骤
        return
    raise StarlingRetryableError("Starling AI 处理轮询超时")


def _sync_subtasks_to_items(
    items: list[dict], subtasks: list[SubtaskInfo], target_langs: list[str]
) -> None:
    """把 subtask 信息同步到 items_json 的 translations[lang].starling_subtask_id 和 ai_flow_status。"""
    # 按 episode_num + target_language 匹配
    subtask_map: dict[tuple[str, str], SubtaskInfo] = {}
    for s in subtasks:
        subtask_map[(s.episode_num, s.target_language)] = s
    for it in items:
        if it.get("status") == "failed":
            continue
        ep_num = str(it.get("episode_number", ""))
        it.setdefault("translations", {})
        for lang in target_langs:
            t = it["translations"].get(lang)
            if t is None:
                continue
            # 尝试匹配（target_language 可能是 ISO 或英文）
            sub = subtask_map.get((ep_num, lang)) or subtask_map.get((ep_num, lang.upper()))
            if sub:
                t["starling_subtask_id"] = sub.subtask_id
                t["ai_flow_status"] = sub.status_text
                t["suppression_status"] = sub.suppression_status_text
                if sub.status == _SUBTASK_STATUS_FAILED:
                    t["error_message"] = t.get("error_message") or f"AI 处理失败 (status={sub.status})"


async def _submit_subtasks(
    db: Database, job_id: str, snapshot: dict, client: StarlingClient
) -> None:
    """每集每语言 VideoEditorSubmitSubtask（全自动模式）。"""
    items: list[dict] = snapshot["items"]
    await _set_job_fields(db, job_id, progress_message="提交 subtask 校对...")
    for it in items:
        if it.get("status") == "failed":
            continue
        translations = it.get("translations", {})
        for lang, t in translations.items():
            subtask_id = t.get("starling_subtask_id")
            if not subtask_id or t.get("submit_status"):
                continue
            # 如果 AI 处理失败，跳过提交
            if t.get("ai_flow_status") == "FAILED":
                continue
            try:
                await client.submit_subtask(subtask_id)
                t["submit_status"] = "SUBMITTED"
            except StarlingError as exc:
                t["submit_status"] = "FAILED"
                t["error_message"] = f"submit_subtask: {exc}"
                logger.warning("submit_subtask %s failed: %s", subtask_id, exc)
        await _persist_items(db, job_id, items)


async def _start_suppression(
    db: Database, job_id: str, snapshot: dict, client: StarlingClient
) -> None:
    """按目标语言批量 VideoProjectSuppressionStart。"""
    items: list[dict] = snapshot["items"]
    project_id = snapshot["starling_project_id"]
    for lang in snapshot["target_langs"]:
        subtask_ids: list[str] = []
        for it in items:
            if it.get("status") == "failed":
                continue
            t = it.get("translations", {}).get(lang, {})
            sid = t.get("starling_subtask_id")
            if sid and t.get("ai_flow_status") != "FAILED":
                subtask_ids.append(sid)
        if not subtask_ids:
            continue
        await _set_job_fields(
            db, job_id,
            progress_message=f"启动压制（{lang}, {len(subtask_ids)} 集）...",
        )
        try:
            await client.start_suppression(project_id, lang, subtask_ids)
            # 标记每个 subtask 进入压制
            for it in items:
                t = it.get("translations", {}).get(lang)
                if t and t.get("starling_subtask_id") in subtask_ids:
                    t["suppression_status"] = "PROCESSING"
            await _persist_items(db, job_id, items)
        except StarlingError as exc:
            logger.exception("start_suppression failed for lang=%s", lang)
            for it in items:
                t = it.get("translations", {}).get(lang)
                if t and t.get("starling_subtask_id") in subtask_ids:
                    t["suppression_status"] = "FAILED"
                    t["error_message"] = f"start_suppression: {exc}"
            await _persist_items(db, job_id, items)


async def _wait_for_suppression(
    db: Database, job_id: str, snapshot: dict, client: StarlingClient, settings: Settings
) -> None:
    """轮询 VideoProjectTaskDetail 的 SuppressionStatus。"""
    project_id = snapshot["starling_project_id"]
    task_id = snapshot["starling_task_id"]
    if not task_id:
        return
    interval = settings.starling_poll_interval_suppression_seconds
    deadline = asyncio.get_event_loop().time() + settings.starling_poll_timeout_seconds

    while asyncio.get_event_loop().time() < deadline:
        if _is_aborted(db, job_id):
            raise StarlingFatalError("任务已被停止")
        subtasks = await client.get_task_detail(project_id, task_id)
        items: list[dict] = snapshot["items"]
        _sync_subtasks_to_items(items, subtasks, snapshot["target_langs"])
        await _persist_items(db, job_id, items)

        active_langs = set()
        for s in subtasks:
            if s.suppression_status not in (
                _SUPPRESSION_STATUS_SUCCEEDED, _SUPPRESSION_STATUS_FAILED
            ):
                active_langs.add(s.target_language)
        await _set_job_fields(
            db, job_id,
            progress_message=f"压制中（{len(active_langs)} 语言未完成）",
        )
        if not active_langs:
            return
        await asyncio.sleep(interval)
    raise StarlingRetryableError("Starling 压制轮询超时")


async def _fetch_and_archive_products(
    db: Database,
    job_id: str,
    snapshot: dict,
    client: StarlingClient,
    settings: Settings,
    tos: TOSStarlingClient,
) -> None:
    """VideoProjectGetTaskProduct + 下载到本地 + 上传 TOS 归档。"""
    project_id = snapshot["starling_project_id"]
    task_id = snapshot["starling_task_id"]
    if not task_id:
        return
    await _set_job_fields(db, job_id, progress_message="获取产物并归档到 TOS...")

    products: list[ProductArtifact] = await client.get_task_products(project_id, task_id)
    items: list[dict] = snapshot["items"]

    # 按 (episode_num, target_lang) 分组
    grouped: dict[tuple[str, str], list[ProductArtifact]] = defaultdict(list)
    for p in products:
        grouped[(p.episode_num, p.target_lang)].append(p)

    sem = asyncio.Semaphore(settings.starling_product_download_concurrency)

    async def _archive_one(episode_num: str, lang: str, plist: list[ProductArtifact]) -> None:
        async with sem:
            # 找到对应 item
            target_item: dict | None = None
            for it in items:
                if str(it.get("episode_number", "")) == episode_num:
                    target_item = it
                    break
            if target_item is None:
                logger.warning("找不到 episode_num=%s 的 item", episode_num)
                return
            translations = target_item.setdefault("translations", {})
            t = translations.setdefault(lang, {
                "starling_subtask_id": None,
                "ai_flow_status": None,
                "submit_status": None,
                "suppression_status": "SUCCEEDED",
                "products": {},
                "error_message": None,
            })
            products_dict = t.setdefault("products", {})
            for p in plist:
                archive_key = _build_archive_key(
                    settings, snapshot, episode_num, lang, p.artifact_type, p.name
                )
                # 下载到临时文件 -> 上传 TOS（带重试：CDN 偶发不可达）
                tmp_path = Path(tempfile.mkdtemp(prefix=f"starling-{p.artifact_type}-")) / (
                    p.name or f"{p.artifact_type}.bin"
                )
                last_err: Exception | None = None
                for attempt in range(3):
                    try:
                        await asyncio.to_thread(tos.download_url_to_file, p.url, str(tmp_path))
                        await asyncio.to_thread(
                            tos.upload_file,
                            archive_key,
                            str(tmp_path),
                            _content_type_for_artifact(p.artifact_type),
                        )
                        products_dict[f"{p.artifact_type}_tos_uri"] = tos.tos_uri(archive_key)
                        products_dict[f"{p.artifact_type}_public_url"] = tos.public_url(archive_key)
                        products_dict.pop(f"{p.artifact_type}_error", None)
                        last_err = None
                        break
                    except Exception as exc:  # noqa: BLE001
                        last_err = exc
                        logger.warning("归档 %s 第 %d 次失败: %s", p.artifact_type, attempt + 1, exc)
                        await asyncio.sleep(2 ** attempt)
                if last_err is not None:
                    products_dict[f"{p.artifact_type}_error"] = str(last_err)[:300]
                # 清理临时文件
                try:
                    tmp_path.unlink()
                except FileNotFoundError:
                    pass
                try:
                    tmp_path.parent.rmdir()
                except OSError:
                    pass
            await _persist_items(db, job_id, items)

    await asyncio.gather(
        *[_archive_one(ep, lang, plist) for (ep, lang), plist in grouped.items()]
    )


def _build_archive_key(
    settings: Settings,
    snapshot: dict,
    episode_num: str,
    lang: str,
    artifact_type: str,
    filename: str,
) -> str:
    """构造 TOS 归档 key：{prefix}/{job_id}/epYY/{lang}/{artifact_type}/{filename}。"""
    safe_name = (filename or "").strip()
    if not safe_name:
        safe_name = f"{artifact_type}.bin"
    # 取最后一项避免路径穿越
    safe_name = safe_name.replace("\\", "/").split("/")[-1]
    prefix = settings.tos_starling_output_prefix.rstrip("/")
    job_prefix = (snapshot.get("output_tos_prefix") or "").rstrip("/")
    if job_prefix:
        # 截掉 "tos://bucket/" 前缀，只用 key 部分
        if "://" in job_prefix:
            job_prefix = job_prefix.split("/", 3)[-1] if job_prefix.count("/") >= 3 else ""
        return f"{prefix}/{job_prefix}/ep{episode_num}/{lang}/{artifact_type}/{safe_name}"
    return f"{prefix}/ep{episode_num}/{lang}/{artifact_type}/{safe_name}"


def _content_type_for_artifact(artifact_type: str) -> str:
    if artifact_type in ("final_video", "clean_video", "origin_video"):
        return "video/mp4"
    if artifact_type == "dubbed_audio":
        return "audio/mpeg"
    if artifact_type in ("source_subtitle", "target_subtitle"):
        return "application/x-subrip"
    return "application/octet-stream"
