from fastapi import APIRouter, Depends

from app.deps import get_registry
from app.schemas import ModelOption


router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=list[ModelOption])
async def list_models(registry=Depends(get_registry)) -> list[ModelOption]:
    return [ModelOption(**model.to_dict()) for model in registry.list_models()]
