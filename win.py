import telebot
import requests
import time
import json 
import re
import os
import math
from datetime import datetime

# ========== CONFIGURATION ==========
BOT_TOKEN = '8616748168:AAH-KyOQHaMvGMO-nuYiekJcIo6zn351ihM'
CHANNEL_ID = '-1003957363150'

API_URL = "https://draw.ar-lottery01.com/TrxWinGo/TrxWinGo_1M/GetHistoryIssuePage.json"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

bot = telebot.TeleBot(BOT_TOKEN)

state = {
    "history": {},
    "total_wins": 0,
    "total_losses": 0,
    "current_loss_streak": 0,
    "max_loss_data": {}, 
    "last_day": "",
    "loss_msg_id": None, 
    "live_msg_id": None, 
    "predictions_memory": {}, 
    "processed_periods": set(),
    "current_prediction": {"period_full": None, "side": None, "conf": 0, "note": "Processing..."}
}

# --- ၁။ PREDICTION ENGINE (GEMINI_FREQ - 20 Rounds) ---

def algo_gemini_freq(history_list):
    """
    နောက်ဆုံး (၂၀) ပွဲအတွင်း BIG နှင့် SMALL ထွက်ရှိမှု အကြိမ်အရေအတွက်ကို တွက်ချက်မည်။
    """
    lookback = 20 # ၂၀ ပွဲကို အခြေခံတွက်မည်
    
    if len(history_list) < lookback:
        return None, f"Syncing ({len(history_list)}/{lookback})"
    
    recent_data = history_list[:lookback]
    big_count = 0
    small_count = 0
    
    for item in recent_data:
        num = int(item['number'])
        if num >= 5:
            big_count += 1
        else:
            small_count += 1
            
    if big_count > small_count:
        side = "BIG"
    elif small_count > big_count:
        side = "SMALL"
    else:
        # ၁၀ ပွဲစီ တူနေခဲ့လျှင် နောက်ဆုံးထွက်ခဲ့သော ပွဲစဉ်အတိုင်း ယူသည်
        last_num = int(recent_data[0]['number'])
        side = "BIG" if last_num >= 5 else "SMALL"
        
    calc_str = f"GEMINI_FREQ ➔ BIG: {big_count}/{lookback} | SMALL: {small_count}/{lookback}"
    return side, calc_str

def get_prediction(history_data):
    try:
        # ပွဲစဉ်များကို နောက်ဆုံးအသစ်မှစ၍ အစဉ်လိုက်စီမည်
        sorted_data = sorted(history_data, key=lambda x: int(x['issueNumber']), reverse=True)
        
        side, note = algo_gemini_freq(sorted_data)
        
        if side is None:
            return None, 0, note
            
        conf = 100 
        return side, conf, note
    except Exception as e:
        return None, 0, "Processing..."

# --- ၂။ MAX LOSS TRACKING ---

def update_loss_stats(streak):
    if streak <= 0: return
    now = datetime.now()
    today = now.strftime("%d,%m,%Y")
    if state["last_day"] != today:
        state["max_loss_data"] = {}
        state["last_day"] = today
    if streak not in state["max_loss_data"]:
        state["max_loss_data"][streak] = {"times": 1, "last_time": now.strftime("%I:%M %p")}
    else:
        state["max_loss_data"][streak]["times"] += 1
        state["max_loss_data"][streak]["last_time"] = now.strftime("%I:%M %p")

# --- ၃။ MESSAGE BUILDERS ---

def build_loss_msg():
    msg = f"<b>⏰ Max Loss History</b>\n"
    msg += f"<i>🗓️Date: {state['last_day']}</i>\n\n"
    if not state["max_loss_data"]:
        msg += "🍁No loss streaks recorded yet."
    else:
        for s in sorted(state["max_loss_data"].keys(), reverse=True):
            d = state["max_loss_data"][s]
            msg += f"<code>⚡{s}x {d['times']}Time {d['last_time']} ,{state['last_day']}</code>\n"
    return msg

