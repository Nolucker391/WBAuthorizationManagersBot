from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram import InputMediaPhoto
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    CallbackContext,
    CallbackQueryHandler,
)
import logging
import os
from datetime import datetime
# import httpx

# Чтобы убрать спам от httpx
logging.getLogger("httpx").setLevel(logging.WARNING)  # или logging.ERROR
# Чтобы полностью отключить
# logging.getLogger("httpx").propagate = False
# httpx_logger = logging.getLogger("httpx")
# httpx_logger.setLevel(logging.CRITICAL)
# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния диалога
(
    BITRIX_NAME,
    SELECT_SERVICE, WB_MENU, WB_DIRECTION, WB_PVZ, WB_CARD,
    WB_REJECT_ITEMS, WB_REJECT_ARTICLES, WB_REJECT_PHOTOS,
    SELECT_ADDRESS, UPLOAD_QR, WB_STORAGE_DAY, TECH_SUPPORT
) = range(13)

# Настройки групп для пересылки
GROUP_SETTINGS = {
    "wb": {
        "Направление 1": {
            "Завидная 15": "-4606750152",
            "Берёзовая 16": "-4606750152",
            "Ольховая 11": "-4606750152",
            "Зеленые аллеи 7": "-4606750152",
            "Лемешко 10": "-4606750152",
            "Фруктовые сады 77": "-4606750152",
            "Совхозная 4": "-4606750152",
            "Петровский пр 26": "-4606750152",
            "Спасский Проезд 171н": "-4606750152",
            "Измайлово 20А": "-4606750152",
            "Востряковский пр 21 к 1": "-4606750152",
            "Булатниковская 6А": "-4606750152",
            "Харьковская 1А": "-4606750152",
            "Харьковский пр 7А": "-4606750152",
            "Харьковский пр 1 к 1": "-4606750152",
            "Медынская 5А к 1": "-4606750152",
            "Элеваторная 8": "-4606750152",
            "Бирюлевская 1 к 3": "-4606750152",
            "Бирюлёвская 22": "-4606750152",
            "Бирюлёвская 29Б": "-4606750152",
            "Бирюлёвская 37А": "-4606750152",
            "Бирюлёвская 47А": "-4606750152",
            "Пролетарский Пр 33к1": "-4606750152",
            "Загорьевский пр 11Ас9": "-4606750152",
            "Липецкая 54/21": "-4606750152",
            "Загорьевская 25": "-4606750152",
            "Лебедянская 38": "-4606750152",
            "Лебедянская 30": "-4606750152",
            "Бакинская 13": "-4606750152",
            "Севанская 3 к 2": "-4606750152",
            "Севанская улица, 9к1": "-4606750152",
            "Луганская Улица, 5": "-4606750152",
            "Ереванская 24": "-4606750152",
            "Медиков 12": "-4606750152",
            "Кантемировская 5 к 4": "-4606750152",
            "Кантемировская 3 к 5": "-4606750152",
            "Липецкая 22": "-4606750152",
            "Липецкая 34/25": "-4606750152",
            "Бирюлевская ул 55к1с2": "-4606750152",
        },
        "Направление 2": {
            "Квартал Северный 14": "-4612609674",
            "Ермолинская 7": "-4612609674",
            "Завидная 20": "-4612609674",
            "Берёзовая 1с8": "-4612609674",
            "Заводская 16": "-4612609674",
            "Дер.Таболово 18А": "-4612609674",
            "Каширское ш 65к2": "-4612609674",
            "Генерала Белова 43к2": "-4612609674",
            "Воронежская 7": "-4612609674",
            "Елецкая 20А": "-4612609674",
            "Ясеневая 36": "-4612609674",
            "Гурьевский пр 25к1": "-4612609674",
            "Воронежская 36к1": "-4612609674",
            "Шипиловская 25А": "-4612609674",
            "Ореховый пр 11": "-4612609674",
            "Мусы Джалиля 13А": "-4612609674",
            "Шипиловская 64к1": "-4612609674",
            "Кустанайская 6": "-4612609674",
            "Ореховый бульвар 57А": "-4612609674",
            "Ореховый бульвар 24к3": "-4612609674",
            "Генерала Белова 29": "-4612609674",
            "Борисовский пр 8/1": "-4612609674",
            "Маршала Захарова 5": "-4612609674",
            "Шипиловская 1": "-4612609674",
            "Шипиловский пр 47": "-4612609674",
            "Домодедовская 7к1с2": "-4612609674",
            "Домодедовская 42А": "-4612609674",
            "Ясеневая 10к1": "-4612609674",
            "Борисовские пр-ы 17к1": "-4612609674",
            "Борисовские пр-ы 8А": "-4612609674",
            "Борисовские пр-ы 16к2": "-4612609674",
            "Братеевская 21к3": "-4612609674",
            "Паромная 9к4": "-4612609674",
            "Алма-атинская 7к2": "-4612609674",
            "Борисовские пруды 34 к2": "-4612609674",
            "Борисовские пруды 26": "-4612609674",
            "Олимпийский пр 1к2": "-4612609674",
        },
        "Направление 3": {
            "Батайский пр 41": "-4671784543",
            "М.Голованова 19": "-4671784543",
            "Батайский пр 25": "-4671784543",
            "Донецкая ул 34к3": "-4671784543",
            "Донецкая ул 30к1": "-4671784543",
            "Донецкая ул 4 к2": "-4671784543",
            "Новочеркасский б. 20к1": "-4671784543",
            "Новочеркасский б. 44": "-4671784543",
            "М. Голованова 11": "-4671784543",
            "Новочеркасский б. 5ст2": "-4671784543",
            "Донецкая 23стр2": "-4671784543",
            "Подольская ул 27к1": "-4671784543",
            "М. Голованова 5": "-4671784543",
            "Перерва 26к1": "-4671784543",
            "Перерва 38": "-4671784543",
            "Люблинская 100к2": "-4671784543",
            "Перерва 54": "-4671784543",
            "Новомарьинская 14/15": "-4671784543",
            "Мясковский б-р 5к1": "-4671784543",
            "Перерва 62к2": "-4671784543",
            "Белореченская 22/6": "-4671784543",
            "Верхние поля 37к2": "-4671784543",
            "Люблинская 147": "-4671784543",
            "Совхозная 8": "-4671784543",
            "Новороссийская 28": "-4671784543",
            "Краснодарская 60А": "-4671784543",
            "М. Кожедуба 16к1": "-4671784543",
            "Марьинский парк 39к1": "-4671784543",
            "Марьинский парк 21к2": "-4671784543",
            "Белореченская 38к2": "-4671784543",
            "Перервинский б 25": "-4671784543",
            "Братиславская ул 30": "-4671784543",
            "Мячковский б 20к3": "-4671784543",
            "Луговой проезд 7": "-4671784543",
            "Поречная ул 3к3": "-4671784543",

        },
        "Направление 4": {
            "Инессы Арманд, 6А": "-4728329751",
            "Голубинская, 32/2": "-4728329751",
            "Голубинская, 16": "-4728329751",
            "Ясногорская, 17к1": "-4728329751",
            "Пр-т Новоясен, 19к2": "-4728329751",
            "Рокотова, 5": "-4728329751",
            "Рокотова, 1А": "-4728329751",
            "Соловьиный пр-д, 4": "-4728329751",
            "Литовский б-р, 7": "-4728329751",
            "Литовский б-р, 22": "-4728329751",
            "Пр-т Новоясен, 12к1": "-4728329751",
            "Пр-т Новоясен, 22к1": "-4728329751",
            "Академика Янгеля 6 к 1": "-4728329751",
            "Академика Капицы, 20": "-4728329751",
            "Профсоюзная, 115к1": "-4728329751",
            "Введенского, 29с1": "-4728329751",
            "Миклухо-Маклая, 42Б": "-4728329751",
            "Миклухо-Маклая, 55": "-4728329751",
            "Миклухо-Маклая, 33": "-4728329751",
            "Академика Волгина, 25к1": "-4728329751",
            "Островитянова, 11к1": "-4728329751",
            "Островитянова, 5": "-4728329751",
            "Академика Бакулева, 10с3": "-4728329751",
            "Ленинский пр-т, 135к2": "-4728329751",
            "Новаторов, 36к3": "-4728329751",
            "Кировоградская, 8к4": "-4728329751",
            "Академика Янгеля, 4к2": "-4728329751",
            "Академика Янгеля, 3": "-4728329751",
            "Варшавское шоссе, 154А": "-4728329751",
        }
    },
    "ozon": {
        "Ермолинская 5": "-1002527032546",
        "Берёзовая улица 1с8": "-1002663389739",
        "Зеленные аллеи 18": "-1002530734155",
        "Пр-т ленинского комсомола 2к1": "-1002694466878",
        "Советский проезд 7": "-1002518747964",
        "Берёзовая улица 10а": "-1002519671554",
        "Жуковский проезд 3А": "-1002607558832",
        "Лемешко 10": "-1002682241251",
        "Советская ул вл10/1": "-1002363559468",
        "Завидная 1":"-4709142739",
        "Ольховая 11":"-4947477113",
        "Березовая 1 стр 8":"-4960077486",
        "Пр-т Ленинского комсомола 36Б":"-4882473799",
        "Пионерский переулок 9":"-4874389714",
        "Зеленые аллеи 2":"-4901643941",
        "3-я радиальная 8":"-4911576116",
    },
    "ym": {
        "Березовая 11": "-1002692030543",
        "Пр-т ленинского комсомола 35": "-1002566587135",
        "Жуковский проезд 3А": "-1002607558832",
        "Советская ул вл 10/1": "-1002363559468",
        "Лемешко 10": "-1002682241251",
        "Петровский пр 14":"-4833506101",
        "Зеленые аллеи 12":"-4924470720",
        "Олимпийский 6к1":"-4809259316",
        "Западный 5к2":"-4925736390",
    }
}

