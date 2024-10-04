import logging
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from datetime import datetime, timedelta
import random
import sqlite3
from telethon import TelegramClient

API_TOKEN = '8024335015:AAEeQ6cZSHJdvSXhMzyubyth1UHOv2mFtpM'
ADMIN_ID = 1083294848
API_ID = '23422308'
API_HASH = '1da8d8d190e8fb59531b28258d1ed64c'

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Создаем бота и диспетчер
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Подключение к базе данных SQLite
conn = sqlite3.connect('bot_database.db')
cursor = conn.cursor()

# Создаем таблицы, если они не существуют
cursor.execute('''CREATE TABLE IF NOT EXISTS accounts (account_id INTEGER PRIMARY KEY, phone TEXT, session TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, access_expires DATETIME)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS keys (key TEXT PRIMARY KEY, valid_until DATETIME)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS mailings (mailing_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, account_id INTEGER, chats TEXT, messages TEXT, status TEXT, sent_messages INTEGER, start_time DATETIME)''')
conn.commit()

# ================== СОСТОЯНИЯ ===================

class AccountStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code = State()

class UserStates(StatesGroup):
    waiting_for_key = State()
    waiting_for_chats = State()
    waiting_for_messages = State()
    waiting_for_delay = State()

class MailingControlStates(StatesGroup):
    managing_mailing = State()

# ================== МЕНЮ ===================

def get_admin_menu():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='👨‍💼 Войти в админку')],
            [KeyboardButton(text='➕ Добавить аккаунт')],
            [KeyboardButton(text='📤 Новая рассылка')],
            [KeyboardButton(text='📋 Профиль')]
        ],
        resize_keyboard=True
    )
    return keyboard

def get_user_menu():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='📋 Профиль')],
            [KeyboardButton(text='📤 Новая рассылка')]
        ],
        resize_keyboard=True
    )
    return keyboard

def get_mailing_control_keyboard(mailing_id):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏸ Остановить", callback_data=f"pause_mailing_{mailing_id}")],
        [InlineKeyboardButton(text="⛔ Прервать", callback_data=f"cancel_mailing_{mailing_id}")]
    ])
    return keyboard

# ================== ФУНКЦИИ ДЛЯ АДМИНА ===================

@dp.message(Command(commands=["start"]))
async def start_bot(message: Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("Привет, <b>админ</b>!", reply_markup=get_admin_menu(), parse_mode="HTML")
    else:
        await message.answer("Добро пожаловать! Введите ключ доступа для активации.", parse_mode="HTML")

@dp.message(F.text == "👨‍💼 Войти в админку")
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("У вас нет доступа к этой команде.", parse_mode="HTML")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Генерация ключа", callback_data="generate_key")]
    ])
    await message.answer("<b>Админ-панель</b>:", reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data == "generate_key")
async def generate_key_panel(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.message.answer("Введите срок действия ключа в днях.", parse_mode="HTML")
    await state.set_state(AdminStates.waiting_for_days)

@dp.message(AdminStates.waiting_for_days)
async def process_generate_key(message: Message, state: FSMContext):
    try:
        days = int(message.text)
        key = generate_key()
        valid_until = (datetime.now() + timedelta(days=days)).isoformat()  # Сохраняем как строку

        cursor.execute('INSERT INTO keys (key, valid_until) VALUES (?, ?)', (key, valid_until))
        conn.commit()

        await message.answer(f"Сгенерирован ключ: <b>{key}</b>\nСрок действия: {days} дней.", parse_mode="HTML")
        await state.clear()
    except ValueError:
        await message.answer("Пожалуйста, введите правильное количество дней.", parse_mode="HTML")

# ================== ФУНКЦИИ ДЛЯ РАБОТЫ С АККАУНТАМИ ===================

@dp.message(F.text == "➕ Добавить аккаунт")
async def add_account(message: Message, state: FSMContext):
    if message.from_user.id == ADMIN_ID:
        await message.answer("Введите номер телефона Telegram для добавления аккаунта.")
        await state.set_state(AccountStates.waiting_for_phone)

@dp.message(AccountStates.waiting_for_phone)
async def process_phone(message: Message, state: FSMContext):
    phone = message.text
    client = TelegramClient(f'session_{phone}', API_ID, API_HASH)
    
    await client.connect()
    if not await client.is_user_authorized():
        await client.send_code_request(phone)
        await state.update_data(phone=phone, client=client)
        await message.answer("Введите код из Telegram.")
        await state.set_state(AccountStates.waiting_for_code)

@dp.message(AccountStates.waiting_for_code)
async def process_code(message: Message, state: FSMContext):
    code = message.text
    user_data = await state.get_data()
    phone = user_data['phone']
    client = user_data['client']

    try:
        await client.sign_in(phone, code)
        session_string = client.session.save()

        cursor.execute('INSERT INTO accounts (phone, session) VALUES (?, ?)', (phone, session_string))
        conn.commit()

        await message.answer(f"Аккаунт {phone} успешно добавлен!")
        await client.disconnect()
        await state.clear()

    except Exception as e:
        await message.answer(f"Ошибка при входе в аккаунт: {e}")
        await client.disconnect()
        await state.clear()

# ================== ФУНКЦИИ ДЛЯ РАССЫЛКИ ===================

@dp.message(F.text == "📤 Новая рассылка")
async def new_mailing(message: Message, state: FSMContext):
    cursor.execute('SELECT account_id, phone FROM accounts')
    accounts = cursor.fetchall()

    if not accounts:
        await message.answer("Нет добавленных аккаунтов. Пожалуйста, добавьте аккаунт.")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Аккаунт {acc[1]}", callback_data=f"select_account_{acc[0]}")] for acc in accounts
    ])
    await message.answer("Выберите аккаунт для рассылки:", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("select_account_"))
