import logging
import asyncio
import sqlite3
import os
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.utils import executor
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web # Добавили библиотеку для "обмана" Render

# --- НАСТРОЙКИ (Берутся из Render) ---
TOKEN = os.getenv("BOT_TOKEN")

# Владелец (может ВСЁ: бан, баланс, рассылка)
admins_env = os.getenv("ADMIN_ID", "")
ADMIN_IDS = [x.strip() for x in admins_env.split(",")] if admins_env else []

# Менеджеры (могут только проверять и писать)
managers_env = os.getenv("MANAGER_IDS", "")
MANAGER_IDS = [x.strip() for x in managers_env.split(",")] if managers_env else []

CHANNEL_ID = os.getenv("CHANNEL_ID")
CHANNEL_LINK = os.getenv("CHANNEL_LINK")

# Общий список персонала
STAFF_IDS = ADMIN_IDS + MANAGER_IDS

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())
conn = sqlite3.connect('database.db')
cursor = conn.cursor()

# Создаем таблицу
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    referrer_id INTEGER,
    referrals_count INTEGER DEFAULT 0,
    username TEXT,
    is_banned INTEGER DEFAULT 0
)
""")
conn.commit()

# --- ФУНКЦИИ БАЗЫ ---
def user_exists(user_id):
    result = cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return bool(result)

def add_user(user_id, referrer_id=None, username=None):
    if not user_exists(user_id):
        cursor.execute("INSERT INTO users (user_id, referrer_id, referrals_count, username, is_banned) VALUES (?, ?, 0, ?, 0)", (user_id, referrer_id, username))
        conn.commit()
        return True
    return False

def count_referral(referrer_id):
    cursor.execute("UPDATE users SET referrals_count = referrals_count + 1 WHERE user_id = ? AND is_banned = 0", (referrer_id,))
    conn.commit()

def get_user_data(user_id):
    return cursor.execute("SELECT referrals_count, is_banned, username FROM users WHERE user_id = ?", (user_id,)).fetchone()

def get_all_users():
    return cursor.execute("SELECT user_id FROM users").fetchall()

async def check_sub(user_id):
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        if member.status in ['creator', 'administrator', 'member']:
            return True
    except:
        return False 
    return False

# --- "ОБМАНКА" ДЛЯ RENDER (Keep Alive) ---
async def health_check(request):
    return web.Response(text="Bot is alive!")

async def start_web_server():
    # Создаем мини-сайт
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    # Render сам дает порт через переменную PORT
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info(f"Web server started on port {port}")

# Запускаем веб-сервер вместе с ботом
async def on_startup(dp):
    await start_web_server()
    # Здесь можно добавить уведомление админу о запуске
    # await bot.send_message(ADMIN_IDS[0], "Бот перезапущен!")

# --- ОБРАБОТЧИКИ ---

@dp.message_handler(commands=['start'])
async def start_command(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    
    user_data = get_user_data(user_id)
    if user_data and user_data[1] == 1: 
        await message.answer("⛔️ **Ваш аккаунт заблокирован администрацией.**")
        return

    args = message.get_args()
    referrer_id = int(args) if args and args.isdigit() and int(args) != user_id else None

    if not await check_sub(user_id):
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton(text="👉 Подписаться на канал", url=CHANNEL_LINK))
        keyboard.add(InlineKeyboardButton(text="✅ Я подписался", callback_data=f"check_sub_{referrer_id if referrer_id else 0}"))
        await message.answer(f"👋 Привет! Подпишись на канал, чтобы начать.", reply_markup=keyboard)
        return

    if not user_exists(user_id):
        add_user(user_id, referrer_id, username)
        if referrer_id:
            count_referral(referrer_id)
            try: await bot.send_message(referrer_id, f"🎉 У тебя новый реферал: {message.from_user.first_name}!")
            except: pass

    await show_main_menu(message)

async def show_main_menu(message: types.Message):
    user_id = message.from_user.id
    data = get_user_data(user_id)
    if not data: return 
    
    count = data[0]
    me = await bot.get_me()
    ref_link = f"https://t.me/{me.username}?start={user_id}"
    
    msg_text = (
        f"🌟 **Roony Stars**\n\n"
        f"🔗 **Твоя ссылка:**\n`{ref_link}`\n\n"
        f"📊 Приглашено: **{count} чел.**\n"
        f"💰 Оплата: 1 друг = 1 ⭐\n"
        f"💳 Вывод от: 15 ⭐"
    )
    
    keyboard = InlineKeyboardMarkup()
    if count >= 15:
        keyboard.add(InlineKeyboardButton(text="💰 ЗАПРОСИТЬ ВЫВОД 💰", callback_data="withdraw_money"))
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_profile"))

    await message.answer(msg_text, reply_markup=keyboard, parse_mode="Markdown")

@dp.callback_query_handler(lambda c: c.data.startswith('check_sub_'))
async def process_sub_check(callback_query: types.CallbackQuery):
    referrer_id = int(callback_query.data.split('_')[2])
    referrer_id = referrer_id if referrer_id != 0 else None
    
    if await check_sub(callback_query.from_user.id):
        await callback_query.message.delete()
        msg = callback_query.message
        msg.from_user = callback_query.from_user
        if not user_exists(callback_query.from_user.id):
             add_user(callback_query.from_user.id, referrer_id, callback_query.from_user.username)
             if referrer_id: count_referral(referrer_id)
        await show_main_menu(msg)
    else:
        await callback_query.answer("❌ Сначала подписка!", show_alert=True)

@dp.callback_query_handler(text="refresh_profile")
async def refresh_profile(callback: types.CallbackQuery):
    try:
        await show_main_menu(callback.message)
        await callback.message.delete()
    except: pass

@dp.callback_query_handler(text="withdraw_money")
async def withdraw_request(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    data = get_user_data(user_id)
    
    if not data or data[1] == 1: 
         await callback.answer("⛔️ Вы заблокированы!", show_alert=True)
         return

    count = data[0]
    if count < 15:
        await callback.answer("❌ Мало рефералов!", show_alert=True)
        return

    if STAFF_IDS:
        for staff_id in STAFF_IDS:
            try:
                if str(staff_id) in ADMIN_IDS:
                    actions = (f"🔎 Чек: `/check {user_id}`\n"
                               f"💬 ЛС: `/pm {user_id} Текст`\n"
                               f"⛔️ БАН: `/ban {user_id}`\n"
                               f"✏️ СЕТ: `/set {user_id} 0`")
                else:
                    actions = (f"🔎 Чек: `/check {user_id}`\n"
                               f"💬 ЛС: `/pm {user_id} Текст`\n"
                               f"⚠️ Если накрутка — пиши Админу!")

                await bot.send_message(
                    staff_id, 
                    f"🚨 **ЗАЯВКА НА ВЫВОД**\n"
                    f"👤 Юзер: @{callback.from_user.username} (ID: `{user_id}`)\n"
                    f"💰 Сумма: {count} звезд\n\n"
                    f"{actions}",
                    parse_mode="Markdown"
                )
            except: pass
        await callback.message.answer("✅ **Заявка отправлена!** Ожидайте.")
        await callback.message.delete()

@dp.message_handler(commands=['check'])
async def check_user(message: types.Message):
    if str(message.from_user.id) not in STAFF_IDS: return
    try: target_id = int(message.get_args())
    except: 
        await message.answer("⚠️ Пиши: `/check ID`")
        return
    data = get_user_data(target_id)
    if not data:
        await message.answer("❌ Нет такого юзера.")
        return
    refs = cursor.execute("SELECT user_id, username FROM users WHERE referrer_id = ? ORDER BY user_id DESC LIMIT 5", (target_id,)).fetchall()
    ref_text = "\n".join([f"- {r[1] if r[1] else 'Без ника'} (ID {r[0]})" for r in refs])
    await message.answer(
        f"🕵️‍♂️ **Досье на {target_id}**\n"
        f"Баланс: {data[0]}\n"
        f"Бан: {'ДА' if data[1] else 'НЕТ'}\n\n"
        f"👥 **Последние 5:**\n{ref_text if ref_text else 'Пусто'}"
    )

@dp.message_handler(commands=['pm'])
async def pm_user(message: types.Message):
    if str(message.from_user.id) not in STAFF_IDS: return
    try:
        args = message.get_args().split(maxsplit=1)
        target_id = int(args[0])
        text = args[1]
    except:
        await message.answer("⚠️ Пиши: `/pm ID Текст`")
        return
    try:
        await bot.send_message(target_id, f"📨 **Сообщение от поддержки:**\n\n{text}")
        await message.answer(f"✅ Сообщение отправлено.")
    except:
        await message.answer("❌ Юзер заблокировал бота.")

@dp.message_handler(commands=['top'])
async def top_users(message: types.Message):
    if str(message.from_user.id) not in STAFF_IDS: return 
    top_players = cursor.execute("SELECT user_id, referrals_count, username FROM users ORDER BY referrals_count DESC LIMIT 10").fetchall()
    top_text = "🏆 **ТОП-10 ЛИДЕРОВ:**\n"
    for index, player in enumerate(top_players):
        uname = player[2] if player[2] else f"ID {player[0]}"
        top_text += f"{index+1}. @{uname} — **{player[1]}**\n"
    await message.answer(top_text, parse_mode="Markdown")

@dp.message_handler(commands=['set'])
async def set_balance(message: types.Message):
    if str(message.from_user.id) not in ADMIN_IDS: return
    try:
        args = message.get_args().split()
        target_id = int(args[0])
        amount = int(args[1])
    except:
        await message.answer("⚠️ `/set ID Сумма`")
        return
    cursor.execute("UPDATE users SET referrals_count = ? WHERE user_id = ?", (amount, target_id))
    conn.commit()
    await message.answer(f"✅ Баланс {target_id} = {amount}")

@dp.message_handler(commands=['ban'])
async def ban_user(message: types.Message):
    if str(message.from_user.id) not in ADMIN_IDS: return
    try: target_id = int(message.get_args())
    except: return
    cursor.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (target_id,))
    conn.commit()
    await message.answer(f"⛔️ Юзер {target_id} ЗАБАНЕН!")

@dp.message_handler(commands=['admin'])
async def admin_panel(message: types.Message):
    if str(message.from_user.id) not in ADMIN_IDS: return
    users = get_all_users()
    await message.answer(f"👑 **ВЛАДЕЛЕЦ**\nПользователей: {len(users)}\n\n`/send Текст` - Рассылка\n`/set` - Менять баланс\n`/ban` - Банить")

@dp.message_handler(commands=['send'])
async def admin_send(message: types.Message):
    if str(message.from_user.id) not in ADMIN_IDS: return
    text = message.get_args()
    if not text: return
    users = get_all_users()
    await message.answer(f"🚀 Рассылка...")
    for u in users:
        try: await bot.send_message(u[0], text)
        except: pass
    await message.answer("✅ Готово.")

if __name__ == '__main__':
    # ВАЖНО: Добавили on_startup=on_startup, чтобы запустить "сайт-обманку"
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
