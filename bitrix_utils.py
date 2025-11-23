import os
import json
import time
import csv
import requests
import random

from typing import List, Dict
from utils.database.sync_session_vremenno import get_db_connection


WEBHOOK_URL = 'https://top-vector.bitrix24.ru/rest/2733/2j4yet73lll4mcgi'
WEBHOOK_URL_USERS = 'https://top-vector.bitrix24.ru/rest/2733/tepa95f5f2zqht1y'
CACHE_USERS_FILE = 'bitrix_integration/cache_users.json'
CACHE_STAGES_FILE = 'bitrix_integration/cache_stages.json'
CSV_FILE = 'bitrix_integration/deals_dump.csv'
CATEGORY_IDS = [83, 107, 113, 85, 111, 115, 87, 0, 1, 3]


def bitrix_post(
        method: str,
        data: dict
) -> dict:
    """
    Запрос в битрикс API.

    param: user.get = Информация юзера по ID
           crm.deal.list = Информация о сделках.
    """
    url = f'{WEBHOOK_URL_USERS}/{method}' if method == "user.get" else f'{WEBHOOK_URL}/{method}'
    response = requests.post(url, json=data)
    response.raise_for_status()

    print(response.json())
    # logger2.info(response.json())
    return response.json()


def load_json_cache(
        filename: str
) -> dict:
    """
    Подгрузка кэшов.

    param: cache_stages (Расшифрока ID стадий)
           cache_users (Информация об отвественных)
    """
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_json_cache(
        filename: str,
        data: dict
):
    """
    Обработчик, для сохранения кэшов.
    """
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def write_csv(
        data: List[dict],
        file_path: str
):
    """
    Обработчик, для формирования CSV-файла для БД
    """
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)


def clear_cache():
    """
    Очистка кэшов.
    """
    for cache_file in [CACHE_USERS_FILE, CACHE_STAGES_FILE]:
        try:
            if os.path.exists(cache_file):
                os.remove(cache_file)
                print(f"Удален кэш: {cache_file}")
        except Exception as e:
            print(f"Ошибка удаления кэша: {e}")


def get_users_info(
        user_ids: List[int]
) -> Dict[str, dict]:
    """
    Обработчик, для отображения данных о юзере.
    Подгрузка из кэшов
    """
    os.makedirs(os.path.dirname(CACHE_USERS_FILE), exist_ok=True)
    cached_users = load_json_cache(CACHE_USERS_FILE)

    if cached_users:
        print("Берем пользователей из кэша")
        return cached_users

    print("Кэш пуст. Загружаю всех пользователей из Bitrix...")
    # logger1.info("Кэш пуст. Загружаю всех пользователей из Bitrix...")

    all_users = {}
    last_id = 0

    while True:
        body = {
            "ORDER": {"ID": "ASC"},
            "FILTER": {">ID": str(last_id)}
        }

        response = bitrix_post("user.get", body)
        result = response.get("result", [])
        if not result:
            break

        for user in result:
            uid = str(user.get("ID"))
            all_users[uid] = {
                "NAME": user.get("NAME", "Не указано"),
                "LAST_NAME": user.get("LAST_NAME", ""),
                "UF_USR_1695286718000": user.get("UF_USR_1695286718000", "")
            }

        last_id = int(result[-1]["ID"])
        time.sleep(random.uniform(0.3, 1))

    save_json_cache(CACHE_USERS_FILE, all_users)
    return all_users


def get_stages_info() -> Dict[str, str]:
    """
    Обработчик, для отображения расшифроки стадий.
    Подгрузка из кэшов
    """
    cached = load_json_cache(CACHE_STAGES_FILE)
    if cached:
        # logger1.info("Возвращаю кэш расшифровок.")
        return cached
    # logger1.info("Подгружаю новые кэши")
    response = bitrix_post('crm.status.list', {})
    stages_dict = {}
    for item in response.get('result', []):
        stages_dict[item['STATUS_ID']] = item['NAME']
    save_json_cache(CACHE_STAGES_FILE, stages_dict)
    return stages_dict


# def load_csv_to_db(csv_file: str):
#     print("Загруженные данные из CSV:")
#     with open(csv_file, 'r', encoding='utf-8') as f:
#         reader = csv.DictReader(f)
#         for row in reader:
#             print(row)
            # logger2.info(row)
def load_csv_to_db(
        csv_file: str
):
    """
    Загружает БД данными.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS bitrix_deals (
            ID TEXT PRIMARY KEY,
            STAGE_NAME TEXT,
            OPPORTUNITY TEXT,
            ASSIGNED_FULL_NAME TEXT,
            MANAGER_CARD TEXT,
            DATE_CREATE TEXT,
            CATEGORY_ID TEXT
        );
    """)
    cur.execute("DELETE FROM bitrix_deals;")

    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            opportunity = row.get('OPPORTUNITY', '').strip()
            opportunity = None if opportunity == '' else opportunity
            cur.execute("""
                INSERT INTO bitrix_deals (ID, STAGE_NAME, OPPORTUNITY, ASSIGNED_FULL_NAME, MANAGER_CARD, DATE_CREATE, CATEGORY_ID)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                row['ID'],
                row['STAGE_NAME'],
                opportunity,
                row['ASSIGNED_FULL_NAME'],
                row['MANAGER_CARD'],
                row['DATE_CREATE'],
                row['CATEGORY_ID']
            ))

    conn.commit()
    cur.close()
    conn.close()



# def update_db(deals: List[dict]):
#     print("Обновление активных сделок:")
#     for row in deals:
#         print(row)
#         logger2.info(row)


def update_db(
        deals: List[dict]
):
    """
    Обновляет базу данных.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    for row in deals:
        opportunity = None if row['OPPORTUNITY'] == '' else row['OPPORTUNITY']
        cur.execute("""
            INSERT INTO bitrix_deals (
                ID,
                STAGE_NAME,
                OPPORTUNITY,
                ASSIGNED_FULL_NAME,
                MANAGER_CARD,
                DATE_CREATE,
                CATEGORY_ID
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (ID) DO UPDATE SET
                STAGE_NAME = EXCLUDED.STAGE_NAME,
                OPPORTUNITY = EXCLUDED.OPPORTUNITY,
                ASSIGNED_FULL_NAME = EXCLUDED.ASSIGNED_FULL_NAME,
                MANAGER_CARD = EXCLUDED.MANAGER_CARD,
                DATE_CREATE = EXCLUDED.DATE_CREATE,
                CATEGORY_ID = EXCLUDED.CATEGORY_ID
        """, (
            row['ID'],
            row['STAGE_NAME'],
            opportunity,
            row['ASSIGNED_FULL_NAME'],
            row['MANAGER_CARD'],
            row['DATE_CREATE'],
            row['CATEGORY_ID']
        ))
    conn.commit()
    cur.close()
    conn.close()

