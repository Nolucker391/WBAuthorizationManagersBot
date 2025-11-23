from aiogram import types, Bot
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile

from configuration_bot.settings import config
from handlers.routes import router
from utils.database.get_async_session_db import get_db_connection

from keyboards.InlineMarkup.default_commands import start_kb, auth_user_markup
from configuration_bot.settings import get_logger

logger = get_logger()


@router.message(CommandStart())
async def start_command(msd: types.Message, bot: Bot):
    chat_id = msd.from_user.id
    first_name = msd.from_user.first_name
    last_name = msd.from_user.last_name
    await bot.delete_message(
        chat_id=chat_id,
        message_id=msd.message_id
    )

    try:
        async with get_db_connection() as conn:
            row = await conn.fetchrow(
                """
                SELECT is_verified, phone_number, wp_email
                FROM auth_user
                WHERE chat_id = $1
                """, str(chat_id)
            )

        if row and row["is_verified"] is True:
            logger.info(f"Авторизованный пользователь: {chat_id} - нажал кнопку /start")
            photo = FSInputFile(config.MAIN_MENU_PHOTO_PATH)

            await msd.answer_photo(
                photo=photo,
                caption=("📋 Ваши данные:\n\n"
                         "Аккаунт WILDBERRIES:\n\n"
                         f"{row['phone_number']}\n\n"
                         "Аккаунт Bitrix24:\n\n"
                         f"{row['phone_number']} {row['wp_email']}"
                         ),
                reply_markup=auth_user_markup()
            )
            # await bot.send_photo(
            #     chat_id=chat_id,
            #     photo=photo,
            #     caption=("📋 Ваши данные:\n\n"
            #              "Аккаунт WILDBERRIES:\n\n"
            #              f"{row['phone_number']}\n\n"
            #              "Аккаунт Bitrix24:\n\n"
            #              f"{row['phone_number']} {row['wp_email']}"
            #              ),
            #     reply_markup=auth_user_markup()
            # )
        else:
            logger.info(f"Неавторизованный пользователь: {chat_id} - нажал кнопку /start")
            photo = FSInputFile(config.AUTH_PHOTO_PATH)

            await msd.answer_photo(
                photo=photo,
                caption=(
                    "👋 Привет от ООО «Солюшен»\n\n"
                    "Для дальнейшей авторизации в Боте, необходимо:\n\n"
                    "📞 Номер телефона, привязанный к аккаунту WildBerries\n\n"
                    "📨 Адрес электронной почты, привязанный к аккаунту Bitrix24"),
                reply_markup=start_kb()
            )
            # await bot.send_photo(
            #     chat_id=chat_id,
            #     photo=photo,
            #     caption=(
            #         "👋 Привет от ООО «Солюшен»\n\n"
            #         "Для дальнейшей авторизации в Боте, необходимо:\n\n"
            #         "📞 Номер телефона, привязанный к аккаунту WildBerries\n\n"
            #         "📨 Адрес электронной почты, привязанный к аккаунту Bitrix24"),
            #     reply_markup=start_kb()
            # )
    except Exception as e:
        logger.error(f"У пользователя произошла при /start Ошибка: {e}")

