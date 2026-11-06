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

def send_message(chat_id, text):
    url = f"{BASE_URL}/messages"
    headers = {"Authorization": MAX_TOKEN}
    params = {"chat_id": chat_id}
    payload = {"text": text}
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
    if update.get("update_type") != "message_created":
        return

    message = update.get("message", {})
    chat_id = message.get("recipient", {}).get("chat_id")
    user_id = message.get("sender", {}).get("user_id")
    text = message.get("body", {}).get("text", "")

    if not chat_id or not user_id or not text:
        return
    
    if text == "/start" or text == "/help":
        welcome = "👋 Привет! Я твой персональный ИИ-ассистент. Задай мне вопрос!"
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
