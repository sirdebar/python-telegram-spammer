import logging
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, Text
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from datetime import datetime, timedelta
import random
import sqlite3

API_TOKEN = '8024335015:AAEeQ6cZSHJdvSXhMzyubyth1UHOv2mFtpM'
ADMIN_ID = 1083294848  # Ваш Telegram ID для доступа к админке

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Создаем бота и диспетчер
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Подключение к базе данных SQLite
conn = sqlite3.connect('bot_database.db')
cursor = conn.cursor()

# Создаем таблицы, если они не существуют
cursor.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, access_expires DATETIME)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS keys (key TEXT PRIMARY KEY, valid_until DATETIME)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS mailings (mailing_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, chats TEXT, messages TEXT, status TEXT, sent_messages INTEGER, start_time DATETIME)''')
conn.commit()

# ================== СОСТОЯНИЯ ===================

class AdminStates(StatesGroup):
    waiting_for_days = State()

class UserStates(StatesGroup):
    waiting_for_key = State()
    waiting_for_chats = State()
    waiting_for_messages = State()
    waiting_for_delay = State()

# ================== ФУНКЦИИ ДЛЯ АДМИНА ===================

@dp.message(Command(commands=["admin"]))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("У вас нет доступа к этой команде.")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Генерация ключа", callback_data="generate_key")]
    ])

    await message.answer("Добро пожаловать в админ-панель.", reply_markup=keyboard)

@dp.callback_query(Text(text="generate_key"))
async def generate_key_panel(callback_query):
    await callback_query.message.answer("Введите срок действия ключа в днях.")
    await dp.fsm_context.set_state(AdminStates.waiting_for_days)

@dp.message(AdminStates.waiting_for_days)
async def process_generate_key(message: Message, state: FSMContext):
    try:
        days = int(message.text)
        key = generate_key()
        valid_until = datetime.now() + timedelta(days=days)

        # Сохраняем ключ в базу данных
        cursor.execute('INSERT INTO keys (key, valid_until) VALUES (?, ?)', (key, valid_until))
        conn.commit()

        await message.answer(f"Сгенерирован ключ: **{key}**\nСрок действия: {days} дней.")
        await state.clear()
    except ValueError:
        await message.answer("Пожалуйста, введите правильное количество дней.")

# ================== ПОМОЩНИКИ ===================

def generate_key():
    """Генерация случайного одноразового ключа"""
    return ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890', k=8))

# ================== ФУНКЦИИ ДЛЯ ПОЛЬЗОВАТЕЛЯ ===================

@dp.message(Command(commands=["start"]))
async def send_welcome(message: Message):
    builder = ReplyKeyboardBuilder()
    builder.button(text="🗝️ Ввести код")
    builder.adjust(1)

    await message.answer("Добро пожаловать! Введите ключ доступа для активации.", reply_markup=builder.as_markup())

@dp.message(Text(text="🗝️ Ввести код"))
async def ask_for_code(message: Message, state: FSMContext):
    await message.answer("Пожалуйста, введите ваш ключ.")
    await state.set_state(UserStates.waiting_for_key)

@dp.message(UserStates.waiting_for_key)
async def process_code(message: Message, state: FSMContext):
    key = message.text
    cursor.execute('SELECT valid_until FROM keys WHERE key = ?', (key,))
    result = cursor.fetchone()

    if result:
        valid_until = result[0]
        cursor.execute('DELETE FROM keys WHERE key = ?', (key,))
        conn.commit()

        cursor.execute('INSERT INTO users (user_id, access_expires) VALUES (?, ?)', (message.from_user.id, valid_until))
        conn.commit()

        await message.answer(f"Ключ принят. Доступ активирован до: {valid_until}")
        await state.clear()
    else:
        await message.answer("Ключ недействителен или уже использован.")
        await state.clear()

# ================== ФУНКЦИЯ ДЛЯ РАССЫЛКИ ===================

@dp.message(Command(commands=["new_mailing"]))
async def new_mailing(message: Message, state: FSMContext):
    await message.answer("Пожалуйста, укажите список чатов через запятую.")
    await state.set_state(UserStates.waiting_for_chats)

@dp.message(UserStates.waiting_for_chats)
async def process_chats(message: Message, state: FSMContext):
    chats = message.text.split(',')
    await state.update_data(chats=chats)

    await message.answer("Теперь введите сообщения для рассылки (одно на строку).")
    await state.set_state(UserStates.waiting_for_messages)

@dp.message(UserStates.waiting_for_messages)
async def process_messages(message: Message, state: FSMContext):
    messages = message.text.split('\n')
    await state.update_data(messages=messages)

    await message.answer("Введите задержку между сообщениями в секундах.")
    await state.set_state(UserStates.waiting_for_delay)

@dp.message(UserStates.waiting_for_delay)
async def process_delay(message: Message, state: FSMContext):
    try:
        delay = int(message.text)
        user_data = await state.get_data()
        chats = user_data['chats']
        messages = user_data['messages']

        mailing_id = cursor.execute(
            'INSERT INTO mailings (user_id, chats, messages, status, sent_messages, start_time) VALUES (?, ?, ?, ?, ?, ?)',
            (message.from_user.id, ','.join(chats), '\n'.join(messages), 'active', 0, datetime.now())
        ).lastrowid
        conn.commit()

        await message.answer(f"Рассылка #**{mailing_id}** создана и запущена!")

        # Запуск рассылки
        asyncio.create_task(send_messages(mailing_id, chats, messages, delay))
        await state.clear()

    except ValueError:
        await message.answer("Пожалуйста, введите правильное число для задержки.")

async def send_messages(mailing_id, chats, messages, delay):
    cursor.execute('UPDATE mailings SET status = ? WHERE mailing_id = ?', ('active', mailing_id))
    conn.commit()

    sent_count = 0

    for chat_id in chats:
        for message in random.sample(messages, len(messages)):  # Случайная выборка сообщений
            await bot.send_message(chat_id, message)
            sent_count += 1
            cursor.execute('UPDATE mailings SET sent_messages = ? WHERE mailing_id = ?', (sent_count, mailing_id))
            conn.commit()

            await asyncio.sleep(delay)

    # Завершение рассылки
    cursor.execute('UPDATE mailings SET status = ? WHERE mailing_id = ?', ('completed', mailing_id))
    conn.commit()

# ================== ЗАПУСК БОТА ===================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
