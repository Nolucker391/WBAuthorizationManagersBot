import aiohttp
import asyncio

from httpx import AsyncHTTPTransport, AsyncClient

# async def change_ip(modem_url: str):
#     try:
#         async with aiohttp.ClientSession(
#                 timeout=aiohttp.ClientTimeout(total=15)
#         ) as session:
#             async with session.get(modem_url) as response:
#                 txt = await response.text()
#                 if "ok" in txt.lower():
#                     logger.info("IP успешно изменен: %s", txt)
#                     await asyncio.sleep(2.5)
#                     return True
#                 else:
#                     logger.error("IP не изменен на %s: %s", modem_url, txt)
#                     return False
#     except Exception as e:
#         logger.error(
#             "Ошибка при изменении IP %s: %s", modem_url, str(e), exc_info=True
#         )
#         return False
#
#
# async def change_gather():
#     urls = [
#         "http://94.143.43.213:33333/modem11.php",
#         "http://94.143.43.213:33333/modem15.php"
#     ]
#     tasks = [change_ip(url) for url in urls]
#     results = await asyncio.gather(*tasks)
#     return any(results)



# if __name__ == "__main__":
#     async def main():
#         transport = AsyncHTTPTransport(proxy="http://admin:admin@94.143.43.213:30615")
#         async with AsyncClient(transport=transport, timeout=10.0) as client:
