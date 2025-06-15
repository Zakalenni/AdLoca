import os
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(token=os.getenv('BOT_TOKEN'))
dp = Dispatcher()

# Состояния для FSM
class OrderStates(StatesGroup):
    WAITING_FOR_ADDRESS = State()
    WAITING_FOR_PHONE = State()

# "База данных" - в реальном проекте замените на подключение к реальной БД
products = {
    1: {"name": "Диван угловой", "price": 29999, "description": "Мягкий угловой диван из экокожи", "category": "Диваны"},
    2: {"name": "Кресло офисное", "price": 14999, "description": "Эргономичное кресло с регулировкой", "category": "Кресла"},
    3: {"name": "Стол обеденный", "price": 24999, "description": "Деревянный стол на 6 персон", "category": "Столы"},
}

# Корзина пользователя (временное хранилище)
user_carts = {}

# Клавиатуры
def main_menu_kb():
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="🛋️ Каталог", callback_data="catalog"))
    builder.add(types.InlineKeyboardButton(text="🛒 Корзина", callback_data="cart"))
    builder.add(types.InlineKeyboardButton(text="📞 Контакты", callback_data="contacts"))
    builder.adjust(1)
    return builder.as_markup()

def categories_kb():
    categories = set(product["category"] for product in products.values())
    builder = InlineKeyboardBuilder()
    for category in categories:
        builder.add(types.InlineKeyboardButton(text=category, callback_data=f"category_{category}"))
    builder.add(types.InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu"))
    builder.adjust(1)
    return builder.as_markup()

def products_kb(category):
    builder = InlineKeyboardBuilder()
    for product_id, product in products.items():
        if product["category"] == category:
            builder.add(types.InlineKeyboardButton(
                text=f"{product['name']} - {product['price']//100} руб.", 
                callback_data=f"product_{product_id}"
            ))
    builder.add(types.InlineKeyboardButton(text="🔙 Назад", callback_data="catalog"))
    builder.adjust(1)
    return builder.as_markup()

def product_kb(product_id):
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="➕ В корзину", callback_data=f"add_{product_id}"))
    builder.add(types.InlineKeyboardButton(text="🔙 Назад", callback_data=f"category_{products[product_id]['category']}"))
    builder.adjust(1)
    return builder.as_markup()

def cart_kb():
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="🚀 Оформить заказ", callback_data="checkout"))
    builder.add(types.InlineKeyboardButton(text="🗑️ Очистить корзину", callback_data="clear_cart"))
    builder.add(types.InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu"))
    builder.adjust(1)
    return builder.as_markup()

# Обработчики команд
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "🏠 Добро пожаловать в мебельный магазин 'Уютный Дом'!\n\n"
        "Здесь вы можете выбрать мебель для вашего интерьера.",
        reply_markup=main_menu_kb()
    )

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "ℹ️ Помощь по боту:\n\n"
        "/start - Главное меню\n"
        "/help - Эта справка\n"
        "/cart - Посмотреть корзину\n"
        "Используйте кнопки для навигации"
    )

# Обработчики колбэков
@dp.callback_query(F.data == "main_menu")
async def main_menu(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🏠 Главное меню",
        reply_markup=main_menu_kb()
    )
    await callback.answer()

@dp.callback_query(F.data == "catalog")
async def show_catalog(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🛋️ Выберите категорию:",
        reply_markup=categories_kb()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("category_"))
async def show_category_products(callback: types.CallbackQuery):
    category = callback.data.split("_")[1]
    await callback.message.edit_text(
        f"📦 Товары в категории '{category}':",
        reply_markup=products_kb(category)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("product_"))
async def show_product(callback: types.CallbackQuery):
    product_id = int(callback.data.split("_")[1])
    product = products[product_id]
    await callback.message.edit_text(
        f"🛋️ <b>{product['name']}</b>\n\n"
        f"💵 Цена: {product['price']//100} руб.\n\n"
        f"📝 Описание: {product['description']}\n"
        f"📦 Категория: {product['category']}",
        reply_markup=product_kb(product_id)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("add_"))
