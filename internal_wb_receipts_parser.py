import httpx
import datetime
import asyncio

from bs4 import BeautifulSoup

from utils.proxies import change_proxy_ip, get_valid_proxy, get_db_connection


MODEM_FALLBACK_PROXY = "http://admin:admin@94.143.43.213:30620"


async def start_wb_parsing():
    """
    Асинхронный запуск парсера ссылок.
    """
    while True:
        await parse_receipts(with_last_date=False)
        print('Парсинг окончен. Отправляюсь на перерыв.')
        await asyncio.sleep(99999)


async def make_request(url, proxy=None, timeout=6.0):
    """
    Делает один HTTP-запрос с указанным прокси.
    """
    proxy_url = None
    if proxy:
        proxy_url = proxy if proxy.startswith(("http://", "https://")) else f"http://{proxy}"
    transport = httpx.AsyncHTTPTransport(proxy=proxy_url) if proxy_url else None

    async with httpx.AsyncClient(transport=transport, timeout=timeout) as client:
        resp = await client.get(url)

    if resp.status_code == 502:
        raise httpx.HTTPStatusError("502 Bad Gateway", request=resp.request, response=resp)

    resp.raise_for_status()
    return resp


async def parse_receipts(with_last_date=False, one_user_phone=False):
    """
    Асинхронный парсинг чеков и запись в БД.
    """
    conn = await get_db_connection()

    last_date = datetime.datetime.now().date() - datetime.timedelta(days=10) if with_last_date else datetime.date(1970, 1, 1)

    if not one_user_phone:
        all_links_statement = f"""
        SELECT link, phone_number, receipt_uid
        FROM receipt
        WHERE receipt_date > '{last_date}' AND receipt_date > '2023-09-01'
        ORDER BY receipt_date, link ASC
        """
    else:
        all_links_statement = f"""
        SELECT link, phone_number, receipt_uid
        FROM receipt
        WHERE receipt_date > '{last_date}' AND receipt_date > '2024-10-29'
        AND phone_number = '{one_user_phone}'
        ORDER BY receipt_date, link ASC
        """

    links_data = await conn.fetch(all_links_statement)
    base_tags = ['products-item products-item', 'products-item products-item first']

    for record in links_data:
        link = record['link']
        phone_number = record['phone_number']
        receipt_uid = record['receipt_uid']

        proxy_row = await conn.fetchrow(
            """
            SELECT proxy_name, chat_id
            FROM auth_user
            WHERE phone_number = $1
            LIMIT 1
            """,
            phone_number
        )
        proxy_name = proxy_row['proxy_name'] if proxy_row else None
        chat_id = proxy_row['chat_id'] if proxy_row else None

        if not proxy_name and chat_id is not None:
            new_proxy = await get_valid_proxy(phone_number, chat_id)
            if new_proxy:
                if new_proxy.startswith(("http://", "https://")):
                    parsing_proxy = new_proxy
                    proxy_name = new_proxy.split("://", 1)[-1]
                else:
                    proxy_name = new_proxy
                    parsing_proxy = f"http://{new_proxy}"
            else:
                parsing_proxy = MODEM_FALLBACK_PROXY
        else:
            parsing_proxy = (
                proxy_name if proxy_name and proxy_name.startswith(("http://", "https://"))
                else f"http://{proxy_name}" if proxy_name else MODEM_FALLBACK_PROXY
            )

        proxy_retry_done = False
        modem_switched = False
        resp = None

        async def handle_proxy_issue(reason: str) -> bool:
            nonlocal proxy_retry_done, modem_switched, parsing_proxy, proxy_name
            print(reason)

            if not proxy_retry_done:
                changed = False
                if proxy_name:
                    try:
                        changed = await change_proxy_ip(proxy_name)
                    except Exception as e:
                        print(f"Не удалось сменить IP для {proxy_name}: {e}")
                        changed = False

                if changed:
                    proxy_retry_done = True
                    parsing_proxy = (
                        proxy_name if proxy_name.startswith(("http://", "https://"))
                        else f"http://{proxy_name}"
                    )
                    print("IP прокси успешно сменён, повторяю запрос...")
                    await asyncio.sleep(2.5)
                    return True

                new_proxy = await get_valid_proxy(phone_number, chat_id) if chat_id is not None else None
                if new_proxy:
                    if new_proxy.startswith(("http://", "https://")):
                        proxy_name = new_proxy.split("://", 1)[-1]
                        parsing_proxy = new_proxy
                    else:
                        proxy_name = new_proxy
                        parsing_proxy = f"http://{new_proxy}"
                    proxy_retry_done = True
                    print(f"Сменил прокси на {parsing_proxy}, пробую снова...")
                    await asyncio.sleep(2.5)
                    return True
                else:
                    print("Не удалось получить валидный прокси.")

            if not modem_switched:
                print(f"Смена модема для {phone_number} (receipts parser)...")
                parsing_proxy = MODEM_FALLBACK_PROXY
                modem_switched = True
                await asyncio.sleep(2.5)
                return True

            print(f"Ошибка после смены IP и модема. Пропускаю {phone_number}.")
            return False

        while True:
            try:
                resp = await make_request(link, proxy=parsing_proxy)
            except httpx.HTTPStatusError as e:
                status = e.response.status_code if e.response else None
                if status == 502:
                    print(f"502 Bad Gateway for {link}, повторяю позже")
                    await asyncio.sleep(2)
                    continue
                print(f"HTTP ошибка при запросе {link}: {e}")
                resp = None
                break
            except httpx.TimeoutException:
                print(f"Таймаут при обращении к {link}")
                await asyncio.sleep(1)
                continue
            except httpx.ProxyError:
                if await handle_proxy_issue(
                    f"Неактуал авторизация для {phone_number}. Скорее всего отключен прокси"
                ):
                    continue
                resp = None
                break
            except httpx.ConnectError as e:
                if await handle_proxy_issue(f"Ошибка подключения: {e}"):
                    continue
                resp = None
                break
            except httpx.RequestError as e:
                print(f"Ошибка запроса {link}: {e}")
                await asyncio.sleep(1)
                continue
            except Exception as e:
                print(f"Непредвиденная ошибка {link}: {e}")
                resp = None
                break
            else:
                break

        if not resp:
            continue

        soup = BeautifulSoup(resp.text, 'html.parser')
        result = []
        uniq_orders = set()
        counting_receipt_map = {}

        for tag in base_tags:
            elements = soup.findAll('div', class_=tag)
            for element in elements:
                text_info = element.find('div', class_='products-prop-value').text.strip().split('\n')
                supplier_inn_element = element.find('div', class_='products-supplier-inn gray')
                supplier_inn = supplier_inn_element.text.strip() if supplier_inn_element else 'Не найдено'

                try:
                    name = text_info[0].strip()
                    order_id = text_info[2].strip()
                except:
                    print(f"Ошибка в имени или order_id для {link}")
                    continue

                quantity = int(float(element.find('div', class_='products-cell products-cell_count').text.replace('\n', '')))
                cost = int(float(element.find('div', class_='products-cell products-cell_cost').text.replace('\n', '')))
                price = int(float(element.find('div', class_='products-cell products-cell_price').text.replace('\n', '')))

                if order_id not in uniq_orders:
                    uniq_orders.add(order_id)
                    counting_receipt_map[order_id] = {
                        'order_id': order_id,
                        'link': link,
                        'receipt_uid': receipt_uid,
                        'name': name,
                        'phone_number': phone_number,
                        'quantity': quantity,
                        'price': price,
                        'cost': cost,
                        'supplier_inn': supplier_inn
                    }
                else:
                    counting_receipt_map[order_id]['quantity'] += quantity
                    counting_receipt_map[order_id]['cost'] += cost

        for value in counting_receipt_map.values():
            result.append([
                value['order_id'], value['link'], value['receipt_uid'], value['name'],
                value['phone_number'], value['quantity'], value['price'], value['cost'], value['supplier_inn']
            ])

        if result:
            await conn.executemany(
                """
                INSERT INTO receipt_info (
                    order_id, link, receipt_uid, name, phone_number,
                    quantity, price, cost, supplier_inn
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9
                )
                ON CONFLICT (order_id) DO UPDATE SET
                    link = EXCLUDED.link,
                    receipt_uid = EXCLUDED.receipt_uid,
                    name = EXCLUDED.name,
                    phone_number = EXCLUDED.phone_number,
                    quantity = EXCLUDED.quantity,
                    price = EXCLUDED.price,
                    cost = EXCLUDED.cost,
                    supplier_inn = EXCLUDED.supplier_inn
                """,
                result
            )
        print(f"Обработан чек: {link}")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(start_wb_parsing())