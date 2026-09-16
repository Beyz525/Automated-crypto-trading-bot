import ccxt
import time
import pandas as pd
import ta
import json
import os
from datetime import datetime

C = {"RESET": "\033[0m","RED": "\033[91m","GREEN": "\033[92m"
,"YELLOW": "\033[93m","CYAN": "\033[96m"}

API_KEY = 'YOUR_API_KEY_HERE'
API_SECRET = 'YOUR_SECRET_API_KEY_HERE'

SYMBOLS = [
    "ETH/USDT:USDT",
    "SOL/USDT:USDT",
    "XRP/USDT:USDT",
    "BTC/USDT:USDT"
]

LEVERAGE_MAP = {
    "ETH/USDT:USDT": 75,
    "SOL/USDT:USDT": 75,
    "BTC/USDT:USDT": 75,
    "XRP/USDT:USDT": 75,
}

CAPITAL_PER_TRADE = 2
RSI_PERIOD = 6; RSI_OVERSOLD = 25; RSI_OVERBOUGHT = 75
TF = '30m'

TP_PERCENT = 0.5 # TP fix 0.5%
SL_PERCENT = 0.25 # SL tetap 0.25%
BEP_TRIGGER = 0.25 # Kalo profit 0.25% langsung geser SL ke BE

VOLUME_MIN = {
    "ETH/USDT:USDT": 200000000, # 200M
    "SOL/USDT:USDT": 50000000, # 50M
    "BTC/USDT:USDT": 400000000, #400M
    "XRP/USDT:USDT": 40000000, #40M
}

TP_TARGET_PER_COIN = 4
STATE_FILE = "bot_state_v46.json"

exchange = ccxt.binanceusdm({'apiKey': API_KEY,'secret': API_SECRET,'enableRateLimit': True})

OPEN_DATA = {}

def now(): return datetime.now().strftime("%H:%M:%S")

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {"last_reset_date": "", "tp_count": {}, "last_tp_time": {}}

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

def check_reset():
    state = load_state()
    today = datetime.now().strftime("%Y-%m-%d")
    if state["last_reset_date"]!= today:
        state["last_reset_date"] = today
        state["tp_count"] = {}
        state["last_tp_time"] = {}
        save_state(state)
        print(f"{C['CYAN']}[{now()}] [RESET] Hari baru. Counter TP reset{C['RESET']}")
    return state

def get_mark_price(symbol):
    try: return float(exchange.fetch_ticker(symbol)['info']['markPrice'])
    except: return float(exchange.fetch_ticker(symbol)['last'])

for s in SYMBOLS:
    try:
        lev = LEVERAGE_MAP.get(s, 75)
        exchange.set_leverage(lev, s); exchange.set_position_mode(True)
    except: pass

def get_data(symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, TF, limit=100)
        df = pd.DataFrame(ohlcv, columns=['ts','o','h','l','c','v'])
        rsi = ta.momentum.rsi(df['c'], RSI_PERIOD).iloc[-1]
        price = df['c'].iloc[-1]
        volume_5m = df['c'].iloc[-1] * df['v'].iloc[-1]
        avg_volume_20 = (df['c'].iloc[-20:] * df['v'].iloc[-20:]).mean()
        return rsi, price, volume_5m, avg_volume_20, df
    except: return None,None,None,None,None

def calc_amount(symbol, price):
    try:
        lev = LEVERAGE_MAP.get(symbol, 75)
        return float(exchange.amount_to_precision(symbol, (CAPITAL_PER_TRADE * lev) / price))
    except: return 0

def close_pos(symbol, side, size):
    try:
        params = {'positionSide': side.upper()}
        order_side = 'sell' if side=='long' else 'buy'
        exchange.create_market_order(symbol, order_side, size, None, params)
        if symbol in OPEN_DATA: del OPEN_DATA[symbol]
        print(f"{C['CYAN']}[{now()}] [CLOSE] {symbol} {side.upper()}{C['RESET']}")
    except Exception as e: print(f"{C['RED']}[{now()}] [ERR CLOSE] {e}{C['RESET']}")

print(f"{C['CYAN']}[{now()}] [BOT V46.3.2 - FIX BEP MANUAL]{C['RESET']}")

