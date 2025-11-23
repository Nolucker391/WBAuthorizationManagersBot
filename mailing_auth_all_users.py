import asyncio
import json
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram import Bot
from keyboards.InlineMarkup.mailing import confirm_auth_user_kb
from configuration_bot.settings import config
from utils.database.get_async_session_db import get_db_connection


async def get_all_users():
    async with get_db_connection() as conn:
        rows = await conn.fetch("""
            SELECT chat_id
            FROM auth_user
        """)
        return [row['chat_id'] for row in rows]


def next_step_auth():
    ikb = [
        [InlineKeyboardButton(text="🔐 Перейти к авторизации", callback_data='mailing_auth_bot')],
    ]
    keybord = InlineKeyboardMarkup(inline_keyboard=ikb)
    return keybord


async def send_auth(bot: Bot, users: list[int]):
    photo = FSInputFile(path="attachments/media/pismo.png")

    total_sent = 0
    failed = []

    print(f"\nОтправка {len(users)} пользователям")
    # for user_id in users:
    #     try:
    #         await bot.send_photo(
    #             chat_id=user_id,
    #             # caption=(
    #             #     "<b>👋 Привет от ООО «Солюшен»</b>\n\n"
    #             #     "🔄 Необходима повторная Авторизация!\n\n"
    #             #     "🔐 Пройдите пожалуйста авторизацию по кнопке ниже 👇\n\n"
    #             #     ""
    #             # ),
    #             caption=(
    #                 "<b>❌ Привет от ООО «Солюшен»</b>\n\n"
    #                 "🔄 Необходима повторная Авторизация!\n\n"
    #                 "🔐 Пройдите пожалуйста авторизацию по кнопке ниже 👇\n\n"
    #                 ""
    #             ),
    #             photo=photo,
    #             parse_mode="HTML",
    #             reply_markup=next_step_auth()
    #         )
    #         print(f"Отправлено: {user_id}")
    #         total_sent += 1
    #     except Exception as e:
    #         print(f"Не удалось отправить пользователю {user_id}: {e}")
    #         failed.append(user_id)
    users = [687061691]
    for id_user in users:
        try:
            await bot.send_photo(
                chat_id=id_user,
                caption=(
                    "<b>👋 Привет от ООО «Солюшен»</b>\n\n"
                    "🔄 Необходима повторная Авторизация!\n\n"
                    "🔐 Пройдите пожалуйста авторизацию по кнопке ниже 👇\n\n"
                ),
                photo=photo,
                parse_mode="HTML",
                reply_markup=next_step_auth()
            )
            print(f"Отправлено: {id_user}")
            total_sent += 1
        except Exception as e:
            print(f"❌ Не удалось отправить пользователю {id_user}: {e}")
            failed.append(id_user)
    print("\nРассылка завершена!")
    print(f"Успешно отправлено: {total_sent}")
    print(f"Ошибок: {len(failed)}")

    if failed:
        print("Список неуспешных ID:")
        for uid in failed:
            print(f"- {uid}")

if __name__ == "__main__":
    async def main():
        bot = Bot(token=config.TG_TOKEN.get_secret_value())

        users = await get_all_users()  
        await send_auth(bot, users=users)

        await bot.session.close()

    asyncio.run(main())