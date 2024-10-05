import logging
import asyncio
import os
from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.bot import DefaultBotProperties
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, ContentType
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from telethon.tl.types import InputPeerChannel, Channel
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.errors.rpcerrorlist import PhoneNumberInvalidError
from datetime import datetime, timedelta
import random
import os
import sqlite3
import threading

API_TOKEN = '8024335015:AAEeQ6cZSHJdvSXhMzyubyth1UHOv2mFtpM'
ADMIN_ID = 1083294848 # Ваш Telegram ID для доступа к админке
TELEGRAM_API_ID = '23422308'
TELEGRAM_API_HASH = '1da8d8d190e8fb59531b28258d1ed64c'
BUY_LINK = "https://t.me/sirdebar"

db_lock = threading.Lock()

if not os.path.exists('temp_photos'):
    os.makedirs('temp_photos')

# Настройка логирования
logging.basicConfig(level=logging.INFO)

session = AiohttpSession()
bot = Bot(token=API_TOKEN, session=session, default=DefaultBotProperties(parse_mode='HTML'))
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
    waiting_for_password = State()

class MailingStates(StatesGroup):
    waiting_for_account = State()
    choosing_chats = State()
    waiting_for_messages = State()
    waiting_for_delay = State()
    waiting_for_action = State()

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
# ================== ПРОФИЛЬ И ПОДПИСКА ===================

