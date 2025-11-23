import os
import logging

from typing import ClassVar, Optional
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ColorFormatter(logging.Formatter):
    """
    Обозначение цветов для уровней логера.

    :params
        INFO: green
        WARNING: yellow
        ERROR: red
    """
    COLORS = {
        'INFO': '\033[92m',
        'WARNING': '\033[93m',
        'ERROR': '\033[91m',
        'RESET': '\033[0m',     # Сброс цвета
    }

    def format(self, record):
        color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
        message = super().format(record)
        return f"{color}{message}{self.COLORS['RESET']}"


def get_logger(
        name: Optional[str] = None,
        log_file: str = "authorization_bot_logs.log"
) -> logging.Logger:
    """
    Настройки логгера.
    :param name:
    :param log_file:
    :return: logger_name
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        # Запись в файл
        file_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        file_handler = logging.FileHandler(os.path.abspath(log_file), encoding="utf-8")
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

        # Консолька
        console_formatter = ColorFormatter("%(asctime)s - %(levelname)s - %(message)s")
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(console_formatter)
        logger.addHandler(stream_handler)

    return logger


class Settings(BaseSettings):
    """
    Валидация переменные окруженых
    """
    TG_TOKEN: SecretStr
    PG_DB_INTERNAL: str
    PG_USER: str
    PG_PASSWORD: SecretStr
    PG_HOST: SecretStr
    PG_PORT: str

    BASE_DIR: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    AUTH_PHOTO_PATH: str = os.path.join(BASE_DIR, "attachments", "media", "auth.png")
    GOOD_AUTH_PHOTO_PATH: str = os.path.join(BASE_DIR, "attachments", "media", "good_auth.png")
    ERROR_PHOTO_PATH: str = os.path.join(BASE_DIR, "attachments", "media", "error_auth.png")
    MAIN_MENU_PHOTO_PATH: str = os.path.join(BASE_DIR, "attachments", "media", "basic_menu.png")
    DATA_APPROVE: str = os.path.join(BASE_DIR, "attachments", "media", "data2.png")
    QUIT_ACCOUNT_PATH: str = os.path.join(BASE_DIR, "attachments", "media", "quit.png")
    NOTIF_PHOTO_PATH: str = os.path.join(BASE_DIR, "attachments", "media", "notifications", "notif.png")

    TEST_DEAL_WB: str = os.path.join(BASE_DIR, "attachments", "media", "deals", "test_wb2025.png")
    TEST_DEAL_OZON: str = os.path.join(BASE_DIR, "attachments", "media", "deals", "test_wb2025.png")
    TEST_DEAL_YMARKET: str = os.path.join(BASE_DIR, "attachments", "media", "deals", "test_wb2025.png")

    model_config: ClassVar[SettingsConfigDict] = {
        # "env_file": os.path.join(os.path.dirname(__file__), "..", ".env"),
        "env_file": ".env",
        "env_file_encoding": "utf-8"
    }


config = Settings()
# os.makedirs(config.RESULTS_DIR, exist_ok=True)
# os.makedirs(config.ATTACHMENTS_DIR, exist_ok=True)
