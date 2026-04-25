import telebot
import requests
import time
import os
import re
import json
from datetime import datetime, timedelta, timezone

# ========== CONFIGURATION ========== 
BOT_TOKEN = '8616748168:AAH-KyOQHaMvGMO-nuYiekJcIo6zn351ihM'
CHANNEL_ID = '-1003957363150'
GEMINI_API_KEY = 'AIzaSyC70DKqvTU4mGNOlNEr9f1UDai8njXS6QU' # ဤနေရာတွင် Gemini API Key ထည့်ပါ

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
    "current_prediction": {"period_full": None, "block": None, "side": None, "conf": 0, "note": "Processing..."}
}

# --- ၀။ TIMEZONE UTILS ---
def get_mm_time():
    return datetime.now(timezone.utc) + timedelta(hours=6, minutes=30)

# --- ၁။ MAIN ALGORITHM (Gemini AI Strategy) ---

def get_gemini_prediction(history_list):
    """
    Gemini API ကို အသုံးပြု၍ Prediction ယူခြင်း
    """
    if len(history_list) < 10:
        return None, 0, "Not enough data"

    # နောက်ဆုံးထွက်ခဲ့တဲ့ ဂဏန်း ၁၀ လုံးကို ယူမည်
    last_10_numbers = [str(item.get('number')) for item in history_list[:10]]
    numbers_str = ", ".join(last_10_numbers)

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY}"
    
    prompt = (
        f"Based on these last 10 TrxWinGo results (newest to oldest): {numbers_str}. "
        "Predict if the next result will be BIG (5-9) or SMALL (0-4). "
        "Reply strictly with JSON format: {\"side\": \"BIG\" or \"SMALL\", \"confidence\": 0-100}"
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        if response.status_code == 200:
            data = response.json()
            text = data['candidates'][0]['content']['parts'][0]['text']
            
            # JSON Data ကို ရှာဖွေပြီး ထုတ်ယူမည် (re.DOTALL အသုံးပြုထား၍ line breaks ပါလည်း အလုပ်လုပ်ပါသည်)
            json_match = re.search(r'\{.*?\}', text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(0))
                side = result.get("side", "").upper()
                conf = int(result.get("confidence", 0))
                
                if side in ["BIG", "SMALL"]:
                    return side, conf, "Gemini AI"
                else:
                    return "SKIP", 0, "Invalid side from Gemini"
            else:
                return "SKIP", 0, "No JSON found in Gemini response"
        else:
            print(f"Gemini API Error: {response.status_code} - {response.text}")
            return "SKIP", 0, "Gemini API Error"
            
    except Exception as e:
        print(f"Gemini Request Exception: {e}")
        return "SKIP", 0, "Gemini Connection Error"

def get_prediction(history_data):
    try:
        data_list = sorted(history_data, key=lambda x: int(x['issueNumber']), reverse=True)
        latest = data_list[0]
        
        # Gemini API မှ prediction တောင်းမည်
        side, conf, note = get_gemini_prediction(data_list) 
        
        if side is None or side == "SKIP":
            return "SKIP", 0, note, latest.get('blockNumber')
            
        return side, conf, note, latest.get('blockNumber')
    except Exception as e:
        return None, 0, f"Error: {e}", None

# --- ၂။ STATS & UTILS ---

def update_loss_stats(streak):
    if streak <= 0: return
    now = get_mm_time()
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

def build_live_msg(remaining_sec):
    total = state["total_wins"] + state["total_losses"]
    win_rate = (state["total_wins"] / total * 100) if total > 0 else 0
    curr = state['current_prediction']
    
    msg = f"<b>🤖 GEMINI AI TRX LIVE </b>\n"
    msg += f"🍁ʜɪꜱᴛᴏʀʏ: <b>W-{state['total_wins']} | L-{state['total_losses']}</b>\n"
    msg += f"🍁ᴡɪɴʀᴀᴛᴇ: <b>{win_rate:.1f}%</b> \n"    
    msg += f"🍁ᴛɪᴍᴇ ʀᴇᴍᴀɪɴɪɴɢ: <b>{remaining_sec}s</b>\n"
    
    table = "📄     Period Number     • Result   •  W/L •\n"
                
    sorted_hist = sorted(state["history"].values(), key=lambda x: int(x['issueNumber']), reverse=True)
    
    for item in sorted_hist[:10]:
        p = str(item['issueNumber'])
        num = int(item['number'])
        actual_side = "BIG" if num >= 5 else "SMALL"
        
        wl = "▫️"
        if p in state["predictions_memory"]:
            predicted = state["predictions_memory"][p]
            if predicted == actual_side:
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
        
        table += f"🍁 {p[-17:]}  •  {num}-{actual_side[:1]}     • {wl:^3} •\n"

    msg += f"<pre>{table}</pre>"
        
    msg += f"🍁ᴘᴇʀɪᴏᴅ: {curr['period_full'][-17:] if curr['period_full'] else '----'}\n"
    msg += f"🍁ᴘʀᴇᴅɪᴄᴛɪᴏɴ: <b>{curr['side'] or 'WAITING'}</b> ({curr['conf']}%)\n"
    msg += f"🍁ᴄʀᴇᴀᴛᴏʀ: @XQNSY"

    return msg

def build_loss_msg():
    msg = f"<b>⏰ Max Loss History</b>\n"
    msg += f"<i>🗓️ Date: {state['last_day']}</i>\n\n"
    if not state["max_loss_data"]:
        msg += "▫️ No loss streaks recorded yet."
    else:
        for s in sorted(state["max_loss_data"].keys(), reverse=True):
            d = state["max_loss_data"][s]
            msg += f"<code>⚡{s}x {d['times']}Time {d['last_time']}</code>\n"
    return msg

# --- ၄။ MAIN LOOP ---

def main_loop():
    print("Bot starting with Gemini AI Logic...")
    state["last_day"] = get_mm_time().strftime("%d,%m,%Y")
    
    while True:
        try:
            res = requests.get(f"{API_URL}?pageSize=50&pageNo=1&ts={int(time.time())}", headers=HEADERS, timeout=15)
            if res.status_code == 200:
                data = res.json().get('data', {}).get('list', [])
                for i in data: state["history"][i['issueNumber']] = i
                
                latest_p = sorted(state["history"].keys(), reverse=True)[0]
                next_p = str(int(latest_p) + 1)
                
                # Period အသစ်ဖြစ်မှသာ Gemini API ကို ခေါ်မည် (API Limit မထိအောင်)
                if state["current_prediction"]["period_full"] != next_p:
                    side, conf, note, b_num = get_prediction(list(state["history"].values()))
                        
                    state["current_prediction"] = {
                        "period_full": next_p, 
                        "block": b_num,
                        "side": side, 
                        "conf": conf, 
                        "note": note
                    }
                    
                    if side and side != "SKIP": 
                        state["predictions_memory"][next_p] = side

                rem_sec = 60 - get_mm_time().second
                
                # Update Messages
                l_text = build_loss_msg()
                if state["loss_msg_id"] is None:
                    m = bot.send_message(CHANNEL_ID, l_text, parse_mode='HTML')
                    state["loss_msg_id"] = m.message_id
                else:
                    try: bot.edit_message_text(l_text, CHANNEL_ID, state["loss_msg_id"], parse_mode='HTML')
                    except: pass

                v_text = build_live_msg(rem_sec)
                if state["live_msg_id"] is None:
                    m = bot.send_message(CHANNEL_ID, v_text, parse_mode='HTML')
                    state["live_msg_id"] = m.message_id
                else:
                    try: bot.edit_message_text(v_text, CHANNEL_ID, state["live_msg_id"], parse_mode='HTML')
                    except: pass

                time.sleep(5)
            else:
                time.sleep(10)
        except Exception as e:
            print(f"Error in main loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main_loop()
