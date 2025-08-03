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

# Состояния
class SurveyStates(StatesGroup):
    WAITING_TASK = State()
    WAITING_WORK_TYPE = State()
    WAITING_PROGRESS = State()
    WAITING_QUANTITY = State()
    WAITING_MORE_WORK = State()

class AdminStates(StatesGroup):
    WAITING_TASK_ASSIGNMENT = State()

# База данных
reports_db = {}
tasks_db = {}
user_tasks = {}

# Виды работ для мебельного производства
WORK_TYPES = [
    "Распил доски",
    "Фугование",
    "Рейсмусование",
    "Распил на детали",
    "Отверстия в пласть",
    "Присадка отверстий",
    "Фрезеровка пазов",
    "Фрезеровка углов",
    "Шлифовка",
    "Подрез",
    "Сборка",
    "Дошлифовка",
    "Покраска каркасов",
    "Покраска ножек",
    "Покраска ручек",
    "Рез на коробки",
    "Сборка коробок",
    "Упаковка",
    "Фрезеровка пазов ручек",
    "Распил на ручки"
]

# --- Вспомогательные функции ---
async def delete_previous_message(message: types.Message):
    """Безопасное удаление предыдущего сообщения"""
    try:
        await message.delete()
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения: {e}")

def get_current_date():
    """Возвращает текущую дату в формате ДД.ММ.ГГГГ"""
    return datetime.now().strftime("%d.%m.%Y")

def generate_user_report(user_id: int):
    """Генерирует отчет по пользователю"""
    if user_id not in reports_db or not reports_db[user_id]:
        return "📭 У вас пока нет отчетов"
    
    report = ["📊 <b>Ваши отчеты</b>\n"]
    for date, records in reports_db[user_id].items():
        report.append(f"\n📅 <b>{date}</b>")
        for i, record in enumerate(records, 1):
            report.append(
                f"{i}. {record['work_type']}: "
                f"{record['progress']}% ({record['quantity']} шт.)"
            )
    return "\n".join(report)

def generate_admin_report():
    """Генерирует сводный отчет для администратора"""
    if not reports_db:
        return "📭 Нет данных по выполнению работ"
    
    report = ["📈 <b>Сводный отчет по выполнению работ</b>\n"]
    
    for user_id, user_data in reports_db.items():
        report.append(f"\n👤 <b>Пользователь ID: {user_id}</b>")
        for date, records in user_data.items():
            report.append(f"\n  📅 {date}")
            for record in records:
                report.append(
                    f"    • {record['work_type']}: "
                    f"{record['progress']}% ({record['quantity']} шт.)"
                )
    
    return "\n".join(report)

def generate_tasks_report():
    """Генерирует отчет по поставленным задачам"""
    if not tasks_db:
        return "📭 Нет активных задач"
    
    report = ["📋 <b>Текущие задачи</b>\n"]
    for date, tasks in tasks_db.items():
        report.append(f"\n📅 {date}")
        for task in tasks:
            report.append(f"\n  • {task['description']}")
            if task['assigned_to']:
                assigned = ", ".join(str(uid) for uid in task['assigned_to'])
                report.append(f"    👥 Назначено: {assigned}")
    return "\n".join(report)

# --- Клавиатуры ---
def get_main_menu_kb():
    """Основное меню"""
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="📝 Новый отчет"))
    builder.add(types.KeyboardButton(text="📊 Мои отчеты"))
    builder.add(types.KeyboardButton(text="📋 Текущие задачи"))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_work_types_kb():
    """Клавиатура с видами работ"""
    builder = ReplyKeyboardBuilder()
    for work_type in WORK_TYPES:
        builder.add(types.KeyboardButton(text=work_type))
    builder.adjust(3)
    return builder.as_markup(resize_keyboard=True)

def get_progress_kb():
    """Клавиатура с процентами выполнения"""
    builder = ReplyKeyboardBuilder()
    for i in range(0, 101, 10):
        builder.add(types.KeyboardButton(text=f"{i}%"))
    builder.adjust(5)
    return builder.as_markup(resize_keyboard=True)

def get_quantity_kb():
    """Клавиатура с количеством"""
    builder = ReplyKeyboardBuilder()
    for i in [1, 2, 5, 10, 20, 50]:
        builder.add(types.KeyboardButton(text=f"{i} шт."))
    builder.add(types.KeyboardButton(text="Другое количество"))
    builder.adjust(3)
    return builder.as_markup(resize_keyboard=True)

def get_more_work_kb():
    """Клавиатура для добавления еще работ"""
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="✅ Завершить отчет"))
    builder.add(types.KeyboardButton(text="➕ Добавить еще работу"))
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)

# --- Обработчики команд ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🏭 <b>Система учета работ мебельного производства</b>\n\n"
        "Выберите действие:",
        reply_markup=get_main_menu_kb(),
        parse_mode="HTML"
    )

@dp.message(F.text == "📝 Новый отчет")
async def cmd_new_report(message: types.Message, state: FSMContext):
    await delete_previous_message(message)
    await state.set_state(SurveyStates.WAITING_WORK_TYPE)
    await message.answer(
        "Выберите вид выполненной работы:",
        reply_markup=get_work_types_kb()
    )

@dp.message(F.text == "📊 Мои отчеты")
async def cmd_my_reports(message: types.Message):
    await delete_previous_message(message)
    report = generate_user_report(message.from_user.id)
    await message.answer(report, parse_mode="HTML")

