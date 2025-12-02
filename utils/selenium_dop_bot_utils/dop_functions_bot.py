from aiogram import Bot
from aiogram.types import FSInputFile

from keyboards.InlineMarkup.default_commands import base_inline_kb_post_auth
from configuration_bot.settings import config
from utils.database.get_async_session_db import get_db_connection

bot = Bot(token=config.TG_TOKEN.get_secret_value(), session=None)


async def sms_registration(user_id: int, attempt_number: int = 1):
    print(f"Запущена sms_registration для user_id={user_id}, попытка={attempt_number}")

    if attempt_number > 2:
        print(f"[user_id: {user_id}] - Превышено количество попыток отправки кода")
        return False

    async with get_db_connection() as conn:
        await conn.execute(
            "UPDATE auth_user SET auth_state = 'waiting_sms_code' WHERE chat_id = $1",
            str(user_id)
        )

    try:
        photo = FSInputFile(path=config.NOTIF_PHOTO_PATH)

        await bot.send_photo(
            photo=photo,
            chat_id=user_id,
            caption=(
                "<b>📩 ВАМ был отправлен «КОД ПОДТВЕРЖДЕНИЯ»</b>\n\n"
                "<i>- Вы можете посмотреть код в разделе «Уведомлений» 🔔\np.s:  скриншот 1\n\n"
                "- Или же, посмотреть в «sms-сообщениях» вашего телефона 💌\np.s:  скриншот 2\n\n</i>"
                "<b>Пожалуйста, введите его в следующем образце:\n\n"
                "Пример: 678997 ✍️</b>"
            ),
            parse_mode="HTML"
        )

        await bot.send_message(
            chat_id=user_id,
            text="<b>💬 Если Вам вдруг не приходит смс-код ни в кабинете, ни в смс-сообщениях, попробуйте ввести 111111 😊</b>\n\n"
                 "* Если вдруг проблемы с получением кода, отпишите «Куратору по Ботам Альмир»",
            parse_mode="HTML"
        )

        print(f"[user_id: {user_id}] Код отправлен (попытка {attempt_number})")
        return True
    finally:
        await conn.close()


async def bad_registration(user_id, errors):
    user_id = int(user_id)
    try:
        photo = FSInputFile(path=config.ERROR_PHOTO_PATH)
        message = await bot.send_photo(chat_id=user_id,
                                       caption=('<b>❌ ПРИ АВТОРИЗАЦИИ ПРОИЗОШЛА ОШИБКА😰</b>\n'
                                                'Бот уже уведомил поддержку\n\n'
                                                '<b>🙏ПОПРОБУЙТЕ ПОЖАЛУЙСТА ЧУТЬ ПОЗЖЕ🙏</b>\n'
                                                ),
                                       photo=photo,
                                       reply_markup=base_inline_kb_post_auth(),
                                       parse_mode="HTML")
    except Exception as exc:
        print("Не удалось отправить сообщение юзеру")
    try:
        await bot.send_message(chat_id=687061691,
                               text=("У данного пользователя возникли проблемы"
                                     " с авторизацией.\n\n"
                                     f"Ошибка имеет следующую формулировку: {errors}\n"
                                     "Данные пользователя:\n"
                                     f"user_id: {user_id}"))
    except Exception as e:
        print(f"Данному администратору не было выслано уведомление об ошибке, т.к {e}")
    await bot.session.close()


async def good_registration(user_id):
    try:
        user_id = int(user_id)

        photo = FSInputFile(config.GOOD_AUTH_PHOTO_PATH)
        message = await bot.send_photo(chat_id=user_id,
                                       caption=('<b>✅ Ваша авторизация успешна! </b>\n\n'
                                                '<i>*Если по каким-то причинам авторизация на WB будет сброшена, бот Вас об этом уведомит.☺️</i>\n\n'
                                                '<i>*Если у вас не отображаются все кнопки, нажмите в левом нижнем углу кнопку меню.Появится вспомогательное окно /start,нажмите на него.</i>\n\n'
                                                '🙋‍♂️За доп. помощью, обращайтесь в наш битрикс! https://top-vector.bitrix24.ru/stream/'),
                                       photo=photo,
                                       reply_markup=base_inline_kb_post_auth(),
                                       parse_mode="HTML")
    except Exception as exc:
        print("Не удалось отправить сообщение юзеру")
    await bot.session.close()

