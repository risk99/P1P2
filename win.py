import telebot
import requests
import time
import json 
import os
from datetime import datetime, timedelta, timezone

# ========== CONFIGURATION ========== 
BOT_TOKEN = '8616748168:AAH-KyOQHaMvGMO-nuYiekJcIo6zn351ihM'
CHANNEL_ID = '-1003957363150'


STATE_FILE = 'bot_state.json' 

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
    "last_loss_text": "", 
    "last_live_text": "", 
    "predictions_memory": {}, 
    "processed_periods": set(),
    "current_prediction": {"period_full": None, "block": None, "side": None, "conf": 0, "note": "Processing..."}
}

# --- ၀။ TIMEZONE & FILE UTILS ---
def get_mm_time():
    return datetime.now(timezone.utc) + timedelta(hours=6, minutes=30)

def load_msg_ids():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r') as f:
                data = json.load(f)
                state["loss_msg_id"] = data.get("loss_msg_id")
                state["live_msg_id"] = data.get("live_msg_id")
    except Exception as e:
        pass

def save_msg_ids():
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump({
                "loss_msg_id": state["loss_msg_id"],
                "live_msg_id": state["live_msg_id"]
            }, f)
    except Exception as e:
        pass

# --- ၁။ PREDICTION ALGORITHM ---
def algo_gemini_freq(history_list):
    lookback = 20 
    if len(history_list) < lookback:
        return None, f"Not enough data (Need {lookback} results)"
    
    recent_data = history_list[:lookback]
    big_count = 0
    small_count = 0
    
    for item in recent_data:
        num = int(item['number'])
        if num >= 5: big_count += 1
        else: small_count += 1
            
    if big_count > small_count: side = "BIG"
    elif small_count > big_count: side = "SMALL"
    else:
        last_num = int(recent_data[0]['number'])
        side = "BIG" if last_num >= 5 else "SMALL"
        
    calc_str = f"GEMINI_FREQ ➔ BIG: {big_count}/{lookback} | SMALL: {small_count}/{lookback} ➔ {side}"
    return side, calc_str

def get_prediction(history_data):
    try:
        data_list = sorted(history_data, key=lambda x: int(x['issueNumber']), reverse=True)
        latest = data_list[0]
        side, calc_str = algo_gemini_freq(data_list)
        if side is None: side = "SKIP"
        conf = 100 
        return side, conf, calc_str, latest.get('blockNumber')
    except Exception as e:
        return "SKIP", 0, f"Error: {e}", None

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

# --- ၃။ MESSAGE BUILDERS (Timer ဖြုတ်လိုက်ပါပြီ) ---
def build_live_msg():
    total = state["total_wins"] + state["total_losses"]
    win_rate = (state["total_wins"] / total * 100) if total > 0 else 0
    curr = state['current_prediction']
    
    msg = f"<b>🍁GLOBAL TRX LIVE - WWC LABS</b>\n"
    msg += f"🍁ʜɪꜱᴛᴏʀʏ: <b>W-{state['total_wins']} | L-{state['total_losses']}</b>\n"
    msg += f"🍁ᴡɪɴʀᴀᴛᴇ: <b>{win_rate:.1f}%</b> \n"    
    msg += f"🍁ꜱᴛᴀᴛᴜꜱ: <b>🟢 Live Analysis</b>\n" # <--- Timer အစား ဒါထည့်လိုက်ပါပြီ
    
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
    msg += f"🍁ᴄʀᴇᴀᴛᴏʀ: @XQNSY\n\n"
    msg += f"⚙️ <b>Logic Formula:</b>\n<code>{curr['note']}</code>"
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
    print("Bot starting... Rate Limit (Timer Edit) is Fixed!")
    state["last_day"] = get_mm_time().strftime("%d,%m,%Y")
    load_msg_ids()
    
    while True:
        try:
            res = requests.get(f"{API_URL}?pageSize=50&pageNo=1&ts={int(time.time())}", headers=HEADERS, timeout=15)
            if res.status_code == 200:
                data = res.json().get('data', {}).get('list', [])
                for i in data: state["history"][i['issueNumber']] = i
                
                latest_p = sorted(state["history"].keys(), reverse=True)[0]
                next_p = str(int(latest_p) + 1)
                
                if state["current_prediction"]["period_full"] != next_p:
                    side, conf, note, b_num = get_prediction(list(state["history"].values()))
                    state["current_prediction"] = {"period_full": next_p, "block": b_num, "side": side, "conf": conf, "note": note}
                    if side and side != "SKIP": state["predictions_memory"][next_p] = side

                # --- 1. UPDATE LOSS MESSAGE ---
                l_text = build_loss_msg()
                if state["loss_msg_id"] is None:
                    m = bot.send_message(CHANNEL_ID, l_text, parse_mode='HTML')
                    state["loss_msg_id"] = m.message_id
                    state["last_loss_text"] = l_text
                    save_msg_ids()
                elif l_text != state["last_loss_text"]:
                    try: 
                        bot.edit_message_text(l_text, CHANNEL_ID, state["loss_msg_id"], parse_mode='HTML')
                        state["last_loss_text"] = l_text
                    except Exception as e:
                        if "message to edit not found" in str(e).lower():
                            m = bot.send_message(CHANNEL_ID, l_text, parse_mode='HTML')
                            state["loss_msg_id"] = m.message_id
                            state["last_loss_text"] = l_text
                            save_msg_ids()

                # --- 2. UPDATE LIVE MESSAGE (၁ မိနစ် ၁ ခါသာ ပြောင်းမည်) ---
                v_text = build_live_msg()
                if state["live_msg_id"] is None:
                    m = bot.send_message(CHANNEL_ID, v_text, parse_mode='HTML')
                    state["live_msg_id"] = m.message_id
                    state["last_live_text"] = v_text
                    save_msg_ids()
                elif v_text != state["last_live_text"]:
                    try: 
                        bot.edit_message_text(v_text, CHANNEL_ID, state["live_msg_id"], parse_mode='HTML')
                        state["last_live_text"] = v_text
                    except Exception as e:
                        if "message to edit not found" in str(e).lower():
                            m = bot.send_message(CHANNEL_ID, v_text, parse_mode='HTML')
                            state["live_msg_id"] = m.message_id
                            state["last_live_text"] = v_text
                            save_msg_ids()

                # API Call မများစေရန် ၇ စက္ကန့်ခြားထားသည်
                time.sleep(7) 
            else:
                time.sleep(10)
        except Exception as e:
            print(f"Error in main loop: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main_loop()
