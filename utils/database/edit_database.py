from utils.database.get_async_session_db import get_db_connection

from configuration_bot.settings import get_logger

logger = get_logger()


# async def clear_db_auth_user(user_id: str | int):
#     """
#     Асинхронно удаляет пользователя из базы данных и освобождает selenium-процесс, если он был назначен.
#     """
#     async with get_db_connection() as conn:
#         try:
#             # Удаляем пользователя
#             await conn.execute("""
#                 DELETE FROM auth_user WHERE chat_id = CAST($1 AS VARCHAR(50))
#             """, str(user_id))
#
#             logger.info(f"Пользователь полностью удалён: chat_id = {user_id}")
#
#         except Exception as e:
#             logger.error(f"Ошибка при удалении: {e}")
async def clear_db_auth_user(user_id: str | int):
    """
    Асинхронно очищает все данные пользователя, кроме chat_id,
    и освобождает selenium-процесс, если он был назначен.
    """
    async with get_db_connection() as conn:
        try:
            # Получаем selenium_id, если он был
            selenium_id = await conn.fetchval("""
                SELECT selenium_id FROM auth_user WHERE chat_id = CAST($1 AS VARCHAR(50))
            """, str(user_id))

            # Освобождаем selenium-процесс, если он был
            if selenium_id:
                await conn.execute("""
                    UPDATE selenium_process SET is_busy = FALSE WHERE process_id = $1
                """, selenium_id)

            # Обнуляем все поля кроме chat_id
            await conn.execute("""
                UPDATE auth_user SET
                    wp_email = NULL,
                    phone_number = NULL,
                    wp_id = NULL,
                    wp_date = NULL,
                    wp_name = NULL,
                    wp_role = NULL,
                    captcha = NULL,
                    captcha_iteration = NULL,
                    sms_code = NULL,
                    code_iteration = NULL,
                    last_parsing_date = NULL,
                    cookies = NULL,
                    auth_token = NULL,
                    auth_state = NULL,
                    selenium_id = NULL,
                    is_verified = FALSE,
                    proxy_name = NULL,
                    proxy_id = NULL,
                    user_agent = NULL
                WHERE chat_id = CAST($1 AS VARCHAR(50))
            """, str(user_id))

            logger.info(f"Данные пользователя очищены, chat_id и last_auth_try_time сохранён: {user_id}")

        except Exception as e:
            logger.error(f"Ошибка при очистке данных пользователя: {e}")


async def get_auth_user_info(user_id: str | int) -> dict | None:
    """
    Асинхронно получает phone_number и wb_email по chat_id из базы данных.
    """
    async with get_db_connection() as conn:
        try:
            result = await conn.fetchrow("""
                SELECT phone_number, wp_email FROM auth_user WHERE chat_id = CAST($1 AS VARCHAR(50))
            """, str(user_id))
            if result:
                return dict(result)
            return None
        except Exception as e:
            logger.error(f"Ошибка при получении данных пользователя: {e}")
            return None

