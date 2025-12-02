from utils.database.get_async_session_db import get_db_connection
import locale
import random
from typing import Optional, Dict, Tuple

import httpx, json
import datetime
import time
import asyncio
import pytz


async def get_actual_auth_data():
    async with get_db_connection() as conn:
        # rows = await conn.fetch("""
        #     SELECT phone_number, cookies, auth_token, user_agent, proxy_name, chat_id, proxy_id, last_parsing_date
        #     FROM auth_user
        #     WHERE is_verified = true
        # """)
        rows = await conn.fetch("""
                    SELECT phone_number, cookies, auth_token, user_agent, proxy_name, chat_id, proxy_id, last_parsing_date
                    FROM auth_user
                    WHERE phone_number = '+79615251514'
                """)
    auth_data_dict = {}
    for row in rows:
        auth_data_dict[row['phone_number']] = {
            'cookies': row['cookies'],
            'auth_token': row['auth_token'],
            'user_agent': row['user_agent'],
            'proxy_name': row['proxy_name'],
            'chat_id': row['chat_id'],
            'proxy_id': row['proxy_id'],
        }
    return auth_data_dict


async def start_wb_parsing():
    print("Начинаю парсинг активных доставок...")
    auth_data_dict = await get_actual_auth_data()
    for phone_number, phone_data in auth_data_dict.items():
        headers = {
            'Authorization': phone_data['auth_token'],
            'Cookie': phone_data['cookies'],
            'User-Agent': phone_data['user_agent']
        }
        user_proxy = phone_data.get('proxy_name')
        async with httpx.AsyncClient(proxy=user_proxy, timeout=10.0) as client:
            resp = await client.post("https://www.wildberries.ru/webapi/v2/lk/myorders/delivery/active", headers=headers)
            resp_nf = await client.get("https://wbxoofex.wildberries.ru/api/v2/orders", headers=headers)
            print(resp.status_code)
            print(resp_nf.status_code)



if __name__ == '__main__':
    asyncio.run(start_wb_parsing())
