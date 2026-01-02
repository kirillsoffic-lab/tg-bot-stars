import asyncio
import logging
import sys
import os  # Модуль для работы с "сейфом" (переменными окружения)
from aiohttp import web  # Нужен для Render
from aiogram import Bot, Dispatcher, html
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

# --- НАСТРОЙКИ ---
# Мы говорим боту: "Ищи токен в настройках сервера Render"
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Ссылка на канал и контакт
REFERRAL_LINK = "https://t.me/nftMETRO"
PAYOUT_CONTACT = "@goatlyroony"

# Проверка на всякий случай, чтобы не забыть добавить токен
if not BOT_TOKEN:
    print("ОШИБКА: Токен не найден! Убедитесь, что добавили переменную BOT_TOKEN в настройках Render.")

# --- ЛОГИКА БОТА ---
dp = Dispatcher()

@dp.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    text = (
        f"Здравствуйте, {html.bold(message.from_user.full_name)}! 👋\n"
        f"Спасибо, что выбрали нас.\n\n"
        f"📋 {html.bold('Ваше задание:')}\n"
        f"Привести как можно больше людей по этой ссылке:\n"
        f"👉 {html.code(REFERRAL_LINK)}\n\n"
        f"💰 {html.bold('Оплата:')} 1 человек = 1 звезда TG ⭐\n"
        f"⚠️ {html.bold('ВАЖНО:')} Минимальное количество приглашенных — {html.bold('15 человек')}!\n\n"
        f"Как только ваши люди подпишутся и скинут вам скриншоты-подтверждения, "
        f"напишите команду /go, чтобы связаться с менеджером."
    )
    await message.answer(text)

@dp.message(Command("go"))
async def command_go_handler(message: Message) -> None:
    text = (
        f"Еще раз здравствуйте! 👋\n\n"
        f"Перед тем как писать нашему менеджеру, убедитесь, что:\n"
        f"✅ У вас собраны {html.bold('ВСЕ')} скриншоты приглашенных людей.\n"
        f"✅ Количество приглашенных не менее 15.\n\n"
        f"Если все готово, прошу писать сюда: {PAYOUT_CONTACT}\n\n"
        f"❗️ {html.bold('Убедительная просьба не спамить.')} "
        f"Как только человек освободится, он вам сразу ответит.\n"
        f"{html.italic('Удачи!')}"
    )
    await message.answer(text)

# --- ВЕБ-СЕРВЕР (Чтобы Render не убил бота) ---
async def health_check(request):
    return web.Response(text="Bot is running safely!")

async def start_server():
    app = web.Application()
    app.add_routes([web.get('/', health_check)])
    runner = web.AppRunner(app)
    await runner.setup()
    # Render сам скажет, какой порт использовать (обычно 10000)
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# --- ГЛАВНЫЙ ЗАПУСК ---
async def main() -> None:
    # Если токена нет, останавливаемся сразу
    if not BOT_TOKEN:
        return

    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    
    # Запускаем обманку для Render
    await start_server()
    
    # Запускаем бота
    print("Бот успешно запущен на сервере! 🚀")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен.")
