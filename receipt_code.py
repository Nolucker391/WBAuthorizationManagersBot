import httpx
import json
import datetime
import psycopg2
import gspread
import time

from google.oauth2.service_account import Credentials
from utils.database.sync_session_vremenno import get_db_connection


CREDENTIALS_FILE = '/home/AuthorizationBot/cred2.json'
SPREADSHEET_ID = "1xgb2LLXxEQBs1DZyKravv8IFT67cS1zD8F12RlSGeSU"
SHEET_NAME = 'Лист1'


def log_message(message):
    """Логирует сообщение с временной меткой."""
    current_time = datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    print(f"{current_time}: {message}")


def create_service_obj():
    """Авторизует Google Sheets API и возвращает объект клиента gspread."""
    creds = Credentials.from_service_account_file(
        CREDENTIALS_FILE,
        scopes=['https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive']
    )
    return gspread.authorize(creds)


def fetch_data_from_postgres():
    """Извлекает данные из базы данных PostgreSQL."""
    connection = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        query = f"""
                    SELECT 
                        phone_number,
                        code
                    FROM 
                        delivery_codes dc
                """
        cursor.execute(query)
        records = cursor.fetchall()
        return records

    except (Exception, psycopg2.Error) as error:
        log_message(f"Ошибка при извлечении данных из PostgreSQL: {error}")
        return None
    finally:
        if connection:
            cursor.close()
            connection.close()


def update_google_sheet(data, sheet_name):
    """Обновляет данные в Google Sheets."""
    if data is None or len(data) == 0:
        log_message(f"Нет данных для обновления в Google Sheets для листа: {sheet_name}")
        return

    client = create_service_obj()
    try:
        sheet = client.open_by_key(SPREADSHEET_ID).worksheet(sheet_name)
    except gspread.SpreadsheetNotFound:
        log_message("Лист в Google не найден. Пожалуйста, проверьте идентификатор листа.")
        return
    except gspread.WorksheetNotFound:
        log_message(f"Лист '{sheet_name}' не найден. Пожалуйста, проверьте название листа")
        return

    formatted_data = [
        [str(cell) if isinstance(cell, str) else cell for cell in row] for row in data
    ]

    log_message(f"Данные для обновления: {formatted_data}")

    log_message(f"Очищение данных в Google Sheet '{sheet_name}'...")
    sheet.clear()  # Очищаем лист

    log_message(f"Данные добавлены в Google Sheet таблицу '{sheet_name}'...")

    # Добавляем заголовки
    headers = ["Номер телефона", "Код получения товаров"]
    if len(formatted_data[0]) != len(headers):
        log_message(f"Ошибка: Число столбцов данных ({len(formatted_data[0])}) не совпадает с числом столбцов заголовков ({len(headers)})")
        return

    all_data = [headers] + formatted_data  # Добавляем заголовки к данным

    # Обновляем данные с использованием USER_ENTERED для форматирования как числа
    sheet.update(range_name=f"A1:{chr(64 + len(headers))}{len(all_data)}", values=all_data, value_input_option='USER_ENTERED')
    time.sleep(20)


def main():
    """Основной процесс."""
    # Шаг 1: Получить пользователей
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT phone_number, chat_id, cookies, auth_token, user_agent
        FROM auth_user
        WHERE is_verified = true
    """)
    users = cur.fetchall()
    conn.close()

    # Шаг 2: Обработка пользователей
    for phone_number, chat_id, cookies, auth_token, user_agent in users:
        if not cookies:
            print(f"Cookies отсутствуют для пользователя {phone_number}. Пропуск...")
            continue

        # Подготовка cookies
        try:
            parsed_cookies = {k.strip(): v for k, v in (pair.split('=', 1) for pair in cookies.split(';'))}
        except Exception as e:
            print(f"Ошибка парсинга cookies для пользователя {phone_number}: {e}")
            continue

        # Отправка запроса
        headers = {"Authorization": auth_token, "User-Agent": user_agent}
        response = httpx.get(
            "https://code-generator.wb.ru/generate/api/v1/code",
            headers=headers,
            cookies=parsed_cookies
        )

        if response.status_code != 200:
            print(f"Ошибка получения кода для пользователя {phone_number}: {response.status_code}")
            continue

        # Обработка ответа
        try:
            result = response.json()
            user_id_code = result["code"].split('_')[0]
            code = result["code"].split('_')[1]
            state = result["state"]
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            print(f"Ошибка обработки ответа для пользователя {phone_number}: {e}")
            continue

        # Сохранение в базу данных
        save_to_database(phone_number, code, state, chat_id, user_id_code)

    # Шаг 3: Обновить Google Sheet с данными из базы данных
    log_message("Извлечение данных из таблицы delivery_codes")
    data = fetch_data_from_postgres()
    if data:
        log_message("Обновление Google Sheet с данными...")
        update_google_sheet(data, SHEET_NAME)
        log_message("Процесс завершён.")

def save_to_database(phone_number, code, state, chat_id, user_id_code):
    """Сохраняет код в таблицу."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # user_id_code = code.split('_')[0]
        cur.execute("""
            INSERT INTO delivery_codes (chat_id, phone_number, state, code , user_id_code)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (chat_id, phone_number) 
            DO UPDATE SET state = EXCLUDED.state, code = EXCLUDED.code, user_id_code = EXCLUDED.user_id_code
        """, (chat_id, phone_number, state, code , user_id_code))
        conn.commit()
        print(f"Код для пользователя {phone_number} сохранён.")
    except Exception as e:
        print(f"Ошибка сохранения кода для пользователя {phone_number}: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f'[{current_time}] Парсинг кодов и обновление данных в Google Sheets')
    main()
