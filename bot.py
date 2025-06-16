import os
import logging
import asyncio
from html import escape
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
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

# Состояния для оформления заказа
class OrderStates(StatesGroup):
    WAITING_FOR_ADDRESS = State()
    WAITING_FOR_PHONE = State()

# База данных товаров
products = {
    1: {
        "id": 1,
        "name": "Этажерка, 4 секции",
        "price": 300000,  # в копейках для точности
        "description": "Этажерка для ванной и кухни деревянная. Идеально подходит для организации хранения в любом уголке вашего дома — будь то ванная комната или кухня. Стеллаж имеет четыре съемных ящика-корзины, что делает его универсальным для хранения различных предметов. Деревянная конструкция придаёт привлекательный внешний вид. Полка такого типа не только функциональна, но и эстетична, что делает её отличным решением для любого стиля (лофт, скандинавский, эко-стиль, современный, минимализм). Узкая напольная этажерка можно разместить в маленьком пространстве без потери места, а легкий вес позволяет без труда перемещать при необходимости. Возможные применения: В ванной комнате — для хранения уходовой косметики, полотенец и принадлежностей для ванны и туалета. На кухне — для хранения фруктов, овощей, корма для животных и кухонных принадлежностей. А еще это отличный подарок на новоселье!",
        "category": "Этажерки",
        "images": [
            "https://ir-8.ozone.ru/s3/multimedia-1-h/wc1000/7497020069.jpg",
            "https://ir-8.ozone.ru/s3/multimedia-1-k/wc1000/7483462508.jpg",
            "https://ir-8.ozone.ru/s3/multimedia-1-b/wc1000/7483462499.jpg"
        ],
        "colors": ["белые", "черные"]
    },
    2: {
        "id": 2,
        "name": "Этажерка, 3 секции",
        "price": 250000,
        "description": "Компактная этажерка для ванной и кухни деревянная. Идеально подходит для организации хранения в любом уголке вашего дома — будь то ванная комната или кухня. Стеллаж имеет четыре съемных ящика-корзины, что делает его универсальным для хранения различных предметов. Деревянная конструкция придаёт привлекательный внешний вид. Полка такого типа не только функциональна, но и эстетична, что делает её отличным решением для любого стиля (лофт, скандинавский, эко-стиль, современный, минимализм). Узкая напольная этажерка можно разместить в маленьком пространстве без потери места, а легкий вес позволяет без труда перемещать при необходимости. Возможные применения: В ванной комнате — для хранения уходовой косметики, полотенец и принадлежностей для ванны и туалета. На кухне — для хранения фруктов, овощей, корма для животных и кухонных принадлежностей. А еще это отличный подарок на новоселье!",
        "category": "Этажерки",
        "images": [
            "https://ir-8.ozone.ru/s3/multimedia-1-a/wc1000/7497018550.jpg",
            "https://ir-8.ozone.ru/s3/multimedia-1-9/wc1000/7483485033.jpg",
            "https://ir-8.ozone.ru/s3/multimedia-1-b/wc1000/7483462499.jpg"
        ],
        "colors": ["белые", "черные"]
    }
}

# Корзина пользователя {user_id: {product_id: {"quantity": int, "color": str}}}
user_carts = {}

async def delete_previous_message(message: types.Message):
    """Безопасное удаление предыдущего сообщения"""
    try:
        await message.delete()
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения: {e}")

