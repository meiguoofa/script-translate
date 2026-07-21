from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone

from app.config import Settings
from app.db import Database
from app.models import VideoBaiduVodJob
from app.services.baidu_bos_client import BaiduBOSClient
from app.services.baidu_vod_client import BaiduVodClient
from app.services.baidu_vod_governor import BaiduVodGovernor
from app.services.ffmpeg_burn import probe_video_duration_seconds
import httpx

logger = logging.getLogger("baidu_vod_runner")


_persist_locks: dict[str, asyncio.Lock] = {}


def _get_persist_lock(job_id: str) -> asyncio.Lock:
    lock = _persist_locks.get(job_id)
    if lock is None:
        lock = asyncio.Lock()
        _persist_locks[job_id] = lock
    return lock


async def _persist_items(db: Database, job_id: str, items: list[dict]) -> None:
    async with _get_persist_lock(job_id):
        async with await db.session() as session:
            job = await session.get(VideoBaiduVodJob, job_id)
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
    baidu_project_id: str | None = None,
    submitted_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> None:
    async with await db.session() as session:
        job = await session.get(VideoBaiduVodJob, job_id)
        if job is None:
            return
        if status is not None:
            job.status = status
        if progress_message is not None:
            job.progress_message = progress_message
        if error_message is not None:
            job.error_message = error_message
        if baidu_project_id is not None:
            job.baidu_project_id = baidu_project_id
        if submitted_at is not None:
            job.submitted_at = submitted_at
        if completed_at is not None:
            job.completed_at = completed_at
        await session.commit()


async def _load_snapshot(db: Database, job_id: str) -> dict | None:
    async with await db.session() as session:
        job = await session.get(VideoBaiduVodJob, job_id)
        if job is None:
            return None
        return {
            "id": job.id,
            "title": job.title,
            "baidu_project_id": job.baidu_project_id,
            "project_type": job.project_type,
            "source_language": job.source_language,
            "target_langs": json.loads(job.target_langs_json or "[]"),
            "translation_config": json.loads(job.translation_config_json or "{}"),
            "subtitle_config": json.loads(job.subtitle_config_json or "{}"),
            "qps": job.qps,
            "items": json.loads(job.items_json or "[]"),
        }


def _build_translation_config(snapshot: dict, target_lang: str) -> dict:
    """构造 translationConfig(每个 target_lang 一份)。

    百度 VOD API 要求配音模式以 `ttsConfig.type` 嵌套对象传入
    (旧版字段 voiceMode 已被服务端忽略,会导致 speech 翻译流程
    移除原对白音轨但缺失配音,出现对白处静音)。
    """
    cfg = snapshot["translation_config"]
    voice_mode = cfg.get("voiceMode")  # VOICE_CLONE / AI_DUB / None

    # 当选择配音时强制把 speech 加入 translationTypeList,
    # 否则百度仅做字幕翻译不会触发 TTS 流程。
    types = list(cfg.get("translationTypeList") or ["subtitle"])
    if voice_mode and "speech" not in types:
        types.append("speech")

    out: dict[str, object] = {
        "sourceLanguage": snapshot["source_language"],
        "targetLanguage": target_lang,
        "translationTypeList": types,
    }
    if voice_mode:
        tts_config: dict[str, object] = {"type": voice_mode}
        # AI_DUB 必须传 voiceList(百度只支持 1 个音色),结构为对象数组
        # [{"voiceId": "..."}](百度官方文档明确要求,不是字符串数组)。
        # voiceId 必须匹配目标语言,从百度 VOD 控制台音色列表查询。
        voice_list = cfg.get("voiceList")
        if voice_mode == "AI_DUB" and voice_list:
            tts_config["voiceList"] = [{"voiceId": vid} for vid in voice_list]
        out["ttsConfig"] = tts_config
    return out


