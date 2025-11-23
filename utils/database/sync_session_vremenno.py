import psycopg2
import time
import requests

from configuration_bot.settings import config


def get_db_connection():
    """
    Устанавливает соединение с базой данных PostgreSQL.
    Возвращает объект соединения.
    """
    return psycopg2.connect(dbname=config.PG_DB_INTERNAL,
                            user=config.PG_USER,
                            password=config.PG_PASSWORD.get_secret_value(),
                            host=config.PG_HOST.get_secret_value(),
                            port=config.PG_PORT
                            )


def check_proxy(proxy_name, proxy_id):
    """
    Проверяет доступность прокси. Если прокси работает, обновляется его статус в БД.
    Если прокси не работает, обновляется его статус и выполняется дополнительная очистка.
    """

    print("Проверяю на валидность прокси: ", proxy_name, proxy_id)

    # if ENVIRONMENT.value == 'PROD':
    #     return True
    proxies = {
        "http": proxy_name,
        "https": proxy_name,
    }
    try:
        # Пытаемся подключиться через прокси
        print(f"Проверка прокси: {proxy_name}")
        response = requests.get(
            "https://code-generator.wb.ru/generate/api/v1/code",
            proxies=proxies,
            timeout=30,
        )
        print(f"Ответ от прокси: {response.status_code}")

        return True

    except (requests.exceptions.ProxyError, requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError) as e:
        print(f"Ошибка при подключении через прокси: {e}")
        try:
            # Обновляем статус прокси в БД
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("UPDATE proxy SET is_healthy = false WHERE proxy_id = %s", (proxy_id,))
            cur.execute("SELECT phone_number FROM auth_user WHERE proxy_id = %s", (proxy_id,))
            phone = cur.fetchone()
            conn.commit()
        except Exception as db_error:
            print(f"Ошибка при работе с БД: {db_error}")
        finally:
            conn.close()
        return False

    except Exception as e:
        print(f"Неизвестная ошибка прокси {proxy_name}: {str(e)}")
        # Для других ошибок считаем, что прокси может работать
        return True


def get_valid_proxy(phone_number, chat_id):
    """
    Получает рабочий прокси из базы данных.
    Если прокси доступен, обновляет его статус и связывает с пользователем.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    while True:
        cur.execute('SELECT proxy_name, proxy_id FROM proxy WHERE is_busy = FALSE AND is_healthy = TRUE LIMIT 1')
        proxy_data = cur.fetchone()

        if not proxy_data:
            print("Свободные прокси закончились")
            cur.execute('SELECT proxy_name, proxy_id FROM proxy WHERE is_healthy = TRUE ORDER BY RANDOM() LIMIT 1')
            proxy_data = cur.fetchone()

        if proxy_data:
            proxy_name, proxy_id = proxy_data
            if check_proxy(proxy_name, proxy_id):
                cur.execute('UPDATE proxy SET is_busy = TRUE WHERE proxy_id = %s', (proxy_id,))
                cur.execute('''
                    UPDATE auth_user SET proxy_name = %s 
                    WHERE phone_number = %s AND chat_id = %s
                ''', (proxy_name, phone_number, chat_id))
                cur.execute('''
                    UPDATE auth_user SET proxy_id = %s 
                    WHERE phone_number = %s AND chat_id = %s
                ''', (proxy_id, phone_number, chat_id))

                conn.commit()
                conn.close()
                return proxy_name

        # Если подходящий прокси не найден или проверка не прошла, ждем и пробуем снова
        time.sleep(7)
    conn.close()
    return None