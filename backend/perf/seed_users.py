"""
Seed 500+ ACTIVE users (plus one Owner) directly in the database for
load-test runs, bypassing the register->approve HTTP flow entirely —
running that flow 500 times just to get into a state to load-test
*other* endpoints would be its own (unrelated) bottleneck. This script
intentionally talks to the DB directly, not the API.

Usage:
    cd backend
    DATABASE_URL=postgresql+asyncpg://... python -m perf.seed_users --count 500
"""
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.core.config import get_settings
from src.core.security import hash_password
from src.models.enums import GroupStatus, Role, UserStatus
from src.models.group import Group
from src.models.user import User

LOAD_TEST_PASSWORD = "correct-horse-1"


async def seed(count: int) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async with session_factory() as session:
        group = Group(name="loadtest-group", status=GroupStatus.ACTIVE)
        session.add(group)
        await session.flush()

        owner = User(
            username="loadtest_owner",
            email="loadtest_owner@example.com",
            password_hash=hash_password(LOAD_TEST_PASSWORD),
            status=UserStatus.ACTIVE,
            role=Role.OWNER,
        )
        session.add(owner)

        for i in range(count):
            session.add(
                User(
                    username=f"loadtest_seed_{i}",
                    email=f"loadtest_seed_{i}@example.com",
                    password_hash=hash_password(LOAD_TEST_PASSWORD),
                    status=UserStatus.ACTIVE,
                    role=Role.USER,
                    group_id=group.id,
                )
            )
            if i % 100 == 0:
                await session.flush()  # keep a single transaction from growing unbounded

        await session.commit()

    await engine.dispose()
    print(f"Seeded {count} ACTIVE users + 1 Owner (loadtest_owner) for load testing.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=500)
    args = parser.parse_args()
    asyncio.run(seed(args.count))
