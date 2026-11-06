import requests
import time
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

MAX_TOKEN = "f9LHodD0cOLWL39U48Z8RsC2X4HIL1mYcfhxK4qmPXNCyP5nqUn6F7Pbi1QRJ_VdTv_SEobZNS7Y-t2g6NV-"
BASE_URL = "https://platform-api2.max.ru"

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
        else:
            print(f"ОШИБКА API: {response.status_code} - {response.text}", flush=True)
            return {}
    except requests.exceptions.ReadTimeout:
        pass
    except Exception as e:
        print(f"Ошибка сети: {e}", flush=True)
        return {}

def send_message(chat_id, text):
    url = f"{BASE_URL}/messages"
    headers = {"Authorization": MAX_TOKEN}
    params = {"chat_id": chat_id}
    payload = {"text": text}
    try:
        response = requests.post(url, headers=headers, params=params, json=payload, timeout=10)
        print(f"ОТПРАВКА: {response.status_code} - {response.text}", flush=True)
    except Exception as e:
        print(f"Ошибка отправки: {e}", flush=True)

def main():
    print("ТЕСТОВЫЙ БОТ ЗАПУЩЕН!", flush=True)
    marker = 0
    while True:
        updates_data = get_updates(marker)
        
        if updates_data and "updates" in updates_data:
            for update in updates_data["updates"]:
                print(f"ПОЛУЧЕНО СООБЩЕНИЕ: {update}", flush=True)
                
                if update.get("update_type") == "message_created":
                    message = update.get("message", {})
                    chat_id = message.get("recipient", {}).get("chat_id")
                    text = message.get("body", {}).get("text", "")
                    
                    if chat_id:
                        send_message(chat_id, f"Я получил твой текст: {text}")
                        
                marker = update.get("timestamp", marker) 
                
        time.sleep(1)

if __name__ == '__main__':
    main()
