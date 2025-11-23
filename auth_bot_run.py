import asyncio

from aiogram import Dispatcher, Bot
from aiogram.methods import DeleteWebhook
from aiogram.types import BotCommand
from aiogram.fsm.storage.memory import MemoryStorage

from configuration_bot.settings import config
from handlers.routes import router
from configuration_bot.settings import get_logger

logger = get_logger()


async def set_commands(bot: Bot):
    commands = [
        BotCommand(command="/start", description="🚀 Запустить бота")
    ]
    await bot.set_my_commands(commands)


def on_startup():
    logger.info('Бот запущен')


def shutdown_func():
    logger.info("Бот выключен")


async def main():
    bot = Bot(config.TG_TOKEN.get_secret_value())
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_routers(
        router
    )
    dp.startup.register(on_startup)
    dp.shutdown.register(shutdown_func)

    await set_commands(bot)
    await bot(DeleteWebhook(drop_pending_updates=True))
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
