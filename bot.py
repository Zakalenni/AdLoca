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

# Состояния для FSM
class AdminStates(StatesGroup):
    WAITING_TASK_NAME = State()
    WAITING_WORK_ASSIGNMENT = State()
    WAITING_WORKER_SELECTION = State()

class WorkerStates(StatesGroup):
    WAITING_WORK_SELECTION = State()
    WAITING_PROGRESS_REPORT = State()
    WAITING_QUANTITY_REPORT = State()

# База данных
tasks_db = {}  # {task_id: {name, assigned_works: {work_type: {worker_id: quantity}}}}
reports_db = {}  # {user_id: {date: [{work_type, progress, quantity, task_id}]}}
users_db = {}  # {user_id: {"name": full_name, "username": username}}

# Виды работ
WORK_TYPES = [
    "Распил доски", "Фугование", "Рейсмусование", "Распил на детали",
    "Отверстия в пласть", "Присадка отверстий", "Фрезеровка пазов",
    "Фрезеровка углов", "Шлифовка", "Подрез", "Сборка", "Дошлифовка",
    "Покраска каркасов", "Покраска ножек", "Покраска ручек",
    "Рез на коробки", "Сборка коробок", "Упаковка",
    "Фрезеровка пазов ручек", "Распил на ручки"
]

# --- Вспомогательные функции ---
async def delete_previous_message(message: types.Message):
    """Безопасное удаление предыдущего сообщения"""
    try:
        await message.delete()
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения: {e}")

def get_current_date():
    """Возвращает текущую дату в формате DD.MM.YYYY"""
    return datetime.now().strftime("%d.%m.%Y")

def get_current_weekday():
    """Возвращает текущий день недели"""
    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Саббота", "Воскресенье"]
    return days[datetime.now().weekday()]

def register_user(user: types.User):
    """Регистрирует/обновляет информацию о пользователе"""
    users_db[user.id] = {
        "name": user.full_name,
        "username": user.username
    }

def get_user_name(user_id: int) -> str:
    """Возвращает имя пользователя"""
    user = users_db.get(user_id, {})
    return user.get("name", f"User_{user_id}")

# --- Клавиатуры ---
def get_admin_main_kb():
    """Основная клавиатура администратора"""
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(
        text="📌 Поставить задачу",
        callback_data="admin_create_task"
    ))
    builder.add(types.InlineKeyboardButton(
        text="📊 Сводный отчет",
        callback_data="admin_get_report"
    ))
    builder.adjust(1)
    return builder.as_markup()

def get_worker_main_kb():
    """Основная клавиатура работника"""
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(
        text="📝 Отправить отчет",
        callback_data="worker_send_report"
    ))
    builder.add(types.InlineKeyboardButton(
        text="📋 Мои отчеты",
        callback_data="worker_my_reports"
    ))
    builder.adjust(1)
    return builder.as_markup()

def get_work_types_kb(action: str = "select"):
    """Клавиатура с видами работ"""
    builder = InlineKeyboardBuilder()
    for work in WORK_TYPES:
        builder.add(types.InlineKeyboardButton(
            text=work,
            callback_data=f"{action}_{work}"
        ))
    builder.adjust(2)
    return builder.as_markup()

def get_workers_kb():
    """Клавиатура с работниками"""
    builder = InlineKeyboardBuilder()
    for user_id, user_data in users_db.items():
        builder.add(types.InlineKeyboardButton(
            text=user_data["name"],
            callback_data=f"assign_{user_id}"
        ))
    builder.adjust(1)
    return builder.as_markup()

def get_progress_kb():
    """Клавиатура с процентами выполнения"""
    builder = ReplyKeyboardBuilder()
    for i in range(0, 101, 10):
        builder.add(types.KeyboardButton(text=f"{i}%"))
    builder.adjust(5)
    return builder.as_markup(resize_keyboard=True)

# --- Генерация отчетов ---
def generate_worker_report(user_id: int) -> str:
    """Генерирует отчет для работника"""
    if user_id not in reports_db or not reports_db[user_id]:
        return "📭 У вас пока нет отчетов"
    
    report = ["📊 <b>Ваши отчеты</b>\n"]
    for date, records in reports_db[user_id].items():
        report.append(f"\n📅 <b>{date}</b>")
        for record in records:
            task_name = tasks_db.get(record.get("task_id", ""), {}).get("name", "Общая задача")
            report.append(
                f"\n  • {task_name}: {record['work_type']}\n"
                f"    ▸ Выполнено: {record['progress']}%\n"
                f"    ▸ Количество: {record.get('quantity', 'N/A')}"
            )
    
    return "\n".join(report)

