import os
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from dotenv import load_dotenv

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Загружаем переменные окружения
load_dotenv()

# Инициализация бота
bot = Bot(token=os.getenv('BOT_TOKEN'))
dp = Dispatcher()

# Состояния для опроса
class SurveyStates(StatesGroup):
    WAITING_TASK = State()
    WAITING_WORK_TYPE = State()
    WAITING_PROGRESS = State()
    WAITING_QUANTITY = State()

class AdminStates(StatesGroup):
    WAITING_TASK_ASSIGNMENT = State()
    WAITING_WORKER_SELECTION = State()
    WAITING_USER_MANAGEMENT = State()

# База данных
reports_db = {}
tasks_db = {}
allowed_users = set()
admin_users = {int(os.getenv('ADMIN_ID'))} if os.getenv('ADMIN_ID') else set()

# Виды работ
WORK_TYPES = [
    "Распил доски", "Фугование", "Рейсмусование", "Распил на детали",
    "Отверстия в пласть", "Присадка отверстий", "Фрезеровка пазов",
    "Фрезеровка углов", "Шлифовка", "Подрез", "Сборка", "Дошлифовка",
    "Покраска каркасов", "Покраска ножек", "Покраска ручек",
    "Рез на коробки", "Сборка коробок", "Упаковка", 
    "Фрезеровка пазов ручек", "Распил на ручки"
]

# --- Клавиатуры ---
def get_user_main_kb():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="📝 Новый отчет"))
    builder.add(types.KeyboardButton(text="📊 Мои отчеты"))
    builder.add(types.KeyboardButton(text="📌 Мои задачи"))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_admin_main_kb():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="📝 Новый отчет"))
    builder.add(types.KeyboardButton(text="📊 Мои отчеты"))
    builder.add(types.KeyboardButton(text="👥 Управление пользователями"))
    builder.add(types.KeyboardButton(text="📌 Назначить задачу"))
    builder.add(types.KeyboardButton(text="📈 Сводный отчет"))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_work_types_kb():
    builder = ReplyKeyboardBuilder()
    for work_type in WORK_TYPES:
        builder.add(types.KeyboardButton(text=work_type))
    builder.adjust(3)
    return builder.as_markup(resize_keyboard=True)

def get_progress_kb():
    builder = ReplyKeyboardBuilder()
    for i in range(0, 101, 10):
        builder.add(types.KeyboardButton(text=f"{i}%"))
    builder.adjust(5)
    return builder.as_markup(resize_keyboard=True)

def get_quantity_kb():
    builder = ReplyKeyboardBuilder()
    for i in [1, 5, 10, 20, 50, 100]:
        builder.add(types.KeyboardButton(text=str(i)))
    builder.add(types.KeyboardButton(text="✏️ Другое количество"))
    builder.add(types.KeyboardButton(text="❌ Отмена"))
    builder.adjust(3)
    return builder.as_markup(resize_keyboard=True)

def get_user_management_kb():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="➕ Добавить пользователя"))
    builder.add(types.KeyboardButton(text="➖ Удалить пользователя"))
    builder.add(types.KeyboardButton(text="📋 Список пользователей"))
    builder.add(types.KeyboardButton(text="🔙 Назад"))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_cancel_kb():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="❌ Отмена"))
    return builder.as_markup(resize_keyboard=True)

# --- Основные обработчики ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in {u[0] for u in allowed_users} and user_id not in admin_users:
        await message.answer("⛔ У вас нет доступа к этому боту")
        return
    
    await state.clear()
    if user_id in admin_users:
        await message.answer(
            "🛠 <b>Панель администратора</b>\n\n"
            "Вы можете управлять пользователями и просматривать все отчеты",
            reply_markup=get_admin_main_kb(),
            parse_mode="HTML"
        )
    else:
        await message.answer(
            "🏭 <b>Система учета столярных работ</b>\n\n"
            "Используйте кнопки ниже для работы с системой",
            reply_markup=get_user_main_kb(),
            parse_mode="HTML"
        )

@dp.message(F.text == "🔙 Назад", F.from_user.id.in_(admin_users))
async def admin_back(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🛠 <b>Панель администратора</b>",
        reply_markup=get_admin_main_kb(),
        parse_mode="HTML"
    )

@dp.message(F.text == "❌ Отмена"))
async def cancel_action(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    if user_id in admin_users:
        await message.answer(
            "Действие отменено",
            reply_markup=get_admin_main_kb()
        )
    else:
        await message.answer(
            "Действие отменено",
            reply_markup=get_user_main_kb()
        )

# --- Обработчики для пользователей ---
@dp.message(F.text == "📝 Новый отчет"))
async def new_report_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in {u[0] for u in allowed_users}:
        return
    
    await state.set_state(SurveyStates.WAITING_TASK)
    await message.answer(
        "📝 Введите задачу, над которой работали:",
        reply_markup=get_cancel_kb()
    )

@dp.message(SurveyStates.WAITING_TASK)
async def process_task(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await cancel_action(message, state)
        return
    
    await state.update_data(task=message.text)
    await state.set_state(SurveyStates.WAITING_WORK_TYPE)
    await message.answer(
        "Выберите вид работы:",
        reply_markup=get_work_types_kb()
    )

@dp.message(F.text == "📊 Мои отчеты"))
async def show_my_reports(message: types.Message):
    user_id = message.from_user.id
    username = next((u[1] for u in allowed_users if u[0] == user_id), "Unknown")
    report = generate_user_report(user_id, username)
    await message.answer(report, parse_mode="HTML")

# --- Обработчики для администратора ---
@dp.message(F.text == "👥 Управление пользователями", F.from_user.id.in_(admin_users))
async def manage_users(message: types.Message):
    await message.answer(
        "👥 <b>Управление пользователями</b>",
        reply_markup=get_user_management_kb(),
        parse_mode="HTML"
    )

@dp.message(F.text == "📌 Назначить задачу", F.from_user.id.in_(admin_users))
async def assign_task(message: types.Message, state: FSMContext):
    await state.set_state(AdminStates.WAITING_TASK_ASSIGNMENT)
    await message.answer(
        "📝 Введите задачу для назначения:",
        reply_markup=get_cancel_kb()
    )

@dp.message(F.text == "📈 Сводный отчет", F.from_user.id.in_(admin_users))
async def full_report(message: types.Message):
    report = generate_admin_report()
    await message.answer(report, parse_mode="HTML")

# Запуск бота
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