# async def sms_registration(user_id: int, attempt_number: int = 1):
#     logger.info(f"Запущена sms_registration для user_id={user_id}, попытка={attempt_number}")
#
#     if attempt_number > 2:
#         print(f"[user_id: {user_id}] - Превышено количество попыток отправки кода")
#         return False
#
#     conn = await asyncpg.connect(
#         user="postgres",
#         password="hs,rf73",
#         database="analitycs",
#         host="localhost",
#         port=5432
#     )
#
#     try:
#         await conn.execute(
#             "UPDATE auth_user SET auth_state = 'waiting_sms_code' WHERE chat_id = $1",
#             str(user_id)
#         )
#         photo = FSInputFile("attachments/media/notifications/notif.png")
#
#         await bot.send_photo(
#             photo=photo,
#             chat_id=user_id,
#             caption=(
#                 "<b>📩 ВАМ был отправлен «КОД ПОДТВЕРЖДЕНИЯ»</b>\n\n"
#                 "<i>- Вы можете посмотреть код в разделе «Уведомлений» 🔔\np.s:  скриншот 1\n\n"
#                 "- Или же, посмотреть в «sms-сообщениях» вашего телефона 💌\np.s:  скриншот 2\n\n</i>"
#                 "<b>Пожалуйста, введите его в следующем образце:\n\n"
#                 "Пример: 678997 ✍️</b>"
#             ),
#             parse_mode="HTML"
#         )
#
#         print(f"[user_id: {user_id}] 📩 Код отправлен (попытка {attempt_number})")
#         return True
#     finally:
#         await conn.close()
#
#
# async def bad_registration(user_id, errors):
#     user_id = int(user_id)
#     try:
#         photo = FSInputFile("attachments/media/error_auth.png")
#         message = await bot.send_photo(chat_id=user_id,
#                                        caption=('<b>☹️ПРИ АВТОРИЗАЦИИ ПРОИЗОШЛА ОШИБКА☹️</b>\n'
#                                                 'Бот уже уведомил поддержку\n\n'
#                                                 '<b>🙏ПОПРОБУЙТЕ ЧУТЬ ПОЗЖЕ🙏</b>\n'
#                                                 'Для того чтобы авторизироваться ,требуется номер телефона, '
#                                                 'прикрепленным к кабинету вайлдберрис и e-mail привязанный к битриксу:\n'
#                                                 '1. WB (через данный бот)'),
#                                        photo=photo,
#                                        reply_markup=base_inline_kb_post_auth(),
#                                        parse_mode="HTML")
#     except Exception as exc:
#         print("Не удалось отправить сообщение юзеру")
#     try:
#         await bot.send_message(chat_id=687061691,
#                                text=("У данного пользователя возникли проблемы"
#                                      " с авторизацией.\n\n"
#                                      f"Ошибка имеет следующую формулировку: {errors}\n"
#                                      "Данные пользователя:\n"
#                                      f"user_id: {user_id}"))
#     except Exception as e:
#         print(f"Данному администратору не было выслано уведомление об ошибке, т.к {e}")
#     await bot.session.close()
#
#
# async def good_registration(user_id):
#     try:
#         user_id = int(user_id)
#
#         photo = FSInputFile("attachments/media/good_auth.png")
#         message = await bot.send_photo(chat_id=user_id,
#                                        caption=('<b>✅ Ваша авторизация успешна! </b>\n\n'
#                                                 '<i>*Если по каким-то причинам авторизация на WB будет сброшена, бот Вас об этом уведомит.☺️</i>\n\n'
#                                                 '<i>*Если у вас не отображаются все кнопки, нажмите в левом нижнем углу кнопку меню.Появится вспомогательное окно /start,нажмите на него.</i>\n\n'
#                                                 '🙋‍♂️За доп. помощью, обращайтесь в наш битрикс! https://top-vector.bitrix24.ru/stream/'),
#                                        photo=photo,
#                                        reply_markup=base_inline_kb_post_auth(),
#                                        parse_mode="HTML")
#     except Exception as exc:
#         print("Не удалось отправить сообщение юзеру")
#     await bot.session.close()
