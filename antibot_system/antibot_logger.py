import logging

from logging import getLogger, StreamHandler

WHITE = "\033[97m"
GREEN = "\033[92m"
RESET = "\033[0m"
WHITE_MESSAGES = (
    "Token set to localStorage",
    "Set 4 cookies",
    "Camoufox client successfully initialized!",
)

class ColorFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)

        # Если сообщение нужно сделать белым
        if any(text in record.getMessage() for text in WHITE_MESSAGES):
            return f"{WHITE}{message}{RESET}"

        # INFO → зелёный
        if record.levelno == logging.INFO:
            return f"{GREEN}{message}{RESET}"

        return message

logger = getLogger("antibot")
logger.setLevel(logging.INFO)
logger.propagate = False

handler = StreamHandler()
handler.setFormatter(
    ColorFormatter("%(asctime)s - %(levelname)s - %(message)s")
)

logger.handlers.clear()
logger.addHandler(handler)