async def send_product_card(chat_id: int, product: dict, image_index=0):
    """Отправка карточки товара с указанным изображением"""
    try:
        await bot.send_photo(
            chat_id=chat_id,
            photo=product["images"][image_index],
            caption=(
                f"🛋️ <b>{escape(product['name'])}</b>\n\n"
                f"📸 Изображение {image_index+1} из {len(product['images'])}\n\n"
                f"💵 Цена: {product['price']//100}₽\n"
                f"🎨 Доступные цвета корзин: {', '.join(escape(c) for c in product['colors'])}\n\n"
                f"📝 Описание:\n{escape(product['description'])}"
            ),
            reply_markup=product_kb(product["id"], image_index),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка отправки карточки товара: {e}")
        raise

def generate_order_text(user: types.User, phone: str, address: str, cart_items: dict) -> str:
    """Генерирует текст заказа с корректным HTML-форматированием"""
    order_lines = []
    total = 0
    
    for product_id, item in cart_items.items():
        product = products[product_id]
        price = product["price"] * item["quantity"]
        total += price
        line = f"- {escape(product['name'])}"
        if item.get("color"):
            line += f" (цвет: {escape(item['color'])})"
        line += f" - {item['quantity']} × {product['price']//100}₽ = {price//100}₽"
        order_lines.append(line)
    
    text = (
        "🛎 <b>Детали заказа</b>\n\n"
        f"👤 <b>Клиент:</b> {escape(user.full_name)}\n"
        f"🆔 <b>ID:</b> {user.id}\n"
    )
    
    if user.username:
        text += f"📱 <b>Username:</b> @{escape(user.username)}\n"
    
    text += (
        f"📞 <b>Телефон:</b> {escape(phone)}\n"
        f"🏠 <b>Адрес доставки:</b> {escape(address)}\n\n"
        "<b>Состав заказа:</b>\n"
        f"{chr(10).join(order_lines)}\n\n"
        f"💵 <b>Итого к оплате:</b> {total//100}₽"
    )
    
    return text

def generate_admin_order_text(user: types.User, phone: str, address: str, cart_items: dict) -> str:
    """Генерирует текст заказа для администратора"""
    order_lines = []
    total = 0
    
    for product_id, item in cart_items.items():
        product = products[product_id]
        price = product["price"] * item["quantity"]
        total += price
        line = f"- {escape(product['name'])}"
        if item.get("color"):
            line += f" (цвет: {escape(item['color'])})"
        line += f" - {item['quantity']} × {product['price']//100}₽ = {price//100}₽"
        order_lines.append(line)
    
    text = (
        "🛎 <b>НОВЫЙ ЗАКАЗ!</b>\n\n"
        f"👤 <b>Клиент:</b> {escape(user.full_name)}\n"
        f"🆔 <b>ID:</b> {user.id}\n"
    )
    
    if user.username:
        text += f"📱 <b>Username:</b> @{escape(user.username)}\n"
    
    text += (
        f"📞 <b>Телефон:</b> {escape(phone)}\n"
        f"🏠 <b>Адрес:</b> {escape(address)}\n\n"
        "<b>Состав заказа:</b>\n"
        f"{chr(10).join(order_lines)}\n\n"
        f"💵 <b>Итого:</b> {total//100}₽"
    )
    
    return text

def admin_order_kb(user_id: int, phone: str) -> types.InlineKeyboardMarkup:
    """Клавиатура для действий администратора с заказом"""
    builder = InlineKeyboardBuilder()
    
    # Кнопка подтверждения заказа
    builder.add(types.InlineKeyboardButton(
        text="✅ Подтвердить заказ",
        callback_data=f"admin_confirm_{user_id}"
    ))
    
    # Кнопка звонка (только если номер начинается с +)
    if phone.startswith('+'):
        builder.add(types.InlineKeyboardButton(
            text=f"📞 Позвонить ({phone})",
            callback_data=f"admin_call_{user_id}"
        ))
    
    # Кнопка написания сообщения клиенту
    builder.add(types.InlineKeyboardButton(
        text="💬 Написать клиенту",
        url=f"tg://user?id={user_id}"
    ))
    
    builder.adjust(1)
    return builder.as_markup()

def main_menu_kb():
    """Клавиатура главного меню"""
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(
        text="🛋️ Каталог товаров",
        callback_data="catalog"
    ))
    builder.add(types.InlineKeyboardButton(
        text="🛒 Моя корзина", 
        callback_data="cart"
    ))
    builder.add(types.InlineKeyboardButton(
        text="📞 Контакты магазина",
        callback_data="contacts"
    ))
    builder.adjust(1)
    return builder.as_markup()

def categories_kb():
    """Клавиатура с категориями товаров"""
    categories = sorted(set(product["category"] for product in products.values()))
    builder = InlineKeyboardBuilder()
    for category in categories:
        builder.add(types.InlineKeyboardButton(
            text=category,
            callback_data=f"category_{category}"
        ))
    builder.add(types.InlineKeyboardButton(
        text="🔙 В главное меню",
        callback_data="main_menu"
    ))
    builder.adjust(1)
    return builder.as_markup()

def products_kb(category: str):
    """Клавиатура с товарами в категории"""
    builder = InlineKeyboardBuilder()
    for product_id, product in products.items():
        if product["category"] == category:
            builder.add(types.InlineKeyboardButton(
                text=f"{product['name']} - {product['price']//100}₽",
                callback_data=f"product_{product_id}"
            ))
    builder.add(types.InlineKeyboardButton(
        text="🔙 К категориям",
        callback_data="catalog"
    ))
    builder.adjust(1)
    return builder.as_markup()

