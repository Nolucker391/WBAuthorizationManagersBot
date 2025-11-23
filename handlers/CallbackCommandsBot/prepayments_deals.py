import aiohttp
from aiogram import types
from aiogram.types import InputMediaPhoto, FSInputFile
from datetime import datetime, timedelta, timezone
from handlers.routes import router
from utils.database.edit_database import get_auth_user_info
from utils.database.requests_times_info import get_last_request_time, set_last_request_time
from configuration_bot.settings import get_logger, config
from keyboards.InlineMarkup.default_commands import base_inline_kb_post_auth

MOSCOW_TIME = timedelta(hours=0)
TEN_MINUTES = timedelta(minutes=10)
logger = get_logger()


#ПредОплата WB(Курьеры)
@router.callback_query(lambda callback_query: callback_query.data == "pred_pay_wb")
async def pred_pay_wbb(callback_query: types.CallbackQuery):
    chat_id = callback_query.from_user.id
    user_data = await get_auth_user_info(user_id=chat_id)
    logger.info(f"Пользователь: {chat_id} - нажал кнопку - Предоплата WB")

    if not user_data:
        await callback_query.message.answer(
            "<b>Ваш номер телефона не найден.</b> \n\nПропишите команду /start и пройдите авторизацию снова.\n"
            "<i>Если это не поможет,то пожалуйста, обратитесь в группу в Битриксе</i> 'Оплата товара в Боте телеграмм'", parse_mode="HTML")
        return

    phone_number = user_data.get("phone_number")
    email = user_data.get("wp_email")

    last_request_time_wb_prepayment = await get_last_request_time(phone_number, type_request="wb_prepayment")
    current_time = datetime.now(timezone.utc) + MOSCOW_TIME

    if last_request_time_wb_prepayment is not None:
        last_request_time_wb_prepayment += MOSCOW_TIME
        logger.info(f"Время последнего запроса (МСК): {last_request_time_wb_prepayment} для {phone_number}")

        if current_time - last_request_time_wb_prepayment < TEN_MINUTES:
            print(f"True: {TEN_MINUTES}", current_time - last_request_time_wb_prepayment)
            # Calculate the remaining time until the next request is allowed (1 hour from last request)
            time_remaining = (last_request_time_wb_prepayment + TEN_MINUTES) - current_time
            total_minutes = int(time_remaining.total_seconds() // 60)
            seconds = int(time_remaining.total_seconds() % 60)
            await callback_query.answer(
                f"Ваш запрос уже был отправлен. \n\n⌛ Попробуйте снова через {total_minutes} минут и {seconds} секунд.", show_alert=True
            )
            return
    else:
        logger.info(f"Нет данных о предыдущем запросе для номера {phone_number}. Продолжаем выполнение запроса.")

    await callback_query.answer("⌛️ Ожидайте, обрабатываю запрос...", show_alert=True, cache_time=5)

    formatted_phone_number = phone_number.lstrip('+')
    url = f"http://91.105.198.24/api/payment_request?"
    data = {
        "phone": formatted_phone_number,
        "email": email,
        "chatid": chat_id,
        "type": "wb_prepayment"
    }
    logger.info(f"Отправка запроса на URL: {url}")

    # Send the request to the external API
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data) as response:
            logger.info(f"Статус сайта: {response.status}")  # Debug info

            if response.status == 201:
                response_data = await response.json()
                data_section = response_data.get("data")
                message_text = data_section.get("text") if data_section else "Информация передана."
                data_text = response_data.get("message", "Сообщение недоступно.")
                status_text = response_data.get("status", "Статус не указан.")

                logger.info(f"Ответ текста post wb_prepayment: {data_text}")
                logger.info(f"Ответ сообщение post wb_prepayment: {message_text}")  # Debug info
                logger.info(f"Ответ статуса post wb_prepayment: {status_text}")

                # Убедимся, что message_text содержит строку
                if not message_text:
                    message_text = "Внутренняя ошибка сервера (Нет текста.)"

                photo = FSInputFile(path=config.TEST_DEAL_WB)

                await callback_query.message.edit_media(
                    media=InputMediaPhoto(
                        media=photo,
                        caption=message_text,
                        parse_mode="HTML"
                    )
                )
                await callback_query.message.edit_reply_markup(reply_markup=base_inline_kb_post_auth())
                await set_last_request_time(phone_number, current_time, type_request="wb_prepayment")
            elif response.status == 500:
                # Обработка ошибки сервера
                logger.error("Внутренняя ошибка сервера (500).")
                photo = FSInputFile(path=config.TEST_DEAL_WB)
                await callback_query.message.edit_media(
                    media=InputMediaPhoto(
                        media=photo,
                        caption="⚠️ На стороне сервера произошла ошибка.⚠️ Пожалуйста, повторите попытку через час.\n"
                                "Если проблема сохранится, напишите в группу <b>'Оплата товара в Боте телеграмм'</b> в Битриксе.",
                        parse_mode="HTML"
                    )
                )
                await callback_query.message.edit_reply_markup(reply_markup=base_inline_kb_post_auth())
                await set_last_request_time(phone_number, current_time, type_request="wb_prepayment")
            elif response.status == 405:
                # Обработка ошибки сервера
                logger.error("Внутренняя ошибка сервера (405).")
                photo = FSInputFile(path=config.TEST_DEAL_WB)

                await callback_query.message.edit_media(
                    media=InputMediaPhoto(
                        media=photo,
                        caption="⚠️ На стороне сервера произошла ошибка.⚠️ Пожалуйста, повторите попытку через час.\n"
                                "Если проблема сохранится, напишите в группу <b>'Оплата товара в Боте телеграмм'</b> в Битриксе.",
                        parse_mode="HTML"
                    )
                )
                await callback_query.message.edit_reply_markup(reply_markup=base_inline_kb_post_auth())
                # Обновляем время последнего запроса
                await set_last_request_time(phone_number, current_time, type_request="wb_prepayment")
            else:
                # Получаем текст ошибки и отображаем его пользователю для отладки
                error_message = await response.text()
                logger.info(f"Ошибка ответа: {error_message}")  # Отладочная информация
                photo = FSInputFile(path=config.TEST_DEAL_WB)
                await callback_query.message.edit_media(
                    media=InputMediaPhoto(
                        media=photo,
                        caption="<b>❌ Ошибка запроса! ❌</b> \n\nДля решения проблемы, "
                                f"отпишите в Тех. Поддержку\n\nВыдало ошибку: {error_message}",
                        parse_mode="HTML"
                    )
                )
                await callback_query.message.edit_reply_markup(reply_markup=base_inline_kb_post_auth())
                await set_last_request_time(phone_number, current_time, type_request="wb_prepayment")


