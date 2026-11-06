import requests
import time
import sqlite3
import uuid
import io
import os
from PIL import Image
import pytesseract
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

print("=========================================", flush=True)
print("ЗАПУСК НОВОГО КОДА С КНОПКАМИ...", flush=True)
print("=========================================", flush=True)

MAX_TOKEN = "f9LHodD0cOLWL39U48Z8RsC2X4HIL1mYcfhxK4qmPXNCyP5nqUn6F7Pbi1QRJ_VdTv_SEobZNS7Y-t2g6NV-"
GIGACHAT_AUTH_KEY = "MDFhMWIxMzEtYjNiZi03N2EwLThmZTUtZjMzMWMwOWYwNzI5OjBiZTY4Njk4LTc4ZWYtNDllMS1hYzI3LWUwZGFmOTQxNGQ0NA=="

BASE_URL = "https://platform-api2.max.ru"

def init_db():
    conn = sqlite3.connect('school_assistant.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        current_session_id INTEGER,
                        state TEXT
                      )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS sessions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        title TEXT,
                        history TEXT
                      )''')
    conn.commit()
    conn.close()

def get_active_session(user_id):
    conn = sqlite3.connect('school_assistant.db')
    cursor = conn.cursor()
    cursor.execute("SELECT current_session_id FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row or not row[0]:
        cursor.execute("INSERT INTO sessions (user_id, title, history) VALUES (?, ?, ?)", (user_id, "Чат 1", ""))
        session_id = cursor.lastrowid
        cursor.execute("INSERT OR REPLACE INTO users (user_id, current_session_id) VALUES (?, ?)", (user_id, session_id))
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
    history = (history + "\n" + new_message)[-2000:]
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
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json',
        'RqUID': str(uuid.uuid4()),
        'Authorization': f'Basic {GIGACHAT_AUTH_KEY}'
    }
    try:
        response = requests.post(url, headers=headers, data=payload, verify=False, timeout=10)
        print(f"DEBUG AUTH GIGACHAT: {response.status_code} -> {response.text}", flush=True)
        return response.json().get('access_token')
    except Exception as e:
        print(f"Ошибка сети GigaChat: {e}", flush=True)
        return None

def ask_gigachat(prompt, context="", mode="explain"):
    token = get_gigachat_token()
    if not token:
        return "Извините, произошла ошибка авторизации в ИИ (проверьте логи)."

    url = "https://api.giga.chat/v1/chat/completions"
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json', 'Authorization': f'Bearer {token}'}
    
    system_prompt = "Ты — дружелюбный ИИ-ассистент для школьников. Отвечай понятно."
    messages = [{"role": "system", "content": system_prompt}]
    if context:
        messages.append({"role": "user", "content": f"История: {context}"})
    messages.append({"role": "user", "content": prompt})

    data = {"model": "GigaChat", "messages": messages, "temperature": 0.7}

    try:
        response = requests.post(url, headers=headers, json=data, verify=False, timeout=30)
        print(f"DEBUG API GIGACHAT: {response.status_code} -> {response.text[:150]}", flush=True)
        return response.json()['choices'][0]['message']['content']
    except Exception as e:
        print(f"Ошибка запроса к GigaChat: {e}", flush=True)
        return "Ошибка при генерации ответа."

def get_main_keyboard():
    return {
        "type": "inline_keyboard",
        "payload": {
            "buttons": [
                [
                    {"type": "callback", "text": "➕ Новый чат", "payload": "btn_new_chat"},
                    {"type": "callback", "text": "📂 Мои чаты", "payload": "btn_list_chats"}
                ],
                [
                    {"type": "callback", "text": "📚 Объяснить тему", "payload": "btn_explain"},
                    {"type": "callback", "text": "📸 Решить задачу с фото", "payload": "btn_solve_photo"}
                ]
            ]
        }
    }

def send_message(chat_id, text, attachments=None):
    url = f"{BASE_URL}/messages"
    headers = {"Authorization": MAX_TOKEN}
    params = {"chat_id": chat_id}
    payload = {"text": text}
    
    if not attachments:
        payload["attachments"] = [get_main_keyboard()]
    else:
        payload["attachments"] = attachments

    try:
        response = requests.post(url, headers=headers, params=params, json=payload, timeout=10)
        print(f"DEBUG SEND MSG: {response.status_code} -> {response.text}", flush=True)
    except Exception as e:
        print(f"Ошибка отправки: {e}", flush=True)

def get_updates(marker=0):
    url = f"{BASE_URL}/updates"
    headers = {"Authorization": MAX_TOKEN}
    params = {"timeout": 30, "limit": 100}
    if marker:
        params["marker"] = marker
    try:
        response = requests.get(url, headers=headers, params=params, timeout=35)
        if response.status_code == 200:
            return response.json()
        return {}
    except requests.exceptions.ReadTimeout:
        pass
    except Exception:
        return {}

def process_update(update):
    update_type = update.get("update_type")
    
    if update_type == "message_callback":
        callback = update.get("callback", {})
        user_id = callback.get("user", {}).get("user_id")
        chat_id = callback.get("message", {}).get("recipient", {}).get("chat_id")
        payload = callback.get("payload")
        
        if payload == "btn_new_chat":
            create_new_session(user_id)
            send_message(chat_id, "✨ Создан новый чат! Задай свой вопрос.")
        elif payload == "btn_list_chats":
            sessions = get_user_sessions(user_id)
            buttons = [[{"type": "callback", "text": f"💬 {sess[1]}", "payload": f"switch_{sess[0]}"}] for sess in sessions]
            send_message(chat_id, "Выбери чат:", attachments=[{"type": "inline_keyboard", "payload": {"buttons": buttons}}])
        elif payload.startswith("switch_"):
            switch_session(user_id, int(payload.split("_")[1]))
            send_message(chat_id, "✅ Переключено на выбранный чат.")
        return

    if update_type != "message_created":
        return

    message = update.get("message", {})
    chat_id = message.get("recipient", {}).get("chat_id")
    user_id = message.get("sender", {}).get("user_id")
    text = message.get("body", {}).get("text", "")

    if not chat_id or not user_id:
        return
    
    if text == "/start" or text == "/help":
        get_active_session(user_id)
        welcome = "👋 Привет! Я твой ИИ-ассистент.\n\nИспользуй кнопки ниже, чтобы создать новый чат или задать вопрос!"
        send_message(chat_id, welcome)
        return

    if text:
        send_message(chat_id, "⏳ Думаю...")
        history = get_history(user_id)
        response_text = ask_gigachat(text, context=history)
        send_message(chat_id, response_text)
        update_history(user_id, f"Ученик: {text}\nАссистент: {response_text}")

def main():
    init_db()
    print("Бот запущен и слушает сообщения...", flush=True)
    marker = 0
    while True:
        try:
            updates_data = get_updates(marker)
            if updates_data and "updates" in updates_data:
                for update in updates_data["updates"]:
                    process_update(update)
                    marker = update.get("timestamp", marker) 
            time.sleep(1)
        except Exception as e:
            time.sleep(5)

if __name__ == '__main__':
    main()
