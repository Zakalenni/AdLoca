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
    WAITING_ADDITIONAL_WORK = State()

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

# --- Вспомогательные функции ---
def get_current_weekday():
    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    return days[datetime.now().weekday()]

def generate_user_report(user_id: int, username: str) -> str:
    if user_id not in reports_db or not reports_db[user_id]:
        return "📭 У вас пока нет отчетов"
    
    report = [f"📊 <b>Отчеты {username}</b>\n"]
    for date, records in reports_db[user_id].items():
        report.append(f"\n📅 <b>{date}</b>")
        for record in records:
            report.append(
                f"  • {record['work_type']}: {record['progress']}% ({record.get('quantity', 'N/A')} шт.)"
            )
    return "\n".join(report)

def generate_admin_report():
    if not reports_db:
        return "📭 Нет данных по выполнению работ"
    
    report = ["📈 <b>Сводный отчет по выполнению работ</b>\n"]
    for user_id, user_data in reports_db.items():
        username = next((u for u in allowed_users if u[0] == user_id), ("Unknown", ""))[1]
        report.append(f"\n👷 <b>{username}</b>")
        for date, records in user_data.items():
            report.append(f"\n  📅 {date}")
            for record in records:
                report.append(f"    • {record['work_type']}: {record['progress']}% ({record.get('quantity', 'N/A')} шт.)")
    
    return "\n".join(report)

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
    builder.add(types.KeyboardButton(text="Другое количество"))
    builder.adjust(3)
    return builder.as_markup(resize_keyboard=True)

def get_admin_action_kb():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="Назначить задачу"))
    builder.add(types.KeyboardButton(text="Управление пользователями"))
    builder.add(types.KeyboardButton(text="Получить сводный отчет"))
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)

def get_user_management_kb():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="Добавить пользователя"))
    builder.add(types.KeyboardButton(text="Удалить пользователя"))
    builder.add(types.KeyboardButton(text="Список пользователей"))
    builder.add(types.KeyboardButton(text="Назад"))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

async def delete_previous_message(message: types.Message):
    try:
        await message.delete()
    except Exception as e:
        logger.error(f"Ошибка удаления сообщения: {e}")

# --- Обработчики команд ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in {u[0] for u in allowed_users} and user_id not in admin_users:
        await message.answer("⛔ У вас нет доступа к этому боту")
        return
    
    await state.clear()
    await message.answer(
        "🏭 <b>Система учета столярных работ</b>\n\n"
        "Используйте команды:\n"
        "/new_report - создать отчет\n"
        "/my_reports - ваши отчеты\n"
        "/admin - панель администратора" if user_id in admin_users else "",
        parse_mode="HTML",
        reply_markup=types.ReplyKeyboardRemove()
    )

@dp.message(Command("admin"), F.from_user.id.in_(admin_users))
async def cmd_admin(message: types.Message, state: FSMContext):
    await delete_previous_message(message)
    await message.answer(
        "🛠 <b>Панель администратора</b>",
        reply_markup=get_admin_action_kb(),
        parse_mode="HTML"
    )

@dp.message(F.text == "Назначить задачу", F.from_user.id.in_(admin_users))
async def assign_task_start(message: types.Message, state: FSMContext):
    await delete_previous_message(message)
    await state.set_state(AdminStates.WAITING_TASK_ASSIGNMENT)
    await message.answer(
        "📝 Введите задачу для назначения:",
        reply_markup=types.ReplyKeyboardRemove()
    )

@dp.message(AdminStates.WAITING_TASK_ASSIGNMENT)
async def assign_task_description(message: types.Message, state: FSMContext):
    await state.update_data(task=message.text)
    await state.set_state(AdminStates.WAITING_WORKER_SELECTION)
    
    builder = InlineKeyboardBuilder()
    for user_id, username in allowed_users:
        builder.add(types.InlineKeyboardButton(
            text=username,
            callback_data=f"assign_{user_id}"
        ))
    builder.adjust(2)
    
    await message.answer(
        "👥 Выберите работника для назначения задачи:",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith("assign_"), AdminStates.WAITING_WORKER_SELECTION)