async def add_to_cart(callback: types.CallbackQuery):
    product_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    if user_id not in user_carts:
        user_carts[user_id] = {}
    
    if product_id not in user_carts[user_id]:
        user_carts[user_id][product_id] = 0
    
    user_carts[user_id][product_id] += 1
    await callback.answer(f"{products[product_id]['name']} добавлен в корзину!")

@dp.callback_query(F.data == "cart")
async def show_cart(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in user_carts or not user_carts[user_id]:
        await callback.message.edit_text(
            "🛒 Ваша корзина пуста",
            reply_markup=main_menu_kb()
        )
        await callback.answer()
        return
    
    cart_text = "🛒 Ваша корзина:\n\n"
    total = 0
    
    for product_id, quantity in user_carts[user_id].items():
        product = products[product_id]
        price = product["price"] * quantity
        total += price
        cart_text += f"🛋️ {product['name']}\n"
        cart_text += f"💰 {product['price']//100} руб. x {quantity} = {price//100} руб.\n\n"
    
    cart_text += f"💵 Итого: {total//100} руб."
    
    await callback.message.edit_text(
        cart_text,
        reply_markup=cart_kb()
    )
    await callback.answer()

@dp.callback_query(F.data == "clear_cart")
async def clear_cart(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id in user_carts:
        user_carts[user_id] = {}
    await callback.answer("Корзина очищена!")
    await show_cart(callback)

@dp.callback_query(F.data == "checkout")
async def start_checkout(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📝 Введите ваш адрес для доставки:",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[[
                types.InlineKeyboardButton(text="🔙 Отмена", callback_data="cart")
            ]]
        )
    )
    await state.set_state(OrderStates.WAITING_FOR_ADDRESS)
    await callback.answer()

@dp.message(OrderStates.WAITING_FOR_ADDRESS)
async def process_address(message: types.Message, state: FSMContext):
    await state.update_data(address=message.text)
    await message.answer(
        "📞 Теперь введите ваш номер телефона:",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[[
                types.InlineKeyboardButton(text="🔙 Отмена", callback_data="cart")
            ]]
        )
    )
    await state.set_state(OrderStates.WAITING_FOR_PHONE)

@dp.message(OrderStates.WAITING_FOR_PHONE)
async def process_phone(message: types.Message, state: FSMContext):
    data = await state.get_data()
    address = data.get("address")
    phone = message.text
    user_id = message.from_user.id
    
    # Формируем заказ
    order_text = "✅ Ваш заказ оформлен!\n\n"
    order_text += f"🏠 Адрес: {address}\n"
    order_text += f"📞 Телефон: {phone}\n\n"
    order_text += "🛒 Состав заказа:\n"
    
    total = 0
    for product_id, quantity in user_carts[user_id].items():
        product = products[product_id]
        price = product["price"] * quantity
        total += price
        order_text += f"  - {product['name']} x{quantity} = {price//100} руб.\n"
    
    order_text += f"\n💵 Итого: {total//100} руб."
    
    await message.answer(
        order_text,
        reply_markup=main_menu_kb()
    )
    
    # Очищаем корзину
    user_carts[user_id] = {}
    await state.clear()

@dp.callback_query(F.data == "contacts")
async def show_contacts(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "📞 Наши контакты:\n\n"
        "🏢 Адрес: г. Москва, ул. Мебельная, 42\n"
        "📞 Телефон: +7 (495) 123-45-67\n"
        "🕒 Часы работы: Пн-Пт 10:00-20:00, Сб-Вс 11:00-18:00\n\n"
        "📍 Мы на карте: https://yandex.ru/maps/-/CDRrV0~t",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[[
                types.InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")
            ]]
        )
    )
    await callback.answer()

# Запуск бота
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())