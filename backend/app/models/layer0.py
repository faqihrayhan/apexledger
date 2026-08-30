"""
Layer 0 — Foundational models: Entity (tenant), UserProfile, SystemLog.

These tables are created before any business module and form the basis
of multi-tenancy, identity, and immutable audit logging.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RoleEnum(enum.StrEnum):
    """Application-level roles enforced by RLS policies."""

    SUPER_ADMIN = "SUPER_ADMIN"
    IT_ADMIN = "IT_ADMIN"
    DEPT_HEAD_SALES = "DEPT_HEAD_SALES"
    DEPT_HEAD_WAREHOUSE = "DEPT_HEAD_WAREHOUSE"
    DEPT_HEAD_FA = "DEPT_HEAD_FA"
    SALES_OPERATOR = "SALES_OPERATOR"
    WAREHOUSE_OPERATOR = "WAREHOUSE_OPERATOR"
    FINANCE_OPERATOR = "FINANCE_OPERATOR"


# ---------------------------------------------------------------------------
# Entity (tenant / branch / holding company)
# ---------------------------------------------------------------------------


class Entity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Represents a company, branch, or holding entity.

    Supports hierarchical structures via ``parent_entity_id`` for
    intercompany consolidation scenarios.
    """

    __tablename__ = "entities"

    parent_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("entities.id"),
        nullable=True,
    )
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    base_currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    children: Mapped[list[Entity]] = relationship("Entity", back_populates="parent")
    parent: Mapped[Entity | None] = relationship(
        "Entity", back_populates="children", remote_side="Entity.id"
    )
    user_profiles: Mapped[list[UserProfile]] = relationship(back_populates="entity")


# ---------------------------------------------------------------------------
# UserProfile
# ---------------------------------------------------------------------------


class UserProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Local user profile with role and entity assignment.

    The ``id`` doubles as the user's authentication identifier.  In the
    on-premise model, passwords are stored locally (hashed with Argon2)
    and validated by FastAPI — there is no external auth provider.
    """

    __tablename__ = "user_profiles"

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("entities.id"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[RoleEnum] = mapped_column(
        Enum(RoleEnum, name="role_enum", create_type=True),
        nullable=False,
    )
    department_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    force_password_reset: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    entity: Mapped[Entity] = relationship(back_populates="user_profiles")


# ---------------------------------------------------------------------------
# SystemLog (immutable audit trail)
# ---------------------------------------------------------------------------


class SystemLog(Base):
    """Immutable audit log entry.

    Every write operation across all modules must create a log entry.
    ``UPDATE`` and ``DELETE`` are revoked at the database level to
    guarantee immutability — this is enforced in the Alembic migration
    that creates the table.
    """

    __tablename__ = "system_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("entities.id"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    table_name: Mapped[str] = mapped_column(String(100), nullable=False)
    record_id: Mapped[str] = mapped_column(Text, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    before_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