SUPPORT_CHAT_ID = "-1002414445943"


async def start(update: Update, context: CallbackContext) -> int:
    """Обработка команды /start - запрос имени в Битриксе или главное меню"""
    try:
        # Проверяем, есть ли уже имя в user_data
        if 'bitrix_name' not in context.user_data:
            await update.message.reply_text("Какое ваше имя в Битриксе?")
            return BITRIX_NAME

        # Если имя уже есть, показываем главное меню
        return await show_main_menu(update, context)

    except Exception as e:
        logger.error(f"Ошибка в start: {str(e)}")
        if update.message:
            await update.message.reply_text("❌ Ошибка при запуске. Попробуйте снова.")
        return ConversationHandler.END


async def handle_bitrix_name(update: Update, context: CallbackContext) -> int:
    """Обработка имени в Битриксе"""
    try:
        bitrix_name = update.message.text.strip()
        if not bitrix_name:
            await update.message.reply_text("Имя не может быть пустым. Пожалуйста, введите ваше имя в Битриксе:")
            return BITRIX_NAME

        # Сохраняем имя в user_data
        context.user_data['bitrix_name'] = bitrix_name
        logger.info(f"Пользователь {update.effective_user.id} указал имя в Битриксе: {bitrix_name}")

        # Показываем главное меню
        return await show_main_menu(update, context)

    except Exception as e:
        logger.error(f"Ошибка в handle_bitrix_name: {str(e)}")
        await update.message.reply_text("❌ Ошибка при обработке имени. Попробуйте снова.")
        return BITRIX_NAME

