import random
import httpx, json
import datetime
import asyncio

import psycopg2
import time

from psycopg2.extras import execute_values
from dateutil import parser

from utils.database.get_async_session_db import get_db_connection, get_db_driver_connection
from utils.proxies import get_valid_proxy, change_proxy_ip


ORDER_WB_URL = 'https://www.wildberries.ru/webapi/lk/myorders/archive/get'
# LINKS_WB_URL = 'https://www.wildberries.ru/webapi/lk/receipts/data?count=10'
LINKS_WB_URL = 'https://astro.wildberries.ru/api/v1/receipt-api/v1/receipts'

feedback_WB_URL = 'https://www.wildberries.ru/webapi/lk/discussion/feedback/data?type=comments'
DELIVERY_WB_URL = 'https://www.wildberries.ru/webapi/v2/lk/myorders/delivery/active' # deliveryPrice

MODEM_FALLBACK_PROXY = "http://admin:admin@94.143.43.213:30609"
async def change_gather(conn, phone_number: str, phone_data: dict) -> bool:
    """
    Пробует сменить IP текущего прокси или подобрать новый.
    Возвращает True, если получилось сменить IP или назначить новый прокси.
    """
    user_proxy = phone_data.get('proxy_name')

    if user_proxy:
        changed = await change_proxy_ip(user_proxy)
        if changed:
            return True

    new_proxy = await get_valid_proxy(phone_number, phone_data.get('chat_id'))
    if not new_proxy:
        return False

    proxy_record = await conn.fetchrow(
        "SELECT id FROM mobile_proxies WHERE name = $1", new_proxy
    )
    if proxy_record:
        await conn.execute(
            """
            UPDATE auth_user
            SET proxy_name = $1, proxy_id = $2
            WHERE phone_number = $3 AND chat_id = $4
            """,
            new_proxy,
            proxy_record['id'],
            phone_number,
            phone_data.get('chat_id')
        )

    phone_data['proxy_name'] = new_proxy
    print(f"Сменил прокси на {new_proxy}, пробую снова...")
    return True


async def start_wb_parsing():
    """
    Асинхронный запуск парсинга
    """
    while True:
        print("Начинаю парсинг...")
        auth_data_dict = await get_actual_auth_data()

        # Парсим заказы
        await asyncio.gather(*[
            parse_orders({phone: data}, is_full_parsing=data['is_full_parsing'])
            for phone, data in auth_data_dict.items()
        ])

        # Парсим чеки
        await asyncio.gather(*[
            parse_links({phone: data}, is_full_parsing=data['is_full_parsing'])
            for phone, data in auth_data_dict.items()
        ])

        print("Парсинг окончен. Перерыв 2 часа.")
        await asyncio.sleep(7200)


async def get_actual_auth_data():
    """
    Получает актуальных пользователей из БД и определяет, нужен ли полный парсинг.
    """
    today_limit = datetime.date(2025, 7, 24)
    async with get_db_connection() as conn:
        rows = await conn.fetch("""
            SELECT phone_number, cookies, auth_token, user_agent, proxy_name, chat_id, proxy_id, last_parsing_date
            FROM auth_user
            WHERE is_verified = true
        """)
        # rows = await conn.fetch("""
        #             SELECT phone_number, cookies, auth_token, user_agent, proxy_name, chat_id, proxy_id, last_parsing_date
        #             FROM auth_user
        #             WHERE phone_number = '+77750511917'
        #         """)

    auth_data_dict = {}
    for row in rows:
        last_parsing_date = row['last_parsing_date']
        is_full_parsing = (
            last_parsing_date is None or
            (isinstance(last_parsing_date, datetime.date) and last_parsing_date < today_limit)
        )
        auth_data_dict[row['phone_number']] = {
            'cookies': row['cookies'],
            'auth_token': row['auth_token'],
            'user_agent': row['user_agent'],
            'proxy_name': row['proxy_name'],
            'chat_id': row['chat_id'],
            'proxy_id': row['proxy_id'],
            'is_full_parsing': is_full_parsing
        }
    return auth_data_dict


async def get_office_address(office_id, headers, proxy):
    """
    Получает адрес офиса WB по ID
    """
    try:
        proxy_url = f"http://{proxy}" if proxy and not str(proxy).startswith("http") else proxy
        transport = httpx.AsyncHTTPTransport(proxy=proxy_url) if proxy_url else None
        async with httpx.AsyncClient(transport=transport, timeout=6.0) as client:

            resp = await client.request(
                method="POST",
                url="https://www.wildberries.ru/webapi/lk/myorders/delivery/offices",
                headers=headers,
                data={"ids": [office_id]}
            )
        resp.raise_for_status()
        office_data = resp.json().get("value", {})
        return office_data.get(str(office_id), {}).get("address")
    except Exception as e:
        print(f"Не удалось получить адрес для office_id {office_id}: {e}")
        return None


