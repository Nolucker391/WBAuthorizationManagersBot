from datetime import date

from aiogram import F, types
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from aiogram.types import FSInputFile

from handlers.routes import router
from keyboards.InlineMarkup.default_commands import cancel, start_kb, auth_user_markup
from states.authorization_states import StateEmail, StateApprove
from utils.database.get_async_session_db import get_db_connection
from utils.selenium_dop_bot_utils.workers_db_selenium import check_free_selenium, try_write_new_tg_user
from configuration_bot.settings import config
from configuration_bot.settings import get_logger
from utils.database.check_last_auth_time import check_last_auth_time

logger = get_logger()


@router.callback_query(F.data == "wb_cb", StateFilter(None))
async def wb_start_reg(call: types.CallbackQuery, state: FSMContext):
    logger.info(f"Пользователь - {call.from_user.id} нажал на кнопку 'Авторизации'")

    can_proceed, wait_msg = await check_last_auth_time(str(call.from_user.id))
    if not can_proceed:
        await call.answer(
            f"🔔 Важное уведомление!\n\n"
            f"Извините, но сейчас Вы - не можете пройти авторизацию.😣\n"
            f"Повторите свою попытку через: {wait_msg} ⏳\n\n",
            parse_mode="HTML", show_alert=True
        )
        return

    message = await call.message.answer(
        text="<b>📨 Введите адресс вашей электронной почты от Bitrix24\n\n"
             "Пример:\n"
             "solution@example.com</b>",
        parse_mode="HTML"
    )
    await state.set_state(StateEmail.email_state)


@router.callback_query(F.data == "wb_cb", StateFilter("*"))
async def wb_start_reg(call: types.CallbackQuery, state: FSMContext):
    logger.info(f"Пользователь - {call.from_user.id} нажал на кнопку 'Авторизации'")

    can_proceed, wait_msg = await check_last_auth_time(str(call.from_user.id))
    if not can_proceed:
        await call.answer(
            f"🔔 Важное уведомление!\n\n"
            f"Извините, но сейчас Вы - не можете пройти авторизацию.😣\n"
            f"Повторите свою попытку через: {wait_msg} ⏳\n\n",
            parse_mode="HTML", show_alert=True
        )
        return

    message = await call.message.answer(
        text="<b>📨 Введите адресс вашей электронной почты от Bitrix24\n\n"
             "Пример:\n"
             "solution@example.com</b>",
        parse_mode="HTML"
    )

    await state.set_state(StateEmail.email_state)


@router.callback_query(F.data == "approve_data_get_true", StateFilter(StateApprove.approve))
async def approve_true(call: types.CallbackQuery, state: FSMContext, bot):
    data = await state.get_data()
    phone = data.get("phone")
    await call.message.delete()
    await state.set_state(StateApprove.approve_true)

    logger.info(f"Начинаю авторизацию для юзера: {phone} - {call.from_user.id}")

    async with get_db_connection() as conn:
        # await conn.execute(
        #     """UPDATE auth_user SET phone_number = $1 WHERE chat_id = $2""",
        #     phone, str(call.from_user.id)
        # )
        await conn.execute(
            """
            UPDATE auth_user
            SET phone_number = $1,
                wp_date = $2
            WHERE chat_id = $3
            """,
            phone, date.today(), str(call.from_user.id)
        )
        try:
            result = await conn.fetchrow("SELECT wp_email FROM auth_user WHERE chat_id = $1", str(call.from_user.id))
            if not result:
                await state.clear()
                return
            email = result['wp_email']
            situation_status = await check_free_selenium(call.from_user.id, phone, email)
        except Exception as e:
            await state.clear()
            return

        if isinstance(situation_status, int):
            try:
                logger.info("Отправляю на регистрацию")
                is_success = await try_write_new_tg_user(call.from_user.id, phone, situation_status, email)
                logger.info(f"Successfully status: {is_success}")
            except Exception as e:
                logger.info(f"Произошла ошибка: {e}")
                await state.clear()
                return

            if not is_success:
                text_message = ('<b>На данный момент авторизация не возможна</b>☹️\n'
                                'Бот уведомил поддержку о данной проблеме.\n\n')
                try:
                    await bot.send_message(
                        chat_id=687061691,
                        text=("У данного пользователя возникли проблемы с авторизацией из-за отсутствия proxy\n\n"
                              f"user_name: {call.from_user.username}\n"
                              f"first_name: {call.from_user.first_name}\n"
                              f"last_name: {call.from_user.last_name}\n"
                              f"user_id: {call.from_user.id}")
                    )
                except Exception as e:
                    logger.error(f"Ошибка рассылки админу 687061691: {e}")

                try:
                    photo = FSInputFile(path=config.AUTH_PHOTO_PATH)
                    await call.message.answer_photo(
                        photo=photo,
                        caption=(text_message +
                                 '<b>🙏ПОПРОБУЙТЕ ЧУТЬ ПОЗЖЕ🙏</b>\n'
                                 ),
                        parse_mode="HTML",
                        reply_markup=start_kb()
                    )
                except Exception as e:
                    logger.error(f'Ошибка при отправке сообщения авторизации: {e}')

                await conn.execute("""
                    UPDATE auth_user SET chat_id = NULL, phone_number = NULL WHERE chat_id = $1
                """, str(call.from_user.id))
                await state.clear()
            else:
                text = ("<b>🔄 Начинаю процесс авторизации…</b>\n\n"
                        "<i>Авторизация произойдет в два этапа:\n\n"
                        "• Вход в ваш аккаунт\n"
                        "• Аунтефикация входа в аккаунт\n\n"
                        "Пожалуйста, следуйте инструкции - Бота 🪁</i>\n\n"
                        "<b>⏳ Ориентировочное время авторизации: 4-5 минут</b>")
                logger.info(f"Статус авторизации: {situation_status}")
                await call.message.answer(
                    text=text,
                    parse_mode="HTML"
                )
                await state.clear()
        else:
            situation = situation_status
            logger.info(f"Статус авторизации2: {situation}")

            if situation == "1":
                try:
                    photo = FSInputFile(path=config.MAIN_MENU_PHOTO_PATH)
                    await call.message.answer_photo(
                        photo=photo,
                        caption='<b>ВЫ УЖЕ АВТОРИЗОВАНЫ😊</b>\n\n',
                        parse_mode="HTML",
                        reply_markup=auth_user_markup()
                    )
                    await state.clear()
                except Exception as ex:
                    logger.error(f'Ошибка при отправке сообщения авторизации: {ex}')

            elif situation == "2":
                await call.answer(
                    text="У вас уже начат процесс авторизации.\nНужно немного подождать...⏳",
                    parse_mode="HTML", show_alert=True
                )
                await state.clear()

            elif situation == "3":
                try:
                    photo = FSInputFile(path=config.AUTH_PHOTO_PATH)
                    await call.message.answer_photo(
                        photo=photo,
                        caption=(
                            '<b>ОБРАЗОВАЛАСЬ НЕБОЛЬШАЯ ОЧЕРЕДЬ НА РЕГИСТРАЦИЮ☹️</b>\n\n'
                            '<b>🙏ПОПРОБУЙТЕ ЧУТЬ ПОЗЖЕ🙏</b>\n'
                        ),
                        parse_mode="HTML",
                        reply_markup=start_kb()
                    )
                except Exception as e:
                    logger.error(f"Произошла ошибка при отправке сообщения юзеру: {e}")
                await state.clear()

        logger.info(f"Первый этап завершен - Ждем ответа selenium: {phone} - {call.from_user.id}")
