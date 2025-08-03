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
    WAITING_NEXT_ACTION = State()

# Виды работ
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

# База данных для хранения отчетов
reports_db = {}
user_current_reports = {}  # Для хранения текущих отчетов пользователей

# --- Вспомогательные функции ---
async def delete_previous_messages(chat_id: int, message_ids: list):
    """Удаляет предыдущие сообщения"""
    for msg_id in message_ids:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception as e:
            logger.error(f"Ошибка удаления сообщения: {e}")

def get_current_weekday():
    """Возвращает текущий день недели"""
    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    return days[datetime.now().weekday()]

def generate_user_report(user_id: int) -> str:
    """Генерирует отчет по пользователю"""
    if user_id not in reports_db or not reports_db[user_id]:
        return "📭 У вас пока нет сохраненных отчетов"
    
    report = ["📊 <b>Ваши отчеты</b>\n"]
    for date, records in reports_db[user_id].items():
        report.append(f"\n📅 <b>{date}</b>")
        for i, record in enumerate(records, 1):
            report.append(
                f"\n{i}. {record['work_type']}\n"
                f"   - Выполнено: {record['progress']}%\n"
                f"   - Количество: {record.get('quantity', 'не указано')}\n"
                f"   - Задача: {record['task']}"
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
                    f"    • {record['work_type']}: {record['progress']}% "
                    f"(кол-во: {record.get('quantity', 'н/у')})"
                )
    
    return "\n".join(report)

# --- Клавиатуры ---
def get_main_menu_kb():
    """Главное меню"""
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="📝 Новый отчет"))
    builder.add(types.KeyboardButton(text="📊 Мои отчеты"))
    builder.add(types.KeyboardButton(text="🛠 Добавить работу"))
    builder.add(types.KeyboardButton(text="✅ Завершить отчет"))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_work_types_kb():
    """Клавиатура с типами работ"""
    builder = ReplyKeyboardBuilder()
    for work_type in WORK_TYPES:
        builder.add(types.KeyboardButton(text=work_type))
    builder.adjust(2)
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
    builder.add(types.KeyboardButton(text="1"))
    builder.add(types.KeyboardButton(text="2"))
    builder.add(types.KeyboardButton(text="5"))
    builder.add(types.KeyboardButton(text="10"))
    builder.add(types.KeyboardButton(text="Другое количество"))
    builder.adjust(3)
    return builder.as_markup(resize_keyboard=True)

def get_next_action_kb():
    """Клавиатура выбора следующего действия"""
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="➕ Добавить еще работу"))
    builder.add(types.KeyboardButton(text="✅ Завершить отчет"))
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)

# --- Обработчики команд ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    msg = await message.answer(
        "🔧 <b>Система учета столярных работ</b>\n\n"
        "Выберите действие:",
        parse_mode="HTML",
        reply_markup=get_main_menu_kb()
    )
    # Сохраняем ID сообщения для последующего удаления
    await state.update_data(last_message_id=msg.message_id)

