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
from dateutil import parser
from configuration_bot.settings import config as auth_bot_config
from mailing_auth_all_users import next_step_auth
from utils.database.get_async_session_db import get_db_connection, get_db_driver_connection
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
    """
    Асинхронный запуск парсинга
    """
    while True:
        print("Начинаю парсинг...")
        auth_data_dict = await get_actual_auth_data()

        # Парсим заказы
        for phone, data in auth_data_dict.items():
            await parse_archive_data(
                {phone: data},
                is_full_parsing=data['is_full_parsing']
            )

        # await asyncio.gather(*[
        #     parse_archive_data({phone: data}, is_full_parsing=data['is_full_parsing'])
        #     for phone, data in auth_data_dict.items()
        # ])

        # Парсим чеки
        for phone, data in auth_data_dict.items():
            await parse_links(
                {phone: data},
                is_full_parsing=data['is_full_parsing']
            )

        # await asyncio.gather(*[
        #     parse_links({phone: data}, is_full_parsing=data['is_full_parsing'])
        #     for phone, data in auth_data_dict.items()
        # ])

        print("Парсинг окончен. Перерыв 2 часа.")
        await asyncio.sleep(7200)


async def get_actual_auth_data():
    """
    Получает актуальных пользователей из БД и определяет, нужен ли полный парсинг.
    """
    today_limit = datetime.date(2025, 12, 1)
    async with get_db_connection() as conn:
        rows = await conn.fetch("""
            SELECT phone_number, cookies, auth_token, user_agent, proxy_name, chat_id, proxy_id, last_parsing_date
            FROM auth_user
            WHERE is_verified = true
        """)
        # phone_numbers = [
        #     "+79888514061"
        # ]
        #
        # rows = await conn.fetch(
        #     """
        #     SELECT phone_number, cookies, auth_token, user_agent, proxy_name, chat_id, proxy_id, last_parsing_date
        #     FROM auth_user
        #     WHERE phone_number = ANY($1)
        #     """,
        #     phone_numbers
        # )

    auth_data_dict = {}
    for row in rows:
        # last_parsing_date = row['last_parsing_date']
        #
        # is_full_parsing = (
        #     last_parsing_date is None or
        #     (isinstance(last_parsing_date, datetime.date) and last_parsing_date < today_limit)
        # )

        raw_date = row['last_parsing_date']

        if raw_date is None:
            last_date = None
        elif isinstance(raw_date, datetime.datetime):
            last_date = raw_date.date()
        elif isinstance(raw_date, datetime.date):
            last_date = raw_date
        elif isinstance(raw_date, str):
            try:
                last_date = datetime.datetime.fromisoformat(raw_date).date()
            except Exception:
                logger.warning(f"[{row['phone_number']}] Не удалось распарсить дату: {raw_date}")
                last_date = None
        else:
            last_date = None

        # полный парсинг нужен, если нет даты или дата меньше today_limit
        is_full_parsing = last_date is None or last_date < today_limit

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

    async def parser_links_checks(
            self,
            request_params
    ):
        try:
            async with PlaywrightClient(self.pw_config) as client:
                parser = PlaywrightOrdersParser(client)

                resp_fetch_offices = await parser.get_links_receipts(request_params)

                return resp_fetch_offices
        except Exception as e:
            logger.warning(f"Ошибка при парсинге чеков: {e}")
            return {}

    async def parse_one_profile(
            self,
            request_data,
            is_full_parsing: bool = False
    ) -> List[Dict[str, Any]]:
        """
            Парсинг одного профиля через Playwright.
            Возвращает кортеж: (active_orders, delivery_orders)
        """
        pw_proxy_retry_done = False
        pw_modem_switched = False

        all_orders: List[Dict[str, Any]] = []

        limit = int(request_data.get("limit", 250))
        offset = int(request_data.get("offset", 0))

        for attempt in range(1, 3):
            try:
                async with PlaywrightClient(self.pw_config) as client:
                    parser = PlaywrightOrdersParser(client)

                    while True:
                        request_data["limit"] = str(limit)
                        request_data["offset"] = str(offset)
                        logger.info(f"Запускаю парсер. Смотрим Флаг: {is_full_parsing}. Offset: {offset}")

                        resp_data_archive = await parser.get_archived_orders(
                            request_data
                        )

                        if not resp_data_archive:
                            break

                        all_orders.extend(resp_data_archive)

                        if not is_full_parsing:
                            break

                        offset += limit

                        # защита от бесконечного цикла
                        if len(resp_data_archive) < limit:
                            break
                    return all_orders

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

        return []

