import datetime
import json
import os
import multiprocessing
import random
import asyncio
import re
import shutil
import time
import telebot
import asyncpg
import psutil

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException, NoSuchElementException
from selenium.webdriver.common.keys import Keys

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


def check_sms_block_conditions(driver, chat_id):
    try:
        span_block = driver.find_element(By.XPATH, "/html/body/div[1]/div/div/div/form/div/div[2]/span[2]")
        text = span_block.text.strip()
        if text.startswith("Не прошло время"):
            bot.send_message(chat_id, f"<b>❌ Извините, но для Вас, авторизация временно недоступна.</b> Попробуйте позже.\n\n"
                                      f"<b>Причина: ⏳ {text}</b>", parse_mode="HTML")
            print(f"[{chat_id}] — Ожидание лимита на запрос кода: {text}")
            driver.quit()
            return False

    except NoSuchElementException:
        pass

    try:
        countdown_block = driver.find_element(By.CSS_SELECTOR, "div.login__countdown")
        text = countdown_block.text.strip()
        time_left = parse_time(text)
        if time_left and time_left.total_seconds() > 3600:  # > 1 час
            bot.send_message(chat_id, "<b>❌ Извините, но для Вас, авторизация временно недоступна.</b> Попробуйте позже.\n\n"
                                      "<b>Причина: ⏳ {text}</b>", parse_mode="HTML")
            print(f"[{chat_id}] — Ожидание лимита на запрос кода: {text}")
            driver.quit()
            return False

    except NoSuchElementException:
        pass  # Элемент не найден — продолжаем

    return True  # Всё нормально — продолжаем авторизацию


def create_selenium_processes():
    """
    Создаем процессы Selenium - для распредления задач.

    :param
        process_ids: int
    :return:
    """
    process_lst = []
    process_ids = list(range(1, 12))
    asyncio.run(update_selenium_process_table(process_ids))

    for process_id in process_ids:
        p = multiprocessing.Process(target=start_selenium_process, args=(process_id,))
        print(f"Запущен процесс Selenium-{process_id}, PID: {p.pid}")
        process_lst.append(p)
        p.start()

    for p in process_lst:
        p.join()


def start_selenium_process(process_id):
    """
    Запускаем Selenium-процесыы.
    :param process_id: int
    :return:
    """
    time.sleep(random.randint(3, 5))
    print(f'запущен процесс {process_id}')
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(handle_selenium_loop(process_id))


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



async def handle_selenium_loop(process_id):
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
                    result = WildberriesSeleniumAuth(
                        process_id, phone_number, chat_id,
                        proxy_name, proxy_id, user_agent
                    )

                    try:
                        auth_result = await result.authorize_user()

                        print(f"Результат: {auth_result}")
                        if auth_result:
                            # Успешная авторизация
                            await good_registration(user_id=chat_id)
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


