import asyncio
import aiohttp
import asyncpg

from configuration_bot.settings import config


async def get_db_connection():
    """
    Устанавливает асинхронное соединение с PostgreSQL.
    Возвращает соединение asyncpg.
    """
    return await asyncpg.connect(
        user=config.PG_USER,
        password=config.PG_PASSWORD.get_secret_value(),
        database=config.PG_DB_INTERNAL,
        host=config.PG_HOST.get_secret_value(),
        port=config.PG_PORT
    )


async def check_proxy(proxy_name: str, proxy_id: int, conn: asyncpg.Connection) -> bool:
    """
    Проверяет доступность прокси. Обновляет его статус в БД, если он не работает.
    """
    print("Проверяю на валидность прокси:", proxy_name, proxy_id)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                    "https://code-generator.wb.ru/generate/api/v1/code",
                    proxy=proxy_name,
                    timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                print(f"Ответ от прокси: {response.status}")
                return True

    except (aiohttp.ClientProxyConnectionError, aiohttp.ClientHttpProxyError,
            aiohttp.ClientConnectionError, asyncio.TimeoutError) as e:
        print(f"Ошибка при подключении через прокси: {e}")
        try:
            await conn.execute(
                "UPDATE proxy SET is_healthy = FALSE, is_busy = FALSE WHERE proxy_id = $1", proxy_id
            )
            phone = await conn.fetchval(
                "SELECT phone_number FROM auth_user WHERE proxy_id = $1", proxy_id
            )
            print(f"Найденный пользователь с проблемным прокси: {phone}")
        except Exception as db_error:
            print(f"Ошибка при работе с БД: {db_error}")
        return False

    except Exception as e:
        print(f"Неизвестная ошибка прокси {proxy_name}: {str(e)}")
        return True  # как и в твоём коде — любые другие ошибки не считаем фатальными


async def get_valid_proxy(phone_number: str, chat_id: int) -> str | None:
    """
    Получает рабочий прокси из таблицы mobile_proxies.
    Распределяет прокси поровну между пользователями.
    """
    conn = await get_db_connection()

    try:
        while True:
            # Получаем все доступные прокси из mobile_proxies
            available_proxies = await conn.fetch("""
                SELECT id, name FROM mobile_proxies
                ORDER BY id
            """)

            if not available_proxies:
                print("Прокси в mobile_proxies не найдены")
                await asyncio.sleep(7)
                continue

            # Для каждой прокси считаем количество пользователей
            proxy_counts = []
            for proxy in available_proxies:
                count = await conn.fetchval("""
                    SELECT COUNT(*) FROM auth_user 
                    WHERE proxy_id = $1
                """, proxy['id'])
                proxy_counts.append({
                    'id': proxy['id'],
                    'name': proxy['name'],
                    'count': count or 0
                })

            # Сортируем по количеству пользователей (от меньшего к большему)
            proxy_counts.sort(key=lambda x: x['count'])

            # Выбираем прокси с наименьшим количеством пользователей
            selected_proxy = proxy_counts[0]
            proxy_name = selected_proxy['name']

            print(f"Выбран прокси: {proxy_name} (пользователей: {selected_proxy['count']})")
            return proxy_name

    except Exception as e:
        print(f"Ошибка при получении прокси: {e}")
        return None
    finally:
        await conn.close()


async def change_proxy_ip(proxy_name: str, *, timeout: float = 10.0) -> bool:
    """
    Вызывает эндпоинт смены IP для указанного прокси.

    :param proxy_name: строка вида login:password@host:port
    :returns: True, если смена IP прошла успешно (ответ содержит 'ok')
    """
    try:
        host_part = proxy_name.split("@", 1)[-1]
        host, port = host_part.split(":")

        modem_suffix = ''.join(ch for ch in port if ch.isdigit())
        if len(modem_suffix) < 2:
            raise ValueError(f"Невозможно определить номер модема из порта: {port}")
        modem_id = modem_suffix[-2:]

        change_url = f"http://{host}:33333/modem{modem_id}.php"
        async with aiohttp.ClientSession() as session:
            async with session.get(
                    change_url,
                    timeout=aiohttp.ClientTimeout(total=timeout)
            ) as response:
                text = await response.text()
                if response.status == 200 and "ok" in text.lower():
                    print(f"Смена IP успешно выполнена для {proxy_name}")
                    return True
                print(f"Не удалось сменить IP для {proxy_name}. "
                      f"Статус: {response.status}, ответ: {text[:200]}")
                return False
    except Exception as e:
        print(f"Ошибка при смене IP для {proxy_name}: {e}")
        return False