def product_kb(product_id: int, image_index=0):
    """Клавиатура для карточки товара"""
    try:
        product = products[product_id]
        builder = InlineKeyboardBuilder()
        
        # Кнопки навигации по изображениям
        if len(product["images"]) > 1:
            builder.add(types.InlineKeyboardButton(
                text="⬅️ Предыдущее фото",
                callback_data=f"nav_img_{product_id}_{image_index}_prev"
            ))
            builder.add(types.InlineKeyboardButton(
                text=f"{image_index+1}/{len(product['images'])}",
                callback_data="no_action"
            ))
            builder.add(types.InlineKeyboardButton(
                text="Следующее фото ➡️",
                callback_data=f"nav_img_{product_id}_{image_index}_next"
            ))
        
        # Кнопки выбора цвета
        for color in product["colors"]:
            builder.add(types.InlineKeyboardButton(
                text=f"🎨 {color.capitalize()}",
                callback_data=f"color_{product_id}_{color}"
            ))
        
        # Основные кнопки
        builder.add(types.InlineKeyboardButton(
            text="➕ Добавить в корзину",
            callback_data=f"add_{product_id}"
        ))
        builder.add(types.InlineKeyboardButton(
            text="🔙 Назад к товарам",
            callback_data=f"category_{product['category']}"
        ))
        
        # Оптимальное расположение кнопок
        if len(product["images"]) > 1:
            builder.adjust(3, *[2 for _ in product["colors"]], 1)
        else:
            builder.adjust(*[2 for _ in product["colors"]], 1)
        
        return builder.as_markup()
    except KeyError:
        return None