class WildberriesSeleniumAuth:
    """
    Модуль обработчиков событий Selenium
    """
    def __init__(self, selenium_id, phone_number, chat_id, proxy_name, proxy_id, user_agent):
        self.chat_id = chat_id
        self.phone_number = phone_number
        self.selenium_id = selenium_id
        self.process_id = selenium_id
        self.driver = None
        self.user_agent = user_agent
        self.proxy_name = proxy_name
        self.code_iteration = 1
        self.user_data_dir = f"/home/AuthorizationBot/profiles/{self.chat_id}_{self.phone_number}"
        self.profile_name = "Default"

    def setup_driver(self):
        self.kill_zombie_chrome()
        
        chrome_options = Options()
        chrome_options.add_argument(f"user-agent={self.user_agent}")
        chrome_options.add_argument("start-maximized")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--headless=new")  # Если headless нужен

        os.makedirs(self.user_data_dir, exist_ok=True)
        chrome_options.add_argument(f"--user-data-dir={self.user_data_dir}")
        chrome_options.add_argument(f"--profile-directory={self.profile_name}")

        chrome_options.add_argument("--allow-profiles-outside-user-dir")
        chrome_options.add_argument("--enable-profile-shortcut-manager")

        self.driver = webdriver.Chrome(options=chrome_options)

    def teardown(self):
        if self.driver:
            self.driver.quit()
        # shutil.rmtree(self.user_data_dir, ignore_errors=True)  # Удаление только вручную при необходимости
        print(f"Профиль сохранён: {self.user_data_dir}")

    def kill_zombie_chrome(self):
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                cmd = " ".join(proc.info["cmdline"]) if proc.info["cmdline"] else ""
                if "chromedriver" in proc.info["name"] or "chrome" in cmd:
                    if str(self.chat_id) in cmd or str(self.phone_number) in cmd:
                        proc.kill()
                        print(f"[{self.chat_id}] Убил зависший процесс: {proc.info['name']} (PID: {proc.pid})")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    def wait_xpath(self, xpath, timeout=10):
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((By.XPATH, xpath))
        )

    def check_authorization_initial(self):
        """
        Проверка авторизации перед началом входа.
        Если пользователь уже авторизован — возвращает True.
        Если редиректит на login — возвращает False.
        """
        print('check_authorization (initial)')
        try:
            WB_ORDERS_URL = 'https://www.wildberries.ru/lk/myorders/archive'
            LOGIN_URL = 'https://www.wildberries.ru/security/login'

            self.driver.get(WB_ORDERS_URL)
            time.sleep(3)

            current_url = self.driver.current_url
            print(f"[{self.chat_id}] Текущий URL: {current_url}")

            # Проверяем — не редиректнуло ли на login
            if LOGIN_URL in current_url:
                print(" Пользователь не авторизован (редирект на страницу входа).")
                return False

            # Если остались в /lk/myorders — проверяем наличие элемента (опционально)
            try:
                search_query = (By.XPATH, '//a[contains(text(), "Архив заказов")]')
                wait = WebDriverWait(self.driver, 5)
                element = wait.until(EC.visibility_of_element_located(search_query))
                if element:
                    print(" Пользователь уже авторизован (страница заказов доступна).")
                    return True
            except TimeoutException:
                print(
                    " Элемент 'Архив заказов' не найден, но редиректа не было — предполагаем, что авторизация есть.")
                return True

            return True

        except Exception as ex:
            print(f'check_authorization_initial Ошибка: {type(ex).__name__}: {str(ex)}')
            return False

    async def authorize_user(self):
        self.setup_driver()
        driver = self.driver
        driver.get("https://www.wildberries.ru/security/login?returnUrl=https%3A%2F%2Fwww.wildberries.ru%2F")
        time.sleep(5)

        await self.snapshot("Загрузил страницу")

        # if self.check_authorization():
        if self.check_authorization_initial():
            print("Пользователь уже авторизован — пропускаем ввод кода.")

            await self.snapshot("Пользователь уже авторизован — пропускаем ввод кода.")

            headers = {
                "Cookie": self.get_cookies_str(),
                "User-Agent": self.user_agent,
                "Proxy-Authorization": f"Basic {self.proxy_name}"
            }

            bot.send_message(self.chat_id, f"<b>Спасибо ☺️</b>\n\n"
                                           f"🟢 Я успешно вошел в Ваш аккаунт.\n\n"
                                           f"<b>Остался последний этап… 🤌</b>", parse_mode="HTML")
            await self.store_auth_success(headers)

            await self.snapshot("Перешел в ЛК")
            # Переход в ЛК и всё, что идёт после
            self.driver.get("https://www.wildberries.ru/lk")
            time.sleep(5)

            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            self.driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(2)

            await self.complete_success()
            return True
        try:
            phone_xpath = '/html/body/div[2]/main/div[2]/div[1]/div/div[1]/div/div/form/div/div/div[2]/input'
            phone_el = self.wait_xpath(phone_xpath)
            phone_el.click()
            self.backspace_clear(phone_el, times=20)
            phone_number = str(self.phone_number)
            phone_el.send_keys(phone_number)
            phone_el.send_keys(Keys.TAB)
            time.sleep(1)

            await self.snapshot("Ввел номер телефона")

            # Жмём кнопку "Получить код"
            btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, "requestCode"))
            )
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
            time.sleep(0.3)
            try:
                btn.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", btn)
            print(f"[{self.chat_id}] Кнопка 'Получить код' нажата")
            time.sleep(6)
            await self.snapshot("Нажал получить код")

            # Ждём поле для SMS
            code_input_xpath = '/html/body/div[2]/main/div[2]/div[1]/div/div[1]/div/div/form/div/div[2]/div/div[1]/input'
            # code_input_xpath = '//*[@id="spaAuthForm"]//input[contains(@class,"charInputItem")]'

            # self.wait_xpath(code_input_xpath)
            # print(f"[{self.chat_id}] Поле для SMS доступно")

            # Ждём код от юзера и вводим
            success = await self.await_code_input(code_input_xpath, self.phone_number)

            if not success:
                print(f"[user_id: {self.chat_id}] ❌ Не дождались корректного кода.")
                return False

            await self.snapshot("Код введён")

            time.sleep(5)
            headers = {
                "Cookie": self.get_cookies_str(),
                "User-Agent": self.user_agent,
                "Proxy-Authorization": f"Basic {self.proxy_name}"
            }

            response = self.check_authorization()
            time.sleep(5)
            if response:
                bot.send_message(self.chat_id, f"<b>Спасибо ☺️</b>\n\n"
                                               f"🟢 Я успешно вошел в Ваш аккаунт.\n\n"
                                               f"<b>Остался последний этап… 🤌</b>", parse_mode="HTML")
                await self.store_auth_success(headers)
            else:
                raise Exception("Проверка авторизации не прошла.")

            # 5. Переход в ЛК
            self.driver.get("https://www.wildberries.ru/lk")
            time.sleep(5)

            # Скроллим вниз и вверх — для прогрузки
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            self.driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(2)

            await self.complete_success()
            return True
        except Exception as e:
            print(f"ERROR: {e}")
            return False
        finally:
            self.teardown()

    def backspace_clear(self, el, times: int = 15):
        el.click()
        # Последовательно жмём Backspace — без clear()/JS
        for _ in range(times):
            el.send_keys(Keys.BACK_SPACE)
            time.sleep(0.02)


    def get_cookies_str(self):
        cookies = self.driver.get_cookies()
        return "; ".join([f"{c['name']}={c['value']}" for c in cookies])

    def check_authorization(self):
        """
        Проверка авторизации через Selenium.
        Успех -> остаёмся на https://www.wildberries.ru/lk/myorders/delivery
        Неуспех -> редиректит обратно на login + кнопка "Получить код"
        """
        print('check_authorization (новая логика)')
        try:
            TARGET_URL = "https://www.wildberries.ru/lk/myorders/delivery"
            LOGIN_URL = "https://www.wildberries.ru/security/login"

            self.driver.get(TARGET_URL)
            time.sleep(5)  # ждём редирект, если он будет

            cur_url = self.driver.current_url
            print(f"Текущий URL после проверки: {cur_url}")

            if cur_url.startswith(TARGET_URL):
                print(" Пользователь авторизован (остался на delivery).")
                return True

            if cur_url.startswith(LOGIN_URL):
                # Проверяем наличие кнопки "Получить код"
                try:
                    btn = WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.ID, "requestCode"))
                    )
                    if btn:
                        print(" Авторизация неуспешна: редирект на login + кнопка 'Получить код'")
                        return False
                except TimeoutException:
                    print(" Авторизация неуспешна: редирект на login, кнопка не найдена.")
                    return False

            print(" Авторизация неуспешна: неизвестное состояние (URL не совпадает).")
            return False

        except Exception as ex:
            print(f'check_authorization Ошибка: {type(ex).__name__}: {str(ex)}')
            try:
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                self.driver.save_screenshot(f"screenshots/check_authorization_error_{self.chat_id}_{ts}.png")
            except:
                pass
            return False

    async def store_auth_success(self, headers):
        try:
            # 1. Получаем cookies
            cookies_list = self.driver.get_cookies()
            cookies_str = "; ".join([f"{item['name']}={item['value']}" for item in cookies_list])

            # 2. Получаем токен из localStorage через JS
            token_data_raw = self.driver.execute_script('return localStorage.getItem("wbx__tokenData");')
            auth_token = ""
            if token_data_raw:
                try:
                    auth_token = 'Bearer ' + json.loads(token_data_raw).get("token", "")
                except Exception as e:
                    print(f"store_auth_success Ошибка парсинга токена: {e}")

            # 3. Записываем в базу данных
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

    async def snapshot(self, step_name: str):
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')

        import os
        os.makedirs("screenshots", exist_ok=True)

        filename = f"screenshots/{self.phone_number}_{step_name}_{timestamp}.png"

        self.driver.save_screenshot(filename)
        with open(filename, "rb") as img:
            bot.send_photo(687061691, img, caption=f"{step_name} @ {timestamp}")

    async def await_code_input(self, input_xpath: str, phone_number: str):
        """
        Улучшенная версия ввода кода с правильной обработкой статусов
        Возвращает: "success", "wrong_code", "timeout", "error"
        """
        print(f"[{self.chat_id}] Начало ввода кода")
        max_attempts = 2

        for attempt in range(1, max_attempts + 1):
            print(f"[{self.chat_id}] Попытка {attempt} из {max_attempts}")
            await self.snapshot(f"Старт попытки {attempt}")

            # Запрашиваем SMS у пользователя
            sent = await sms_registration(user_id=int(self.chat_id), attempt_number=attempt)
            if not sent:
                return "error"

            # Ждем код от пользователя
            code = await self.wait_for_sms_code(timeout=60)
            if not code:
                # Таймаут - пробуем запросить код повторно
                return await self.handle_code_timeout(attempt)

            # Вводим код и проверяем результат
            result = await self.enter_and_check_code(code, input_xpath)

            if result == "success":
                return "success"
            elif result == "wrong_code":
                if attempt < max_attempts:
                    # Пробуем еще раз
                    continue
                else:
                    return "wrong_code"
            else:
                return "error"

        return "error"

    async def wait_for_sms_code(self, timeout: int):
        """Ожидает SMS код от пользователя"""
        print(f"[{self.chat_id}] Ожидаю ввод кода от пользователя ({timeout} секунд)...")

        for _ in range(timeout):
            await asyncio.sleep(1)
            try:
                code = await check_sms_code_requests(user_id=str(self.chat_id))
                if code:
                    print(f"[{self.chat_id}] Получен код: {code}")
                    await clear_sms_code(str(self.chat_id))
                    return code
            except Exception as e:
                print(f"[{self.chat_id}] Ошибка check_sms_code_requests: {e}")

        return None

    async def handle_code_timeout(self, attempt: int):
        """Обрабатывает таймаут ожидания кода"""
        print(f"[{self.chat_id}] Код не получен в течение 60 секунд")

        bot.send_message(self.chat_id,
                        "<b>⌛ Время ожидания истекло</b>\n\n"
                        "Я запрошу код повторно, пожалуйста, ожидайте новый код…",
                        parse_mode="HTML")

        # Пробуем нажать кнопку повторной отправки
        if await self.click_retry_button():
            # Ждем новый код
            new_code = await self.wait_for_sms_code(timeout=90)
            if new_code:
                return "retry"  # Вернем специальный статус для повторной попытки
            else:
                bot.send_message(self.chat_id, "❌ Не удалось получить код даже после повторного запроса.")
                return "timeout"
        else:
            bot.send_message(self.chat_id, "❌ Не смог нажать кнопку повторного запроса.")
            return "error"

    async def enter_and_check_code(self, code: str, input_xpath: str):
        """Вводит код и проверяет результат"""
        print(f"[{self.chat_id}] Ввожу код: {code}")

        # Вводим код в поля
        if not await self.enter_code_to_inputs(code, input_xpath):
            return "error"

        await self.snapshot("Код введён")

        # Ждем и проверяем результат
        return await self.wait_for_auth_result()

    async def enter_code_to_inputs(self, code: str, input_xpath: str):
        """Вводит код в input поля"""
        try:
            code = str(code).strip()

            # Находим все поля для ввода кода
            cells = WebDriverWait(self.driver, 10).until(
                EC.presence_of_all_elements_located(
                    (By.CSS_SELECTOR, "#spaAuthForm input.j-b-charinput")
                )
            )

            if len(code) > len(cells):
                code = code[:len(cells)]

            # Очищаем поля
            for el in cells:
                try:
                    el.clear()
                except Exception:
                    self.backspace_clear(el, times=2)

            # Вводим код
            for ch, el in zip(code, cells):
                try:
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
                    el.click()
                    el.send_keys(ch)
                    time.sleep(0.08)
                except Exception as e:
                    print(f"[{self.chat_id}] Ошибка при вводе символа {ch}: {e}")
                    return False

            print(f"[{self.chat_id}] Код введён по отдельным input'ам")
            return True

        except Exception as e:
            print(f"[{self.chat_id}] Ошибка при вводе кода: {e}")
            return False

    async def wait_for_auth_result(self, timeout: int = 15):
        """Ожидает и проверяет результат авторизации"""
        print(f"[{self.chat_id}] Ожидаю результат авторизации...")

        start_time = time.time()

        while time.time() - start_time < timeout:
            await asyncio.sleep(0.5)

            # 1. СНАЧАЛА проверяем УСПЕШНУЮ авторизацию
            if self.check_authorization_initial():
                print(f"[{self.chat_id}] ✅ Авторизация успешна!")
                await self.snapshot("Успешная авторизация")
                return "success"

            # 2. Потом проверяем ОШИБКИ
            error_text = await self.check_for_errors()
            if error_text:
                print(f"[{self.chat_id}] Обнаружена ошибка: {error_text}")
                if "Неверный код" in error_text or "Запросите код повторно" in error_text:
                    return "wrong_code"
                return "error"

            # 3. Проверяем исчезновение полей ввода (косвенный признак успеха)
            if await self.check_inputs_disappeared():
                # Если поля исчезли, еще раз проверяем авторизацию
                if self.check_authorization_initial():
                    return "success"

        print(f"[{self.chat_id}] Таймаут ожидания результата авторизации")
        return "timeout"

    async def check_for_errors(self):
        """Проверяет наличие сообщений об ошибках"""
        error_selectors = [
            '/html/body/div[1]/div/div/div/form/div/div[4]/p[2]/span',
            '/html/body/div[2]/main/div[2]/div[1]/div/div[1]/div/div/form/div/div[2]/p'
        ]

        for selector in error_selectors:
            try:
                error_el = self.driver.find_element(By.XPATH, selector)
                error_text = error_el.text.strip()
                if error_text:
                    return error_text
            except:
                continue
        return ""

    async def check_inputs_disappeared(self):
        """Проверяет, исчезли ли поля ввода кода"""
        try:
            cells = self.driver.find_elements(By.CSS_SELECTOR, "#spaAuthForm input.j-b-charinput")
            return len(cells) == 0
        except:
            return False

    async def click_retry_button(self):
        """Пытается нажать кнопку повторной отправки кода"""
        print(f"[{self.chat_id}] Ищу кнопку 'Запросить код повторно'...")

        selectors = [
            (By.ID, 'requestCode'),
            (By.CSS_SELECTOR, "button.login__btn-request.btn-minor"),
            (By.XPATH, '/html/body/div[1]/div/div/div/form/div/button'),
            (By.XPATH, '/html/body/div[1]/main/div[2]/div[3]/div[2]/div/div/form/div/button'),
        ]

        for by, selector in selectors:
            try:
                btn = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((by, selector))
                )
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                time.sleep(0.5)
                btn.click()
                print(f"[{self.chat_id}] Кнопка 'Запросить код повторно' нажата")
                return True
            except:
                continue

        print(f"[{self.chat_id}] Не удалось найти активную кнопку повторного запроса")
        return False


if __name__ == "__main__":
    create_selenium_processes()
