from utils.database.get_async_session_db import get_db_connection

from configuration_bot.settings import get_logger

logger = get_logger()


async def get_last_request_time(phone_number: str, type_request: str) -> str | None:
    """
    Получает дату последнего запроса по номеру телефона.

    wb_prepayment
    ozon_prepayment
    ymarket_prepayment
    """
    async with get_db_connection() as conn:
        try:
            if type_request == "wb_prepayment":
                result = await conn.fetchrow("""
                    SELECT last_request_time_wb_prepayment FROM request_log WHERE phone_number = $1
                """, phone_number)
                return result['last_request_time_wb_prepayment'] if result else None
            elif type_request == "ozon_prepayment":
                result = await conn.fetchrow("""
                                    SELECT last_request_time_ozon FROM request_log WHERE phone_number = $1
                                """, phone_number)
                return result['last_request_time_ozon'] if result else None
            elif type_request == "ymarket_prepayment":
                result = await conn.fetchrow("""
                                   SELECT last_request_time_ym FROM request_log WHERE phone_number = $1
                               """, phone_number)
                return result['last_request_time_ym'] if result else None
        except Exception as e:
            logger.error(f"Ошибка при получении времени последнего запроса: {e}")
            return None


async def set_last_request_time(phone_number: str, request_time, type_request: str):
    """
    Устанавливает или обновляет дату последнего запроса по номеру телефона.

    wb_prepayment
    ozon_prepayment
    ymarket_prepayment
    """
    logger.info(f"Устанавливаем время запроса для {phone_number}: {request_time} - {type_request}")
    column_map = {
        "wb_prepayment": "last_request_time_wb_prepayment",
        "ozon_prepayment": "last_request_time_ozon",
        "ymarket_prepayment": "last_request_time_ym"
    }

    column_name = column_map.get(type_request)
    if not column_name:
        logger.error(f"Неизвестный тип запроса: {type_request}")
        return

    async with get_db_connection() as conn:
        try:
            exists = await conn.fetchval("""
                    SELECT 1 FROM request_log WHERE phone_number = $1
                """, phone_number)

            if exists:
                query = f"""
                        UPDATE request_log SET {column_name} = $1 WHERE phone_number = $2
                    """
                await conn.execute(query, request_time, phone_number)
            else:
                query = f"""
                        INSERT INTO request_log (phone_number, {column_name}) VALUES ($1, $2)
                    """
                await conn.execute(query, phone_number, request_time)

        except Exception as e:
            logger.error(f"Ошибка при установке времени последнего запроса: {e}")