def cart_kb(cart_items: dict):
    """Клавиатура для корзины"""
    builder = InlineKeyboardBuilder()
    
    if cart_items:
        builder.add(types.InlineKeyboardButton(
            text="🚀 Оформить заказ",
            callback_data="checkout"
        ))
        builder.add(types.InlineKeyboardButton(
            text="🗑️ Очистить корзину",
            callback_data="clear_cart"
        ))
    
    builder.add(types.InlineKeyboardButton(
        text="🛋️ Продолжить покупки",
        callback_data="catalog"
    ))
    builder.add(types.InlineKeyboardButton(
        text="🔙 Главное меню",
        callback_data="main_menu"
    ))
    
    builder.adjust(1)
    return builder.as_markup()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    await message.answer_photo(
        photo="https://external-content.duckduckgo.com/iu/?u=https%3A%2F%2Fpriroda.club%2Fuploads%2Fposts%2F2022-08%2F1660129024_1-priroda-club-p-krasivie-doma-na-prirode-krasivo-foto-1.jpg&f=1&nofb=1&ipt=b0676001edfb48dde41f75ef58a27c7a4d238afcd0ef1ed482f147d0591cc26e",
        caption=(
            "🏠 Добро пожаловать в мебельный магазин 'Ad Loca'!\n\n"
            "Здесь вы найдете качественную мебель ручной работы из натуральных материалов.\n\n"
            "Используйте кнопки ниже для навигации:"
        ),
        reply_markup=main_menu_kb()
    )

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Обработчик команды /help"""
    await message.answer(
        "ℹ️ <b>Помощь по боту</b>\n\n"
        "<b>Основные команды:</b>\n"
        "/start - Главное меню\n"
        "/help - Эта справка\n"
        "/cart - Посмотреть корзину\n\n"
        "<b>Как сделать заказ:</b>\n"
        "1. Выберите товар в каталоге\n"
        "2. Добавьте нужное количество в корзину\n"
        "3. Перейдите в корзину и оформите заказ\n"
        "4. Укажите адрес доставки и контактный телефон\n\n"
        "<b>Возникли вопросы?</b> Напишите нам через раздел 'Контакты'",
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "main_menu")
async def main_menu(callback: types.CallbackQuery):
    """Обработчик возврата в главное меню"""
    await delete_previous_message(callback.message)
    await callback.message.answer(
        "🏠 <b>Главное меню</b>\n\n"
        "Выберите нужный раздел:",
        reply_markup=main_menu_kb(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data == "catalog")
async def show_catalog(callback: types.CallbackQuery):
    """Обработчик показа каталога"""
    await delete_previous_message(callback.message)
    await callback.message.answer(
        "🛋️ <b>Каталог товаров</b>\n\n"
        "Выберите категорию:",
        reply_markup=categories_kb(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("category_"))
async def show_category_products(callback: types.CallbackQuery):
    """Обработчик показа товаров в категории"""
    await delete_previous_message(callback.message)
    category = callback.data.split("_")[1]
    await callback.message.answer(
        f"📦 <b>Товары в категории '{category}'</b>\n\n"
        "Выберите товар для просмотра:",
        reply_markup=products_kb(category),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("product_"))
async def show_product(callback: types.CallbackQuery):
    """Обработчик показа карточки товара"""
    try:
        await delete_previous_message(callback.message)
        product_id = int(callback.data.split("_")[1])
        product = products[product_id]
        await send_product_card(callback.message.chat.id, product)
    except Exception as e:
        logger.error(f"Ошибка показа товара: {e}")
        await callback.answer("Произошла ошибка при загрузке товара", show_alert=True)
    finally:
        await callback.answer()

@dp.callback_query(F.data.startswith("nav_img_"))
async def handle_image_nav(callback: types.CallbackQuery):
    """Обработчик навигации по изображениям товара"""
    try:
        parts = callback.data.split('_')
        product_id = int(parts[2])
        current_idx = int(parts[3])
        direction = parts[4]
        
        product = products[product_id]
        
        if direction == "next":
            new_idx = (current_idx + 1) % len(product["images"])
        elif direction == "prev":
            new_idx = (current_idx - 1) % len(product["images"])
        else:
            raise ValueError("Неверное направление навигации")
        
        await delete_previous_message(callback.message)
        await send_product_card(callback.message.chat.id, product, new_idx)
    except Exception as e:
        logger.error(f"Ошибка навигации по изображениям: {e}")
        await callback.answer("Ошибка переключения изображения", show_alert=True)
    finally:
        await callback.answer()

@dp.callback_query(F.data == "no_action")
async def no_action(callback: types.CallbackQuery):
    """Пустой обработчик для кнопок без действия"""
    await callback.answer()

@dp.callback_query(F.data.startswith("color_"))
async def select_color(callback: types.CallbackQuery):
    """Обработчик выбора цвета товара"""
    try:
        parts = callback.data.split('_')
        product_id = int(parts[1])
        color = parts[2]
        product = products[product_id]
        
        # Получаем текущий индекс изображения
        caption = callback.message.caption or ""
        current_idx = 0
        if "Изображение" in caption:
            try:
                current_idx = int(caption.split("Изображение")[1].split("из")[0].strip()) - 1
            except:
                current_idx = 0
        
        await callback.answer(f"Выбран цвет: {color}", show_alert=True)
        
        # Обновляем сообщение с новым цветом
        new_caption = (
            f"🛋️ <b>{escape(product['name'])}</b>\n\n"
            f"📸 Изображение {current_idx+1} из {len(product['images'])}\n\n"
            f"💵 Цена: {product['price']//100}₽\n"
            f"🎨 <b>Выбранный цвет:</b> {escape(color)}\n\n"
            f"📝 Описание:\n{escape(product['description'])}"
        )
        
        await callback.message.edit_caption(
            caption=new_caption,
            reply_markup=product_kb(product_id, current_idx),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка выбора цвета: {e}")
        await callback.answer("Произошла ошибка при выборе цвета", show_alert=True)

@dp.callback_query(F.data.startswith("add_"))
async def add_to_cart(callback: types.CallbackQuery):
    """Обработчик добавления товара в корзину"""
    try:
        product_id = int(callback.data.split('_')[1])
        user_id = callback.from_user.id
        
        if user_id not in user_carts:
            user_carts[user_id] = {}
        
        if product_id not in user_carts[user_id]:
            user_carts[user_id][product_id] = {
                "quantity": 0,
                "color": None
            }
        
        user_carts[user_id][product_id]["quantity"] += 1
        
        # Получаем выбранный цвет из сообщения
        caption = callback.message.caption or ""
        if "Выбранный цвет:" in caption:
            selected_color = caption.split("Выбранный цвет:")[1].split("\n")[0].strip()
            user_carts[user_id][product_id]["color"] = selected_color
        
        await callback.answer(f"{products[product_id]['name']} добавлен в корзину!")
    except Exception as e:
        logger.error(f"Ошибка добавления в корзину: {e}")
        await callback.answer("Произошла ошибка при добавлении в корзину", show_alert=True)

@dp.callback_query(F.data == "cart")
async def show_cart(callback: types.CallbackQuery):
    """Обработчик показа корзины"""
    try:
        await delete_previous_message(callback.message)
        user_id = callback.from_user.id
        
        if user_id not in user_carts or not user_carts[user_id]:
            await callback.message.answer(
                "🛒 <b>Ваша корзина пуста</b>\n\n"
                "Добавьте товары из каталога, чтобы сделать заказ.",
                reply_markup=types.InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            types.InlineKeyboardButton(text="🛋️ В каталог", callback_data="catalog"),
                            types.InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")
                        ]
                    ]
                ),
                parse_mode="HTML"
            )
            await callback.answer()
            return
        
        cart_text = "🛒 <b>Ваша корзина</b>\n\n"
        total = 0
        
        for product_id, item in user_carts[user_id].items():
            product = products[product_id]
            price = product["price"] * item["quantity"]
            total += price
            
            cart_text += f"<b>{escape(product['name'])}</b>\n"
            if item["color"]:
                cart_text += f"🎨 Цвет: {escape(item['color'])}\n"
            cart_text += f"💰 {product['price']//100}₽ × {item['quantity']} = {price//100}₽\n\n"
        
        cart_text += f"💵 <b>Итого:</b> {total//100}₽"
        
        await callback.message.answer(
            cart_text,
            reply_markup=cart_kb(user_carts[user_id]),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка показа корзины: {e}")
        await callback.answer("Произошла ошибка при загрузке корзины", show_alert=True)
    finally:
        await callback.answer()

@dp.callback_query(F.data == "clear_cart")
async def clear_cart(callback: types.CallbackQuery):
    """Обработчик очистки корзины"""
    try:
        user_id = callback.from_user.id
        if user_id in user_carts:
            user_carts[user_id] = {}
        await callback.answer("Корзина очищена!", show_alert=True)
        await show_cart(callback)
    except Exception as e:
        logger.error(f"Ошибка очистки корзины: {e}")
        await callback.answer("Произошла ошибка при очистке корзины", show_alert=True)

@dp.callback_query(F.data == "checkout")
async def start_checkout(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик начала оформления заказа"""
    try:
        await delete_previous_message(callback.message)
        user_id = callback.from_user.id
        
        if user_id not in user_carts or not user_carts[user_id]:
            await callback.answer("Ваша корзина пуста!", show_alert=True)
            return
        
        await callback.message.answer(
            "📝 <b>Оформление заказа</b>\n\n"
            "Пожалуйста, введите ваш адрес для доставки:\n"
            "(Укажите город, улицу, дом и квартиру)",
            reply_markup=types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [types.InlineKeyboardButton(text="🔙 Назад в корзину", callback_data="cart")]
                ]
            ),
            parse_mode="HTML"
        )
        await state.set_state(OrderStates.WAITING_FOR_ADDRESS)
    except Exception as e:
        logger.error(f"Ошибка начала оформления заказа: {e}")
        await callback.answer("Произошла ошибка при оформлении заказа", show_alert=True)
    finally:
        await callback.answer()

