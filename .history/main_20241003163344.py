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
import os
import sqlite3

API_TOKEN = '8024335015:AAEeQ6cZSHJdvSXhMzyubyth1UHOv2mFtpM'
ADMIN_ID = 1083294848 # Ваш Telegram ID для доступа к админке
TELEGRAM_API_ID = '23422308'
TELEGRAM_API_HASH = '1da8d8d190e8fb59531b28258d1ed64c'
BUY_LINK = "https://t.me/sirdebar"


# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Создаем бота и диспетчер
bot = Bot(token=API_TOKEN, parse_mode='HTML')  # Включаем HTML парсинг для сообщений
dp = Dispatcher(storage=MemoryStorage())

# Подключение к базе данных SQLite
conn = sqlite3.connect('bot_database.db')
cursor = conn.cursor()

# Создаем таблицы, если они не существуют
cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, 
        name TEXT, 
        subscription_expires DATETIME
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS accounts (
        account_id INTEGER PRIMARY KEY AUTOINCREMENT, 
        user_id INTEGER, 
        phone_number TEXT, 
        session TEXT
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS keys (
        key TEXT PRIMARY KEY, 
        valid_until DATETIME, 
        days INTEGER
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

class KeyStates(StatesGroup):
    waiting_for_key = State()
    waiting_for_days = State()

# ================== МЕНЮ ===================

def get_new_user_menu():
    """Меню для новых пользователей"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='🛒 Купить доступ', url=BUY_LINK)],
            [KeyboardButton(text='🔑 Ввести ключ доступа')]
        ],
        resize_keyboard=True
    )
    return keyboard

def get_user_menu():
    """Меню для пользователей с активной подпиской"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='📋 Профиль')],
            [KeyboardButton(text='🗝️ Добавить аккаунт')],
            [KeyboardButton(text='📤 Новая рассылка')]
        ],
        resize_keyboard=True
    )
    return keyboard

