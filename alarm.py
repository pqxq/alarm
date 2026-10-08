import time
import os
import ctypes
import requests
from datetime import datetime
from winotify import Notification, audio
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("API")
OBLAST_ID = "15"  # Миколаївська область

# Шляхи до кастомних .mp3 файлів
YELLOW_SOUND_PATH = "yellow.mp3"  # Звук для жовтого рівня
RED_SOUND_PATH = "red.mp3"        # Звук для червоного рівня
CLEAR_SOUND_PATH = "clear.mp3"    # Звук відбою

HEADERS = {
    "accept": "application/json",
    "Authorization": API_KEY,
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

current_state = None  # True / False
current_level = None  # "Yellow" / "Red"


def play_mp3(file_path, repeat=1):
    """
    Відтворює mp3 файл вказану кількість разів (repeat).
    Використовує 'wait', щоб дочекатися завершення першого програвання перед повтором.
    """
    if not os.path.exists(file_path):
        print(f"[!] Файл звуку не знайдено: {file_path}")
        return
    
    try:
        abs_path = os.path.abspath(file_path)
        ctypes.windll.winmm.mciSendStringW("close custom_sound", None, 0, 0)
        ctypes.windll.winmm.mciSendStringW(f'open "{abs_path}" type mpegvideo alias custom_sound', None, 0, 0)
        
        for _ in range(repeat):
            # 'wait' гарантує, що звук дограє повністю до кінця перед наступним запуском
            ctypes.windll.winmm.mciSendStringW("play custom_sound wait", None, 0, 0)
            ctypes.windll.winmm.mciSendStringW("seek custom_sound to start", None, 0, 0)
            
        ctypes.windll.winmm.mciSendStringW("close custom_sound", None, 0, 0)
    except Exception as e:
        print(f"[!] Помилка відтворення звуку: {e}")


def get_mykolaiv_target_ids():
    """Збирає всі ID, пов'язані з Миколаєвом (область, район, місто)."""
    url = "https://api.ukrainealarm.com/api/v3/regions"
    target_ids = {OBLAST_ID, "98", "1215"}
    
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            states = res.json().get("states", [])
            myk_oblast = next(
                (s for s in states if str(s.get("regionId")) == OBLAST_ID or "Миколаївська" in s.get("regionName", "")),
                None
            )
            
            if myk_oblast:
                for district in myk_oblast.get("regionChildIds", []):
                    d_name = district.get("regionName", "").lower()
                    d_id = str(district.get("regionId"))
                    if "миколаїв" in d_name:
                        target_ids.add(d_id)
                        
                    for community in district.get("regionChildIds", []):
                        c_name = community.get("regionName", "").lower()
                        c_id = str(community.get("regionId"))
                        if "миколаїв" in c_name:
                            target_ids.add(c_id)
    except Exception as e:
        print(f"[!] Помилка завантаження дерева регіонів: {e}")
        
    return target_ids


def check_alert(target_ids):
    """
    Перевіряє активні тривоги.
    Повертає tuple: (is_active, level, reason)
    """
    url = "https://api.ukrainealarm.com/api/v3/alerts"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        
        if res.status_code == 401:
            print("[!] Помилка 401: Невірний або прострочений API-ключ!")
            return None, None, ""
        elif res.status_code != 200:
            print(f"[!] Помилка сервера: Код {res.status_code}")
            return None, None, ""

        data = res.json()
        if not data or not isinstance(data, list):
            return False, None, ""

        for item in data:
            item_region_id = str(item.get("regionId", ""))
            active_alerts = item.get("activeAlerts", [])
            
            for alert in active_alerts:
                alert_region_id = str(alert.get("regionId", item_region_id))
                
                if item_region_id in target_ids or alert_region_id in target_ids:
                    reason = ""
                    level = "Red"
                    
                    levels = alert.get("activeAlertLevels", [])
                    if levels:
                        reason = levels[0].get("reason", "")
                        raw_level = levels[0].get("alertLevel", "Red")
                        if raw_level in ["Yellow", "YellowLevel"]:
                            level = "Yellow"
                        else:
                            level = "Red"
                    elif alert.get("type"):
                        reason = alert.get("type")
                    
                    return True, level, reason
                
        return False, None, ""

    except Exception as e:
        print(f"[!] Помилка з'єднання: {e}")
        return None, None, ""


print("Отримання актуальних ID регіону...")
MYKOLAIV_IDS = get_mykolaiv_target_ids()
print(f"Відстежуються ID: {MYKOLAIV_IDS}")
print("Моніторинг запущено...")

while True:
    state, level, reason = check_alert(MYKOLAIV_IDS)
    now = datetime.now().strftime("%H:%M:%S")

    if state is not None:
        reason_msg = f" ({reason})" if reason else ""

        # 1. Перший запуск після старту скрипта
        if current_state is None:
            if state:
                icon = "⚠️" if level == "Yellow" else "🚨"
                title_level = "ЖОВТИЙ РІВЕНЬ ЗАГРОЗИ" if level == "Yellow" else "🚨 ПОВІТРЯНА ТРИВОГА!"
                
                # Жовтий повторюємо 2 рази, Червоний - 1 раз
                repeat_count = 2 if level == "Yellow" else 1
                sound = YELLOW_SOUND_PATH if level == "Yellow" else RED_SOUND_PATH
                
                print(f"[{now}] ПОТОЧНИЙ СТАН: {icon} {title_level}{reason_msg}")
                play_mp3(sound, repeat=repeat_count)
                
                toast = Notification(
                    app_id="Повітряна Тривога",
                    title=f"ПОТОЧНИЙ СТАН: {title_level}",
                    msg=f"Тривога в Миколаєві/районі!{reason_msg}",
                    duration="short"
                )
                toast.set_audio(audio.Silent, loop=False)
                toast.show()
            else:
                print(f"[{now}] ПОТОЧНИЙ СТАН: 🟢 Спокійно (тривоги немає)")
            
            current_state = state
            current_level = level

        # 2. Зміна стану або рівня загрози під час роботи
        elif state != current_state or (state and level != current_level):
            if state:
                icon = "⚠️" if level == "Yellow" else "🚨"
                title_level = "⚠️ ЖОВТИЙ РІВЕНЬ ЗАГРОЗИ" if level == "Yellow" else "🚨 ЧЕРВОНИЙ РІВЕНЬ / ПОВІТРЯНА ТРИВОГА"
                
                # Жовтий повторюємо 2 рази, Червоний - 1 раз
                repeat_count = 2 if level == "Yellow" else 1
                sound = YELLOW_SOUND_PATH if level == "Yellow" else RED_SOUND_PATH
                
                print(f"[{now}] {icon} ЗМІНА СТАНУ: {title_level}{reason_msg}")
                play_mp3(sound, repeat=repeat_count)
                
                toast = Notification(
                    app_id="Повітряна Тривога",
                    title=title_level,
                    msg=f"Тривога в м. Миколаїв / районі!{reason_msg}",
                    duration="short"
                )
                toast.set_audio(audio.Silent, loop=False)
                toast.show()
            else:
                print(f"[{now}] 🟢 ВІДБІЙ ПОВІТРЯНОЇ ТРИВОГИ")
                # Відбій повторюємо 2 рази
                play_mp3(CLEAR_SOUND_PATH, repeat=2)
                
                toast = Notification(
                    app_id="Повітряна Тривога",
                    title="ВІДБІЙ",
                    msg="Відбій у м. Миколаїв та районі.",
                    duration="short"
                )
                toast.set_audio(audio.Silent, loop=False)
                toast.show()

            current_state = state
            current_level = level

    time.sleep(12)