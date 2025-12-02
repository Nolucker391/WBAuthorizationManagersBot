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
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from antibot_system.playwright_client_for_parsers import PlaywrightClient
from antibot_system.antibot_logger import logger

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
    logger.info(f"Сменил прокси на {new_proxy}, пробую снова...")
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
        #             WHERE phone_number = '+79047981052'
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


class ManagerParseInfo:
    def __init__(self, phone_number: str, phone_data: dict, connect_db):
        self.phone_number = phone_number
        self.phone_data = phone_data
        self.connect_db = connect_db
        self.pw_config = self._create_pw_config()

    def _create_pw_config(self) -> "PlaywrightConfig":
        """Создаёт объект PlaywrightConfig для текущего пользователя"""
        raw_token = self.phone_data.get('auth_token') or ''
        token_value = raw_token.strip()
        if token_value.lower().startswith("bearer "):
            token_value = token_value.split(" ", 1)[1].strip()

        cookies_list = parse_cookies_string_to_list(self.phone_data.get('cookies') or '')
        device_id = generate_device_id()
        useragent = self.phone_data.get('user_agent') or 'Mozilla/5.0 (Windows)'

        pw_config = PlaywrightConfig(
            token=token_value,
            phone=self.phone_number,
            cookies=cookies_list,
            device_id=device_id,
            # proxy=self.phone_data.get('proxy_name'),
            proxy=None,
        )

        setattr(pw_config, "useragent", useragent)
        return pw_config

    def get_pw_config(self) -> "PlaywrightConfig":
        """Возвращает текущий PlaywrightConfig"""
        return self.pw_config

    async def parser_office_address(
            self,
            office_ids_to_fetch: List[int]
    ) -> Dict[int, str]:
        try:
            async with PlaywrightClient(self.pw_config) as client:
                parser = PlaywrightOrdersParser(client)

                resp_fetch_offices = await parser.get_offices(office_ids_to_fetch)

                return resp_fetch_offices
        except Exception as e:
            logger.warning(f"Ошибка при парсинге адрессов: {e}")
            return {}

    async def parser_tracker_status(
            self,
            order_id: Optional[str],
            phone_number: Optional[str]
    ) -> Optional[str]:
        try:
            async with PlaywrightClient(self.pw_config) as client:
                parser = PlaywrightOrdersParser(client)

                resp_fetch_offices = await parser.get_tracker_status(order_id, phone_number)

                return resp_fetch_offices
        except Exception as e:
            logger.warning(f"Ошибка при парсинге статусов: {e}")
            return None

    async def parse_one_profile(
            self
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
            Парсинг одного профиля через Playwright.
            Возвращает кортеж: (active_orders, delivery_orders)
        """
        pw_proxy_retry_done = False
        pw_modem_switched = False

        for attempt in range(1, 3):
            try:
                async with PlaywrightClient(self.pw_config) as client:
                    parser = PlaywrightOrdersParser(client)
                    resp_data_active = await parser.get_active_orders()
                    resp_data_orders = await parser.get_delivery_orders()
                    return resp_data_active, resp_data_orders

            except ProxyBlockedError:
                if not pw_proxy_retry_done:
                    logger.info("Пробую смену IP (через change_gather)")
                    changed = await change_gather(self.connect_db, self.phone_number, self.phone_data)
                    if changed:
                        pw_proxy_retry_done = True
                        new_proxy_name = self.phone_data.get('proxy_name')
                        self.pw_config.proxy = new_proxy_name
                        logger.info(f"IP прокси успешно сменён на {new_proxy_name}, повторяю Playwright попытку...")
                        await asyncio.sleep(2.5)
                        continue
                if not pw_modem_switched:
                    logger.info("Пробую сменить модем (fallback proxy)")
                    self.pw_config.proxy = MODEM_FALLBACK_PROXY
                    pw_modem_switched = True
                    await asyncio.sleep(2.5)
                    continue
                raise  # если прокси и модем не помогли
            except UnauthorizedError as e:
                logger.warning(f"[{self.phone_number}] Неактуальная авторизация пользователя, пропускаю парсинг: {e}")

                # Отправка сообщения в TG
                try:
                    photo = FSInputFile(path="attachments/media/pismo.png")
                    bot = Bot(token=auth_bot_config.TG_TOKEN.get_secret_value())

                    await bot.send_photo(
                        chat_id=self.phone_data.get("chat_id"),
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
                    logger.info(f"Повторная авторизация для пользователя {self.phone_number} успешно отправлено")
                except Exception as e:
                    logger.warning(f"Ошибка при отправке на повторную авторизацию для пользователя {self.phone_number}: {e}")
                raise
            except (PlaywrightTimeoutError, PlaywrightError) as e:
                logger.warning(
                    f"[{self.phone_number}] ошибка ({attempt}/{2}): {e}"
                )

                if attempt >= 2:
                    raise

                logger.info(f"[{self.phone_number}] рестарт браузера и повтор...")
                await asyncio.sleep(1)

        return [], []

async def parse_delivery_data(
        auth_data_dict
):
    if not auth_data_dict:
        return

    processed_count = 0
    failed_users = []
    un_auth_users = []

    async with get_db_connection() as conn:
        await truncate_delivery_table_if_needed(conn)
        db_data: List[List[Any]] = []

        for phone_number, phone_data in auth_data_dict.items():
            if processed_count > 0 and processed_count % 40 == 0:
                logger.info(f"Обработал 40 юзеров - делаю перерыв...")
                await asyncio.sleep(60*2)

            logger.info(f"Начинаю парсинг заказов для {phone_number}")
            manager = ManagerParseInfo(phone_number, phone_data, connect_db=conn)

            try:
                resp_active, resp_orders = await manager.parse_one_profile()
                logger.info(f"[{phone_number}] Успешно получил: Active={len(resp_active)}, Orders={len(resp_orders)}")
            except UnauthorizedError:
                un_auth_users.append(phone_number)
                resp_active, resp_orders = [], []
            except (PlaywrightTimeoutError, PlaywrightError, ProxyBlockedError) as e:
                failed_users.append(phone_number)
                resp_active, resp_orders = [], []
            except Exception as e:
                logger.warning(f"[{phone_number}] Ошибка обработки профиля: {e}")
                result = []

                if "Failed to get IP address" in str(e):
                    logger.info("Уведомляю Админа об ошибке")


            if resp_orders:
                logger.info(f"Парсим названия адресов у ПВЗ по id")

                office_ids_to_fetch = list(
                    {product.get('dst_office_id') for order in resp_orders for product in order.get('rids', []) if
                     product.get('dst_office_id')})
                office_id_to_address: Dict[int, str] = {}
                office_id_to_address = await manager.parser_office_address(office_ids_to_fetch)

            for order_active in resp_active:
                try:
                    date_str = order_active.get('orderDate', '').rstrip(' .Z')
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
                    price = int(order_active.get('price', 0))
                    delivery_price = int(order_active.get('logisticsCost') or 0)
                    amount = price + delivery_price
                except:
                    delivery_price = None
                    amount = None
                raw_expire_str = order_active.get('rawExpireDate')
                expire_date = None

                try:
                    if order_active.get("trackingStatusReady"):
                        tracking_status = "Готов к выдаче"
                    else:
                        tracking_status = order_active.get('trackingStatus')
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
                        date_str = order_active.get('orderDate', '').rstrip(' .Z')
                        if '.' in date_str:
                            base, frac = date_str.split('.')
                            frac = (frac + '000000')[:6]
                            date_str = f"{base}.{frac}"
                        my_date = datetime.datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%S.%f')
                        expire_date = (my_date + datetime.timedelta(days=14)).date()
                    except Exception as e:
                        expire_date = None

                db_data.append([
                    safe_str(order_active.get('rId')),
                    safe_str(order_active.get('code1S')),
                    order_active.get('name'),
                    phone_number,
                    my_date,
                    amount,
                    order_active.get('postPayment'),
                    order_active.get('prepaid'),
                    order_active.get('address'),
                    safe_str(order_active.get('officeId')),
                    tracking_status,
                    safe_str(order_active.get('shkId')),
                    delivery_price,
                    expire_date
                ])

            for order in resp_orders:
                my_date = datetime.datetime.utcfromtimestamp(order.get('order_dt')).date()

                for product in order.get('rids', []):
                    order_id = product.get("uid", "")

                    logger.info(f"Отправка на проверку статутов: {order_id}")
                    status_name = await manager.parser_tracker_status(
                        order_id,
                        phone_number
                    )

                    if status_name == "Готов к получению":
                        status_name = "Готов к выдаче"

                    logger.info(f"Вернуло статус: {status_name} -> Переформатировано: {status_name}")

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
            processed_count += 1
            logger.info(f"[{phone_number}] Завершён парсинг. Вставлено: {len(db_data)}\n")

        logger.info(f"Общее количество записей (заказов) для вставки в БД: {len(db_data)}")



    logger.info("=== Итог парсинга ===")
    logger.info(f"Количество успешно обработанных номеров: {processed_count}")
    logger.info(f"Пользователи с неактуальной авторизацией (Unauthorized): {len(un_auth_users)}")
    if un_auth_users:
        logger.info(f"Номера: {', '.join(un_auth_users)}")

    logger.info(f"Пользователи с другими ошибками: {len(failed_users)}")
    if failed_users:
        logger.info(f"Номера: {', '.join(failed_users)}")

if __name__ == '__main__':
    asyncio.run(start_wb_parsing())