@dp.message(F.text == "📋 Профиль")
async def show_profile(message: Message):
    user_id = message.from_user.id

    if user_id == ADMIN_ID:
        # Подсчитываем количество активных подписчиков
        cursor.execute('SELECT COUNT(*) FROM users WHERE subscription_expires > ?', (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),))
        active_subscribers = cursor.fetchone()[0]

        # Подсчитываем общее количество рассылок всеми пользователями
        cursor.execute('SELECT SUM(sent_messages) FROM mailings')
        total_mailings = cursor.fetchone()[0] or 0  # Используем 0, если нет рассылок

        # Подсчитываем количество личных рассылок администратора
        cursor.execute('SELECT SUM(sent_messages) FROM mailings WHERE user_id = ?', (ADMIN_ID,))
        personal_mailings = cursor.fetchone()[0] or 0  # Используем 0, если администратор не делал рассылки

        # Отправляем информацию администратору
        await message.answer(
            "<b>👑 Профиль администратора:</b>\n"
            f"<b>Имя:</b> Администратор\n\n"
            f"<b>Активных подписчиков:</b> {active_subscribers}\n\n"
            f"<b>Общее количество всех рассылок:</b> {total_mailings}\n\n"
            f"<b>Количество ваших рассылок:</b> {personal_mailings}"
        )
        return

    # Если не администратор, показываем профиль обычного пользователя
    cursor.execute('SELECT name, subscription_expires FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()

    if not result:
        await message.answer("<b>⛔ У вас нет активной подписки.</b>")
        return

    name, subscription_expires = result
    cursor.execute('SELECT SUM(sent_messages) FROM mailings WHERE user_id = ?', (user_id,))
    mailing_count = cursor.fetchone()[0] or 0  # Используем 0, если рассылок нет

    await message.answer(
        f"<b>👤 Ваш профиль:</b>\n"
        f"<b>Имя:</b> {name}\n\n"
        f"<b>Оставшийся срок подписки:</b> {subscription_expires}\n\n"
        f"<b>Количество ваших рассылок:</b> {mailing_count}"
    )

# ================== ПОКУПКА ДОСТУПА ===================

@dp.message(F.text == "🛒 Купить доступ")
async def buy_access(message: Message):
    admin_username = "sirdebar"  # Здесь нужно указать ваш username
    await message.answer(f"<b>Доступ к боту вы можете приобрести у @{admin_username}!</b>")

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

# ================== ПРОВЕРКА ПОДПИСКИ ===================

async def check_subscription_expiration():
    """Проверяем, не истекла ли подписка, и блокируем доступ, если истекла."""
    while True:
        cursor.execute('SELECT user_id, subscription_expires FROM users')
        users = cursor.fetchall()

        for user_id, subscription_expires in users:
            if datetime.strptime(subscription_expires, "%Y-%m-%d %H:%M:%S") < datetime.now():
                # Уведомляем пользователя об окончании подписки
                await bot.send_message(
                    user_id,
                    "<b>⏳ Ваша подписка закончилась.</b>\n"
                    "Продлить доступ вы можете у администратора."
                )

                # Обновляем клавиатуру для покупки доступа
                await bot.send_message(
                    user_id,
                    "<b>Продлить доступ вы можете с помощью кнопок ниже.</b>",
                    reply_markup=get_new_user_menu()
                )

                # Удаляем доступ ко всем командам (в базе данных или в другом месте)
                cursor.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
                conn.commit()

        await asyncio.sleep(3600)  # Проверка каждый час

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

    try:
        if not await client.is_user_authorized():
            await client.send_code_request(phone_number)
            await message.answer(f"<b>📲 Код отправлен на номер {phone_number}.</b> Введите его.")
            await state.update_data(phone_number=phone_number, client=client)
            await state.set_state(AccountStates.waiting_for_code)
        else:
            await message.answer("<b>✅ Этот номер уже авторизован.</b>")
            await state.clear()
    except PhoneNumberInvalidError:
        await message.answer(f"<b>❌ Неверный номер телефона: {phone_number}. Пожалуйста, введите корректный номер.</b>")
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

        await message.answer(f"<b>🗝️ Аккаунт {phone_number} успешно добавлен.</b>")
        await state.clear()

    except SessionPasswordNeededError:
        # Если требуется пароль для 2FA, запрашиваем его
        await message.answer("<b>🔐 Этот аккаунт защищен двухфакторной аутентификацией. Введите пароль:</b>")
        await state.update_data(client=client)
        await state.set_state(AccountStates.waiting_for_password)

    except Exception as e:
        await message.answer(f"<b>❌ Ошибка авторизации:</b> {e}")
        await state.clear()

@dp.message(AccountStates.waiting_for_password)
async def process_password(message: Message, state: FSMContext):
    password = message.text
    user_data = await state.get_data()
    client = user_data['client']

    try:
        # Входим с паролем
        await client.sign_in(password=password)
        phone_number = user_data['phone_number']
        session_string = client.session.save()
        cursor.execute('INSERT INTO accounts (user_id, phone_number, session) VALUES (?, ?, ?)', (message.from_user.id, phone_number, session_string))
        conn.commit()

        await message.answer(f"<b>🗝️ Аккаунт {phone_number} успешно добавлен с двухфакторной аутентификацией.</b>")
        await state.clear()

    except Exception as e:
        await message.answer(f"<b>❌ Ошибка авторизации:</b> {e}")
        await state.set_state(AccountStates.waiting_for_password)

# ================== ДОБАВЛЕНИЕ АККАУНТА И ПАРСИНГ ЧАТОВ ===================

async def get_chats(client, account_id):
    """Получение списка чатов с аккаунта и сохранение их в базу данных."""
    dialogs = await client.get_dialogs()
    for dialog in dialogs:
        if isinstance(dialog.entity, InputPeerChannel):
            chat_id = dialog.id
            title = dialog.title
            cursor.execute('INSERT OR REPLACE INTO chats (chat_id, account_id, title) VALUES (?, ?, ?)', (chat_id, account_id, title))
    conn.commit()

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

    # Создаем клавиатуру с кнопками для выбора аккаунта
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Аккаунт {account[1]}", callback_data=f"choose_account_{account[0]}")]
        for account in accounts
    ])

    await message.answer("<b>📋 Выберите аккаунт для рассылки:</b>", reply_markup=keyboard)
    await state.set_state(MailingStates.waiting_for_account)