# ПредОплата OZON'a
@router.callback_query(lambda callback_query: callback_query.data == "pred_pay_ozon")
async def pred_pay_ozon(callback_query: types.CallbackQuery):
    chat_id = callback_query.from_user.id
    user_data = await get_auth_user_info(user_id=chat_id)
    logger.info(f"Пользователь: {chat_id} - нажал кнопку - Предоплата Ozon")

    if not user_data:
        await callback_query.message.answer(
            "<b>Ваш номер телефона не найден.</b> \n\nПропишите команду /start и пройдите авторизацию снова.\n"
            "<i>Если это не поможет,то пожалуйста, обратитесь в группу в Битриксе</i> 'Оплата товара в Боте телеграмм'",
            parse_mode="HTML")
        return

    phone_number = user_data.get("phone_number")
    email = user_data.get("wp_email")

    last_request_time_ozon = await get_last_request_time(phone_number, type_request="ozon_prepayment")
    current_time = datetime.now(timezone.utc) + MOSCOW_TIME

    if last_request_time_ozon is not None:
        last_request_time_ozon += MOSCOW_TIME
        logger.info(f"Время последнего запроса (МСК): {last_request_time_ozon} для {phone_number}")

        if current_time - last_request_time_ozon < TEN_MINUTES:
            time_remaining = (last_request_time_ozon + TEN_MINUTES) - current_time
            total_minutes = int(time_remaining.total_seconds() // 60)
            seconds = int(time_remaining.total_seconds() % 60)
            await callback_query.answer(
                f"Ваш запрос уже был отправлен. \n\n⌛ Попробуйте снова через {total_minutes} минут и {seconds} секунд.",
                show_alert=True
            )
            return
    else:
        logger.info(f"Нет данных о предыдущем запросе для номера {phone_number}. Продолжаем выполнение запроса.")

    await callback_query.answer("⌛️ Ожидайте, обрабатываю запрос...", show_alert=True, cache_time=5)

    formatted_phone_number = phone_number.lstrip('+')
    url = f"http://91.105.198.24/api/ozon_payment_request"
    data = {
        "phone": formatted_phone_number,
        "email": email,
        "chatid": chat_id,
        "type": "prepayment"
    }
    logger.info(f"Отправка запроса на URL: {url}")

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data) as response:
            logger.info(f"Статус сайта: {response.status}")

            if response.status == 201:
                response_data = await response.json()
                data_section = response_data.get("data")
                message_text = data_section.get("text") if data_section else "Информация передана."
                data_text = response_data.get("message", "Сообщение недоступно.")
                status_text = response_data.get("status", "Статус не указан.")

                print(f"Ответ текста post ozon: {data_text}")
                print(f"Ответ сообщение post ozon: {message_text}")
                print(f"Ответ статуса post ozon: {status_text}")

                if not message_text:
                    message_text = "Внутренняя ошибка сервера (Нет текста.)"

                photo = FSInputFile(path=config.TEST_DEAL_OZON)

                await callback_query.message.edit_media(
                    media=InputMediaPhoto(
                        media=photo,
                        caption=message_text,
                        parse_mode="HTML"
                    )
                )
                await callback_query.message.edit_reply_markup(reply_markup=base_inline_kb_post_auth())
                await set_last_request_time(phone_number, current_time, type_request="ozon_prepayment")
            elif response.status == 500:
                # Обработка ошибки сервера
                logger.info("Внутренняя ошибка сервера (500).")
                photo = FSInputFile(path=config.TEST_DEAL_WB)

                await callback_query.message.edit_media(
                    media=InputMediaPhoto(
                        media=photo,
                        caption="⚠️ На стороне сервера произошла ошибка.⚠️ Пожалуйста, повторите попытку через час.\n"
                                "Если проблема сохранится, напишите в группу <b>'Оплата товара в Боте телеграмм'</b> в Битриксе.",
                        parse_mode="HTML"
                    )
                )
                await callback_query.message.edit_reply_markup(reply_markup=base_inline_kb_post_auth())
                await set_last_request_time(phone_number, current_time, type_request="ozon_prepayment")
            else:
                # Получаем текст ошибки и отображаем его пользователю для отладки
                error_message = await response.text()
                logger.info(f"Ошибка ответа: {error_message}")  # Отладочная информация
                photo = FSInputFile(path=config.TEST_DEAL_WB)
                await callback_query.message.edit_media(
                    media=InputMediaPhoto(
                        media=photo,
                        caption="<b>❌ Ошибка запроса! ❌</b> \n\nДля решения проблемы, "
                                f"отпишите в Тех. Поддержку\n\nВыдало ошибку: {error_message}",
                        parse_mode="HTML"
                    )
                )
                await callback_query.message.edit_reply_markup(reply_markup=base_inline_kb_post_auth())
                await set_last_request_time(phone_number, current_time, type_request="ozon_prepayment")


