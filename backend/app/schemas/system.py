"""
Pydantic schemas for system-level endpoints (setup wizard, health, updates).
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class SetupRequest(BaseModel):
    """Payload for the first-boot setup wizard.

    Creates the first entity, the SUPER_ADMIN user, and the current
    fiscal year with its 12 monthly periods in one atomic transaction.
    """

    entity_code: str = Field(..., min_length=2, max_length=20)
    entity_name: str = Field(..., min_length=1, max_length=150)
    base_currency_code: str = Field(default="IDR", min_length=3, max_length=3)
    admin_email: EmailStr
    admin_full_name: str = Field(..., min_length=1, max_length=150)
    admin_password: str = Field(..., min_length=8, max_length=128)
    fiscal_year: int = Field(..., ge=2000, le=2100)


class SetupResponse(BaseModel):
    """Result of a successful setup."""

    entity_id: UUID
    entity_code: str
    user_id: UUID
    fiscal_year_id: UUID
    periods_created: int
    access_token: str


class SetupStatusResponse(BaseModel):
    """Reports whether the instance has been initialized."""

    is_initialized: bool