async def parse_archive_data(
        auth_data_dict,
        is_full_parsing=False
):
    if not auth_data_dict:
        return

    offset = 0
    limit = 250

    request_data = {
        'limit': str(limit),
        'offset': str(offset),
        'type': 'all'
    }
    if is_full_parsing:
        request_data.update({
            'from': '2019-01-01',
            'to': datetime.datetime.now().strftime('%Y-%m-%d')
        })
    processed_count = 0
    failed_users = []
    un_auth_users = []

    async with get_db_connection() as conn:
        db_data: List[List[Any]] = []

        for phone_number, phone_data in auth_data_dict.items():

            if processed_count > 0 and processed_count % 20 == 0:
                logger.info(f"Обработал 30 юзеров - делаю перерыв...")
                await asyncio.sleep(60*2)

            logger.info(f"Начинаю парсинг заказов для {phone_number}")

            manager = ManagerParseInfo(phone_number, phone_data, connect_db=conn)

            try:
                resp_archive = await manager.parse_one_profile(
                    request_data,
                    is_full_parsing=phone_data['is_full_parsing']
                )
                logger.info(f"[{phone_number}] Успешно получил: Acrhives={len(resp_archive)}")
            except UnauthorizedError:
                un_auth_users.append(phone_number)
                resp_archive = []
            except (PlaywrightTimeoutError, PlaywrightError, ProxyBlockedError) as e:
                failed_users.append(phone_number)
                resp_archive = []
            except Exception as e:
                logger.warning(f"[{phone_number}] Ошибка обработки профиля: {e}")
                resp_archive = []

                if "Failed to get IP address" in str(e):
                    logger.info("Уведомляю Админа об ошибке")

            for order in resp_archive:
                office = order.get('office')
                office_id = order.get('officeId')
                my_date = parser.parse(order.get('lastDate')).date() if order.get('lastDate') else None
                price = int(order.get('price') or 0)
                delivery_price = int(order.get('logisticsCost') or 0)
                total_price = price + delivery_price

                if office:
                    address = office.get('address')
                else:
                    address_parsing = await manager.parser_office_address([int(office_id)])
                    address = address_parsing.get(office_id, 'upd')

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
            logger.info(f"[{phone_number}] Завершён парсинг. Вставлено: {len(resp_archive)}\n")

        logger.info("=== Итог парсинга ===")
        logger.info(f"Общее количество записей (заказов) для вставлено в БД: {len(db_data)}")
        logger.info(f"Количество успешно обработанных номеров: {processed_count}")
        logger.info(f"Пользователи с неактуальной авторизацией (Unauthorized): {len(un_auth_users)}")
        if un_auth_users:
            logger.info(f"Номера: {', '.join(un_auth_users)}")

        logger.info(f"Пользователи с другими ошибками: {len(failed_users)}")
        if failed_users:
            logger.info(f"Номера: {', '.join(failed_users)}")


async def parse_links(
        auth_data_dict,
        is_full_parsing=True
):
    if not auth_data_dict:
        return

    processed_count = 0
    failed_users = []
    un_auth_users = []

    async with get_db_connection() as conn:
        db_data: List[List[Any]] = []

        for phone_number, phone_data in auth_data_dict.items():
            if processed_count > 0 and processed_count % 40 == 0:
                logger.info(f"Обработал 40 юзеров - делаю перерыв...")
                await asyncio.sleep(60*2)

            logger.info(f"Начинаю парсинг заказов для {phone_number}")

            next_receipt_uid = None
            request_params = {'receiptsPerPage': str(20) if is_full_parsing else str(10)}

            if is_full_parsing and next_receipt_uid:
                request_params['nextReceiptUid'] = str(next_receipt_uid)

            manager = ManagerParseInfo(phone_number, phone_data, connect_db=conn)

            try:
                resp_links = await manager.parser_links_checks(
                    request_params
                )
                logger.info(
                    f"[{phone_number}] Успешно получил: Links={len(resp_links)}")
            except UnauthorizedError:
                un_auth_users.append(phone_number)
                resp_links = []
            except (PlaywrightTimeoutError, PlaywrightError, ProxyBlockedError) as e:
                failed_users.append(phone_number)
                resp_links = []
            except Exception as e:
                logger.warning(f"[{phone_number}] Ошибка обработки профиля: {e}")
                resp_links = []

                if "Failed to get IP address" in str(e):
                    logger.info("Уведомляю Админа об ошибке")

            try:
                receipts = resp_links.get('receipts', [])
                next_receipt_uid = str(resp_links.get('nextReceiptUid'))
                print(next_receipt_uid)
            except json.JSONDecodeError:
                next_receipt_uid = None
                break

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

            processed_count += 1
            logger.info(f"[{phone_number}] Завершён парсинг чеков. Вставлено: {len(receipts)}\n")

        logger.info(f"Общее количество записей (чеков) вставлено в БД: {len(db_data)}")


if __name__ == '__main__':
    asyncio.run(start_wb_parsing())