# ПредОплата YMarket'a
@router.callback_query(lambda callback_query: callback_query.data == "pred_pay_ym")
async def pred_pay_ym(callback_query: types.CallbackQuery):
    chat_id = callback_query.from_user.id
    user_data = await get_auth_user_info(user_id=chat_id)
    logger.info(f"Пользователь: {chat_id} - нажал кнопку - Предоплата Ozon")

    if not user_data:
        await callback_query.message.answer(
            "<b>Ваш номер телефона не найден.</b> \n\nПропишите команду /start и пройдите авторизацию снова.\n"
            "<i>Если это не поможет,то пожалуйста, обратитесь в группу в Битриксе</i> 'Оплата товара в Боте телеграмм'",
            parse_mode="HTML")
        return

    phone_number = user_data.get("phone_number")
    email = user_data.get("wp_email")

    last_request_time_ym = await get_last_request_time(phone_number, type_request="ymarket_prepayment")
    current_time = datetime.now(timezone.utc) + MOSCOW_TIME

    logger.info(last_request_time_ym)

    if last_request_time_ym is not None:
        last_request_time_ym += MOSCOW_TIME
        logger.info(f"Время последнего запроса (МСК): {last_request_time_ym} для {phone_number}")

        if current_time - last_request_time_ym < TEN_MINUTES:
            time_remaining = (last_request_time_ym + TEN_MINUTES) - current_time
            total_minutes = int(time_remaining.total_seconds() // 60)
            seconds = int(time_remaining.total_seconds() % 60)

            await callback_query.answer(
                f"Ваш запрос уже был отправлен. \n\n⌛ Попробуйте снова через {total_minutes} минут и {seconds} секунд.",
                show_alert=True
            )
            return
    else:
        logger.info(f"Нет данных о предыдущем запросе для номера {phone_number}. Продолжаем выполнение запроса.")

    await callback_query.answer("⌛️ Ожидайте, обрабатываю запрос...", show_alert=True, cache_time=5)

    formatted_phone_number = phone_number.lstrip('+')
    url = f"http://91.105.198.24/api/ymarket_payment_request"
    data = {
        "phone": formatted_phone_number,
        "email": email,
        "chatid": chat_id,
        "type": "ym_prepayment"
    }
    logger.info(f"Отправка запроса на URL: {url}")

    # Send the request to the external API
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data) as response:
            logger.info(f"Статус сайта: {response.status}")

            if response.status == 201:
                response_data = await response.json()
                data_section = response_data.get("data")
                message_text = data_section.get("text") if data_section else "Информация передана."
                data_text = response_data.get("message", "Сообщение недоступно.")
                status_text = response_data.get("status", "Статус не указан.")

                print(f"Ответ текста post ymarket: {data_text}")
                print(f"Ответ сообщение post ymarket: {message_text}")  # Debug info
                print(f"Ответ статуса post ymarket: {status_text}")

                # Убедимся, что message_text содержит строку
                if not message_text:
                    message_text = "Внутренняя ошибка сервера (Нет текста.)"

                photo = FSInputFile(path=config.TEST_DEAL_YMARKET)

                await callback_query.message.edit_media(
                    media=InputMediaPhoto(
                        media=photo,
                        caption=message_text,
                        parse_mode="HTML"
                    )
                )
                await callback_query.message.edit_reply_markup(reply_markup=base_inline_kb_post_auth())
                await set_last_request_time(phone_number, current_time, type_request="ymarket_prepayment")
            elif response.status == 500:
                # Обработка ошибки сервера
                logger.info("Внутренняя ошибка сервера (500).")
                photo = FSInputFile(path=config.TEST_DEAL_YMARKET)

                await callback_query.message.edit_media(
                    media=InputMediaPhoto(
                        media=photo,
                        caption="⚠️ На стороне сервера произошла ошибка.⚠️ Пожалуйста, повторите попытку через час.\n"
                                "Если проблема сохранится, напишите в группу <b>'Оплата товара в Боте телеграмм'</b> в Битриксе.",
                        parse_mode="HTML"
                    )
                )
                await callback_query.message.edit_reply_markup(reply_markup=base_inline_kb_post_auth())
                await set_last_request_time(phone_number, current_time, type_request="ymarket_prepayment")
            else:
                # Получаем текст ошибки и отображаем его пользователю для отладки
                error_message = await response.text()
                logger.info(f"Ошибка ответа: {error_message}")  # Отладочная информация
                photo = FSInputFile(path=config.TEST_DEAL_YMARKET)

                await callback_query.message.edit_media(
                    media=InputMediaPhoto(
                        media=photo,
                        caption="<b>❌ Ошибка запроса! ❌</b> \n\nДля решения проблемы, "
                                f"отпишите в Тех. Поддержку\n\nВыдало ошибку: {error_message}",
                        parse_mode="HTML"
                    )
                )
                await callback_query.message.edit_reply_markup(reply_markup=base_inline_kb_post_auth())
                await set_last_request_time(phone_number, current_time, type_request="ozon_prepayment")