async def assign_task_final(callback: types.CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split("_")[1])
    data = await state.get_data()
    
    if user_id not in tasks_db:
        tasks_db[user_id] = []
    
    tasks_db[user_id].append({
        "task": data["task"],
        "assigned_by": callback.from_user.id,
        "date": datetime.now().strftime("%d.%m.%Y %H:%M")
    })
    
    await callback.message.edit_text(
        f"✅ Задача назначена работнику {next((u[1] for u in allowed_users if u[0] == user_id), 'Unknown')}"
    )
    await bot.send_message(
        chat_id=user_id,
        text=f"📌 <b>Вам назначена новая задача</b>\n\n{data['task']}",
        parse_mode="HTML"
    )
    await state.clear()

@dp.message(F.text == "Управление пользователями", F.from_user.id.in_(admin_users))
async def manage_users_start(message: types.Message, state: FSMContext):
    await delete_previous_message(message)
    await message.answer(
        "👥 <b>Управление пользователями</b>",
        reply_markup=get_user_management_kb(),
        parse_mode="HTML"
    )

@dp.message(F.text == "Добавить пользователя", F.from_user.id.in_(admin_users))
async def add_user_start(message: types.Message, state: FSMContext):
    await delete_previous_message(message)
    await state.set_state(AdminStates.WAITING_USER_MANAGEMENT)
    await state.update_data(action="add")
    await message.answer(
        "Введите ID пользователя и имя через пробел (например: 123456789 Иван):",
        reply_markup=types.ReplyKeyboardRemove()
    )

@dp.message(F.text == "Удалить пользователя", F.from_user.id.in_(admin_users))
async def remove_user_start(message: types.Message, state: FSMContext):
    await delete_previous_message(message)
    await state.set_state(AdminStates.WAITING_USER_MANAGEMENT)
    await state.update_data(action="remove")
    
    if not allowed_users:
        await message.answer("Нет пользователей для удаления")
        await state.clear()
        return
    
    builder = InlineKeyboardBuilder()
    for user_id, username in allowed_users:
        builder.add(types.InlineKeyboardButton(
            text=f"{username} (ID: {user_id})",
            callback_data=f"user_{user_id}"
        ))
    builder.adjust(1)
    
    await message.answer(
        "Выберите пользователя для удаления:",
        reply_markup=builder.as_markup()
    )

@dp.message(F.text == "Список пользователей", F.from_user.id.in_(admin_users))
async def list_users(message: types.Message):
    await delete_previous_message(message)
    if not allowed_users:
        await message.answer("Нет добавленных пользователей")
        return
    
    users_list = "\n".join([f"{user_id}: {username}" for user_id, username in allowed_users])
    await message.answer(f"👥 <b>Список пользователей</b>\n\n{users_list}", parse_mode="HTML")

@dp.message(F.text == "Назад", F.from_user.id.in_(admin_users))
async def admin_back(message: types.Message, state: FSMContext):
    await delete_previous_message(message)
    await state.clear()
    await message.answer(
        "🛠 <b>Панель администратора</b>",
        reply_markup=get_admin_action_kb(),
        parse_mode="HTML"
    )

@dp.message(AdminStates.WAITING_USER_MANAGEMENT)
async def process_user_management(message: types.Message, state: FSMContext):
    data = await state.get_data()
    action = data.get("action")
    
    if action == "add":
        try:
            parts = message.text.split()
            user_id = int(parts[0])
            username = " ".join(parts[1:])
            
            allowed_users.add((user_id, username))
            await message.answer(
                f"✅ Пользователь {username} (ID: {user_id}) добавлен",
                reply_markup=get_user_management_kb()
            )
        except Exception as e:
            await message.answer("Ошибка формата. Пример: 123456789 Иван")
    await state.clear()

@dp.callback_query(F.data.startswith("user_"), AdminStates.WAITING_USER_MANAGEMENT)
async def remove_user_final(callback: types.CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split("_")[1])
    user_to_remove = next((u for u in allowed_users if u[0] == user_id), None)
    
    if user_to_remove:
        allowed_users.remove(user_to_remove)
        await callback.message.edit_text(
            f"✅ Пользователь {user_to_remove[1]} удален"
        )
    else:
        await callback.message.edit_text("Пользователь не найден")
    
    await state.clear()

@dp.message(F.text == "Получить сводный отчет", F.from_user.id.in_(admin_users))
async def get_full_report(message: types.Message):
    await delete_previous_message(message)
    report = generate_admin_report()
    await message.answer(report, parse_mode="HTML")

