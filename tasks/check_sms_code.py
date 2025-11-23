from utils.selenium_dop_bot_utils.workers_db_selenium import get_db_connection
from configuration_bot.settings import get_logger

logger = get_logger()


async def check_sms_code_requests(user_id: str):
    async with get_db_connection() as conn:
        row = await conn.fetchrow("""
            SELECT sms_code FROM auth_user
            WHERE chat_id = $1 AND sms_code IS NOT NULL
        """, user_id)

        if row:
            return row['sms_code']
        return None


async def clear_sms_code(chat_id: str):
    async with get_db_connection() as conn:
        await conn.execute("""
            UPDATE auth_user
            SET sms_code = NULL
            WHERE chat_id = $1
        """, chat_id)


async def write_sms_code(chat_id: int | str, sms_code: str, code_iteration: int):
    """
    Асинхронно записывает SMS-код в базу данных.
    """
    async with get_db_connection() as conn:
        try:
            result = await conn.execute("""
                UPDATE auth_user
                SET sms_code = $1, code_iteration = $2
                WHERE chat_id = $3
            """, int(sms_code), int(code_iteration), str(chat_id))
            logger.info(f"write_sms_code - Обновлено строк: {result}")
        except Exception as e:
            logger.info(f"write_sms_code - Ошибка при записи: {e}")


async def get_next_code_iteration(chat_id: int) -> int:
    async with get_db_connection() as conn:
        try:
            result = await conn.fetchrow("""
                SELECT code_iteration FROM auth_user
                WHERE chat_id = $1
            """, str(chat_id))
            current = result['code_iteration'] if result and result['code_iteration'] is not None else 0
            return current + 1
        except Exception as e:
            logger.info(f"get_next_code_iteration - Ошибка: {e}")
            return 1

