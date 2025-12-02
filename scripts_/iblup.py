import aiohttp
import asyncio



if __name__ == "__main__":
    async def main():
        async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)
        ) as session:
            async with session.get("http://94.143.43.213:33333/modem9.php") as response:
                txt = await response.text()
                print(txt)

    asyncio.run(main())