async def _probe_video_duration_seconds(url: str) -> float:
    """ffprobe 探公网 URL 视频时长。失败返回 0。"""
    try:
        return await asyncio.to_thread(probe_video_duration_seconds, url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("probe duration failed for %s: %s", url[:80], exc)
        return 0.0


async def _run_episode(
    db: Database,
    job_id: str,
    vod: BaiduVodClient,
    settings: Settings,
    snapshot: dict,
    items: list[dict],
    index: int,
    *,
    governor: BaiduVodGovernor,
) -> None:
    """单集流水线:fetch_media(跨语言共享)-> 每语言 submit_translation_tasks -> wait -> 取结果。"""
    async with governor.episode_slot():
        item = items[index]
        try:
            await _run_episode_impl(db, job_id, vod, settings, snapshot, items, index)
        except Exception as exc:  # noqa: BLE001
            logger.exception("_run_episode %s/%d top-level error", job_id, index)
            item["status"] = "failed"
            item["error"] = f"未捕获异常: {exc}"[:1000]
            try:
                await _persist_items(db, job_id, items)
            except Exception:  # noqa: BLE001
                logger.exception("persist failed after top-level error %s/%d", job_id, index)


async def _run_episode_impl(
    db: Database,
    job_id: str,
    vod: BaiduVodClient,
    settings: Settings,
    snapshot: dict,
    items: list[dict],
    index: int,
) -> None:
    item = items[index]
    input_oss_uri = item["input_oss_uri"]
    input_public_url = item["input_public_url"]
    target_langs: list[str] = snapshot["target_langs"]
    force_reregister = bool(snapshot.get("force_reregister", False))

    if not isinstance(item.get("translations"), dict):
        item["translations"] = {}

    # 生成 presigned GET URL:认证请求,比 unsigned public_url 更稳健,
    # 走 BOS 认证路径。24h 有效期远大于 fetch 总耗时。
    bos_key = item.get("input_bos_key")
    fetch_url = input_public_url
    if bos_key:
        try:
            bos_client = BaiduBOSClient(settings)
            fetch_url = bos_client.presign_get(bos_key, expires_in=86400)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "presign_get failed for %s, fallback to public_url: %s",
                bos_key, exc,
            )

    # ===== 阶段 0: 探测视频时长 =====
    if not item.get("duration_seconds"):
        duration = await _probe_video_duration_seconds(fetch_url)
        item["duration_seconds"] = duration
        await _persist_items(db, job_id, items)

    # ===== 阶段 1: 拉取上传到 VOD 媒资库(跨语言共享,只做一次)=====
    if item.get("baidu_media_id") and not force_reregister:
        logger.info("skip fetch_media %s/%d, reuse media_id=%s",
                    job_id, index, item["baidu_media_id"])
    else:
        item["stage"] = "fetching"
        item["status"] = "running"
        item["error"] = None
        await _persist_items(db, job_id, items)
        try:
            fetch_result = await vod.fetch_media(
                source_url=fetch_url,
                name=f"{job_id[:8]}-d{item.get('drama_index', 0):02d}-e{item.get('episode_index', 0):02d}",
                delete_after_seconds=86400 * 30,  # 30 天后自动删
            )
            item["baidu_upload_task_id"] = fetch_result.task_id
            await _persist_items(db, job_id, items)
            # 轮询拿 mediaId
            media_id = await vod.wait_for_fetch_media(
                fetch_result.task_id,
                poll_interval=10,
                timeout=settings.baidu_vod_poll_timeout_seconds,
            )
            item["baidu_media_id"] = media_id
            await _persist_items(db, job_id, items)
        except Exception as exc:  # noqa: BLE001
            logger.exception("fetch_media %s/%d failed", job_id, index)
            item["status"] = "failed"
            item["error"] = f"拉取上传失败: {exc}"[:500]
            await _persist_items(db, job_id, items)
            return

    media_id = item["baidu_media_id"]
    project_id = snapshot["baidu_project_id"]

    # ===== 阶段 2: 每语言循环提交翻译任务 + 轮询 =====
    item["stage"] = "translating"
    item["status"] = "running"
    await _persist_items(db, job_id, items)

    for lang in target_langs:
        t = item["translations"].setdefault(lang, {})
        # 复用已有成功 task
        if t.get("baidu_task_id") and t.get("status") == "SUCCESS":
            logger.info("skip translate %s/%d/%s, reuse task=%s",
                        job_id, index, lang, t["baidu_task_id"])
            continue
        # 复用已有失败 task 的 media_id,重新提交新 task
        t["stage"] = "submitting"
        t["status"] = "running"
        t["error"] = None
        await _persist_items(db, job_id, items)
        try:
            translation_config = _build_translation_config(snapshot, lang)
            subtitle_config = snapshot["subtitle_config"]
            task_results = await vod.submit_translation_tasks(
                project_id=project_id,
                media_id_list=[media_id],
                translation_config=translation_config,
                subtitle_config=subtitle_config,
            )
            if not task_results:
                raise RuntimeError("submit_translation_tasks 返回空")
            tr = task_results[0]
            t["baidu_task_id"] = tr.task_id
            await _persist_items(db, job_id, items)

            # 轮询到终态
            t["stage"] = "translating"
            await _persist_items(db, job_id, items)
            final = await vod.wait_for_task(
                project_id, tr.task_id,
                poll_interval=settings.baidu_vod_poll_interval_seconds,
                timeout=settings.baidu_vod_poll_timeout_seconds,
            )
            t["status"] = final.status
            t["final_video_url"] = final.url
            t["desubtitle_video_url"] = final.desubtitle_url
            t["cover_url"] = final.cover_url
            t["source_srt_url"] = final.source_srt_url
            t["target_srt_url"] = final.target_srt_url
            t["stage"] = "done"
            t["error"] = None
            await _persist_items(db, job_id, items)
        except Exception as exc:  # noqa: BLE001
            logger.exception("translation %s/%d/%s failed", job_id, index, lang)
            t["status"] = "failed"
            t["stage"] = "done"
            t["error"] = f"翻译失败: {exc}"[:500]
            await _persist_items(db, job_id, items)

    # ===== 汇总 item 级状态 =====
    statuses = [t.get("status") for t in item["translations"].values()]
    if statuses and all(s == "SUCCESS" for s in statuses):
        item["status"] = "succeeded"
        item["stage"] = "done"
        item["error"] = None
    elif any(s == "SUCCESS" for s in statuses):
        item["status"] = "partial"
        item["stage"] = "done"
        errors = [t.get("error") for t in item["translations"].values()
                  if t.get("status") == "failed"]
        item["error"] = "; ".join(e for e in errors if e)[:500]
    else:
        item["status"] = "failed"
        item["stage"] = "done"
        errors = [t.get("error") for t in item["translations"].values()
                  if t.get("status") == "failed"]
        item["error"] = "; ".join(e for e in errors if e)[:500]
    await _persist_items(db, job_id, items)


