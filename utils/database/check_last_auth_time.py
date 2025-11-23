from datetime import datetime, timedelta, timezone
from utils.database.get_async_session_db import get_db_connection


async def check_last_auth_time(chat_id: str) -> tuple[bool, str]:
    async with get_db_connection() as conn:
        row = await conn.fetchrow("""
            SELECT last_auth_try_time
            FROM auth_user
            WHERE chat_id = $1
        """, chat_id)

        if row is None or row["last_auth_try_time"] is None:
            return True, ""

        last_time = row["last_auth_try_time"].replace(tzinfo=timezone.utc)
        now_time = datetime.utcnow().replace(tzinfo=timezone.utc)

        diff = now_time - last_time
        required_wait = timedelta(minutes=5)

        if diff >= required_wait:
            return True, ""
        else:
            remaining = required_wait - diff
            total_seconds = int(remaining.total_seconds())
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            wait_str = f"{minutes} минут {round(seconds)} сек" if minutes else f"{round(seconds)} сек"
            return False, wait_str
