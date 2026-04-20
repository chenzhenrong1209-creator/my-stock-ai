import streamlit as st
from groq import Groq
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import re
import akshare as ak
import tushare as ts
import baostock as bs
import random
import time
from datetime import datetime
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ================= 页面与终端 UI 配置 =================
st.set_page_config(
    page_title="AI 智能投研终端 Pro Max",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 增强移动端适配，优化 Metric 显示
st.markdown("""
    <style>
    .stTabs [data-baseweb="tab-list"] { gap: 10px; flex-wrap: wrap; }
    .stTabs [data-baseweb="tab"] { height: auto; min-height: 40px; white-space: normal; border-radius: 4px 4px 0 0; padding: 8px 12px; font-weight: bold; }
    .terminal-header { font-family: 'Courier New', Courier, monospace; color: #888; font-size: 0.8em; margin-bottom: 20px; word-wrap: break-word; }
    [data-testid="stMetricValue"] { font-size: 1.4rem; }
    /* 适配移动端 Termux 环境 */
    @media (max-width: 768px) {
        [data-testid="stMetricValue"] { font-size: 1.1rem; }
        .stButton>button { width: 100%; }
    }
    </style>
""", unsafe_allow_html=True)

st.title("🏦 AI 智能量化投研终端")
st.markdown(
    f"<div class='terminal-header'>TERMINAL BUILD v7.0.0 | SYS_TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | SMART_MONEY_TRACK + WECHAT_ALERT</div>",
    unsafe_allow_html=True
)

api_key = st.secrets.get("GROQ_API_KEY", "")

# ================= 侧边栏与参数调优 =================
with st.sidebar:
    st.header("⚙️ 终端控制台")

    st.markdown("### 🧠 核心推理引擎")
    selected_model = st.selectbox(
        "选择大模型",
        ["llama-3.3-70b-versatile", "mixtral-8x7b-32768", "gemma2-9b-it"],
        index=0,
        help="手动指定底层计算模型，精准控制分析逻辑"
    )

    st.markdown("### 🎛️ 策略参数微调")
    with st.expander("自定义均线周期 (手动输入)", expanded=False):
        ema_short = st.number_input("短期 EMA", min_value=5, max_value=50, value=20, step=1)
        ema_mid = st.number_input("中期 EMA", min_value=10, max_value=100, value=60, step=1)
        ema_long = st.number_input("长期 EMA", min_value=20, max_value=250, value=120, step=1)

    st.markdown("### 🔔 预警推送配置")
    server_key = st.text_input("🔑 Server酱 SendKey", type="password", help="填入后可启用报告微信推送")
    ts_token = st.text_input("🔑 Tushare Token", type="password", help="仅作极致容灾兜底")
    DEBUG_MODE = st.checkbox("🛠️ 开启底层日志嗅探")

    st.markdown("---")
    st.markdown("### 📡 数据连通性")
    st.success("行情引流 : ACTIVE")
    st.success("主力资金监控 : ACTIVE")
    st.success("板块扫描 : ACTIVE")
    st.success("技术结构引擎 : ACTIVE")
    st.success("多周期分析 : ACTIVE (15m / 60m / 120m)")

if ts_token:
    ts.set_token(ts_token)

# ================= 网络底座 =================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
]