@dp.message(F.text == "📋 Текущие задачи")
async def cmd_current_tasks(message: types.Message):
    await delete_previous_message(message)
    report = generate_tasks_report()
    await message.answer(report, parse_mode="HTML")

@dp.message(Command("admin_report"), F.from_user.id == int(os.getenv('ADMIN_ID')))
async def cmd_admin_report(message: types.Message):
    await delete_previous_message(message)
    report = generate_admin_report()
    await message.answer(report, parse_mode="HTML")

@dp.message(Command("assign_task"), F.from_user.id == int(os.getenv('ADMIN_ID')))
async def cmd_assign_task(message: types.Message, state: FSMContext):
    await delete_previous_message(message)
    await state.set_state(AdminStates.WAITING_TASK_ASSIGNMENT)
    await message.answer(
        "📌 Введите задачу для постановки рабочим:",
        reply_markup=types.ReplyKeyboardRemove()
    )

# --- Обработчики состояний ---
@dp.message(SurveyStates.WAITING_WORK_TYPE)
async def process_work_type(message: types.Message, state: FSMContext):
    if message.text not in WORK_TYPES:
        await message.answer("Пожалуйста, выберите вид работы из списка")
        return
    
    await state.update_data(work_type=message.text)
    await state.set_state(SurveyStates.WAITING_PROGRESS)
    await message.answer(
        "Укажите процент выполнения:",
        reply_markup=get_progress_kb()
    )

@dp.message(SurveyStates.WAITING_PROGRESS)
async def process_progress(message: types.Message, state: FSMContext):
    try:
        progress = int(message.text.replace("%", ""))
        if not 0 <= progress <= 100:
            raise ValueError
    except ValueError:
        await message.answer("Пожалуйста, укажите процент от 0 до 100")
        return
    
    await state.update_data(progress=progress)
    await state.set_state(SurveyStates.WAITING_QUANTITY)
    await message.answer(
        "Укажите количество выполненных единиц:",
        reply_markup=get_quantity_kb()
    )

@dp.message(SurveyStates.WAITING_QUANTITY)
async def process_quantity(message: types.Message, state: FSMContext):
    try:
        if message.text == "Другое количество":
            await message.answer(
                "Введите количество вручную (число):",
                reply_markup=types.ReplyKeyboardRemove()
            )
            return
        
        quantity = int(message.text.split()[0])
    except ValueError:
        await message.answer("Пожалуйста, укажите корректное количество")
        return
    
    await state.update_data(quantity=quantity)
    data = await state.get_data()
    
    current_date = get_current_date()
    user_id = message.from_user.id
    
    # Сохраняем отчет
    if user_id not in reports_db:
        reports_db[user_id] = {}
    
    if current_date not in reports_db[user_id]:
        reports_db[user_id][current_date] = []
    
    reports_db[user_id][current_date].append({
        "work_type": data["work_type"],
        "progress": data["progress"],
        "quantity": quantity,
        "timestamp": datetime.now().isoformat()
    })
    
    # Обновляем назначенные задачи
    for date, tasks in tasks_db.items():
        for task in tasks:
            if user_id in task['assigned_to'] and data["work_type"] in task['description']:
                task['completed_by'] = task.get('completed_by', [])
                task['completed_by'].append(user_id)
    
    await state.set_state(SurveyStates.WAITING_MORE_WORK)
    await message.answer(
        "✅ Работа добавлена в отчет\n\n"
        f"🔧 {data['work_type']}\n"
        f"📈 {data['progress']}%\n"
        f"🔢 {quantity} шт.",
        reply_markup=get_more_work_kb()
    )

@dp.message(SurveyStates.WAITING_QUANTITY, F.text.regexp(r'^\d+$'))
async def process_custom_quantity(message: types.Message, state: FSMContext):
    await process_quantity(message, state)

@dp.message(SurveyStates.WAITING_MORE_WORK, F.text == "➕ Добавить еще работу")
async def add_more_work(message: types.Message, state: FSMContext):
    await state.set_state(SurveyStates.WAITING_WORK_TYPE)
    await message.answer(
        "Выберите вид выполненной работы:",
        reply_markup=get_work_types_kb()
    )

@dp.message(SurveyStates.WAITING_MORE_WORK, F.text == "✅ Завершить отчет")
async def finish_report(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "📋 Отчет сохранен. Спасибо за работу!",
        reply_markup=get_main_menu_kb()
    )
    
    # Отправляем уведомление администратору
    admin_id = os.getenv('ADMIN_ID')
    if admin_id:
        try:
            user_report = generate_user_report(message.from_user.id)
            await bot.send_message(
                chat_id=int(admin_id),
                text=f"📌 Новый отчет от пользователя {message.from_user.full_name} (ID: {message.from_user.id})\n\n{user_report}",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления админу: {e}")

@dp.message(AdminStates.WAITING_TASK_ASSIGNMENT)
async def process_task_assignment(message: types.Message, state: FSMContext):
    current_date = get_current_date()
    task = {
        "description": message.text,
        "assigned_to": [],
        "created_at": datetime.now().isoformat()
    }
    
    if current_date not in tasks_db:
        tasks_db[current_date] = []
    
    tasks_db[current_date].append(task)
    await state.clear()
    await message.answer(
        "✅ Задача успешно добавлена!",
        reply_markup=get_main_menu_kb()
    )

# Запуск бота
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
