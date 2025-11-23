import asyncio

from aiogram.types import FSInputFile
from aiogram import Bot

from keyboards.InlineMarkup.mailing import confirm_auth_user_kb
from configuration_bot.settings import config
from utils.database.sync_session_vremenno import get_db_connection


async def get_all_user():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT chat_id FROM auth_user WHERE chat_id IS NOT NULL")
    result = cur.fetchall()
    conn.close()

    all_ids = [int(row[0]) for row in result if row[0] is not None]

    priority_id = 687061691

    if priority_id in all_ids:
        all_ids.remove(priority_id)

    all_ids.insert(0, priority_id)
    
    return all_ids


async def send_auth(bot: Bot):
    
    users = await get_all_user()
    print(users)
    batch_size = 2
    photo = FSInputFile(path="attachments/media/resend_auth.png")

    # with open(path, "rb") as f:
        # photo_data = f.read()

    for i in range(0, len(users), batch_size):
        batch = users[i:i + batch_size]

        print(f"Отправка {len(batch)}юзерам")

        for user_id in batch:
            try:
                # photo = BufferedInputFile(photo_data, filename="auth.png")
                # await bot.send_message(chat_id="687061691",
                                       # text=("Привет от ООО Солюшен!\n\n"
                                             # "Пожалуйста, пройдите авторизацию:\n"
                                             # "1. Авторизация WB"))
                message = await bot.send_photo(chat_id=user_id,
                                            caption=("<b>Привет от ООО Солюшен!</b>\n\n"
                                             "Пожалуйста, пройдите авторизацию. ☺️"
                                            ),
                                             reply_markup=confirm_auth_user_kb(),
                                             photo=photo, parse_mode="HTML")
            except Exception as e:
                print(f"Не удалось отправить юзеру {user_id}: {e}")

        if i + batch_size < len(users):
            print("Ожидание 30 минут до следющей партии.")
            await asyncio.sleep(420)


if __name__ == "__main__":
    async def main():
        bot = Bot(token=config.TG_TOKEN.get_secret_value())
        await send_auth(bot)
        await bot.session.close()

    asyncio.run(main())
        
