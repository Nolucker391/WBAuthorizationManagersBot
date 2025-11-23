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
        # Проверка: "Не прошло время для повторной отправки..."
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
                            admin_ids = [687061691, 6712521678]

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
        # self.user_data_dir = f"/home/AuthorizationBot/profiles/{self.chat_id}_{self.phone_number}"
        self.user_data_dir = f"/mnt/c/Users/User2/PycharmProjects/ManagersAuthorizationBot/profiles/{self.chat_id}_{self.phone_number}"
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

        # Указываем путь к Chrome через Service args (работает с символическими ссылками)
        from selenium.webdriver.chrome.service import Service
        
        # Используем реальный путь к бинарнику Chrome
        chrome_binary = '/opt/google/chrome/chrome'
        if not os.path.exists(chrome_binary):
            # Если не найден, пробуем через which
            import shutil
            chrome_binary = shutil.which('google-chrome') or '/usr/bin/google-chrome'
        
        service = Service(
            executable_path='/usr/bin/chromedriver',
            service_args=['--binary=' + chrome_binary] if chrome_binary else []
        )
        
        self.driver = webdriver.Chrome(service=service, options=chrome_options)

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
                print(f"[user_id: {self.chat_id}] Не дождались корректного кода.")
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
            # self.driver.get("https://www.wildberries.ru/lk")
            # time.sleep(5)

            # Скроллим вниз и вверх — для прогрузки
            # self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            # time.sleep(2)
            # self.driver.execute_script("window.scrollTo(0, 0);")
            # time.sleep(2)

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
                print("Пользователь авторизован (остался на delivery).")
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

    async def await_code_input(self, input_xpath: str, phone_number: str):
        print("Начал ввода кода")
        max_attempts = 2

        for attempt in range(1, max_attempts + 1):
            print(f"[{self.chat_id}] Попытка {attempt} из {max_attempts}")
            await self.snapshot(f"Старт попытки {attempt}")

            sent = await sms_registration(user_id=int(self.chat_id), attempt_number=attempt)
            if not sent:
                print("await_code_input: sms_registration вернуло False")
                return None

            print("Ожидаю ввод кода от пользователя (1 минута)...")
            code = None
            for _ in range(60):
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
                # Пользователь ничего не ввёл — жмём "Запросить код повторно"
                print("Код не получен в течение 60 секунд. Пробуем запросить повторно.")

                bot.send_message(self.chat_id, "<b>⌛ Время ожидания истекло</b>\n\n"
                                               "Я запрошу код повторно, пожалуйста, ожидайте новый код…",
                                 parse_mode="HTML")

                total_seconds = 90  # ждём 1.5 минуты после повторного запроса

                # Нажимаем "Запросить код повторно"
                try:
                    print("Ищем кнопку 'Запросить код повторно'...")
                    repeat_btn = None

                    try:
                        repeat_btn = WebDriverWait(self.driver, timeout=10).until(
                            EC.element_to_be_clickable((By.ID, 'requestCode'))
                        )
                    except:
                        pass

                    if not repeat_btn:
                        try:
                            repeat_btn = WebDriverWait(self.driver, timeout=10).until(
                                EC.element_to_be_clickable((By.CSS_SELECTOR, "button.login__btn-request.btn-minor"))
                            )
                        except:
                            pass

                    if not repeat_btn:
                        try:
                            repeat_btn = WebDriverWait(self.driver, timeout=10).until(
                                EC.element_to_be_clickable((By.XPATH, '/html/body/div[1]/div/div/div/form/div/button'))
                            )
                        except:
                            pass

                    if not repeat_btn:
                        repeat_btn = WebDriverWait(self.driver, timeout=10).until(
                            EC.element_to_be_clickable(
                                (By.XPATH, '/html/body/div[1]/main/div[2]/div[3]/div[2]/div/div/form/div/button'))
                        )

                    # Скроллим к кнопке
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", repeat_btn)
                    time.sleep(0.5)

                    try:
                        repeat_btn.click()
                    except Exception:
                        self.driver.execute_script("arguments[0].click();", repeat_btn)

                    print("Кнопка 'Запросить код повторно' нажата")
                    await sms_registration(user_id=int(self.chat_id), attempt_number=attempt)

                except Exception as e:
                    print(f"Ошибка при повторном запросе кода: {e}")
                    bot.send_message(self.chat_id, "❌ Не смог нажать кнопку повторного запроса.")
                    return None

                # Ждём новый код
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

            # Пробуем ввести код
            for try_count in range(3):
                print(f"Try{try_count} - Код получил, ввожу его:")
                try:
                    current_url = self.driver.current_url
                    if "security/login" not in current_url:
                        print(f"[{self.chat_id}] После ввода кода страница сменилась -> {current_url}")
                        if self.check_authorization_initial():
                            await self.snapshot(f"{self.chat_id} - Код ввели - словили редирект")
                            print(f"[{self.chat_id}] Авторизация подтверждена сразу после ввода кода.")
                            return True
                        else:
                            print("Редиректа не было - значит  код неверный")
                    else:
                        print(
                            f"[{self.chat_id}] Остались на странице логина ({current_url}) — продолжаем обычную обработку.")
                except Exception as e:
                    print(f"[{self.chat_id}] Ошибка при мгновенной проверке редиректа: {e}")

                try:
                    code = str(code).strip()

                    cells = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_all_elements_located(
                            (By.CSS_SELECTOR, "#spaAuthForm input.j-b-charinput")
                        )
                    )

                    if len(code) > len(cells):
                        code = code[:len(cells)]

                    for el in cells:
                        try:
                            el.clear()
                        except Exception:
                            # на всякий случай — через backspace
                            self.backspace_clear(el, times=2)

                    for ch, el in zip(code, cells):
                        try:
                            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
                            el.click()
                            el.send_keys(ch)
                            time.sleep(0.08)  # короткая пауза, чтобы сработали обработчики
                        except Exception as e:
                            print(f"Ошибка при вводе символа {ch}: {e}")

                    entered = "".join((el.get_attribute("value") or "") for el in cells)[:len(code)]
                    if entered != code:
                        print(f"Введено не полностью ({entered} != {code}), пробуем JS-вставку по ячейкам")
                        for ch, el in zip(code, cells):
                            self.driver.execute_script(
                                "arguments[0].value = arguments[1];"
                                "arguments[0].dispatchEvent(new Event('input', { bubbles: true }));",
                                el, ch
                            )
                        entered = "".join((el.get_attribute("value") or "") for el in cells)[:len(code)]
                    time.sleep(0.5)

                    await self.snapshot(f"[{self.chat_id}] - Ввел код по ячейкам = {entered}")
                    print("Код введён по ячейкам")

                    try:
                        current_url = self.driver.current_url
                        if "security/login" not in current_url:
                            print(f"[{self.chat_id}] После ввода кода страница сменилась -> {current_url}")
                            if self.check_authorization_initial():
                                await self.snapshot(f"{self.chat_id} - Код ввели - словили редирект")
                                print(f"[{self.chat_id}] Авторизация подтверждена сразу после ввода кода.")
                                return True
                            else:
                                print("Редиректа не было - значит  код неверный")
                        else:
                            print(
                                f"[{self.chat_id}] Остались на странице логина ({current_url}) — продолжаем обычную обработку.")
                    except Exception as e:
                        print(f"[{self.chat_id}] Ошибка при мгновенной проверке редиректа: {e}")

                    start_check = time.time()
                    while time.time() - start_check < 15:
                        await asyncio.sleep(0.5)

                        try:
                            cur_url = (self.driver.current_url or "")
                        except Exception:
                            cur_url = ""

                        error_text = ""
                        try:
                            errA_el = self.driver.find_element(By.XPATH,
                                                               '/html/body/div[1]/div/div/div/form/div/div[4]/p[2]/span')
                            error_text = (errA_el.text or "").strip()
                        except Exception:
                            pass
                        if not error_text:
                            try:
                                errB_el = self.driver.find_element(By.XPATH,
                                                                   '/html/body/div[1]/main/div[2]/div[1]/div/div[1]/div/div/form/div/div[2]/p')
                                error_text = (errB_el.text or "").strip()
                            except Exception:
                                pass
                        if error_text:
                            print(f"[{self.chat_id}] Явная ошибка после ввода кода: {error_text}")
                            # не считаем это успехом — выходим к обработке ошибки ниже
                            break

                        if cur_url and "security/login" not in cur_url:
                            print(f"[{self.chat_id}] URL сменился -> пробуем проверить авторизацию через check_authorization_initial(): {cur_url}")
                            try:
                                if self.check_authorization_initial():
                                    await self.snapshot("Редирект после ввода кода (успех)")
                                    return True
                                else:
                                    print(f"[{self.chat_id}] check_authorization_initial() вернул False после смены URL.")
                                    # если initial вернул False — прекращаем ожидание и идём к обработке ошибки
                                    break
                            except Exception as e:
                                print(f"[{self.chat_id}] Ошибка при check_authorization_initial(): {e}")
                                # продолжим ожидать, чтобы дать странице проявить ошибку
                                continue

                        try:
                            still_cells = self.driver.find_elements(By.CSS_SELECTOR, "#spaAuthForm input.j-b-charinput")
                        except Exception:
                            still_cells = []

                        if len(still_cells) == 0:
                            print(f"[{self.chat_id}] Поля ввода кода исчезли — проверяем аккуратно (не считаем успехом сразу). current_url={cur_url}")
                            # если мы видимо на странице логина — это скорее ложный успех -> продолжаем ждать ошибки/таймер
                            if "security/login" in cur_url:
                                print(f"[{self.chat_id}] Поля исчезли, но URL содержит security/login -> ложный успех, продолжаем ожидание")
                                continue

                            # Попробуем подтвердить авторизацию через initial (это сделает аккуратную проверку)
                            try:
                                if self.check_authorization_initial():
                                    print(f"[{self.chat_id}] Поля исчезли и check_authorization_initial подтвердил авторизацию.")
                                    await self.snapshot("Форма исчезла (успех подтверждён через initial)")
                                    return True
                                else:
                                    print(f"[{self.chat_id}] Поля исчезли, но initial вернул False -> возможно сообщение об ошибке появится, продолжаем ожидание")
                                    continue
                            except Exception as e:
                                print(f"[{self.chat_id}] Ошибка при проверке initial после исчезновения полей: {e}")
                                continue

                except Exception as e:
                    print(f"send_keys не сработал: {e}")
                    continue

                error_text = ""
                for _ in range(3):
                    await asyncio.sleep(1)
                    try:
                        error_el = self.driver.find_element(By.XPATH,
                                                            '/html/body/div[1]/div/div/div/form/div/div[4]/p[2]/span')
                        error_text = error_el.text.strip()
                        if error_text:
                            print(f"Ошибка: {error_text}")
                            break
                    except:
                        pass
                    try:
                        error_el = self.driver.find_element(By.XPATH,
                                                            '/html/body/div[2]/main/div[2]/div[1]/div/div[1]/div/div/form/div/div[2]/p')
                        error_text = error_el.text.strip()
                        if error_text:
                            print(f"Ошибка: {error_text}")
                            break
                    except:
                        pass

                if "Неверный код" in error_text or "Запросите код повторно" in error_text:
                    # Получаем оставшееся время
                    try:
                        print_timer = self.driver.find_element(By.XPATH,
                                                               '/html/body/div[2]/main/div[2]/div[1]/div/div[1]/div/div/form/div/div[2]/p').text

                    except:
                        print_timer = "04:01"

                    try:
                        minutes, seconds = map(int, print_timer.strip().split(":"))
                        total_seconds = minutes * 60 + seconds
                    except:
                        total_seconds = 240

                    bot.send_message(self.chat_id, f"<b>❌ Введенный Вами - код, оказался «НЕВЕРНЫМ» 😢</b>\n\n"
                                                   f"Я отправлю запрос на повторное получение кода на протяжении <b>4-ех минут.</b>\n\n"
                                                   f"<b>⏳ Ожидайте…</b>", parse_mode="HTML")
                    print(f"Ждём {total_seconds} секунд до 00:00...")

                    # Нажимаем кнопку
                    print("Ожидаем, когда кнопка 'Запросить код повторно' станет активной...")
                    elapsed = 0
                    while elapsed < total_seconds:
                        try:
                            # Попробуем найти кнопку (разными способами)
                            selectors = [
                                (By.ID, 'requestCode'),
                                (By.CSS_SELECTOR, "button.login__btn-request.btn-minor"),
                                (By.XPATH, '/html/body/div[1]/div/div/div/form/div/button'),
                                (By.XPATH, '/html/body/div[1]/main/div[2]/div[3]/div[2]/div/div/form/div/button'),
                            ]

                            repeat_btn = None
                            for by, selector in selectors:
                                try:
                                    btn = self.driver.find_element(by, selector)
                                    if btn.is_enabled():
                                        repeat_btn = btn
                                        break
                                except:
                                    continue

                            if repeat_btn:
                                print("Кнопка активна — пытаемся нажать.")
                                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});",
                                                           repeat_btn)
                                time.sleep(0.5)
                                try:
                                    repeat_btn.click()
                                except Exception as e:
                                    print(f"Клик обычным способом не сработал: {e}")
                                    try:
                                        self.driver.execute_script("arguments[0].click();", repeat_btn)
                                    except Exception as js_click_err:
                                        print(f"JS-клик не сработал: {js_click_err}")
                                        bot.send_message(self.chat_id, "❌ Не смог нажать кнопку повторного запроса.")
                                        return None

                                await update_last_auth_try_time(self.chat_id)
                                print("Нажали 'Запросить код повторно'")
                                break
                            else:
                                print(f"Кнопка ещё неактивна, жду 60 секунд...")

                        except Exception as e:
                            print(f"Ошибка при попытке нажать кнопку: {e}")
                        await asyncio.sleep(60)
                        elapsed += 60
                    else:
                        print("Кнопка так и не стала активной за 240 секунд.")
                        bot.send_message(self.chat_id, "<b>❌ Извините :(\n\n"
                                                       "Не удалось найти кнопку повторного запроса.</b>",
                                         parse_mode="HTML")
                        return None

                    # Повторная отправка и ожидание кода
                    sent = await sms_registration(user_id=int(self.chat_id), attempt_number=attempt)
                    if not sent:
                        return None

                    bot.send_message(self.chat_id, "<b>🔁 Отправил повторный код. Введите его.</b>\n\n"
                                                   "<b>💬 Подсказка:</b> если вдруг повторный код <b>Вам</b> не прийдет - попробуйте ввести предыдущий код (возможно вы ошиблись в цифре).",
                                     parse_mode="HTML"
                                     )
                    print("Ожидаем повторный код...")

                    for _ in range(180):
                        await asyncio.sleep(1)
                        try:
                            code = await check_sms_code_requests(user_id=str(self.chat_id))
                            if code:
                                print(f"Повторно получен код: {code}")
                                await clear_sms_code(str(self.chat_id))
                                break
                        except:
                            continue
                    else:
                        print("Повторный код не пришёл.")
                        bot.send_message(self.chat_id, "❌ Повторный код не получен.")
                        return None

                    # Повторный ввод
                    cells = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_all_elements_located(
                            (By.CSS_SELECTOR, "#spaAuthForm input.j-b-charinput")
                        )
                    )
                    code = str(code).strip()
                    
                    for ch, el in zip(code, cells):
                        try:
                            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
                            el.click()
                            el.send_keys(ch)
                            time.sleep(0.1)  # небольшая задержка для стабильности
                        except StaleElementReferenceException:
                            # если страница уже обновилась — скорее всего код был верным
                            try:
                                cur_url = self.driver.current_url
                            except Exception:
                                cur_url = ""
                            if "security/login" not in cur_url and cur_url:
                                print(
                                    f"[{self.chat_id}] StaleElement после ввода — вероятно, страница уже обновилась (успешный вход)")
                                await self.snapshot("StaleElement -> авторизация вероятно успешна")
                                return True
                            else:
                                print(f"[{self.chat_id}] StaleElement, но URL всё ещё login — продолжаем попытку")
                                continue
                        except Exception as e:
                            print(f"Ошибка при вводе символа {ch}: {e}")

                    print("Повторно ввели код через JS")
                    return True
                print("Код принят (по отсутствию ошибок), продолжаем")
                return True

            print("Попытка неудачна. Пробуем заново...")

        print("Все попытки исчерпаны.")
        await update_last_auth_try_time(self.chat_id)
        return None

    async def snapshot(self, step_name: str):
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')\

        import os
        os.makedirs("screenshots", exist_ok=True)

        filename = f"screenshots/{self.phone_number}_{step_name}_{timestamp}.png"

        self.driver.save_screenshot(filename)
        with open(filename, "rb") as img:
            bot.send_photo(687061691, img, caption=f"{step_name} @ {timestamp}")


if __name__ == "__main__":
    create_selenium_processes()
