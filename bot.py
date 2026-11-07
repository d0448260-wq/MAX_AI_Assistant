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

print("=== ЗАПУСК БОТА С ОБРАБОТКОЙ КНОПКИ 'НАЧАТЬ' ===", flush=True)

MAX_TOKEN = "f9LHodD0cOLWL39U48Z8RsC2X4HIL1mYcfhxK4qmPXNCyP5nqUn6F7Pbi1QRJ_VdTv_SEobZNS7Y-t2g6NV-"
GIGACHAT_AUTH_KEY = "MDFhMWI2YWQtOWFlZi03MTMyLWE4YzctMmNkZTkzNGFlY2UyOjQyMmQ2YjU2LTBkMjctNDYwMC04MTlmLTgxMzgxNDY4ZjA2MA=="

BASE_URL = "https://platform-api2.max.ru"

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
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, chat_id INTEGER, current_session_id INTEGER, state TEXT)''')
    try: cursor.execute("ALTER TABLE users ADD COLUMN chat_id INTEGER")
    except sqlite3.OperationalError: pass
    cursor.execute('''CREATE TABLE IF NOT EXISTS sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, title TEXT, history TEXT)''')
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

def get_active_session(user_id):
    conn = sqlite3.connect('school_assistant.db')
    cursor = conn.cursor()
    cursor.execute("SELECT current_session_id FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row or not row[0]:
        cursor.execute("INSERT INTO sessions (user_id, title, history) VALUES (?, ?, ?)", (user_id, "Чат 1", ""))
        session_id = cursor.lastrowid
        cursor.execute("INSERT OR IGNORE INTO users (user_id, current_session_id) VALUES (?, ?)", (user_id, session_id))
        cursor.execute("UPDATE users SET current_session_id = ? WHERE user_id = ?", (session_id, user_id))
        conn.commit()
        conn.close()
        return session_id
    conn.close()
    return row[0]

def create_new_session(user_id):
    conn = sqlite3.connect('school_assistant.db')
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ?", (user_id,))
    count = cursor.fetchone()[0]
    title = f"Чат {count + 1}"
    cursor.execute("INSERT INTO sessions (user_id, title, history) VALUES (?, ?, ?)", (user_id, title, ""))
    session_id = cursor.lastrowid
    cursor.execute("UPDATE users SET current_session_id = ? WHERE user_id = ?", (session_id, user_id))
    conn.commit()
    conn.close()
    return session_id

def switch_session(user_id, session_id):
    conn = sqlite3.connect('school_assistant.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM sessions WHERE id = ? AND user_id = ?", (session_id, user_id))
    if cursor.fetchone():
        cursor.execute("UPDATE users SET current_session_id = ? WHERE user_id = ?", (session_id, user_id))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

def get_user_sessions(user_id):
    conn = sqlite3.connect('school_assistant.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, title FROM sessions WHERE user_id = ? ORDER BY id DESC", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_history(user_id):
    session_id = get_active_session(user_id)
    conn = sqlite3.connect('school_assistant.db')
    cursor = conn.cursor()
    cursor.execute("SELECT history FROM sessions WHERE id = ?", (session_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row and row[0] else ""

def update_history(user_id, new_message):
    session_id = get_active_session(user_id)
    conn = sqlite3.connect('school_assistant.db')
    cursor = conn.cursor()
    cursor.execute("SELECT history FROM sessions WHERE id = ?", (session_id,))
    row = cursor.fetchone()
    history = row[0] if row and row[0] else ""
    history = (history + "\n" + new_message)[-4000:]
    cursor.execute("UPDATE sessions SET history = ? WHERE id = ?", (history, session_id))
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
    url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    payload = 'scope=GIGACHAT_API_PERS'
    headers = {'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json', 'RqUID': str(uuid.uuid4()), 'Authorization': f'Basic {GIGACHAT_AUTH_KEY}'}
    try:
        response = requests.post(url, headers=headers, data=payload, verify=False, timeout=10)
        return response.json().get('access_token')
    except Exception: return None

def ask_gigachat(prompt, context="", mode="chat"):
    token = get_gigachat_token()
    if not token: return "Извините, произошла ошибка авторизации в ИИ."

    url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json', 'Authorization': f'Bearer {token}'}
    
    base_instruction = "ТЫ ДОЛЖЕН СТРОГО СОБЛЮДАТЬ ЭТИ ПРАВИЛА: 1. Без $ и \\. 2. Степени: x², y³. 3. Дроби: ½ или a/b. 4. Корень: √. 5. Умножение: ×. 6. Жирный: *текст*. 7. Курсив: _текст_. 8. Без решеток для заголовков.\n"
    
    if mode == "chat": system_prompt = base_instruction + "Ты — дружелюбный онлайн-учитель. Веди естественную беседу."
    elif mode == "explain": system_prompt = base_instruction + "Ты — ИИ-учитель. Объясни тему просто, дай пример и 3 задачи."
    elif mode == "solve": system_prompt = base_instruction + "Ты — репетитор. Реши задачу по шагам."
    else: system_prompt = base_instruction + "Ты — учитель. Найди ошибки в ДЗ и объясни их."

    messages = [{"role": "system", "content": system_prompt}]
    if context: messages.append({"role": "user", "content": f"История: {context}"})
    messages.append({"role": "user", "content": prompt})

    data = {"model": "GigaChat", "messages": messages, "temperature": 0.7}
    try:
        response = requests.post(url, headers=headers, json=data, verify=False, timeout=30)
        if response.status_code != 200: return f"Ошибка ИИ."
        return clean_latex(response.json()['choices'][0]['message']['content'])
    except Exception: return "Ошибка при генерации ответа."

def get_main_keyboard():
    return {
        "type": "inline_keyboard",
        "payload": {
            "buttons": [
                [{"type": "callback", "text": "💬 Поговорить с ИИ", "payload": "btn_chat_teacher"}, {"type": "callback", "text": "📚 Объяснить тему", "payload": "btn_explain"}],
                [{"type": "callback", "text": "📸 Решить задачу", "payload": "btn_solve_photo"}, {"type": "callback", "text": "📝 Проверить ДЗ", "payload": "btn_check_hw"}],
                [{"type": "callback", "text": "➕ Новый чат", "payload": "btn_new_chat"}, {"type": "callback", "text": "📂 Мои чаты", "payload": "btn_list_chats"}]
            ]
        }
    }

def send_message(chat_id, text, show_keyboard=False):
    url = f"{BASE_URL}/messages"
    headers = {"Authorization": MAX_TOKEN}
    params = {"chat_id": chat_id}
    payload = {"text": text, "format": "markdown"}
    if show_keyboard: payload["attachments"] = [get_main_keyboard()]
    try: requests.post(url, headers=headers, params=params, json=payload, timeout=10, verify=False)
    except Exception as e: print(f"Ошибка отправки: {e}", flush=True)

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
    
    # ОБРАБОТКА НАЖАТИЯ КНОПКИ "НАЧАТЬ"
    if update_type == "bot_started":
        chat_id = update.get("chat_id")
        user_id = update.get("user", {}).get("user_id")
        if chat_id and user_id:
            save_user_chat(user_id, chat_id)
            get_active_session(user_id)
            set_user_state(user_id, "idle")
            welcome = "👋 Привет! Я твой личный онлайн-учитель.\n\nВыбери нужный режим на кнопках ниже или просто напиши мне, если хочешь поболтать!"
            send_message(chat_id, welcome, show_keyboard=True)
        return
        
    if update_type == "message_callback":
        callback = update.get("callback", {})
        user_id = callback.get("user", {}).get("user_id")
        chat_id = callback.get("message", {}).get("recipient", {}).get("chat_id") or get_user_chat(user_id)
        payload = callback.get("payload")
        
        if payload == "btn_chat_teacher":
            set_user_state(user_id, "chatting_with_teacher")
            send_message(chat_id, "💬 *Отлично! Я готов обсудить с тобой учебу.* Задавай любые вопросы. О чем хочешь поговорить?")
        elif payload == "btn_new_chat":
            create_new_session(user_id)
            send_message(chat_id, "✨ Создан новый чат! Задай свой вопрос.")
        elif payload == "btn_list_chats":
            sessions = get_user_sessions(user_id)
            buttons = [[{"type": "callback", "text": f"💬 {sess[1]}", "payload": f"switch_{sess[0]}"}] for sess in sessions]
            send_message(chat_id, "Выбери чат:", attachments=[{"type": "inline_keyboard", "payload": {"buttons": buttons}}])
        elif payload.startswith("switch_"):
            if switch_session(user_id, int(payload.split("_")[1])): send_message(chat_id, "✅ Переключено!")
            else: send_message(chat_id, "❌ Ошибка.")
        elif payload == "btn_explain":
            set_user_state(user_id, "waiting_for_explanation")
            send_message(chat_id, "📚 Напиши тему, которую нужно объяснить.")
        elif payload == "btn_solve_photo":
            set_user_state(user_id, "waiting_for_solve_photo")
            send_message(chat_id, "📸 Отправь фото с задачей.")
        elif payload == "btn_check_hw":
            set_user_state(user_id, "waiting_for_check_hw")
            send_message(chat_id, "📝 Отправь фото или текст решения.")
        return

    if update_type != "message_created": return

    message = update.get("message", {})
    chat_id = message.get("recipient", {}).get("chat_id")
    user_id = message.get("sender", {}).get("user_id")
    text = message.get("body", {}).get("text", "")
    attachments = message.get("body", {}).get("attachments", [])

    if not chat_id or not user_id: return
    save_user_chat(user_id, chat_id)
    
    # Обработка /start (на случай, если пришел текстом)
    if text == "/start" or text == "/help":
        get_active_session(user_id)
        set_user_state(user_id, "idle")
        welcome = "👋 Привет! Я твой личный онлайн-учитель.\n\nВыбери нужный режим на кнопках ниже или просто напиши мне, если хочешь поболтать!"
        send_message(chat_id, welcome, show_keyboard=True)
        return

    user_state = get_user_state(user_id)
    image_url = next((att.get("payload", {}).get("url") for att in attachments if att.get("type") == "image"), None)

    if image_url:
        send_message(chat_id, "📸 Фото получено! Распознаю...")
        try:
            img_resp = requests.get(image_url, timeout=15, verify=False)
            image = Image.open(io.BytesIO(img_resp.content))
            extracted_text = pytesseract.image_to_string(image, lang='rus+eng')
            
            if not extracted_text.strip():
                send_message(chat_id, "😔 Текст не распознан.")
                return
            
            send_message(chat_id, "✅ Текст распознан. Отправляю ИИ...")
            mode = "check" if user_state == "waiting_for_check_hw" else "solve"
            response_text = ask_gigachat(f"Задача:\n\n{extracted_text}", context=get_history(user_id), mode=mode)
            send_message(chat_id, response_text, show_keyboard=True)
            update_history(user_id, "Фото решено.")
            set_user_state(user_id, "idle")
        except Exception: send_message(chat_id, "⚠️ Ошибка обработки фото.")
        return

    if text:
        send_message(chat_id, "⏳ Думаю...")
        mode = "explain" if user_state == "waiting_for_explanation" else ("check" if user_state == "waiting_for_check_hw" else "chat")
        response_text = ask_gigachat(text, context=get_history(user_id), mode=mode)
        send_message(chat_id, response_text, show_keyboard=True)
        update_history(user_id, f"Ученик: {text}\nАссистент: {response_text}")
        if user_state in ["waiting_for_explanation", "waiting_for_check_hw"]: set_user_state(user_id, "idle")

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
