import asyncio
import json
import random
from types import TracebackType
from typing import Any

from camoufox.async_api import AsyncCamoufox
from playwright.async_api import (
    Browser,
    BrowserContext,
    Cookie,
    Page,
    Playwright,
)
from playwright.async_api import Error as PlaywrightError
from antibot_system.config import PlaywrightConfig, orders_config
from antibot_system.antibot_logger import logger


class PlaywrightClient:
    """Camoufox browser client for Wildberries."""

    def __init__(self, config: PlaywrightConfig) -> None:
        self.config = config
        self.__is_initialized = False

        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.__playwright: Playwright | None = None
        self._camoufox_kwargs: dict[str, Any] = {}

    async def __aenter__(self):
        """Enter context manager.

        Initialize browser and authorize.

        Returns:
            PlaywrightClient: Self.


        """
        await self.init()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Exit context manager.

        Close browser and context.

        """
        await self.close()

    async def init(self) -> None:
        """Initialize browser.

        Raises:
            Error: If browser initialization fails.

        """
        try:
            camoufox_options = self._build_camoufox_options()
            self.__playwright = AsyncCamoufox(**camoufox_options, os=("windows"))

            self.browser = await self.__playwright.__aenter__()

            self.context = await self.browser.new_context()

            self.page = await self.context.new_page()

            self.page.set_default_timeout(self.config.default_timeout)
            self.page.set_default_navigation_timeout(
                self.config.default_navigation_timeout,
            )
            await self._authorize()

            self.__is_initialized = True
            logger.info("Camoufox client successfully initialized!")
        except PlaywrightError:
            logger.exception("Failed to initialize Camoufox client")
            await self.close()
            raise

    async def close(self) -> None:
        """Close all resources of Camoufox client."""
        try:
            if self.page:
                try:
                    await self.page.close()
                finally:
                    self.page = None

            if self.context:
                try:
                    await self.context.close()
                finally:
                    self.context = None

            if self.__playwright:
                try:
                    await self.__playwright.__aexit__(None, None, None)
                finally:
                    self.__playwright = None
                    self.browser = None
        finally:
            self.__is_initialized = False

    async def _authorize(self) -> None:
        """Authorize using token and cookies.

        Raises:
            Error: If authorization fails.

        """
        if not self.page:
            msg = "Page is not initialized"
            raise PlaywrightError(msg)

        try:
            await self.page.goto(orders_config.BASE_URL)
            await asyncio.sleep(2)
            await self._set_token()
            await self._set_cookies()
            await asyncio.sleep(2)
            await self.page.goto(orders_config.BASE_URL)

            if await self.page.get_by_text("Что-то не так...").is_visible():
                logger.warning("!!!!! Captcha detected, waiting 60 seconds !!!!!")
                await asyncio.sleep(60)

            await asyncio.sleep(5)

        except PlaywrightError:
            logger.exception("Authorization failed")
            raise

    async def _set_token(self) -> None:
        """Set token to localStorage.

        Raises:
            Error: If token is not set.

        """
        if not self.page:
            msg = "Page is not initialized"
            raise PlaywrightError(msg)

        if not self.config.token:
            msg = "Token is not set"
            raise PlaywrightError(msg)

        await self.page.evaluate(
            """
            ({ token, deviceId }) => {
                localStorage.setItem(
                    'wbx__tokenData',
                    JSON.stringify({ token }),
                );
                if (deviceId) {
                    localStorage.setItem('wbx__sessionID', deviceId);
                }
            }
            """,
            {
                "token": self.config.token,
                "deviceId": self.config.device_id or "",
            },
        )
        logger.info("Token set to localStorage")

    async def _set_cookies(self) -> None:
        """Set cookies before authorization.

        Raises:
            Error: If cookies are not set.

        """
        if not self.context:
            logger.warning("Context is not initialized, cookies skipped")
            return

        if not self.config.cookies:
            msg = "Cookies are not set"
            raise PlaywrightError(msg)

        cookie_data = (
            json.loads(self.config.cookies)
            if isinstance(self.config.cookies, str)
            else self.config.cookies
        )
        await self.context.add_cookies(cookie_data)
        logger.info("Set %d cookies", len(cookie_data))

    def _build_camoufox_options(self) -> dict[str, Any]:
        """Build Camoufox options.

        Returns:
            dict[str, Any]: Camoufox options.

        """
        options = self._camoufox_default_options.copy()
        options.update(self._camoufox_kwargs)
        options["headless"] = self.config.headless

        proxy = self._prepare_proxy()
        if proxy:
            options["proxy"] = proxy

        return options

    @property
    def _camoufox_default_options(self) -> dict[str, Any]:
        """Default Camoufox options with geoip enabled.

        Returns:
            dict[str, Any]: Default Camoufox options.

        """
        options: dict[str, Any] = {
            "geoip": False,
            "locale": self.config.default_locale,
            "humanize": True,
        }

        return options

    def _prepare_proxy(self) -> dict[str, str] | None:
        """Prepare proxy dictionary for Camoufox.

        Returns:
            dict[str, str] | None: Proxy dictionary or None.

        """
        if not self.config.proxy:
            return None

        if "@" in self.config.proxy:
            credentials, server = self.config.proxy.split("@", 1)
            username, password = credentials.split(":", 1)
        else:
            server = self.config.proxy
            username = password = ""

        proxy_payload: dict[str, str] = {"server": server}
        if username and password:
            proxy_payload.update({"username": username, "password": password})

        return proxy_payload

    async def human_delay(
        self,
        min_delay: float = 0.5,
        max_delay: float = 2.0,
    ) -> None:
        """Human-like delay.

        Args:
            min_delay (float): Minimum delay in seconds.
            max_delay (float): Maximum delay in seconds.


        """
        delay = random.uniform(min_delay, max_delay)  # noqa: S311
        await asyncio.sleep(delay)

    async def execute_script(self, script: str) -> dict | None:
        """Execute script.

        Args:
            script (str): Script to execute.

        Returns:
            dict: Result of the script execution.

        Raises:
            Error: If browser is not initialized.

        """
        if not self.page:
            msg = "Browser is not initialized"
            raise PlaywrightError(msg)

        return await self.page.evaluate(script)

    async def get_cookies(self) -> list[Cookie]:
        """Get cookies from the session.

        Returns:
            list[Cookie]: List of cookies.

        Raises:
            Error: If browser is not initialized.

        """
        if not self.page:
            msg = "Browser is not initialized"
            raise PlaywrightError(msg)

        return await self.page.context.cookies()

    @property
    def current_url(self) -> str:
        """Get current url.

        Returns:
            str: Current url.

        Raises:
            Error: If browser is not initialized.

        """
        if not self.page:
            msg = "Browser is not initialized"
            raise PlaywrightError(msg)

        return self.page.url