def generate_admin_report() -> str:
    """Генерирует сводный отчет для администратора"""
    if not reports_db:
        return "📭 Нет данных по выполнению работ"
    
    report = ["📊 <b>Сводный отчет по выполнению работ</b>\n"]
    
    # Отчет по задачам
    report.append("\n<b>Текущие задачи:</b>")
    for task_id, task_data in tasks_db.items():
        report.append(f"\n📌 <b>{task_data['name']}</b> (ID: {task_id})")
        for work_type, workers in task_data.get("assigned_works", {}).items():
            report.append(f"\n  🔧 {work_type}:")
            for worker_id, quantity in workers.items():
                report.append(f"    👷 {get_user_name(worker_id)}: {quantity} шт.")
    
    # Отчет по выполнению
    report.append("\n\n<b>Выполнение работ:</b>")
    for user_id, user_data in reports_db.items():
        report.append(f"\n👷 <b>{get_user_name(user_id)}</b>")
        for date, records in user_data.items():
            report.append(f"\n  📅 {date}")
            for record in records:
                task_name = tasks_db.get(record.get("task_id", ""), {}).get("name", "Общая задача")
                report.append(
                    f"    • {task_name}: {record['work_type']}\n"
                    f"      ▸ Выполнено: {record['progress']}%\n"
                    f"      ▸ Количество: {record.get('quantity', 'N/A')}"
                )
    
    return "\n".join(report)

# --- Обработчики команд ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    register_user(message.from_user)
    
    if str(message.from_user.id) == os.getenv('ADMIN_ID'):
        await message.answer(
            "👨‍💻 <b>Панель администратора</b>",
            reply_markup=get_admin_main_kb(),
            parse_mode="HTML"
        )
    else:
        await message.answer(
            "👷 <b>Панель работника</b>",
            reply_markup=get_worker_main_kb(),
            parse_mode="HTML"
        )

# --- Обработчики администратора ---
@dp.callback_query(F.data == "admin_create_task")
async def admin_create_task(callback: types.CallbackQuery, state: FSMContext):
    await delete_previous_message(callback.message)
    await callback.message.answer(
        "📝 Введите название новой задачи:",
        reply_markup=types.ReplyKeyboardRemove()
    )
    await state.set_state(AdminStates.WAITING_TASK_NAME)
    await callback.answer()

@dp.message(AdminStates.WAITING_TASK_NAME)
async def process_task_name(message: types.Message, state: FSMContext):
    task_id = str(datetime.now().timestamp())
    tasks_db[task_id] = {
        "name": message.text,
        "assigned_works": {}
    }
    await state.update_data(task_id=task_id)
    await state.set_state(AdminStates.WAITING_WORK_ASSIGNMENT)
    await message.answer(
        f"✅ Задача '{message.text}' создана\n\n"
        "Выберите вид работы для назначения:",
        reply_markup=get_work_types_kb("assign_work")
    )

@dp.callback_query(F.data.startswith("assign_work_"), AdminStates.WAITING_WORK_ASSIGNMENT)
async def select_work_for_assignment(callback: types.CallbackQuery, state: FSMContext):
    work_type = callback.data.split("_", 2)[2]
    await state.update_data(work_type=work_type)
    await delete_previous_message(callback.message)
    await callback.message.answer(
        f"Выберите работника для назначения '{work_type}':",
        reply_markup=get_workers_kb()
    )
    await state.set_state(AdminStates.WAITING_WORKER_SELECTION)
    await callback.answer()

@dp.callback_query(F.data.startswith("assign_"), AdminStates.WAITING_WORKER_SELECTION)
async def assign_worker_to_work(callback: types.CallbackQuery, state: FSMContext):
    worker_id = int(callback.data.split("_")[1])
    data = await state.get_data()
    
    task_id = data["task_id"]
    work_type = data["work_type"]
    
    if task_id not in tasks_db:
        await callback.message.answer("Ошибка: задача не найдена")
        await state.clear()
        return
    
    if "assigned_works" not in tasks_db[task_id]:
        tasks_db[task_id]["assigned_works"] = {}
    
    if work_type not in tasks_db[task_id]["assigned_works"]:
        tasks_db[task_id]["assigned_works"][work_type] = {}
    
    await callback.message.answer(
        f"Введите количество для {work_type} (целое число):",
        reply_markup=types.ReplyKeyboardRemove()
    )
    
    await state.update_data(worker_id=worker_id)
    await callback.answer()

