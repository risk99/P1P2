import telebot
import requests
import time
from datetime import datetime, timedelta, timezone

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
    "current_prediction": {"period_full": None, "block": None, "side": None, "conf": 0, "note": "Processing..."}
}

# --- ၀။ TIMEZONE UTILS ---
def get_mm_time():
    return datetime.now(timezone.utc) + timedelta(hours=6, minutes=30)

# --- ၁။ MAIN ALGORITHM (Custom Math Logic) ---

def algo_custom_math(history_list):
    """
    User တောင်းဆိုထားသော တွက်နည်းအတိုင်း တွက်ချက်ခြင်း:
    - n1 = အပေါ်ဆုံးကဏန်း
    - n5 = ၅ ခုမြောက်ကဏန်း
    - n10 = အောက်ဆုံးကဏန်း (၁၀ ခုမြောက်)
    """
    if len(history_list) < 10:
        return None, "Not enough data (Need 10 results)"
    
    # ဂဏန်းများဆွဲထုတ်ခြင်း
    n1 = int(history_list[0]['number'])
    n5 = int(history_list[4]['number'])
    n10 = int(history_list[9]['number'])
    
    # တွက်ချက်ခြင်း
    calc1 = n5 + 9
    calc2 = n1 + n10
    
    # အချင်းချင်းနှုတ်ခြင်း (အနှုတ်မထွက်အောင် abs ခံထားသည်)
    diff = abs(calc1 - calc2)
    
    # နောက်ဆုံးဂဏန်းကိုပဲယူခြင်း (ဥပမာ 15 ဆိုရင် 5 ကိုယူမယ်)
    final_digit = diff % 10
    
    # BIG / SMALL သတ်မှတ်ခြင်း
    side = "BIG" if final_digit >= 5 else "SMALL"
    
    # တွက်ထားတဲ့ ပုံစံကို Text ပြန်ထုတ်ပေးခြင်း
    calc_str = f"[{n5}+9={calc1}] & [{n1}+{n10}={calc2}] ➔ |{calc1}-{calc2}| = {diff} ➔ {final_digit}"
    
    return side, calc_str

def get_prediction(history_data, next_period):
    try:
        # နောက်ဆုံးထွက်ထားတဲ့ပွဲစဉ်တွေကို အစဉ်လိုက်စီမယ်
        data_list = sorted(history_data, key=lambda x: int(x['issueNumber']), reverse=True)
        latest = data_list[0]
        
        # Custom Math Logic ကိုခေါ်သုံးမယ်
        side, calc_str = algo_custom_math(data_list)
        
        if side is None:
            side = "SKIP"
            note = calc_str
        else:
            note = calc_str
            
        conf = 100 
        
        return side, conf, note, latest.get('blockNumber')
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

# --- ၃။ MESSAGE BUILDERS ---

def build_live_msg(remaining_sec):
    total = state["total_wins"] + state["total_losses"]
    win_rate = (state["total_wins"] / total * 100) if total > 0 else 0
    curr = state['current_prediction']
    
    msg = f"<b>🍁GLOBAL TRX LIVE - WWC LABS</b>\n"
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
    print("Bot starting with Custom User Math Logic...")
    state["last_day"] = get_mm_time().strftime("%d,%m,%Y")
    
    while True:
        try:
            res = requests.get(f"{API_URL}?pageSize=50&pageNo=1&ts={int(time.time())}", headers=HEADERS, timeout=15)
            if res.status_code == 200:
                data = res.json().get('data', {}).get('list', [])
                for i in data: state["history"][i['issueNumber']] = i
                
                latest_p = sorted(state["history"].keys(), reverse=True)[0]
                next_p = str(int(latest_p) + 1)
                
                if state["current_prediction"]["period_full"] != next_p:
                    # Pass next_p to prediction logic
                    side, conf, note, b_num = get_prediction(list(state["history"].values()), next_p)
                        
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
            print(f"Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main_loop()