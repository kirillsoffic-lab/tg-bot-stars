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

# Админы и Менеджеры (Получаем списки ID)
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

# Таблица пользователей
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    referrer_id INTEGER,
    referrals_count INTEGER DEFAULT 0,
    username TEXT,
    is_banned INTEGER DEFAULT 0
)
""")

# Таблица промокодов
cursor.execute("""
CREATE TABLE IF NOT EXISTS promos (
    code TEXT PRIMARY KEY,
    amount INTEGER,
    uses_left INTEGER
)
""")

# Таблица использованных промокодов (чтобы не вводили дважды)
cursor.execute("""
CREATE TABLE IF NOT EXISTS used_promos (
    user_id INTEGER,
    code TEXT
)
""")
conn.commit()

# --- ФУНКЦИИ БД ---
def user_exists(user_id):
    with conn: return cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone() is not None

def add_user(user_id, referrer_id=None, username=None):
    if not user_exists(user_id):
        with conn:
            cursor.execute("INSERT INTO users (user_id, referrer_id, referrals_count, username, is_banned) VALUES (?, ?, 0, ?, 0)", (user_id, referrer_id, username))
            return True
    return False

def update_username(user_id, username):
    with conn: cursor.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))

def count_referral(referrer_id):
    with conn: cursor.execute("UPDATE users SET referrals_count = referrals_count + 1 WHERE user_id = ? AND is_banned = 0", (referrer_id,))

def get_user_data(user_id):
    with conn: return cursor.execute("SELECT referrals_count, is_banned, username FROM users WHERE user_id = ?", (user_id,)).fetchone()

def get_all_users():
    with conn: return cursor.execute("SELECT user_id FROM users").fetchall()

def get_user_by_username(username):
    # Убираем @ если есть
    username = username.replace("@", "")
    with conn: return cursor.execute("SELECT user_id, referrals_count, is_banned FROM users WHERE username LIKE ?", (username,)).fetchone()

# --- 3. ВЕБ-СЕРВЕР (Для Render) ---
async def health_check(request): return web.Response(text="Alive")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

async def on_startup(dp): await start_web_server()

# --- 4. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
async def check_sub(user_id):
    try:
        m = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return m.status in ['creator', 'administrator', 'member']
    except: return False

async def show_main_menu(message: types.Message):
    user_id = message.from_user.id
    data = get_user_data(user_id)
    if not data: return 
    
    count = data[0]
    me = await bot.get_me()
    ref_link = f"https://t.me/{me.username}?start={user_id}"
    
    msg_text = (
        f"🌟 **Личный кабинет**\n\n"
        f"🆔 Твой ID: `{user_id}`\n"
        f"🔗 **Ссылка:**\n`{ref_link}`\n\n"
        f"📊 Рефералов: **{count}**\n"
        f"💰 Баланс: **{count} ⭐**\n\n"
        f"🎁 Ввести код: `/code ВАШ_КОД`"
    )
    
    keyboard = InlineKeyboardMarkup()
    if count >= 15:
        keyboard.add(InlineKeyboardButton(text="💰 ЗАПРОСИТЬ ВЫВОД 💰", callback_data="withdraw_money"))
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_profile"))

    await message.answer(msg_text, reply_markup=keyboard, parse_mode="Markdown")

# --- 5. ЮЗЕРСКАЯ ЧАСТЬ ---

@dp.message_handler(commands=['start'])
async def start_command(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    
    user_data = get_user_data(user_id)
    if user_data and user_data[1] == 1: 
        await message.answer("⛔️ Вы заблокированы.")
        return

    # Обновляем юзернейм в базе, если он сменился
    if user_data: update_username(user_id, username)

    args = message.get_args()
    referrer_id = int(args) if args and args.isdigit() and int(args) != user_id else None

    if not await check_sub(user_id):
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton(text="👉 Подписаться", url=CHANNEL_LINK))
        keyboard.add(InlineKeyboardButton(text="✅ Я подписался", callback_data=f"check_sub_{referrer_id if referrer_id else 0}"))
        await message.answer(f"👋 Для начала подпишись на канал!", reply_markup=keyboard)
        return

    if not user_exists(user_id):
        add_user(user_id, referrer_id, username)
        if referrer_id:
            count_referral(referrer_id)
            try: await bot.send_message(referrer_id, f"🎉 Новый реферал: {message.from_user.first_name}!")
            except: pass

    await show_main_menu(message)

@dp.callback_query_handler(lambda c: c.data.startswith('check_sub_'))
async def process_sub_check(callback_query: types.CallbackQuery):
    ref_id = int(callback_query.data.split('_')[2])
    ref_id = ref_id if ref_id != 0 else None
    
    if await check_sub(callback_query.from_user.id):
        await callback_query.message.delete()
        if not user_exists(callback_query.from_user.id):
             add_user(callback_query.from_user.id, ref_id, callback_query.from_user.username)
             if ref_id: count_referral(ref_id)
        await show_main_menu(callback_query.message)
    else:
        await callback_query.answer("❌ Нет подписки!", show_alert=True)

@dp.callback_query_handler(text="refresh_profile")
async def refresh_profile(callback: types.CallbackQuery):
    try:
        await callback.message.delete()
        await show_main_menu(callback.message)
    except: pass

@dp.callback_query_handler(text="withdraw_money")
async def withdraw_request(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    data = get_user_data(user_id)
    if not data or data[1] == 1: return await callback.answer("⛔️ Бан!", show_alert=True)
    if data[0] < 15: return await callback.answer("❌ Нужно 15 звезд!", show_alert=True)

    if STAFF_IDS:
        for staff_id in STAFF_IDS:
            try:
                msg = f"🚨 **ЗАЯВКА**\n👤 @{callback.from_user.username} (`{user_id}`)\n💰 {data[0]} ⭐\n\n🔎 `/search @{callback.from_user.username}`"
                if str(staff_id) in ADMIN_IDS: msg += f"\n⛔️ `/ban {user_id}`\n✏️ `/set {user_id} 0`"
                await bot.send_message(staff_id, msg, parse_mode="Markdown")
            except: pass
        await callback.message.answer("✅ Заявка принята!")
        await callback.message.delete()

# --- НОВАЯ ФУНКЦИЯ: Активация промокода (Для всех) ---
@dp.message_handler(commands=['code'])
async def activate_promo(message: types.Message):
    user_id = message.from_user.id
    code = message.get_args().strip()
    if not code: return await message.answer("⚠️ Пиши: `/code НАЗВАНИЕ`")

    # Проверка, использовал ли уже
    if cursor.execute("SELECT code FROM used_promos WHERE user_id=? AND code=?", (user_id, code)).fetchone():
        return await message.answer("❌ Ты уже активировал этот код!")

    # Поиск кода
    promo = cursor.execute("SELECT amount, uses_left FROM promos WHERE code=?", (code,)).fetchone()
    if not promo: return await message.answer("❌ Такого кода нет.")
    if promo[1] <= 0: return await message.answer("❌ Код закончился.")

    # Начисление
    amount = promo[0]
    cursor.execute("UPDATE users SET referrals_count = referrals_count + ? WHERE user_id=?", (amount, user_id))
    cursor.execute("UPDATE promos SET uses_left = uses_left - 1 WHERE code=?", (code,))
    cursor.execute("INSERT INTO used_promos VALUES (?, ?)", (user_id, code))
    conn.commit()
    
    await message.answer(f"✅ **Успех!** Ты получил +{amount} ⭐")

# --- ФУНКЦИИ МЕНЕДЖЕРА ---

@dp.message_handler(commands=['search'])
async def search_user_by_nick(message: types.Message):
    if str(message.from_user.id) not in STAFF_IDS: return
    try:
        username = message.get_args().strip()
        user = get_user_by_username(username)
        if not user: return await message.answer("❌ Юзер не найден в базе.")
        
        await message.answer(
            f"🔎 **Поиск: {username}**\n"
            f"🆔 ID: `{user[0]}`\n"
            f"💰 Баланс: {user[1]}\n"
            f"⛔️ Бан: {'ДА' if user[2] else 'Нет'}\n\n"
            f"Команды:\n`/check {user[0]}`\n`/pm {user[0]} Текст`",
            parse_mode="Markdown"
        )
    except: await message.answer("⚠️ Пиши: `/search @username`")

@dp.message_handler(commands=['dm', 'msg'])
async def dm_by_username(message: types.Message):
    if str(message.from_user.id) not in STAFF_IDS: return
    try:
        args = message.get_args().split(maxsplit=1)
        username = args[0]
        text = args[1]
        
        user = get_user_by_username(username)
        if not user: return await message.answer("❌ Юзер не найден.")
        
        await bot.send_message(user[0], f"📨 **Поддержка:**\n{text}")
        await message.answer(f"✅ Отправлено пользователю @{username}")
    except: await message.answer("⚠️ Пиши: `/dm @username Текст`")

@dp.message_handler(commands=['check'])
async def check_user(message: types.Message):
    if str(message.from_user.id) not in STAFF_IDS: return
    try: 
        uid = int(message.get_args())
        d = get_user_data(uid)
        if d: await message.answer(f"👤 ID: {uid}\n💰: {d[0]}\n⛔️: {d[1]}")
    except: pass

@dp.message_handler(commands=['pm'])
async def pm_user_id(message: types.Message):
    if str(message.from_user.id) not in STAFF_IDS: return
    try:
        args = message.get_args().split(maxsplit=1)
        await bot.send_message(int(args[0]), f"📨 **Поддержка:**\n{args[1]}")
        await message.answer("✅")
    except: await message.answer("❌ Ошибка")

@dp.message_handler(commands=['top'])
async def top_users(message: types.Message):
    if str(message.from_user.id) not in STAFF_IDS: return 
    users = cursor.execute("SELECT username, referrals_count FROM users ORDER BY referrals_count DESC LIMIT 10").fetchall()
    text = "\n".join([f"{u[0]}: {u[1]}" for u in users])
    await message.answer(f"🏆 **ТОП-10:**\n{text}")

# --- ФУНКЦИИ АДМИНА ---

@dp.message_handler(commands=['add_promo'])
async def add_promo(message: types.Message):
    if str(message.from_user.id) not in ADMIN_IDS: return
    try:
        args = message.get_args().split()
        code = args[0]
        amount = int(args[1])
        uses = int(args[2])
        cursor.execute("INSERT OR REPLACE INTO promos VALUES (?, ?, ?)", (code, amount, uses))
        conn.commit()
        await message.answer(f"🎁 Промокод `{code}` на {amount} звезд ({uses} шт) создан!", parse_mode="Markdown")
    except: await message.answer("⚠️ Пиши: `/add_promo КОД СУММА КОЛ-ВО`")

@dp.message_handler(commands=['send'])
async def admin_broadcast(message: types.Message):
    if str(message.from_user.id) not in ADMIN_IDS: return
    
    users = get_all_users()
    count = 0
    
    # Если это ответ на фото
    if message.reply_to_message and message.reply_to_message.photo:
        photo_id = message.reply_to_message.photo[-1].file_id
        caption = message.get_args()
        await message.answer("📸 Рассылка фото началась...")
        for u in users:
            try: 
                await bot.send_photo(u[0], photo_id, caption=caption)
                count += 1
                await asyncio.sleep(0.05)
            except: pass
    
    # Если просто текст
    else:
        text = message.get_args()
        if not text: return await message.answer("⚠️ Пиши текст или ответь на фото.")
        await message.answer("🚀 Рассылка текста началась...")
        for u in users:
            try: 
                await bot.send_message(u[0], text)
                count += 1
                await asyncio.sleep(0.05)
            except: pass
            
    await message.answer(f"✅ Доставлено: {count}")

@dp.message_handler(commands=['set'])
async def set_bal(message: types.Message):
    if str(message.from_user.id) not in ADMIN_IDS: return
    try:
        uid, amt = map(int, message.get_args().split())
        cursor.execute("UPDATE users SET referrals_count = ? WHERE user_id = ?", (amt, uid))
        conn.commit()
        await message.answer("✅")
    except: pass

@dp.message_handler(commands=['ban'])
async def ban(message: types.Message):
    if str(message.from_user.id) not in ADMIN_IDS: return
    try:
        cursor.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (int(message.get_args()),))
        conn.commit()
        await message.answer("⛔️")
    except: pass

@dp.message_handler(commands=['admin'])
async def adm(message: types.Message):
    if str(message.from_user.id) not in ADMIN_IDS: return
    await message.answer("👑 Админка:\n`/add_promo`\n`/send` (текст или реплай на фото)\n`/set`\n`/ban`")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