@dp.message(F.text == "📝 Новый отчет")
async def cmd_new_report(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    await delete_previous_messages(message.chat.id, [user_data.get('last_message_id'), message.message_id])
    
    await state.set_state(SurveyStates.WAITING_TASK)
    msg = await message.answer(
        "📝 <b>Новый отчет</b>\n\n"
        "Опишите общую задачу, над которой вы работаете:",
        parse_mode="HTML",
        reply_markup=types.ReplyKeyboardRemove()
    )
    await state.update_data(last_message_id=msg.message_id)

@dp.message(F.text == "📊 Мои отчеты")
async def cmd_my_reports(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    await delete_previous_messages(message.chat.id, [user_data.get('last_message_id'), message.message_id])
    
    report = generate_user_report(message.from_user.id)
    msg = await message.answer(
        report,
        parse_mode="HTML",
        reply_markup=get_main_menu_kb()
    )
    await state.update_data(last_message_id=msg.message_id)

@dp.message(F.text == "🛠 Добавить работу")
async def cmd_add_work(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    await delete_previous_messages(message.chat.id, [user_data.get('last_message_id'), message.message_id])
    
    if 'task' not in user_data:
        await state.set_state(SurveyStates.WAITING_TASK)
        msg = await message.answer(
            "Сначала нужно создать отчет с общей задачей",
            reply_markup=types.ReplyKeyboardRemove()
        )
    else:
        await state.set_state(SurveyStates.WAITING_WORK_TYPE)
        msg = await message.answer(
            "Выберите вид работы:",
            reply_markup=get_work_types_kb()
        )
    await state.update_data(last_message_id=msg.message_id)

@dp.message(F.text == "✅ Завершить отчет")
async def cmd_finish_report(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    await delete_previous_messages(message.chat.id, [user_data.get('last_message_id'), message.message_id])
    
    user_id = message.from_user.id
    if user_id in user_current_reports and user_current_reports[user_id]:
        # Сохраняем текущий отчет
        current_date = datetime.now().strftime("%d.%m.%Y")
        if user_id not in reports_db:
            reports_db[user_id] = {}
        reports_db[user_id][current_date] = user_current_reports[user_id]
        
        # Отправляем подтверждение
        report = generate_user_report(user_id)
        msg = await message.answer(
            f"✅ <b>Отчет завершен и сохранен</b>\n\n{report}",
            parse_mode="HTML",
            reply_markup=get_main_menu_kb()
        )
        
        # Очищаем временные данные
        user_current_reports.pop(user_id, None)
        await state.clear()
        await state.update_data(last_message_id=msg.message_id)
        
        # Уведомление администратору
        admin_id = os.getenv('ADMIN_ID')
        if admin_id:
            try:
                await bot.send_message(
                    chat_id=int(admin_id),
                    text=f"📌 Новый завершенный отчет от пользователя {message.from_user.full_name}\n\n{report}",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления админу: {e}")
    else:
        msg = await message.answer(
            "У вас нет активного отчета для сохранения",
            reply_markup=get_main_menu_kb()
        )
        await state.update_data(last_message_id=msg.message_id)

@dp.message(Command("admin_report"), F.from_user.id == int(os.getenv('ADMIN_ID')))
async def cmd_admin_report(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    await delete_previous_messages(message.chat.id, [user_data.get('last_message_id'), message.message_id])
    
    report = generate_admin_report()
    msg = await message.answer(report, parse_mode="HTML")
    await state.update_data(last_message_id=msg.message_id)

# --- Обработчики состояний ---
@dp.message(SurveyStates.WAITING_TASK)
async def process_task(message: types.Message, state: FSMContext):
    await state.update_data(task=message.text)
    await state.set_state(SurveyStates.WAITING_WORK_TYPE)
    
    # Инициализируем временный отчет для пользователя
    user_current_reports[message.from_user.id] = []
    
    msg = await message.answer(
        "Выберите вид работы:",
        reply_markup=get_work_types_kb()
    )
    await state.update_data(last_message_id=msg.message_id)

@dp.message(SurveyStates.WAITING_WORK_TYPE)
async def process_work_type(message: types.Message, state: FSMContext):
    if message.text not in WORK_TYPES:
        msg = await message.answer("Пожалуйста, выберите вид работы из списка")
        await state.update_data(last_message_id=msg.message_id)
        return
    
    await state.update_data(work_type=message.text)
    await state.set_state(SurveyStates.WAITING_PROGRESS)
    
    msg = await message.answer(
        "Укажите процент выполнения:",
        reply_markup=get_progress_kb()
    )
    await state.update_data(last_message_id=msg.message_id)

@dp.message(SurveyStates.WAITING_PROGRESS)
async def process_progress(message: types.Message, state: FSMContext):
    try:
        progress = int(message.text.replace("%", ""))
        if not 0 <= progress <= 100:
            raise ValueError
    except ValueError:
        msg = await message.answer("Пожалуйста, укажите процент от 0 до 100")
        await state.update_data(last_message_id=msg.message_id)
        return
    
    await state.update_data(progress=progress)
    await state.set_state(SurveyStates.WAITING_QUANTITY)
    
    msg = await message.answer(
        "Укажите количество выполненных единиц:",
        reply_markup=get_quantity_kb()
    )
    await state.update_data(last_message_id=msg.message_id)

@dp.message(SurveyStates.WAITING_QUANTITY)
async def process_quantity(message: types.Message, state: FSMContext):
    quantity = message.text if message.text != "Другое количество" else None
    
    if quantity and not quantity.isdigit():
        msg = await message.answer("Пожалуйста, укажите число")
        await state.update_data(last_message_id=msg.message_id)
        return
    
    data = await state.get_data()
    work_data = {
        "task": data["task"],
        "work_type": data["work_type"],
        "progress": data["progress"],
        "quantity": quantity if quantity else "не указано",
        "weekday": get_current_weekday()
    }
    
    # Добавляем работу в текущий отчет пользователя
    user_current_reports[message.from_user.id].append(work_data)
    
    await state.set_state(SurveyStates.WAITING_NEXT_ACTION)
    
    msg = await message.answer(
        f"✅ <b>Работа добавлена в отчет</b>\n\n"
        f"🔧 Вид работы: {data['work_type']}\n"
        f"📊 Выполнено: {data['progress']}%\n"
        f"🔢 Количество: {quantity if quantity else 'не указано'}\n\n"
        "Выберите следующее действие:",
        parse_mode="HTML",
        reply_markup=get_next_action_kb()
    )
    await state.update_data(last_message_id=msg.message_id)

@dp.message(SurveyStates.WAITING_NEXT_ACTION)
async def process_next_action(message: types.Message, state: FSMContext):
    if message.text == "➕ Добавить еще работу":
        await state.set_state(SurveyStates.WAITING_WORK_TYPE)
        msg = await message.answer(
            "Выберите вид работы:",
            reply_markup=get_work_types_kb()
        )
    elif message.text == "✅ Завершить отчет":
        # Сохраняем отчет
        user_id = message.from_user.id
        current_date = datetime.now().strftime("%d.%m.%Y")
        
        if user_id not in reports_db:
            reports_db[user_id] = {}
        reports_db[user_id][current_date] = user_current_reports[user_id]
        
        # Отправляем подтверждение
        report = generate_user_report(user_id)
        msg = await message.answer(
            f"✅ <b>Отчет завершен и сохранен</b>\n\n{report}",
            parse_mode="HTML",
            reply_markup=get_main_menu_kb()
        )
        
        # Очищаем временные данные
        user_current_reports.pop(user_id, None)
        await state.clear()
        
        # Уведомление администратору
        admin_id = os.getenv('ADMIN_ID')
        if admin_id:
            try:
                await bot.send_message(
                    chat_id=int(admin_id),
                    text=f"📌 Новый завершенный отчет от пользователя {message.from_user.full_name}\n\n{report}",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления админу: {e}")
    else:
        msg = await message.answer(
            "Пожалуйста, выберите действие из предложенных",
            reply_markup=get_next_action_kb()
        )
    
    await state.update_data(last_message_id=msg.message_id)

# Запуск бота
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
