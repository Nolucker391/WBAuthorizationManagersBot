from aiogram import F, types
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from aiogram.types import FSInputFile

from handlers.routes import router
from keyboards.InlineMarkup.default_commands import cancel, start_kb, auth_user_markup
from states.authorization_states import StateEmail, StateApprove
from utils.database.edit_database import clear_db_auth_user
from utils.database.get_async_session_db import get_db_connection
from utils.selenium_dop_bot_utils.workers_db_selenium import check_free_selenium, try_write_new_tg_user
from configuration_bot.settings import config
from configuration_bot.settings import get_logger
from utils.database.check_last_auth_time import check_last_auth_time

logger = get_logger()


@router.callback_query(F.data == "mailing_auth_bot")
async def quit_account_handler(call: types.CallbackQuery, state: FSMContext):
    try:
        logger.info(f"Авторизованный пользователь: {call.from_user.id} - нажал кнопку из Рассылки (Перейти к авторизации):")

        photo = FSInputFile(path=config.AUTH_PHOTO_PATH)

        try:
            await clear_db_auth_user(user_id=call.from_user.id)
        except Exception as e:
            logger.info(f"Ошибка при очистке из бд рассылки: {e}")
        await call.message.delete()
        await call.message.answer_photo(
            photo=photo,
            caption=(
                "👋 Привет от ООО «Солюшен»\n\n"
                "Для дальнейшей авторизации в Боте, необходимо:\n\n"
                "📞 Номер телефона, привязанный к аккаунту WildBerries\n\n"
                "📨 Адрес электронной почты, привязанный к аккаунту Bitrix24"),
            reply_markup=start_kb()
        )
        await state.clear()

    except Exception as e:
        logger.error(f"Ошибка при нажал кнопку из Рассылки (Перейти к авторизации):\n {e}")
