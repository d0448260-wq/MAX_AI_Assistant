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

BASE_URL = "https://botapi.max.ru"

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
        response = requests.post(url, headers=headers, data=payload, verify=False, timeout=10)
        return response.json().get('access_token')
    except Exception as e:
        print(f"Error GigaChat auth: {e}", flush=True)
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
        response = requests.post(url, headers=headers, json=data, verify=False, timeout=30)
        return response.json()['choices'][0]['message']['content']
    except Exception as e:
        print(f"Error GigaChat request: {e}", flush=True)
        return "Произошла ошибка при генерации ответа."

def send_message(chat_id, text):
    url = f"{BASE_URL}/messages"
    headers = {"Authorization": MAX_TOKEN}
    payload = {"chat_id": chat_id, "text": text}
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        if response.status_code != 200:
            print(f"Send error: {response.text}", flush=True)
    except Exception as e:
        print(f"Error send_message: {e}", flush=True)

def get_updates(offset=0):
    url = f"{BASE_URL}/updates"
    headers = {"Authorization": MAX_TOKEN}
    params = {"offset": offset, "timeout": 30}
    try:
        response = requests.get(url, headers=headers, params=params, timeout=35)
        if response.status_code == 200:
            data = response.json()
            if data and data.get("result"):
                print(f"ПОЛУЧЕНЫ ДАННЫЕ ОТ MAX: {data}", flush=True)
            return data
        else:
            print(f"Updates error (Status {response.status_code}): {response.text}", flush=True)
            return {}
    except requests.exceptions.ReadTimeout:
        pass
    except Exception as e:
        print(f"Error get_updates: {e}", flush=True)
        return {}

def process_update(update):
    print(f"ОБРАБОТКА ОБНОВЛЕНИЯ: {update}", flush=True)
    
    if "message" not in update:
        print("В обновлении нет ключа 'message'", flush=True)
        return

    message = update["message"]
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    
    if not chat_id or not user_id:
        print("Не удалось найти chat_id или user_id", flush=True)
        return
    
    if "text" in message:
        text = message["text"]
        print(f"Текст сообщения: {text}", flush=True)
        
        if text == "/start" or text == "/help":
            welcome = "👋 Привет! Я твой персональный ИИ-ассистент."
            send_message(chat_id, welcome)
            return

        send_message(chat_id, "⏳ Секунду, готовлю объяснение...")
        history = get_history(user_id)
        response_text = ask_gigachat(text, context=history, mode="explain")
        send_message(chat_id, response_text)
        update_history(user_id, f"Ученик: {text}\nАссистент: {response_text}")

def main():
    init_db()
    print("Бот запущен! Слушаю обновления...", flush=True)
    offset = 0
    
    while True:
        try:
            updates = get_updates(offset)
            
            if updates and "result" in updates:
                for update in updates["result"]:
                    process_update(update)
                    offset = update.get("update_id", offset) + 1
                    
            time.sleep(1)
        except Exception as e:
            print(f"Критическая ошибка в цикле: {e}", flush=True)
            time.sleep(5)

if __name__ == '__main__':
    main()
