import logging
import asyncio
import sqlite3
import os
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.utils import executor
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- НАСТРОЙКИ (Берутся из Render) ---
TOKEN = os.getenv("BOT_TOKEN")

# Получаем список админов (разделенных запятой)
admins_env = os.getenv("ADMIN_ID", "")
ADMIN_IDS = [x.strip() for x in admins_env.split(",")] if admins_env else []

CHANNEL_ID = os.getenv("CHANNEL_ID")  # ID канала (с минусом)
CHANNEL_LINK = os.getenv("CHANNEL_LINK") # Ссылка на канал

# Включаем логирование
logging.basicConfig(level=logging.INFO)

# Инициализация бота и БД
bot = Bot(token=TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())
conn = sqlite3.connect('database.db')
cursor = conn.cursor()

# Создаем таблицу пользователей
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    referrer_id INTEGER,
    referrals_count INTEGER DEFAULT 0
)
""")
conn.commit()

# --- ФУНКЦИИ БАЗЫ ДАННЫХ ---
def user_exists(user_id):
    result = cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return bool(result)

def add_user(user_id, referrer_id=None):
    if not user_exists(user_id):
        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        if cursor.fetchone() is None:
            cursor.execute("INSERT INTO users (user_id, referrer_id, referrals_count) VALUES (?, ?, 0)", (user_id, referrer_id))
            conn.commit()
            return True
    return False

def count_referral(referrer_id):
    cursor.execute("UPDATE users SET referrals_count = referrals_count + 1 WHERE user_id = ?", (referrer_id,))
    conn.commit()

def get_referrals_count(user_id):
    result = cursor.execute("SELECT referrals_count FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return result[0] if result else 0

def get_all_users():
    return cursor.execute("SELECT user_id FROM users").fetchall()

# --- ПРОВЕРКА ПОДПИСКИ ---
async def check_sub(user_id):
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        if member.status in ['creator', 'administrator', 'member']:
            return True
    except Exception as e:
        logging.error(f"Ошибка проверки подписки: {e}")
        # Если бот не админ или ошибка, лучше вернуть True чтобы не блокировать всех
        return False 
    return False

# --- ОБРАБОТЧИКИ (HANDLERS) ---

@dp.message_handler(commands=['start'])
async def start_command(message: types.Message):
    user_id = message.from_user.id
    
    args = message.get_args()
    referrer_id = int(args) if args and args.isdigit() and int(args) != user_id else None

    # 1. Проверяем подписку
    is_subscribed = await check_sub(user_id)
    
    if not is_subscribed:
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton(text="👉 Подписаться на канал", url=CHANNEL_LINK))
        keyboard.add(InlineKeyboardButton(text="✅ Я подписался", callback_data=f"check_sub_{referrer_id if referrer_id else 0}"))
        
        await message.answer(
            f"👋 Привет, {message.from_user.first_name}!\n\n"
            f"⛔️ **Доступ закрыт!**\n"
            f"Чтобы начать зарабатывать Звезды, ты должен быть подписан на наш главный канал.",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return

    # 2. Регистрируем
    if not user_exists(user_id):
        add_user(user_id, referrer_id)
        if referrer_id and user_exists(referrer_id):
            count_referral(referrer_id)
            try:
                await bot.send_message(referrer_id, f"🎉 У тебя новый реферал: {message.from_user.first_name}!")
            except:
                pass

    # 3. Меню
    await show_main_menu(message)

async def show_main_menu(message: types.Message):
    user_id = message.from_user.id
    username = (await bot.get_me()).username
    ref_link = f"https://t.me/{username}?start={user_id}"
    
    msg_text = (
        f"🌟 **Roony Stars Bot**\n\n"
        f"Твоя задача: приглашать друзей и получать Звезды.\n\n"
        f"🔗 **Твоя личная ссылка:**\n`{ref_link}`\n\n"
        f"📊 Приглашено: **{get_referrals_count(user_id)} чел.**\n"
        f"💰 Оплата: 1 друг = 1 ⭐\n"
        f"💳 Минимальный вывод: 15 ⭐"
    )
    
    keyboard = InlineKeyboardMarkup()
    if get_referrals_count(user_id) >= 15:
        keyboard.add(InlineKeyboardButton(text="💰 ЗАПРОСИТЬ ВЫВОД 💰", callback_data="withdraw_money"))
    
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить статистику", callback_data="refresh_profile"))

    await message.answer(msg_text, reply_markup=keyboard, parse_mode="Markdown")

# --- CALLBACKS ---

@dp.callback_query_handler(lambda c: c.data.startswith('check_sub_'))
async def process_sub_check(callback_query: types.CallbackQuery):
    referrer_id = int(callback_query.data.split('_')[2])
    referrer_id = referrer_id if referrer_id != 0 else None
    
    if await check_sub(callback_query.from_user.id):
        await callback_query.message.delete()
        msg = callback_query.message
        msg.from_user = callback_query.from_user
        
        # Регистрируем
        if not user_exists(callback_query.from_user.id):
             add_user(callback_query.from_user.id, referrer_id)
             if referrer_id and user_exists(referrer_id):
                 count_referral(referrer_id)
                 try:
                    await bot.send_message(referrer_id, "🎉 У тебя новый реферал!")
                 except: pass
        
        await show_main_menu(msg)
    else:
        await callback_query.answer("❌ Ты еще не подписался!", show_alert=True)

@dp.callback_query_handler(text="refresh_profile")
async def refresh_profile(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    count = get_referrals_count(user_id)
    
    keyboard = InlineKeyboardMarkup()
    if count >= 15:
        keyboard.add(InlineKeyboardButton(text="💰 ЗАПРОСИТЬ ВЫВОД 💰", callback_data="withdraw_money"))
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить статистику", callback_data="refresh_profile"))
    
    ref_link = f"https://t.me/{(await bot.get_me()).username}?start={user_id}"
    new_text = (
        f"🌟 **Roony Stars Bot**\n\n"
        f"🔗 **Твоя личная ссылка:**\n`{ref_link}`\n\n"
        f"📊 Приглашено: **{count} чел.**\n"
        f"💰 Оплата: 1 друг = 1 ⭐\n"
        f"💳 Минимальный вывод: 15 ⭐"
    )
    
    try:
        await callback.message.edit_text(new_text, reply_markup=keyboard, parse_mode="Markdown")
    except:
        pass 
    await callback.answer()

@dp.callback_query_handler(text="withdraw_money")
async def withdraw_request(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    username = callback.from_user.username
    count = get_referrals_count(user_id)

    if count < 15:
        await callback.answer("❌ Недостаточно рефералов!", show_alert=True)
        return

    # Отправляем уведомление ВСЕМ АДМИНАМ
    if ADMIN_IDS:
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id, 
                    f"🚨 **ЗАЯВКА НА ВЫВОД** 🚨\n\n"
                    f"👤 Юзер: @{username} (ID: {user_id})\n"
                    f"👥 Рефералов: {count}\n"
                    f"💵 К оплате: {count} звезд\n\n"
                    f"👉 Проверь его и свяжись!"
                )
            except Exception as e:
                logging.error(f"Не удалось отправить админу {admin_id}: {e}")
        
        await callback.message.answer("✅ **Заявка отправлена менеджеру!**\nОжидайте проверки в течение 24 часов.")
        await callback.message.delete()
    else:
        await callback.answer("Ошибка настройки админов.", show_alert=True)

# --- АДМИНСКИЕ КОМАНДЫ ---

@dp.message_handler(commands=['admin'])
async def admin_stats(message: types.Message):
    # Проверка: есть ли ID пользователя в списке админов
    if str(message.from_user.id) not in ADMIN_IDS:
        return 

    users = get_all_users()
    count_users = len(users)
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE referrals_count > 0")
    active_users = cursor.fetchone()[0]

    await message.answer(
        f"👮‍♂️ **Админ-Панель**\n\n"
        f"👥 Всего пользователей: **{count_users}**\n"
        f"⚡️ Приводили друзей: **{active_users}**\n\n"
        f"Для рассылки пиши: `/send Текст сообщения`",
        parse_mode="Markdown"
    )

@dp.message_handler(commands=['send'])
async def admin_broadcast(message: types.Message):
    if str(message.from_user.id) not in ADMIN_IDS:
        return

    text = message.get_args()
    if not text:
        await message.answer("❌ Введи текст рассылки!\nПример: `/send Всем привет!`")
        return

    users = get_all_users()
    await message.answer(f"📢 Начинаю рассылку на {len(users)} человек...")
    
    count = 0
    for user in users:
        try:
            await bot.send_message(user[0], f"📢 **НОВОСТИ ROONY STARS**\n\n{text}", parse_mode="Markdown")
            count += 1
            await asyncio.sleep(0.1) 
        except:
            pass 
    
    await message.answer(f"✅ Рассылка завершена! Доставлено: {count}")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
