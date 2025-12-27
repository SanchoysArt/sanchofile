import os
import logging
import sqlite3
from datetime import datetime, timedelta
from uuid import uuid4
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# Исправление для sqlite3 и datetime в Python 3.12+
def adapt_datetime(dt):
    return dt.isoformat()

def convert_datetime(text):
    return datetime.fromisoformat(text.decode())

sqlite3.register_adapter(datetime, adapt_datetime)
sqlite3.register_converter("TIMESTAMP", convert_datetime)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = "8563587236:AAHDjVuAm8hSn4HLUGdG7hAsOaf2nM7sUUU"
ADMIN_IDS = [5091693487]
DEFAULT_UPLOAD_LIMIT = 10

# Состояния для ConversationHandler
SEARCH, ADMIN_BAN, ADMIN_UNBAN, ADMIN_LIMIT, ADMIN_BROADCAST, DELETE_FILE = range(6)

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('file_exchange.db', check_same_thread=False, 
                          detect_types=sqlite3.PARSE_DECLTYPES)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            is_banned BOOLEAN DEFAULT FALSE,
            ban_reason TEXT,
            banned_until TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS files (
            file_id TEXT PRIMARY KEY,
            user_id INTEGER,
            file_name TEXT,
            file_type TEXT,
            file_size INTEGER,
            short_code TEXT UNIQUE,
            message_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    conn.commit()
    conn.close()

# Функции для работы с базой данных
def get_user(user_id):
    conn = sqlite3.connect('file_exchange.db', check_same_thread=False,
                          detect_types=sqlite3.PARSE_DECLTYPES)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, username, full_name, is_banned, ban_reason, banned_until, created_at 
        FROM users WHERE user_id = ?
    ''', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def add_user(user_id, username, full_name):
    conn = sqlite3.connect('file_exchange.db', check_same_thread=False,
                          detect_types=sqlite3.PARSE_DECLTYPES)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR IGNORE INTO users (user_id, username, full_name) 
        VALUES (?, ?, ?)
    ''', (user_id, username, full_name))
    conn.commit()
    conn.close()

def add_file(file_data, user_id, short_code, message_id, file_name, file_type):
    conn = sqlite3.connect('file_exchange.db', check_same_thread=False,
                          detect_types=sqlite3.PARSE_DECLTYPES)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO files (file_id, user_id, file_name, file_type, file_size, short_code, message_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (file_data.file_id, user_id, file_name, file_type, 
          getattr(file_data, 'file_size', 0), short_code, message_id))
    conn.commit()
    conn.close()

def get_user_files(user_id):
    conn = sqlite3.connect('file_exchange.db', check_same_thread=False,
                          detect_types=sqlite3.PARSE_DECLTYPES)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT file_id, file_name, file_type, short_code, created_at 
        FROM files WHERE user_id = ? ORDER BY created_at DESC
    ''', (user_id,))
    files = cursor.fetchall()
    conn.close()
    return files

def get_file_by_code(short_code):
    conn = sqlite3.connect('file_exchange.db', check_same_thread=False,
                          detect_types=sqlite3.PARSE_DECLTYPES)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT file_id, user_id, file_name, file_type, file_size, short_code, message_id, created_at 
        FROM files WHERE short_code = ?
    ''', (short_code,))
    file_data = cursor.fetchone()
    conn.close()
    return file_data

def delete_file(file_id, user_id):
    conn = sqlite3.connect('file_exchange.db', check_same_thread=False,
                          detect_types=sqlite3.PARSE_DECLTYPES)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM files WHERE file_id = ? AND user_id = ?', (file_id, user_id))
    conn.commit()
    success = cursor.rowcount > 0
    conn.close()
    return success

def get_user_upload_count(user_id):
    conn = sqlite3.connect('file_exchange.db', check_same_thread=False,
                          detect_types=sqlite3.PARSE_DECLTYPES)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM files WHERE user_id = ?', (user_id,))
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_all_users():
    conn = sqlite3.connect('file_exchange.db', check_same_thread=False,
                          detect_types=sqlite3.PARSE_DECLTYPES)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, username, full_name, is_banned, ban_reason, banned_until, created_at 
        FROM users
    ''')
    users = cursor.fetchall()
    conn.close()
    return users

def get_active_users():
    """Получить всех активных пользователей (не забаненных)"""
    conn = sqlite3.connect('file_exchange.db', check_same_thread=False,
                          detect_types=sqlite3.PARSE_DECLTYPES)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, username, full_name 
        FROM users WHERE is_banned = FALSE
    ''')
    users = cursor.fetchall()
    conn.close()
    return users

