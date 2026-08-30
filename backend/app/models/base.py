"""
SQLAlchemy declarative base and shared column mixins.

All ORM models inherit from ``Base``.  The ``TimestampMixin`` adds
``created_at`` (server-default ``now()``) to any model that uses it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all ApexLedger ORM models."""

    pass


class TimestampMixin:
    """Mixin that adds a ``created_at`` column with server-default ``now()``."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class UUIDPrimaryKeyMixin:
    """Mixin that adds a UUID primary key with database-side default."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
