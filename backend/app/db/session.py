"""
Async SQLAlchemy engine, session factory, and RLS context injection.

Every request that touches the database goes through ``get_db()``, which:
1. Acquires a connection from the async pool.
2. Injects JWT claims into the PostgreSQL session via ``SET LOCAL`` so
   that RLS policies and ``fn_current_*()`` helpers can evaluate the
   caller's identity without any application-level filtering.
3. Yields an ``AsyncSession`` to the route handler.
4. Commits on success, rolls back on exception, and returns the
   connection to the pool.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

engine = create_async_engine(
    str(settings.database_url),
    echo=settings.debug,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def inject_rls_context(session: AsyncSession, claims: dict[str, Any]) -> None:
    """Inject JWT claims into the PostgreSQL session for RLS evaluation.

    After this call, PL/pgSQL helpers ``fn_current_role()`` and
    ``fn_current_entity_id()`` can read the values via
    ``current_setting('jwt.claims.<key>', true)``.
    """
    await session.execute(
        text("SELECT set_config('jwt.claims.user_id', :uid, true)"),
        {"uid": str(claims["user_id"])},
    )
    await session.execute(
        text("SELECT set_config('jwt.claims.entity_id', :eid, true)"),
        {"eid": str(claims["entity_id"])},
    )
    await session.execute(
        text("SELECT set_config('jwt.claims.role', :role, true)"),
        {"role": claims["role"]},
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that provides an async database session.

    Usage in a route::

        @router.post("/journals")
        async def create_journal(db: AsyncSession = Depends(get_db)):
            ...

    RLS context injection is handled separately by the auth middleware
    (see ``app.api.deps``), because the raw ``get_db`` dependency does
    not know about the current user's JWT claims.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