async def select_account(callback_query: CallbackQuery, state: FSMContext):
    account_id = int(callback_query.data.split("_")[-1])
    await state.update_data(account_id=account_id)

    await callback_query.message.answer("Введите список чатов для рассылки (ссылки через запятую).")
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
        account_id = user_data['account_id']

        mailing_id = cursor.execute(
            'INSERT INTO mailings (user_id, account_id, chats, messages, status, sent_messages, start_time) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (message.from_user.id, account_id, ','.join(chats), '\n'.join(messages), 'active', 0, datetime.now().isoformat())
        ).lastrowid
        conn.commit()

        await message.answer(f"Рассылка #<b>{{mailing_id}</b> создана и запущена!", parse_mode="HTML")

        asyncio.create_task(send_messages(mailing_id, account_id, chats, messages, delay))
        await state.clear()

    except ValueError:
        await message.answer("Пожалуйста, введите правильное число для задержки.")

# Функция отправки сообщений от имени выбранного аккаунта
async def send_messages(mailing_id, account_id, chats, messages, delay):
    cursor.execute('SELECT session FROM accounts WHERE account_id = ?', (account_id,))
    session_data = cursor.fetchone()

    client = TelegramClient(f'session_{account_id}', API_ID, API_HASH)
    await client.connect()
    await client.session.load(session_data[0])

    sent_count = 0

    for chat in chats:
        try:
            for message in random.sample(messages, len(messages)):
                await client.send_message(chat.strip(), message)
                sent_count += 1
                cursor.execute('UPDATE mailings SET sent_messages = ? WHERE mailing_id = ?', (sent_count, mailing_id))
                conn.commit()

                await asyncio.sleep(delay)
        except Exception as e:
            logging.error(f"Ошибка при отправке сообщения в чат {chat}: {e}")

    cursor.execute('UPDATE mailings SET status = ? WHERE mailing_id = ?', ('completed', mailing_id))
    conn.commit()
    await client.disconnect()

# ================== УПРАВЛЕНИЕ РАССЫЛКАМИ ===================

@dp.callback_query(F.data.startswith("pause_mailing_"))
async def pause_mailing(callback_query: CallbackQuery):
    mailing_id = callback_query.data.split("_")[-1]
    cursor.execute('UPDATE mailings SET status = ? WHERE mailing_id = ?', ('paused', mailing_id))
    conn.commit()

    await callback_query.message.edit_text(f"Рассылка #<b>{mailing_id}</b> приостановлена.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Продолжить", callback_data=f"resume_mailing_{mailing_id}")]
    ]), parse_mode="HTML")

@dp.callback_query(F.data.startswith("cancel_mailing_"))
async def cancel_mailing(callback_query: CallbackQuery):
    mailing_id = callback_query.data.split("_")[-1]
    cursor.execute('UPDATE mailings SET status = ? WHERE mailing_id = ?', ('cancelled', mailing_id))
    conn.commit()

    await callback_query.message.edit_text(f"Рассылка #<b>{mailing_id}</b> прервана.", parse_mode="HTML")

# ================== ПОМОЩНИКИ ===================

def generate_key():
    """Генерация случайного одноразового ключа"""
    return ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890', k=8))

# ================== ЗАПУСК БОТА ===================

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

