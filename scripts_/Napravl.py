import apiclient
import psycopg2
import gspread
import datetime
import time
import httplib2
from oauth2client.service_account import ServiceAccountCredentials
from google.oauth2.service_account import Credentials
from utils.database.sync_session_vremenno import get_db_connection


table_to_sheet = {
    'users_order': 'Лист1',
}


def log_message(message):
    current_time = datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    print(f"{current_time}: {message}")


def create_service_obj():
    # from Google Developer Console
    CREDENTIALS_FILE = '/home/AuthorizationBot/cred.json'
    # Authorize and create the service object
    credentials = ServiceAccountCredentials.from_json_keyfile_name(
        CREDENTIALS_FILE,
        ['https://www.googleapis.com/auth/spreadsheets',
         'https://www.googleapis.com/auth/drive']
    )
    http_auth = credentials.authorize(httplib2.Http())
    service = apiclient.discovery.build('sheets', 'v4', http=http_auth, cache_discovery=False)
    return service


def format_data_for_sheet(data):
    formatted_data = []
    for row in data:
        formatted_row = []  # Создаём новую строку для каждой итерации
        for cell in row:
            if isinstance(cell, datetime.date):  # Проверяем, является ли ячейка объектом date
                formatted_row.append(cell.strftime('%Y-%m-%d'))  # Преобразуем дату в строку
            else:
                formatted_row.append(str(cell))  # Преобразуем остальные данные в строку
        formatted_data.append(formatted_row)  # Добавляем строку в итоговый список
    return formatted_data


def chunked_data(data, chunk_size):
    """Разделяет данные на блоки заданного размера."""
    for i in range(0, len(data), chunk_size):
        yield data[i:i + chunk_size]


def fetch_data_from_postgres(spreadsheet_id):
    connection = None
    # Коннектимся к базе данных
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
 # Номер телефона Артикул Цена Адрес ПВЗ Статус заказа в кабинете wb Код получения товаров User_id
 # phone_number article
 # Дата забора Номер телефона Артикул Цена Адрес ПВЗ Статус заказа с ПВЗ Коды забора товара
    #     "1jcAEXuTWn-2eHxAnJLiE1hFgb4uMk5-hMGtXFpR72nk", # Полученные заказы направление 1 поля Дата забора	Номер телефона	Артикул	Наименование	Статус заказа с ПВЗ	Адрес ПВЗ
    #     "1ne-Wv5XiaArd3SQ33pPIA3nG0TKT9lZbOFXCqT_mxIY" # Направление 1 коды поля Номер телефона	Артикул	Цена	Адрес ПВЗ	Статус заказа в кабинете wb	Код получения товаров	User_id
        if spreadsheet_id in ["1jcAEXuTWn-2eHxAnJLiE1hFgb4uMk5-hMGtXFpR72nk","1qIOlKzE8jR4hfNjIOHhzOOf0WPDOJkME-ok_83vrmVI"]:
            query = f"""
                        SELECT 
                            uo.order_date,
                            uo.phone_number,
                            uo.product_id,
                            uo.price,
                            uo.office_address,
                            uo.status,
                            dc.code
                        FROM 
                            users_order uo
                        LEFT JOIN delivery_codes dc ON uo.phone_number = dc.phone_number
                        WHERE 
                            order_date >= '2025-01-01'
                            AND status = 'Purchased'
                        ORDER BY order_date desc;
                    """
        elif spreadsheet_id in ["1pct-T5Uz9xTTJrd1XXclYaNoJrJgv6AsId9gpol2HUo","1dKOcCVL13xfquNrpa1m6uhI4FtWm9T5AVs8q2iYXioQ","1N2FnVTFwFbS339QZpeyN1lJoPMQ27OweEJNB5xsU5hI"]:
            query = f"""
                        SELECT 
                            di.phone_number,
                            di.product_id,
                            di.price,
                            di.office_address,
                            di.tracking_status,
                            dc.code,
                            dc.user_id_code,
                            di.order_date
                        FROM 
                            delivery_info di
                        LEFT JOIN delivery_codes dc ON di.phone_number = dc.phone_number
                        WHERE tracking_status = 'Готов к выдаче'
                                """
        else:
            print(f"Неизвестный spreadsheet_id : {spreadsheet_id}")
            return None

        cursor.execute(query)
        records = cursor.fetchall()
        return records

    except (Exception, psycopg2.Error) as error:
        log_message(f"Error while fetching data from PostgreSQL: {error}")
        return None
    finally:
        if connection:
            cursor.close()
            connection.close()


