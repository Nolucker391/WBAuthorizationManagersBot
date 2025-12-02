import sys
import time
import asyncio

from utils.database.get_async_session_db import get_db_connection


async def generate_some_id(conn) -> int:
    result = await conn.fetchval("SELECT MAX(proxy_id) FROM public.proxy")
    max_id = result if result is not None else 999
    new_id = max_id + 1

    if new_id > 9999:
        print("Достигнут предел 4-ех значных цифр")
    return new_id


async def main():
    async with get_db_connection() as conn:
        async with conn.transaction():
            with open("proxies_2025-10-30.txt", "r", encoding="utf-8") as f:
                proxies_from_file = [line.strip() for line in f if line.strip()]
            total = len(proxies_from_file)
            print(f"Total proxies from file: {total}")

            rows = await conn.fetch("SELECT proxy_name FROM public.proxy")
            existing_proxies = set(row["proxy_name"] for row in rows)

            new_proxies = [p for p in proxies_from_file if p not in existing_proxies]
            print(f"New proxies to insert: {len(new_proxies)}")

            for idx, proxy in enumerate(new_proxies, start=1):
                proxy_id = await generate_some_id(conn)

                await conn.execute("""
                    INSERT INTO public.proxy (proxy_id, proxy_name, is_busy, is_healthy)
                    VALUES ($1, $2, $3, $4)
                """, proxy_id, proxy, False, True)

                print(f"Вставлено {idx}/{len(new_proxies)}: {proxy}")

    print("Завершаю работу")
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())

    print("работа завершена")
    time.sleep(99999)
