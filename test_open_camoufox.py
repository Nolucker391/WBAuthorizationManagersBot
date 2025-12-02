import asyncio
import logging

from camoufox.async_api import AsyncCamoufox
from browserforge.fingerprints import Screen

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)
logger = logging.getLogger("auth_camoufox")

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


async def check_authentication(page):
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

if __name__ == "__main__":
    async def main():
        logger.info("Инициализация браузера...")
        async with AsyncCamoufox(
            screen=constrains,
            headless=False,
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

            if await check_authentication(page):
                logger.info("Пользователь уже авторизован. Пропускаю авторизацию...")
                return

            # Ожидаем, пока элемент ячейки появится
            phone_selector = '#spaAuthForm > div > div > div.inputWrapper--MGUCa > input'
            await page.wait_for_selector(phone_selector, timeout=30000)  # тайм-аут до 30 секунд, если не нашел сразу

            phone_el = await page.query_selector(phone_selector)

            # Проверка найден ли селектор
            if phone_el:
                await phone_el.fill("+79815582322")
                await phone_el.press("Tab")
                logger.info("Селектор найден, Номер телефона успешно введен.")
            else:
                logger.warning("Селектор не найден, номер не введен.")

            # Нажимаем кнопку Получить код через JS Path
            code_button_request = 'document.querySelector("#requestCode").click()' # Кнопка Запросить код

            try:
                await page.evaluate(code_button_request)
                logger.info("Нажал кнопку «Получить код»")
            except Exception as e:
                logger.warning(f"Не удалось нажать на кнопку «Получить код»: {e}")

            # Вводим код-получения
            code_input_selector = '#spaAuthForm > div > div.charInputBlock--B8MB2 > div > div:nth-child(1) > input'
            await page.wait_for_selector(code_input_selector, timeout=30000)

            code_el = await page.query_selector(code_input_selector)

            if code_el:
                await code_el.fill("655655")
                await code_el.press("Tab")
                logger.info("Селектор найден, «Код получения» успешно введен.")
            else:
                logger.warning("Селектор не найден, «Код получения» не введен.")

            await asyncio.sleep(5)
            if await check_authentication(page):
                logger.info("Пользователь успешно авторизован после ввода кода.")
                return

            # Ищем селекторы ошибки кода или запрос нового кода
            error_code_input_selector = "#spaAuthForm > div > div.charInputBlock--B8MB2 > p" # Неверный код/Запросите новый код
            timer_retry_new_req_selector = 'document.querySelector("#spaAuthForm > div > p.loginCountdown--t_mMs") === null' # таймер ожидания для запроса нового кода

            # Ставим условие, если данный селектор получился значит,
            # нужно ждать таймер для запроса нового кода и пробовать ввести новый код

            error_el = await page.wait_for_selector(error_code_input_selector, timeout=60000)  # Ожидаем появления ошибки

            if error_el:
                logger.warning("Код неверный. Ожидаем таймер для запроса нового кода...")

                # Ждем, пока исчезнет таймер
                await page.wait_for_function(
                    timer_retry_new_req_selector,
                    timeout=180000
                )
                logger.info("Таймер для запроса нового кода исчез.")

                try:
                    await page.evaluate(code_button_request)
                    logger.info("Запрашиваем новый код.")
                except Exception as e:
                    logger.warning(f"Не удалось найти кнопку запроса нового кода: {e}")

                await page.wait_for_selector(code_input_selector, timeout=30000)
                code_el = await page.query_selector(code_input_selector)

                if code_el:
                    await code_el.fill("123456")  # Новый код
                    await code_el.press("Tab")
                    logger.info("Новый код успешно введен.")
                else:
                    logger.warning("Селектор для ввода нового кода не найден.")

            await asyncio.sleep(5)
            if await check_authentication(page):
                logger.info("Пользователь успешно авторизован.")
                return

            # Ожидаем 1 час, чтобы посмотреть результат
            while True:
                await asyncio.sleep(3600)  # Даем время для взаимодействия

    asyncio.run(main())
