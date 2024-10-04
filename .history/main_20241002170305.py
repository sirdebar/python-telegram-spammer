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

API_TOKEN = '8024335015:AAEeQ6cZSHJdvSXhMzyubyth1UHOv2mFtpM'
ADMIN_ID = 1083294848 # Ваш Telegram ID для доступа к админке

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
cursor.execute('''CREATE TABLE IF NOT EXISTS accounts (user_id INTEGER, phone_number TEXT, session_data BLOB)''')  # Для хранения данных аккаунта
conn.commit()

# ================== СОСТОЯНИЯ ===================

class AdminStates(StatesGroup):
    waiting_for_days = State()

class UserStates(StatesGroup):
    waiting_for_key = State()
    waiting_for_phone_number = State()
    waiting_for_code = State()
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
            [KeyboardButton(text='📤 Новая рассылка')],
            [KeyboardButton(text='📋 Профиль')]
        ],
        resize_keyboard=True
    )
    return keyboard

def get_user_menu():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='🗝️ Ввести код')],
            [KeyboardButton(text='📋 Профиль')],
            [KeyboardButton(text='➕ Добавить аккаунт')],
            [KeyboardButton(text='📤 Новая рассылка')]
        ],
        resize_keyboard=True
    )
    return keyboard

# ================== ФУНКЦИИ ДЛЯ ПОЛЬЗОВАТЕЛЯ ===================

@dp.message(F.text == "🗝️ Ввести код")
async def ask_for_code(message: Message, state: FSMContext):
    await message.answer("Пожалуйста, введите ваш ключ.", parse_mode="HTML")
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

        await message.answer(f"Ключ принят. Доступ активирован до: {valid_until}", reply_markup=get_user_menu(), parse_mode="HTML")
        await state.clear()
    else:
        await message.answer("Ключ недействителен или уже использован.", parse_mode="HTML")
        await state.clear()

# ================== ФУНКЦИИ ДЛЯ ДОБАВЛЕНИЯ АККАУНТОВ ===================

@dp.message(F.text == "➕ Добавить аккаунт")
async def ask_for_phone_number(message: Message, state: FSMContext):
    await message.answer("Пожалуйста, введите номер телефона аккаунта Telegram.", parse_mode="HTML")
    await state.set_state(UserStates.waiting_for_phone_number)

@dp.message(UserStates.waiting_for_phone_number)
async def process_phone_number(message: Message, state: FSMContext):
    phone_number = message.text
    await state.update_data(phone_number=phone_number)
    
    # Здесь должен быть вызов API для отправки кода
    await message.answer("Пожалуйста, введите код подтверждения, который вы получили на телефон.", parse_mode="HTML")
    await state.set_state(UserStates.waiting_for_code)

@dp.message(UserStates.waiting_for_code)
async def process_code(message: Message, state: FSMContext):
    code = message.text
    user_data = await state.get_data()
    phone_number = user_data['phone_number']
    
    # Здесь идет процесс входа в аккаунт через API
    # Пример для сохранения сессии в базу данных
    cursor.execute('INSERT INTO accounts (user_id, phone_number, session_data) VALUES (?, ?, ?)', (message.from_user.id, phone_number, 'session_data_here'))
    conn.commit()

    await message.answer(f"Аккаунт с номером {phone_number} успешно добавлен.", reply_markup=get_user_menu())
    await state.clear()

# ================== ВЫБОР ЧАТОВ ДЛЯ РАССЫЛКИ ===================

async def list_chats_for_account(user_id):
    # Функция для получения чатов, связанных с аккаунтом пользователя
    # Это пример, данные можно извлечь из Telegram через используемое API
    return ["Встречи Москва", "Встречи московсити"]

@dp.message(F.text == "📤 Новая рассылка")
async def new_mailing(message: Message, state: FSMContext):
    # Получаем список чатов для выбранного аккаунта
    chats = await list_chats_for_account(message.from_user.id)

    chat_buttons = []
    for chat in chats:
        chat_buttons.append([InlineKeyboardButton(text=f"{chat} ✅", callback_data=f"toggle_chat_{chat}")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=chat_buttons)
    await message.answer("Выберите чаты для рассылки:", reply_markup=keyboard)
    await state.set_state(UserStates.waiting_for_chats)

@dp.callback_query(F.data.startswith("toggle_chat_"))
async def toggle_chat(callback_query: CallbackQuery, state: FSMContext):
    chat = callback_query.data.split("_")[-1]
    # Обработка логики включения/отключения чата в рассылке
    await callback_query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=f"{chat} ❌", callback_data=f"toggle_chat_{chat}")]]
    ))

# ================== ФУНКЦИИ ДЛЯ РАССЫЛКИ ===================

@dp.message(UserStates.waiting_for_chats)
async def process_chats(message: Message, state: FSMContext):
    chats = message.text.split(',')
    await state.update_data(chats=chats)

    await message.answer("Теперь введите сообщения для рассылки (одно на строку).", parse_mode="HTML")
    await state.set_state(UserStates.waiting_for_messages)

@dp.message(UserStates.waiting_for_messages)
async def process_messages(message: Message, state: FSMContext):
    messages = message.text.split('\n')
    await state.update_data(messages=messages)

    await message.answer("Введите задержку между сообщениями в секундах.", parse_mode="HTML")
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
            (message.from_user.id, ','.join(chats), '\n'.join(messages), 'active', 0, datetime.now().isoformat())
        ).lastrowid
        conn.commit()

        await message.answer(f"Рассылка #<b>{mailing_id}</b> создана и запущена!", reply_markup=get_mailing_control_keyboard(mailing_id), parse_mode="HTML")

        asyncio.create_task(send_messages(mailing_id, chats, messages, delay))
        await state.clear()

    except ValueError:
        await message.answer("Пожалуйста, введите правильное число для задержки.", parse_mode="HTML")

async def send_messages(mailing_id, chats, messages, delay):
    cursor.execute('UPDATE mailings SET status = ? WHERE mailing_id = ?', ('active', mailing_id))
    conn.commit()

    sent_count = 0

    for chat in chats:
        # Поскольку бот не может присоединяться к каналам, предполагаем, что он уже добавлен
        try:
            for message in random.sample(messages, len(messages)):  # Случайная выборка сообщений
                await bot.send_message(chat.strip(), message)
                sent_count += 1
                cursor.execute('UPDATE mailings SET sent_messages = ? WHERE mailing_id = ?', (sent_count, mailing_id))
                conn.commit()

                await asyncio.sleep(delay)  # Задержка между сообщениями
        except Exception as e:
            logging.error(f"Ошибка при отправке сообщения в чат {chat}: {e}")

    cursor.execute('UPDATE mailings SET status = ? WHERE mailing_id = ?', ('completed', mailing_id))
    conn.commit()

# ================== УПРАВЛЕНИЕ РАССЫЛКАМИ ===================

def get_mailing_control_keyboard(mailing_id):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏸ Остановить", callback_data=f"pause_mailing_{mailing_id}")],
        [InlineKeyboardButton(text="⛔ Прервать", callback_data=f"cancel_mailing_{mailing_id}")]
    ])
    return keyboard

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

# ================== ЗАПУСК БОТА ===================

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())