from aiogram import F, types, Bot
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from aiogram.types import FSInputFile, InputMediaPhoto

from handlers.routes import router
from keyboards.InlineMarkup.default_commands import start_kb, auth_user_markup, approve_quit
from states.authorization_states import StateApprove
from utils.database.get_async_session_db import get_db_connection
from utils.database.edit_database import clear_db_auth_user
from configuration_bot.settings import get_logger, config

logger = get_logger()


@router.callback_query(F.data == "cancel", StateFilter(StateApprove.approve))
async def cancel_handler(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    await call.answer("Авторизация отменена.")
    try:
        async with get_db_connection() as conn:
            row = await conn.fetchrow(
                """
                SELECT is_verified, phone_number, wp_email
                FROM auth_user
                WHERE chat_id = $1
                """, str(call.from_user.id)
            )

        if row and row["is_verified"] is True:
            logger.info(f"Авторизованный пользователь: {call.from_user.id} - нажал кнопку - отменить")
            photo = FSInputFile(path=config.MAIN_MENU_PHOTO_PATH)

            await call.message.edit_media(
                media=InputMediaPhoto(
                    media=photo,
                    caption=("📋 Ваши данные:\n\n"
                             "Аккаунт WILDBERRIES:\n\n"
                             f"{row['phone_number']}\n\n"
                             "Аккаунт Bitrix24:\n\n"
                             f"{row['phone_number']} {row['wp_email']}"
                             ),
                    parse_mode="HTML"
                )
            )

            await call.message.edit_reply_markup(reply_markup=auth_user_markup())

        else:
            await clear_db_auth_user(user_id=call.from_user.id)
            logger.info(f"Неавторизованный пользователь: {call.from_user.id} - нажал кнопку - отменить")
            photo = FSInputFile(path=config.AUTH_PHOTO_PATH)

            await call.message.edit_media(
                media=InputMediaPhoto(
                    media=photo,
                    caption=(
                        "👋 Привет от ООО «Солюшен»\n\n"
                        "Для дальнейшей авторизации в Боте, необходимо:\n\n"
                        "📞 Номер телефона, привязанный к аккаунту WildBerries\n\n"
                        "📨 Адрес электронной почты, привязанный к аккаунту Bitrix24"),
                    parse_mode="HTML"
                )
            )

            await call.message.edit_reply_markup(reply_markup=start_kb())

        await state.clear()
    except Exception as e:
        logger.error(f"Ошибка при отмене: {e}")


@router.callback_query(F.data == "back_main_menu", StateFilter("*"))
async def back_to_handler(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    await call.answer("Вы вернулись в меню")

    try:
        async with get_db_connection() as conn:
            row = await conn.fetchrow(
                """
                SELECT is_verified, phone_number, wp_email
                FROM auth_user
                WHERE chat_id = $1
                """, str(call.from_user.id)
            )

        if row and row["is_verified"] is True:
            logger.info(f"Авторизованный пользователь: {call.from_user.id} - нажал кнопку - Вернуться в меню")
            photo = FSInputFile(path=config.MAIN_MENU_PHOTO_PATH)

            await call.message.edit_media(
                media=InputMediaPhoto(
                    media=photo,
                    caption=("📋 Ваши данные:\n\n"
                             "Аккаунт WILDBERRIES:\n\n"
                             f"{row['phone_number']}\n\n"
                             "Аккаунт Bitrix24:\n\n"
                             f"{row['phone_number']} {row['wp_email']}"
                             ),
                    parse_mode="HTML"
                )
            )

            await call.message.edit_reply_markup(reply_markup=auth_user_markup())

        else:
            await clear_db_auth_user(user_id=call.from_user.id)
            logger.info(f"Неавторизованный пользователь: {call.from_user.id} - нажал кнопку - Вернуться в меню")
            photo = FSInputFile(path=config.AUTH_PHOTO_PATH)

            await call.message.edit_media(
                media=InputMediaPhoto(
                    media=photo,
                    caption=(
                        "👋 Привет от ООО «Солюшен»\n\n"
                        "Для дальнейшей авторизации в Боте, необходимо:\n\n"
                        "📞 Номер телефона, привязанный к аккаунту WildBerries\n\n"
                        "📨 Адрес электронной почты, привязанный к аккаунту Bitrix24"),
                    parse_mode="HTML"
                )
            )

            await call.message.edit_reply_markup(reply_markup=start_kb())

        await state.clear()
    except Exception as e:
        logger.error(f"Ошибка при back_menu: {e}")


@router.callback_query(F.data == "quit_account_user", StateFilter(None))
async def quit_account(call: types.CallbackQuery, state: FSMContext):
    try:
        photo = FSInputFile(path=config.QUIT_ACCOUNT_PATH)

        await call.message.edit_media(
            media=InputMediaPhoto(
                media=photo,
                caption="📤 <b>Вы</b> подтверждаете <b>«Выход из аккаунта»?</b>",
                parse_mode="HTML"
            )
        )
        await call.message.edit_reply_markup(reply_markup=approve_quit())
        await state.set_state(StateApprove.approve_quit_account_state)

    except Exception as e:
        logger.error(f"Ошибка при нажатии на кнопку - Выход из аккаунта: {e}")


@router.callback_query(F.data == "approve_quit_account", StateFilter(StateApprove.approve_quit_account_state))
async def quit_account_handler(call: types.CallbackQuery, state: FSMContext):
    try:
        async with get_db_connection() as conn:
            row = await conn.fetchrow(
                """
                SELECT is_verified, chat_id
                FROM auth_user
                WHERE chat_id = $1
                """, str(call.from_user.id)
            )

        if row and row["is_verified"] is True:
            logger.info(f"Авторизованный пользователь: {call.from_user.id} - нажал кнопку - Выйти из аккаунта")

            photo = FSInputFile(path=config.AUTH_PHOTO_PATH)

            await call.message.edit_media(
                media=InputMediaPhoto(
                    media=photo,
                    caption=(
                        "👋 Привет от ООО «Солюшен»\n\n"
                        "Для дальнейшей авторизации в Боте, необходимо:\n\n"
                        "📞 Номер телефона, привязанный к аккаунту WildBerries\n\n"
                        "📨 Адрес электронной почты, привязанный к аккаунту Bitrix24"),
                    parse_mode="HTML"
                )
            )
            await clear_db_auth_user(user_id=call.from_user.id)
            await call.answer("Вы успешно вышли из аккаунта!")
            await call.message.edit_reply_markup(reply_markup=start_kb())
        else:
            logger.info(f"Неавторизованный пользователь: {call.from_user.id} - пытался нажать кнопку - Выйти из аккаунта")

            await call.answer("Вы не можете выйти из аккаунта - Вы не авторизованы!", show_alert=True)
        await state.clear()
    except Exception as e:
        logger.error(f"Ошибка при Выйти из аккаунта: {e}")
