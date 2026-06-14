from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import get_settings
from app.schemas import AccessVerifyRequest, AccessVerifyResponse


router = APIRouter(prefix="/access", tags=["access"])


@router.post("/verify", response_model=AccessVerifyResponse)
async def verify(payload: AccessVerifyRequest, settings=Depends(get_settings)) -> AccessVerifyResponse:
    expected = (settings.access_passphrase or "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="后端 ACCESS_PASSPHRASE 未配置",
        )
    if (payload.passphrase or "").strip() != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="访问密钥不正确")
    return AccessVerifyResponse(ok=True)