async def show_main_menu(update: Update, context: CallbackContext) -> int:
    """Показывает главное меню"""
    try:
        keyboard = [
            [InlineKeyboardButton("WB", callback_data="wb")],
            [InlineKeyboardButton("Ozon", callback_data="ozon")],
            [InlineKeyboardButton("Яндекс Маркет", callback_data="ym")],
            [InlineKeyboardButton("Тех.поддержка", callback_data="txp")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if update.message:
            await update.message.reply_text(
                "🚚 Выберите сервис для забора:\n"
                "<b>Внимание!</b> QR-код для забора товара отправляется <b>1 раз в сутки</b>, по графику",
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        else:
            await update.callback_query.edit_message_text(
                "🚚 Выберите сервис для забора:\n"
                "<b>Внимание!</b> QR-код для забора товара отправляется <b>1 раз в сутки</b>, по графику",
                reply_markup=reply_markup,
                parse_mode="HTML"
            )

        return SELECT_SERVICE

    except Exception as e:
        logger.error(f"Ошибка в show_main_menu: {str(e)}")
        if update.message:
            await update.message.reply_text("❌ Ошибка при отображении меню. Попробуйте снова.")
        return ConversationHandler.END


async def select_service(update: Update, context: CallbackContext) -> int:
    """Обработка выбора сервиса"""
    query = update.callback_query
    await query.answer()

    service = query.data
    context.user_data['service'] = service
    logger.info(f"Выбран сервис: {service}")

    if service == "wb":
        keyboard = [
            [InlineKeyboardButton("📍 Выбрать направление", callback_data="wb_select_direction")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_start")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("📦 Выберите действие для WB:", reply_markup=reply_markup)
        return WB_MENU
    elif service == "txp":
        await query.edit_message_text("✉️ С чем вам помочь? Опишите вашу проблему:")
        return TECH_SUPPORT
    elif service in ["ozon", "ym"]:
        return await show_addresses(update, context)
    return SELECT_SERVICE


async def handle_tech_support(update: Update, context: CallbackContext) -> int:
    """Обработка вопроса в техподдержку"""
    try:
        user_message = update.message.text
        username = update.message.from_user.username or "Не указан"
        phone = update.message.contact.phone_number if update.message.contact else "Не указан"

        # Сохраняем вопрос
        context.user_data['tech_support_question'] = user_message

        # Отправляем подтверждение
        await update.message.reply_text("✅ В скором времени вам ответят в Битриксе")

        # Отправляем в группу поддержки
        support_msg = (
            f"🆘 Новый запрос в техподдержку\n\n"
            f"От: @{username}\n"
            f"Имя в битриксе: {context.user_data['bitrix_name']}\n\n"
            f"Вопрос:\n{user_message}"
        )
        await context.bot.send_message(
            chat_id=SUPPORT_CHAT_ID,
            text=support_msg
        )

        return await start(update, context)
    except Exception as e:
        logger.error(f"Ошибка в handle_tech_support: {e}")
        await update.message.reply_text("❌ Ошибка при обработке запроса.")
        return ConversationHandler.END

async def wb_menu(update: Update, context: CallbackContext) -> int:
    """Меню для WB"""
    query = update.callback_query
    await query.answer()

    if query.data == "wb_select_direction":
        # Показываем направления для WB
        keyboard = [
            [InlineKeyboardButton("Направление 1", callback_data="wb_dir_1")],
            [InlineKeyboardButton("Направление 2", callback_data="wb_dir_2")],
            [InlineKeyboardButton("Направление 3", callback_data="wb_dir_3")],
            [InlineKeyboardButton("Направление 4", callback_data="wb_dir_4")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_wb_menu")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("📍 Выберите направление для WB:", reply_markup=reply_markup)
        return WB_DIRECTION

    elif query.data == "back_to_start":
        return await start(update, context)

    return WB_MENU


async def wb_select_direction(update: Update, context: CallbackContext) -> int:
    """Обработка выбора направления для WB"""
    query = update.callback_query
    await query.answer()

    if query.data == "back_to_wb_menu":
        keyboard = [
            [InlineKeyboardButton("📍 Выбрать направление", callback_data="wb_select_direction")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_start")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("📦 Выберите действие для WB:", reply_markup=reply_markup)
        return WB_MENU

    if query.data.startswith("wb_dir_"):
        direction_num = query.data.split("_")[-1]
        direction_name = f"Направление {direction_num}"
        context.user_data['wb_direction'] = direction_name

        # Получаем список ПВЗ для выбранного направления
        pvz_list = list(GROUP_SETTINGS["wb"][direction_name].keys())

        # Создаем кнопки ПВЗ по 2 в ряд
        keyboard = []
        for i in range(0, len(pvz_list), 2):
            row = []
            if i < len(pvz_list):
                row.append(InlineKeyboardButton(pvz_list[i], callback_data=f"wb_pvz_{pvz_list[i]}"))
            if i+1 < len(pvz_list):
                row.append(InlineKeyboardButton(pvz_list[i+1], callback_data=f"wb_pvz_{pvz_list[i+1]}"))
            if row:  # Добавляем только непустые ряды
                keyboard.append(row)

        # Добавляем кнопку "Назад"
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_wb_directions")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            text=f"🏪 Выберите ПВЗ ({direction_name}):",
            reply_markup=reply_markup
        )
        return WB_PVZ

    return WB_DIRECTION


async def wb_select_pvz(update: Update, context: CallbackContext) -> int:
    """Обработка выбора ПВЗ для WB"""
    query = update.callback_query
    await query.answer()

    if query.data == "back_to_wb_directions":
        # Возврат к выбору направления
        keyboard = [
            [InlineKeyboardButton("Направление 1", callback_data="wb_dir_1")],
            [InlineKeyboardButton("Направление 2", callback_data="wb_dir_2")],
            [InlineKeyboardButton("Направление 3", callback_data="wb_dir_3")],
            [InlineKeyboardButton("Направление 4", callback_data="wb_dir_4")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_wb_menu")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("📍 Выберите направление для WB:", reply_markup=reply_markup)
        return WB_DIRECTION

        # Сохраняем выбранный ПВЗ
    pvz_name = query.data.replace("wb_pvz_", "")
    context.user_data['address'] = pvz_name

    # Задаем вопрос о последнем дне хранения
    keyboard = [
        [InlineKeyboardButton("Да", callback_data="last_day_yes")],
        [InlineKeyboardButton("Нет", callback_data="last_day_no")],
    ]
    await query.edit_message_text(
        "📆 У вас предпоследний/последний день хранения на ПВЗ?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return WB_STORAGE_DAY


async def handle_storage_day(update: Update, context: CallbackContext) -> int:
    """Обработка ответа о последнем дне хранения"""
    query = update.callback_query
    await query.answer()

    # Сохраняем ответ
    context.user_data['last_storage_day'] = (query.data == "last_day_yes")

    await query.edit_message_text("💳 Введите последние 4 цифры банковской карты:")
    return WB_CARD

async def show_addresses(update: Update, context: CallbackContext) -> int:
    """Показывает список адресов ПВЗ"""
    query = update.callback_query
    await query.answer()  # Важно: подтверждаем нажатие кнопки

    service = context.user_data['service']

    try:
        # Получаем адреса для выбранного сервиса
        addresses = GROUP_SETTINGS.get(service, {})

        if not addresses:
            await query.edit_message_text(f"⚠️ Нет доступных адресов для {service}")
            return await start(update, context)

        # Создаем кнопки с адресами
        keyboard = []
        for address in addresses:
            # Используем простой и безопасный формат callback_data
            btn_data = f"addr_{address[:30].replace(' ', '_')}"  # Ограничиваем длину и заменяем пробелы
            keyboard.append([InlineKeyboardButton(address, callback_data=btn_data)])

        # Добавляем кнопку "Назад"
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_start")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        service_name = "Ozon" if service == "ozon" else "Яндекс Маркет"

        # Редактируем сообщение с новыми кнопками
        await query.edit_message_text(
            text=f"🏪 Выберите адрес ПВЗ {service_name}:",
            reply_markup=reply_markup
        )
        return SELECT_ADDRESS

    except Exception as e:
        logger.error(f"Ошибка в show_addresses: {str(e)}", exc_info=True)
        await query.edit_message_text("❌ Ошибка при загрузке адресов")
        return await start(update, context)


async def select_address(update: Update, context: CallbackContext) -> int:
    """Обработка выбора адреса"""
    query = update.callback_query
    await query.answer()

    if query.data == "back_to_start":
        return await start(update, context)

    try:
        # Получаем адрес и заменяем подчеркивания обратно на пробелы
        address = query.data.replace("addr_", "").replace("_", " ")
        context.user_data['address'] = address
        await query.edit_message_text("📷 Пришлите фото QR-кода:")
        return UPLOAD_QR

    except Exception as e:
        logger.error(f"Ошибка в select_address: {str(e)}")
        await query.edit_message_text("❌ Ошибка выбора адреса")
        return await start(update, context)


async def handle_wb_card(update: Update, context: CallbackContext) -> int:
    """Обработка номера карты для WB и запрос об отказе от товаров"""
    card = update.message.text.strip()
    if len(card) != 4 or not card.isdigit():
        await update.message.reply_text("❌ Неверный формат. Введите 4 последние цифры карты:")
        return WB_CARD

    context.user_data['card'] = card

    # Создаем клавиатуру с кнопками Да/Нет
    keyboard = [
        [InlineKeyboardButton("Да", callback_data="reject_yes")],
        [InlineKeyboardButton("Нет", callback_data="reject_no")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Нужно ли отказаться от ошибочного товара?",
        reply_markup=reply_markup
    )
    return WB_REJECT_ITEMS


async def handle_reject_choice(update: Update, context: CallbackContext) -> int:
    """Обработка выбора отказа от товаров"""
    query = update.callback_query
    await query.answer()

    if query.data == "reject_no":
        await query.edit_message_text("📷 Пришлите фото QR-кода:")
        return UPLOAD_QR

    # Если выбрано "Да"
    await query.edit_message_text("Укажите артикул или артикулы через запятую:")
    return WB_REJECT_ARTICLES


async def handle_reject_articles(update: Update, context: CallbackContext) -> int:
    """Обработка артикулов для отказа"""
    articles = update.message.text.strip()
    context.user_data['reject_articles'] = articles

    await update.message.reply_text("Прикрепите фотографию/фотографии данных товаров с WB:")
    return WB_REJECT_PHOTOS


async def handle_reject_photos(update: Update, context: CallbackContext) -> int:
    """Обработка фотографий для отказа"""
    if 'reject_photos' not in context.user_data:
        context.user_data['reject_photos'] = []

    # Сохраняем фото
    photo_file = await update.message.photo[-1].get_file()
    file_path = f"temp_reject_{update.message.message_id}.jpg"
    await photo_file.download_to_drive(file_path)
    context.user_data['reject_photos'].append(file_path)

    await update.message.reply_text("Фото сохранено. Пришлите еще фото или нажмите /done для продолжения")
    return WB_REJECT_PHOTOS

async def done_reject_photos(update: Update, context: CallbackContext) -> int:
    """Завершение загрузки фото для отказа"""
    await update.message.reply_text("📷 Теперь пришлите фото QR-кода:")
    return UPLOAD_QR


async def handle_qr_code(update: Update, context: CallbackContext) -> int:
    """Обработка QR-кода и пересылка в группу"""
    try:
        # Сохраняем QR-код
        qr_photo_file = await update.message.photo[-1].get_file()
        qr_file_path = f"temp_qr_{update.message.message_id}.jpg"
        await qr_photo_file.download_to_drive(qr_file_path)

        # Получаем текущее время
        current_time = datetime.now()
        is_late = current_time.hour >= 12  # Проверяем, что время 12:00 или позже

        # Получаем основные данные
        service = context.user_data['service']
        address = context.user_data['address']
        time = current_time.strftime("%H:%M %d.%m.%Y")

        # Формируем базовое сообщение
        base_message = (
            f"🚚 {'ПОЗДНИЙ ' if is_late else ''}Забор {service.upper()}\n"
            f"🏪 ПВЗ: {address}\n"
            f"⏰ Время: {time}\n"
            f"🧍🏻 Имя: {context.user_data['bitrix_name']}\n"
        )

        if service == "wb":
            # Добавляем информацию о карте для WB
            base_message += f"💳 Карта: ****{context.user_data['card']}\n"

            # Добавляем предупреждение если последний день
            if context.user_data.get('last_storage_day'):
                base_message += "\n‼️🔴 ВНИМАНИЕ: ПОСЛЕДНИЙ ДЕНЬ ХРАНЕНИЯ! 🔴‼️\n"

            # Добавляем информацию об отказе, если есть
            if 'reject_articles' in context.user_data:
                base_message += (
                    f"\n⚠️ Отказ от товаров:\n"
                    f"Артикулы: {context.user_data['reject_articles']}\n"
                )

            group_id = GROUP_SETTINGS["wb"][context.user_data['wb_direction']][address]
        else:
            # Для Ozon/Яндекс.Маркет просто определяем группу
            service_name = "Ozon" if service == "ozon" else "Яндекс Маркет"
            group_id = None
            for addr, gid in GROUP_SETTINGS[service].items():
                if addr == address:
                    group_id = gid
                    break

            if not group_id:
                raise ValueError(f"Адрес {address} не найден в настройках")

        # Если время позднее, отправляем уведомление в поддержку
        if is_late:
            late_notification = (
                f"⚠️ ВНИМАНИЕ: ПОЗДНИЙ QR-КОД\n\n"
                f"{base_message}\n"
                f"От: @{update.effective_user.username or 'не указан'}\n"
                f"ID: {update.effective_user.id}"
            )

            # Отправляем фото с сообщением в поддержку
            with open(qr_file_path, 'rb') as photo:
                await context.bot.send_photo(
                    chat_id=SUPPORT_CHAT_ID,
                    photo=photo,
                    caption=late_notification
                )

            # Отправляем предупреждение пользователю
            await update.message.reply_text(
                "QR-код принят. Но вы поздно его прислали, его могут не забрать"
            )

        # Подготавливаем медиагруппу для отправки в целевую группу
        media_group = []
        with open(qr_file_path, 'rb') as qr_photo:
            media_group.append(InputMediaPhoto(
                media=qr_photo,
                caption=base_message
            ))

        # Добавляем фото отказных товаров (только для WB)
        if service == "wb" and 'reject_photos' in context.user_data:
            for photo_path in context.user_data['reject_photos']:
                with open(photo_path, 'rb') as photo:
                    media_group.append(InputMediaPhoto(media=photo))

        # Отправляем медиагруппу в целевую группу
        await context.bot.send_media_group(
            chat_id=group_id,
            media=media_group
        )

        # Очистка временных файлов
        os.remove(qr_file_path)
        if 'reject_photos' in context.user_data:
            for photo_path in context.user_data['reject_photos']:
                if os.path.exists(photo_path):
                    os.remove(photo_path)
            del context.user_data['reject_photos']

        # Отправляем финальное сообщение пользователю
        if not is_late:
            await update.message.reply_text("✅ Информация отправлена!")

        return await start(update, context)

    except Exception as e:
        logger.error(f"Ошибка обработки QR: {e}", exc_info=True)

        # Очистка при ошибке
        if 'qr_file_path' in locals() and os.path.exists(qr_file_path):
            os.remove(qr_file_path)
        if 'reject_photos' in context.user_data:
            for photo_path in context.user_data['reject_photos']:
                if os.path.exists(photo_path):
                    os.remove(photo_path)

        await update.message.reply_text("❌ Ошибка обработки. Попробуйте еще раз.")
        return await start(update, context)


async def error_handler(update: object, context: CallbackContext) -> None:
    """Глобальный обработчик ошибок"""
    logger.error("Ошибка в обработчике:", exc_info=context.error)
    if update and hasattr(update, 'message'):
        await update.message.reply_text("⚠️ Произошла ошибка. Пожалуйста, попробуйте снова.")


def main() -> None:
    """Запуск бота"""
    application = Application.builder().token("7782698601:AAFS55hyBYjL_1_R7uulH7PvGL-1G8gg5pg").build()

    # Создаем обработчик команды /start
    start_handler = CommandHandler('start', start)

    # Основной обработчик диалога
    conv_handler = ConversationHandler(
        entry_points=[start_handler],
        states={
            BITRIX_NAME: [  # Новое состояние для обработки имени
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_bitrix_name),
            ],
            SELECT_SERVICE: [
                CallbackQueryHandler(select_service, pattern="^(wb|ozon|ym|txp|back_to_start)$"),
            ],
            WB_MENU: [
                CallbackQueryHandler(wb_menu, pattern="^(wb_select_direction|back_to_wb_menu|back_to_start)$"),
            ],
            WB_DIRECTION: [
                CallbackQueryHandler(wb_select_direction, pattern=r"^(wb_dir_\d+|back_to_wb_directions|back_to_wb_menu)$"),
            ],
            WB_PVZ: [
                CallbackQueryHandler(wb_select_pvz, pattern=r"^(wb_pvz_.+|back_to_wb_directions)$"),
            ],
            WB_CARD: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_wb_card)],
            WB_REJECT_ITEMS: [
                CallbackQueryHandler(handle_reject_choice, pattern=r"^(reject_yes|reject_no)$"),
            ],
            WB_REJECT_ARTICLES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reject_articles),
            ],
            WB_REJECT_PHOTOS: [
                MessageHandler(filters.PHOTO, handle_reject_photos),
                CommandHandler('done', done_reject_photos),
            ],
            SELECT_ADDRESS: [
                CallbackQueryHandler(select_address, pattern=r"^(addr_.+|back_to_start)$"),
            ],
            UPLOAD_QR: [MessageHandler(filters.PHOTO, handle_qr_code)],
            WB_STORAGE_DAY: [
                CallbackQueryHandler(handle_storage_day, pattern=r"^(last_day_yes|last_day_no)$"),
            ],
            TECH_SUPPORT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_tech_support),
            ],
        },
        fallbacks=[start_handler],
    )

    # Добавляем обработчики
    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)

    logger.info("Бот запущен и готов к работе")
    application.run_polling()

if __name__ == '__main__':
    main()
