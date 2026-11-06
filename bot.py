import telebot
from telebot import apihelper, types
import telebot.util
import requests
import uuid
import sqlite3
import io
from PIL import Image
import pytesseract
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

telebot.util.validate_token = lambda token: True

MAX_BOT_TOKEN = "f9LHodD0cOLWL39U48Z8RsC2X4HIL1mYcfhxK4qmPXNCyP5nqUn6F7Pbi1QRJ_VdTv_SEobZNS7Y-t2g6NV-"
GIGACHAT_AUTH_KEY = "sk_2af1ad731243b8e5f04799d4a82c4c59da3c296b3cb6ad8e"

apihelper.API_URL = "https://botapi.max.ru/bot{0}/{1}" 
bot = telebot.TeleBot(MAX_BOT_TOKEN)

def init_db():
    conn = sqlite3.connect('school_assistant.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        history TEXT
                      )''')
    conn.commit()
    conn.close()

def get_history(user_id):
    conn = sqlite3.connect('school_assistant.db')
    cursor = conn.cursor()
    cursor.execute("SELECT history FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else ""

def update_history(user_id, new_message):
    conn = sqlite3.connect('school_assistant.db')
    cursor = conn.cursor()
    history = get_history(user_id)
    history = (history + "\n" + new_message)[-2000:]
    cursor.execute("INSERT OR REPLACE INTO users (user_id, history) VALUES (?, ?)", (user_id, history))
    conn.commit()
    conn.close()

def get_gigachat_token():
    url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    payload = 'scope=GIGACHAT_API_PERS'
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json',
        'RqUID': str(uuid.uuid4()),
        'Authorization': f'Basic {GIGACHAT_AUTH_KEY}'
    }
    try:
        response = requests.post(url, headers=headers, data=payload, verify=False)
        return response.json().get('access_token')
    except Exception as e:
        print(f"Error GigaChat auth: {e}")
        return None

def ask_gigachat(prompt, context="", mode="explain"):
    token = get_gigachat_token()
    if not token:
        return "Извините, произошла ошибка подключения к ИИ. Попробуйте позже."

    url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json', 'Authorization': f'Bearer {token}'}
    
    if mode == "explain":
        system_prompt = (
            "Ты — дружелюбный ИИ-ассистент для школьников 5-11 классов. "
            "Твоя задача — объяснять сложные темы простым языком. НИКОГДА не осуждай за незнание. "
            "Структура ответа: 1. Простое объяснение. 2. Пример. 3. Три тренировочные задачи. "
            "Используй эмодзи для красоты и форматирование Markdown."
        )
    else:
        system_prompt = (
            "Ты — заботливый учитель. Ученик прислал домашнее задание. "
            "Твоя задача: найти ошибки (если есть), объяснить ПОЧЕМУ они возникли, как правильно, "
            "и какое правило нужно повторить. Пиши мягко, без осуждения. Используй Markdown."
        )

    messages = [{"role": "system", "content": system_prompt}]
    if context:
        messages.append({"role": "user", "content": f"Контекст диалога: {context}"})
    messages.append({"role": "user", "content": prompt})

    data = {"model": "GigaChat", "messages": messages, "temperature": 0.7}

    try:
        response = requests.post(url, headers=headers, json=data, verify=False)
        return response.json()['choices'][0]['message']['content']
    except Exception as e:
        print(f"Error GigaChat request: {e}")
        return "Произошла ошибка при генерации ответа."

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_explain = types.KeyboardButton('📚 Объяснить тему')
    btn_check = types.KeyboardButton('📝 Проверить ДЗ')
    btn_help = types.KeyboardButton('ℹ️ Помощь')
    markup.add(btn_explain, btn_check, btn_help)
    return markup

def get_inline_keyboard():
    markup = types.InlineKeyboardMarkup()
    btn_more = types.InlineKeyboardButton("🔄 Дай еще задачу", callback_data="more_tasks")
    btn_simpler = types.InlineKeyboardButton("👶 Объясни еще проще", callback_data="simpler")
    markup.add(btn_more, btn_simpler)
    return markup

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "👋 **Привет! Я твой персональный ИИ-ассистент.**\n\n"
        "Я здесь, чтобы помочь тебе с учебой без стресса и осуждения.\n"
        "📚 **Объясню тему** простым языком и дам задачки для тренировки.\n"
        "📝 **Проверю твое ДЗ** (по фото или тексту) и укажу на ошибки.\n\n"
        "Выбери действие на клавиатуре ниже или просто напиши свой вопрос! 👇"
    )
    bot.send_message(message.chat.id, welcome_text, parse_mode='Markdown', reply_markup=get_main_keyboard())

@bot.message_handler(content_types=['text'])
def handle_text(message):
    user_id = message.chat.id
    text = message.text
    
    if text == 'ℹ️ Помощь':
        bot.send_message(user_id, "Просто напиши вопрос (например: 'Объясни теорему Пифагора') или отправь фото тетради с решением. Я помогу!", reply_markup=get_main_keyboard())
        return

    if text == '📚 Объяснить тему':
        bot.send_message(user_id, "Напиши, какую тему ты хочешь разобрать? (например: 'Квадратные уравнения' или 'Закон Ома')", reply_markup=get_main_keyboard())
        return
        
    if text == '📝 Проверить ДЗ':
        bot.send_message(user_id, "Отправь мне фото своего решения или напиши текст задания и свой ответ. Я проверю!", reply_markup=get_main_keyboard())
        return

    bot.send_chat_action(user_id, 'typing')
    msg = bot.send_message(user_id, "⏳ *Секунду, готовлю объяснение...*", parse_mode='Markdown')
    
    history = get_history(user_id)
    response_text = ask_gigachat(text, context=history, mode="explain")
    
    bot.edit_message_text(chat_id=user_id, message_id=msg.message_id, text=response_text, parse_mode='Markdown', reply_markup=get_inline_keyboard())
    update_history(user_id, f"Ученик: {text}\nАссистент: {response_text}")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    user_id = message.chat.id
    msg = bot.send_message(user_id, "📸 *Получил фото! Распознаю текст...*", parse_mode='Markdown')
    
    try:
        file_info = bot.get_file(message.photo[len(message.photo)-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        image = Image.open(io.BytesIO(downloaded_file))
        extracted_text = pytesseract.image_to_string(image, lang='rus+eng')
        
        if not extracted_text.strip():
            bot.edit_message_text(chat_id=user_id, message_id=msg.message_id, text="😔 Не удалось распознать текст. Сделай фото четче или напиши задание текстом.")
            return

        bot.edit_message_text(chat_id=user_id, message_id=msg.message_id, text="📝 *Текст распознан! Проверяю решение...*", parse_mode='Markdown')
        bot.send_chat_action(user_id, 'typing')
        
        prompt = f"Проверь мою домашнюю работу. Вот задание и мое решение:\n\n{extracted_text}"
        history = get_history(user_id)
        
        response_text = ask_gigachat(prompt, context=history, mode="check")
        
        bot.send_message(user_id, response_text, parse_mode='Markdown', reply_markup=get_inline_keyboard())
        update_history(user_id, f"Ученик отправил фото ДЗ. Ассистент проверил.")
        
    except Exception as e:
        print(f"Error photo: {e}")
        bot.edit_message_text(chat_id=user_id, message_id=msg.message_id, text="⚠️ Ошибка обработки фото. Отправь задание текстом.")

@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call):
    user_id = call.message.chat.id
    if call.data == "more_tasks":
        bot.answer_callback_query(call.id, "Генерирую новые задачи...")
        bot.send_chat_action(user_id, 'typing')
        response = ask_gigachat("Дай мне еще 3 похожие задачи для тренировки по последней теме, которую мы разбирали.", context=get_history(user_id))
        bot.send_message(user_id, response, parse_mode='Markdown', reply_markup=get_inline_keyboard())
    elif call.data == "simpler":
        bot.answer_callback_query(call.id, "Упрощаю...")
        bot.send_chat_action(user_id, 'typing')
        response = ask_gigachat("Объясни эту же тему еще проще, как будто мне 10 лет.", context=get_history(user_id))
        bot.send_message(user_id, response, parse_mode='Markdown', reply_markup=get_inline_keyboard())

if __name__ == '__main__':
    init_db()
    print("Bot started!")
    bot.infinity_polling()
