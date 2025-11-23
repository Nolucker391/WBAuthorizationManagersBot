import time
import random

from typing import List, Dict, Any
from dateutil import parser

from bitrix_utils import (
    bitrix_post,
    clear_cache,
    get_users_info,
    get_stages_info,
    CATEGORY_IDS,
    update_db
)


def get_active_deals(category_ids: List[int]) -> List[Dict[str, Any]]:
    deals = []
    last_id = 0

    while True:
        body = {
            "SELECT": ["ID", "STAGE_ID", "OPPORTUNITY", "ASSIGNED_BY_ID", "CATEGORY_ID", "DATE_CREATE", "DATE_MODIFY"],
            "FILTER": {
                "@CATEGORY_ID": category_ids,
                "STAGE_SEMANTIC_ID": "P",
                ">ID": str(last_id)
            },
            "ORDER": {"ID": "ASC"},
            "LIMIT": 50
        }
        response = bitrix_post("crm.deal.list", body)
        chunk = response.get("result", [])
        if not chunk:
            break
        deals.extend(chunk)
        last_id = int(chunk[-1]["ID"])
        time.sleep(random.uniform(0.3, 1))
    return deals


def main():
    print("Очистка кэша...")
    clear_cache()
    while True:
        print("Загружаем сделки...")
        deals = get_active_deals(CATEGORY_IDS)
        print(f"Получено сделок: {len(deals)}")

        assigned_ids = list({int(d['ASSIGNED_BY_ID']) for d in deals if d.get('ASSIGNED_BY_ID')})
        print(f"Найдено уникальных ответственных: {len(assigned_ids)}")

        print("Загружаем данные ответственных...")
        users = get_users_info(assigned_ids)

        print("Загружаем стадии...")
        stages = get_stages_info()

        final_data = []
        for d in deals:
            uid = str(d.get('ASSIGNED_BY_ID'))
            user = users.get(uid, {})

            # full_name = f"{user.get('NAME', '')} {user.get('LAST_NAME', '')}".strip()
            first = user.get('NAME', '')
            last = user.get('LAST_NAME', '')
            full_name = f"{first} {last}".strip()

            if not full_name:
                full_name = "Неизвестно"

            raw_date = d.get("DATE_CREATE", "")
            formatted_date = ""
            try:
                if raw_date:
                    dt = parser.isoparse(raw_date)
                    formatted_date = dt.strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                formatted_date = ""

            final_data.append({
                "ID": d.get("ID"),
                "STAGE_NAME": stages.get(d.get("STAGE_ID"), "Неизвестно"),
                "OPPORTUNITY": d.get("OPPORTUNITY", "0.00"),
                "ASSIGNED_FULL_NAME": full_name,
                "MANAGER_CARD": user.get("UF_USR_1695286718000", ''),
                "DATE_CREATE": formatted_date,
                "CATEGORY_ID": d.get("CATEGORY_ID", "0")
            })

        update_db(final_data)
        print("Обновление завершено. Перерыв 30 минут...\n")
        time.sleep(1800)


if __name__ == '__main__':
    print("Начинаю мониторинг сделок.")
    main()