def get_admin_menu():
    """Меню для администратора"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='🔑 Генерация ключа')],
            [KeyboardButton(text='📋 Профиль')],
            [KeyboardButton(text='🗝️ Добавить аккаунт')],  # Добавляем возможность администратору добавлять аккаунты
            [KeyboardButton(text='📤 Новая рассылка')]
        ],
        resize_keyboard=True
    )
    return keyboard

# ================== ПРОФИЛЬ И ПОДПИСКА ===================

# Хэндлер для команды "start"
@dp.message(Command(commands=["start"]))
async def start_bot(message: Message):
    user_id = message.from_user.id
    
    # Если пользователь - админ, сразу выводим админ-панель
    if user_id == ADMIN_ID:
        await message.answer("<b>👑 Добро пожаловать, админ!</b>", reply_markup=get_admin_menu())
        return
    
    cursor.execute('SELECT subscription_expires FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()

    if result:
        subscription_expires = result[0]
        if datetime.strptime(subscription_expires, "%Y-%m-%d %H:%M:%S") > datetime.now():
            await message.answer("<b>🎉 Добро пожаловать!</b> Ваш доступ <b>активен</b>.", reply_markup=get_user_menu())
        else:
            await message.answer("<b>⏳ Ваш доступ истек.</b> Воспользуйтесь кнопками ниже.", reply_markup=get_new_user_menu())
    else:
        await message.answer("<b>👋 Добро пожаловать!</b> Воспользуйтесь кнопками ниже.", reply_markup=get_new_user_menu())

# Хэндлер для показа профиля
@dp.message(F.text == "📋 Профиль")
async def show_profile(message: Message):
    cursor.execute('SELECT name, subscription_expires FROM users WHERE user_id = ?', (message.from_user.id,))
    result = cursor.fetchone()

    if not result:
        await message.answer("<b>⛔ У вас нет активной подписки.</b>")
        return

    name, subscription_expires = result
    cursor.execute('SELECT COUNT(*) FROM mailings WHERE user_id = ?', (message.from_user.id,))
    mailing_count = cursor.fetchone()[0]

    await message.answer(f"<b>👤 Ваш профиль:</b>\n<b>Имя:</b> {name}\n<b>Оставшийся срок подписки:</b> {subscription_expires}\n<b>Количество рассылок:</b> {mailing_count}")

# ================== ГЕНЕРАЦИЯ И ПРОВЕРКА КЛЮЧЕЙ ===================

@dp.message(F.text == "🔑 Ввести ключ доступа")
async def ask_for_key(message: Message, state: FSMContext):
    await message.answer("<b>🔑 Введите ключ доступа.</b>")
    await state.set_state(KeyStates.waiting_for_key)

@dp.message(KeyStates.waiting_for_key)
async def process_key(message: Message, state: FSMContext):
    key = message.text
    cursor.execute('SELECT valid_until, days FROM keys WHERE key = ?', (key,))
    result = cursor.fetchone()

    if result:
        valid_until, days = result
        if datetime.strptime(valid_until, "%Y-%m-%d %H:%M:%S") > datetime.now():
            subscription_expires = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute('INSERT OR REPLACE INTO users (user_id, name, subscription_expires) VALUES (?, ?, ?)',
                           (message.from_user.id, message.from_user.full_name, subscription_expires))
            conn.commit()

            await message.answer("<b>✅ Ключ активирован!</b> Ваш доступ <b>продлен</b>.", reply_markup=get_user_menu())
        else:
            await message.answer("<b>⛔ Ключ истек.</b>")
    else:
        await message.answer("<b>❌ Неверный ключ.</b>")
    
    await state.clear()

# ================== ДОБАВЛЕНИЕ АККАУНТА ===================

@dp.message(F.text == "🗝️ Добавить аккаунт")
async def add_account(message: Message, state: FSMContext):
    await message.answer("<b>📞 Введите номер телефона (в формате 9123456789).</b>")
    await state.set_state(AccountStates.waiting_for_phone)

@dp.message(AccountStates.waiting_for_phone)
async def process_phone(message: Message, state: FSMContext):
    phone_number = message.text
    user_id = message.from_user.id

    # Создаем сессию для входа через Telethon
    session_path = f'sessions/{phone_number}.session'
    if not os.path.exists('sessions'):
        os.mkdir('sessions')

    client = TelegramClient(session_path, TELEGRAM_API_ID, TELEGRAM_API_HASH)
    await client.connect()

    if not await client.is_user_authorized():
        await client.send_code_request(phone_number)
        await message.answer(f"<b>📲 Код отправлен на номер {phone_number}.</b> Введите его.")
        await state.update_data(phone_number=phone_number, client=client)
        await state.set_state(AccountStates.waiting_for_code)
    else:
        await message.answer("<b>✅ Этот номер уже авторизован.</b>")
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

        await message.answer(f"<b>🗝️ Аккаунт {phone_number} успешно добавлен.</b>", reply_markup=get_user_menu())
        await state.clear()
    except Exception as e:
        if "The confirmation code has expired" in str(e):
            await message.answer("<b>⏳ Код истек. Отправляем новый...</b>")
            await client.send_code_request(phone_number)
            await message.answer(f"<b>📲 Новый код отправлен на номер {phone_number}. Введите его.</b>")
        else:
            await message.answer(f"<b>❌ Ошибка авторизации:</b> {e}")
        await state.set_state(AccountStates.waiting_for_code)

# ================== ГЕНЕРАЦИЯ КЛЮЧА ДЛЯ АДМИНА С ВЫБОРОМ СРОКА ===================

@dp.message(F.text == "🔑 Генерация ключа")
async def ask_for_days(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("<b>⛔ У вас нет доступа.</b>")
        return
    await message.answer("<b>📅 Укажите срок действия ключа в днях:</b>")
    await state.set_state(KeyStates.waiting_for_days)

@dp.message(KeyStates.waiting_for_days)
async def generate_key(message: Message, state: FSMContext):
    try:
        days = int(message.text)
        if days <= 0:
            await message.answer("<b>⚠️ Количество дней должно быть положительным числом.</b>")
            return

        key = generate_random_key()
        valid_until = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute('INSERT INTO keys (key, valid_until, days) VALUES (?, ?, ?)', (key, valid_until, days))
        conn.commit()

        await message.answer(f"<b>🔑 Сгенерирован новый ключ на {days} дней:</b> {key}")
        await state.clear()

    except ValueError:
        await message.answer("<b>⚠️ Пожалуйста, введите корректное число.</b>")

def generate_random_key():
    """Генерация случайного одноразового ключа"""
    return ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=8))

# ================== РАССЫЛКА СООБЩЕНИЙ ===================

def get_chat_control_keyboard(chats, selected_chats, page=0):
    """Генерация клавиатуры для выбора чатов с возможностью включения/выключения"""
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

@dp.message(F.text == "📤 Новая рассылка")
async def new_mailing(message: Message, state: FSMContext):
    # Запрашиваем список аккаунтов пользователя
    cursor.execute('SELECT account_id, phone_number FROM accounts WHERE user_id = ?', (message.from_user.id,))
    accounts = cursor.fetchall()

    if not accounts:
        await message.answer("<b>❌ Сначала добавьте аккаунт для рассылки.</b>")
        return

    keyboard = InlineKeyboardMarkup()
    for account in accounts:
        keyboard.add(InlineKeyboardButton(text=f"Аккаунт {account[1]}", callback_data=f"choose_account_{account[0]}"))

    await message.answer("<b>📋 Выберите аккаунт для рассылки:</b>", reply_markup=keyboard)
    await state.set_state(MailingStates.waiting_for_account)

@dp.callback_query(F.data.startswith("choose_account_"))
async def choose_account(callback_query: CallbackQuery, state: FSMContext):
    account_id = int(callback_query.data.split("_")[-1])

    # Запрашиваем список чатов из базы данных
    cursor.execute('SELECT chat_id, title FROM chats WHERE account_id = ?', (account_id,))
    chats = [{'id': row[0], 'title': row[1]} for row in cursor.fetchall()]

    if not chats:
        await callback_query.message.answer("<b>❌ Нет доступных чатов для этого аккаунта.</b>")
        await state.clear()
        return

    await callback_query.message.answer("<b>📋 Выберите чаты для рассылки:</b>", reply_markup=get_chat_control_keyboard(chats, selected_chats=[], page=0))
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
    await callback_query.message.answer("<b>💬 Введите сообщения для рассылки (каждое сообщение с новой строки).</b>")
    await state.set_state(MailingStates.waiting_for_messages)

@dp.message(MailingStates.waiting_for_messages)
async def process_messages(message: Message, state: FSMContext):
    messages = message.text.split('\n')
    await state.update_data(messages=messages)

    await message.answer("<b>⏳ Введите задержку между сообщениями (в секундах).</b>")
    await state.set_state(MailingStates.waiting_for_delay)

@dp.message(MailingStates.waiting_for_delay)
async def process_delay(message: Message, state: FSMContext):
    try:
        delay = int(message.text)
        user_data = await state.get_data()
        account_id = user_data['account_id']
        selected_chats = user_data['selected_chats']
        messages = user_data['messages']

        # Запускаем рассылку
        asyncio.create_task(send_messages(account_id, selected_chats, messages, delay, message.from_user.id))

        await message.answer("<b>🚀 Рассылка запущена!</b>", reply_markup=get_user_menu())
        await state.clear()

    except ValueError:
        await message.answer("<b>⚠️ Введите правильное число для задержки.</b>")

async def send_messages(account_id, chats, messages, delay, user_id):
    # Получаем аккаунт пользователя и запускаем сессию Telethon
    cursor.execute('SELECT phone_number, session FROM accounts WHERE account_id = ?', (account_id,))
    account = cursor.fetchone()

    session_path = f'sessions/{account[0]}.session'
    client = TelegramClient(session_path, TELEGRAM_API_ID, TELEGRAM_API_HASH)
    await client.connect()

    sent_count = 0
    previous_message = None  # Переменная для хранения предыдущего сообщения

    # Перебираем все чаты и сообщения для рассылки
    for chat in chats:
        for message in messages:
            try:
                # Удаляем предыдущее сообщение перед отправкой нового
                if previous_message:
                    await previous_message.delete()

                previous_message = await client.send_message(chat, message)
                sent_count += 1
                cursor.execute('INSERT INTO mailings (user_id, chats, messages, status, sent_messages, start_time) VALUES (?, ?, ?, ?, ?, ?)',
                               (user_id, ','.join(str(c) for c in chats), '\n'.join(messages), 'active', sent_count, datetime.now().isoformat()))
                conn.commit()
                await asyncio.sleep(delay)
            except Exception as e:
                logging.error(f"Ошибка при отправке сообщения в чат {chat}: {e}")

    await client.disconnect()

# ================== ЗАПУСК БОТА ===================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())