def update_user_ban_status(user_id, is_banned, ban_reason=None, banned_until=None):
    conn = sqlite3.connect('file_exchange.db', check_same_thread=False,
                          detect_types=sqlite3.PARSE_DECLTYPES)
    cursor = conn.cursor()
    if is_banned:
        cursor.execute('UPDATE users SET is_banned = ?, ban_reason = ?, banned_until = ? WHERE user_id = ?', 
                      (is_banned, ban_reason, banned_until, user_id))
    else:
        cursor.execute('UPDATE users SET is_banned = ?, ban_reason = NULL, banned_until = NULL WHERE user_id = ?', 
                      (is_banned, user_id))
    conn.commit()
    conn.close()

# Проверка бана пользователя
def is_user_banned(user_id):
    user = get_user(user_id)
    if not user:
        return False
    
    is_banned = user[3]
    banned_until = user[5]
    
    if is_banned:
        if banned_until:
            ban_date = datetime.fromisoformat(banned_until) if isinstance(banned_until, str) else banned_until
            if ban_date > datetime.now():
                return True
            else:
                # Время бана истекло - разбаниваем
                update_user_ban_status(user_id, False)
                return False
        else:
            # Бан навсегда
            return True
    return False

# Генерация короткого кода
def generate_short_code():
    return str(uuid4())[:8]

