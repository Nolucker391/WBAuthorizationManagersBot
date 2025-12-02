import pandas as pd
import gspread
import time

from gspread_dataframe import set_with_dataframe
from google.oauth2.service_account import Credentials

from utils.database.sync_session_vremenno import get_db_connection


def start_parse():
    print("Начинаю заполнение Google Таблицы.")

    dataframe = get_dataframe()
    parse_google_table(dataframe)

    print("Заполнение успешно завершено. Отправляюсь на перерыв (4 часа).")
    time.sleep(14400)


def get_dataframe():
    with get_db_connection() as connection:
        query = "select * from auth_user;"
        dataframe = pd.read_sql(query, connection)

    csv_path = "auth_user_table.csv"
    dataframe.to_csv(csv_path, index=False)

    return dataframe


def parse_google_table(dataframe):
    scope = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    #
    creds = Credentials.from_service_account_file('new_0212creds.json')
    creds = creds.with_scopes(scope)
    client = gspread.authorize(creds)

    spreadsheet = client.open_by_key("1MfEmSPcrhxKQdfqPIRltO4_Fd1y_c07Mmnp3s1IBKGY")

    try:
        worksheet = spreadsheet.worksheet("Авторизации Менеджеров")
        worksheet.clear()
    except gspread.exceptions.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title="Лист1", rows="100", cols="20")

    set_with_dataframe(worksheet, dataframe)

    print("Данные auth_user успешно экспортированы в Google Таблицу.")


if __name__ == "__main__":
    start_parse()
