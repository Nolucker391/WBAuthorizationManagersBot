import locale
import random
from typing import Optional, Dict, Tuple

import httpx, json
import datetime
import time
import asyncio
import pytz
from aiogram import Bot
from aiogram.types import FSInputFile

from httpx import AsyncHTTPTransport, AsyncClient

from psycopg2.extras import execute_values

from configuration_bot.settings import config as auth_bot_config
from mailing_auth_all_users import next_step_auth
from utils.database.get_async_session_db import get_db_connection
from utils.proxies import get_valid_proxy, change_proxy_ip
from dataclasses import dataclass

DELIVERY_WB_URL = 'https://www.wildberries.ru/webapi/v2/lk/myorders/delivery/active' # deliveryPrice
DELIVERY_WB_PC_URL = 'https://wbxoofex.wildberries.ru/api/v2/orders' # product_cost total_price

MODEM_FALLBACK_PROXY = "http://admin:admin@94.143.43.213:30620"

# Устанавливаем русскую локаль
# locale.setlocale(locale.LC_TIME, 'ru_RU.UTF-8')  # Для Linux/Unix
# Или для Windows:
# locale.setlocale(locale.LC_TIME, 'russian')
last_cleanup_date = None
tracker_shards: Dict[str, int] = {}


def safe_str(v):
    return str(v) if v is not None else None


async def change_gather(conn, phone_number: str, phone_data: dict) -> bool:
    """
    Пробует сменить IP текущего прокси или подобрать новый.
    Возвращает True, если удалось сменить IP или назначить новый прокси.
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


async def truncate_delivery_table_if_needed(conn):
    """
    Очищает delivery_info_active 1 раз в день в 6:00 утра по МСК.
    Использует таблицу parsing_meta для хранения даты последней очистки.
    """
    tz = pytz.timezone("Europe/Moscow")
    now_msk = datetime.datetime.now(tz)
    current_date = now_msk.date()
    current_time = now_msk.time()
    trigger_time = datetime.time(6, 5)

    # Получаем дату последней очистки из базы
    row = await conn.fetchrow("SELECT last_cleanup_date FROM parsing_meta LIMIT 1")
    last_cleanup_str = row['last_cleanup_date'] if row else None
    last_cleanup_date = datetime.date.fromisoformat(last_cleanup_str) if last_cleanup_str else None

    # Проверяем: 6:00 утра и ещё не чистили сегодня
    if current_time >= trigger_time and last_cleanup_date != current_date:
        print(f"[{now_msk}] Очистка таблицы delivery_info_active...")
        await conn.execute("TRUNCATE TABLE delivery_info_active")

        # Сохраняем дату последней очистки
        if row:
            await conn.execute(
                "UPDATE parsing_meta SET last_cleanup_date = $1",
                str(current_date)
            )
        else:
            await conn.execute(
                "INSERT INTO parsing_meta(last_cleanup_date) VALUES($1)",
                str(current_date)
            )

        print(f"[{now_msk}] Очистка завершена")
    else:
        print(
            f"[{now_msk}] Очистка не выполнена. "
            f"Текущее время: {current_time}, порог: {trigger_time}, "
            f"последняя очистка: {last_cleanup_date}"
        )


async def start_wb_parsing():
    while True:
        print("Начинаю парсинг активных доставок...")
        auth_data_dict = await get_actual_auth_data()
        await parse_delivery_data(auth_data_dict)
        print("Парсинг окончен. Перерыв 30 минут.")
        await asyncio.sleep(1800)


async def get_actual_auth_data():
    async with get_db_connection() as conn:
        rows = await conn.fetch("""
            SELECT phone_number, cookies, auth_token, user_agent, proxy_name, chat_id, proxy_id, last_parsing_date
            FROM auth_user
            WHERE is_verified = true
        """)
        # rows = await conn.fetch("""
        #             SELECT phone_number, cookies, auth_token, user_agent, proxy_name, chat_id, proxy_id, last_parsing_date
        #             FROM auth_user
        #             WHERE phone_number = '+79835399487'
        #         """)
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


