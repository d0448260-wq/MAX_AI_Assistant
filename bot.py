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

print("=== ЗАПУСК ИИ-УЧИТЕЛЯ С РЕЖИМАМИ ===", flush=True)

MAX_TOKEN = "f9LHodD0cOLWL39U48Z8RsC2X4HIL1mYcfhxK4qmPXNCyP5nqUn6F7Pbi1QRJ_VdTv_SEobZNS7Y-t2g6NV-"
GIGACHAT_AUTH_KEY = "MDFhMWI2YTMtMzBmOS03ODdlLWI2MTYtMzk2NTE5YTQyODY5OjA2MmFlNDJlLTBkM2MtNDBkOC05NjU0LWNiYWQyMTVmYjE4Mg=="

BASE_URL = "https://platform-api2.max.ru"

def init_db():
    conn = sqlite3.connect('school_assistant.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        chat_id INTEGER,
                        current_session_id INTEGER,
                        state TEXT
                      )''')
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN chat_id INTEGER")
    except sqlite3.OperationalError:
        pass
    cursor.execute('''CREATE TABLE IF NOT EXISTS sessions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        title TEXT,
                        history TEXT
                      )''')
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
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json',
        'RqUID': str(uuid.uuid4()),
        'Authorization': f'Basic {GIGACHAT_AUTH_KEY}'
    }
    try:
        response = requests.post(url, headers=headers, data=payload, verify=False, timeout=10)
        if response.status_code != 200:
            print(f"ОШИБКА АВТОРИЗАЦИИ: {response.text}", flush=True)
        return response.json().get('access_token')
    except Exception as e:
        print(f"Ошибка сети GigaChat: {e}", flush=True)
        return None

def ask_gigachat(prompt, context="", mode="chat"):
    token = get_gigachat_token()
    if not token:
        return "Извините, произошла ошибка авторизации в ИИ."

    url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json', 'Authorization': f'Bearer {token}'}
    
    base_instruction = (
        "ТЫ ДОЛЖЕН СТРОГО СОБЛЮДАТЬ ЭТИ ПРАВИЛА ФОРМАТИРОВАНИЯ:\n"
        "1. НИКОГДА не используй символы $, $$, \\ и LaTeX-разметку (\\frac, \\cdot, \\sqrt и т.д.).\n"
        "2. Для степеней используй ЮНИКОД-СИМВОЛЫ: x², x³, y⁴ и т.д. (вместо x^2).\n"
        "3. Для дробей используй ЮНИКОД: ½, ⅓, ¼, ⅔ (вместо 1/2). Если дроби сложные, пиши через слэш (a/b).\n"
        "4. Для корня используй символ √ (например, √x).\n"
        "5. Для умножения используй символ × или ·.\n"
        "6. Для жирного текста используй *звездочки*.\n"
        "7. Для курсива используй _подчеркивания_.\n"
        "8. Заголовки пиши просто с новой строки, выделяя их жирным. НЕ используй решетки (#).\n"
        "9. Разбивай текст на короткие абзацы для удобства чтения.\n"
    )
    
    if mode == "chat":
        system_prompt = base_instruction + "Ты — дружелюбный онлайн-учитель для школьников 5-11 классов. Твоя цель — вести с учеником естественную беседу, отвечать на его вопросы по учебе и просто болтать. Если он просит объяснить тему — объясняй просто. Поддерживай диалог, будь вежливым, мотивирующим и используй эмодзи."
    elif mode == "explain":
        system_prompt = base_instruction + "Ты — дружелюбный ИИ-учитель. Объясни тему, которую спросил ученик, простым языком. НИКОГДА не осуждай за незнание. Структура ответа: 1. Простое объяснение. 2. Пример. 3. Три тренировочные задачи."
    elif mode == "solve":
        system_prompt = base_instruction + "Ты — отличный репетитор. Ученик прислал задачу (распознанную с фото). Реши её по шагам. Объясни каждое действие. Дай итоговый ответ."
    else: # check
        system_prompt = base_instruction + "Ты — заботливый учитель. Ученик прислал домашнее задание. Найди ошибки (если есть), объясни ПОЧЕМУ они возникли, как правильно, и какое правило нужно повторить. Пиши мягко."

    messages = [{"role": "system", "content": system_prompt}]
    if context:
        messages.append({"role": "user", "content": f"История нашего диалога: {context}"})
    messages.append({"role": "user", "content": prompt})

    data = {"model": "GigaChat", "messages": messages, "temperature": 0.7}

    try:
        response = requests.post(url, headers=headers, json=data, verify=False, timeout=30)
        res_json = response.json()
        
        if response.status_code != 200:
            print(f"ОШИБКА GIGACHAT API ({response.status_code}): {res_json}", flush=True)
            return f"Ошибка ИИ: {res_json.get('message', 'Неизвестная ошибка')}"
            
        return res_json['choices'][0]['message']['content']
    except Exception as e:
        print(f"Ошибка парсинга GigaChat: {e}", flush=True)
        return "Произошла ошибка при генерации ответа."

def get_main_keyboard():
    return {
        "type": "inline_keyboard",
        "payload": {
            "buttons": [
                [
                    {"type": "callback", "text": "💬 Поговорить с ИИ", "payload": "btn_chat_teacher"},
                    {"type": "callback", "text": "📚 Объяснить тему", "payload": "btn_explain"}
                ],
                [
                    {"type": "callback", "text": "📸 Решить задачу", "payload": "btn_solve_photo"},
                    {"type": "callback", "text": "📝 Проверить ДЗ", "payload": "btn_check_hw"}
                ],
                [
                    {"type": "callback", "text": "➕ Новый чат", "payload": "btn_new_chat"},
                    {"type": "callback", "text": "📂 Мои чаты", "payload": "btn_list_chats"}
                ]
            ]
        }
    }

def send_message(chat_id, text, show_keyboard=False):
    url = f"{BASE_URL}/messages"
    headers = {"Authorization": MAX_TOKEN}
    params = {"chat_id": chat_id}
    payload = {"text": text, "format": "markdown"}
    
    if show_keyboard:
        payload["attachments"] = [get_main_keyboard()]

    try:
        response = requests.post(url, headers=headers, params=params, json=payload, timeout=10, verify=False)
        if response.status_code != 200:
            print(f"ОШИБКА ОТПРАВКИ MAX ({chat_id}): {response.status_code} - {response.text}", flush=True)
    except Exception as e:
        print(f"Ошибка сети при отправке: {e}", flush=True)

def get_updates(marker=0):
    url = f"{BASE_URL}/updates"
    headers = {"Authorization": MAX_TOKEN}
    params = {"timeout": 30, "limit": 100}
    if marker:
        params["marker"] = marker
    try:
        response = requests.get(url, headers=headers, params=params, timeout=35, verify=False)
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
        if not chat_id:
            chat_id = get_user_chat(user_id)
            
        payload = callback.get("payload")
        
        if payload == "btn_chat_teacher":
            set_user_state(user_id, "chatting_with_teacher")
            send_message(chat_id, "💬 *Отлично! Я готов обсудить с тобой учебу.* Задавай любые вопросы, и мы все разберем в формате живого диалога. О чем хочешь поговорить?")
        elif payload == "btn_new_chat":
            create_new_session(user_id)
            send_message(chat_id, "✨ Создан новый чат! Теперь мы общаемся в чистом контексте. Задай свой вопрос.")
        elif payload == "btn_list_chats":
            sessions = get_user_sessions(user_id)
            buttons = [[{"type": "callback", "text": f"💬 {sess[1]}", "payload": f"switch_{sess[0]}"}] for sess in sessions]
            send_message(chat_id, "Выбери чат, к которому хочешь вернуться:", attachments=[{"type": "inline_keyboard", "payload": {"buttons": buttons}}])
        elif payload.startswith("switch_"):
            session_id = int(payload.split("_")[1])
            if switch_session(user_id, session_id):
                send_message(chat_id, "✅ Переключено на выбранный чат. Продолжаем!")
            else:
                send_message(chat_id, "❌ Ошибка: чат не найден.")
        elif payload == "btn_explain":
            set_user_state(user_id, "waiting_for_explanation")
            send_message(chat_id, "📚 Напиши тему, которую нужно объяснить (например: 'Теорема Пифагора').")
        elif payload == "btn_solve_photo":
            set_user_state(user_id, "waiting_for_solve_photo")
            send_message(chat_id, "📸 Отправь мне фото с задачей, и я решу её с подробным объяснением!")
        elif payload == "btn_check_hw":
            set_user_state(user_id, "waiting_for_check_hw")
            send_message(chat_id, "📝 Отправь фото или текст своего решения, и я проверю его без осуждения.")
        return

    if update_type != "message_created":
        return

    message = update.get("message", {})
    chat_id = message.get("recipient", {}).get("chat_id")
    user_id = message.get("sender", {}).get("user_id")
    text = message.get("body", {}).get("text", "")
    attachments = message.get("body", {}).get("attachments", [])

    if not chat_id or not user_id:
        return
    
    save_user_chat(user_id, chat_id)
    
    if text == "/start" or text == "/help":
        get_active_session(user_id)
        set_user_state(user_id, "idle")
        welcome = "👋 Привет! Я твой личный онлайн-учитель.\n\nВыбери нужный режим на кнопках ниже или просто напиши мне, если хочешь поболтать!"
        send_message(chat_id, welcome, show_keyboard=True)
        return

    user_state = get_user_state(user_id)
    image_url = None

    for att in attachments:
        if att.get("type") == "image":
            image_url = att.get("payload", {}).get("url")
            break

    if image_url:
        send_message(chat_id, "📸 Фото получено! Распознаю текст...")
        try:
            img_resp = requests.get(image_url, timeout=15, verify=False)
            image = Image.open(io.BytesIO(img_resp.content))
            extracted_text = pytesseract.image_to_string(image, lang='rus+eng')
            
            if not extracted_text.strip():
                send_message(chat_id, "😔 Не удалось распознать текст. Попробуй сфотографировать четче.")
                return
            
            send_message(chat_id, "✅ Текст распознан. Отправляю ИИ...")
            
            if user_state == "waiting_for_check_hw":
                mode = "check"
                prompt = f"Проверь мою домашнюю работу:\n\n{extracted_text}"
            else:
                mode = "solve"
                prompt = f"Реши эту задачу по шагам:\n\n{extracted_text}"
            
            response_text = ask_gigachat(prompt, context=get_history(user_id), mode=mode)
            send_message(chat_id, response_text, show_keyboard=True)
            update_history(user_id, f"Ученик отправил фото. Ассистент ответил.")
            set_user_state(user_id, "idle")
        except Exception as e:
            print(f"Ошибка обработки фото: {e}", flush=True)
            send_message(chat_id, "⚠️ Ошибка при обработке фото.")
        return

    if text:
        send_message(chat_id, "⏳ Думаю...")
        history = get_history(user_id)
        
        # Выбор режима в зависимости от состояния
        if user_state == "waiting_for_explanation":
            mode = "explain"
        elif user_state == "waiting_for_check_hw":
            mode = "check"
        else:
            # По умолчанию (если нажата кнопка "Поговорить" или просто написан текст)
            mode = "chat"
        
        response_text = ask_gigachat(text, context=history, mode=mode)
        send_message(chat_id, response_text, show_keyboard=True)
        update_history(user_id, f"Ученик: {text}\nАссистент: {response_text}")
        
        # Сбрасываем состояние, чтобы следующее сообщение снова пошло в чат (если не нажата кнопка)
        if user_state in ["waiting_for_explanation", "waiting_for_check_hw"]:
            set_user_state(user_id, "idle")

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
            print(f"Критическая ошибка: {e}", flush=True)
            time.sleep(5)

if __name__ == '__main__':
    main()
