import telebot
import requests
import time
import random
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
    "current_prediction": {"period_full": None, "block": None, "side": None, "conf": 0, "note": "Processing..."},
    "current_active_method": "P1"  # Default active method from JS
}

# --- ၀။ TIMEZONE UTILS ---
def get_mm_time():
    return datetime.now(timezone.utc) + timedelta(hours=6, minutes=30)

# --- ၁။ MAIN ALGORITHM (Pro-WinGo AI Friend Strategy L3) ---

def get_last_two_digits(issue_string):
    try:
        return int(str(issue_string)[-2:])
    except (ValueError, TypeError):
        return 0

def is_even(number):
    return number % 2 == 0

def calculate_p1_size(intermediate_p1_result, is_target_even):
    is_int_even = is_even(intermediate_p1_result)
    
    if not is_target_even:
        # Target is ODD. Rule 1: If IntResult EVEN -> BIG, ODD -> SMALL
        return "BIG" if is_int_even else "SMALL"
    else:
        # Target is EVEN. Rule 3: If IntResult EVEN -> SMALL, ODD -> BIG
        return "SMALL" if is_int_even else "BIG"

def get_calculated_p1_p2_sizes(target_issue, context_issue, context_outcome_num):
    last_2_context = get_last_two_digits(context_issue)
    outcome = int(context_outcome_num)
    
    # Intermediate P1 Result = (Last 2 digits of context) - (Outcome)
    intermediate_result = last_2_context - outcome
    
    last_2_target = get_last_two_digits(target_issue)
    is_target_even = is_even(last_2_target)
    
    p1_size = calculate_p1_size(intermediate_result, is_target_even)
    p2_size = "SMALL" if p1_size == "BIG" else "BIG"
    
    return p1_size, p2_size

def algo_friend_strategy(history_list, next_period):
    """
    JS ထဲက _generateFriendStrategyPrediction အတိုင်း အတိအကျ ရေးသားထားခြင်း
    """
    if not history_list:
        return None
        
    latest_completed = history_list[0]
    actual_outcome_num = int(latest_completed['number'])
    actual_outcome_size = "BIG" if actual_outcome_num >= 5 else "SMALL"
    
    # Evaluate previous round winner to switch method if needed
    if len(history_list) >= 2:
        context_eval = history_list[1]
        eval_outcome_num = int(context_eval['number'])
        
        past_p1, past_p2 = get_calculated_p1_p2_sizes(
            latest_completed['issueNumber'],
            context_eval['issueNumber'],
            eval_outcome_num
        )
        
        predicted_last_round = past_p1 if state["current_active_method"] == 'P1' else past_p2
        
        if predicted_last_round != actual_outcome_size:
            # Active method was WRONG. Switch it!
            state["current_active_method"] = 'P2' if state["current_active_method"] == 'P1' else 'P1'
    
    # Generate prediction for upcoming period
    up_p1, up_p2 = get_calculated_p1_p2_sizes(
        next_period,
        latest_completed['issueNumber'],
        actual_outcome_num
    )
    
    final_predicted_size = up_p1 if state["current_active_method"] == 'P1' else up_p2
    return final_predicted_size

def get_prediction(history_data, next_period):
    try:
        data_list = sorted(history_data, key=lambda x: int(x['issueNumber']), reverse=True)
        latest = data_list[0]
        
        # Call the Javascript logic equivalent
        side = algo_friend_strategy(data_list, next_period) 
        
        # Fallback to Random (like JS _generateRandomPrediction) if algo fails
        if side is None:
            side = random.choice(["BIG", "SMALL"])
            note = "Random Fallback"
        else:
            note = f"Friend Strategy ({state['current_active_method']})"
            
        conf = 100 
        
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
    print("Bot starting with Pro-WinGo AI Friend Strategy Logic...")
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