async def parse_orders(auth_data_dict, is_full_parsing=True):
    if not auth_data_dict:
        return

    processed_count = 0
    failed_users = []

    async with get_db_connection() as conn:
        for phone_number, phone_data in auth_data_dict.items():
            print(f"[{datetime.datetime.now()}] Начинаю парсинг заказов для {phone_number}")

            db_data = []
            headers = {
                'Authorization': phone_data['auth_token'],
                'Cookie': phone_data['cookies'],
                'User-Agent': phone_data['user_agent']
            }
            proxy_name = phone_data.get('proxy_name')
            if proxy_name and not proxy_name.startswith("http"):
                parsing_proxy = f"http://{proxy_name}"
            else:
                parsing_proxy = proxy_name
            print(f"Использую прокси: {parsing_proxy}")
            offset = 0
            limit = 250

            proxy_retry_done = False
            modem_switched = False
            success = False
            unauthorized = False

            async def handle_proxy_issue(reason: str) -> bool:
                nonlocal proxy_retry_done, modem_switched, parsing_proxy
                print(reason)
                if not proxy_retry_done:
                    print("Пробую смену IP")
                    changed = await change_gather(conn, phone_number, phone_data)
                    if changed:
                        proxy_retry_done = True
                        new_proxy_name = phone_data.get('proxy_name')
                        parsing_proxy = (
                            f"http://{new_proxy_name}"
                            if new_proxy_name and not new_proxy_name.startswith("http")
                            else new_proxy_name
                        )
                        print("IP прокси успешно сменён, повторяю запрос...")
                        await asyncio.sleep(2.5)
                        return True
                    else:
                        print("Не удалось сменить IP, попробую сменить модем...")

                if not modem_switched:
                    print(f"Смена модема для {phone_number}...")
                    parsing_proxy = MODEM_FALLBACK_PROXY
                    modem_switched = True
                    await asyncio.sleep(2.5)
                    return True

                print(f"Ошибка после смены IP и модема. Пропускаю {phone_number}.")
                return False

            while True:
                await asyncio.sleep(random.random())
                request_data = {'limit': limit, 'offset': offset, 'type': 'all'}
                if is_full_parsing:
                    request_data.update({
                        'from': '2019-01-01',
                        'to': datetime.datetime.now().strftime('%Y-%m-%d')
                    })

                try:
                    transport = httpx.AsyncHTTPTransport(proxy=parsing_proxy) if parsing_proxy else None
                    async with httpx.AsyncClient(transport=transport, timeout=10.0) as client:
                        resp = await client.post(
                            ORDER_WB_URL,
                            headers=headers,
                            data=request_data
                        )

                    if resp.status_code == 401:
                        print(f'401 Unauthorized для {phone_number}')
                        unauthorized = True
                        break
                    if resp.status_code == 498:
                        if await handle_proxy_issue(
                            f"Получен статус 498 при обращении к API заказов для {phone_number}"
                        ):
                            continue
                        failed_users.append(phone_number)
                        break

                except httpx.TimeoutException:
                    print(f"Таймаут при обращении к {phone_number}")
                    continue
                except httpx.ProxyError:
                    if await handle_proxy_issue(
                        f"Неактуал авторизация для {phone_number}. Скорее всего отключен прокси"
                    ):
                        continue
                    failed_users.append(phone_number)
                    break
                except httpx.ConnectError as e:
                    if await handle_proxy_issue(f"Проблема с прокси {parsing_proxy}: {e}"):
                        continue
                    failed_users.append(phone_number)
                    break
                except httpx.RequestError as e:
                    print(f"Ошибка запроса: {e}")
                    continue
                except Exception as e:
                    print(f"Непонятная ошибка: {e}")
                    import traceback
                    print(f"Ошибка запроса: {repr(e)}")
                    traceback.print_exc()
                    continue

                try:
                    orders = resp.json().get('value', {}).get('archive', [])
                except json.JSONDecodeError:
                    if phone_data['chat_id']:
                        await conn.execute("""
                            UPDATE auth_user SET is_verified = FALSE 
                            WHERE chat_id = $1 AND phone_number = $2
                        """, phone_data['chat_id'], phone_number)
                        await conn.commit()
                    break

                success = True

                for order in orders:
                    office = order.get('office')
                    office_id = order.get('officeId')
                    my_date = parser.parse(order.get('lastDate')).date() if order.get('lastDate') else None
                    price = int(order.get('price') or 0)
                    delivery_price = int(order.get('logisticsCost') or 0)
                    total_price = price + delivery_price
                    address = office.get('address') if office else await get_office_address(
                        office_id, headers, parsing_proxy or phone_data.get('proxy_name')
                    )

                    db_data.append([
                        order.get('rId'),
                        order.get('code1S'),
                        order.get('name'),
                        phone_number,
                        my_date,
                        price,
                        order.get('paymentType'),
                        order.get('status'),
                        order.get('supplierId'),
                        office_id,
                        address,
                        str(order.get('shkId')) if order.get('shkId') is not None else None,
                        total_price,
                        delivery_price
                    ])

                if len(orders) < limit or not is_full_parsing:
                    break
                offset += limit

            if not success:
                if not unauthorized and phone_number not in failed_users:
                    failed_users.append(phone_number)
                continue

            print(f"Количество записей для вставки: {len(db_data)}")

            if db_data:
                await conn.executemany("""
                    INSERT INTO users_order (
                        order_id, product_id, name, phone_number, order_date, price,
                        payment_type, status, supplier_id, office_id, office_address,
                        shkId, total_price, delivery_price
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                    ON CONFLICT (order_id) DO UPDATE SET
                        product_id = EXCLUDED.product_id,
                        name = EXCLUDED.name,
                        phone_number = EXCLUDED.phone_number,
                        order_date = EXCLUDED.order_date,
                        price = EXCLUDED.price,
                        payment_type = EXCLUDED.payment_type,
                        status = EXCLUDED.status,
                        supplier_id = EXCLUDED.supplier_id,
                        office_id = EXCLUDED.office_id,
                        office_address = EXCLUDED.office_address,
                        shkId = EXCLUDED.shkId,
                        total_price = EXCLUDED.total_price,
                        delivery_price = EXCLUDED.delivery_price
                """, db_data)

                async with get_db_driver_connection() as driver_conn:
                    await driver_conn.executemany("""
                        INSERT INTO purchases (
                            order_id, product_id, name, phone_number, order_date, price,
                            payment_type, status, supplier_id, office_id, office_address,
                            shkId, total_price, delivery_price
                        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                        ON CONFLICT (order_id) DO UPDATE SET
                            product_id = EXCLUDED.product_id,
                            name = EXCLUDED.name,
                            phone_number = EXCLUDED.phone_number,
                            order_date = EXCLUDED.order_date,
                            price = EXCLUDED.price,
                            payment_type = EXCLUDED.payment_type,
                            status = EXCLUDED.status,
                            supplier_id = EXCLUDED.supplier_id,
                            office_id = EXCLUDED.office_id,
                            office_address = EXCLUDED.office_address,
                            shkId = EXCLUDED.shkId,
                            total_price = EXCLUDED.total_price,
                            delivery_price = EXCLUDED.delivery_price
                    """, db_data)

            await conn.execute("""
                UPDATE auth_user
                SET last_parsing_date = CURRENT_DATE
                WHERE phone_number = $1
            """, phone_number)

            processed_count += 1
            print(f"[{datetime.datetime.now()}] parse_orders завершен для {phone_number}")

    print(f"\n[{datetime.datetime.now()}] Обработано номеров: {processed_count}")
    if failed_users:
        print("\n- Проблемные пользователи (ошибки или прокси-баны):")
        for u in failed_users:
            print(f"  - {u}")
    else:
        print("\n- Все пользователи обработаны без критических ошибок.")

