import requests
import time
import sqlite3
import uuid
import io
import os
import re
import threading
from PIL import Image
import pytesseract
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

print("=== ЗАПУСК БОТА (ОТКАТ К СТАБИЛЬНОЙ ВЕРСИИ) ===", flush=True)

MAX_TOKEN = "f9LHodD0cOLWL39U48Z8RsC2X4HIL1mYcfhxK4qmPXNCyP5nqUn6F7Pbi1QRJ_VdTv_SEobZNS7Y-t2g6NV-"
GIGACHAT_AUTH_KEY = "MDFhMWI3NzItZThlZS03ZmEzLTlmMDktZGU0YTBlOWIzZTk5OmI2ZDljZjgwLTM2YTQtNDQ1ZS04OWU3LTQ2MmIxYjQ4YmU2MQ=="

BASE_URL = "https://platform-api2.max.ru"

cached_gigachat_token = None
token_expiry_time = 0

def clean_latex(text):
    if not text: return text
    text = text.replace('$$', '').replace('$', '')
    text = text.replace('vecF', 'F').replace('veca', 'a').replace('vecv', 'v')
    text = text.replace('Delta', 'Δ').replace('quad', ' ')
    text = re.sub(r'fracdvecvdt', '(dv)/(dt)', text)
    text = re.sub(r'frac([a-zA-Z0-9]+)([a-zA-Z0-9]+)', r'(\1)/(\2)', text)
    
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
                        history TEXT,
                        last_mid TEXT
                      )''')
    try: cursor.execute("ALTER TABLE users ADD COLUMN chat_id INTEGER")
    except sqlite3.OperationalError: pass
    try: cursor.execute("ALTER TABLE users ADD COLUMN history TEXT")
    except sqlite3.OperationalError: pass
    try: cursor.execute("ALTER TABLE users ADD COLUMN last_mid TEXT")
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

def get_last_mid(user_id):
    conn = sqlite3.connect('school_assistant.db')
    cursor = conn.cursor()
    cursor.execute("SELECT last_mid FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row and row[0] else None

def save_last_mid(user_id, mid):
    conn = sqlite3.connect('school_assistant.db')
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    cursor.execute("UPDATE users SET last_mid = ? WHERE user_id = ?", (mid, user_id))
    conn.commit()
    conn.close()

def delete_message(chat_id, message_id):
    if not message_id: return
    url = f"{BASE_URL}/messages"
    headers = {"Authorization": MAX_TOKEN}
    params = {"chat_id": chat_id, "message_id": message_id}
    try:
        requests.delete(url, headers=headers, params=params, verify=False, timeout=5)
    except Exception:
        pass

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
    history = (history + "\n" + new_message)[-2500:]
    cursor.execute("UPDATE users SET history = ? WHERE user_id = ?", (history, user_id))
    conn.commit()
    conn.close()

def clear_history(user_id):
    conn = sqlite3.connect('school_assistant.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET history = '' WHERE user_id = ?", (user_id,))
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

    url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    payload = 'scope=GIGACHAT_API_PERS'
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded', 
        'Accept': 'application/json', 
        'RqUID': str(uuid.uuid4()), 
        'Authorization': f'Basic {GIGACHAT_AUTH_KEY}'
    }
    try:
        response = requests.post(url, headers=headers, data=payload, verify=False, timeout=20)
        if response.status_code == 200:
            cached_gigachat_token = response.json().get('access_token')
            token_expiry_time = time.time() + 1500 
            return cached_gigachat_token
        return None
    except Exception:
        return None

def ask_gigachat(prompt, context="", mode="chat"):
    token = get_gigachat_token()
    if not token: return "⚠️ Ошибка авторизации в ИИ."

    url = "https://api.giga.chat/v1/chat/completions"
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json', 'Authorization': f'Bearer {token}'}
    
    base_instruction = (
        "ПРАВИЛА: 1. НИКАКОГО LaTeX ($, \\). 2. Степени: x². 3. Дроби: a/b. 4. Корень: √. "
        "5. Жирный: *текст*. 6. Списки: •. 7. Не пиши сплошным текстом. 8. Используй эмодзи."
    )
    
    if mode == "chat": system_prompt = base_instruction + " Ты — учитель. Отвечай коротко и по делу."
    elif mode == "explain": system_prompt = base_instruction + " Ты — учитель. Объясни тему просто и кратко."
    elif mode == "solve": system_prompt = base_instruction + " Ты — репетитор. Реши задачу по шагам."
    else: system_prompt = base_instruction + " Ты — учитель. Найди ошибки и объясни их."

    messages = [{"role": "system", "content": system_prompt}]
    if context: messages.append({"role": "system", "content": f"Контекст: {context}"})
    messages.append({"role": "user", "content": prompt})

    data = {"model": "GigaChat", "messages": messages, "temperature": 0.6}
    
    try:
        response = requests.post(url, headers=headers, json=data, verify=False, timeout=60)
        if response.status_code != 200:
            return "⚠️ Ошибка ИИ при генерации."
            
        return clean_latex(response.json()['choices'][0]['message']['content'])
    except Exception:
        return "⚠️ Превышено время ожидания ответа от ИИ. Попробуйте еще раз."

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

def send_message(user_id, chat_id, text, keyboard_type="single", clean_previous=True):
    if clean_previous:
        old_mid = get_last_mid(user_id)
        if old_mid:
            threading.Thread(target=delete_message, args=(chat_id, old_mid)).start()

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
        if response.status_code == 200:
            res_json = response.json()
            mid = res_json.get("message", {}).get("body", {}).get("mid")
            if mid:
                save_last_mid(user_id, mid)
    except Exception:
        pass

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
            clear_history(user_id)
            welcome = (
                "👋 *Привет! Я твой персональный ИИ-учитель.*\n\n"
                "👇 *Выбери действие на кнопках ниже* или просто напиши мне свой вопрос в чат!"
            )
            send_message(user_id, chat_id, welcome, keyboard_type="main", clean_previous=True)
        return
        
    if update_type == "message_callback":
        callback = update.get("callback", {})
        user_id = callback.get("user", {}).get("user_id")
        chat_id = callback.get("message", {}).get("recipient", {}).get("chat_id") or get_user_chat(user_id)
        payload = callback.get("payload")
        
        if payload == "btn_main_menu":
            set_user_state(user_id, "idle")
            clear_history(user_id)
            send_message(user_id, chat_id, "🏠 *Главное меню.* Чем еще я могу помочь?", keyboard_type="main", clean_previous=True)
        elif payload == "btn_chat_teacher":
            set_user_state(user_id, "chatting_with_teacher")
            clear_history(user_id)
            send_message(user_id, chat_id, "💬 *Отлично! Я готов обсудить с тобой учебу.*\n\nЗадавай любые вопросы. Чтобы выйти, нажми кнопку внизу.", keyboard_type="single", clean_previous=True)
        elif payload == "btn_explain":
            set_user_state(user_id, "waiting_for_explanation")
            clear_history(user_id) 
            send_message(user_id, chat_id, "📚 *Напиши тему*, которую нужно объяснить.", keyboard_type="single", clean_previous=True)
        elif payload == "btn_solve_photo":
            set_user_state(user_id, "waiting_for_solve_photo")
            clear_history(user_id) 
            send_message(user_id, chat_id, "📸 *Отправь мне фото с задачей*.", keyboard_type="single", clean_previous=True)
        elif payload == "btn_check_hw":
            set_user_state(user_id, "waiting_for_check_hw")
            clear_history(user_id) 
            send_message(user_id, chat_id, "📝 *Отправь фото или текст решения*.", keyboard_type="single", clean_previous=True)
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
        clear_history(user_id)
        welcome = (
            "👋 *Привет! Я твой персональный ИИ-учитель.*\n\n"
            "👇 *Выбери действие на кнопках ниже* или просто напиши мне свой вопрос в чат!"
        )
        send_message(user_id, chat_id, welcome, keyboard_type="main", clean_previous=True)
        return

    user_state = get_user_state(user_id)
    image_url = next((att.get("payload", {}).get("url") for att in attachments if att.get("type") == "image"), None)

    if image_url:
        send_message(user_id, chat_id, "📸 *Распознаю текст...*", keyboard_type="none", clean_previous=True)
        try:
            img_resp = requests.get(image_url, timeout=15, verify=False)
            image = Image.open(io.BytesIO(img_resp.content))
            extracted_text = pytesseract.image_to_string(image, lang='rus+eng')
            
            if not extracted_text.strip():
                send_message(user_id, chat_id, "😔 *Не удалось распознать текст.*", keyboard_type="single")
                return
            
            send_message(user_id, chat_id, "⏳ *Решаю задачу...*", keyboard_type="none", clean_previous=True)
            mode = "check" if user_state == "waiting_for_check_hw" else "solve"
            response_text = ask_gigachat(f"Задача:\n\n{extracted_text}", context="", mode=mode)
            
            send_message(user_id, chat_id, response_text, keyboard_type="single", clean_previous=True)
            clear_history(user_id)
            set_user_state(user_id, "idle")
        except Exception: send_message(user_id, chat_id, "⚠️ Ошибка обработки фото.", keyboard_type="single")
        return

    if text:
        send_message(user_id, chat_id, "⏳ *Думаю...*", keyboard_type="none", clean_previous=True)
        
        if user_state == "chatting_with_teacher":
            mode = "chat"
            context = get_history(user_id) 
        elif user_state == "waiting_for_explanation":
            mode = "explain"
            context = "" 
            set_user_state(user_id, "idle")
        elif user_state == "waiting_for_check_hw":
            mode = "check"
            context = "" 
            set_user_state(user_id, "idle")
        else:
            mode = "chat"
            context = "" 

        response_text = ask_gigachat(text, context=context, mode=mode)
        send_message(user_id, chat_id, response_text, keyboard_type="single", clean_previous=True)
        
        if mode == "chat":
            update_history(user_id, f"Ученик: {text}\nАссистент: {response_text}")
        else:
            clear_history(user_id)

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
            time.sleep(0.2)
        except Exception:
            time.sleep(2)

if __name__ == '__main__': main()
