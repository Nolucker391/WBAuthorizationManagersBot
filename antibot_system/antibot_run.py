import json
import os

from typing import Any, Optional, Dict, List

from playwright.async_api import Error as PlaywrightError, APIRequestContext

from antibot_system.antibot_logger import logger


class ProxyBlockedError(Exception):
    """Заглушка 498 ошибки"""
    pass


class UnauthorizedError(Exception):
    """Заглушка 401 ошибки"""
    pass


shard_cache: Dict[str, int] = {}


class PlaywrightOrdersParser:
    """
    Network-layer implemented via Playwright page.evaluate (JS fetch).
    Все сетевые запросы (active, delivery/pc, archive, offices, tracker) реализованы здесь.
    """

    def __init__(self, playwright_client) -> None:
        """
        playwright_client должен иметь атрибуты:
            - page (Playwright Page)
            - config (с полями token, device_id, useragent, proxy и т.д.)
        """
        self.playwright_client = playwright_client
        self.request: APIRequestContext = playwright_client.context.request
        self.config = getattr(playwright_client, "config", None)

        self.cache_file = 'phone_shard_cache.json'
        self.cache = self.load_cache()
        self.client = playwright_client
        self.new_request = self.client.context.request


    def load_cache(self):
        if os.path.exists(self.cache_file):
            with open(self.cache_file, 'r') as f:
                return json.load(f)
        return {}

    def save_cache(self):
        with open(self.cache_file, 'w') as f:
            json.dump(self.cache, f)

    async def get_active_orders(
            self,
    ) -> List[Dict[str, Any]]:
        """
        Возвращает список active delivery positions.

        Бросает ProxyBlockedError при 498, UnauthorizedError при 401. При других ошибках, таймаутов
        закрывает текующий контекст и создает новый.
        """
        # url = "https://www.wildberries.ru/webapi/v2/lk/myorders/delivery/active"
        #
        # response = await self.request.fetch(
        #     url,
        #     method="POST",
        #     data=json.dumps({}),
        #     headers={
        #         "Accept": "application/json",
        #         "Authorization": f"Bearer {self.config.token}",
        #         "DeviceId": self.config.device_id,
        #         "User-Agent": self.config.useragent,
        #         "Content-Type": "application/json",
        #     },
        #     timeout=30_000,
        # )
        #
        # status = response.status
        #
        # if status == 498:
        #     raise ProxyBlockedError("Бан прокси - 498 ошибка")
        #
        # if status == 401:
        #     raise UnauthorizedError("Неактуальная авторизация - 401 ошибка")
        #
        # if status != 200:
        #     text = await response.text()
        #     raise PlaywrightError(f"HTTP статус {status}: {text}")
        #
        # data = await response.json()
        #
        # return data.get("value", {}).get("positions", [])
        url = "https://www.wildberries.ru/webapi/v2/lk/myorders/delivery/active"

        response = await self.request.post(
            url,
            headers={
                "Accept": "application/json",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                "Authorization": f"Bearer {self.client.config.token}",
                "DeviceId": self.client.config.device_id,
            },
            max_retries=2,
            timeout=30_000,
        )
        result = await response.json()

        if response.status == 498:
            raise ProxyBlockedError("Бан прокси - 498 ошибка")

        if response.status == 401:
            raise UnauthorizedError("Неактуальная авторизация - 401 ошибка")

        if response.status != 200:
            text = await response.text()
            raise PlaywrightError(f"HTTP статус {response.status}: {text}")

        return result.get("value", {}).get("positions", [])

    async def get_delivery_orders(
            self
    ) -> List[Dict[str, Any]]:
        """
        Возвращает orders (wbxoofex /api/v2/orders).
        """
        url = "https://wbxoofex.wildberries.ru/api/v2/orders"

        # response = await self.request.fetch(
        #     url,
        #     method="GET",
        #     data=json.dumps({}),
        #     headers={
        #         "Accept": "application/json",
        #         "Authorization": f"Bearer {self.config.token}",
        #         "DeviceId": self.config.device_id,
        #         "User-Agent": self.config.useragent,
        #         "Content-Type": "application/json",
        #     },
        #     timeout=30_000,
        # )
        #
        # status = response.status
        response = await self.request.get(
            url,
            headers={
                "Accept": "application/json",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                "Authorization": f"Bearer {self.client.config.token}",
                "DeviceId": self.client.config.device_id,
            },
            max_retries=2,
        )

        if response.status == 498:
            raise ProxyBlockedError("Бан прокси - 498 ошибка")

        if response.status == 401:
            raise UnauthorizedError("Неактуальная авторизация - 401 ошибка")

        if response.status != 200:
            text = await response.text()
            raise PlaywrightError(f"HTTP статус {response.status}: {text}")

        data = await response.json()

        return data.get("data", []) or []


    async def get_archived_orders(
            self,
            request_data
    ) -> List[Dict[str, Any]]:
        """
        Возвращает архивные заказы (archive/get). Бросает те же исключения на 498/401.
        """

        url = "https://www.wildberries.ru/webapi/lk/myorders/archive/get"

        # response = await self.request.fetch(
        #     url,
        #     method="POST",
        #     data=request_data,
        #     headers={
        #         "Accept": "application/json",
        #         "Authorization": f"Bearer {self.config.token}",
        #         "DeviceId": self.config.device_id,
        #         "User-Agent": self.config.useragent,
        #         "Content-Type": "application/json",
        #     },
        #     timeout=30_000,
        # )
        response = await self.request.post(
            url,
            headers={
                "Accept": "application/json",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                "Authorization": f"Bearer {self.client.config.token}",
                "DeviceId": self.client.config.device_id,
            },
            max_retries=2,
            params=request_data,
        )

        if response.status == 498:
            raise ProxyBlockedError("Бан прокси - 498 ошибка")

        if response.status == 401:
            raise UnauthorizedError("Неактуальная авторизация - 401 ошибка")

        if response.status != 200:
            text = await response.text()
            raise PlaywrightError(f"HTTP статус {response.status}: {text}")

        data = await response.json()

        # archive = data.get("value", {}).get("archive", []) or []

        # with open("archive_dump.json", "w", encoding="utf-8") as f:
        #     json.dump(archive, f, ensure_ascii=False, indent=2)

        return data.get("value", {}).get("archive", []) or []

    async def get_offices(
            self,
            office_ids: List[int]
    ) -> Dict[int, str]:
        url = "https://www.wildberries.ru/webapi/lk/myorders/delivery/offices"
        params = "&".join([f"ids={int(i)}" for i in office_ids])

        logger.info(f"Работаю с office_ids: {office_ids}")

        # response = await self.request.fetch(
        #     url,
        #     method="POST",
        #     data=params,
        #     headers={
        #         "Accept": "application/json",
        #         "Authorization": f"Bearer {self.config.token}",
        #         "DeviceId": self.config.device_id,
        #         "User-Agent": self.config.useragent,
        #         "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        #     },
        #     timeout=30_000
        # )
        response = await self.request.post(
            url,
            headers={
                "Accept": "application/json",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                "Authorization": f"Bearer {self.client.config.token}",
                "DeviceId": self.client.config.device_id,
            },
            max_retries=2,
            params=params,
        )

        status = response.status

        if status == 498:
            raise ProxyBlockedError("Бан прокси - 498 ошибка")

        if status == 401:
            raise UnauthorizedError("Неактуальная авторизация - 401 ошибка")

        if status != 200:
            text = await response.text()
            raise PlaywrightError(f"HTTP статус {status}: {text}")

        data = await response.json()

        out: Dict[int, str] = {}

        value_list = data.get("value", [])
        for k, v in value_list.items():
            try:
                out[int(k)] = v.get("address")
            except:
                pass

        return out

    async def get_tracker_status(
            self,
            uid: Optional[str],
            phone_number: Optional[str] = None
    ) -> Optional[str]:
        logger.info(f"Работаю с UID={uid}")

        shard = None
        if phone_number and phone_number in self.cache:
            shard = self.cache[phone_number]
            logger.info(f"Используем закэшированный shard={shard} для phone_number={phone_number}")

        try:
            if not shard:
                logger.info("Не найден подходящий shard в кэше, пробую все от 1 до 100.")
                for shard in range(1, 101):
                    logger.info(f"Делаю запрос с shard={shard}")
                    url = f"https://wbx-status-tracker.wildberries.ru/api/v3/statuses/{uid}?shard={shard}"

                    # response = await self.request.fetch(
                    #     url,
                    #     method="GET",
                    #     headers={
                    #         "Accept": "application/json",
                    #         "Authorization": f"Bearer {self.config.token}",
                    #         "DeviceId": self.config.device_id,
                    #         "User-Agent": self.config.useragent,
                    #         "Content-Type": "application/json",
                    #     },
                    #     timeout=30_000,
                    # )
                    response = await self.request.get(
                        url,
                        headers={
                            "Accept": "application/json",
                            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                            "Authorization": f"Bearer {self.client.config.token}",
                            "DeviceId": self.client.config.device_id,
                        },
                        max_retries=2
                    )
                    status = response.status

                    if status == 498:
                        raise ProxyBlockedError("Бан прокси - 498 ошибка")

                    if status == 401:
                        raise UnauthorizedError("Неактуальная авторизация - 401 ошибка")

                    if status != 200:
                        text = await response.text()
                        raise PlaywrightError(f"HTTP статус {status}: {text}")

                    data = await response.json()

                    if data:
                        logger.info(f"Удалось найти shard для {phone_number}. Сохранил в кэше.")

                        self.cache[phone_number] = shard
                        self.save_cache()

                        last_status = data[-1] if data else None

                        if last_status:

                            if uid == last_status.get('rid'):
                                logger.info(f"Последний статус для UID={uid}: {last_status['status_name']}")

                                return last_status['status_name']
                            else:
                                logger.info(f"UID не совпадает с rid: {uid} != {last_status.get('rid')}")
                        else:
                            logger.info(f"Статусов не найдено для UID={uid}")
            else:
                logger.info(f"Есть shard для {phone_number} в кэше использую его только: {shard}")

                url = f"https://wbx-status-tracker.wildberries.ru/api/v3/statuses/{uid}?shard={shard}"

                # response = await self.request.fetch(
                #     url,
                #     method="GET",
                #     headers={
                #         "Accept": "application/json",
                #         "Authorization": f"Bearer {self.config.token}",
                #         "DeviceId": self.config.device_id,
                #         "User-Agent": self.config.useragent,
                #         "Content-Type": "application/json",
                #     },
                #     timeout=30_000,
                # )
                response = await self.request.get(
                    url,
                    headers={
                        "Accept": "application/json",
                        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                        "Authorization": f"Bearer {self.client.config.token}",
                        "DeviceId": self.client.config.device_id,
                    },
                    max_retries=2
                )
                status = response.status

                if status == 498:
                    raise ProxyBlockedError("Бан прокси - 498 ошибка")

                if status == 401:
                    raise UnauthorizedError("Неактуальная авторизация - 401 ошибка")

                if status != 200:
                    text = await response.text()
                    raise PlaywrightError(f"HTTP статус {status}: {text}")

                data = await response.json()

                if data:
                    self.cache[phone_number] = shard
                    self.save_cache()

                    last_status = data[-1] if data else None

                    if last_status:

                        if uid == last_status.get('rid'):
                            logger.info(f"Последний статус для UID={uid}: {last_status['status_name']}")

                            return last_status['status_name']
                        else:
                            logger.info(f"UID не совпадает с rid: {uid} != {last_status.get('rid')}")
                    else:
                        logger.info(f"Статусов не найдено для UID={uid}")
        except Exception as e:
            logger.warning(f"Не получилось взять статус для UID={uid}. Статус Shard: {shard}. Текст: {e}")
            return None

    async def get_links_receipts(
            self,
            req_params
    ):
        url = "https://astro.wildberries.ru/api/v1/receipt-api/v1/receipts"

        # response = await self.request.fetch(
        #     url,
        #     method="GET",
        #     data=req_params,
        #     headers={
        #         "Accept": "application/json",
        #         "Authorization": f"Bearer {self.config.token}",
        #         "DeviceId": self.config.device_id,
        #         "User-Agent": self.config.useragent,
        #         "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        #     },
        #     timeout=30_000
        # )
        response = await self.request.get(
            url,
            headers={
                "Accept": "application/json",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                "Authorization": f"Bearer {self.client.config.token}",
                "DeviceId": self.client.config.device_id,
            },
            max_retries=2,
            params=req_params,
        )
        status = response.status

        if status == 498:
            raise ProxyBlockedError("Бан прокси - 498 ошибка")

        if status == 401:
            raise UnauthorizedError("Неактуальная авторизация - 401 ошибка")

        if status != 200:
            text = await response.text()
            raise PlaywrightError(f"HTTP статус {status}: {text}")

        data = await response.json()

        return data.get('data', {}).get('result', {}).get('data', {})