async def run_baidu_vod_job(
    db: Database,
    settings: Settings,
    governor: BaiduVodGovernor,
    job_id: str,
    *,
    only_indices: list[int] | None = None,
) -> None:
    """后台任务入口:编排多剧 + 单剧顺序。"""
    snapshot = await _load_snapshot(db, job_id)
    if snapshot is None:
        logger.warning("baidu-vod job %s 不存在,跳过", job_id)
        return

    async with governor.job_slot():
        try:
            vod = BaiduVodClient(settings, governor)
        except RuntimeError as exc:
            await _set_job_fields(
                db, job_id, status="failed", error_message=str(exc),
                completed_at=datetime.now(timezone.utc),
            )
            return

        # 创建 project(如果还没有)
        project_id = snapshot["baidu_project_id"]
        if not project_id:
            try:
                proj = await vod.create_project(
                    name=snapshot["title"],
                    description=f"job {job_id}",
                    project_type=snapshot["project_type"],
                )
                project_id = proj.project_id
                await _set_job_fields(db, job_id, baidu_project_id=project_id)
                snapshot["baidu_project_id"] = project_id
            except Exception as exc:  # noqa: BLE001
                logger.exception("create_project %s failed", job_id)
                await _set_job_fields(
                    db, job_id, status="failed",
                    error_message=f"创建项目失败: {exc}"[:500],
                    completed_at=datetime.now(timezone.utc),
                )
                return

        items: list[dict] = snapshot["items"]
        indices = only_indices if only_indices is not None else list(range(len(items)))
        if not indices:
            logger.warning("baidu-vod job %s 无可处理的 item", job_id)
            return

        dramas: dict[int, list[int]] = defaultdict(list)
        for idx in indices:
            dramas[items[idx].get("drama_index", 0)].append(idx)

        await _set_job_fields(
            db, job_id, status="running",
            progress_message=f"开始处理 {len(dramas)} 部剧 / {len(indices)} 集",
            submitted_at=datetime.now(timezone.utc),
        )

        async def _run_drama(drama_index: int, episode_indices: list[int]) -> None:
            await asyncio.gather(
                *(
                    _run_episode(
                        db,
                        job_id,
                        vod,
                        settings,
                        snapshot,
                        items,
                        ep_idx,
                        governor=governor,
                    )
                    for ep_idx in episode_indices
                )
            )

        try:
            await asyncio.gather(*(_run_drama(di, eidx) for di, eidx in dramas.items()))
        except Exception as exc:  # noqa: BLE001
            logger.exception("run_baidu_vod_job %s top-level error", job_id)
            await _set_job_fields(
                db, job_id, status="failed",
                error_message=f"未捕获异常: {exc}"[:1000],
                progress_message="任务异常终止",
                completed_at=datetime.now(timezone.utc),
            )
            return

        succeeded = sum(1 for it in items if it.get("status") == "succeeded")
        failed = sum(1 for it in items if it.get("status") == "failed")
        partial = sum(1 for it in items if it.get("status") == "partial")
        overall = "completed" if succeeded > 0 or partial > 0 else "failed"
        await _set_job_fields(
            db, job_id, status=overall,
            progress_message=f"成功 {succeeded}/{len(items)},部分 {partial},失败 {failed}",
            completed_at=datetime.now(timezone.utc),
        )