async def fetch_office_addresses(conn, headers, phone_number, phone_data, office_ids):
    if not office_ids:
        return {}
    MAX_PROXY_RETRIES = 5
    attempts = 0
    proxy_retry_done = False
    modem_switched = False

    proxy_name = phone_data.get('proxy_name')
    if proxy_name and not proxy_name.startswith("http"):
        parsing_proxy = f"http://{proxy_name}"
    else:
        parsing_proxy = proxy_name

    while attempts < MAX_PROXY_RETRIES:
        try:
            await asyncio.sleep(random.random())
            transport = AsyncHTTPTransport(proxy=parsing_proxy) if parsing_proxy else None
            async with httpx.AsyncClient(transport=transport, timeout=6.0) as client:
                response = await client.post(
                    'https://www.wildberries.ru/webapi/lk/myorders/delivery/offices',
                    headers=headers,
                    data={"ids": office_ids}
                )
            response.raise_for_status()
            office_data = response.json().get("value", {})
            return {
                int(office_id): data.get("address")
                for office_id, data in office_data.items()
                if data.get("address")
            }
        except httpx.TimeoutException:
            print("Таймаут при получении адресов офисов")
            attempts += 1
            await asyncio.sleep(0.5)
            continue
        except httpx.HTTPStatusError as e:
            status = e.response.status_code if e.response else 'unknown'
            print(f"HTTP ошибка при получении адресов офисов: {status}")
            if status == 498:
                print("Ответ 498 при получении адресов — прокси заблокирован.")
                attempts += 1
                if not proxy_retry_done:
                    print("Пробую смену IP")
                    changed = await change_gather(conn, phone_number, phone_data)
                    if changed:
                        proxy_retry_done = True
                        proxy_name = phone_data.get('proxy_name')
                        parsing_proxy = f"http://{proxy_name}" if proxy_name and not proxy_name.startswith("http") else proxy_name
                        print("IP прокси успешно сменён, повторяю запрос...")
                        await asyncio.sleep(2.5)
                        continue
                    else:
                        print("Не удалось сменить IP, попробую сменить модем...")
                if not modem_switched:
                    print(f"Смена модема для {phone_number} (offices)...")
                    parsing_proxy = MODEM_FALLBACK_PROXY
                    modem_switched = True
                    await asyncio.sleep(2.5)
                    continue
                print("Ошибка после смены IP и модема при получении адресов, прекращаю попытки.")
                break
            attempts += 1
            await asyncio.sleep(0.5)
            continue
        except httpx.ProxyError as e:
            print(
                f"Неактуал авторизация для {phone_number}. "
                f"Скорее всего отключен прокси при получении адресов\n"
            )
            if not proxy_retry_done:
                print("Пробую смену IP")
                changed = await change_gather(conn, phone_number, phone_data)
                if changed:
                    proxy_retry_done = True
                    proxy_name = phone_data.get('proxy_name')
                    parsing_proxy = f"http://{proxy_name}" if proxy_name and not proxy_name.startswith("http") else proxy_name
                    print("IP прокси успешно сменён, повторяю запрос...")
                    await asyncio.sleep(2.5)
                    continue
                else:
                    print("Не удалось сменить IP, попробую сменить модем...")
            if not modem_switched:
                print(f"Смена модема для {phone_number} (offices)...")
                parsing_proxy = MODEM_FALLBACK_PROXY
                modem_switched = True
                await asyncio.sleep(2.5)
                continue
            print("Ошибка после смены IP и модема при получении адресов. Прекращаю попытки.")
            break
        except httpx.RequestError as e:
            print(f"Ошибка при получении адресов офисов: {e}")
            attempts += 1
            await asyncio.sleep(0.5)
            continue
        except Exception as e:
            print(f"Непредвиденная ошибка при получении адресов: {e}")
            attempts += 1
            await asyncio.sleep(0.5)
            continue

    print("Не удалось получить адреса офисов после нескольких попыток")
    return {}


