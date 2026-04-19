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
from datetime import datetime
import plotly.graph_objects as go

st.set_page_config(
    page_title="AI 智能投研终端 Pro Max",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
.stTabs [data-baseweb="tab-list"] { gap: 10px; flex-wrap: wrap; }
.stTabs [data-baseweb="tab"] {
    height: auto;
    min-height: 40px;
    white-space: normal;
    background-color: transparent;
    border-radius: 4px 4px 0 0;
    padding: 8px 12px;
    font-weight: bold;
}
.terminal-header {
    font-family: 'Courier New', Courier, monospace;
    color: #888;
    font-size: 0.8em;
    margin-bottom: 20px;
    word-wrap: break-word;
}
[data-testid="stMetricValue"] {
    font-size: 1.5rem;
}
</style>
""", unsafe_allow_html=True)

st.title("🏦 AI 智能量化投研终端")
st.markdown(
    f"<div class='terminal-header'>TERMINAL BUILD v6.3.2 | SYS_TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | FINAL HOTFIX</div>",
    unsafe_allow_html=True,
)

api_key = st.secrets.get("GROQ_API_KEY", "")

with st.sidebar:
    st.header("⚙️ 终端控制台")
    ts_token = st.text_input("🔑 Tushare Token", type="password", help="仅作极致容灾兜底")
    DEBUG_MODE = st.checkbox("🛠️ 开启底层日志嗅探")
    st.markdown("---")
    st.markdown("### 📡 数据连通性")
    st.success("行情引流 : ACTIVE")
    st.success("7x24快讯 : ACTIVE")
    st.success("板块扫描 : ACTIVE")
    st.success("技术结构引擎 : ACTIVE")
    st.success("多周期分析 : ACTIVE (15m / 60m / 120m)")

if ts_token:
    ts.set_token(ts_token)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:115.0) Gecko/20100101 Firefox/115.0",
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
    if val is None or val == "-" or str(val).strip() == "":
        return default
    try:
        return float(val)
    except Exception:
        return default


def fetch_json(url, timeout=8, extra_headers=None):
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    if extra_headers:
        headers.update(extra_headers)
    try:
        res = SESSION.get(url, headers=headers, timeout=timeout)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        if DEBUG_MODE:
            st.warning(f"请求失败: {e}")
        return None


def normalize_em_price(raw_price, prev_close=None):
    raw_price = safe_float(raw_price)
    prev_close = safe_float(prev_close)
    if raw_price <= 0:
        return 0.0
    candidates = [raw_price, raw_price / 10, raw_price / 100, raw_price / 1000]
    candidates = [x for x in candidates if 0.01 <= x <= 100000]
    if not candidates:
        return raw_price
    if prev_close > 0:
        return min(candidates, key=lambda x: abs(x - prev_close))
    return min(candidates, key=lambda x: abs(x - (raw_price / 100 if raw_price > 1000 else raw_price)))


def normalize_min_df(df: pd.DataFrame):
    if df is None or df.empty:
        return None
    df = df.copy()
    rename_map = {}
    for col in df.columns:
        if col in ["时间", "日期", "datetime", "date"]:
            rename_map[col] = "date"
        elif col == "开盘":
            rename_map[col] = "open"
        elif col == "收盘":
            rename_map[col] = "close"
        elif col == "最高":
            rename_map[col] = "high"
        elif col == "最低":
            rename_map[col] = "low"
        elif col in ["成交量", "volume"]:
            rename_map[col] = "volume"
    df = df.rename(columns=rename_map)
    need_cols = ["date", "open", "high", "low", "close", "volume"]
    if not all(col in df.columns for col in need_cols):
        return None
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=need_cols).sort_values("date").reset_index(drop=True)
    return df[need_cols]


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema60"] = df["close"].ewm(span=60, adjust=False).mean()
    df["ema120"] = df["close"].ewm(span=120, adjust=False).mean()
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
    if len(df) < left + right + 1:
        return swing_highs, swing_lows
    for i in range(left, len(df) - right):
        high = df["high"].iloc[i]
        low = df["low"].iloc[i]
        if high == df["high"].iloc[i-left:i+right+1].max():
            swing_highs.append((i, high))
        if low == df["low"].iloc[i-left:i+right+1].min():
            swing_lows.append((i, low))
    return swing_highs, swing_lows


def detect_fvg(df: pd.DataFrame, max_zones=5):
    zones = []
    if len(df) < 3:
        return zones
    for i in range(2, len(df)):
        c1 = df.iloc[i - 2]
        c3 = df.iloc[i]
        if c3["low"] > c1["high"]:
            zones.append({"type": "bullish", "start_idx": i - 2, "end_idx": i, "top": c3["low"], "bottom": c1["high"], "date": str(pd.to_datetime(c3["date"]).date())})
        if c3["high"] < c1["low"]:
            zones.append({"type": "bearish", "start_idx": i - 2, "end_idx": i, "top": c1["low"], "bottom": c3["high"], "date": str(pd.to_datetime(c3["date"]).date())})
    return zones[-max_zones:]


def detect_liquidity_sweep(df: pd.DataFrame):
    if len(df) < 25:
        return "样本不足"
    recent = df.tail(20).copy()
    latest = recent.iloc[-1]
    prev_high = recent.iloc[:-1]["high"].max()
    prev_low = recent.iloc[:-1]["low"].min()
    if latest["high"] > prev_high and latest["close"] < prev_high:
        return "向上扫流动性后回落"
    if latest["low"] < prev_low and latest["close"] > prev_low:
        return "向下扫流动性后收回"
    return "未见明显扫流动性"


def detect_bos(df: pd.DataFrame):
    swing_highs, swing_lows = detect_swings(df)
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "结构样本不足"
    latest_close = df.iloc[-1]["close"]
    last_swing_high = swing_highs[-1][1]
    last_swing_low = swing_lows[-1][1]
    if latest_close > last_swing_high:
        return "向上 BOS (结构突破)"
    if latest_close < last_swing_low:
        return "向下 BOS (结构破坏)"
    return "结构未突破"


def detect_order_blocks(df: pd.DataFrame, lookback=30, max_zones=4):
    zones = []
    recent = df.tail(lookback).reset_index(drop=True)
    if len(recent) < 3 or "atr14" not in recent.columns:
        return zones
    for i in range(1, len(recent) - 1):
        curr = recent.iloc[i]
        nxt = recent.iloc[i + 1]
        body_curr = abs(curr["close"] - curr["open"])
        atr = recent["atr14"].iloc[i]
        if pd.isna(atr):
            continue
        if curr["close"] < curr["open"] and nxt["close"] > curr["high"] and body_curr < atr * 1.2:
            zones.append({"type": "bullish_ob", "date": str(pd.to_datetime(curr["date"]).date()), "top": max(curr["open"], curr["close"]), "bottom": min(curr["open"], curr["close"])})
        if curr["close"] > curr["open"] and nxt["close"] < curr["low"] and body_curr < atr * 1.2:
            zones.append({"type": "bearish_ob", "date": str(pd.to_datetime(curr["date"]).date()), "top": max(curr["open"], curr["close"]), "bottom": min(curr["open"], curr["close"])})
    return zones[-max_zones:]


def detect_equal_high_low(df: pd.DataFrame, tolerance=0.003):
    swing_highs, swing_lows = detect_swings(df)
    eqh, eql = [], []
    for i in range(len(swing_highs) - 1):
        h1, h2 = swing_highs[i][1], swing_highs[i + 1][1]
        if h1 > 0 and abs(h1 - h2) / h1 <= tolerance:
            eqh.append((swing_highs[i], swing_highs[i + 1]))
    for i in range(len(swing_lows) - 1):
        l1, l2 = swing_lows[i][1], swing_lows[i + 1][1]
        if l1 > 0 and abs(l1 - l2) / l1 <= tolerance:
            eql.append((swing_lows[i], swing_lows[i + 1]))
    return eqh[-3:], eql[-3:]


def detect_mss(df: pd.DataFrame):
    swing_highs, swing_lows = detect_swings(df)
    if len(swing_highs) < 2 or len(swing_lows) < 2 or len(df) < 2:
        return "样本不足"
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    last_high = swing_highs[-1][1]
    last_low = swing_lows[-1][1]
    if prev["close"] < last_high and latest["close"] > last_high:
        return "Bullish MSS (多头结构转换)"
    if prev["close"] > last_low and latest["close"] < last_low:
        return "Bearish MSS (空头结构转换)"
    return "暂无明显 MSS"


def get_premium_discount_zone(df: pd.DataFrame, lookback=60):
    recent = df.tail(lookback)
    if recent.empty:
        return None
    range_high = recent["high"].max()
    range_low = recent["low"].min()
    eq = (range_high + range_low) / 2
    latest_close = recent.iloc[-1]["close"]
    zone = "Equilibrium"
    if latest_close > eq:
        zone = "Premium Zone"
    elif latest_close < eq:
        zone = "Discount Zone"
    return {"range_high": range_high, "range_low": range_low, "equilibrium": eq, "zone": zone}


def build_smc_summary(df: pd.DataFrame):
    obs = detect_order_blocks(df)
    eqh, eql = detect_equal_high_low(df)
    mss = detect_mss(df)
    pd_zone = get_premium_discount_zone(df)
    latest_bull_ob = next((z for z in reversed(obs) if z["type"] == "bullish_ob"), None)
    latest_bear_ob = next((z for z in reversed(obs) if z["type"] == "bearish_ob"), None)
    return {"latest_bull_ob": latest_bull_ob, "latest_bear_ob": latest_bear_ob, "eqh": eqh, "eql": eql, "mss": mss, "pd_zone": pd_zone}


def summarize_technicals(df: pd.DataFrame):
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else latest
    trend = "震荡"
    if latest["close"] > latest["ema20"] > latest["ema60"]:
        trend = "多头趋势"
    elif latest["close"] < latest["ema20"] < latest["ema60"]:
        trend = "空头趋势"
    rsi = latest["rsi14"]
    macd_state = "中性"
    if latest["macd"] > latest["macd_signal"] and latest["macd_hist"] > prev["macd_hist"]:
        macd_state = "金叉后增强"
    elif latest["macd"] < latest["macd_signal"] and latest["macd_hist"] < prev["macd_hist"]:
        macd_state = "死叉后走弱"
    bb_state = "带内运行"
    if latest["close"] > latest["bb_up"]:
        bb_state = "突破布林上轨"
    elif latest["close"] < latest["bb_low"]:
        bb_state = "跌破布林下轨"
    vol_state = "量能平稳"
    if pd.notna(latest["vol_ma20"]) and latest["vol_ma20"] > 0:
        if latest["volume"] > latest["vol_ma20"] * 1.8:
            vol_state = "显著放量"
        elif latest["volume"] < latest["vol_ma20"] * 0.7:
            vol_state = "明显缩量"
    fvg_zones = detect_fvg(df)
    bos_state = detect_bos(df)
    sweep_state = detect_liquidity_sweep(df)
    nearest_bull_fvg = next((z for z in reversed(fvg_zones) if z["type"] == "bullish"), None)
    nearest_bear_fvg = next((z for z in reversed(fvg_zones) if z["type"] == "bearish"), None)
    smc = build_smc_summary(df)
    return {
        "trend": trend,
        "macd_state": macd_state,
        "bb_state": bb_state,
        "vol_state": vol_state,
        "atr14": latest["atr14"],
        "rsi14": rsi,
        "bos_state": bos_state,
        "sweep_state": sweep_state,
        "nearest_bull_fvg": nearest_bull_fvg,
        "nearest_bear_fvg": nearest_bear_fvg,
        "latest_close": latest["close"],
        "ema20": latest["ema20"],
        "ema60": latest["ema60"],
        "ema120": latest["ema120"],
        "smc": smc,
    }


def build_price_figure(df: pd.DataFrame):
    plot_df = df.copy()
    plot_df["date_str"] = plot_df["date"].dt.strftime("%Y-%m-%d")
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=plot_df["date_str"], open=plot_df["open"], high=plot_df["high"], low=plot_df["low"], close=plot_df["close"], name="K线"))
    fig.add_trace(go.Scatter(x=plot_df["date_str"], y=plot_df["ema20"], mode="lines", name="EMA20"))
    fig.add_trace(go.Scatter(x=plot_df["date_str"], y=plot_df["ema60"], mode="lines", name="EMA60"))
    fig.add_trace(go.Scatter(x=plot_df["date_str"], y=plot_df["ema120"], mode="lines", name="EMA120"))
    fig.update_layout(height=520, xaxis_title="日期", yaxis_title="价格", xaxis_rangeslider_visible=False, legend_title="图层", margin=dict(l=20, r=20, t=30, b=20))
    return fig


@st.cache_data(ttl=120)
def get_intraday_15m(symbol, max_rows=320):
    try:
        df = ak.stock_zh_a_hist_min_em(symbol=str(symbol), period="15", adjust="")
        df = normalize_min_df(df)
        if df is not None and not df.empty and len(df) >= 8:
            return df.tail(max_rows).reset_index(drop=True)
    except Exception:
        pass
    try:
        market = "1" if str(symbol).startswith(("6", "9", "5", "7")) else "0"
        url = (
            f"https://push2his.eastmoney.com/api/qt/stock/kline/get?"
            f"secid={market}.{symbol}&ut=fa5fd1943c7b386f172d6893dbfba10b"
            f"&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58"
            f"&klt=15&fqt=1&end=20500101&lmt=1000"
        )
        res = fetch_json(url, timeout=8)
        if res and res.get("data") and res["data"].get("klines"):
            rows = []
            for item in res["data"]["klines"]:
                parts = item.split(",")
                if len(parts) >= 6:
                    rows.append({"date": parts[0], "open": parts[1], "close": parts[2], "high": parts[3], "low": parts[4], "volume": parts[5]})
            df = normalize_min_df(pd.DataFrame(rows))
            if df is not None and not df.empty:
                return df.tail(max_rows).reset_index(drop=True)
    except Exception:
        pass
    return None


def aggregate_minutes(df_15m: pd.DataFrame, bars_per_group: int):
    if df_15m is None or df_15m.empty:
        return None
    all_parts = []
    df_15m = df_15m.copy()
    df_15m["trade_day"] = df_15m["date"].dt.date
    for _, day_df in df_15m.groupby("trade_day"):
        day_df = day_df.sort_values("date").reset_index(drop=True)
        grp = pd.Series(range(len(day_df))) // bars_per_group
        g = day_df.groupby(grp)
        part = pd.DataFrame({
            "date": g["date"].last(),
            "open": g["open"].first(),
            "high": g["high"].max(),
            "low": g["low"].min(),
            "close": g["close"].last(),
            "volume": g["volume"].sum(),
        })
        all_parts.append(part)
    if not all_parts:
        return None
    return pd.concat(all_parts, ignore_index=True).dropna().reset_index(drop=True)


def summarize_intraday_tf(df: pd.DataFrame, label: str):
    if df is None or df.empty:
        return {"label": label, "status": "无数据", "trend": "N/A", "rsi": None, "macd_state": "N/A", "support": None, "pressure": None, "close": None, "bias": "无法判断"}
    df = df.copy()
    if len(df) < 12:
        latest = df.iloc[-1]
        support = df["low"].min()
        pressure = df["high"].max()
        trend = "偏强" if len(df) >= 3 and latest["close"] > df["close"].iloc[0] else "偏弱"
        bias = "轻量偏多" if latest["close"] > df["open"].mean() else "轻量偏空"
        return {"label": label, "status": "样本较少", "trend": trend, "rsi": None, "macd_state": "简化判断", "support": support, "pressure": pressure, "close": latest["close"], "bias": bias}
    df = add_indicators(df)
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest
    trend = "震荡"
    if pd.notna(latest["ema20"]) and pd.notna(latest["ema60"]) and latest["close"] > latest["ema20"] > latest["ema60"]:
        trend = "多头"
    elif pd.notna(latest["ema20"]) and pd.notna(latest["ema60"]) and latest["close"] < latest["ema20"] < latest["ema60"]:
        trend = "空头"
    elif pd.notna(latest["ema20"]) and latest["close"] > latest["ema20"]:
        trend = "偏强"
    macd_state = "中性"
    if pd.notna(latest["macd"]) and pd.notna(latest["macd_signal"]):
        if latest["macd"] > latest["macd_signal"] and latest["macd_hist"] >= prev["macd_hist"]:
            macd_state = "偏多"
        elif latest["macd"] < latest["macd_signal"] and latest["macd_hist"] <= prev["macd_hist"]:
            macd_state = "偏空"
    support = df.tail(min(12, len(df)))["low"].min()
    pressure = df.tail(min(12, len(df)))["high"].max()
    score = 0
    if trend in ["多头", "偏强"]:
        score += 1
    if macd_state == "偏多":
        score += 1
    if pd.notna(latest["rsi14"]) and latest["rsi14"] > 55:
        score += 1
    if pd.notna(latest["rsi14"]) and latest["rsi14"] < 45:
        score -= 1
    if macd_state == "偏空":
        score -= 1
    if trend == "空头":
        score -= 1
    bias = "多头占优" if score >= 2 else "空头占优" if score <= -2 else "震荡分歧"
    return {"label": label, "status": "有效", "trend": trend, "rsi": latest["rsi14"] if pd.notna(latest["rsi14"]) else None, "macd_state": macd_state, "support": support, "pressure": pressure, "close": latest["close"], "bias": bias}


def get_multi_timeframe_analysis(symbol: str):
    df15 = get_intraday_15m(symbol)
    df60 = aggregate_minutes(df15, 4) if df15 is not None else None
    df120 = aggregate_minutes(df15, 8) if df15 is not None else None
    tf15 = summarize_intraday_tf(df15, "15分钟")
    tf60 = summarize_intraday_tf(df60, "60分钟")
    tf120 = summarize_intraday_tf(df120, "120分钟")
    score_map = {"多头占优": 2, "轻量偏多": 1, "震荡分歧": 0, "轻量偏空": -1, "空头占优": -2}
    score = score_map.get(tf15["bias"], 0) + score_map.get(tf60["bias"], 0) + score_map.get(tf120["bias"], 0)
    if score >= 3:
        final_view = "多周期共振偏多"
    elif score <= -3:
        final_view = "多周期共振偏空"
    else:
        final_view = "多周期分歧，偏观察"
    return {"15m": tf15, "60m": tf60, "120m": tf120, "final_view": final_view}


def call_ai(prompt, model="llama-3.3-70b-versatile", temperature=0.3):
    try:
        client = Groq(api_key=api_key)
        completion = client.chat.completions.create(messages=[{"role": "user", "content": prompt}], model=model, temperature=temperature)
        return completion.choices[0].message.content
    except Exception as e:
        return f"❌ AI 计算节点故障: {e}"


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
else:
    st.warning("宏观看板数据流建立失败。")

st.markdown("<br>", unsafe_allow_html=True)

tab1, tab2, tab3, tab4 = st.tabs([
    "🎯 I. 个股标的解析",
    "📈 II. 宏观大盘推演",
    "🔥 III. 资金热点板块",
    "🦅 IV. 高阶情报终端"
])

with tab1:
    with st.container(border=True):
        st.markdown("#### 🔎 个股雷达锁定（多维买卖点测算版）")
        col1, col2 = st.columns([1, 1])
        with col1:
            symbol_input = st.text_input("标的代码", placeholder="例：600519")
            analyze_btn = st.button("启动核心算法", type="primary", width="stretch")
        if analyze_btn:
            if not api_key:
                st.error("配置缺失: GROQ_API_KEY")
            elif len(symbol_input.strip()) != 6:
                st.warning("代码规范验证失败")
            else:
                with st.spinner("量子计算与数据提取中..."):
                    quote = get_stock_quote(symbol_input)
                    df_kline = get_kline(symbol_input, days=220)
                    mtf = get_multi_timeframe_analysis(symbol_input)
                if not quote:
                    st.error("无法捕获行情资产。")
                else:
                    name, price, pct = quote["name"], quote["price"], quote["pct"]
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric(f"{name}", f"{price:.2f}", f"{pct:.2f}%")
                    c2.metric("总市值(亿)", f"{quote['market_cap']:.1f}")
                    c3.metric("动态PE", f"{quote['pe']}")
                    c4.metric("换手率", f"{quote['turnover']:.2f}%")
                    if df_kline is not None and len(df_kline) >= 15:
                        df_kline = add_indicators(df_kline)
                        tech = summarize_technicals(df_kline)
                        smc = tech["smc"]
                        fig = build_price_figure(df_kline)
                        st.plotly_chart(fig, width="stretch")
                        t1, t2, t3, t4 = st.columns(4)
                        t1.metric("趋势", tech["trend"])
                        t2.metric("RSI14", f"{tech['rsi14']:.2f}" if pd.notna(tech["rsi14"]) else "N/A")
                        t3.metric("ATR14", f"{tech['atr14']:.2f}" if pd.notna(tech["atr14"]) else "N/A")
                        t4.metric("MACD状态", tech["macd_state"])
                        s1, s2, s3 = st.columns(3)
                        eqh_count = len(smc["eqh"]) if smc["eqh"] else 0
                        eql_count = len(smc["eql"]) if smc["eql"] else 0
                        pd_zone = smc["pd_zone"]["zone"] if smc["pd_zone"] else "N/A"
                        s1.metric("MSS", smc["mss"])
                        s2.metric("EQH / EQL", f"{eqh_count} / {eql_count}")
                        s3.metric("P/D Zone", pd_zone)
                    else:
                        st.warning("日线样本不足，已跳过日线增强技术图。")
                    st.markdown("##### ⏱️ 多周期技术分析（新增）")
                    m1, m2, m3 = st.columns(3)
                    for box, key, title in [(m1, "15m", "15分钟级别"), (m2, "60m", "60分钟级别"), (m3, "120m", "120分钟级别")]:
                        tf = mtf[key]
                        with box:
                            st.markdown(f"**{title}**")
                            st.metric("偏向", tf["bias"])
                            st.metric("趋势", tf["trend"])
                            st.metric("MACD", tf["macd_state"])
                            if tf["rsi"] is not None:
                                st.metric("RSI", f"{tf['rsi']:.2f}")
                            if tf["support"] is not None:
                                st.caption(f"支撑: {tf['support']:.2f}")
                            if tf["pressure"] is not None:
                                st.caption(f"压力: {tf['pressure']:.2f}")
                    st.markdown("##### 🧠 多周期综合结论（新增）")
                    st.info(f"综合结论：**{mtf['final_view']}**")

with tab2:
    with st.container(border=True):
        st.markdown("#### 📊 全盘系统级推演")
        st.write("结合全局宏观看板与近期市场结构，进行大局观研判。")
        if st.button("运行大盘沙盘推演", type="primary"):
            if not api_key:
                st.error("配置缺失: GROQ_API_KEY")
            else:
                prompt = f"""
你现在是高盛首席宏观策略师。请基于当前 A 股与外汇的精准数据进行大局观推演：

实时数据：{str(pulse_data)}

请输出：
1. 市场全景定调（分化还是普涨）
2. 北向资金意愿推断（基于汇率）
3. 短期沙盘推演方向
"""
                st.markdown(call_ai(prompt, temperature=0.4))

with tab3:
    with st.container(border=True):
        st.markdown("#### 🔥 当日主力资金狂欢地 (附实战标的推荐)")
        st.write("追踪全天涨幅最猛的行业板块，揪出领涨龙头，识别主线题材，并生成配置标的清单。")
        if st.button("扫描板块与生成配置推荐", type="primary"):
            blocks = get_hot_blocks()
            if blocks:
                df_blocks = pd.DataFrame(blocks)
                st.dataframe(df_blocks, width="stretch", hide_index=True)
            else:
                st.error("获取板块数据失败。")

with tab4:
    st.markdown("#### 📡 机构级事件图谱与智能评级矩阵")
    st.write("追踪彭博、推特、美联储、特朗普等宏观变量。")
    if st.button("🚨 截获并解析全球突发", type="primary"):
        global_news = get_global_news()
        if not global_news:
            st.warning("当前信号静默或被防火墙拦截。")
        else:
            st.text("\n".join(global_news))