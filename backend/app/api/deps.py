"""
Dependencies shared across API v1 routes.

Provides the ``get_db_with_rls`` dependency that combines database
session acquisition with RLS context injection from the current JWT.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends

from app.core.security import get_current_user
from app.db.session import async_session_factory, inject_rls_context

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from sqlalchemy.ext.asyncio import AsyncSession


async def get_db_with_rls(
    current_user: dict = Depends(get_current_user),
) -> AsyncGenerator[AsyncSession, None]:
    """Yield an ``AsyncSession`` with JWT claims injected for RLS.

    This is the primary dependency for any route that reads or writes
    business data.  The PostgreSQL session variables are set via
    ``SET LOCAL``, scoping them to the current transaction.
    """
    async with async_session_factory() as session:
        try:
            await inject_rls_context(session, current_user)
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
