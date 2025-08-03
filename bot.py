import os
import logging
from datetime import datetime, timedelta
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
    ADMIN_ADD_TASK = State()
    ADMIN_ADD_WORKERS = State()
    ADMIN_MANAGE_USERS = State()

# Базы данных
reports_db = {}
tasks_db = {}
allowed_users = set()
user_names = {}

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
def get_current_date():
    return datetime.now().strftime("%d.%m.%Y")

def get_weekday():
    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    return days[datetime.now().weekday()]

async def delete_previous_message(chat_id: int, message_id: int):
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception as e:
        logger.error(f"Ошибка удаления сообщения: {e}")

def generate_user_report(user_id: int):
    if user_id not in reports_db:
        return "Отчетов пока нет"
    
    report = []
    for date, records in reports_db[user_id].items():
        report.append(f"📅 <b>{date}</b>")
        for record in records:
            report.append(
                f"  • {record['work_type']}: {record['progress']}% ({record.get('quantity', 'N/A')} шт)"
            )
    return "\n".join(report)

def generate_admin_report():
    if not reports_db:
        return "Нет данных по выполнению работ"
    
    report = ["📊 <b>Сводный отчет</b>\n"]
    for user_id, user_data in reports_db.items():
        name = user_names.get(user_id, f"ID:{user_id}")
        report.append(f"\n👤 <b>{name}</b>")
        for date, records in user_data.items():
            report.append(f"\n  📅 {date}")
            for record in records:
                report.append(f"    • {record['work_type']}: {record['progress']}% ({record.get('quantity', 'N/A')} шт)")
    
    return "\n".join(report)

def generate_tasks_report():
    if not tasks_db:
        return "Нет активных задач"
    
    report = ["📌 <b>Активные задачи</b>\n"]
    for task_id, task in tasks_db.items():
        report.append(f"\n🔹 <b>Задача {task_id}</b>: {task['description']}")
        for work_type, details in task['works'].items():
            report.append(f"  • {work_type}: {details['assigned']} из {details['total']}")
    return "\n".join(report)

# --- Клавиатуры ---
def get_main_kb(user_id: int):
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="📝 Новый отчет"))
    builder.add(types.KeyboardButton(text="📊 Мои отчеты"))
    if str(user_id) == os.getenv('ADMIN_ID'):
        builder.add(types.KeyboardButton(text="👨‍💼 Администрирование"))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_admin_kb():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="📌 Поставить задачу"))
    builder.add(types.KeyboardButton(text="📊 Сводный отчет"))
    builder.add(types.KeyboardButton(text="👥 Управление пользователями"))
    builder.add(types.KeyboardButton(text="📋 Список задач"))
    builder.add(types.KeyboardButton(text="🔙 Главное меню"))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_work_types_kb():
    builder = ReplyKeyboardBuilder()
    for work in WORK_TYPES:
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
    for i in [1, 5, 10, 20, 50, 100]:
        builder.add(types.KeyboardButton(text=str(i)))
    builder.add(types.KeyboardButton(text="Другое количество"))
    builder.adjust(3)
    return builder.as_markup(resize_keyboard=True)

def get_users_kb():
    builder = InlineKeyboardBuilder()
    for user_id, name in user_names.items():
        builder.add(types.InlineKeyboardButton(
            text=f"{'✅' if user_id in allowed_users else '❌'} {name}",
            callback_data=f"toggle_user_{user_id}"
        ))
    builder.adjust(1)
    return builder.as_markup()

# --- Обработчики команд ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    user_names[user_id] = message.from_user.full_name
    
    await message.answer(
        "🏭 <b>Система учета столярных работ</b>\n\n"
        "Выберите действие:",
        reply_markup=get_main_kb(user_id),
        parse_mode="HTML"
    )
    await delete_previous_message(message.chat.id, message.message_id)

@dp.message(F.text == "🔙 Главное меню")
async def cmd_main_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await cmd_start(message, state)

@dp.message(F.text == "📝 Новый отчет")
async def cmd_new_report(message: types.Message, state: FSMContext):
    if message.from_user.id not in allowed_users and str(message.from_user.id) != os.getenv('ADMIN_ID'):
        await message.answer("❌ У вас нет доступа к этой функции")
        return
    
    await state.set_state(SurveyStates.WAITING_WORK_TYPE)
    await message.answer(
        "Выберите вид работы:",
        reply_markup=get_work_types_kb()
    )
    await delete_previous_message(message.chat.id, message.message_id)

@dp.message(F.text == "📊 Мои отчеты")
async def cmd_my_reports(message: types.Message):
    report = generate_user_report(message.from_user.id)
    await message.answer(
        f"📊 <b>Ваши отчеты</b>\n\n{report}",
        parse_mode="HTML"
    )
    await delete_previous_message(message.chat.id, message.message_id)

@dp.message(F.text == "👨‍💼 Администрирование")
async def cmd_admin_panel(message: types.Message):
    if str(message.from_user.id) != os.getenv('ADMIN_ID'):
        await message.answer("❌ Доступ запрещен")
        return
    
    await message.answer(
        "Панель администратора:",
        reply_markup=get_admin_kb()
    )
    await delete_previous_message(message.chat.id, message.message_id)

@dp.message(F.text == "📌 Поставить задачу")
async def cmd_add_task(message: types.Message, state: FSMContext):
    if str(message.from_user.id) != os.getenv('ADMIN_ID'):
        await message.answer("❌ Доступ запрещен")
        return
    
    await state.set_state(SurveyStates.ADMIN_ADD_TASK)
    await message.answer(
        "Введите описание задачи:",
        reply_markup=types.ReplyKeyboardRemove()
    )
    await delete_previous_message(message.chat.id, message.message_id)