@dp.callback_query(F.data.startswith("choose_account_"))
async def choose_account(callback_query: CallbackQuery, state: FSMContext):
    account_id = int(callback_query.data.split("_")[-1])

    # Парсим группы каждый раз при создании новой рассылки
    cursor.execute('SELECT phone_number, session FROM accounts WHERE account_id = ?', (account_id,))
    account = cursor.fetchone()
    phone_number, session_string = account

    client = TelegramClient(f'sessions/{phone_number}', TELEGRAM_API_ID, TELEGRAM_API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        await callback_query.message.answer("<b>Ошибка авторизации.</b>")
        await state.clear()
        return

    # Парсим группы при каждом запуске рассылки
    await get_group_chats(client, account_id)
    await client.disconnect()

    # Повторно запрашиваем список чатов
    cursor.execute('SELECT chat_id, title FROM chats WHERE account_id = ?', (account_id,))
    chats = cursor.fetchall()

    # Сохраняем account_id в состояние
    await state.update_data(account_id=account_id)
    
    # Показываем чаты с возможностью включения/выключения (начинаем с первой страницы)
    await show_chat_selection(callback_query.message, chats, state, page=0)

async def show_chat_selection(message, chats, state, page=0):
    """Показ списка чатов для выбора с пагинацией."""
    per_page = 10
    start = page * per_page
    end = start + per_page
    current_page_chats = chats[start:end]

    # Получаем выбранные чаты из состояния
    user_data = await state.get_data()
    selected_chats = user_data.get('selected_chats', [chat[0] for chat in chats])  # Изначально все чаты выбраны

    buttons = []
    for chat in current_page_chats:
        status = "✅" if chat[0] in selected_chats else "❌"
        buttons.append([InlineKeyboardButton(text=f"{chat[1]} {status}", callback_data=f"toggle_chat_{chat[0]}")])

    if len(chats) > per_page:
        pagination_buttons = []
        if page > 0:
            pagination_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"prev_page_{page-1}"))
        if end < len(chats):
            pagination_buttons.append(InlineKeyboardButton(text="➡️ Вперед", callback_data=f"next_page_{page+1}"))
        buttons.append(pagination_buttons)

    buttons.append([InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_chats")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer("<b>Выберите чаты для рассылки:</b>", reply_markup=keyboard)
    await state.update_data(selected_chats=selected_chats, all_chats=chats, page=page)

@dp.callback_query(F.data.startswith("toggle_chat_"))
async def toggle_chat(callback_query: CallbackQuery, state: FSMContext):
    chat_id = int(callback_query.data.split("_")[-1])
    user_data = await state.get_data()
    selected_chats = user_data['selected_chats']

    # Включение/выключение чатов
    if chat_id in selected_chats:
        selected_chats.remove(chat_id)
    else:
        selected_chats.append(chat_id)

    await state.update_data(selected_chats=selected_chats)

    # Обновляем клавиатуру после изменения статуса чатов
    chats = user_data['all_chats']
    page = user_data['page']
    await show_chat_selection(callback_query.message, chats, state, page=page)

@dp.callback_query(F.data.startswith("next_page_") | F.data.startswith("prev_page_"))
async def paginate_chats(callback_query: CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    chats = user_data['all_chats']
    page = int(callback_query.data.split("_")[-1])

    await show_chat_selection(callback_query.message, chats, state, page)

@dp.callback_query(F.data == "confirm_chats")
async def confirm_chats(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.message.answer("<b>💬 Введите сообщение для рассылки.</b>")
    await state.set_state(MailingStates.waiting_for_messages)

# ================== ПРОЦЕСС РАССЫЛКИ ===================

@dp.message(MailingStates.waiting_for_messages, F.text | F.photo)
async def process_messages(message: Message, state: FSMContext):
    # Если сообщение содержит фото
    if message.photo:
        photo = message.photo[-1]  # Берем самое большое фото
        file_info = await bot.get_file(photo.file_id)
        file_path = file_info.file_path
        downloaded_file = await bot.download_file(file_path)

        # Сохраняем фото временно на диск
        photo_path = f"temp_photos/{photo.file_id}.jpg"
        os.makedirs("temp_photos", exist_ok=True)  # Создаем папку, если её нет
        with open(photo_path, 'wb') as new_file:
            new_file.write(downloaded_file.getvalue())

        # Сохраняем фото и подпись в состояние
        await state.update_data(photo=photo_path)
        if message.caption:
            await state.update_data(messages=message.caption)  # Подпись сохраняется как текст
        else:
            await state.update_data(messages=None)  # Если подписи нет, оставляем текст пустым

    elif message.text:
        # Сохраняем текст сообщения
        await state.update_data(messages=message.text)
        await state.update_data(photo=None)  # Обнуляем фото, если есть только текст

    await message.answer("<b>⏳ Введите задержку между сообщениями (например, 5с, 5м, 5ч, максимум 5 часов, минимум 5 секунд).</b>")
    await state.set_state(MailingStates.waiting_for_delay)


def parse_delay(delay_str):
    """Парсинг задержки с поддержкой форматов секунд, минут и часов."""
    if delay_str.endswith('с'):
        return int(delay_str[:-1])
    elif delay_str.endswith('м'):
        return int(delay_str[:-1]) * 60
    elif delay_str.endswith('ч'):
        return int(delay_str[:-1]) * 3600
    else:
        raise ValueError("Неверный формат задержки. Используйте с (секунды), м (минуты), ч (часы).")

@dp.message(MailingStates.waiting_for_delay)
async def process_delay(message: Message, state: FSMContext):
    try:
        delay = parse_delay(message.text)
        if delay < 5 or delay > 18000:  # Максимум 5 часов (18000 секунд)
            raise ValueError

        # Сохраняем задержку в состояние
        await state.update_data(delay=delay)

        user_data = await state.get_data()
        account_id = user_data['account_id']
        selected_chats = user_data['selected_chats']
        messages = user_data.get('messages')  # Получаем текст сообщения
        photo = user_data.get('photo')  # Получаем фото, если оно есть

        if not messages and not photo:
            await message.answer("<b>⚠️ Вы не предоставили текст или фото для рассылки.</b>")
            return

        # Запускаем рассылку
        asyncio.create_task(start_mailing(account_id, selected_chats, messages, photo, delay, message.from_user.id))
        await message.answer("<b>🚀 Рассылка запущена!</b> Статус: <b>Активна</b>", reply_markup=get_mailing_control_keyboard(paused=False))
        await state.set_state(MailingStates.waiting_for_action)

    except ValueError:
        await message.answer("<b>⚠️ Неверный формат. Введите задержку в формате 5с, 5м, 5ч (не менее 5 секунд и не более 5 часов).</b>")

def get_mailing_control_keyboard(paused=False):
    """Клавиатура управления рассылкой."""
    buttons = []
    if paused:
        buttons.append([InlineKeyboardButton(text="▶️ Продолжить", callback_data="resume_mailing")])
    else:
        buttons.append([InlineKeyboardButton(text="⏸ Приостановить", callback_data="pause_mailing")])
    buttons.append([InlineKeyboardButton(text="⏹ Закончить", callback_data="stop_mailing")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def send_messages(account_id, chats, messages, delay, user_id):
    cursor.execute('SELECT phone_number, session FROM accounts WHERE account_id = ?', (account_id,))
    account = cursor.fetchone()

    session_path = f'sessions/{account[0]}.session'
    client = TelegramClient(session_path, TELEGRAM_API_ID, TELEGRAM_API_HASH)
    await client.connect()

    sent_count = 0
    previous_message = None

    # Первое сообщение отправляется сразу
    for chat in chats:
        try:
            previous_message = await client.send_message(chat, messages)
            sent_count += 1
            cursor.execute('INSERT INTO mailings (user_id, chats, messages, status, sent_messages, start_time) VALUES (?, ?, ?, ?, ?, ?)',
                           (user_id, ','.join(str(c) for c in chats), '\n'.join(messages), 'active', sent_count, datetime.now().isoformat()))
            conn.commit()

            # Ждем задержку перед отправкой следующего сообщения
            await asyncio.sleep(delay)
        except Exception as e:
            logging.error(f"Ошибка при отправке сообщения в чат {chat}: {e}")

    await client.disconnect()

# ================== ДОБАВЛЕНИЕ АККАУНТА И ПАРСИНГ ГРУПП ===================

async def get_group_chats(client, account_id):
    """Получение списка групповых чатов с аккаунта и сохранение их в базу данных."""
    dialogs = await client.get_dialogs()
    for dialog in dialogs:
        if isinstance(dialog.entity, Channel) and dialog.entity.megagroup:
            chat_id = dialog.id
            title = dialog.title
            cursor.execute('INSERT OR REPLACE INTO chats (chat_id, account_id, title) VALUES (?, ?, ?)', (chat_id, account_id, title))
    conn.commit()

# ================== УПРАВЛЕНИЕ РАССЫЛКОЙ ===================

active_mailings = {}

async def start_mailing(account_id, chats, messages, photo, delay, user_id):
    """Запуск рассылки сообщений с контролем и циклической отправкой."""
    active_mailings[user_id] = True  # Рассылка активна
    cursor.execute('SELECT phone_number, session FROM accounts WHERE account_id = ?', (account_id,))
    account = cursor.fetchone()

    session_path = f'sessions/{account[0]}.session'
    client = TelegramClient(session_path, TELEGRAM_API_ID, TELEGRAM_API_HASH)
    await client.connect()

    sent_count = 0

    while active_mailings.get(user_id):
        for chat_id in chats:
            if not active_mailings.get(user_id):
                break
            try:
                # Если есть фото, отправляем его с подписью (если она есть)
                if photo:
                    await client.send_file(chat_id, photo, caption=messages if messages else "")
                else:
                    await client.send_message(chat_id, messages)
                sent_count += 1
                await asyncio.sleep(delay)  # Задержка перед отправкой следующего сообщения
            except Exception as e:
                logging.error(f"Ошибка при отправке в чат {chat_id}: {e}")
        
        # После одного полного прохода ждем задержку перед новым циклом
        if active_mailings.get(user_id):
            await asyncio.sleep(delay)
        
    await client.disconnect()

@dp.callback_query(F.data == "pause_mailing")
async def pause_mailing(callback_query: CallbackQuery, state: FSMContext):
    """Обработчик паузы рассылки."""
    user_id = callback_query.from_user.id
    if active_mailings.get(user_id):
        active_mailings[user_id] = False  # Останавливаем рассылку (пауза)
        await callback_query.message.edit_text("<b>Статус рассылки:</b> Приостановлена", reply_markup=get_mailing_control_keyboard(paused=True))

@dp.callback_query(F.data == "resume_mailing")
async def resume_mailing(callback_query: CallbackQuery, state: FSMContext):
    """Возобновление рассылки после паузы."""
    user_data = await state.get_data()

    account_id = user_data.get('account_id')  # Получаем id аккаунта
    selected_chats = user_data.get('selected_chats')  # Чаты для рассылки
    messages = user_data.get('messages')  # Текст сообщения
    photo = user_data.get('photo')  # Фото (если есть)
    delay = user_data.get('delay')  # Задержка между сообщениями

    # Проверяем, если фото было случайно удалено
    if photo and not os.path.exists(photo):
        await callback_query.message.edit_text("<b>Ошибка:</b> Фото для рассылки было удалено. Пожалуйста, загрузите новое.")
        return

    if not account_id or not selected_chats or not delay:
        await callback_query.message.edit_text("<b>Ошибка:</b> Недостаточно данных для возобновления рассылки.")
        return

    # Возобновляем рассылку
    active_mailings[callback_query.from_user.id] = True
    asyncio.create_task(start_mailing(account_id, selected_chats, messages, photo, delay, callback_query.from_user.id))

    await callback_query.message.edit_text("<b>Статус рассылки:</b> Активна", reply_markup=get_mailing_control_keyboard(paused=False))

@dp.callback_query(F.data == "stop_mailing")
async def stop_mailing(callback_query: CallbackQuery, state: FSMContext):
    """Обработчик завершения рассылки."""
    user_id = callback_query.from_user.id
    active_mailings[user_id] = False  # Полностью останавливаем рассылку

    # Получаем данные о пользователе и рассылке
    user_data = await state.get_data()
    photo = user_data.get('photo')
    selected_chats = user_data.get('selected_chats')

    # Удаляем фото, если оно было использовано, только после завершения рассылки
    if photo and os.path.exists(photo):
        os.remove(photo)

    # Добавляем завершённую рассылку в базу данных
    cursor.execute('INSERT INTO mailings (user_id, chats, sent_messages, status, start_time) VALUES (?, ?, ?, ?, ?)',
                   (user_id, ','.join(str(c) for c in selected_chats), len(selected_chats), 'finished', datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()

    # Отправляем пользователю сообщение о завершении рассылки
    await callback_query.message.edit_text("<b>Статус рассылки:</b> Завершена")

# ================== ЗАПУСК БОТА ===================
async def main():
    # Запуск регулярной проверки подписки
    asyncio.create_task(check_subscription_expiration())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())