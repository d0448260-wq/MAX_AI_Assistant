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
GIGACHAT_AUTH_KEY = "sk_2af1ad731243b8e5f04799d4a82c4c59da3c296b3cb6ad8e"

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

def send_message(chat_id, text):
    url = f"{BASE_URL}/messages"
    params = {"access_token": MAX_TOKEN}
    payload = {"chat_id": chat_id, "text": text}
    try:
        response = requests.post(url, params=params, json=payload)
        if response.status_code != 200:
            print(f"Send error: {response.text}")
    except Exception as e:
        print(f"Error send_message: {e}")

def get_updates(offset=0):
    url = f"{BASE_URL}/updates"
    params = {"access_token": MAX_TOKEN, "offset": offset, "timeout": 30}
    try:
        response = requests.get(url, params=params, timeout=35)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Updates error: {response.text}")
            return {}
    except Exception as e:
        print(f"Error get_updates: {e}")
        return {}

def process_update(update):
    if "message" not in update:
        return

    message = update["message"]
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    
    if "text" in message:
        text = message["text"]
        
        if text == "/start" or text == "/help":
            welcome = (
                "👋 *Привет! Я твой персональный ИИ-ассистент.*\n\n"
                "📚 Напиши тему, которую нужно объяснить (например: 'Объясни теорему Пифагора').\n"
                "📝 Или отправь фото твоего решения, и я проверю его без осуждения."
            )
            send_message(chat_id, welcome)
            return

        send_message(chat_id, "⏳ Секунду, готовлю объяснение...")
        history = get_history(user_id)
        response_text = ask_gigachat(text, context=history, mode="explain")
        send_message(chat_id, response_text)
        update_history(user_id, f"Ученик: {text}\nАссистент: {response_text}")

    elif "photo" in message:
        send_message(chat_id, "📸 Получил фото! Распознаю текст...")
        photos = message["photo"]
        file_id = photos[-1]["file_id"]
        
        try:
            file_info_url = f"{BASE_URL}/files/{file_id}"
            params = {"access_token": MAX_TOKEN}
            file_info_resp = requests.get(file_info_url, params=params)
            file_info = file_info_resp.json()
            
            file_url = file_info.get("file_path") or file_info.get("url")
            
            if file_url:
                if not file_url.startswith("http"):
                    file_url = f"{BASE_URL}/{file_url}"
                
                img_resp = requests.get(file_url)
                image = Image.open(io.BytesIO(img_resp.content))
                extracted_text = pytesseract.image_to_string(image, lang='rus+eng')
                
                if extracted_text.strip():
                    send_message(chat_id, "📝 Текст распознан! Проверяю...")
                    prompt = f"Проверь мою домашнюю работу:\n\n{extracted_text}"
                    history = get_history(user_id)
                    response_text = ask_gigachat(prompt, context=history, mode="check")
                    send_message(chat_id, response_text)
                    update_history(user_id, f"Ученик отправил фото ДЗ. Ассистент проверил.")
                else:
                    send_message(chat_id, "😔 Не удалось распознать текст. Сделай фото четче или напиши задание текстом.")
            else:
                send_message(chat_id, "⚠️ Не удалось получить ссылку на фото.")
                
        except Exception as e:
            print(f"Error photo processing: {e}")
            send_message(chat_id, "⚠️ Ошибка обработки фото. Отправь задание текстом.")

def main():
    init_db()
    print("Bot started! Listening for updates...")
    offset = 0
    
    while True:
        updates = get_updates(offset)
        
        if updates and "result" in updates:
            for update in updates["result"]:
                process_update(update)
                offset = update["update_id"] + 1
                
        time.sleep(1)

if __name__ == '__main__':
    main()