@dp.message(OrderStates.WAITING_FOR_ADDRESS)
async def process_address(message: types.Message, state: FSMContext):
    """Обработчик ввода адреса доставки"""
    try:
        await state.update_data(address=message.text)
        await message.answer(
            "📞 Теперь введите ваш номер телефона для связи:\n"
            "(Формат: +79998887766)",
            reply_markup=types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [types.InlineKeyboardButton(text="🔙 Назад", callback_data="checkout")]
                ]
            )
        )
        await state.set_state(OrderStates.WAITING_FOR_PHONE)
    except Exception as e:
        logger.error(f"Ошибка обработки адреса: {e}")
        await message.answer(
            "Произошла ошибка, попробуйте еще раз\n"
            "Пожалуйста, введите ваш адрес для доставки:"
        )

@dp.message(OrderStates.WAITING_FOR_PHONE)
async def process_phone(message: types.Message, state: FSMContext):
    """Обработчик ввода телефона и завершения заказа"""
    try:
        user_id = message.from_user.id
        phone = message.text.strip()
        
        # Простая валидация номера телефона
        if not (phone.startswith('+7') and len(phone) == 12) and not (phone.startswith('8') and len(phone) == 11):
            await message.answer(
                "❌ Пожалуйста, введите корректный номер телефона\n"
                "Формат: +79998887766"
            )
            return
        
        data = await state.get_data()
        address = data.get("address")
        
        # Формируем текст заказа для клиента
        order_text = generate_order_text(message.from_user, phone, address, user_carts[user_id])
        
        # Отправляем подтверждение клиенту
        await message.answer(
            f"✅ <b>Ваш заказ оформлен!</b>\n\n{order_text}\n\n"
            "Наш менеджер свяжется с вами в ближайшее время для подтверждения.",
            reply_markup=main_menu_kb(),
            parse_mode="HTML"
        )
        
        # Отправляем уведомление администратору
        admin_id = os.getenv('ADMIN_ID')
        if admin_id:
            try:
                admin_text = generate_admin_order_text(
                    message.from_user, 
                    phone, 
                    address, 
                    user_carts[user_id]
                )
                
                await bot.send_message(
                    chat_id=int(admin_id.strip()),
                    text=admin_text,
                    parse_mode="HTML",
                    reply_markup=admin_order_kb(user_id, phone)
                )
                logger.info(f"Заказ #{user_id} отправлен администратору")
                
            except ValueError as e:
                logger.error(f"Ошибка в ADMIN_ID: {e}")
            except Exception as e:
                logger.exception("Ошибка отправки заказа администратору:")
        
        # Очищаем корзину
        user_carts[user_id] = {}
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка оформления заказа: {e}")
        await message.answer(
            "Произошла ошибка при оформлении заказа. Пожалуйста, попробуйте еще раз.",
            reply_markup=main_menu_kb()
        )

