import json
import asyncio
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

from utils.database.get_async_session_db import get_db_connection


class WBActiveOrdersParser:
    def __init__(self, json_path: str, spreadsheet_key: str, creds_path: str):
        self.json_path = json_path
        self.spreadsheet_key = spreadsheet_key
        self.creds_path = creds_path
        self.office_ids = self._load_wb_office_ids()
        self.client = self._get_gspread_client()
        print(f"Загружено {len(self.office_ids)} office_id из direction_decoding.json (wb).")

    def _load_wb_office_ids(self):
        """Загрузить все office_id из direction_decoding.json -> wb"""
        with open(self.json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        wb_data = data.get("wb", {})
        office_ids = set()

        for direction, addresses in wb_data.items():
            for _, office_id in addresses.items():
                office_ids.add(str(office_id))

        return office_ids

    def _get_gspread_client(self):
        """Авторизация в Google API"""
        scope = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        creds = Credentials.from_service_account_file(self.creds_path)
        creds = creds.with_scopes(scope)
        return gspread.authorize(creds)

    async def get_filtered_delivery_info(self) -> pd.DataFrame:
        """Вытащить из delivery_info_active только нужные поля с фильтрацией по office_id"""
        async with get_db_connection() as conn:
            query = """
                SELECT product_id, name, phone_number, order_date, office_address, tracking_status, last_date_pickup, price
                FROM delivery_info_active
                WHERE office_id = ANY($1);
            """
            rows = await conn.fetch(query, list(self.office_ids))

        if not rows:
            return pd.DataFrame()

        # Преобразуем записи в DataFrame
        df = pd.DataFrame([dict(record) for record in rows])
        return df

    def update_google_sheet(self, dataframe: pd.DataFrame):
        """Очистить лист с сохранением первой строки и вставить данные со 2-й строки"""
        spreadsheet = self.client.open_by_key(self.spreadsheet_key)

        try:
            worksheet = spreadsheet.worksheet("Активные заказы WB")
        except gspread.exceptions.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title="Активные заказы WB", rows="100", cols="20")

        # Получаем первую строку
        first_row = worksheet.row_values(1)

        # Полная очистка листа, кроме первой строки
        worksheet.clear()
        if first_row:
            worksheet.update(range_name="A1", values=[first_row])

        if not dataframe.empty:
            # Преобразуем даты в строки
            for col in dataframe.columns:
                if pd.api.types.is_datetime64_any_dtype(dataframe[col]) or pd.api.types.is_object_dtype(dataframe[col]):
                    dataframe[col] = dataframe[col].astype(str)

            # Вставляем данные начиная со 2-й строки
            values = dataframe.values.tolist()
            worksheet.update(range_name="A2", values=values)
            print(f"В таблицу выгружено {len(values)} строк.")
        else:
            worksheet.update(range_name="A2", values=[["Нет данных"]])

            print("Нет совпадений, выгрузили 'Нет данных'.")

    async def run(self, interval: int = 1800):
        """Запуск цикла каждые interval секунд (по умолчанию 30 мин)"""
        while True:
            print("=== Запуск парсинга ===")
            df = await self.get_filtered_delivery_info()
            self.update_google_sheet(df)
            print(f"Жду {interval // 60} минут до следующего запуска...\n")
            await asyncio.sleep(interval)


if __name__ == "__main__":
    parser = WBActiveOrdersParser(
        json_path="directions_decoding.json",
        spreadsheet_key="1MfEmSPcrhxKQdfqPIRltO4_Fd1y_c07Mmnp3s1IBKGY",
        creds_path="creditions_google.json",
    )
    asyncio.run(parser.run())
