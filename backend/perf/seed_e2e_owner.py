"""
Seed the single `e2e_owner` account the Playwright suite
(frontend/tests/e2e/) needs to approve/promote other test users via
the API. Separate from perf/seed_users.py (which seeds hundreds of
users for load testing) — this is one account, for correctness tests.

Usage:
    cd backend
    DATABASE_URL=postgresql+asyncpg://... python -m perf.seed_e2e_owner
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.core.config import get_settings
from src.core.security import hash_password
from src.models.enums import Role, UserStatus
from src.models.user import User

E2E_OWNER_USERNAME = "e2e_owner"
E2E_OWNER_PASSWORD = "correct-horse-1"  # noqa: S105 — test-only fixture credential, not a real secret


async def seed() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async with session_factory() as session:
        existing = await session.scalar(select(User).where(User.username == E2E_OWNER_USERNAME))
        if existing is not None:
            print(f"{E2E_OWNER_USERNAME} already exists — nothing to do.")
            return

        session.add(
            User(
                username=E2E_OWNER_USERNAME,
                email=f"{E2E_OWNER_USERNAME}@example.com",
                password_hash=hash_password(E2E_OWNER_PASSWORD),
                status=UserStatus.ACTIVE,
                role=Role.OWNER,
            )
        )
        await session.commit()

    await engine.dispose()
    print(f"Seeded {E2E_OWNER_USERNAME} (Owner, ACTIVE) for the Playwright suite.")


if __name__ == "__main__":
    asyncio.run(seed())
