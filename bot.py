import os
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
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

# Состояния для FSM
class AdminStates(StatesGroup):
    WAITING_NEW_TASK = State()
    WAITING_USER_SELECTION = State()
    WAITING_WORK_ASSIGNMENT = State()
    WAITING_QUANTITY = State()

class UserStates(StatesGroup):
    WAITING_PROGRESS_REPORT = State()
    WAITING_QUANTITY_REPORT = State()
    WAITING_ADDITIONAL_WORK = State()

# Базы данных
reports_db = {}
tasks_db = {}
allowed_users = set()
work_types = [
    "Распил доски", "Фугование", "Рейсмусование", "Распил на детали",
    "Отверстия в пласть", "Присадка отверстий", "Фрезеровка пазов",
    "Фрезеровка углов", "Шлифовка", "Подрез", "Сборка", "Дошлифовка",
    "Покраска каркасов", "Покраска ножек", "Покраска ручек",
    "Рез на коробки", "Сборка коробок", "Упаковка",
    "Фрезеровка пазов ручек", "Распил на ручки"
]

# Инициализация администратора
if os.getenv('ADMIN_ID'):
    allowed_users.add(int(os.getenv('ADMIN_ID')))

# --- Вспомогательные функции ---
def get_current_date():
    return datetime.now().strftime("%d.%m.%Y")

def get_weekday():
    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    return days[datetime.now().weekday()]

def get_work_type_kb():
    builder = ReplyKeyboardBuilder()
    for work in work_types:
        builder.add(types.KeyboardButton(text=work))
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
    for i in [1, 2, 5, 10, 20, 50, 100]:
        builder.add(types.KeyboardButton(text=str(i)))
    builder.add(types.KeyboardButton(text="Другое количество"))
    builder.adjust(3)
    return builder.as_markup(resize_keyboard=True)

def get_admin_kb():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="/new_task"))
    builder.add(types.KeyboardButton(text="/admin_report"))
    builder.add(types.KeyboardButton(text="/manage_users"))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_user_kb():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="/new_report"))
    builder.add(types.KeyboardButton(text="/my_reports"))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

async def delete_previous_message(message: types.Message):
    try:
        await message.delete()
    except:
        pass

# --- Обработчики команд ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    
    if user_id in allowed_users:
        await message.answer(
            "👨‍💻 <b>Режим администратора</b>",
            reply_markup=get_admin_kb(),
            parse_mode="HTML"
        )
    else:
        await message.answer(
            "👷 <b>Система учета работ</b>\n\n"
            "Используйте /new_report для отправки отчета",
            reply_markup=get_user_kb(),
            parse_mode="HTML"
        )

# --- Административные команды ---
@dp.message(Command("new_task"), F.from_user.id.in_(allowed_users))
async def cmd_new_task(message: types.Message, state: FSMContext):
    await delete_previous_message(message)
    await state.set_state(AdminStates.WAITING_NEW_TASK)
    await message.answer(
        "📝 Введите название новой задачи:",
        reply_markup=types.ReplyKeyboardRemove()
    )

@dp.message(AdminStates.WAITING_NEW_TASK)
async def process_new_task(message: types.Message, state: FSMContext):
    await state.update_data(task_name=message.text)
    await state.set_state(AdminStates.WAITING_WORK_ASSIGNMENT)
    await message.answer(
        "Выберите вид работы:",
        reply_markup=get_work_type_kb()
    )

@dp.message(AdminStates.WAITING_WORK_ASSIGNMENT)
async def process_work_assignment(message: types.Message, state: FSMContext):
    if message.text not in work_types:
        await message.answer("Пожалуйста, выберите вид работы из предложенных")
        return
    
    await state.update_data(work_type=message.text)
    await state.set_state(AdminStates.WAITING_QUANTITY)
    await message.answer(
        "Укажите количество:",
        reply_markup=get_quantity_kb()
    )

