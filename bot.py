import requests
import time
import sqlite3
import uuid
import io
import os
import re
from PIL import Image
import pytesseract
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

print("=== ЗАПУСК БОТА С НОВЫМ КЛЮЧОМ ===", flush=True)

MAX_TOKEN = "f9LHodD0cOLWL39U48Z8RsC2X4HIL1mYcfhxK4qmPXNCyP5nqUn6F7Pbi1QRJ_VdTv_SEobZNS7Y-t2g6NV-"
# ВСТАВЛЕН ВАШ НОВЫЙ КЛЮЧ
GIGACHAT_AUTH_KEY = "MDFhMWI3NzItZThlZS03ZmEzLTlmMDktZGU0YTBlOWIzZTk5OmI2ZDljZjgwLTM2YTQtNDQ1ZS04OWU3LTQ2MmIxYjQ4YmU2MQ=="

BASE_URL = "https://platform-api2.max.ru"

cached_gigachat_token = None
token_expiry_time = 0

def clean_latex(text):
    if not text: return text
    text = text.replace('$$', '').replace('$', '')
    greek = {'alpha': 'α', 'beta': 'β', 'gamma': 'γ', 'delta': 'δ', 'theta': 'θ', 'lambda': 'λ', 'mu': 'μ', 'pi': 'π', 'rho': 'ρ', 'sigma': 'σ', 'tau': 'τ', 'phi': 'φ', 'omega': 'ω'}
    for eng, sym in greek.items():
        text = text.replace(f'\\{eng}', sym)
        text = re.sub(r'\b' + eng + r'\b', sym, text)
    text = text.replace('^2', '²').replace('^3', '³')
    text = re.sub(r'\^\{([^{}]+)\}', r'^\1', text)
    text = re.sub(r'_\{([^{}]+)\}', r'_\1', text)
    text = re.sub(r'\\?frac\{([^{}]+)\}\{([^{}]+)\}', r'(\1) / (\2)', text)
    text = re.sub(r'\\frac\s+([a-zA-Z0-9]+)\s+([a-zA-Z0-9]+)', r'(\1) / (\2)', text)
    symbols = {'times': '×', 'cdot': '·', 'approx': '≈', 'le': '≤', 'ge': '≥', 'neq': '≠', 'pm': '±', 'sqrt': '√', 'infty': '∞', 'sum': 'Σ'}
    for eng, sym in symbols.items():
        text = text.replace(f'\\{eng}', sym)
    text = re.sub(r'\\text\{([^{}]+)\}', r'\1', text)
    for func in ['sin', 'cos', 'tan', 'log', 'ln']:
        text = text.replace(f'\\{func}', func)
    text = text.replace('\\', '').replace('{', '').replace('}', '').replace(' , ', ' ')
    return text

