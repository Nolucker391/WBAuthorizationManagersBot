import asyncpg
from fake_useragent import UserAgent

from utils.database.get_async_session_db import get_db_connection
from utils.proxies import get_valid_proxy
from configuration_bot.settings import get_logger

ua = UserAgent(platforms='pc', os=["windows", "macos"], browsers='chrome')

logger = get_logger()


async def check_free_selenium(chat_id, phone_number, email=None):
    logger.info("Selenium запущен. Проверяю свободные процессы")

    async with get_db_connection() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("""
                SELECT process_id FROM selenium_process
                WHERE is_busy IS FALSE
                ORDER BY process_id ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            """)
            process_id = row['process_id'] if row else None

            if process_id:
                # Пометить процесс как занятый
                await conn.execute("""
                    UPDATE selenium_process SET is_busy = TRUE WHERE process_id = $1
                """, process_id)

        logger.info(f"Присваиваю пользователю process_id: {process_id}")

        # Проверка авторизации и других условий
        user = await conn.fetchrow(
            'SELECT * FROM auth_user WHERE chat_id = $1 AND selenium_id > 0',
            str(chat_id)
        )

        count_open_registration = await conn.fetchval(
            'SELECT COUNT(*) FROM auth_user WHERE chat_id = $1 AND selenium_id > 0',
            str(chat_id)
        )
        logger.info(f'Кол-во активных регистраций пользователя: {count_open_registration}')

        if email:
            is_verified = await conn.fetchval(
                'SELECT is_verified FROM auth_user WHERE wp_email = $1',
                email
            )
        else:
            is_verified = await conn.fetchval(
                'SELECT is_verified FROM auth_user WHERE phone_number = $1',
                phone_number
            )

    if is_verified is True:
        return '1'  # Уже авторизован

    if process_id and count_open_registration == 0:
        return process_id
    elif process_id and count_open_registration > 0:
        return '2'  # Уже начат процесс
    else:
        return '3'  # Нет свободных браузеров


async def try_write_new_tg_user(chat_id, phone_number, selenium_id, email):
    async with get_db_connection() as conn:
        proxy_data = await conn.fetchrow(
            "SELECT proxy_name, proxy_id FROM auth_user WHERE phone_number = $1",
            phone_number
        )

        if not proxy_data or (not proxy_data['proxy_name'] and not proxy_data['proxy_id']):
            # Получаем новый proxy_name (proxy_id будет получен позже)
            proxy_name = await get_valid_proxy(phone_number, chat_id)
            logger.info(f"Назначен новый прокси: {proxy_name}")

            if not proxy_name:
                logger.error("Не удалось получить валидный прокси")
                return False

            # Получаем proxy_id по proxy_name из таблицы mobile_proxies
            proxy_record = await conn.fetchrow(
                "SELECT id FROM mobile_proxies WHERE name = $1", proxy_name
            )

            if not proxy_record:
                logger.error(f"Не найден proxy_id для {proxy_name} в mobile_proxies")
                return False

            proxy_id = proxy_record['id']
        else:
            proxy_name = proxy_data['proxy_name']
            proxy_id = proxy_data['proxy_id']

        user_agent = ua.random

        try:
            await conn.execute("""
                INSERT INTO auth_user
                    (wp_email, chat_id, phone_number, selenium_id, is_verified, proxy_name, proxy_id, user_agent)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (wp_email) DO UPDATE SET
                    selenium_id = EXCLUDED.selenium_id,
                    chat_id = EXCLUDED.chat_id,
                    phone_number = EXCLUDED.phone_number,
                    is_verified = FALSE,
                    proxy_name = EXCLUDED.proxy_name,
                    proxy_id = EXCLUDED.proxy_id,
                    user_agent = EXCLUDED.user_agent
            """, str(email), str(chat_id), str(phone_number), int(selenium_id), False, proxy_name, proxy_id, user_agent)

            return True
        except asyncpg.PostgresError as e:
            logger.error(f"Ошибка при записи пользователя: {e}")
            return False


async def update_selenium_process_table(process_ids: list[int]):
    async with get_db_connection() as conn:
        try:
            # Очистка таблицы
            await conn.execute("DELETE FROM selenium_process")

            # Добавление новых записей
            for process_id in process_ids:
                await conn.execute(
                    '''
                    INSERT INTO selenium_process (process_id, is_busy)
                    VALUES ($1, FALSE)
                    ''',
                    process_id
                )
            print("Таблица selenium_process обновлена.")
        except Exception as e:
            print(f"Ошибка при обновлении selenium_process: {e}")


async def update_proxies_status(proxy_id: int):
    async with get_db_connection() as conn:
        try:
            await conn.execute(
                "UPDATE proxy SET is_busy = false WHERE proxy_id = $1", proxy_id
            )
            print(f"Таблица proxy обновлена. Proxy_id: {proxy_id} → is_busy = false")
        except Exception as e:
            print(f"Ошибка при обновлении proxy: {e}")