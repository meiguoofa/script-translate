import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.deps import get_registry, get_session, get_settings
from app.models import Script, TranslationLine, TranslationVersion
from app.schemas import TranslateRequest, TranslationDetail, TranslationVersionResponse
from app.services.translator import TranslationContext, run_translation


router = APIRouter(tags=["translations"])


@router.post(
    "/scripts/{script_id}/translate",
    response_model=TranslationVersionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def translate_script(
    script_id: str,
    payload: TranslateRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings=Depends(get_settings),
    registry=Depends(get_registry),
) -> TranslationVersionResponse:
    script = await session.get(Script, script_id)
    if script is None:
        raise HTTPException(status_code=404, detail="Script not found.")

    version = TranslationVersion(
        id=str(uuid.uuid4()),
        script_id=script_id,
        target_lang=payload.target_lang,
        model_provider=payload.provider,
        model_name=payload.model,
        status="running",
        prompt_version=settings.prompt_version,
    )
    session.add(version)
    await session.commit()

    async def run_in_new_session() -> None:
        state = request.app.state
        async with await state.db.session() as background_session:
            await run_translation(
                background_session,
                version.id,
                TranslationContext(settings=state.settings, registry=state.registry),
            )

    background_tasks.add_task(run_in_new_session)
    return TranslationVersionResponse(version_id=version.id, status=version.status)


@router.get("/translations/{version_id}", response_model=TranslationDetail)
async def get_translation(version_id: str, session: AsyncSession = Depends(get_session)) -> TranslationDetail:
    version = await session.scalar(
        select(TranslationVersion)
        .where(TranslationVersion.id == version_id)
        .options(selectinload(TranslationVersion.lines).selectinload(TranslationLine.line))
    )
    if version is None:
        raise HTTPException(status_code=404, detail="Translation version not found.")

    rendered_lines = [
        line.rendered_line
        for line in sorted(version.lines, key=lambda item: item.line.line_no if item.line else 0)
    ]
    return TranslationDetail(
        id=version.id,
        script_id=version.script_id,
        target_lang=version.target_lang,
        model_provider=version.model_provider,
        model_name=version.model_name,
        status=version.status,
        prompt_version=version.prompt_version,
        total_tokens=version.total_tokens,
        cost=float(version.cost) if version.cost is not None else None,
        duration_ms=version.duration_ms,
        error_message=version.error_message,
        created_at=version.created_at,
        rendered_lines=rendered_lines,
    )
