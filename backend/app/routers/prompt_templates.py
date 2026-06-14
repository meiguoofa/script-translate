import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_session, require_passphrase
from app.models import PromptTemplate
from app.schemas import (
    PromptTemplateCreateRequest,
    PromptTemplateOut,
    PromptTemplateUpdateRequest,
)


router = APIRouter(prefix="/prompt-templates", tags=["prompt-templates"])


def _to_out(template: PromptTemplate) -> PromptTemplateOut:
    return PromptTemplateOut(
        id=template.id,
        name=template.name,
        content=template.content,
        is_default=bool(template.is_default),
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


@router.get("", response_model=list[PromptTemplateOut])
async def list_templates(session: AsyncSession = Depends(get_session)) -> list[PromptTemplateOut]:
    rows = await session.scalars(
        select(PromptTemplate).order_by(
            PromptTemplate.is_default.desc(),
            PromptTemplate.created_at.asc(),
        )
    )
    return [_to_out(t) for t in rows]


@router.post(
    "",
    response_model=PromptTemplateOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_passphrase)],
)
async def create_template(
    payload: PromptTemplateCreateRequest,
    session: AsyncSession = Depends(get_session),
) -> PromptTemplateOut:
    name = (payload.name or "").strip()
    content = payload.content or ""
    if not name or not content.strip():
        raise HTTPException(status_code=400, detail="名称与内容均不能为空")
    template = PromptTemplate(
        id=str(uuid.uuid4()),
        name=name,
        content=content,
        is_default=False,
    )
    session.add(template)
    await session.commit()
    await session.refresh(template)
    return _to_out(template)


@router.put(
    "/{template_id}",
    response_model=PromptTemplateOut,
    dependencies=[Depends(require_passphrase)],
)
async def update_template(
    template_id: str,
    payload: PromptTemplateUpdateRequest,
    session: AsyncSession = Depends(get_session),
) -> PromptTemplateOut:
    template = await session.get(PromptTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="提示词不存在")
    if template.is_default:
        raise HTTPException(status_code=400, detail="默认提示词不可编辑")
    if payload.name is not None:
        new_name = payload.name.strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="名称不能为空")
        template.name = new_name
    if payload.content is not None:
        if not payload.content.strip():
            raise HTTPException(status_code=400, detail="内容不能为空")
        template.content = payload.content
    await session.commit()
    await session.refresh(template)
    return _to_out(template)
