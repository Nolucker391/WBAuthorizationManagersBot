from typing import Literal

from pydantic import BaseModel


class AuthorizationConfig(BaseModel):
    """Authorization config."""

    token: str
    phone: str
    proxy: str | None = None
    device_id: str | None = None
    useragent: str | None = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    cookies: str | dict[str, str] | list[dict[str, str]] | None = None

class OrdersConfig(BaseModel):
    """Wildberries config."""

    ACTIVE_ORDERS_URL: str = (
        "https://www.wildberries.ru/webapi/v2/lk/myorders/delivery/active"
    )
    DELIVERY_ORDERS_URL: str = "https://wbxoofex.wildberries.ru/api/v2/orders"
    ARCHIVE_ORDERS_URL: str = (
        "https://www.wildberries.ru/webapi/lk/myorders/archive/get"
    )
    BASE_URL: str = "https://www.wildberries.ru"

    LK_ORDERS_URL: str = "https://www.wildberries.ru/lk/myorders"

    PROXY_BANNED_STATUS: int = 498
    CAPTCHA_FLAGS: tuple[str, ...] = (
        "captcha",
        "<!doctype html>",
        "reCAPTCHA",
        "hcaptcha",
        "для работы с сайтом",
        "javascript",
    )


orders_config = OrdersConfig()

class PlaywrightConfig(AuthorizationConfig):
    """Playwright client config."""

    token_key: str = "wbx__tokenData"
    device_id_key: str = "wbx__sessionID"
    headless: bool = True
    browser_type: Literal["chromium", "firefox", "webkit"] = "chromium"
    site_token_set_base_url: str = "https://www.wildberries.ru/"
    default_timeout: int = 30000
    default_navigation_timeout: int = 30000
    viewport: dict[str, int] | None = {"width": 1920, "height": 1080}
    is_mobile: bool = False
    timezone_id: str = "Europe/Moscow"
    default_locale: str = "ru-RU"

    @property
    def browser_args(self) -> list[str]:
        """Browser args."""
        args = [
            "--allow-running-insecure-content",
            "--no-sandbox",
        ]
        return args