@dataclass
class RequestConfig:
    """
    Конфигурация для HTTP запросов.
    """
    url: str
    method: str = "POST"
    data: Optional[dict] = None


async def make_request_for_account(
    conn,
    phone_number: str,
    config: RequestConfig,
    phone_data: dict,
    proxy: Optional[str] = None
) -> Optional[dict | list]:
    """
    Утилита запросов, использует phone_data (dict).
    В случае проблем с прокси пытается сменить IP/прокси и повторить запрос.
    """
    headers = {
        'Authorization': phone_data.get('auth_token') or phone_data.get('token') or '',
        'Cookie': phone_data.get('cookies') or phone_data.get('cookie') or '',
        'User-Agent': phone_data.get('user_agent') or phone_data.get('useragent') or 'python-httpx'
    }

    if config.data and isinstance(config.data, str):
        headers['Content-Type'] = 'application/json'

    used_proxy = proxy or phone_data.get('proxy_name')
    if used_proxy and not used_proxy.startswith("http"):
        parsing_proxy = f"http://{used_proxy}"
    else:
        parsing_proxy = used_proxy

    counter_errors = 0
    proxy_retry_done = False
    modem_switched = False

    while counter_errors < 3:
        try:
            await asyncio.sleep(random.uniform(0.05, 0.25))
            transport = AsyncHTTPTransport(proxy=parsing_proxy) if parsing_proxy else None
            async with httpx.AsyncClient(transport=transport, timeout=6.0) as client:
                response = await client.request(
                    method=config.method,
                    url=config.url,
                    headers=headers,
                    data=config.data
                )

            if response.status_code == 498:
                print(f"[make_request_for_account] 498 для {phone_number} при обращении к {config.url}")
                raise httpx.ProxyError("Proxy blocked (498)")

            try:
                return response.json()
            except ValueError:
                print(f"[make_request_for_account] Ответ не JSON. url={config.url}, status={response.status_code}, text={response.text[:200]}")
                return None

        except httpx.ProxyError:
            print(
                f"Неактуал авторизация для {phone_number}. "
                f"Скорее всего отключен прокси при обращении к {config.url}\n"
            )
            if not proxy_retry_done:
                print("Пробую смену IP")
                changed = await change_gather(conn, phone_number, phone_data)
                if changed:
                    proxy_retry_done = True
                    new_proxy_name = phone_data.get('proxy_name')
                    used_proxy = new_proxy_name
                    parsing_proxy = (
                        f"http://{new_proxy_name}"
                        if new_proxy_name and not new_proxy_name.startswith("http")
                        else new_proxy_name
                    )
                    print("IP прокси успешно сменён, повторяю запрос...")
                    await asyncio.sleep(2.5)
                    continue
                else:
                    print("Не удалось сменить IP, попробую сменить модем...")

            if not modem_switched:
                print(f"Смена модема для {phone_number} при обращении к {config.url}...")
                parsing_proxy = MODEM_FALLBACK_PROXY
                modem_switched = True
                await asyncio.sleep(2.5)
                continue

            print(f"Ошибка после смены IP и модема. Пропускаю запрос {config.url} для {phone_number}.")
            counter_errors += 1
            break
        except (httpx.TimeoutException, httpx.ReadTimeout):
            print(f"[make_request_for_account] Таймаут при обращении к {config.url}")
            counter_errors += 1
            await asyncio.sleep(0.2)
            continue
        except httpx.RequestError as e:
            print(f"[make_request_for_account] Ошибка запроса: {e}")
            counter_errors += 1
            await asyncio.sleep(0.2)
            continue
        except Exception as e:
            print(f"[make_request_for_account] Непредвиденная ошибка при запросе {config.url}: {e}")
            counter_errors += 1
            await asyncio.sleep(0.2)
            continue

    print(f"[make_request_for_account] Превышено число попыток для {config.url}")
    return None