@st.cache_resource
def get_session():
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[403, 429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

SESSION = get_session()

def safe_float(val, default=0.0):
    if val is None or val == "-" or str(val).strip() == "": return default
    try: return float(val)
    except Exception: return default

def fetch_json(url, timeout=5, extra_headers=None):
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    if extra_headers: headers.update(extra_headers)
    try:
        res = SESSION.get(url, headers=headers, timeout=timeout)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        if DEBUG_MODE: st.error(f"Feed Error: {e}")
        return None

def normalize_em_price(raw_price, prev_close=None):
    raw_price = safe_float(raw_price)
    prev_close = safe_float(prev_close)
    if raw_price <= 0: return 0.0
    candidates = [raw_price, raw_price / 10, raw_price / 100, raw_price / 1000]
    candidates = [x for x in candidates if 0.01 <= x <= 100000]
    if not candidates: return raw_price
    if prev_close > 0:
        best = min(candidates, key=lambda x: abs(x - prev_close))
        return best
    if raw_price > 100000: return raw_price / 1000
    if raw_price > 10000: return raw_price / 100
    if raw_price > 1000: return raw_price / 10
    return raw_price

# ================= 消息推送引擎 =================
def push_to_wechat(title, content, sendkey):
    if not sendkey: return False, "未配置 Server酱 SendKey"
    url = f"https://sctapi.ftqq.com/{sendkey}.send"
    try:
        res = requests.post(url, data={"title": title, "desp": content}, timeout=5)
        if res.status_code == 200: return True, "推送成功"
        else: return False, f"推送失败: {res.text}"
    except Exception as e:
        return False, str(e)

# ================= 技术面核心函数 =================
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema_short"] = df["close"].ewm(span=ema_short, adjust=False).mean()
    df["ema_mid"] = df["close"].ewm(span=ema_mid, adjust=False).mean()
    df["ema_long"] = df["close"].ewm(span=ema_long, adjust=False).mean()

    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    df["rsi14"] = 100 - (100 / (1 + rs))

    prev_close = df["close"].shift(1)
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - prev_close).abs()
    tr3 = (df["low"] - prev_close).abs()
    df["tr"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["atr14"] = df["tr"].rolling(14).mean()

    ma20 = df["close"].rolling(20).mean()
    std20 = df["close"].rolling(20).std()
    df["bb_mid"] = ma20
    df["bb_up"] = ma20 + 2 * std20
    df["bb_low"] = ma20 - 2 * std20

    df["vol_ma20"] = df["volume"].rolling(20).mean()
    return df

def detect_swings(df: pd.DataFrame, left=2, right=2):
    swing_highs, swing_lows = [], []
    if len(df) < left + right + 1: return swing_highs, swing_lows
    for i in range(left, len(df) - right):
        high, low = df["high"].iloc[i], df["low"].iloc[i]
        if high == df["high"].iloc[i-left: i+right+1].max(): swing_highs.append((i, high))
        if low == df["low"].iloc[i-left: i+right+1].min(): swing_lows.append((i, low))
    return swing_highs, swing_lows

def detect_fvg(df: pd.DataFrame, max_zones=5):
    zones = []
    if len(df) < 3: return zones
    for i in range(2, len(df)):
        c1, c3 = df.iloc[i - 2], df.iloc[i]
        if c3["low"] > c1["high"]:
            zones.append({"type": "bullish", "start_idx": i - 2, "end_idx": i, "top": c3["low"], "bottom": c1["high"], "date": str(pd.to_datetime(c3["date"]).date())})
        if c3["high"] < c1["low"]:
            zones.append({"type": "bearish", "start_idx": i - 2, "end_idx": i, "top": c1["low"], "bottom": c3["high"], "date": str(pd.to_datetime(c3["date"]).date())})
    return zones[-max_zones:]

def detect_liquidity_sweep(df: pd.DataFrame):
    if len(df) < 25: return "样本不足"
    recent = df.tail(20).copy()
    latest = recent.iloc[-1]
    prev_high = recent.iloc[:-1]["high"].max()
    prev_low = recent.iloc[:-1]["low"].min()
    if latest["high"] > prev_high and latest["close"] < prev_high: return "向上扫流动性后回落"
    if latest["low"] < prev_low and latest["close"] > prev_low: return "向下扫流动性后收回"
    return "未见明显扫盘"

def detect_bos(df: pd.DataFrame):
    swing_highs, swing_lows = detect_swings(df)
    if len(swing_highs) < 2 or len(swing_lows) < 2: return "样本不足"
    latest_close = df.iloc[-1]["close"]
    last_swing_high = swing_highs[-1][1]
    last_swing_low = swing_lows[-1][1]
    if latest_close > last_swing_high: return "向上 BOS"
    if latest_close < last_swing_low: return "向下 BOS"
    return "结构未突破"

def detect_order_blocks(df: pd.DataFrame, lookback=30, max_zones=4):
    zones = []
    recent = df.tail(lookback).reset_index(drop=True)
    if len(recent) < 3 or "atr14" not in recent.columns: return zones
    for i in range(1, len(recent) - 1):
        curr, nxt = recent.iloc[i], recent.iloc[i + 1]
        body_curr = abs(curr["close"] - curr["open"])
        atr = recent["atr14"].iloc[i]
        if pd.isna(atr): continue
        if curr["close"] < curr["open"] and nxt["close"] > curr["high"] and body_curr < atr * 1.2:
            zones.append({"type": "bullish_ob", "date": str(pd.to_datetime(curr["date"]).date()), "top": max(curr["open"], curr["close"]), "bottom": min(curr["open"], curr["close"])})
        if curr["close"] > curr["open"] and nxt["close"] < curr["low"] and body_curr < atr * 1.2:
            zones.append({"type": "bearish_ob", "date": str(pd.to_datetime(curr["date"]).date()), "top": max(curr["open"], curr["close"]), "bottom": min(curr["open"], curr["close"])})
    return zones[-max_zones:]

def detect_equal_high_low(df: pd.DataFrame, tolerance=0.003):
    swing_highs, swing_lows = detect_swings(df)
    eqh = [ (swing_highs[i], swing_highs[i+1]) for i in range(len(swing_highs)-1) if swing_highs[i][1] > 0 and abs(swing_highs[i][1]-swing_highs[i+1][1])/swing_highs[i][1] <= tolerance ]
    eql = [ (swing_lows[i], swing_lows[i+1]) for i in range(len(swing_lows)-1) if swing_lows[i][1] > 0 and abs(swing_lows[i][1]-swing_lows[i+1][1])/swing_lows[i][1] <= tolerance ]
    return eqh[-3:], eql[-3:]

def detect_mss(df: pd.DataFrame):
    swing_highs, swing_lows = detect_swings(df)
    if len(swing_highs) < 2 or len(swing_lows) < 2 or len(df) < 2: return "样本不足"
    latest, prev = df.iloc[-1], df.iloc[-2]
    last_high, last_low = swing_highs[-1][1], swing_lows[-1][1]
    if prev["close"] < last_high and latest["close"] > last_high: return "Bullish MSS"
    if prev["close"] > last_low and latest["close"] < last_low: return "Bearish MSS"
    return "暂无 MSS"

def get_premium_discount_zone(df: pd.DataFrame, lookback=60):
    recent = df.tail(lookback)
    if recent.empty: return None
    range_high, range_low = recent["high"].max(), recent["low"].min()
    eq = (range_high + range_low) / 2
    latest_close = recent.iloc[-1]["close"]
    zone = "Premium Zone" if latest_close > eq else ("Discount Zone" if latest_close < eq else "Equilibrium")
    return {"range_high": range_high, "range_low": range_low, "equilibrium": eq, "zone": zone}

def build_smc_summary(df: pd.DataFrame):
    obs = detect_order_blocks(df)
    eqh, eql = detect_equal_high_low(df)
    mss = detect_mss(df)
    pd_zone = get_premium_discount_zone(df)
    return {
        "latest_bull_ob": next((z for z in reversed(obs) if z["type"] == "bullish_ob"), None),
        "latest_bear_ob": next((z for z in reversed(obs) if z["type"] == "bearish_ob"), None),
        "eqh": eqh, "eql": eql, "mss": mss, "pd_zone": pd_zone
    }

def summarize_technicals(df: pd.DataFrame):
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else latest
    trend = "多头趋势" if latest["close"] > latest["ema_short"] > latest["ema_mid"] else ("空头趋势" if latest["close"] < latest["ema_short"] < latest["ema_mid"] else "震荡")
    
    rsi = latest["rsi14"]
    momentum = "中性"
    if pd.notna(rsi):
        if rsi >= 70: momentum = "超买"
        elif rsi <= 30: momentum = "超卖"
        elif rsi > 55: momentum = "偏强"
        elif rsi < 45: momentum = "偏弱"
        
    macd_state = "中性"
    if latest["macd"] > latest["macd_signal"] and latest["macd_hist"] > prev["macd_hist"]: macd_state = "金叉后增强"
    elif latest["macd"] < latest["macd_signal"] and latest["macd_hist"] < prev["macd_hist"]: macd_state = "死叉后走弱"
    
    bb_state = "突破布林上轨" if latest["close"] > latest["bb_up"] else ("跌破布林下轨" if latest["close"] < latest["bb_low"] else "带内运行")
    
    vol_state = "量能平稳"
    if pd.notna(latest["vol_ma20"]) and latest["vol_ma20"] > 0:
        if latest["volume"] > latest["vol_ma20"] * 1.8: vol_state = "显著放量"
        elif latest["volume"] < latest["vol_ma20"] * 0.7: vol_state = "明显缩量"

    fvg_zones = detect_fvg(df)
    return {
        "trend": trend, "momentum": momentum, "macd_state": macd_state, "bb_state": bb_state, "vol_state": vol_state,
        "atr14": latest["atr14"], "rsi14": latest["rsi14"], "bos_state": detect_bos(df), "sweep_state": detect_liquidity_sweep(df),
        "nearest_bull_fvg": next((z for z in reversed(fvg_zones) if z["type"] == "bullish"), None),
        "nearest_bear_fvg": next((z for z in reversed(fvg_zones) if z["type"] == "bearish"), None),
        "latest_close": latest["close"], "ema_short": latest["ema_short"], "ema_mid": latest["ema_mid"], "ema_long": latest["ema_long"],
        "smc": build_smc_summary(df)
    }

# ================= 价格图表构建 =================
def build_price_figure(df: pd.DataFrame):
    plot_df = df.copy()
    plot_df["date_str"] = plot_df["date"].dt.strftime("%Y-%m-%d")

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, subplot_titles=('K 线与结构', '成交量'), row_width=[0.2, 0.7])

    fig.add_trace(go.Candlestick(x=plot_df["date_str"], open=plot_df["open"], high=plot_df["high"], low=plot_df["low"], close=plot_df["close"], name="K线"), row=1, col=1)
    fig.add_trace(go.Scatter(x=plot_df["date_str"], y=plot_df["ema_short"], mode="lines", name=f"EMA{ema_short}", line=dict(width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=plot_df["date_str"], y=plot_df["ema_mid"], mode="lines", name=f"EMA{ema_mid}", line=dict(width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=plot_df["date_str"], y=plot_df["ema_long"], mode="lines", name=f"EMA{ema_long}", line=dict(width=1)), row=1, col=1)

    # 修正 A股 涨红跌绿
    colors = ['#EF5350' if row['close'] >= row['open'] else '#26A69A' for index, row in plot_df.iterrows()]
    fig.add_trace(go.Bar(x=plot_df['date_str'], y=plot_df['volume'], marker_color=colors, name='成交量'), row=2, col=1)

    for zone in detect_fvg(plot_df, max_zones=4):
        x0, x1 = plot_df.iloc[zone["start_idx"]]["date_str"], plot_df.iloc[min(len(plot_df) - 1, zone["start_idx"] + 12)]["date_str"]
        fillcolor = "rgba(0, 200, 0, 0.15)" if zone["type"] == "bullish" else "rgba(200, 0, 0, 0.15)"
        fig.add_shape(type="rect", x0=x0, x1=x1, y0=zone["bottom"], y1=zone["top"], line=dict(width=0), fillcolor=fillcolor, row=1, col=1)

    fig.update_layout(height=650, xaxis_rangeslider_visible=False, margin=dict(l=20, r=20, t=30, b=20), showlegend=False)
    return fig

# ================= 多周期分析 =================
def normalize_min_df(df: pd.DataFrame):
    if df is None or df.empty: return None
    rename_map = {col: "date" for col in df.columns if col in ["时间", "日期", "datetime", "date"]}
    rename_map.update({"开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "volume"})
    df = df.rename(columns=rename_map).copy()
    need_cols = ["date", "open", "high", "low", "close", "volume"]
    if not all(col in df.columns for col in need_cols): return None
    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "high", "low", "close", "volume"]: df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna().sort_values("date").reset_index(drop=True)[need_cols]

def get_intraday_15m(symbol, max_rows=320):
    try:
        df = ak.stock_zh_a_hist_min_em(symbol=str(symbol), period="15", adjust="")
        df = normalize_min_df(df)
        return df.tail(max_rows).reset_index(drop=True) if df is not None else None
    except Exception as e:
        if DEBUG_MODE: st.warning(f"15分钟数据异常: {e}")
        return None

def aggregate_minutes(df_15m: pd.DataFrame, bars_per_group: int):
    if df_15m is None or df_15m.empty: return None
    df_15m = df_15m.copy()
    df_15m["trade_day"] = df_15m["date"].dt.date
    all_parts = []
    for _, day_df in df_15m.groupby("trade_day"):
        day_df = day_df.sort_values("date").reset_index(drop=True)
        grp = pd.Series(range(len(day_df))) // bars_per_group
        g = day_df.groupby(grp)
        part = pd.DataFrame({"date": g["date"].last(), "open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(), "close": g["close"].last(), "volume": g["volume"].sum()})
        all_parts.append(part)
    return pd.concat(all_parts, ignore_index=True).dropna().reset_index(drop=True) if all_parts else None

def summarize_intraday_tf(df: pd.DataFrame, label: str):
    if df is None or df.empty: return {"label": label, "status": "无数据", "trend": "N/A", "rsi": None, "macd_state": "N/A", "support": None, "pressure": None, "close": None, "bias": "无法判断"}
    df = df.copy()
    if len(df) >= 12:
        df = add_indicators(df)
        latest, prev = df.iloc[-1], df.iloc[-2] if len(df) > 1 else df.iloc[-1]
        trend = "多头" if pd.notna(latest["ema_mid"]) and latest["close"] > latest["ema_short"] > latest["ema_mid"] else ("空头" if pd.notna(latest["ema_mid"]) and latest["close"] < latest["ema_short"] < latest["ema_mid"] else "震荡")
        macd_state = "偏多" if pd.notna(latest["macd"]) and latest["macd"] > latest["macd_signal"] and latest["macd_hist"] >= prev["macd_hist"] else ("偏空" if pd.notna(latest["macd"]) and latest["macd"] < latest["macd_signal"] and latest["macd_hist"] <= prev["macd_hist"] else "中性")
        support, pressure = df.tail(min(12, len(df)))["low"].min(), df.tail(min(12, len(df)))["high"].max()
        
        bias_score = 0
        if trend in ["多头", "偏强"]: bias_score += 1
        if macd_state == "偏多": bias_score += 1
        if pd.notna(latest["rsi14"]) and latest["rsi14"] > 55: bias_score += 1
        if pd.notna(latest["rsi14"]) and latest["rsi14"] < 45: bias_score -= 1
        if macd_state == "偏空": bias_score -= 1
        if trend == "空头": bias_score -= 1
        
        bias = "多头占优" if bias_score >= 2 else ("空头占优" if bias_score <= -2 else "震荡分歧")
        return {"label": label, "status": "有效", "trend": trend, "rsi": latest["rsi14"] if pd.notna(latest["rsi14"]) else None, "macd_state": macd_state, "support": support, "pressure": pressure, "close": latest["close"], "bias": bias}
    
    return {"label": label, "status": "样本较少", "trend": "简化观察", "rsi": None, "macd_state": "N/A", "support": df["low"].min(), "pressure": df["high"].max(), "close": df.iloc[-1]["close"], "bias": "轻量判断"}

def get_multi_timeframe_analysis(symbol: str):
    df15 = get_intraday_15m(symbol)
    df60, df120 = aggregate_minutes(df15, 4) if df15 is not None else None, aggregate_minutes(df15, 8) if df15 is not None else None
    tf15, tf60, tf120 = summarize_intraday_tf(df15, "15分钟"), summarize_intraday_tf(df60, "60分钟"), summarize_intraday_tf(df120, "120分钟")
    
    score = sum([{"多头占优": 2, "轻量判断": 0, "震荡分歧": 0, "空头占优": -2}.get(tf["bias"], 0) for tf in [tf15, tf60, tf120]])
    final_view = "多周期共振偏多" if score >= 3 else ("多周期共振偏空" if score <= -3 else "多周期分歧，偏观察")
    return {"15m": tf15, "60m": tf60, "120m": tf120, "final_view": final_view}

# ================= 数据拉取模块 =================
@st.cache_data(ttl=60)
def get_global_news():
    res = fetch_json("https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size=60&zhibo_id=152&tag_id=0&dire=f&dpc=1", extra_headers={"Referer": "https://finance.sina.com.cn/"})
    news = []
    if res and res.get("result", {}).get("data", {}).get("feed", {}).get("list"):
        for item in res["result"]["data"]["feed"]["list"]:
            text = re.sub(r'<[^>]+>', '', str(item.get("rich_text", "")).strip())
            if len(text) > 15: news.append(f"[{item.get('create_time', '')}] {text}")
    return news

@st.cache_data(ttl=60)
def get_market_pulse():
    pulse = {}
    for name, code in {"上证指数": "1.000001", "深证成指": "0.399001", "创业板指": "0.399006"}.items():
        res = fetch_json(f"https://push2.eastmoney.com/api/qt/stock/get?secid={code}&ut=fa5fd1943c7b386f172d6893dbfba10b&fltt=2&fields=f43,f170")
        if res and res.get("data"): pulse[name] = {"price": safe_float(res["data"].get("f43")), "pct": safe_float(res["data"].get("f170"))}
    cnh_res = fetch_json("https://push2.eastmoney.com/api/qt/stock/get?secid=133.USDCNH&ut=fa5fd1943c7b386f172d6893dbfba10b&fltt=2&fields=f43,f170")
    if cnh_res and cnh_res.get("data"): pulse["USD/CNH(离岸)"] = {"price": safe_float(cnh_res["data"].get("f43")), "pct": safe_float(cnh_res["data"].get("f170"))}
    return pulse

@st.cache_data(ttl=300)
def get_hot_blocks():
    try:
        df = ak.stock_board_industry_name_em()
        if df is not None and not df.empty: return df.sort_values(by="涨跌幅", ascending=False).head(10)[["板块名称", "涨跌幅", "上涨家数", "下跌家数", "领涨股票"]].to_dict('records')
    except: pass
    time.sleep(1)
    try:
        df = ak.stock_board_concept_name_em()
        if df is not None and not df.empty: return df.sort_values(by="涨跌幅", ascending=False).head(10)[["板块名称", "涨跌幅", "上涨家数", "下跌家数", "领涨股票"]].to_dict('records')
    except: pass
    return None

def get_stock_quote(symbol):
    try:
        spot_df = ak.stock_zh_a_spot_em()
        if spot_df is not None and not spot_df.empty:
            row = spot_df[spot_df["代码"].astype(str) == str(symbol)]
            if not row.empty:
                row = row.iloc[0]
                return {"name": row.get("名称", "未知"), "price": safe_float(row.get("最新价")), "pct": safe_float(row.get("涨跌幅")), "market_cap": safe_float(row.get("总市值")) / 100000000, "pe": row.get("市盈率-动态", "-"), "pb": row.get("市净率", "-"), "turnover": safe_float(row.get("换手率"))}
    except Exception as e:
        if DEBUG_MODE: st.warning(f"AKShare 实时行情降级: {e}")
    
    market = "1" if str(symbol).startswith(("6", "9", "5", "7")) else "0"
    res = fetch_json(f"https://push2.eastmoney.com/api/qt/stock/get?secid={market}.{symbol}&ut=fa5fd1943c7b386f172d6893dbfba10b&fltt=2&fields=f58,f43,f60,f170,f116,f162,f168,f167")
    if res and res.get("data"):
        d = res["data"]
        return {"name": d.get("f58", "未知"), "price": normalize_em_price(d.get("f43"), safe_float(d.get("f60"))), "pct": safe_float(d.get("f170")), "market_cap": safe_float(d.get("f116")) / 100000000, "pe": d.get("f162", "-"), "pb": d.get("f167", "-"), "turnover": safe_float(d.get("f168"))}
    return None

def get_fund_flow(symbol):
    # 新增资金流向追踪模块
    try:
        df = ak.stock_individual_fund_flow(symbol=str(symbol), market="sh" if str(symbol).startswith("6") else "sz")
        if not df.empty:
            latest = df.iloc[-1]
            return {
                "main_net_in": safe_float(latest.get("主力净流入-净额", 0)),
                "main_net_pct": safe_float(latest.get("主力净流入-净占比", 0)),
                "super_net_in": safe_float(latest.get("超大单净流入-净额", 0))
            }
    except:
        pass
    return None

def get_kline(symbol, days=220):
    end_date = datetime.now()
    start_str = (end_date - pd.Timedelta(days=days + 150)).strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")
    
    try:
        df = ak.stock_zh_a_hist(symbol=str(symbol), period="daily", start_date=start_str, end_date=end_str, adjust="qfq")
        if df is not None and not df.empty:
            df = df.rename(columns={"日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "volume", "换手率": "turnover_rate"})
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                for col in ["open", "high", "low", "close", "volume"]: df[col] = pd.to_numeric(df[col], errors="coerce")
                return df.dropna().reset_index(drop=True).tail(days)
    except: pass
    
    # 简化兜底逻辑，保持轻量
    try:
        bs.login()
        bs_code = f"sh.{symbol}" if str(symbol).startswith(("6", "9", "5", "7")) else f"sz.{symbol}"
        rs = bs.query_history_k_data_plus(bs_code, "date,open,high,low,close,volume", start_date=(end_date - pd.Timedelta(days=days + 150)).strftime("%Y-%m-%d"), end_date=end_date.strftime("%Y-%m-%d"), frequency="d", adjustflag="2")
        data_list = []
        while (rs.error_code == '0') & rs.next(): data_list.append(rs.get_row_data())
        bs.logout()
        if data_list:
            df = pd.DataFrame(data_list, columns=rs.fields)
            df["date"] = pd.to_datetime(df["date"])
            for col in ["open", "high", "low", "close", "volume"]: df[col] = pd.to_numeric(df[col], errors="coerce")
            return df.dropna().sort_values("date").reset_index(drop=True).tail(days)
    except: pass
    
    return None

# ================= AI 计算核心 =================
def call_ai(prompt, model=None, temperature=0.3):
    try:
        exec_model = model if model else selected_model
        client = Groq(api_key=api_key)
        completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=exec_model,
            temperature=temperature
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"❌ AI 计算节点故障: {e}"

# ================= 终端全局看板 =================
st.markdown("### 🌍 宏观市场实时看板")
pulse_data = get_market_pulse()
if pulse_data:
    dash_cols = st.columns(len(pulse_data))
    for idx, (key, data) in enumerate(pulse_data.items()):
        with dash_cols[idx]:
            with st.container(border=True):
                if "CNH" in key:
                    st.metric(key, f"{data['price']:.4f}", f"{data['pct']:.2f}%", delta_color="inverse")
                else:
                    st.metric(key, f"{data['price']:.2f}", f"{data['pct']:.2f}%")
else: st.warning("宏观看板数据流建立失败。")
st.markdown("<br>", unsafe_allow_html=True)

# ================= 终端功能选项卡 =================
tab1, tab2, tab3, tab4 = st.tabs(["🎯 I. 个股标的解析", "📈 II. 宏观大盘推演", "🔥 III. 资金热点板块", "🦅 IV. 高阶情报终端"])

# ================= Tab 1: 个股解析 =================
with tab1:
    with st.container(border=True):
        st.markdown("#### 🔎 个股雷达锁定（多维买卖点测算版）")
        col1, col2 = st.columns([1, 1])
        with col1:
            symbol_input = st.text_input("标的代码", placeholder="例：600519")
            analyze_btn = st.button("启动核心算法", type="primary", use_container_width=True)
        
        if analyze_btn:
            if not api_key: st.error("配置缺失: GROQ_API_KEY")
            elif len(symbol_input.strip()) != 6: st.warning("代码规范验证失败")
            else:
                with st.spinner("量子计算与数据提取中 (启用多重行情数据引擎 + 多周期分析 + 资金流监控)..."):
                    quote = get_stock_quote(symbol_input)
                    df_kline = get_kline(symbol_input, days=220)
                    mtf = get_multi_timeframe_analysis(symbol_input)
                    fund_flow = get_fund_flow(symbol_input) # 拉取资金流向

                if not quote: st.error("无法捕获行情资产。")
                else:
                    st.markdown("---")
                    name, price, pct = quote["name"], quote["price"], quote["pct"]
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric(f"{name}", f"{price:.2f}", f"{pct:.2f}%")
                    c2.metric("总市值(亿)", f"{quote['market_cap']:.1f}")
                    c3.metric("动态 PE", f"{quote['pe']}")
                    c4.metric("换手率", f"{quote['turnover']:.2f}%")
                    
                    if fund_flow:
                        st.markdown("##### 💸 当日主力资金博弈 (Smart Money)")
                        cf1, cf2, cf3 = st.columns(3)
                        cf1.metric("主力净流入 (元)", f"{fund_flow['main_net_in']:,.0f}")
                        cf2.metric("超大单净流入 (元)", f"{fund_flow['super_net_in']:,.0f}")
                        cf3.metric("主力净占比", f"{fund_flow['main_net_pct']:.2f}%")

                    if df_kline is None or len(df_kline) < 15:
                        st.warning("获取到的有效 K 线极少，仅能通过最新行情进行轻量化推演。")
                    else:
                        df_kline = add_indicators(df_kline)
                        tech = summarize_technicals(df_kline)
                        smc = tech["smc"]
                        fig = build_price_figure(df_kline)
                        st.plotly_chart(fig, use_container_width=True)

                        st.markdown("##### 🔬 核心技术指标与阻力测算")
                        t1, t2, t3, t4 = st.columns(4)
                        t1.metric("趋势", tech["trend"])
                        t2.metric("RSI14", f"{tech['rsi14']:.2f}" if pd.notna(tech["rsi14"]) else "N/A")
                        t3.metric("ATR14", f"{tech['atr14']:.2f}" if pd.notna(tech["atr14"]) else "N/A")
                        t4.metric("MACD 状态", tech["macd_state"])
                        t5, t6, t7, t8 = st.columns(4)
                        t5.metric("布林状态", tech["bb_state"])
                        t6.metric("量能状态", tech["vol_state"])
                        t7.metric("BOS", tech["bos_state"])
                        t8.metric("流动性扫盘", tech["sweep_state"])

                        st.markdown("##### 🧩 FVG / SMC 结构信息")
                        f1, f2 = st.columns(2)
                        with f1:
                            bull_fvg = tech["nearest_bull_fvg"]
                            if bull_fvg: st.success(f"多头 FVG：{bull_fvg['date']} | {bull_fvg['bottom']:.2f} - {bull_fvg['top']:.2f}")
                            if smc["latest_bull_ob"]: st.success(f"多头 OB：{smc['latest_bull_ob']['date']} | {smc['latest_bull_ob']['bottom']:.2f} - {smc['latest_bull_ob']['top']:.2f}")
                        with f2:
                            bear_fvg = tech["nearest_bear_fvg"]
                            if bear_fvg: st.error(f"空头 FVG：{bear_fvg['date']} | {bear_fvg['bottom']:.2f} - {bear_fvg['top']:.2f}")
                            if smc["latest_bear_ob"]: st.error(f"空头 OB：{smc['latest_bear_ob']['date']} | {smc['latest_bear_ob']['bottom']:.2f} - {smc['latest_bear_ob']['top']:.2f}")

                        st.markdown("##### ⏱️ 多周期技术分析")
                        m1, m2, m3 = st.columns(3)
                        with m1:
                            st.markdown("**15分钟级别**")
                            st.metric("偏向", mtf["15m"]["bias"])
                            st.metric("趋势", mtf["15m"]["trend"])
                        with m2:
                            st.markdown("**60分钟级别**")
                            st.metric("偏向", mtf["60m"]["bias"])
                            st.metric("趋势", mtf["60m"]["trend"])
                        with m3:
                            st.markdown("**120分钟级别**")
                            st.metric("偏向", mtf["120m"]["bias"])
                            st.metric("趋势", mtf["120m"]["trend"])

                        st.info(f"多周期共振结论：**{mtf['final_view']}**")

                        with st.spinner(f"🧠 首席策略官正在使用 {selected_model} 进行多维深度解构..."):
                            ema_mid_val = f"{tech['ema_mid']:.2f}" if pd.notna(tech['ema_mid']) else "数据不足"
                            ema_long_val = f"{tech['ema_long']:.2f}" if pd.notna(tech['ema_long']) else "数据不足"
                            fund_str = f"主力净流入: {fund_flow['main_net_in']}元 (占比{fund_flow['main_net_pct']}%)" if fund_flow else "未知"
                            
                            prompt = f"""
你现在是顶级私募基金的操盘手（精通基本面、量价资金博弈、多周期共振）。
请对股票 {name}({symbol_input}) 做一份极具实战价值的【估值 + 资金流 + 支撑/压力 + 精准买卖点 + 多周期共振】综合研判。
【基础与资金博弈数据】
- 现价: {price} (日涨跌幅: {pct}%)
- 总市值: {quote['market_cap']} 亿 | 动态 PE: {quote['pe']}
- 当日换手率: {quote['turnover']}%
- 资金流向监控: {fund_str}
【核心技术与结构】
- 趋势状态: {tech['trend']} | 最新收盘: {tech['latest_close']}
- 异常流动性: 扫盘({tech['sweep_state']}), MSS({smc['mss']})
- 近期多头磁区 (支撑): FVG {tech['nearest_bull_fvg']}, OB {smc['latest_bull_ob']}
- 近期空头磁区 (阻力): FVG {tech['nearest_bear_fvg']}, OB {smc['latest_bear_ob']}
【多周期分析结论】: {mtf['final_view']}
【请务必输出】
1. 🏦 基本面与聪明钱动向定调
2. 🎯 核心支撑与压力位测算
3. ⚔️ 实战波段交易推演（给出具体的进场点位、止损位与目标位建议）
4. 一句话总结：强势看多 / 偏多观察 / 震荡等待 / 谨慎偏空
"""
                            ai_report = call_ai(prompt)
                            st.markdown("### 📝 首席AI研判报告")
                            st.markdown(ai_report)
                            
                            # 预警推送功能挂载
                            if server_key:
                                if st.button("📲 将研判报告推送到微信", type="secondary"):
                                    push_title = f"AI研判预警: {name} ({symbol_input})"
                                    success, msg = push_to_wechat(push_title, ai_report, server_key)
                                    if success: st.success("推送已送达微信！")
                                    else: st.error(msg)

# ================= Tab 2, 3, 4 保持原逻辑优化 =================
with tab2:
    with st.container(border=True):
        st.markdown("#### 📊 全盘系统级推演")
        if st.button("运行大盘沙盘推演", type="primary"):
            if not api_key: st.error("配置缺失: GROQ_API_KEY")
            else:
                with st.spinner("推演引擎初始化..."):
                    prompt = f"你现在是首席宏观策略师。请基于当前 A 股与外汇的精准数据进行大局观推演：\n实时数据：{str(pulse_data)}\n请输出：\n1. 市场全景定调\n2. 北向资金意愿推断\n3. 短期沙盘推演方向"
                    st.markdown(call_ai(prompt, temperature=0.4))

with tab3:
    with st.container(border=True):
        st.markdown("#### 🔥 当日主力资金狂欢地 (附实战标的推荐)")
        if st.button("扫描板块与生成配置推荐", type="primary"):
            if not api_key: st.error("配置缺失: GROQ_API_KEY")
            else:
                with st.spinner("深潜获取异动数据..."):
                    blocks = get_hot_blocks()
                    if blocks:
                        st.dataframe(pd.DataFrame(blocks), use_container_width=True, hide_index=True)
                        blocks_str = "\n".join([f"{b['板块名称']} (涨幅:{b['涨跌幅']}%, 领涨龙头:{b['领涨股票']})" for b in blocks[:5]])
                        prompt = f"深度解读今日最强的 5 个板块及其领涨龙头：\n{blocks_str}\n请输出：\n1. 核心驱动逻辑\n2. 行情定性\n3. 推荐 2-3 只实战标的及配置理由"
                        st.markdown(call_ai(prompt, temperature=0.4))
                    else: st.error("获取板块数据失败。")

with tab4:
    st.markdown("#### 📡 机构级事件图谱与智能评级矩阵")
    if st.button("🚨 截获并解析全球突发", type="primary"):
        if not api_key: st.error("配置缺失: GROQ_API_KEY")
        else:
            with st.spinner("监听全网节点并执行深度 NLP 解析..."):
                global_news = get_global_news()
                if not global_news: st.warning("信号静默。")
                else:
                    news_text = "\n".join(global_news)
                    with st.expander("🕵️‍♂️ 查看底层监听流 (Raw Data)"): st.text(news_text)
                    prompt = f"挑选出最具市场影响力的 5-8 条动态。\n⚠️ 绝对不能使用表格！必须为每一个事件生成独立的情报卡片。\n格式：\n### [评级 Emoji] [[信源]] [事件标题]\n* ⏰ **时间截获**:\n* 📝 **情报简述**:\n* 🎯 **受波及资产**:\n* 🧠 **沙盘推演**:\n* ☢️ **风控预警**:\n---\n数据流：{news_text}"
                    st.markdown(call_ai(prompt, temperature=0.2))
