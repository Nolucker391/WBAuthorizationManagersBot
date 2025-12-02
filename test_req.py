import asyncio
import aiohttp

async def test_proxy():
    proxy = "http://admin:admin@94.143.43.213:30609"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.ipify.org", proxy=proxy, timeout=10) as response:
                text = await response.text()
                print("IP через прокси:", text)
    except Exception as e:
        print("Ошибка подключения через прокси:", e)

if __name__ == "__main__":
    asyncio.run(test_proxy())
