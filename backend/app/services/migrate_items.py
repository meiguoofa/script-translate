"""启动时迁移旧 subtitle-erase job 的 items_json 到 translations 嵌套结构。

旧结构: items_json 内每个 item 是扁平字段(translated_srt_oss_uri, output_video_oss_uri 等),
        job 级 target_lang 是单字段。
新结构: items_json 内每个 item 有 translations: {lang: {translated_srt_oss_uri, output_video_oss_uri, ...}},
        job 级 target_langs_json 是 JSON 数组。

迁移逻辑:
1. job.target_langs_json 为空/[] 时,从旧 target_lang 推导为 [target_lang]
2. item 没有 translations 字段时,把扁平的翻译/烧录产物挪到 translations[旧 target_lang] 下
3. 保留跨语言共享产物(clean_video_oss_uri, source_srt_oss_uri, cleaned_srt_oss_uri 等)在 item 顶层

迁移幂等:已有 translations 字段的 item 跳过。失败仅日志告警,不阻塞启动。
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import select

from app.db import Database
from app.models import VideoSubtitleEraseJob
from app.services.subtitle_erase_translate_runner import TRANSLATION_FIELDS

logger = logging.getLogger("migrate_items")


async def migrate_items_to_translations(db: Database) -> int:
    """启动时迁移旧 items_json 到 translations 嵌套结构。返回迁移的 job 数。"""

    total = 0
    async with await db.session() as session:
        result = await session.execute(select(VideoSubtitleEraseJob))
        for job in result.scalars():
            migrated = _migrate_one_job(job)
            if migrated:
                total += 1
        if total:
            await session.commit()
    if total:
        logger.info("迁移了 %d 个旧 subtitle-erase job 到 translations 嵌套结构", total)
    return total


def _migrate_one_job(job: VideoSubtitleEraseJob) -> bool:
    """迁移单个 job。返回是否有改动。"""

    changed = False

    # 1. target_langs_json 兜底
    langs: list[str] = []
    if job.target_langs_json:
        try:
            parsed = json.loads(job.target_langs_json)
            if isinstance(parsed, list):
                langs = [str(x) for x in parsed if str(x).strip()]
        except json.JSONDecodeError:
            logger.warning("job %s 非法 target_langs_json: %s", job.id, job.target_langs_json)
    if not langs and job.target_lang:
        langs = [job.target_lang]
        job.target_langs_json = json.dumps(langs, ensure_ascii=False)
        changed = True
    if not langs:
        # 没有目标语言信息,无法迁移 translations,跳过
        return changed

    # 2. items_json 迁移
    try:
        items = json.loads(job.items_json or "[]")
    except json.JSONDecodeError:
        logger.warning("job %s 非法 items_json,跳过迁移", job.id)
        return changed

    primary_lang = langs[0]
    for it in items:
        if not isinstance(it, dict):
            continue
        if isinstance(it.get("translations"), dict) and it["translations"]:
            # 已迁移过,跳过
            continue
        # 收集扁平的翻译/烧录产物
        t: dict = {}
        for f in TRANSLATION_FIELDS:
            v = it.get(f)
            if v is not None:
                t[f] = v
            # 从 item 顶层删除(已挪到 translations)
            if f in it:
                del it[f]
        # item 级状态挪到 translations[primary_lang]
        if "stage" in it:
            t["stage"] = it["stage"]
        if "status" in it:
            t["status"] = it["status"]
        if "error" in it and it.get("error"):
            t["error"] = it["error"]
        if t:
            it["translations"] = {primary_lang: t}
        else:
            it["translations"] = {}
        # 清理 item 顶层的 error/warning(warning 保留在顶层因为是跨语言共享)
        it["error"] = None
        # 确保 clean_video_public_url 存在(新字段,旧数据没有)
        if it.get("clean_video_oss_uri") and not it.get("clean_video_public_url"):
            # 迁移期无法精确算 public_url(需要 OSS endpoint),留空,runner 会兜底
            pass
        changed = True

    if changed:
        job.items_json = json.dumps(items, ensure_ascii=False)
    return changed