@dp.message(AdminStates.WAITING_WORKER_SELECTION)
async def process_work_quantity(message: types.Message, state: FSMContext):
    try:
        quantity = int(message.text)
        if quantity <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Пожалуйста, введите положительное целое число")
        return
    
    data = await state.get_data()
    task_id = data["task_id"]
    work_type = data["work_type"]
    worker_id = data["worker_id"]
    
    tasks_db[task_id]["assigned_works"][work_type][worker_id] = quantity
    
    worker_name = get_user_name(worker_id)
    await message.answer(
        f"✅ Назначение добавлено:\n"
        f"👷 Работник: {worker_name}\n"
        f"🔧 Работа: {work_type}\n"
        f"🔢 Количество: {quantity}",
        reply_markup=get_admin_main_kb()
    )
    
    # Уведомляем работника
    try:
        await bot.send_message(
            chat_id=worker_id,
            text=f"📌 Вам назначена новая работа:\n\n"
                 f"📝 Задача: {tasks_db[task_id]['name']}\n"
                 f"🔧 Вид работы: {work_type}\n"
                 f"🔢 Количество: {quantity}",
            reply_markup=get_worker_main_kb()
        )
    except Exception as e:
        logger.error(f"Ошибка уведомления работника: {e}")
    
    await state.clear()

@dp.callback_query(F.data == "admin_get_report")
async def admin_get_report(callback: types.CallbackQuery):
    await delete_previous_message(callback.message)
    report = generate_admin_report()
    await callback.message.answer(report, parse_mode="HTML")
    await callback.answer()

# --- Обработчики работника ---
@dp.callback_query(F.data == "worker_send_report")
async def worker_send_report(callback: types.CallbackQuery, state: FSMContext):
    await delete_previous_message(callback.message)
    await callback.message.answer(
        "Выберите вид выполненной работы:",
        reply_markup=get_work_types_kb("report_work")
    )
    await state.set_state(WorkerStates.WAITING_WORK_SELECTION)
    await callback.answer()

@dp.callback_query(F.data.startswith("report_work_"), WorkerStates.WAITING_WORK_SELECTION)
async def select_work_for_report(callback: types.CallbackQuery, state: FSMContext):
    work_type = callback.data.split("_", 2)[2]
    await state.update_data(work_type=work_type)
    await delete_previous_message(callback.message)
    await callback.message.answer(
        f"Укажите процент выполнения для '{work_type}':",
        reply_markup=get_progress_kb()
    )
    await state.set_state(WorkerStates.WAITING_PROGRESS_REPORT)
    await callback.answer()

@dp.message(WorkerStates.WAITING_PROGRESS_REPORT)
async def process_progress_report(message: types.Message, state: FSMContext):
    try:
        progress = int(message.text.replace("%", ""))
        if not 0 <= progress <= 100:
            raise ValueError
    except ValueError:
        await message.answer("Пожалуйста, укажите процент от 0 до 100")
        return
    
    await state.update_data(progress=progress)
    await message.answer(
        "Введите количество выполненного (целое число):",
        reply_markup=types.ReplyKeyboardRemove()
    )
    await state.set_state(WorkerStates.WAITING_QUANTITY_REPORT)

@dp.message(WorkerStates.WAITING_QUANTITY_REPORT)
async def process_quantity_report(message: types.Message, state: FSMContext):
    try:
        quantity = int(message.text)
        if quantity <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Пожалуйста, введите положительное целое число")
        return
    
    data = await state.get_data()
    user_id = message.from_user.id
    current_date = get_current_date()
    
    if user_id not in reports_db:
        reports_db[user_id] = {}
    
    if current_date not in reports_db[user_id]:
        reports_db[user_id][current_date] = []
    
    # Находим задачу, к которой относится эта работа
    task_id = None
    for t_id, task in tasks_db.items():
        if data["work_type"] in task.get("assigned_works", {}):
            if user_id in task["assigned_works"][data["work_type"]]:
                task_id = t_id
                break
    
    reports_db[user_id][current_date].append({
        "work_type": data["work_type"],
        "progress": data["progress"],
        "quantity": quantity,
        "task_id": task_id
    })
    
    await message.answer(
        "✅ <b>Отчет сохранен</b>\n\n"
        f"📅 Дата: {current_date}\n"
        f"🔧 Вид работы: {data['work_type']}\n"
        f"📊 Выполнено: {data['progress']}%\n"
        f"🔢 Количество: {quantity}",
        parse_mode="HTML",
        reply_markup=get_worker_main_kb()
    )
    
    # Уведомляем администратора
    admin_id = os.getenv('ADMIN_ID')
    if admin_id:
        try:
            task_name = tasks_db.get(task_id, {}).get("name", "Общая задача") if task_id else "Общая задача"
            await bot.send_message(
                chat_id=int(admin_id),
                text=f"📌 Новый отчет от {message.from_user.full_name}\n\n"
                     f"📅 {current_date}\n"
                     f"📝 Задача: {task_name}\n"
                     f"🔧 {data['work_type']}\n"
                     f"📊 {data['progress']}%, {quantity} шт.",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка уведомления админа: {e}")
    
    await state.clear()

@dp.callback_query(F.data == "worker_my_reports")
async def worker_my_reports(callback: types.CallbackQuery):
    await delete_previous_message(callback.message)
    report = generate_worker_report(callback.from_user.id)
    await callback.message.answer(report, parse_mode="HTML")
    await callback.answer()

# Запуск бота
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
