import logging
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from telethon import TelegramClient
from datetime import datetime, timedelta
import random
import sqlite3

API_TOKEN = '8024335015:AAEeQ6cZSHJdvSXhMzyubyth1UHOv2mFtpM'
ADMIN_ID = 1083294848 # Ваш Telegram ID для доступа к админке
TELEGRAM_API_ID = '23422308'
TELEGRAM_API_HASH = '1da8d8d190e8fb59531b28258d1ed64c'

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Создаем бота и диспетчер
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Подключение к базе данных SQLite
conn = sqlite3.connect('bot_database.db')
cursor = conn.cursor()

# Создаем таблицы, если они не существуют
cursor.execute('''
    CREATE TABLE IF NOT EXISTS accounts (
        account_id INTEGER PRIMARY KEY AUTOINCREMENT, 
        user_id INTEGER, 
        phone_number TEXT, 
        session TEXT
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS mailings (
        mailing_id INTEGER PRIMARY KEY AUTOINCREMENT, 
        user_id INTEGER, 
        chats TEXT, 
        messages TEXT, 
        status TEXT, 
        sent_messages INTEGER, 
        start_time DATETIME
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS chats (
        chat_id INTEGER PRIMARY KEY, 
        account_id INTEGER, 
        title TEXT
    )
''')
conn.commit()

# ================== СОСТОЯНИЯ ===================

class AccountStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code = State()

class MailingStates(StatesGroup):
    waiting_for_account = State()
    choosing_chats = State()
    waiting_for_messages = State()
    waiting_for_delay = State()

# ================== МЕНЮ ===================

def get_user_menu():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='📋 Профиль')],
            [KeyboardButton(text='🗝️ Добавить аккаунт')],
            [KeyboardButton(text='📤 Новая рассылка')]
        ],
        resize_keyboard=True
    )
    return keyboard

def get_chat_control_keyboard(chats, selected_chats, page=0):
    keyboard = InlineKeyboardMarkup()
    for chat in chats[page*10:(page+1)*10]:
        status = "✅" if chat['id'] in selected_chats else "❌"
        keyboard.add(InlineKeyboardButton(text=f"{chat['title']} {status}", callback_data=f"toggle_chat_{chat['id']}"))

    if len(chats) > 10:
        if page > 0:
            keyboard.add(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"prev_page_{page-1}"))
        if (page + 1) * 10 < len(chats):
            keyboard.add(InlineKeyboardButton(text="➡️ Вперед", callback_data=f"next_page_{page+1}"))
    
    keyboard.add(InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_chats"))
    return keyboard

# ================== ДОБАВЛЕНИЕ АККАУНТА ===================

@dp.message(F.text == "🗝️ Добавить аккаунт")
async def add_account(message: Message, state: FSMContext):
    await message.answer("Введите номер телефона для добавления аккаунта.")
    await state.set_state(AccountStates.waiting_for_phone)

@dp.message(AccountStates.waiting_for_phone)
async def process_phone(message: Message, state: FSMContext):
    phone_number = message.text
    user_id = message.from_user.id

    client = TelegramClient(f'sessions/{phone_number}', TELEGRAM_API_ID, TELEGRAM_API_HASH)
    await client.connect()

    if not await client.is_user_authorized():
        await client.send_code_request(phone_number)
        await message.answer(f"Код отправлен на номер {phone_number}. Введите его.")
        await state.update_data(phone_number=phone_number, client=client)
        await state.set_state(AccountStates.waiting_for_code)
    else:
        await message.answer("Этот номер уже авторизован.")
        await state.clear()

@dp.message(AccountStates.waiting_for_code)
async def process_code(message: Message, state: FSMContext):
    code = message.text
    user_data = await state.get_data()
    phone_number = user_data['phone_number']
    client = user_data['client']

    try:
        await client.sign_in(phone_number, code)
        session_string = client.session.save()
        cursor.execute('INSERT INTO accounts (user_id, phone_number, session) VALUES (?, ?, ?)', (message.from_user.id, phone_number, session_string))
        conn.commit()

        await message.answer(f"Аккаунт {phone_number} успешно добавлен.", reply_markup=get_user_menu())
        await state.clear()
    except Exception as e:
        await message.answer(f"Ошибка авторизации: {e}")
        await state.clear()

# ================== НОВАЯ РАССЫЛКА ===================

@dp.message(F.text == "📤 Новая рассылка")
async def new_mailing(message: Message, state: FSMContext):
    cursor.execute('SELECT account_id, phone_number FROM accounts WHERE user_id = ?', (message.from_user.id,))
    accounts = cursor.fetchall()

    if not accounts:
        await message.answer("Сначала добавьте аккаунт для рассылки.")
        return

    keyboard = InlineKeyboardMarkup()
    for account in accounts:
        keyboard.add(InlineKeyboardButton(text=f"Аккаунт {account[1]}", callback_data=f"choose_account_{account[0]}"))

    await message.answer("Выберите аккаунт для рассылки:", reply_markup=keyboard)
    await state.set_state(MailingStates.waiting_for_account)

@dp.callback_query(F.data.startswith("choose_account_"))
async def choose_account(callback_query: CallbackQuery, state: FSMContext):
    account_id = int(callback_query.data.split("_")[-1])

    cursor.execute('SELECT chat_id, title FROM chats WHERE account_id = ?', (account_id,))
    chats = [{'id': row[0], 'title': row[1]} for row in cursor.fetchall()]  # Исправлено

    await callback_query.message.answer("Выберите чаты для рассылки:", reply_markup=get_chat_control_keyboard(chats, selected_chats=[], page=0))
    await state.update_data(account_id=account_id, chats=chats, selected_chats=[])
    await state.set_state(MailingStates.choosing_chats)

@dp.callback_query(F.data.startswith("toggle_chat_"))
async def toggle_chat(callback_query: CallbackQuery, state: FSMContext):
    chat_id = int(callback_query.data.split("_")[-1])
    user_data = await state.get_data()
    selected_chats = user_data['selected_chats']

    if chat_id in selected_chats:
        selected_chats.remove(chat_id)
    else:
        selected_chats.append(chat_id)

    await state.update_data(selected_chats=selected_chats)
    await callback_query.message.edit_reply_markup(get_chat_control_keyboard(user_data['chats'], selected_chats, page=0))

@dp.callback_query(F.data == "confirm_chats")
async def confirm_chats(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.message.answer("Введите сообщения для рассылки.")
    await state.set_state(MailingStates.waiting_for_messages)

# ================== ЗАПУСК БОТА ===================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())