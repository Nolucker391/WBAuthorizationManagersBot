import asyncpg

from contextlib import asynccontextmanager
from configuration_bot.settings import config


@asynccontextmanager
async def get_db_connection():
    conn = await asyncpg.connect(
        user=config.PG_USER,
        password=config.PG_PASSWORD.get_secret_value(),
        database=config.PG_DB_INTERNAL,
        host=config.PG_HOST.get_secret_value(),
        port=config.PG_PORT
    )
    try:
        yield conn
    finally:
        await conn.close()


@asynccontextmanager
async def get_db_driver_connection():
    conn = await asyncpg.connect(
        user='analitycs_user',
        password='solutionti432muralmirka827',
        database='driver_fence',
        host='91.105.198.24',
        port=5433
    )
    try:
        yield conn
    finally:
        await conn.close()