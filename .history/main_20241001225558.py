import logging
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from aiogram.dispatcher.filters import Text
from aiogram.contrib.fsm_storage.memory import MemoryStorage
import random
import sqlite3
from datetime import datetime, timedelta

API_TOKEN = 'YOUR_BOT_API_TOKEN'
ADMIN_ID = 1083294848  # Ваш Telegram ID для доступа к админке

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Создаем бота и диспетчер
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
dp.middleware.setup(LoggingMiddleware())

# Подключение к базе данных SQLite
conn = sqlite3.connect('bot_database.db')
cursor = conn.cursor()

# Создаем таблицы, если они не существуют
cursor.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, access_expires DATETIME)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS keys (key TEXT PRIMARY KEY, valid_until DATETIME)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS mailings (mailing_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, chats TEXT, messages TEXT, status TEXT, sent_messages INTEGER, start_time DATETIME)''')
conn.commit()

# ================== ФУНКЦИИ ДЛЯ АДМИНА ===================

@dp.message_handler(commands=['admin'])
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.reply("У вас нет доступа к этой команде.")
        return

    keyboard = InlineKeyboardMarkup()
    generate_key_btn = InlineKeyboardButton('Генерация ключа', callback_data='generate_key')
    keyboard.add(generate_key_btn)

    await message.answer("Добро пожаловать в админ-панель.", reply_markup=keyboard)

@dp.callback_query_handler(Text(startswith='generate_key'))
async def generate_key_panel(callback_query: types.CallbackQuery):
    await callback_query.message.answer("Введите срок действия ключа в днях:")

    # Сохраняем состояние, чтобы получить ответ
    @dp.message_handler()
    async def process_generate_key(message: types.Message):
        try:
            days = int(message.text)
            key = generate_key()
            valid_until = datetime.now() + timedelta(days=days)

            # Сохраняем ключ в базу данных
            cursor.execute('INSERT INTO keys (key, valid_until) VALUES (?, ?)', (key, valid_until))
            conn.commit()

            await message.answer(f"Сгенерирован ключ: **{key}**\nСрок действия: {days} дней.")
        except ValueError:
            await message.answer("Пожалуйста, введите правильное количество дней.")

# ================== ПОМОЩНИКИ ===================

def generate_key():
    """Генерация случайного одноразового ключа"""
    return ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890', k=8))

# ================== ФУНКЦИИ ДЛЯ ПОЛЬЗОВАТЕЛЯ ===================

@dp.message_handler(commands=['start'])
async def send_welcome(message: types.Message):
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    enter_code_btn = KeyboardButton('🗝️ Ввести код')
    keyboard.add(enter_code_btn)

    await message.answer("Добро пожаловать! Введите ключ доступа для активации.", reply_markup=keyboard)

@dp.message_handler(Text(equals="🗝️ Ввести код"))
async def ask_for_code(message: types.Message):
    await message.answer("Пожалуйста, введите ваш ключ:")

    @dp.message_handler()
    async def process_code(message: types.Message):
        key = message.text
        cursor.execute('SELECT valid_until FROM keys WHERE key = ?', (key,))
        result = cursor.fetchone()

        if result:
            valid_until = result[0]
            cursor.execute('DELETE FROM keys WHERE key = ?', (key,))
            conn.commit()

            cursor.execute('INSERT INTO users (user_id, access_expires) VALUES (?, ?)', (message.from_user.id, valid_until))
            conn.commit()

            await message.answer("Ключ принят. Доступ активирован до: " + valid_until)
        else:
            await message.answer("Ключ недействителен или уже использован.")

# ================== ФУНКЦИЯ ДЛЯ РАССЫЛКИ ===================

@dp.message_handler(commands=['new_mailing'])
async def new_mailing(message: types.Message):
    await message.answer("Пожалуйста, укажите список чатов через запятую.")

    @dp.message_handler()
    async def process_chats(message: types.Message):
        chats = message.text.split(',')

        await message.answer("Теперь введите сообщения для рассылки (одно на строку).")

        @dp.message_handler()
        async def process_messages(message: types.Message):
            messages = message.text.split('\n')

            await message.answer("Введите задержку между сообщениями в секундах:")

            @dp.message_handler()
            async def process_delay(message: types.Message):
                try:
                    delay = int(message.text)
                    mailing_id = cursor.execute('INSERT INTO mailings (user_id, chats, messages, status, sent_messages, start_time) VALUES (?, ?, ?, ?, ?, ?)',
                                                (message.from_user.id, ','.join(chats), '\n'.join(messages), 'active', 0, datetime.now())).lastrowid
                    conn.commit()

                    await message.answer(f"Рассылка #**{mailing_id}** создана и запущена!")

                    # Запуск рассылки
                    asyncio.create_task(send_messages(mailing_id, chats, messages, delay))

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
if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