@dp.message(F.text == "📊 Сводный отчет")
async def cmd_full_report(message: types.Message):
    if str(message.from_user.id) != os.getenv('ADMIN_ID'):
        await message.answer("❌ Доступ запрещен")
        return
    
    report = generate_admin_report()
    await message.answer(report, parse_mode="HTML")
    await delete_previous_message(message.chat.id, message.message_id)

@dp.message(F.text == "👥 Управление пользователями")
async def cmd_manage_users(message: types.Message, state: FSMContext):
    if str(message.from_user.id) != os.getenv('ADMIN_ID'):
        await message.answer("❌ Доступ запрещен")
        return
    
    await state.set_state(SurveyStates.ADMIN_MANAGE_USERS)
    await message.answer(
        "Управление пользователями:",
        reply_markup=get_users_kb()
    )
    await delete_previous_message(message.chat.id, message.message_id)

@dp.message(F.text == "📋 Список задач")
async def cmd_tasks_list(message: types.Message):
    if str(message.from_user.id) != os.getenv('ADMIN_ID'):
        await message.answer("❌ Доступ запрещен")
        return
    
    report = generate_tasks_report()
    await message.answer(report, parse_mode="HTML")
    await delete_previous_message(message.chat.id, message.message_id)

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
            await message.answer("Введите количество вручную:", reply_markup=types.ReplyKeyboardRemove())
            return
        
        quantity = int(message.text)
        if quantity <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Пожалуйста, укажите корректное количество")
        return
    
    data = await state.get_data()
    current_date = get_current_date()
    weekday = get_weekday()
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
        "weekday": weekday,
        "timestamp": datetime.now().isoformat()
    })
    
    # Обновляем задачу (если есть)
    for task_id, task in tasks_db.items():
        if data["work_type"] in task["works"]:
            task["works"][data["work_type"]]["assigned"] += quantity
    
    await state.clear()
    await message.answer(
        "✅ <b>Отчет сохранен</b>\n\n"
        f"📅 День: {weekday}, {current_date}\n"
        f"🔧 Вид работы: {data['work_type']}\n"
        f"📊 Выполнено: {data['progress']}%\n"
        f"🔢 Количество: {quantity} шт",
        parse_mode="HTML",
        reply_markup=get_main_kb(user_id)
    )
    
    # Уведомление администратору
    admin_id = os.getenv('ADMIN_ID')
    if admin_id and str(user_id) != admin_id:
        try:
            name = user_names.get(user_id, f"ID:{user_id}")
            await bot.send_message(
                chat_id=int(admin_id),
                text=f"📌 Новый отчет от {name}\n\n"
                     f"📅 {weekday}, {current_date}\n"
                     f"🔧 {data['work_type']}: {data['progress']}% ({quantity} шт)",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления админу: {e}")

@dp.message(SurveyStates.ADMIN_ADD_TASK)
async def process_task_description(message: types.Message, state: FSMContext):
    task_id = len(tasks_db) + 1
    tasks_db[task_id] = {
        "description": message.text,
        "works": {},
        "created": datetime.now().isoformat()
    }
    
    await state.update_data(task_id=task_id)
    await state.set_state(SurveyStates.ADMIN_ADD_WORKERS)
    await message.answer(
        "Теперь добавьте виды работ для этой задачи.\n"
        "Отправьте в формате:\n"
        "<b>Вид работы: количество</b>\n\n"
        "Например:\n"
        "<code>Распил доски: 10</code>\n\n"
        "Когда закончите, отправьте <b>Готово</b>",
        parse_mode="HTML"
    )

@dp.message(SurveyStates.ADMIN_ADD_WORKERS)
async def process_task_works(message: types.Message, state: FSMContext):
    if message.text.lower() == "готово":
        data = await state.get_data()
        task_id = data["task_id"]
        await state.clear()
        await message.answer(
            f"✅ Задача #{task_id} создана!\n\n"
            f"{generate_tasks_report()}",
            parse_mode="HTML",
            reply_markup=get_admin_kb()
        )
        return
    
    try:
        work_type, quantity = message.text.split(":")
        work_type = work_type.strip()
        quantity = int(quantity.strip())
        
        if work_type not in WORK_TYPES:
            await message.answer(f"Неизвестный вид работы. Доступные: {', '.join(WORK_TYPES)}")
            return
        
        data = await state.get_data()
        task_id = data["task_id"]
        
        if "works" not in tasks_db[task_id]:
            tasks_db[task_id]["works"] = {}
        
        tasks_db[task_id]["works"][work_type] = {
            "total": quantity,
            "assigned": 0
        }
        
        await message.answer(f"Добавлено: {work_type} - {quantity} шт\nПродолжайте или отправьте 'Готово'")
    except Exception as e:
        logger.error(f"Ошибка обработки работы: {e}")
        await message.answer("Неверный формат. Используйте: 'Вид работы: количество'")

@dp.callback_query(F.data.startswith("toggle_user_"))
async def toggle_user(callback: types.CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split("_")[2])
    if user_id in allowed_users:
        allowed_users.remove(user_id)
    else:
        allowed_users.add(user_id)
    
    await callback.message.edit_reply_markup(reply_markup=get_users_kb())
    await callback.answer()

# Запуск бота
async def main():
    # Добавляем администратора в разрешенные пользователи
    admin_id = os.getenv('ADMIN_ID')
    if admin_id:
        allowed_users.add(int(admin_id))
    
    # Автоматическая очистка старых отчетов (старше 30 дней)
    for user_id, user_data in reports_db.items():
        for date in list(user_data.keys()):
            report_date = datetime.strptime(date, "%d.%m.%Y")
            if datetime.now() - report_date > timedelta(days=30):
                del user_data[date]
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
