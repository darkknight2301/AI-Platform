"""Authentication endpoints: register, login, logout, current-user profile."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user
from src.core.security import decode_access_token
from src.db.session import get_db
from src.models.user import User
from src.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserPublic
from src.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest, request: Request, session: AsyncSession = Depends(get_db)
) -> User:
    request_id = getattr(request.state, "request_id", None)
    return await auth_service.register_user(session, payload, request_id=request_id)


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest, request: Request, session: AsyncSession = Depends(get_db)
) -> TokenResponse:
    request_id = getattr(request.state, "request_id", None)
    _, token, expires_at = await auth_service.authenticate(
        session,
        payload,
        request_id=request_id,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    return TokenResponse(access_token=token, expires_at=expires_at)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> None:
    request_id = getattr(request.state, "request_id", None)
    jti = getattr(request.state, "auth_jti", None)
    if jti is None:
        # Defensive: get_current_user always sets this on success, but
        # decode again rather than trust request.state blindly.
        auth_header = request.headers.get("authorization", "")
        token = auth_header.removeprefix("Bearer ").strip()
        payload = decode_access_token(token) if token else None
        jti = payload.get("jti") if payload else None
    await auth_service.logout(
        session, user_id=current_user.id, jti=jti, request_id=request_id
    )


@router.get("/me", response_model=UserPublic)
async def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