while True:
    try:
        state = check_reset()
        all_positions = {}
        try: all_positions = {p['symbol']: p for p in exchange.fetch_positions() if float(p['info']['positionAmt'])!= 0}
        except: pass

        for symbol in SYMBOLS:
            try:
                tp_count = state["tp_count"].get(symbol, 0)
                if tp_count >= TP_TARGET_PER_COIN:
                    print(f"[{now()}] [SKIP] {symbol} Target 4TP tercapai hari ini")
                    continue

                last_tp = state["last_tp_time"].get(symbol, 0)
                if time.time() - last_tp < 60:
                    print(f"[{now()}] [DELAY] {symbol} Tunggu 1 menit setelah TP")
                    continue

                rsi, price, volume_5m, avg_volume_20, df = get_data(symbol)
                if rsi is None: continue

                pos = all_positions.get(symbol)
                pos_size, pos_side, entry = (0, None, 0)
                if pos:
                    pos_size = abs(float(pos['info']['positionAmt']))
                    pos_side = pos['info']['positionSide']
                    entry = float(pos['info']['entryPrice'])

                mark_price = get_mark_price(symbol)

                if pos_size == 0:
                    status = f"{C['YELLOW']}[SCAN]{C['RESET']}"
                elif pos_side == 'LONG':
                    status = f"{C['GREEN']}[LONG 🔥]{C['RESET']}"
                else:
                    status = f"{C['RED']}[SHORT 💀]{C['RESET']}"

                print(f"[{now()}] {status} {symbol} RSI:{rsi:.2f} MARK:{mark_price:.2f} VOL:{volume_5m/1000000:.1f}Jt TP:{tp_count}/{TP_TARGET_PER_COIN}")

                if pos_size == 0:
                    amount = calc_amount(symbol, price)
                    if amount == 0: continue
                    min_vol = VOLUME_MIN.get(symbol, 10000000)
                    vol_ok = volume_5m > min_vol
                    if vol_ok:
                        if rsi < RSI_OVERSOLD:
                            exchange.create_market_order(symbol, 'buy', amount, None, {'positionSide':'LONG'});
                            OPEN_DATA[symbol] = {"volume_buka": volume_5m, "entry": price, "bep_aktif": False}
                            print(f"{C['GREEN']}[{now()}] [OPEN] {symbol} LONG TP:0.5% SL:0.25%{C['RESET']}")
                        elif rsi > RSI_OVERBOUGHT:
                            exchange.create_market_order(symbol, 'sell', amount, None, {'positionSide':'SHORT'});
                            OPEN_DATA[symbol] = {"volume_buka": volume_5m, "entry": price, "bep_aktif": False}
                            print(f"{C['RED']}[{now()}] [OPEN] {symbol} SHORT TP:0.5% SL:0.25%{C['RESET']}")
                    else:
                        print(f"{C['YELLOW']}[{now()}] [SKIP] {symbol} Volume kecil: {volume_5m/1000000:.1f}Jt{C['RESET']}")

                # ============= [FIX BEP START - CUMA UBAH SINI DOANG] =============
                if pos_size > 0:
                    entry_buka = entry # [FIX] PAKSA PAKE ENTRY DARI EXCHANGE
                    if symbol not in OPEN_DATA: OPEN_DATA[symbol] = {"bep_aktif": False} # [FIX] ANTI KEYERROR PAS RESTART
                    volume_buka = OPEN_DATA[symbol].get("volume_buka", 0)

                    tp_percent = TP_PERCENT
                    sl_percent = SL_PERCENT
                    if pos_side == 'LONG':
                        profit_now = (mark_price - entry_buka) / entry_buka * 100
                    elif pos_side == 'SHORT':
                        profit_now = (entry_buka - mark_price) / entry_buka * 100

                    # [FIX BEP 1] KALO UDAH PROFIT 0.25% DAN BEP BELUM AKTIF
                    if profit_now >= BEP_TRIGGER and not OPEN_DATA[symbol]["bep_aktif"]:
                        print(f"{C['CYAN']}[{now()}] [BEP AKTIF] {symbol} Profit:{profit_now:.2f}% SL dikunci ke BEP @ {entry_buka:.2f}{C['RESET']}")
                        OPEN_DATA[symbol]["bep_aktif"] = True

                    # [FIX BEP 2] KALO BEP UDAH AKTIF, SL PAKSA = ENTRY
                    if OPEN_DATA[symbol]["bep_aktif"]:
                        sl = entry_buka
                    else:
                        sl = entry_buka * (1 - sl_percent/100) if pos_side == 'LONG' else entry_buka * (1 + sl_percent/100)

                    tp = entry_buka * (1 + tp_percent/100) if pos_side == 'LONG' else entry_buka * (1 - tp_percent/100)

                    if (pos_side == 'LONG' and mark_price >= tp) or (pos_side == 'SHORT' and mark_price <= tp):
                        close_pos(symbol, pos_side.lower(), pos_size)
                        state["tp_count"][symbol] = tp_count + 1
                        state["last_tp_time"][symbol] = time.time()
                        save_state(state)
                        print(f"{C['GREEN']}[{now()}] [TP] {symbol} Ke-{state['tp_count'][symbol]}/{TP_TARGET_PER_COIN}{C['RESET']}")

                    elif (pos_side == 'LONG' and mark_price <= sl) or (pos_side == 'SHORT' and mark_price >= sl):
                        # [FIX BEP 3] KASIH NOTIF KALO KENA SL BEP
                        if OPEN_DATA[symbol]["bep_aktif"]:
                            print(f"{C['YELLOW']}[{now()}] [SL BEP] {symbol} Kena SL di BEP. Aman ga rugi{C['RESET']}")
                        close_pos(symbol, pos_side.lower(), pos_size)
                # ============= [FIX BEP END] =============

                time.sleep(1)

            except Exception as e: print(f"{C['RED']}[{now()}] [ERR] {symbol}: {e}{C['RESET']}")

    except Exception as e: print(f"{C['RED']}[{now()}] [ERR GLOBAL] {e}{C['RESET']}")
    time.sleep(5)
