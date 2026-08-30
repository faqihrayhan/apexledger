"""
Authentication routes: register, login, token refresh, and profile.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.db.session import get_db
from app.models.layer0 import RoleEnum, UserProfile
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
    UserProfileResponse,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Create a new user account.

    During the setup wizard (first boot), the first user is
    automatically assigned ``SUPER_ADMIN``.
    """
    # Validate the role string against the RoleEnum (rejects unknown roles with 422)
    try:
        role_enum = RoleEnum(payload.role)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid role: {payload.role}.",
        ) from None

    # Check for duplicate email
    existing = await db.execute(
        select(UserProfile).where(UserProfile.email == payload.email)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists.",
        )

    user = UserProfile(
        entity_id=payload.entity_id,
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=role_enum,
    )
    db.add(user)
    await db.flush()

    token = create_access_token(
        user_id=user.id,
        entity_id=user.entity_id,
        role=role_enum.value,
    )

    return RegisterResponse(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        access_token=token,
    )


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate with email and password, returns a JWT."""
    result = await db.execute(
        select(UserProfile).where(UserProfile.email == payload.email)
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Contact your administrator.",
        )

    # SQLAlchemy returns a RoleEnum here (loaded from DB); handle both shapes defensively.
    role_value = user.role.value if isinstance(user.role, RoleEnum) else str(user.role)

    token = create_access_token(
        user_id=user.id,
        entity_id=user.entity_id,
        role=role_value,
    )

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        user_id=user.id,
        role=role_value,
    )


@router.get("/me", response_model=UserProfileResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
    """Return the current user's profile from the JWT claims."""
    return UserProfileResponse(
        user_id=current_user["user_id"],
        entity_id=current_user["entity_id"],
        role=current_user["role"],
    )
