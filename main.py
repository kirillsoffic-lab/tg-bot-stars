import logging
import asyncio
import sqlite3
import os
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.utils import executor
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web

# --- 1. НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN")

# Админы и Менеджеры
admins_env = os.getenv("ADMIN_ID", "")
ADMIN_IDS = [x.strip() for x in admins_env.split(",")] if admins_env else []

managers_env = os.getenv("MANAGER_IDS", "")
MANAGER_IDS = [x.strip() for x in managers_env.split(",")] if managers_env else []

CHANNEL_ID = os.getenv("CHANNEL_ID")
CHANNEL_LINK = os.getenv("CHANNEL_LINK")

STAFF_IDS = ADMIN_IDS + MANAGER_IDS

# Логирование
logging.basicConfig(level=logging.INFO)

# Инициализация
bot = Bot(token=TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

# --- 2. БАЗА ДАННЫХ ---
conn = sqlite3.connect('database.db', check_same_thread=False)
cursor = conn.cursor()

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

# Функции БД
def user_exists(user_id):
    with conn:
        return cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone() is not None

def add_user(user_id, referrer_id=None, username=None):
    if not user_exists(user_id):
        with conn:
            cursor.execute("INSERT INTO users (user_id, referrer_id, referrals_count, username, is_banned) VALUES (?, ?, 0, ?, 0)", (user_id, referrer_id, username))
            return True
    return False

def count_referral(referrer_id):
    with conn:
        cursor.execute("UPDATE users SET referrals_count = referrals_count + 1 WHERE user_id = ? AND is_banned = 0", (referrer_id,))

def get_user_data(user_id):
    with conn:
        return cursor.execute("SELECT referrals_count, is_banned, username FROM users WHERE user_id = ?", (user_id,)).fetchone()

def get_all_users():
    with conn:
        return cursor.execute("SELECT user_id FROM users").fetchall()

# --- 3. ВЕБ-СЕРВЕР (Для Render) ---
async def health_check(request):
    return web.Response(text="Bot is alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info(f"✅ Web server started on port {port}")

async def on_startup(dp):
    await start_web_server()

# --- 4. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
async def check_sub(user_id):
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ['creator', 'administrator', 'member']
    except:
        return False

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

# --- 5. ОБРАБОТЧИКИ ---

@dp.message_handler(commands=['start'])
async def start_command(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    
    user_data = get_user_data(user_id)
    if user_data and user_data[1] == 1: 
        await message.answer("⛔️ **Ваш аккаунт заблокирован.**")
        return

    args = message.get_args()
    referrer_id = int(args) if args and args.isdigit() and int(args) != user_id else None

    if not await check_sub(user_id):
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton(text="👉 Подписаться", url=CHANNEL_LINK))
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
         await callback.answer("⛔️ БАН!", show_alert=True)
         return

    if data[0] < 15:
        await callback.answer("❌ Мало звезд!", show_alert=True)
        return

    if STAFF_IDS:
        for staff_id in STAFF_IDS:
            try:
                msg = f"🚨 **ВЫВОД**\n👤 @{callback.from_user.username} (`{user_id}`)\n💰 {data[0]} ⭐\n\n🔎 `/check {user_id}`"
                if str(staff_id) in ADMIN_IDS:
                    msg += f"\n⛔️ `/ban {user_id}`\n✏️ `/set {user_id} 0`"
                await bot.send_message(staff_id, msg, parse_mode="Markdown")
            except: pass
        await callback.message.answer("✅ Заявка отправлена!")
        await callback.message.delete()

# --- АДМИНКА ---

@dp.message_handler(commands=['check'])
async def check_user(message: types.Message):
    if str(message.from_user.id) not in STAFF_IDS: return
    try: target_id = int(message.get_args())
    except: return
    data = get_user_data(target_id)
    if data:
        await message.answer(f"👤 ID: {target_id}\n💰 Баланс: {data[0]}\n⛔️ Бан: {data[1]}")

@dp.message_handler(commands=['pm'])
async def pm_user(message: types.Message):
    if str(message.from_user.id) not in STAFF_IDS: return
    try:
        args = message.get_args().split(maxsplit=1)
        await bot.send_message(int(args[0]), f"📨 {args[1]}")
        await message.answer("✅ Отправлено")
    except: await message.answer("❌ Ошибка")

@dp.message_handler(commands=['top'])
async def top_users(message: types.Message):
    if str(message.from_user.id) not in STAFF_IDS: return 
    users = cursor.execute("SELECT username, referrals_count FROM users ORDER BY referrals_count DESC LIMIT 10").fetchall()
    text = "\n".join([f"{u[0]}: {u[1]}" for u in users])
    await message.answer(f"🏆 **ТОП-10:**\n{text}", parse_mode="Markdown")

@dp.message_handler(commands=['set'])
async def set_balance(message: types.Message):
    if str(message.from_user.id) not in ADMIN_IDS: return
    try:
        uid, amt = map(int, message.get_args().split())
        cursor.execute("UPDATE users SET referrals_count = ? WHERE user_id = ?", (amt, uid))
        conn.commit()
        await message.answer("✅")
    except: pass

@dp.message_handler(commands=['ban'])
async def ban_user(message: types.Message):
    if str(message.from_user.id) not in ADMIN_IDS: return
    try:
        cursor.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (int(message.get_args()),))
        conn.commit()
        await message.answer("⛔️")
    except: pass

@dp.message_handler(commands=['admin'])
async def admin_panel(message: types.Message):
    if str(message.from_user.id) not in ADMIN_IDS: return
    await message.answer(f"Всего людей: {len(get_all_users())}")

@dp.message_handler(commands=['send'])
async def admin_send(message: types.Message):
    if str(message.from_user.id) not in ADMIN_IDS: return
    users = get_all_users()
    for u in users:
        try: await bot.send_message(u[0], message.get_args())
        except: pass
    await message.answer("✅ Рассылка завершена")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
