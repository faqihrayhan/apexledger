"""
Pydantic schemas for authentication request/response payloads.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    """Payload for creating a new user account."""

    entity_id: UUID
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=150)
    password: str = Field(..., min_length=8, max_length=128)
    role: str = Field(default="FINANCE_OPERATOR")


class RegisterResponse(BaseModel):
    """Returned after successful registration."""

    user_id: UUID
    email: str
    full_name: str
    access_token: str


class LoginRequest(BaseModel):
    """Credentials for obtaining a JWT."""

    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    """JWT token returned on successful login."""

    access_token: str
    token_type: str = "bearer"
    user_id: UUID
    role: str


class UserProfileResponse(BaseModel):
    """Minimal user profile extracted from JWT claims."""

    user_id: str
    entity_id: str
    role: str