# Клавиатуры
def get_main_keyboard(user_id):
    """Основная клавиатура для пользователей"""
    keyboard = [
        [KeyboardButton("📤 Загрузить файл")],
        [KeyboardButton("📁 Мои загрузки"), KeyboardButton("🔍 Поиск по коду")],
        [KeyboardButton("ℹ️ Информация")]
    ]
    
    if user_id in ADMIN_IDS:
        keyboard.append([KeyboardButton("⚙️ Админ панель")])
    
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_keyboard():
    """Клавиатура для админов"""
    keyboard = [
        [KeyboardButton("👥 Пользователи"), KeyboardButton("📊 Статистика")],
        [KeyboardButton("🚫 Бан пользователя"), KeyboardButton("✅ Разбан пользователя")],
        [KeyboardButton("📈 Установить лимит"), KeyboardButton("📢 Рассылка")],
        [KeyboardButton("⚙️ Инфо"), KeyboardButton("🔙 Главное меню")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_cancel_keyboard():
    """Клавиатура с кнопкой отмены"""
    keyboard = [
        [KeyboardButton("❌ Отмена")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# Проверка бана перед выполнением действий
async def check_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if is_user_banned(user_id):
        user_data = get_user(user_id)
        ban_reason = user_data[4] if user_data[4] else "Нарушение правил"
        banned_until = user_data[5]
        
        if banned_until:
            ban_date = datetime.fromisoformat(banned_until) if isinstance(banned_until, str) else banned_until
            if ban_date > datetime.now():
                days_left = (ban_date - datetime.now()).days
                await update.message.reply_text(
                    f"❌ Вы забанены!\n\n"
                    f"📝 Причина: {ban_reason}\n"
                    f"⏰ Разбан через: {days_left} дней\n\n"
                    f"Если вы не согласны с баном, напишите в поддержку."
                )
                return True
        else:
            # Бан навсегда
            await update.message.reply_text(
                f"❌ Вы забанены навсегда!\n\n"
                f"📝 Причина: {ban_reason}\n\n"
                f"Если вы не согласны с баном, напишите в поддержку."
            )
            return True
    return False

# Главное меню
async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username, user.full_name)
    
    # Проверка бана
    if await check_ban(update, context):
        return ConversationHandler.END
    
    # Очищаем состояние пользователя
    if 'user_files' in context.user_data:
        del context.user_data['user_files']
    if 'waiting_for' in context.user_data:
        del context.user_data['waiting_for']
    
    menu_text = "📁 Файлообменник\n\nВыберите действие:"
    
    await update.message.reply_text(
        menu_text, 
        reply_markup=get_main_keyboard(user.id)
    )
    return ConversationHandler.END

# Информация
async def show_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    # Проверка бана
    if await check_ban(update, context):
        return
    
    user_data = get_user(user_id)
    upload_count = get_user_upload_count(user_id)
    
    info_text = (
        f"ℹ️ Информация\n\n"
        f"📊 Общий лимит загрузок: {DEFAULT_UPLOAD_LIMIT} файлов\n"
        f"📁 Ваши загрузки: {upload_count}/{DEFAULT_UPLOAD_LIMIT}\n"
    )
    
    if upload_count >= DEFAULT_UPLOAD_LIMIT:
        info_text += f"❌ Лимит исчерпан!\n"
    else:
        info_text += f"✅ Можно загрузить еще: {DEFAULT_UPLOAD_LIMIT - upload_count} файлов\n"
    
    await update.message.reply_text(info_text)

# Загрузка файла
async def upload_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    # Проверка бана
    if await check_ban(update, context):
        return
    
    user_data = get_user(user_id)
    
    # Проверяем лимит загрузок
    upload_count = get_user_upload_count(user_id)
    
    if upload_count >= DEFAULT_UPLOAD_LIMIT:
        await update.message.reply_text(
            f"❌ Лимит загрузок исчерпан!\n"
            f"Максимум: {DEFAULT_UPLOAD_LIMIT} файлов\n"
            f"Ваш текущий счет: {upload_count}/{DEFAULT_UPLOAD_LIMIT}\n\n"
            f"Удалите некоторые файлы в разделе 'Мои загрузки'"
        )
        return
    
    await update.message.reply_text(
        "📤 Загрузка файла\n\n"
        "Просто отправьте мне файл любого типа (документ, фото, видео, аудио).\n"
        "После загрузки вы получите уникальную ссылку для скачивания."
    )

# Обработчик файлов
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    # Проверка бана
    if await check_ban(update, context):
        return
    
    # Получаем файл
    file = None
    file_name = "Неизвестный файл"
    file_type = "document"
    
    if update.message.document:
        file = update.message.document
        file_name = file.file_name or "document"
        file_type = "document"
    elif update.message.photo:
        file = update.message.photo[-1]
        file_name = "photo.jpg"
        file_type = "photo"
    elif update.message.video:
        file = update.message.video
        file_name = getattr(file, 'file_name', 'video.mp4') or "video.mp4"
        file_type = "video"
    elif update.message.audio:
        file = update.message.audio
        file_name = getattr(file, 'file_name', 'audio.mp3') or "audio.mp3"
        file_type = "audio"
    elif update.message.voice:
        file = update.message.voice
        file_name = "voice.ogg"
        file_type = "voice"
    
    if not file:
        await update.message.reply_text("❌ Пожалуйста, отправьте файл!")
        return
    
    short_code = generate_short_code()
    
    try:
        add_file(file, user_id, short_code, update.message.message_id, file_name, file_type)
    except Exception as e:
        logger.error(f"Ошибка при сохранении файла: {e}")
        await update.message.reply_text("❌ Ошибка при сохранении файла!")
        return
    
    file_url = f"https://t.me/sanchobmbot?start={short_code}"
    upload_count = get_user_upload_count(user_id)
    
    await update.message.reply_text(
        f"✅ Файл успешно загружен!\n\n"
        f"📁 Имя: {file_name}\n"
        f"🔗 Ссылка: {file_url}\n"
        f"📊 Код: {short_code}\n\n"
        f"📊 Статистика: {upload_count + 1}/{DEFAULT_UPLOAD_LIMIT} файлов"
    )

# Мои загрузки
async def my_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    # Проверка бана
    if await check_ban(update, context):
        return
    
    files = get_user_files(user_id)
    upload_count = get_user_upload_count(user_id)
    
    if not files:
        await update.message.reply_text(
            f"📭 У вас пока нет загруженных файлов.\n"
            f"📊 Лимит: {upload_count}/{DEFAULT_UPLOAD_LIMIT}"
        )
        return
    
    # Сохраняем файлы пользователя в контексте для удаления по номеру
    context.user_data['user_files'] = files
    context.user_data['waiting_for'] = 'delete_file'
    
    message_text = f"📂 Ваши загрузки: ({upload_count}/{DEFAULT_UPLOAD_LIMIT})\n\n"
    
    for i, file in enumerate(files, 1):
        file_id, file_name, file_type, short_code, created_at = file
        
        message_text += f"{i}. {file_name}\n"
        message_text += f"   🔗 https://t.me/sanchobmbot?start={short_code}\n"
        message_text += f"   🆔 Код: {short_code}\n\n"
    
    message_text += "\n💡 Чтобы удалить файл, отправьте:\n• Номер файла (1, 2, 3...)\n• Или код файла\n\nДля отмены нажмите кнопку '❌ Отмена'"
    
    await update.message.reply_text(message_text, reply_markup=get_cancel_keyboard())

# Обработка удаления файла по номеру или коду
async def handle_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.strip()
    
    # Проверка бана
    if await check_ban(update, context):
        context.user_data['waiting_for'] = None
        return
    
    # Если это отмена
    if text == "❌ Отмена":
        context.user_data['waiting_for'] = None
        await show_menu(update, context)
        return
    
    # Проверяем, ожидаем ли мы удаление файла
    if context.user_data.get('waiting_for') != 'delete_file':
        await handle_text(update, context)
        return
    
    # Пробуем удалить по номеру (если введено число)
    if text.isdigit():
        file_number = int(text)
        files = context.user_data.get('user_files', [])
        
        if not files:
            # Если файлы не сохранены в контексте, получаем их заново
            files = get_user_files(user_id)
            context.user_data['user_files'] = files
        
        if 1 <= file_number <= len(files):
            file_data = files[file_number - 1]
            file_id, file_name, file_type, short_code, created_at = file_data
            
            success = delete_file(file_id, user_id)
            if success:
                upload_count = get_user_upload_count(user_id)
                await update.message.reply_text(
                    f"✅ Файл '{file_name}' успешно удален!\n"
                    f"📊 Осталось файлов: {upload_count}/{DEFAULT_UPLOAD_LIMIT}",
                    reply_markup=get_main_keyboard(user_id)
                )
                context.user_data['waiting_for'] = None
            else:
                await update.message.reply_text("❌ Ошибка при удалении файла!", reply_markup=get_cancel_keyboard())
        else:
            await update.message.reply_text(f"❌ Неверный номер файла! Доступные номера: 1-{len(files)}", reply_markup=get_cancel_keyboard())
    
    # Пробуем удалить по коду (8 символов)
    elif len(text) == 8:
        file_data = get_file_by_code(text)
        if file_data:
            file_id, file_owner, file_name, file_type, file_size, short_code, message_id, created_at = file_data
            
            if file_owner == user_id:
                success = delete_file(file_id, user_id)
                if success:
                    upload_count = get_user_upload_count(user_id)
                    await update.message.reply_text(
                        f"✅ Файл '{file_name}' успешно удален!\n"
                        f"📊 Осталось файлов: {upload_count}/{DEFAULT_UPLOAD_LIMIT}",
                        reply_markup=get_main_keyboard(user_id)
                    )
                    context.user_data['waiting_for'] = None
                else:
                    await update.message.reply_text("❌ Ошибка при удалении файла!", reply_markup=get_cancel_keyboard())
            else:
                await update.message.reply_text("❌ Вы не можете удалить чужой файл!", reply_markup=get_cancel_keyboard())
        else:
            await update.message.reply_text("❌ Файл с таким кодом не найден!", reply_markup=get_cancel_keyboard())
    
    else:
        await update.message.reply_text(
            "❌ Неверный формат!\n\n"
            "💡 Для удаления файла отправьте:\n"
            "• Номер файла из списка (1, 2, 3...)\n"
            "• Или код файла (8 символов)\n\n"
            "Для отмены нажмите кнопку '❌ Отмена'",
            reply_markup=get_cancel_keyboard()
        )

# Поиск по коду
async def search_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    # Проверка бана
    if await check_ban(update, context):
        return
    
    context.user_data['waiting_for'] = 'search_file'
    
    await update.message.reply_text(
        "🔍 Поиск по коду\n\n"
        "Отправьте код файла для поиска и скачивания:\n\n"
        "Для отмены нажмите кнопку '❌ Отмена'",
        reply_markup=get_cancel_keyboard()
    )

# Обработка поиска по коду
async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.strip()
    
    # Проверка бана
    if await check_ban(update, context):
        context.user_data['waiting_for'] = None
        return
    
    # Если это отмена
    if text == "❌ Отмена":
        context.user_data['waiting_for'] = None
        await show_menu(update, context)
        return
    
    # Проверяем, ожидаем ли мы поиск файла
    if context.user_data.get('waiting_for') != 'search_file':
        await handle_text(update, context)
        return
    
    file_data = get_file_by_code(text)
    
    if file_data:
        file_id, file_owner, file_name, file_type, file_size, short_code, message_id, created_at = file_data
        file_url = f"https://t.me/sanchobmbot?start={text}"
        
        # Отправляем информацию о файле
        info_message = await update.message.reply_text(
            f"🔍 Файл найден:\n\n"
            f"📁 Имя: {file_name}\n"
            f"🔗 Ссылка: {file_url}\n"
            f"📊 Код: {text}\n"
            f"📦 Тип: {file_type}\n"
            f"💾 Размер: {file_size} байт\n\n"
            f"⏳ Отправляю файл..."
        )
        
        # Отправляем сам файл
        try:
            if file_type == 'photo':
                await update.message.reply_photo(file_id, caption=f"📁 {file_name}")
            elif file_type == 'video':
                await update.message.reply_video(file_id, caption=f"📁 {file_name}")
            elif file_type == 'audio':
                await update.message.reply_audio(file_id, caption=f"📁 {file_name}")
            elif file_type == 'voice':
                await update.message.reply_voice(file_id, caption=f"📁 {file_name}")
            else:
                await update.message.reply_document(file_id, caption=f"📁 {file_name}")
            
            await info_message.edit_text(
                f"🔍 Файл найден:\n\n"
                f"📁 Имя: {file_name}\n"
                f"🔗 Ссылка: {file_url}\n"
                f"📊 Код: {text}\n"
                f"📦 Тип: {file_type}\n"
                f"💾 Размер: {file_size} байт\n\n"
                f"✅ Файл успешно отправлен!"
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке файла: {e}")
            await info_message.edit_text(
                f"❌ Ошибка при загрузке файла. Возможно, файл был удален.\n"
                f"Ошибка: {str(e)}"
            )
        
        context.user_data['waiting_for'] = None
        await show_menu(update, context)
    else:
        await update.message.reply_text(
            "❌ Файл не найден! Проверьте правильность кода.",
            reply_markup=get_cancel_keyboard()
        )

# Админ панель
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет доступа к админ панели!")
        return
    
    await update.message.reply_text(
        "⚙️ Админ панель\n\nВыберите действие:",
        reply_markup=get_admin_keyboard()
    )

# Админ: список пользователей
async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет доступа!")
        return
    
    users = get_all_users()
    
    if not users:
        await update.message.reply_text("📭 Нет пользователей в базе.")
        return
    
    message_text = "👥 Список пользователей:\n\n"
    
    for user in users[:10]:
        user_id, username, full_name, is_banned, ban_reason, banned_until, created_at = user
        status = "🚫 ЗАБАНЕН" if is_banned else "✅ АКТИВЕН"
        username_display = f"@{username}" if username else "без username"
        
        message_text += f"{status}\n"
        message_text += f"👤 {full_name} ({username_display})\n"
        message_text += f"🆔 ID: {user_id}\n"
        
        if is_banned and banned_until:
            try:
                ban_date = datetime.fromisoformat(banned_until) if isinstance(banned_until, str) else banned_until
                if ban_date > datetime.now():
                    days_left = (ban_date - datetime.now()).days
                    message_text += f"⏰ Разбан через: {days_left} дней\n"
                message_text += f"📝 Причина: {ban_reason or 'Не указана'}\n"
            except (ValueError, TypeError):
                message_text += f"📝 Причина: {ban_reason or 'Не указана'}\n"
        
        message_text += "\n"
    
    if len(users) > 10:
        message_text += f"\n... и еще {len(users) - 10} пользователей"
    
    await update.message.reply_text(message_text)

# Админ: статистика
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет доступа!")
        return
    
    conn = sqlite3.connect('file_exchange.db', check_same_thread=False,
                          detect_types=sqlite3.PARSE_DECLTYPES)
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM files')
    total_files = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM users WHERE is_banned = TRUE')
    banned_users = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(DISTINCT user_id) FROM files')
    active_users = cursor.fetchone()[0]
    
    conn.close()
    
    await update.message.reply_text(
        f"📊 Статистика бота\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"📁 Всего файлов: {total_files}\n"
        f"🚫 Забаненных: {banned_users}\n"
        f"✅ Активных: {active_users}\n"
        f"📈 Общий лимит: {DEFAULT_UPLOAD_LIMIT} файлов"
    )

# Админ: бан пользователя
async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет доступа!")
        return
    
    context.user_data['waiting_for'] = 'admin_ban'
    
    await update.message.reply_text(
        "🚫 Бан пользователя\n\n"
        "Отправьте в формате:\n"
        "ID_ПОЛЬЗОВАТЕЛЯ ДНИ ПРИЧИНА\n\n"
        "Пример:\n"
        "123456789 7 Распространение вирусов\n"
        "987654321 30 Нарушение правил\n\n"
        "Для отмены нажмите кнопку '❌ Отмена'",
        reply_markup=get_cancel_keyboard()
    )

# Админ: обработка бана
async def handle_admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.strip()
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет доступа!")
        return
    
    # Если это отмена
    if text == "❌ Отмена":
        context.user_data['waiting_for'] = None
        await admin_panel(update, context)
        return
    
    # Проверяем, ожидаем ли мы бан пользователя
    if context.user_data.get('waiting_for') != 'admin_ban':
        await handle_text(update, context)
        return
    
    try:
        parts = text.split(' ', 2)
        if len(parts) < 3:
            await update.message.reply_text("❌ Неверный формат! Нужно: ID ДНИ ПРИЧИНА", reply_markup=get_cancel_keyboard())
            return
        
        target_user_id = int(parts[0])
        ban_days = int(parts[1])
        ban_reason = parts[2]
        
        if ban_days <= 0:
            await update.message.reply_text("❌ Количество дней должно быть больше 0!", reply_markup=get_cancel_keyboard())
            return
        
        banned_until = datetime.now() + timedelta(days=ban_days)
        update_user_ban_status(target_user_id, True, ban_reason, banned_until)
        
        await update.message.reply_text(
            f"✅ Пользователь {target_user_id} забанен!\n"
            f"⏰ Срок: {ban_days} дней\n"
            f"📝 Причина: {ban_reason}",
            reply_markup=get_admin_keyboard()
        )
        context.user_data['waiting_for'] = None
    except ValueError:
        await update.message.reply_text("❌ Неверные параметры! Убедитесь что ID и дни - числа.", reply_markup=get_cancel_keyboard())

# Админ: разбан пользователя
async def admin_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет доступа!")
        return
    
    context.user_data['waiting_for'] = 'admin_unban'
    
    await update.message.reply_text(
        "✅ Разбан пользователя\n\n"
        "Отправьте ID пользователя для разбана:\n"
        "Пример: 123456789\n\n"
        "Для отмены нажмите кнопку '❌ Отмена'",
        reply_markup=get_cancel_keyboard()
    )

# Админ: обработка разбана
async def handle_admin_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.strip()
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет доступа!")
        return
    
    # Если это отмена
    if text == "❌ Отмена":
        context.user_data['waiting_for'] = None
        await admin_panel(update, context)
        return
    
    # Проверяем, ожидаем ли мы разбан пользователя
    if context.user_data.get('waiting_for') != 'admin_unban':
        await handle_text(update, context)
        return
    
    try:
        target_user_id = int(text)
        update_user_ban_status(target_user_id, False)
        await update.message.reply_text(
            f"✅ Пользователь {target_user_id} разбанен!",
            reply_markup=get_admin_keyboard()
        )
        context.user_data['waiting_for'] = None
    except ValueError:
        await update.message.reply_text("❌ Неверный ID пользователя!", reply_markup=get_cancel_keyboard())

# Админ: установка лимита
async def admin_set_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет доступа!")
        return
    
    context.user_data['waiting_for'] = 'admin_limit'
    
    await update.message.reply_text(
        "📈 Установка лимита\n\n"
        "Отправьте новое значение общего лимита:\n"
        "Пример: 25\n\n"
        "Для отмены нажмите кнопку '❌ Отмена'",
        reply_markup=get_cancel_keyboard()
    )

# Админ: обработка установки лимита
async def handle_admin_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.strip()
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет доступа!")
        return
    
    # Если это отмена
    if text == "❌ Отмена":
        context.user_data['waiting_for'] = None
        await admin_panel(update, context)
        return
    
    # Проверяем, ожидаем ли мы установку лимита
    if context.user_data.get('waiting_for') != 'admin_limit':
        await handle_text(update, context)
        return
    
    try:
        global DEFAULT_UPLOAD_LIMIT
        new_limit = int(text)
        
        if new_limit < 1:
            await update.message.reply_text("❌ Лимит должен быть больше 0!", reply_markup=get_cancel_keyboard())
            return
            
        DEFAULT_UPLOAD_LIMIT = new_limit
        await update.message.reply_text(
            f"✅ Общий лимит установлен: {new_limit} файлов",
            reply_markup=get_admin_keyboard()
        )
        context.user_data['waiting_for'] = None
    except ValueError:
        await update.message.reply_text("❌ Неверный лимит! Укажите число.", reply_markup=get_cancel_keyboard())

# Админ: рассылка
async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет доступа!")
        return
    
    context.user_data['waiting_for'] = 'admin_broadcast'
    
    await update.message.reply_text(
        "📢 Рассылка сообщения\n\n"
        "Отправьте сообщение для рассылки всем пользователям:\n\n"
        "Вы можете отправить:\n"
        "• Текст\n"
        "• Текст с фото\n"
        "• Текст с видео\n"
        "• Текст с документом\n\n"
        "Для отмены нажмите кнопку '❌ Отмена'",
        reply_markup=get_cancel_keyboard()
    )

# Админ: обработка рассылки
async def handle_admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет доступа!")
        return
    
    # Если это отмена
    if update.message.text and update.message.text.strip() == "❌ Отмена":
        context.user_data['waiting_for'] = None
        await admin_panel(update, context)
        return
    
    # Проверяем, ожидаем ли мы рассылку
    if context.user_data.get('waiting_for') != 'admin_broadcast':
        await handle_text(update, context)
        return
    
    # Получаем активных пользователей
    users = get_active_users()
    total_users = len(users)
    
    if total_users == 0:
        await update.message.reply_text("❌ Нет активных пользователей для рассылки!")
        await admin_panel(update, context)
        context.user_data['waiting_for'] = None
        return
    
    # Статистика рассылки
    successful = 0
    failed = 0
    
    # Отправляем уведомление о начале рассылки
    progress_message = await update.message.reply_text(
        f"📢 Начинаю рассылку...\n"
        f"👥 Получателей: {total_users}\n"
        f"✅ Успешно: 0\n"
        f"❌ Ошибок: 0"
    )
    
    # Рассылаем сообщение
    for i, user in enumerate(users):
        user_id_target, username, full_name = user
        
        try:
            # Проверяем тип сообщения
            if update.message.text:
                # Текстовое сообщение
                await context.bot.send_message(
                    chat_id=user_id_target,
                    text=update.message.text,
                    parse_mode='HTML'
                )
            elif update.message.photo:
                # Сообщение с фото
                await context.bot.send_photo(
                    chat_id=user_id_target,
                    photo=update.message.photo[-1].file_id,
                    caption=update.message.caption or "",
                    parse_mode='HTML'
                )
            elif update.message.video:
                # Сообщение с видео
                await context.bot.send_video(
                    chat_id=user_id_target,
                    video=update.message.video.file_id,
                    caption=update.message.caption or "",
                    parse_mode='HTML'
                )
            elif update.message.document:
                # Сообщение с документом
                await context.bot.send_document(
                    chat_id=user_id_target,
                    document=update.message.document.file_id,
                    caption=update.message.caption or "",
                    parse_mode='HTML'
                )
            else:
                # Неподдерживаемый тип
                continue
            
            successful += 1
            
        except Exception as e:
            logger.error(f"Ошибка при отправке пользователю {user_id_target}: {e}")
            failed += 1
        
        # Обновляем прогресс каждые 10 отправок
        if (i + 1) % 10 == 0 or (i + 1) == total_users:
            await progress_message.edit_text(
                f"📢 Рассылка...\n"
                f"👥 Получателей: {total_users}\n"
                f"✅ Успешно: {successful}\n"
                f"❌ Ошибок: {failed}\n"
                f"📊 Прогресс: {i + 1}/{total_users} ({((i + 1) / total_users * 100):.1f}%)"
            )
    
    # Финальная статистика
    await progress_message.edit_text(
        f"📢 Рассылка завершена!\n\n"
        f"👥 Всего получателей: {total_users}\n"
        f"✅ Успешно доставлено: {successful}\n"
        f"❌ Не доставлено: {failed}\n"
        f"📊 Эффективность: {(successful / total_users * 100):.1f}%"
    )
    
    context.user_data['waiting_for'] = None
    await admin_panel(update, context)

# Админ: информация
async def admin_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет доступа!")
        return
    
    users = get_active_users()
    total_users = len(get_all_users())
    active_users = len(users)
    
    await update.message.reply_text(
        f"⚙️ Текущие настройки\n\n"
        f"📊 Общий лимит загрузок: {DEFAULT_UPLOAD_LIMIT} файлов\n"
        f"👑 Администраторы: {len(ADMIN_IDS)} пользователей\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"✅ Активных пользователей: {active_users}\n"
        f"🆔 Ваш ID: {user_id}"
    )

# Обработчик текстовых сообщений
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.strip()
    
    # Проверка бана для всех пользователей
    if user_id not in ADMIN_IDS and await check_ban(update, context):
        return
    
    # Проверяем, не находимся ли мы в режиме ожидания какого-то действия
    waiting_for = context.user_data.get('waiting_for')
    
    if waiting_for == 'delete_file':
        await handle_delete(update, context)
        return
    elif waiting_for == 'search_file':
        await handle_search(update, context)
        return
    elif waiting_for == 'admin_ban':
        await handle_admin_ban(update, context)
        return
    elif waiting_for == 'admin_unban':
        await handle_admin_unban(update, context)
        return
    elif waiting_for == 'admin_limit':
        await handle_admin_limit(update, context)
        return
    elif waiting_for == 'admin_broadcast':
        await handle_admin_broadcast(update, context)
        return
    
    # Основные кнопки
    if text == "📤 Загрузить файл":
        await upload_info(update, context)
    elif text == "📁 Мои загрузки":
        await my_files(update, context)
    elif text == "🔍 Поиск по коду":
        await search_prompt(update, context)
    elif text == "ℹ️ Информация":
        await show_info(update, context)
    elif text == "⚙️ Админ панель":
        await admin_panel(update, context)
    elif text == "🔙 Главное меню":
        await show_menu(update, context)
    elif text == "❌ Отмена":
        await show_menu(update, context)
    
    # Админ кнопки
    elif user_id in ADMIN_IDS:
        if text == "👥 Пользователи":
            await admin_users(update, context)
        elif text == "📊 Статистика":
            await admin_stats(update, context)
        elif text == "🚫 Бан пользователя":
            await admin_ban(update, context)
        elif text == "✅ Разбан пользователя":
            await admin_unban(update, context)
        elif text == "📈 Установить лимит":
            await admin_set_limit(update, context)
        elif text == "📢 Рассылка":
            await admin_broadcast(update, context)
        elif text == "⚙️ Инфо":
            await admin_info(update, context)
    
    else:
        await update.message.reply_text(
            "❌ Неизвестная команда!\n\n"
            "Используйте кнопки меню для навигации."
        )

# Стартовая команда
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    # Проверка бана
    if await check_ban(update, context):
        return
    
    args = context.args
    
    if args and len(args) > 0:
        # Если перешли по ссылке с кодом файла
        short_code = args[0]
        file_data = get_file_by_code(short_code)
        
        if file_data:
            file_id, file_owner, file_name, file_type, file_size, short_code, message_id, created_at = file_data
            
            try:
                if file_type == 'photo':
                    await update.message.reply_photo(file_id, caption=f"📁 {file_name}")
                elif file_type == 'video':
                    await update.message.reply_video(file_id, caption=f"📁 {file_name}")
                elif file_type == 'audio':
                    await update.message.reply_audio(file_id, caption=f"📁 {file_name}")
                elif file_type == 'voice':
                    await update.message.reply_voice(file_id, caption=f"📁 {file_name}")
                else:
                    await update.message.reply_document(file_id, caption=f"📁 {file_name}")
                    
                await update.message.reply_text("✅ Файл успешно загружен!")
            except Exception as e:
                logger.error(f"Ошибка при отправке файла: {e}")
                await update.message.reply_text("❌ Ошибка при загрузке файла. Возможно, файл был удален.")
        else:
            await update.message.reply_text("❌ Файл не найден или был удален.")
    else:
        await show_menu(update, context)

# Основная функция
def main():
    init_db()
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Обработчики команд
    application.add_handler(CommandHandler("start", start_command))
    
    # Обработчики сообщений
    application.add_handler(MessageHandler(
        filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.VOICE, 
        handle_file
    ))
    
    # Обработчик текста (для всех текстовых сообщений)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("Бот запущен!")
    application.run_polling()

if __name__ == '__main__':
    main()