@dp.message(AdminStates.WAITING_QUANTITY)
async def process_quantity(message: types.Message, state: FSMContext):
    try:
        quantity = int(message.text)
    except:
        await message.answer("Пожалуйста, введите число")
        return
    
    data = await state.get_data()
    task_name = data['task_name']
    work_type = data['work_type']
    
    if task_name not in tasks_db:
        tasks_db[task_name] = {}
    
    tasks_db[task_name][work_type] = quantity
    
    await state.clear()
    await message.answer(
        f"✅ Задача добавлена:\n\n"
        f"<b>{task_name}</b>\n"
        f"🔧 {work_type}\n"
        f"📦 Количество: {quantity}",
        reply_markup=get_admin_kb(),
        parse_mode="HTML"
    )

@dp.message(Command("admin_report"), F.from_user.id.in_(allowed_users))
async def cmd_admin_report(message: types.Message):
    report = generate_admin_report()
    await delete_previous_message(message)
    await message.answer(
        report,
        parse_mode="HTML",
        reply_markup=get_admin_kb()
    )

@dp.message(Command("manage_users"), F.from_user.id.in_(allowed_users))
async def cmd_manage_users(message: types.Message, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(
        text="Добавить пользователя",
        callback_data="add_user"
    ))
    builder.add(types.InlineKeyboardButton(
        text="Удалить пользователя",
        callback_data="remove_user"
    ))
    await message.answer(
        "Управление пользователями:",
        reply_markup=builder.as_markup()
    )

# --- Пользовательские команды ---
@dp.message(Command("new_report"))
async def cmd_new_report(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in allowed_users:
        await message.answer("У вас нет доступа к этой команде")
        return
    
    await delete_previous_message(message)
    await state.set_state(UserStates.WAITING_PROGRESS_REPORT)
    await message.answer(
        "Выберите вид работы:",
        reply_markup=get_work_type_kb()
    )

@dp.message(Command("my_reports"))
async def cmd_my_reports(message: types.Message):
    user_id = message.from_user.id
    report = generate_user_report(user_id)
    await delete_previous_message(message)
    await message.answer(
        f"📊 <b>Ваши отчеты</b>\n\n{report}",
        parse_mode="HTML",
        reply_markup=get_user_kb()
    )

# --- Генерация отчетов ---
def generate_admin_report():
    if not reports_db:
        return "📊 <b>Сводный отчет</b>\n\nНет данных о выполненных работах"
    
    report = ["📊 <b>Сводный отчет</b>\n"]
    current_date = get_current_date()
    
    for user_id, user_data in reports_db.items():
        if current_date in user_data:
            report.append(f"\n👤 <b>{user_data.get('name', f'Пользователь {user_id}')}</b>")
            for record in user_data[current_date]:
                report.append(
                    f"  • {record['work_type']}: {record['progress']}% "
                    f"({record.get('quantity', 'N/A')} шт.)"
                )
    
    return "\n".join(report)

def generate_user_report(user_id):
    if user_id not in reports_db or not reports_db[user_id]:
        return "У вас пока нет отчетов"
    
    report = ["📊 <b>Ваши отчеты</b>\n"]
    for date, records in reports_db[user_id].items():
        if date == "name":
            continue
        report.append(f"\n📅 {date}")
        for record in records:
            report.append(
                f"  • {record['work_type']}: {record['progress']}% "
                f"({record.get('quantity', 'N/A')} шт.)"
            )
    
    return "\n".join(report)

# --- Обработчики состояний пользователя ---
@dp.message(UserStates.WAITING_PROGRESS_REPORT)
async def process_work_type_report(message: types.Message, state: FSMContext):
    if message.text not in work_types:
        await message.answer("Пожалуйста, выберите вид работы из предложенных")
        return
    
    await state.update_data(work_type=message.text)
    await state.set_state(UserStates.WAITING_QUANTITY_REPORT)
    await message.answer(
        "Укажите количество выполненного:",
        reply_markup=get_quantity_kb()
    )

@dp.message(UserStates.WAITING_QUANTITY_REPORT)
async def process_quantity_report(message: types.Message, state: FSMContext):
    try:
        quantity = int(message.text)
    except:
        await message.answer("Пожалуйста, введите число")
        return
    
    await state.update_data(quantity=quantity)
    await state.set_state(UserStates.WAITING_PROGRESS_REPORT)
    await message.answer(
        "Укажите процент выполнения:",
        reply_markup=get_progress_kb()
    )

# Запуск бота
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
