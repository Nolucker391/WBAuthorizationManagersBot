# internal_wb_parser_delivery.py
import random
from typing import Optional, Dict, Tuple, List, Any
import json
import datetime
import asyncio
import pytz
import secrets
from aiogram import Bot
from aiogram.types import FSInputFile

import httpx
from httpx import AsyncHTTPTransport, AsyncClient

from configuration_bot.settings import config as auth_bot_config
from mailing_auth_all_users import next_step_auth
from utils.database.get_async_session_db import get_db_connection
from utils.proxies import get_valid_proxy, change_proxy_ip
from dataclasses import dataclass

from antibot_system.config import (
    PlaywrightConfig
)
from antibot_system.antibot_run import (
    PlaywrightOrdersParser,
    ProxyBlockedError,
    UnauthorizedError,
)

from antibot_system.playwright_client_for_parsers import PlaywrightClient

DELIVERY_WB_URL = 'https://www.wildberries.ru/webapi/v2/lk/myorders/delivery/active'  # deliveryPrice
DELIVERY_WB_PC_URL = 'https://wbxoofex.wildberries.ru/api/v2/orders'  # product_cost total_price

MODEM_FALLBACK_PROXY = "http://admin:admin@94.143.43.213:30620"

last_cleanup_date = None


def safe_str(v):
    return str(v) if v is not None else None


def generate_device_id() -> str:
    return "site_" + secrets.token_hex(16)