@dp.callback_query(F.data.startswith("admin_confirm_"))
async def confirm_order(callback: types.CallbackQuery):
    """Обработчик подтверждения заказа администратором"""
    try:
        user_id = int(callback.data.split('_')[2])
        
        # Отправляем уведомление клиенту
        await bot.send_message(
            chat_id=user_id,
            text="✅ <b>Ваш заказ подтвержден!</b>\n\n"
                 "Мы начали собирать ваш заказ. Ожидайте доставки в указанный срок.",
            parse_mode="HTML"
        )
        
        # Уведомляем администратора
        await callback.answer("Заказ подтвержден! Клиент уведомлен.", show_alert=True)
        
        # Можно добавить логику изменения статуса заказа в БД
    except Exception as e:
        logger.error(f"Ошибка подтверждения заказа: {e}")
        await callback.answer("Произошла ошибка при подтверждении заказа", show_alert=True)

@dp.callback_query(F.data.startswith("admin_call_"))
async def call_client(callback: types.CallbackQuery):
    """Обработчик кнопки звонка клиенту"""
    try:
        user_id = int(callback.data.split('_')[2])
        await callback.answer(
            "Используйте номер телефона из информации о заказе для звонка клиенту",
            show_alert=True
        )
    except Exception as e:
        logger.error(f"Ошибка обработки запроса звонка: {e}")

@dp.callback_query(F.data == "contacts")
async def show_contacts(callback: types.CallbackQuery):
    """Обработчик показа контактной информации"""
    try:
        await delete_previous_message(callback.message)
        await callback.message.answer_photo(
            photo="https://external-content.duckduckgo.com/iu/?u=https%3A%2F%2Fpriroda.club%2Fuploads%2Fposts%2F2022-08%2F1660129024_1-priroda-club-p-krasivie-doma-na-prirode-krasivo-foto-1.jpg&f=1&nofb=1&ipt=b0676001edfb48dde41f75ef58a27c7a4d238afcd0ef1ed482f147d0591cc26e",
            caption=(
                "📌 <b>Наши контакты</b>\n\n"
                "🏢 <b>Адрес магазина:</b>\n"
                "г. Уфа, ул. Грибоедова, 2к1\n\n"
                "📞 <b>Телефоны:</b>\n"
                "+7 (987) 772-63-99 - отдел продаж\n"
                "+7 (987) 772-63-99 - служба доставки\n\n"
                "🕒 <b>Часы работы:</b>\n"
                "Пн-Пт: 10:00-20:00\n"
                "Сб-Вс: 11:00-18:00\n\n"
                "📍 Мы на карте: https://tinyurl.com/3mxcjxww"
            ),
            reply_markup=types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [types.InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
                ]
            ),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка показа контактов: {e}")
        await callback.answer("Произошла ошибка при загрузке контактов", show_alert=True)
    finally:
        await callback.answer()

async def main():
    try:
        # Удаляем вебхук перед запуском (на всякий случай)
        await bot.delete_webhook(drop_pending_updates=True)
        
        # Запускаем поллинг (если не используем вебхуки)
        await dp.start_polling(bot)
        
    except Exception as e:
        logger.error(f"Ошибка запуска: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