async def _get_order_status_from_tracker(
    conn,
    uid: str,
    phone_number: str,
    phone_data: dict,
    proxy: Optional[str] = None
) -> Optional[str]:
    """
    Проверяет статус заказа через wbx-status-tracker.
    - Кэширует shard по phone_number в tracker_shards
    - Возвращает последний (по времени) статус из списка
    """
    if not isinstance(phone_data, dict):
        raise TypeError(f"_get_order_status_from_tracker: phone_data must be dict, got {type(phone_data)!r}")

    base_url = "https://wbx-status-tracker.wildberries.ru/api/v3/statuses"

    shard_known = tracker_shards.get(phone_number)
    if shard_known is not None:
        url = f"{base_url}/{uid}?shard={shard_known}"
        try:
            data = await make_request_for_account(conn, phone_number, RequestConfig(url=url, method="GET"), phone_data, proxy)
        except Exception as e:
            print(f"[tracker] Ошибка при запросе shard={shard_known}: {e}")
            return None

        if data and isinstance(data, list) and len(data) > 0:
            # фильтруем только нужный UID (rid может содержать .0.0 и т.п.)
            records = [item for item in data if item.get("rid", "").startswith(uid)]
            if not records:
                records = data  # fallback, если фильтр ничего не дал

            # находим запись с максимальным временем
            last_record = max(records, key=lambda r: r.get("date", 0))
            last_status = last_record.get("status_name")
            last_date = datetime.datetime.fromtimestamp(last_record.get("date", 0) / 1e9)

            print(f"[Tracker] Последний статус для UID={uid}: {last_status} ({last_date})")
            return last_status

        return None

    # если shard не известен — ищем по всем 0..100
    async def fetch_shard(i: int) -> Tuple[Optional[int], Optional[str]]:
        url = f"{base_url}/{uid}?shard={i}"
        try:
            data = await make_request_for_account(conn, phone_number, RequestConfig(url=url, method="GET"), phone_data, proxy)
        except Exception as e:
            print(f"[fetch_shard] Ошибка shard={i}: {e}")
            return None, None

        if not data or not isinstance(data, list):
            return None, None

        # выбираем последний статус из списка
        last_record = max(data, key=lambda r: r.get("date", 0))
        if last_record and last_record.get("rid", "").startswith(uid):
            return i, last_record.get("status_name")

        return None, None

    shards = list(range(0, 101))
    for start in range(0, len(shards), 20):
        batch = shards[start:start + 20]
        results = await asyncio.gather(*[fetch_shard(i) for i in batch])
        for found_shard, status in results:
            if found_shard is not None and status is not None:
                tracker_shards[phone_number] = found_shard
                print(f"[tracker] Найден shard={found_shard} для UID {uid}, статус: {status}")
                return status

    print(f"[tracker] UID {uid} не найден ни на одном shard 0..100")
    return None


