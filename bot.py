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

MAX_TOKEN = "f9LHodD0cOLWL39U48Z8RsC2X4HIL1mYcfhxK4qmPXNCyP5nqUn6F7Pbi1QRJ_VdTv_SEobZNS7Y-t2g6NV-"
GIGACHAT_AUTH_KEY = "MDFhMWIxMzEtYjNiZi03N2EwLThmZTUtZjMzMWMwOWYwNzI5OmE0MWExMWZjLWYwYTEtNGM1Ny1hYzY5LTVkOWFkMzA0MTFmMA=="

BASE_URL = "https://platform-api2.max.ru"

def init_db():
    conn = sqlite3.connect('school_assistant.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        history TEXT,
                        state TEXT
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
        return response.json().get('access_token')
    except Exception as e:
        print(f"Ошибка авторизации GigaChat: {e}", flush=True)
        return None

def ask_gigachat(prompt, context="", mode="explain"):
    token = get_gigachat_token()
    if not token:
        return "Извините, произошла ошибка подключения к ИИ."

    url = "https://api.giga.chat/v1/chat/completions"
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json', 'Authorization': f'Bearer {token}'}
    
    if mode == "explain":
        system_prompt = "Ты — дружелюбный ИИ-ассистент для школьников 5-11 классов. Объясняй сложные темы простым языком. НИКОГДА не осуждай за незнание. Структура ответа: 1. Простое объяснение. 2. Пример. 3. Три тренировочные задачи. Используй эмодзи и Markdown."
    elif mode == "solve":
        system_prompt = "Ты — отличный репетитор. Ученик прислал задачу (распознанную с фото). Реши её по шагам. Объясни каждое действие. Дай итоговый ответ. Используй Markdown."
    else:
        system_prompt = "Ты — заботливый учитель. Ученик прислал домашнее задание. Найди ошибки (если есть), объясни ПОЧЕМУ они возникли, как правильно, и какое правило нужно повторить. Пиши мягко. Используй Markdown."

    messages = [{"role": "system", "content": system_prompt}]
    if context:
        messages.append({"role": "user", "content": f"Контекст диалога: {context}"})
    messages.append({"role": "user", "content": prompt})

    data = {"model": "GigaChat-2", "messages": messages, "temperature": 0.7}

    try:
        response = requests.post(url, headers=headers, json=data, verify=False, timeout=30)
        print(f"ОТВЕТ ОТ GIGACHAT: {response.status_code}", flush=True)
        return response.json()['choices'][0]['message']['content']
    except Exception as e:
        print(f"Ошибка запроса к GigaChat: {e}", flush=True)
        return "Произошла ошибка при генерации ответа."

def send_message(chat_id, text, with_keyboard=False):
    url = f"{BASE_URL}/messages"
    headers = {"Authorization": MAX_TOKEN}
    params = {"chat_id": chat_id}
    payload = {"text": text}

    if with_keyboard:
        payload["attachments"] = [
            {
                "type": "inline_keyboard",
                "payload": {
                    "buttons": [
                        [
                            {"type": "callback", "text": "📚 Объяснить тему", "payload": "btn_explain"},
                            {"type": "callback", "text": "📸 Решить задачу с фото", "payload": "btn_solve_photo"}
                        ],
                        [
                            {"type": "callback", "text": "📝 Проверить ДЗ", "payload": "btn_check_hw"},
                            {"type": "callback", "text": "ℹ️ Помощь", "payload": "btn_help"}
                        ]
                    ]
                }
            }
        ]

    try:
        response = requests.post(url, headers=headers, params=params, json=payload, timeout=10)
        print(f"ОТВЕТ ОТ MAX (отправка): {response.status_code} - {response.text}", flush=True)
    except Exception as e:
        print(f"Ошибка отправки send_message: {e}", flush=True)

def get_updates(marker=0):
    url = f"{BASE_URL}/updates"
    headers = {"Authorization": MAX_TOKEN}
    params = {"timeout": 30, "limit": 100}
    if marker:
        params["marker"] = marker
    try:
        response = requests.get(url, headers=headers, params=params, timeout=35)
        if response.status_code == 200:
            data = response.json()
            if data.get("updates"):
                print(f"ПОЛУЧЕНЫ ДАННЫЕ ОТ MAX: {data}", flush=True)
            return data
        else:
            print(f"Ошибка Updates (Status {response.status_code}): {response.text}", flush=True)
            return {}
    except requests.exceptions.ReadTimeout:
        pass
    except Exception as e:
        print(f"Ошибка get_updates: {e}", flush=True)
        return {}

def process_update(update):
    update_type = update.get("update_type")
    
    if update_type == "message_callback":
        callback = update.get("callback", {})
        user_id = callback.get("user", {}).get("user_id")
        chat_id = callback.get("message", {}).get("recipient", {}).get("chat_id")
        payload = callback.get("payload")
        
        if payload == "btn_help":
            send_message(chat_id, "👋 Я умею: \n1. Объяснять темы.\n2. Решать задачи по фото.\n3. Проверять твои решения.\n\nПросто выбери кнопку или напиши вопрос!", with_keyboard=True)
        elif payload == "btn_explain":
            send_message(chat_id, "Напиши тему, которую нужно объяснить (например: 'Теорема Пифагора').")
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
    
    if text == "/start" or text == "/help":
        welcome = "👋 Привет! Я твой персональный ИИ-ассистент. Выбери действие на кнопках ниже или просто напиши свой вопрос!"
        send_message(chat_id, welcome, with_keyboard=True)
        set_user_state(user_id, "idle")
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
            img_resp = requests.get(image_url, timeout=15)
            image = Image.open(io.BytesIO(img_resp.content))
            extracted_text = pytesseract.image_to_string(image, lang='rus+eng')
            
            if not extracted_text.strip():
                send_message(chat_id, "😔 Не удалось распознать текст. Попробуй сфотографировать четче или напиши задание текстом.")
                return
            
            send_message(chat_id, "✅ Текст распознан. Отправляю ИИ на решение...")
            
            if user_state == "waiting_for_check_hw":
                mode = "check"
                prompt = f"Проверь мою домашнюю работу:\n\n{extracted_text}"
            else:
                mode = "solve"
                prompt = f"Реши эту задачу по шагам и объясни:\n\n{extracted_text}"
            
            response_text = ask_gigachat(prompt, context=get_history(user_id), mode=mode)
            send_message(chat_id, response_text, with_keyboard=True)
            update_history(user_id, f"Ученик отправил фото. Ассистент ответил.")
            set_user_state(user_id, "idle")
            
        except Exception as e:
            print(f"Ошибка обработки фото: {e}", flush=True)
            send_message(chat_id, "⚠️ Ошибка при обработке фото. Попробуй еще раз.")
        return

    if text:
        send_message(chat_id, "⏳ Думаю над ответом...")
        history = get_history(user_id)
        mode = "check" if user_state == "waiting_for_check_hw" else "explain"
        response_text = ask_gigachat(text, context=history, mode=mode)
        send_message(chat_id, response_text, with_keyboard=True)
        update_history(user_id, f"Ученик: {text}\nАссистент: {response_text}")
        set_user_state(user_id, "idle")

def main():
    init_db()
    print("Бот запущен! Слушаю обновления...", flush=True)
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
            print(f"Критическая ошибка в цикле: {e}", flush=True)
            time.sleep(5)

if __name__ == '__main__':
    main()