async def parse_links(auth_data_dict, is_full_parsing=True):
    if not auth_data_dict:
        return

    async with get_db_connection() as conn:
        for phone_number, phone_data in auth_data_dict.items():
            db_data = []
            headers = {
                'Authorization': phone_data['auth_token'],
                'Cookie': phone_data['cookies'],
                'User-Agent': phone_data['user_agent'],
                'Accept': 'application/json',
            }
            proxy_name = phone_data.get('proxy_name')
            if proxy_name and not proxy_name.startswith("http"):
                parsing_proxy = f"http://{proxy_name}"
            else:
                parsing_proxy = proxy_name
            print(f"Использую прокси: {parsing_proxy}")
            proxy_retry_done = False
            modem_switched = False
            next_receipt_uid = None
            success = False
            unauthorized = False

            async def handle_proxy_issue(reason: str) -> bool:
                nonlocal proxy_retry_done, modem_switched, parsing_proxy
                print(reason)
                if not proxy_retry_done:
                    print("Пробую смену IP")
                    changed = await change_gather(conn, phone_number, phone_data)
                    if changed:
                        proxy_retry_done = True
                        new_proxy_name = phone_data.get('proxy_name')
                        parsing_proxy = (
                            f"http://{new_proxy_name}"
                            if new_proxy_name and not new_proxy_name.startswith("http")
                            else new_proxy_name
                        )
                        print("IP прокси успешно сменён, повторяю запрос...")
                        await asyncio.sleep(2.5)
                        return True
                    else:
                        print("Не удалось сменить IP, попробую сменить модем...")

                if not modem_switched:
                    print(f"Смена модема для {phone_number} (receipts)...")
                    parsing_proxy = MODEM_FALLBACK_PROXY
                    modem_switched = True
                    await asyncio.sleep(2.5)
                    return True

                print(f"Ошибка после смены IP и модема. Пропускаю {phone_number} (receipts).")
                return False

            while True:
                await asyncio.sleep(random.random())
                request_params = {'receiptsPerPage': 20 if is_full_parsing else 10}
                if is_full_parsing and next_receipt_uid:
                    request_params['nextReceiptUid'] = next_receipt_uid

                try:
                    transport = httpx.AsyncHTTPTransport(proxy=parsing_proxy) if parsing_proxy else None
                    async with httpx.AsyncClient(transport=transport, timeout=6.0) as client:
                        resp = await client.get(
                            LINKS_WB_URL,
                            headers=headers,
                            params=request_params
                        )

                except httpx.TimeoutException:
                    print(f"Таймаут при обращении к {LINKS_WB_URL}")
                    continue
                except httpx.ProxyError:
                    if await handle_proxy_issue(
                        f"Неактуал авторизация для {phone_number} при загрузке чеков. Скорее всего отключен прокси"
                    ):
                        continue
                    break
                except httpx.ConnectError as e:
                    if await handle_proxy_issue(f"Ошибка подключения: {e}"):
                        continue
                    break
                except httpx.RequestError as e:
                    print(f"Ошибка запроса: {e}")
                    continue
                except Exception as e:
                    print(f"Непонятная ошибка: {e}")
                    continue

                if resp.status_code == 401:
                    print(f"401 Unauthorized для {phone_number}")
                    unauthorized = True
                    break

                if resp.status_code == 498:
                    if await handle_proxy_issue(
                        f"Получен статус 498 при запросе чеков для {phone_number}"
                    ):
                        continue
                    break

                try:
                    resp_data = resp.json().get('data', {}).get('result', {}).get('data', {})
                    receipts = resp_data.get('receipts', [])
                    next_receipt_uid = resp_data.get('nextReceiptUid')
                except json.JSONDecodeError:
                    if phone_data['chat_id']:
                        await conn.execute("""
                            UPDATE auth_user SET is_verified = FALSE 
                            WHERE chat_id = $1 AND phone_number = $2
                        """, phone_data['chat_id'], phone_number)
                    break

                success = True

                for receipt in receipts:
                    try:
                        my_date = datetime.datetime.strptime(receipt['operationDateTime'], '%Y-%m-%dT%H:%M:%SZ').date()
                    except:
                        try:
                            my_date = datetime.datetime.strptime(receipt['operationDateTime'], '%Y-%m-%dT%H:%M:%S.%f').date()
                        except:
                            my_date = None

                    amount = int(receipt.get('operationSum') or 0)

                    db_data.append([
                        receipt.get('receiptUid'),
                        receipt.get('link'),
                        phone_number,
                        my_date,
                        amount,
                        str(receipt.get('operationTypeId')),
                        receipt.get('operationTypeId')
                    ])

                if not is_full_parsing or not next_receipt_uid:
                    break

            if not success:
                if not unauthorized:
                    print(f"Не удалось получить данные чеков для {phone_number}, пропускаю.")
                continue

            print(f"Количество записей для вставки: {len(db_data)}")

            if db_data:
                await conn.executemany("""
                    INSERT INTO receipt (
                        receipt_uid, link, phone_number, receipt_date,
                        amount, operation_type, operation_type_id
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7)
                    ON CONFLICT (link) DO UPDATE SET
                        amount = EXCLUDED.amount,
                        receipt_date = EXCLUDED.receipt_date,
                        receipt_uid = EXCLUDED.receipt_uid,
                        operation_type = EXCLUDED.operation_type,
                        operation_type_id = EXCLUDED.operation_type_id
                """, db_data)

            print(f"[{datetime.datetime.now()}] parse_links завершен для {phone_number}")
            print(f"Вставлено в БД: {len(db_data)} записей")


if __name__ == '__main__':
    asyncio.run(start_wb_parsing())