async def parse_delivery_data(auth_data_dict):
    if not auth_data_dict:
        return

    processed_count = 0
    failed_users = []

    async with get_db_connection() as conn:
        await truncate_delivery_table_if_needed(conn)

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

            proxy_retry_done = False
            modem_switched = False

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

            await asyncio.sleep(random.random())

            resp_data = []
            resp_nf_data = []
            success = False
            unauthorized = False

            while True:
                try:
                    transport = AsyncHTTPTransport(proxy=parsing_proxy) if parsing_proxy else None
                    async with AsyncClient(transport=transport, timeout=10.0) as client:
                        resp = await client.post(DELIVERY_WB_URL, headers=headers)
                        resp_nf = await client.get(DELIVERY_WB_PC_URL, headers=headers)
                        print(resp.status_code)
                        print(resp_nf.status_code)

                except httpx.TimeoutException:
                    print(f"Таймаут при обращении к {DELIVERY_WB_URL} или {DELIVERY_WB_PC_URL}")
                    await asyncio.sleep(0.5)
                    continue
                except httpx.ProxyError:
                    if await handle_proxy_issue(
                        f"Неактуал авторизация для {phone_number}. Скорее всего отключен прокси\n"
                    ):
                        continue
                    failed_users.append(phone_number)
                    break
                except httpx.ConnectError as e:
                    if await handle_proxy_issue(f"Проблема с прокси {parsing_proxy}: {e}"):
                        continue
                    failed_users.append(phone_number)
                    break
                except Exception as e:
                    import traceback
                    print(f"Ошибка запроса: {repr(e)}")
                    traceback.print_exc()
                    break

                if resp.status_code == 401 or resp_nf.status_code == 401:
                    print(f'401 Unauthorized для {phone_number}')
                    unauthorized = True

                    try:
                        photo = FSInputFile(path="attachments/media/pismo.png")
                        bot = Bot(token=auth_bot_config.TG_TOKEN.get_secret_value())

                        await bot.send_photo(
                            chat_id=phone_data["chat_id"],
                            caption=(
                                "<b>❌ Привет от ООО «Солюшен»</b>\n\n"
                                "🔄 Необходима повторная Авторизация!\n\n"
                                "🔐 Пройдите пожалуйста авторизацию по кнопке ниже 👇\n\n"
                                ""
                            ),
                            photo=photo,
                            parse_mode="HTML",
                            reply_markup=next_step_auth()
                        )
                        print(f"Повторная авторизация для пользователя {phone_number} успешно отправлено")
                    except Exception as e:
                        print(f"Ошибка при отправке на повторную авторизацию для пользователя {phone_number}: {e}")
                    break

                if resp.status_code == 498 or resp_nf.status_code == 498:
                    if await handle_proxy_issue(
                        f"Получен статус 498 при обращении к API для {phone_number}"
                    ):
                        continue
                    failed_users.append(phone_number)
                    break

                try:
                    resp_data = resp.json().get('value', {}).get('positions', [])
                except json.JSONDecodeError:
                    resp_data = []
                try:
                    resp_nf_data = resp_nf.json().get('data', []) or []
                except json.JSONDecodeError:
                    resp_nf_data = []

                success = True
                break

            if not success:
                if not unauthorized and phone_number not in failed_users:
                    failed_users.append(phone_number)
                continue

            # Обработка delivery positions
            for order in resp_data:
                try:
                    date_str = order.get('orderDate', '').rstrip(' .Z')
                    if "." in date_str:
                        base, frac = date_str.split('.')
                        date_str = f"{base}.{frac[:6]}"
                    my_date = datetime.datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%S.%f').date()
                except:
                    try:
                        my_date = datetime.datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%S').date()
                    except:
                        continue

                try:
                    price = int(order.get('price', 0))
                    delivery_price = int(order.get('logisticsCost') or 0)
                    amount = price + delivery_price
                except:
                    delivery_price = None
                    amount = None

                raw_expire_str = order.get('rawExpireDate')
                expire_date = None

                try:
                    if order.get("trackingStatusReady"):
                        tracking_status = "Готов к выдаче"
                    else:
                        tracking_status = order.get('trackingStatus')
                except:
                    tracking_status = "Ошибка при получении статуса"

                if raw_expire_str:
                    try:
                        raw_expire_str = raw_expire_str.rstrip('Z')
                        if '.' in raw_expire_str:
                            date_part, micro_part = raw_expire_str.split('.')
                            micro_part = (micro_part + '000000')[:6]
                            raw_expire_str = f"{date_part}.{micro_part}"
                        expire_dt = datetime.datetime.fromisoformat(raw_expire_str)
                        expire_date = expire_dt.date()
                    except Exception as e:
                        print(f"Ошибка парсинга rawExpireDate: {e}")
                        expire_date = None

                if not expire_date:
                    try:
                        date_str = order.get('orderDate', '').rstrip(' .Z')
                        if '.' in date_str:
                            base, frac = date_str.split('.')
                            frac = (frac + '000000')[:6]
                            date_str = f"{base}.{frac}"
                        my_date = datetime.datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%S.%f')
                        expire_date = (my_date + datetime.timedelta(days=14)).date()
                    except Exception as e:
                        expire_date = None

                db_data.append([
                    safe_str(order.get('rId')),
                    safe_str(order.get('code1S')),
                    order.get('name'),
                    phone_number,
                    my_date,
                    amount,
                    order.get('postPayment'),
                    order.get('prepaid'),
                    order.get('address'),
                    safe_str(order.get('officeId')),
                    tracking_status,
                    safe_str(order.get('shkId')),
                    delivery_price,
                    expire_date
                ])

            # Обработка PC orders
            office_ids_to_fetch = list({product.get('dst_office_id') for order in resp_nf_data for product in order['rids'] if product.get('dst_office_id')})
            office_id_to_address = await fetch_office_addresses(conn, headers, phone_number, phone_data, office_ids_to_fetch)

            for order in resp_nf_data:
                my_date = datetime.datetime.utcfromtimestamp(order.get('order_dt')).date()
                for product in order['rids']:
                    order_id = product.get("uid", "")

                    print("Отправка на проверку статутов")
                    status_name = await _get_order_status_from_tracker(
                        conn,
                        order_id,
                        phone_number,
                        phone_data,
                        parsing_proxy
                    )


                    if status_name == "Готов к получению":
                        status_name = "Готов к выдаче"

                    print(f"Вернуло статус: {status_name} -> Переформатировано: {status_name}")

                    try:
                        amount = int(str(product.get('total_price', 0))[:-2])
                    except:
                        amount = 0

                    address = office_id_to_address.get(product.get('dst_office_id'), 'upd')

                    try:
                        delivery_price = int(str(product.get('logistic_cost'))[:-2])
                    except:
                        delivery_price = 0

                    expiry_ts = product.get('expiry_dt')
                    expiry_date = None
                    if expiry_ts:
                        try:
                            expiry_date = datetime.datetime.utcfromtimestamp(expiry_ts).date() + datetime.timedelta(
                                days=1)
                        except:
                            expiry_date = None

                    db_data.append([
                        safe_str(order_id),
                        safe_str(product.get('nm_id')),
                        product.get('name'),
                        phone_number,
                        my_date,
                        amount,
                        None,
                        None,
                        address,
                        safe_str(product.get('dst_office_id')),
                        status_name,
                        None,
                        delivery_price,
                        expiry_date
                    ])

            # break  # выходим из цикла если всё успешно

            print(f"Количество записей для вставки: {len(db_data)}")

            if db_data:
                await conn.executemany("""
                    INSERT INTO delivery_info_active (
                        order_id,
                        product_id,
                        name,
                        phone_number,
                        order_date,
                        price,
                        post_payment,
                        prepaid,
                        office_address,
                        office_id,
                        tracking_status,
                        shkId,
                        delivery_price,
                        last_date_pickup
                    ) VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14
                    )
                    ON CONFLICT (order_id) DO UPDATE SET
                        product_id = EXCLUDED.product_id,
                        name = EXCLUDED.name,
                        phone_number = EXCLUDED.phone_number,
                        order_date = EXCLUDED.order_date,
                        price = EXCLUDED.price,
                        post_payment = EXCLUDED.post_payment,
                        prepaid = EXCLUDED.prepaid,
                        office_address = EXCLUDED.office_address,
                        office_id = EXCLUDED.office_id,
                        tracking_status = EXCLUDED.tracking_status,
                        shkId = EXCLUDED.shkId,
                        delivery_price = EXCLUDED.delivery_price,
                        last_date_pickup = EXCLUDED.last_date_pickup
                """, db_data)
            print(f"[{datetime.datetime.now()}] Вставка завершена ✅")

            processed_count += 1
            print(f"[{datetime.datetime.now()}] parse_delivery_data завершен для {phone_number}")

    print(f"\n[{datetime.datetime.now()}] Обработано номеров: {processed_count}")

    if failed_users:
        print("\n- Проблемные пользователи (ошибки или прокси-баны):")
        for u in failed_users:
            print(f"  - {u}")
    else:
        print("\n- Все пользователи обработаны без критических ошибок.")

if __name__ == '__main__':
    asyncio.run(start_wb_parsing())