def parse_cookies_string_to_list(cookies_str: str) -> List[dict]:
    """
    Преобразует строку cookies из БД вида:
    "a=b; c=d; e=f"
    в список объектов для Playwright:
    [{"name":"a","value":"b","domain":"wildberries.ru","path":"/"}, ...]
    """
    if not cookies_str:
        return []

    cookies = []
    parts = [p.strip() for p in cookies_str.split(';') if p.strip()]
    for part in parts:
        if '=' not in part:
            continue
        name, value = part.split('=', 1)
        cookies.append({
            "name": name.strip(),
            "value": value.strip(),
            "domain": "wildberries.ru",
            "path": "/"
        })
    return cookies


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
    tz = pytz.timezone("Europe/Moscow")
    now_msk = datetime.datetime.now(tz)
    current_date = now_msk.date()
    current_time = now_msk.time()
    trigger_time = datetime.time(6, 5)

    row = await conn.fetchrow("SELECT last_cleanup_date FROM parsing_meta LIMIT 1")
    last_cleanup_str = row['last_cleanup_date'] if row else None
    last_cleanup_date = datetime.date.fromisoformat(last_cleanup_str) if last_cleanup_str else None

    if current_time >= trigger_time and last_cleanup_date != current_date:
        print(f"[{now_msk}] Очистка таблицы delivery_info_active...")
        await conn.execute("TRUNCATE TABLE delivery_info_active")

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
        # rows = await conn.fetch("""
        #             SELECT phone_number, cookies, auth_token, user_agent, proxy_name, chat_id, proxy_id, last_parsing_date
        #             FROM auth_user
        #             WHERE phone_number = '+79642165025'
        #         """)
        rows = await conn.fetch("""
            SELECT phone_number, cookies, auth_token, user_agent, proxy_name, chat_id, proxy_id, last_parsing_date
            FROM auth_user
            WHERE is_verified = true
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


@dataclass
class RequestConfig:
    """
    Соответствие старой структуры — оставлено для совместимости.
    """
    url: str
    method: str = "POST"
    data: Optional[dict] = None


async def parse_delivery_data(auth_data_dict):
    if not auth_data_dict:
        return

    processed_count = 0
    failed_users = []

    async with get_db_connection() as conn:
        await truncate_delivery_table_if_needed(conn)

        for phone_number, phone_data in auth_data_dict.items():
            print(f"[{datetime.datetime.now()}] Начинаю парсинг заказов для {phone_number}")
            db_data: List[List[Any]] = []

            # Подготовка PlaywrightConfig
            raw_token = phone_data.get('auth_token') or ''
            token_value = raw_token.strip()
            if token_value.lower().startswith("bearer "):
                token_value = token_value.split(" ", 1)[1].strip()

            cookies_list = parse_cookies_string_to_list(phone_data.get('cookies') or '')
            device_id = generate_device_id()
            useragent = phone_data.get('user_agent') or 'Mozilla/5.0 (Windows)'
            proxy_name = phone_data.get('proxy_name')

            playwright_proxy = proxy_name

            pw_config = PlaywrightConfig(
                token=token_value,
                phone=phone_number,
                cookies=cookies_list,
                device_id=device_id,
                proxy=playwright_proxy,
            )

            try:
                setattr(pw_config, "useragent", useragent)
            except Exception:
                pass

            await asyncio.sleep(random.random())

            resp_data = []
            resp_nf_data = []
            success = False
            unauthorized = False

            pw_attempts = 0
            pw_proxy_retry_done = False
            pw_modem_switched = False

            while pw_attempts < 3 and not success:
                try:
                    print(f"[{phone_number}] Попытка получить данные через Playwright (антибот), попытка {pw_attempts+1}")
                    async with PlaywrightClient(pw_config) as client:
                        parser = PlaywrightOrdersParser(client)

                        # active
                        try:
                            resp_data = await parser.get_active_orders()
                        except ProxyBlockedError:
                            raise
                        except UnauthorizedError:
                            raise
                        except Exception as e:
                            print(f"[{phone_number}] Ошибка get_active_orders: {e}")
                            resp_data = []

                        # orders
                        try:
                            resp_nf_data = await parser.get_delivery_orders()
                        except ProxyBlockedError:
                            raise
                        except UnauthorizedError:
                            raise
                        except Exception as e:
                            print(f"[{phone_number}] Ошибка get_delivery_orders: {e}")
                            resp_nf_data = []

                        if (resp_data and isinstance(resp_data, list)) or (resp_nf_data and isinstance(resp_nf_data, list)):
                            success = True
                            print(f"[{phone_number}] Playwright вернул данные: active={len(resp_data)} pc={len(resp_nf_data)}")
                            break

                        # Playwright вернул пустые данные — выходим к httpx фоллбеку
                        print(f"[{phone_number}] Playwright вернул пустые данные")
                        break

                except ProxyBlockedError as e:
                    print(f"[{phone_number}] Playwright: 498 Proxy blocked: {e}")
                    # Попробуем смену прокси/modem — change_gather реализован в internal
                    if not pw_proxy_retry_done:
                        print("Пробую смену IP (через change_gather)")
                        changed = await change_gather(conn, phone_number, phone_data)
                        if changed:
                            pw_proxy_retry_done = True
                            new_proxy_name = phone_data.get('proxy_name')
                            pw_config.proxy = new_proxy_name
                            print(f"IP прокси успешно сменён на {new_proxy_name}, повторяю Playwright попытку...")
                            await asyncio.sleep(2.5)
                            pw_attempts += 1
                            continue
                        else:
                            print("Не удалось сменить IP (change_gather вернул False)")
                    if not pw_modem_switched:
                        print("Пробую сменить модем (fallback proxy)")
                        pw_config.proxy = MODEM_FALLBACK_PROXY
                        pw_modem_switched = True
                        await asyncio.sleep(2.5)
                        pw_attempts += 1
                        continue

                    print("После смены IP и модема всё ещё 498 — прерываю Playwright попытки")
                    pw_attempts = 99
                    break

                except UnauthorizedError:
                    print(f"[{phone_number}] Playwright: 401 Unauthorized — требуется повторная авторизация")
                    unauthorized = True
                    # Отправка сообщения в TG
                    try:
                        # photo = FSInputFile(path="attachments/media/pismo.png")
                        # bot = Bot(token=auth_bot_config.TG_TOKEN.get_secret_value())
                        #
                        # await bot.send_photo(
                        #     chat_id=phone_data["chat_id"],
                        #     caption=(
                        #         "<b>❌ Привет от ООО «Солюшен»</b>\n\n"
                        #         "🔄 Необходима повторная Авторизация!\n\n"
                        #         "🔐 Пройдите пожалуйста авторизацию по кнопке ниже 👇\n\n"
                        #         ""
                        #     ),
                        #     photo=photo,
                        #     parse_mode="HTML",
                        #     reply_markup=next_step_auth()
                        # )
                        print(f"Повторная авторизация для пользователя {phone_number} успешно отправлено")
                    except Exception as e:
                        print(f"Ошибка при отправке на повторную авторизацию для пользователя {phone_number}: {e}")
                    break

                except Exception as e:
                    print(f"[{phone_number}] Непредвиденная ошибка при Playwright попытке: {e}")
                    break

            if not success and not unauthorized and (not resp_data and not resp_nf_data):
                print(f"[{phone_number}] (Playwright не дал данных)")

            if not success and unauthorized:
                print(f"[{phone_number}] Пропускаю пользователя, нужна авторизация.")
                continue

            office_ids_to_fetch = list({product.get('dst_office_id') for order in resp_nf_data for product in order.get('rids', []) if product.get('dst_office_id')})
            office_id_to_address: Dict[int, str] = {}

            if success:
                try:
                    async with PlaywrightClient(pw_config) as client2:
                        parser2 = PlaywrightOrdersParser(client2)
                        office_id_to_address = await parser2.get_offices(office_ids_to_fetch)
                except ProxyBlockedError as e:
                    print(f"[{phone_number}] 498 при get_offices (Playwright): {e} — попытаемся сменить прокси/модем и продолжить без адресов.")
                    # пробуем смену прокси
                    changed = await change_gather(conn, phone_number, phone_data)
                    if changed:
                        # попробуем ещё раз быстро
                        try:
                            async with PlaywrightClient(pw_config) as client2:
                                parser2 = PlaywrightOrdersParser(client2)
                                office_id_to_address = await parser2.get_offices(office_ids_to_fetch)
                        except Exception:
                            office_id_to_address = {}
                    else:
                        office_id_to_address = {}
                except UnauthorizedError:
                    print(f"[{phone_number}] 401 при get_offices (Playwright) — нужно авторизоваться заново.")
                    # Отправка сообщения TG
                    try:
                        # photo = FSInputFile(path="attachments/media/pismo.png")
                        # bot = Bot(token=auth_bot_config.TG_TOKEN.get_secret_value())
                        #
                        # await bot.send_photo(
                        #     chat_id=phone_data["chat_id"],
                        #     caption=(
                        #         "<b>❌ Привет от ООО «Солюшен»</b>\n\n"
                        #         "🔄 Необходима повторная Авторизация!\n\n"
                        #         "🔐 Пройдите пожалуйста авторизацию по кнопке ниже 👇\n\n"
                        #         ""
                        #     ),
                        #     photo=photo,
                        #     parse_mode="HTML",
                        #     reply_markup=next_step_auth()
                        # )
                        print(f"Повторная авторизация для пользователя {phone_number} успешно отправлено")
                    except Exception as e:
                        print(f"Ошибка при отправке на повторную авторизацию для пользователя {phone_number}: {e}")
                    office_id_to_address = {}
                except Exception as e:
                    print(f"[{phone_number}] Ошибка при get_offices: {e}")
                    office_id_to_address = {}
            else:
                print(f"Playwright не получилось - get_offices")

            # Обработка delivery positions (resp_data)
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

            # Обработка PC orders (resp_nf_data)
            for order in resp_nf_data:
                my_date = datetime.datetime.utcfromtimestamp(order.get('order_dt')).date()
                for product in order.get('rids', []):
                    order_id = product.get("uid", "")

                    print("Отправка на проверку статутов")
                    status_name = None

                    if success:
                        try:
                            async with PlaywrightClient(pw_config) as client3:
                                parser3 = PlaywrightOrdersParser(client3)
                                status_name = await parser3.get_tracker_status(order_id, phone_number)
                        except ProxyBlockedError as e:
                            print(f"[{phone_number}] 498 при get_tracker_status (Playwright): {e} — пропускаем получение статуса")
                            status_name = None
                        except UnauthorizedError:
                            print(f"[{phone_number}] 401 при get_tracker_status (Playwright) — нужно авторизоваться")
                            status_name = None
                        except Exception as e:
                            print(f"[{phone_number}] Ошибка get_tracker_status: {e}")
                            status_name = None
                    else:
                        # httpx fallback: ничего не делаем — можно оставить None или сделать httpx запрос
                        print(f"не получилось взять статус продукта ")
                        pass

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
                            expiry_date = datetime.datetime.utcfromtimestamp(expiry_ts).date() + datetime.timedelta(days=1)
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
