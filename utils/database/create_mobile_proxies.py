"""
Скрипт для создания таблицы mobile_proxies и добавления прокси
"""
import asyncpg
from configuration_bot.settings import config


async def create_mobile_proxies_table():
    """
    Создает таблицу mobile_proxies и добавляет 2 прокси
    """
    conn = await asyncpg.connect(
        user=config.PG_USER,
        password=config.PG_PASSWORD.get_secret_value(),
        database=config.PG_DB_INTERNAL,
        host=config.PG_HOST.get_secret_value(),
        port=config.PG_PORT
    )
    
    try:
        # Создаем таблицу mobile_proxies
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS mobile_proxies (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            )
        """)
        
        # Добавляем 2 прокси, если их еще нет
        proxies = [
            "admin:admin@94.143.43.213:30615",
            "admin:admin@94.143.43.213:30611"
        ]
        
        for proxy_name in proxies:
            await conn.execute("""
                INSERT INTO mobile_proxies (name)
                VALUES ($1)
                ON CONFLICT (name) DO NOTHING
            """, proxy_name)
        
        print("Таблица mobile_proxies создана и заполнена прокси")
        
    except Exception as e:
        print(f"Ошибка при создании таблицы mobile_proxies: {e}")
    finally:
        await conn.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(create_mobile_proxies_table())

