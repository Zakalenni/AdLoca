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

# База данных для хранения отчетов
reports_db = {}

# --- Вспомогательные функции ---
def get_current_weekday():
    """Возвращает текущий день недели"""
    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    return days[datetime.now().weekday()]

def generate_report(user_id: int) -> str:
    """Генерирует отчет по пользователю"""
    if user_id not in reports_db or not reports_db[user_id]:
        return "Отчетов пока нет"
    
    report = []
    for date, records in reports_db[user_id].items():
        report.append(f"📅 <b>{date}</b>")
        for record in records:
            report.append(
                f"  • {record['work_type']}: {record['progress']}%"
            )
        report.append("")
    
    return "\n".join(report)

def generate_admin_report():
    """Генерирует сводный отчет для администратора"""
    if not reports_db:
        return "Нет данных по выполнению работ"
    
    report = ["📊 <b>Сводный отчет по выполнению работ</b>\n"]
    
    for user_id, user_data in reports_db.items():
        report.append(f"\n👤 <b>Пользователь ID: {user_id}</b>")
        for date, records in user_data.items():
            report.append(f"\n  📅 {date}")
            for record in records:
                report.append(f"    • {record['work_type']}: {record['progress']}%")
    
    return "\n".join(report)

# --- Клавиатуры ---
def get_work_types_kb():
    """Клавиатура с типами работ"""
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="Разработка"))
    builder.add(types.KeyboardButton(text="Тестирование"))
    builder.add(types.KeyboardButton(text="Дизайн"))
    builder.add(types.KeyboardButton(text="Документация"))
    builder.add(types.KeyboardButton(text="Другое"))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_progress_kb():
    """Клавиатура с процентами выполнения"""
    builder = ReplyKeyboardBuilder()
    for i in range(0, 101, 10):
        builder.add(types.KeyboardButton(text=f"{i}%"))
    builder.adjust(5)
    return builder.as_markup(resize_keyboard=True)

# --- Обработчики команд ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "📋 <b>Система учета выполнения работ</b>\n\n"
        "Для начала работы отправьте команду /new_report",
        parse_mode="HTML"
    )

@dp.message(Command("new_report"))
async def cmd_new_report(message: types.Message, state: FSMContext):
    await state.set_state(SurveyStates.WAITING_TASK)
    await message.answer(
        "📝 <b>Новый отчет</b>\n\n"
        "Опишите общую задачу, над которой вы работаете:",
        parse_mode="HTML",
        reply_markup=types.ReplyKeyboardRemove()
    )

@dp.message(Command("my_reports"))
async def cmd_my_reports(message: types.Message):
    report = generate_report(message.from_user.id)
    await message.answer(
        f"📊 <b>Ваши отчеты</b>\n\n{report}",
        parse_mode="HTML"
    )

@dp.message(Command("admin_report"), F.from_user.id == int(os.getenv('ADMIN_ID')))
async def cmd_admin_report(message: types.Message):
    report = generate_admin_report()
    await message.answer(report, parse_mode="HTML")

# --- Обработчики состояний ---
@dp.message(SurveyStates.WAITING_TASK)
async def process_task(message: types.Message, state: FSMContext):
    await state.update_data(task=message.text)
    await state.set_state(SurveyStates.WAITING_WORK_TYPE)
    await message.answer(
        "Выберите вид работы:",
        reply_markup=get_work_types_kb()
    )

@dp.message(SurveyStates.WAITING_WORK_TYPE)
async def process_work_type(message: types.Message, state: FSMContext):
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
    
    data = await state.get_data()
    current_date = datetime.now().strftime("%d.%m.%Y")
    weekday = get_current_weekday()
    
    # Сохраняем отчет
    user_id = message.from_user.id
    if user_id not in reports_db:
        reports_db[user_id] = {}
    
    if current_date not in reports_db[user_id]:
        reports_db[user_id][current_date] = []
    
    reports_db[user_id][current_date].append({
        "task": data["task"],
        "work_type": data["work_type"],
        "progress": progress,
        "weekday": weekday
    })
    
    await state.clear()
    await message.answer(
        "✅ <b>Отчет сохранен</b>\n\n"
        f"📅 День: {weekday}, {current_date}\n"
        f"📌 Задача: {data['task']}\n"
        f"🔧 Вид работы: {data['work_type']}\n"
        f"📊 Выполнено: {progress}%",
        parse_mode="HTML",
        reply_markup=types.ReplyKeyboardRemove()
    )
    
    # Отправляем уведомление администратору
    admin_id = os.getenv('ADMIN_ID')
    if admin_id:
        try:
            await bot.send_message(
                chat_id=int(admin_id),
                text=f"📌 Новый отчет от пользователя {message.from_user.full_name} (ID: {user_id})\n\n"
                     f"📅 {weekday}, {current_date}\n"
                     f"🔧 {data['work_type']}: {progress}%\n"
                     f"📝 Задача: {data['task']}",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления админу: {e}")

# Запуск бота
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