def chunk_data(data, chunk_size):
    """Разбивает данные на батчи заданного размера."""
    for i in range(0, len(data), chunk_size):
        yield data[i:i + chunk_size]


def update_google_sheet(data, sheet_name, headers, spreadsheet_id):
    if data is None:
        log_message(f"Нет данных для обновления в Google Sheets для sheet: {sheet_name}")
        return

    # Аутентификация с помощью Google Sheets API
    creds = Credentials.from_service_account_file(
        'cred.json',
        scopes=['https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive']
    )
    client = gspread.authorize(creds)

    try:
        sheet = client.open_by_key(spreadsheet_id).worksheet(sheet_name)
    except gspread.SpreadsheetNotFound:
        log_message("Лист в Google не найден. Пожалуйста, проверьте идентификатор листа.")
        return
    except gspread.WorksheetNotFound:
        log_message(f"Лист '{sheet_name}' не найден. Пожалуйста, проверьте название листа.")
        return

    # Очищаем лист со 2 строки и добавляем заголовки
    sheet.batch_clear(["A2:Z"])
    # Форматируем данные
    formatted_data = format_data_for_sheet(data)
    chunk_size = 5000  # Размер блока для каждого обновления

    try:
        # Добавляем данные по частям
        for chunk in chunked_data(formatted_data, chunk_size):
            sheet.append_rows(chunk)  # Добавляем блок данных
            log_message(f"Добавлено {len(chunk)} строк в Google Sheet: {sheet_name}.")
            time.sleep(20)
        log_message(f"Данные успешно обновлены в Google Sheet: {sheet_name}.")
    except Exception as e:
        log_message(f"Ошибка при обновлении данных в Google Sheet: {e}")


def main():
    log_message("Процесс начат")

    # Список всех spreadsheet_id, которые нужно обновить
    spreadsheet_ids = [
        "1jcAEXuTWn-2eHxAnJLiE1hFgb4uMk5-hMGtXFpR72nk", # Полученные заказы направление 1
        "1qIOlKzE8jR4hfNjIOHhzOOf0WPDOJkME-ok_83vrmVI",  # Полученные сделки для Алёны Сергеевны
        "1pct-T5Uz9xTTJrd1XXclYaNoJrJgv6AsId9gpol2HUo",  # Направление 1 коды новая
        "1dKOcCVL13xfquNrpa1m6uhI4FtWm9T5AVs8q2iYXioQ",  # Направление 2 коды новая
        "1N2FnVTFwFbS339QZpeyN1lJoPMQ27OweEJNB5xsU5hI",  # Направление 3 коды новая
    ]

    for table_name, sheet_name in table_to_sheet.items():
        log_message(f"Извлечение данных из таблицы: {table_name}")
        for spreadsheet_id in spreadsheet_ids:
            data = fetch_data_from_postgres(spreadsheet_id)
            if data:
                formatted_data = format_data_for_sheet(data)
                log_message(f"Обновление Google Sheet для таблицы: {table_name} в spreadsheet_id: {spreadsheet_id}")
                update_google_sheet(data, sheet_name,None, spreadsheet_id)
    log_message("Процесс завершен")
# def main():
#     log_message("Процесс начат")
#     # Список всех spreadsheet_id, которые нужно обновить
#     spreadsheet_ids = [
#         "1jcAEXuTWn-2eHxAnJLiE1hFgb4uMk5-hMGtXFpR72nk",
#         "1ne-Wv5XiaArd3SQ33pPIA3nG0TKT9lZbOFXCqT_mxIY"
#     ]
#     table_headers = {
#         "users_order": ["Дата забора", "Номер телефона", "Артикул", "Наименование", "Статус заказа с ПВЗ", "Адрес ПВЗ"]
#     }
#     for table_name, sheet_name in table_to_sheet.items():
#         log_message(f"Извлечение данных из таблицы: {table_name}")
#         data = fetch_data_from_postgres()
#         if data:
#             headers = table_headers.get(table_name)
#             if headers:
#                 log_message(f"Обновление Google Sheet для таблицы: {table_name}")
#                 update_google_sheet(data, sheet_name, headers)
#     log_message("Процесс завершен")


if __name__ == "__main__":
    main()