def init_db():
    conn = sqlite3.connect('school_assistant.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        chat_id INTEGER,
                        state TEXT,
                        history TEXT
                      )''')
    try: cursor.execute("ALTER TABLE users ADD COLUMN chat_id INTEGER")
    except sqlite3.OperationalError: pass
    try: cursor.execute("ALTER TABLE users ADD COLUMN history TEXT")
    except sqlite3.OperationalError: pass
    conn.commit()
    conn.close()

def save_user_chat(user_id, chat_id):
    conn = sqlite3.connect('school_assistant.db')
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    cursor.execute("UPDATE users SET chat_id = ? WHERE user_id = ?", (chat_id, user_id))
    conn.commit()
    conn.close()

def get_user_chat(user_id):
    conn = sqlite3.connect('school_assistant.db')
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row and row[0] else user_id

def get_history(user_id):
    conn = sqlite3.connect('school_assistant.db')
    cursor = conn.cursor()
    cursor.execute("SELECT history FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row and row[0] else ""

def update_history(user_id, new_message):
    conn = sqlite3.connect('school_assistant.db')
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    cursor.execute("SELECT history FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    history = row[0] if row and row[0] else ""
    history = (history + "\n" + new_message)[-4000:]
    cursor.execute("UPDATE users SET history = ? WHERE user_id = ?", (history, user_id))
    conn.commit()
    conn.close()

def set_user_state(user_id, state):
    conn = sqlite3.connect('school_assistant.db')
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, state) VALUES (?, ?)", (user_id, state))
    cursor.execute("UPDATE users SET state = ? WHERE user_id = ?", (state, user_id))
    conn.commit()
    conn.close()

def get_user_state(user_id):
    conn = sqlite3.connect('school_assistant.db')
    cursor = conn.cursor()
    cursor.execute("SELECT state FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def get_gigachat_token():
    global cached_gigachat_token, token_expiry_time
    if cached_gigachat_token and time.time() < token_expiry_time:
        return cached_gigachat_token

    print("🔄 Запрашиваю новый токен GigaChat...", flush=True)
    url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    payload = 'scope=GIGACHAT_API_PERS'
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded', 
        'Accept': 'application/json', 
        'RqUID': str(uuid.uuid4()), 
        'Authorization': f'Basic {GIGACHAT_AUTH_KEY}'
    }
    try:
        # Увеличили timeout до 30 секунд
        response = requests.post(url, headers=headers, data=payload, verify=False, timeout=30)
        if response.status_code == 200:
            data = response.json()
            cached_gigachat_token = data.get('access_token')
            token_expiry_time = time.time() + 1500 
            print("✅ Токен успешно получен.", flush=True)
            return cached_gigachat_token
        else:
            print(f"❌ ОШИБКА АВТОРИЗАЦИИ GIGACHAT ({response.status_code}): {response.text}", flush=True)
            return None
    except Exception as e:
        print(f"❌ Ошибка сети: {e}", flush=True)
        return None

def ask_gigachat(prompt, context="", mode="chat"):
    token = get_gigachat_token()
    if not token: return "⚠️ Извините, произошла ошибка авторизации в ИИ. Проверьте логи."

    url = "https://api.giga.chat/v1/chat/completions"
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json', 'Authorization': f'Bearer {token}'}
    
    base_instruction = (
        "ТЫ ДОЛЖЕН СТРОГО СОБЛЮДАТЬ ЭТИ ПРАВИЛА ФОРМАТИРОВАНИЯ:\n"
        "1. НИКОГДА не используй $, $$, \\ и LaTeX (\\frac, \\cdot и т.д.).\n"
        "2. Степени: x², y³. Дроби: ½ или a/b. Корень: √.\n"
        "3. Для жирного текста используй *звездочки*.\n"
        "4. Для списков используй маркеры (•) или цифры (1., 2.).\n"
        "5. Делай текст структурированным: абзацы, списки, *выделение главного*.\n"
        "6. Не пиши сплошным текстом. Используй эмодзи для акцентов.\n"
    )
    
    if mode == "chat": system_prompt = base_instruction + "Ты — дружелюбный онлайн-учитель. Веди естественную беседу, объясняй понятно, подбадривай."
    elif mode == "explain": system_prompt = base_instruction + "Ты — ИИ-учитель. Объясни тему просто. Структура: 1. Определение. 2. Пример. 3. 3 задачи для тренировки."
    elif mode == "solve": system_prompt = base_instruction + "Ты — репетитор. Реши задачу по шагам (Шаг 1, Шаг 2...). В конце выдели *Итоговый ответ*."
    else: system_prompt = base_instruction + "Ты — учитель. Найди ошибки в ДЗ и объясни их. Пиши мягко."

    messages = [{"role": "system", "content": system_prompt}]
    if context: messages.append({"role": "user", "content": f"История: {context}"})
    messages.append({"role": "user", "content": prompt})

    data = {"model": "GigaChat-2", "messages": messages, "temperature": 0.7}
    
    try:
        response = requests.post(url, headers=headers, json=data, verify=False, timeout=40)
        if response.status_code != 200:
            print(f"❌ ОШИБКА API GIGACHAT ({response.status_code}): {response.text}", flush=True)
            return "⚠️ Ошибка ИИ при генерации."
            
        return clean_latex(response.json()['choices'][0]['message']['content'])
    except Exception as e:
        print(f"❌ Ошибка парсинга: {e}", flush=True)
        return "⚠️ Ошибка при генерации ответа."

def get_main_keyboard():
    return {
        "type": "inline_keyboard",
        "payload": {
            "buttons": [
                [
                    {"type": "callback", "text": "💬 Чат с учителем", "payload": "btn_chat_teacher"},
                    {"type": "callback", "text": "📚 Объяснить тему", "payload": "btn_explain"}
                ],
                [
                    {"type": "callback", "text": "📸 Решить задачу", "payload": "btn_solve_photo"},
                    {"type": "callback", "text": "📝 Проверить ДЗ", "payload": "btn_check_hw"}
                ]
            ]
        }
    }

def get_single_back_keyboard():
    return {
        "type": "inline_keyboard",
        "payload": {
            "buttons": [
                [{"type": "callback", "text": "🏠 Вернуться в главное меню", "payload": "btn_main_menu"}]
            ]
        }
    }

def send_message(chat_id, text, keyboard_type="single"):
    url = f"{BASE_URL}/messages"
    headers = {"Authorization": MAX_TOKEN}
    params = {"chat_id": chat_id}
    payload = {"text": text, "format": "markdown"}
    
    if keyboard_type == "main":
        payload["attachments"] = [get_main_keyboard()]
    elif keyboard_type == "single":
        payload["attachments"] = [get_single_back_keyboard()]
    
    try:
        response = requests.post(url, headers=headers, params=params, json=payload, timeout=10, verify=False)
        if response.status_code != 200:
            print(f"ОШИБКА ОТПРАВКИ MAX: {response.text}", flush=True)
    except Exception as e:
        print(f"Ошибка отправки: {e}", flush=True)

def get_updates(marker=0):
    url = f"{BASE_URL}/updates"
    headers = {"Authorization": MAX_TOKEN}
    params = {"timeout": 30, "limit": 100}
    if marker: params["marker"] = marker
    try:
        response = requests.get(url, headers=headers, params=params, timeout=35, verify=False)
        return response.json() if response.status_code == 200 else {}
    except Exception: return {}

def process_update(update):
    update_type = update.get("update_type")
    
    if update_type == "bot_started":
        chat_id = update.get("chat_id")
        user_id = update.get("user", {}).get("user_id")
        if chat_id and user_id:
            save_user_chat(user_id, chat_id)
            set_user_state(user_id, "idle")
            welcome = (
                "👋 *Привет! Я твой персональный ИИ-учитель.*\n\n"
                "Я помогу тебе разобраться в сложных темах, проверю домашку или решу задачу по фото.\n\n"
                "👇 *Выбери действие на кнопках ниже* или просто напиши мне свой вопрос в чат!"
            )
            send_message(chat_id, welcome, keyboard_type="main")
        return
        
    if update_type == "message_callback":
        callback = update.get("callback", {})
        user_id = callback.get("user", {}).get("user_id")
        chat_id = callback.get("message", {}).get("recipient", {}).get("chat_id") or get_user_chat(user_id)
        payload = callback.get("payload")
        
        if payload == "btn_main_menu":
            set_user_state(user_id, "idle")
            send_message(chat_id, "🏠 *Главное меню.* Чем еще я могу помочь?", keyboard_type="main")
        elif payload == "btn_chat_teacher":
            set_user_state(user_id, "chatting_with_teacher")
            send_message(chat_id, "💬 *Отлично! Я готов обсудить с тобой учебу.*\n\nЗадавай любые вопросы, я буду отвечать. Чтобы выйти, нажми кнопку внизу.", keyboard_type="single")
        elif payload == "btn_explain":
            set_user_state(user_id, "waiting_for_explanation")
            send_message(chat_id, "📚 *Напиши тему*, которую нужно объяснить (например: _Теорема Пифагора_).", keyboard_type="single")
        elif payload == "btn_solve_photo":
            set_user_state(user_id, "waiting_for_solve_photo")
            send_message(chat_id, "📸 *Отправь мне фото с задачей*, и я решу её по шагам!", keyboard_type="single")
        elif payload == "btn_check_hw":
            set_user_state(user_id, "waiting_for_check_hw")
            send_message(chat_id, "📝 *Отправь фото или текст решения*, и я проверю его.", keyboard_type="single")
        return

    if update_type != "message_created": return

    message = update.get("message", {})
    chat_id = message.get("recipient", {}).get("chat_id")
    user_id = message.get("sender", {}).get("user_id")
    text = message.get("body", {}).get("text", "")
    attachments = message.get("body", {}).get("attachments", [])

    if not chat_id or not user_id: return
    save_user_chat(user_id, chat_id)
    
    if text in ["/start", "/help"]:
        set_user_state(user_id, "idle")
        welcome = (
            "👋 *Привет! Я твой персональный ИИ-учитель.*\n\n"
            "👇 *Выбери действие на кнопках ниже* или просто напиши мне свой вопрос в чат!"
        )
        send_message(chat_id, welcome, keyboard_type="main")
        return

    user_state = get_user_state(user_id)
    image_url = next((att.get("payload", {}).get("url") for att in attachments if att.get("type") == "image"), None)

    if image_url:
        send_message(chat_id, "📸 *Фото получено! Распознаю текст...*", keyboard_type="none")
        try:
            img_resp = requests.get(image_url, timeout=15, verify=False)
            image = Image.open(io.BytesIO(img_resp.content))
            extracted_text = pytesseract.image_to_string(image, lang='rus+eng')
            
            if not extracted_text.strip():
                send_message(chat_id, "😔 *Не удалось распознать текст.* Попробуй сфотографировать четче.", keyboard_type="single")
                return
            
            send_message(chat_id, "✅ *Текст распознан. Отправляю ИИ...*", keyboard_type="none")
            mode = "check" if user_state == "waiting_for_check_hw" else "solve"
            response_text = ask_gigachat(f"Задача:\n\n{extracted_text}", context=get_history(user_id), mode=mode)
            
            send_message(chat_id, response_text, keyboard_type="single")
            update_history(user_id, "Фото решено.")
            set_user_state(user_id, "idle")
        except Exception: send_message(chat_id, "⚠️ Ошибка обработки фото.", keyboard_type="single")
        return

    if text:
        send_message(chat_id, "⏳ *Думаю над ответом...*", keyboard_type="none")
        
        if user_state == "chatting_with_teacher":
            mode = "chat"
        elif user_state == "waiting_for_explanation":
            mode = "explain"
            set_user_state(user_id, "idle")
        elif user_state == "waiting_for_check_hw":
            mode = "check"
            set_user_state(user_id, "idle")
        else:
            mode = "chat"

        response_text = ask_gigachat(text, context=get_history(user_id), mode=mode)
        send_message(chat_id, response_text, keyboard_type="single")
        update_history(user_id, f"Ученик: {text}\nАссистент: {response_text}")

def main():
    init_db()
    print("Бот запущен...", flush=True)
    marker = 0
    while True:
        try:
            updates_data = get_updates(marker)
            if updates_data and "updates" in updates_data:
                for update in updates_data["updates"]:
                    process_update(update)
                    marker = update.get("timestamp", marker) 
            time.sleep(1)
        except Exception: time.sleep(5)

if __name__ == '__main__': main()