def build_live_msg(remaining_sec):
    total = state["total_wins"] + state["total_losses"]
    win_rate = (state["total_wins"] / total * 100) if total > 0 else 0
    curr_conf = state['current_prediction']['conf']
    
    msg = f"<b>🍁 GLOBAL TRX -  MM</b>\n"
    msg += f"🍁 HIT: <b>Win-{state['total_wins']}  ✺  Loss-{state['total_losses']}</b>\n"
    msg += f"🍁 WinRate: <b>{win_rate:.1f}%</b> \n"    
    msg += f"🍁 Next Result In: <b>{remaining_sec}s</b>\n"
    
    # --- History Copy Code Box ---
    table = "✵ Period      ✵  Result     ✵  W/L ✵\n"
    
    sorted_hist = sorted(state["history"].values(), key=lambda x: int(x['issueNumber']), reverse=True)
    for item in sorted_hist[:10]:
        p, num = str(item['issueNumber']), int(item['number'])
        side = "BIG" if num >= 5 else "SMALL"
        wl = "SKIP"
        if p in state["predictions_memory"]:
            if state["predictions_memory"][p] == side:
                wl = "🍏"
                if p not in state["processed_periods"]:
                    update_loss_stats(state["current_loss_streak"])
                    state["total_wins"] += 1
                    state["current_loss_streak"] = 0
                    state["processed_periods"].add(p)
            else:
                wl = "🍎"
                if p not in state["processed_periods"]:
                    state["total_losses"] += 1
                    state["current_loss_streak"] += 1
                    state["processed_periods"].add(p)
        table += f"✺ {p[:3]}**{p[-4:]} • {num}-{side:<6} ✺ {wl:^3} ✺\n"

    msg += f"<pre>{table}</pre>"
    # ---------------------------

    pred_data = state['current_prediction']
    msg += f"✺ Period: {pred_data['period_full'] if pred_data['period_full'] else '---'}\n"
    msg += f"✺ Prediction: <b>{pred_data['side'] or 'WAITING'}</b> ({curr_conf}%)\n"
    msg += f"✺ Signal Analysis: <i>{pred_data['note']}</i>\n"

    return msg

# --- ၄။ MAIN LOOP ---

def main_loop():
    print("Bot starting with GEMINI_FREQ Strategy...")
    state["last_day"] = datetime.now().strftime("%d,%m,%Y")
    while True:
        try:
            res = requests.get(f"{API_URL}?pageSize=50&pageNo=1&ts={int(time.time())}", headers=HEADERS, timeout=15)
            if res.status_code == 200:
                data = res.json().get('data', {}).get('list', [])
                for i in data: state["history"][i['issueNumber']] = i
                
                latest_p = sorted(state["history"].keys(), reverse=True)[0]
                next_p = str(int(latest_p) + 1)
                
                if state["current_prediction"]["period_full"] != next_p:
                    side, conf, note = get_prediction(list(state["history"].values()))
                    state["current_prediction"] = {"period_full": next_p, "side": side, "conf": conf, "note": note}
                    if side: state["predictions_memory"][next_p] = side

                rem_sec = 60 - datetime.now().second
                
                # Message 1
                l_text = build_loss_msg()
                if state["loss_msg_id"] is None:
                    m = bot.send_message(CHANNEL_ID, l_text, parse_mode='HTML')
                    state["loss_msg_id"] = m.message_id
                else:
                    try: bot.edit_message_text(l_text, CHANNEL_ID, state["loss_msg_id"], parse_mode='HTML')
                    except: pass

                # Message 2
                v_text = build_live_msg(rem_sec)
                if state["live_msg_id"] is None:
                    m = bot.send_message(CHANNEL_ID, v_text, parse_mode='HTML')
                    state["live_msg_id"] = m.message_id
                else:
                    try: bot.edit_message_text(v_text, CHANNEL_ID, state["live_msg_id"], parse_mode='HTML')
                    except: pass

                time.sleep(5)
            else: time.sleep(10)
        except Exception as e:
            print(f"Loop Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main_loop()