@dp.message(Command("new_report"))
async def cmd_new_report(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in {u[0] for u in allowed_users}:
        await message.answer("⛔ У вас нет доступа к этой команде")
        return
    
    await delete_previous_message(message)
    await state.set_state(SurveyStates.WAITING_TASK)
    
    # Показываем назначенные задачи
    assigned_tasks = tasks_db.get(user_id, [])
    if assigned_tasks:
        tasks_text = "\n".join([f"• {task['task']} ({task['date']})" for task in assigned_tasks])
        await message.answer(
            f"📌 <b>Ваши назначенные задачи</b>\n\n{tasks_text}",
            parse_mode="HTML"
        )
    
    await message.answer(
        "📝 Введите задачу, над которой работали:",
        reply_markup=types.ReplyKeyboardRemove()
    )

@dp.message(SurveyStates.WAITING_TASK)
async def process_task(message: types.Message, state: FSMContext):
    await delete_previous_message(message)
    await state.update_data(task=message.text)
    await state.set_state(SurveyStates.WAITING_WORK_TYPE)
    await message.answer(
        "Выберите вид работы:",
        reply_markup=get_work_types_kb()
    )

@dp.message(SurveyStates.WAITING_WORK_TYPE)
async def process_work_type(message: types.Message, state: FSMContext):
    await delete_previous_message(message)
    if message.text not in WORK_TYPES:
        await message.answer("Пожалуйста, выберите вид работы из предложенных")
        return
    
    await state.update_data(work_type=message.text)
    await state.set_state(SurveyStates.WAITING_PROGRESS)
    await message.answer(
        "Укажите процент выполнения:",
        reply_markup=get_progress_kb()
    )

@dp.message(SurveyStates.WAITING_PROGRESS)
async def process_progress(message: types.Message, state: FSMContext):
    await delete_previous_message(message)
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
    await delete_previous_message(message)
    if message.text == "Другое количество":
        await message.answer("Введите количество вручную:")
        return
    
    try:
        quantity = int(message.text)
        if quantity <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Пожалуйста, укажите положительное число")
        return
    
    await state.update_data(quantity=quantity)
    await proceed_to_save(message, state)

async def proceed_to_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    current_date = datetime.now().strftime("%d.%m.%Y")
    weekday = get_current_weekday()
    user_id = message.from_user.id
    username = next((u[1] for u in allowed_users if u[0] == user_id), "Unknown")
    
    # Сохраняем отчет
    if user_id not in reports_db:
        reports_db[user_id] = {}
    
    if current_date not in reports_db[user_id]:
        reports_db[user_id][current_date] = []
    
    reports_db[user_id][current_date].append({
        "task": data["task"],
        "work_type": data["work_type"],
        "progress": data["progress"],
        "quantity": data.get("quantity", 0),
        "weekday": weekday
    })
    
    # Формируем сообщение о сохранении
    report_msg = (
        "✅ <b>Отчет сохранен</b>\n\n"
        f"📅 День: {weekday}, {current_date}\n"
        f"📌 Задача: {data['task']}\n"
        f"🔧 Вид работы: {data['work_type']}\n"
        f"📊 Выполнено: {data['progress']}%\n"
        f"🔢 Количество: {data.get('quantity', 'N/A')} шт."
    )
    
    await message.answer(
        report_msg,
        parse_mode="HTML",
        reply_markup=types.ReplyKeyboardRemove()
    )
    
    # Уведомление администратора
    admin_msg = (
        f"📌 Новый отчет от {username}\n\n"
        f"📅 {weekday}, {current_date}\n"
        f"🔧 {data['work_type']}: {data['progress']}% ({data.get('quantity', 'N/A')} шт.)\n"
        f"📝 Задача: {data['task']}"
    )
    
    for admin_id in admin_users:
        try:
            await bot.send_message(admin_id, admin_msg, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления админу {admin_id}: {e}")
    
    await state.clear()

@dp.message(Command("my_reports"))
async def cmd_my_reports(message: types.Message):
    user_id = message.from_user.id
    username = next((u[1] for u in allowed_users if u[0] == user_id), "Unknown")
    report = generate_user_report(user_id, username)
    await message.answer(report, parse_mode="HTML")

# Запуск бота
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
