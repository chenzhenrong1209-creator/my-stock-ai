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


# ================= 页面与终端 UI 配置 =================
st.set_page_config(
    page_title="AI 智能投研终端 Pro Max",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    .stTabs [data-baseweb="tab-list"] {
        gap: 10px;
        flex-wrap: wrap;
    }
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
    f"<div class='terminal-header'>TERMINAL BUILD v6.3.1 | SYS_TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | MULTI-TF BUGFIX</div>",
    unsafe_allow_html=True
)

api_key = st.secrets.get("GROQ_API_KEY", "")


# ================= 侧边栏 =================
with st.sidebar:
    st.header("⚙️ 终端控制台")
    ts_token = st.text_input("🔑 Tushare Token", type="password", help="仅作极致容灾兜底")
    DEBUG_MODE = st.checkbox("🛠️ 开启底层日志嗅探")

    st.markdown("---")
    st.markdown("### 📡 数据连通性")
    st.success("行情引流 : ACTIVE")
    st.success("7x24快讯 : ACTIVE")
    st.success("板块扫描 : ACTIVE (带熔断保护)")
    st.success("技术结构引擎 : ACTIVE")
    st.success("多周期分析 : ACTIVE (15m / 60m / 120m)")

if ts_token:
    ts.set_token(ts_token)


# ================= 网络底座 =================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:115.0) Gecko/20100101 Firefox/115.0",
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
]


@st.cache_resource
def get_session():
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[403, 429, 500, 502, 503, 504],
    )
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


def fetch_json(url, timeout=5, extra_headers=None):
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    if extra_headers:
        headers.update(extra_headers)
    try:
        res = SESSION.get(url, headers=headers, timeout=timeout)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        if DEBUG_MODE:
            st.error(f"Feed Error: {e}")
        return None


# ================= 价格归一化修复 =================
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
        best = min(candidates, key=lambda x: abs(x - prev_close))
        return best

    if raw_price > 100000:
        return raw_price / 1000
    if raw_price > 10000:
        return raw_price / 100
    if raw_price > 1000:
        return raw_price / 10
    return raw_price


# ================= 技术面核心函数 =================
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
    swing_highs = []
    swing_lows = []
    if len(df) < left + right + 1:
        return swing_highs, swing_lows

    for i in range(left, len(df) - right):
        high = df["high"].iloc[i]
        low = df["low"].iloc[i]
        if high == df["high"].iloc[i-left: i+right+1].max():
            swing_highs.append((i, high))
        if low == df["low"].iloc[i-left: i+right+1].min():
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
            zones.append({
                "type": "bullish",
                "start_idx": i - 2,
                "end_idx": i,
                "top": c3["low"],
                "bottom": c1["high"],
                "date": str(pd.to_datetime(c3["date"]).date())
            })

        if c3["high"] < c1["low"]:
            zones.append({
                "type": "bearish",
                "start_idx": i - 2,
                "end_idx": i,
                "top": c1["low"],
                "bottom": c3["high"],
                "date": str(pd.to_datetime(c3["date"]).date())
            })
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
            zones.append({
                "type": "bullish_ob",
                "date": str(pd.to_datetime(curr["date"]).date()),
                "top": max(curr["open"], curr["close"]),
                "bottom": min(curr["open"], curr["close"])
            })

        if curr["close"] > curr["open"] and nxt["close"] < curr["low"] and body_curr < atr * 1.2:
            zones.append({
                "type": "bearish_ob",
                "date": str(pd.to_datetime(curr["date"]).date()),
                "top": max(curr["open"], curr["close"]),
                "bottom": min(curr["open"], curr["close"])
            })
    return zones[-max_zones:]


def detect_equal_high_low(df: pd.DataFrame, tolerance=0.003):
    swing_highs, swing_lows = detect_swings(df)
    eqh = []
    eql = []

    for i in range(len(swing_highs) - 1):
        h1 = swing_highs[i][1]
        h2 = swing_highs[i + 1][1]
        if h1 > 0 and abs(h1 - h2) / h1 <= tolerance:
            eqh.append((swing_highs[i], swing_highs[i + 1]))

    for i in range(len(swing_lows) - 1):
        l1 = swing_lows[i][1]
        l2 = swing_lows[i + 1][1]
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

    return {
        "range_high": range_high,
        "range_low": range_low,
        "equilibrium": eq,
        "zone": zone
    }


def build_smc_summary(df: pd.DataFrame):
    obs = detect_order_blocks(df)
    eqh, eql = detect_equal_high_low(df)
    mss = detect_mss(df)
    pd_zone = get_premium_discount_zone(df)

    latest_bull_ob = next((z for z in reversed(obs) if z["type"] == "bullish_ob"), None)
    latest_bear_ob = next((z for z in reversed(obs) if z["type"] == "bearish_ob"), None)

    return {
        "latest_bull_ob": latest_bull_ob,
        "latest_bear_ob": latest_bear_ob,
        "eqh": eqh,
        "eql": eql,
        "mss": mss,
        "pd_zone": pd_zone
    }


def summarize_technicals(df: pd.DataFrame):
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else latest

    trend = "震荡"
    if latest["close"] > latest["ema20"] > latest["ema60"]:
        trend = "多头趋势"
    elif latest["close"] < latest["ema20"] < latest["ema60"]:
        trend = "空头趋势"

    momentum = "中性"
    rsi = latest["rsi14"]
    if pd.notna(rsi):
        if rsi >= 70:
            momentum = "超买"
        elif rsi <= 30:
            momentum = "超卖"
        elif rsi > 55:
            momentum = "偏强"
        elif rsi < 45:
            momentum = "偏弱"

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
        "momentum": momentum,
        "macd_state": macd_state,
        "bb_state": bb_state,
        "vol_state": vol_state,
        "atr14": latest["atr14"],
        "rsi14": latest["rsi14"],
        "bos_state": bos_state,
        "sweep_state": sweep_state,
        "nearest_bull_fvg": nearest_bull_fvg,
        "nearest_bear_fvg": nearest_bear_fvg,
        "latest_close": latest["close"],
        "ema20": latest["ema20"],
        "ema60": latest["ema60"],
        "ema120": latest["ema120"],
        "smc": smc
    }


def build_price_figure(df: pd.DataFrame):
    plot_df = df.copy()
    plot_df["date_str"] = plot_df["date"].dt.strftime("%Y-%m-%d")

    fig = go.Figure()

    fig.add_trace(go.Candlestick(
        x=plot_df["date_str"],
        open=plot_df["open"],
        high=plot_df["high"],
        low=plot_df["low"],
        close=plot_df["close"],
        name="K线"
    ))

    fig.add_trace(go.Scatter(
        x=plot_df["date_str"], y=plot_df["ema20"],
        mode="lines", name="EMA20"
    ))
    fig.add_trace(go.Scatter(
        x=plot_df["date_str"], y=plot_df["ema60"],
        mode="lines", name="EMA60"
    ))
    fig.add_trace(go.Scatter(
        x=plot_df["date_str"], y=plot_df["ema120"],
        mode="lines", name="EMA120"
    ))

    for zone in detect_fvg(plot_df, max_zones=4):
        start_idx = zone["start_idx"]
        end_idx = min(len(plot_df) - 1, start_idx + 12)
        x0 = plot_df.iloc[start_idx]["date_str"]
        x1 = plot_df.iloc[end_idx]["date_str"]
        fillcolor = "rgba(0, 200, 0, 0.15)" if zone["type"] == "bullish" else "rgba(200, 0, 0, 0.15)"

        fig.add_shape(
            type="rect",
            x0=x0, x1=x1,
            y0=zone["bottom"], y1=zone["top"],
            line=dict(width=0),
            fillcolor=fillcolor
        )

    fig.update_layout(
        height=520,
        xaxis_title="日期",
        yaxis_title="价格",
        xaxis_rangeslider_visible=False,
        legend_title="图层",
        margin=dict(l=20, r=20, t=30, b=20)
    )
    return fig


# ================= 多周期分析修复版 =================
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


def fetch_em_minute_df(symbol: str, klt: int = 15, lmt: int = 800):
    market = "1" if str(symbol).startswith(("6", "9", "5", "7")) else "0"
    url = (
        f"https://push2his.eastmoney.com/api/qt/stock/kline/get?"
        f"secid={market}.{symbol}&ut=fa5fd1943c7b386f172d6893dbfba10b"
        f"&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58"
        f"&klt={klt}&fqt=1&end=20500101&lmt={lmt}"
    )
    res = fetch_json(url, timeout=8)
    if not res or not res.get("data") or not res["data"].get("klines"):
        return None

    rows = []
    for item in res["data"]["klines"]:
        parts = item.split(",")
        if len(parts) >= 6:
            rows.append({
                "date": parts[0],
                "open": parts[1],
                "close": parts[2],
                "high": parts[3],
                "low": parts[4],
                "volume": parts[5]
            })

    if not rows:
        return None

    df = pd.DataFrame(rows)
    return normalize_min_df(df)


@st.cache_data(ttl=120)
def get_intraday_15m(symbol, max_rows=320):
    # 1) AKShare 优先
    try:
        df = ak.stock_zh_a_hist_min_em(symbol=str(symbol), period="15", adjust="")
        df = normalize_min_df(df)
        if df is not None and not df.empty and len(df) >= 8:
            return df.tail(max_rows).reset_index(drop=True)
    except Exception as e:
        if DEBUG_MODE:
            st.warning(f"AKShare 15分钟数据失败，回退东财: {e}")

    # 2) 东方财富分钟K线兜底
    try:
        df = fetch_em_minute_df(symbol, klt=15, lmt=1000)
        if df is not None and not df.empty:
            return df.tail(max_rows).reset_index(drop=True)
    except Exception as e:
        if DEBUG_MODE:
            st.warning(f"东财 15分钟数据失败: {e}")

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
            "volume": g["volume"].sum()
        })
        all_parts.append(part)

    if not all_parts:
        return None

    out = pd.concat(all_parts, ignore_index=True)
    out = out.dropna().reset_index(drop=True)
    return out


def summarize_intraday_tf(df: pd.DataFrame, label: str):
    if df is None or df.empty:
        return {
            "label": label,
            "status": "无数据",
            "trend": "N/A",
            "rsi": None,
            "macd_state": "N/A",
            "support": None,
            "pressure": None,
            "close": None,
            "bias": "无法判断"
        }

    df = df.copy()

    # 样本很少时也给轻量判断，不直接 N/A
    if len(df) < 12:
        latest = df.iloc[-1]
        support = df["low"].min()
        pressure = df["high"].max()

        if len(df) >= 3:
            trend = "偏强" if latest["close"] > df["close"].iloc[0] else "偏弱"
        else:
            trend = "简化观察"

        bias = "轻量偏多" if latest["close"] > df["open"].mean() else "轻量偏空"

        return {
            "label": label,
            "status": "样本较少",
            "trend": trend,
            "rsi": None,
            "macd_state": "简化判断",
            "support": support,
            "pressure": pressure,
            "close": latest["close"],
            "bias": bias
        }

    df = add_indicators(df)
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest

    trend = "震荡"
    if pd.notna(latest["ema20"]) and latest["close"] > latest["ema20"]:
        trend = "偏强"
    if pd.notna(latest["ema20"]) and pd.notna(latest["ema60"]) and latest["close"] > latest["ema20"] > latest["ema60"]:
        trend = "多头"
    elif pd.notna(latest["ema20"]) and pd.notna(latest["ema60"]) and latest["close"] < latest["ema20"] < latest["ema60"]:
        trend = "空头"

    macd_state = "中性"
    if pd.notna(latest["macd"]) and pd.notna(latest["macd_signal"]):
        if latest["macd"] > latest["macd_signal"] and latest["macd_hist"] >= prev["macd_hist"]:
            macd_state = "偏多"
        elif latest["macd"] < latest["macd_signal"] and latest["macd_hist"] <= prev["macd_hist"]:
            macd_state = "偏空"

    support = df.tail(min(12, len(df)))["low"].min()
    pressure = df.tail(min(12, len(df)))["high"].max()

    bias_score = 0
    if trend in ["多头", "偏强"]:
        bias_score += 1
    if macd_state == "偏多":
        bias_score += 1
    if pd.notna(latest["rsi14"]) and latest["rsi14"] > 55:
        bias_score += 1
    if pd.notna(latest["rsi14"]) and latest["rsi14"] < 45:
        bias_score -= 1
    if macd_state == "偏空":
        bias_score -= 1
    if trend == "空头":
        bias_score -= 1

    if bias_score >= 2:
        bias = "多头占优"
    elif bias_score <= -2:
        bias = "空头占优"
    else:
        bias = "震荡分歧"

    return {
        "label": label,
        "status": "有效",
        "trend": trend,
        "rsi": latest["rsi14"] if pd.notna(latest["rsi14"]) else None,
        "macd_state": macd_state,
        "support": support,
        "pressure": pressure,
        "close": latest["close"],
        "bias": bias
    }


def get_multi_timeframe_analysis(symbol: str):
    df15 = get_intraday_15m(symbol)
    df60 = aggregate_minutes(df15, 4) if df15 is not None else None
    df120 = aggregate_minutes(df15, 8) if df15 is not None else None

    tf15 = summarize_intraday_tf(df15, "15分钟")
    tf60 = summarize_intraday_tf(df60, "60分钟")
    tf120 = summarize_intraday_tf(df120, "120分钟")

    score_map = {
        "多头占优": 2,
        "轻量偏多": 1,
        "震荡分歧": 0,
        "轻量偏空": -1,
        "空头占优": -2
    }

    score = 0
    score += score_map.get(tf15["bias"], 0)
    score += score_map.get(tf60["bias"], 0)
    score += score_map.get(tf120["bias"], 0)

    if score >= 3:
        final_view = "多周期共振偏多"
    elif score <= -3:
        final_view = "多周期共振偏空"
    else:
        final_view = "多周期分歧，偏观察"

    return {
        "15m": tf15,
        "60m": tf60,
        "120m": tf120,
        "final_view": final_view
    }


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
else:
    st.warning("宏观看板数据流建立失败。")

st.markdown("<br>", unsafe_allow_html=True)


# ================= 终端功能选项卡 =================
tab1, tab2, tab3, tab4 = st.tabs([
    "🎯 I. 个股标的解析",
    "📈 II. 宏观大盘推演",
    "🔥 III. 资金热点板块",
    "🦅 IV. 高阶情报终端"
])


# ================= Tab 1: 个股解析 =================
with tab1:
    with st.container(border=True):
        st.markdown("#### 🔎 个股雷达锁定（多维买卖点测算版）")

        col1, col2 = st.columns([1, 1])
        with col1:
            symbol_input = st.text_input("标的代码", placeholder="例：600519")
            analyze_btn = st.button("启动核心算法", type="primary", use_container_width=True)

        if analyze_btn:
            if not api_key:
                st.error("配置缺失: GROQ_API_KEY")
            elif len(symbol_input.strip()) != 6:
                st.warning("代码规范验证失败")
            else:
                with st.spinner("量子计算与数据提取中 (启用四重行情数据引擎)..."):
                    quote = get_stock_quote(symbol_input)
                    df_kline = get_kline(symbol_input, days=220)
                    mtf = get_multi_timeframe_analysis(symbol_input)

                if not quote:
                    st.error("无法捕获行情资产。")
                else:
                    st.markdown("---")
                    name, price, pct = quote["name"], quote["price"], quote["pct"]
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric(f"{name}", f"{price:.2f}", f"{pct:.2f}%")
                    c2.metric("总市值(亿)", f"{quote['market_cap']:.1f}")
                    c3.metric("动态PE", f"{quote['pe']}")
                    c4.metric("换手率", f"{quote['turnover']:.2f}%")

                    if df_kline is None or len(df_kline) < 15:
                        st.warning("获取到的有效 K 线极少，仅能通过最新行情进行轻量化推演。")
                        with st.spinner("🧠 首席策略官撰写资产评估报告..."):
                            prompt = f"""
作为顶级私募经理，请基于股票 {name}({symbol_input}) 当前状态：
现价 {price}，涨跌幅 {pct}%，市值 {quote['market_cap']} 亿，动态 PE {quote['pe']}，换手率 {quote['turnover']}%。

【请重点进行以下维度的分析】：
1. 🏦 基本面诊断与资金意图盲猜
2. ⚔️ 布局进入与离场推演：
   - 【短期波段】进入点与离场点建议
   - 【中长期配置】建仓点位与长线离场目标
3. 结论定调：[看多 / 观察 / 谨慎 / 偏空]
"""
                            st.markdown(call_ai(prompt))
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
                        t4.metric("MACD状态", tech["macd_state"])

                        t5, t6, t7, t8 = st.columns(4)
                        t5.metric("布林状态", tech["bb_state"])
                        t6.metric("量能状态", tech["vol_state"])
                        t7.metric("BOS", tech["bos_state"])
                        t8.metric("流动性扫盘", tech["sweep_state"])

                        st.markdown("##### 🧩 FVG / ICT / SMC 结构信息")
                        f1, f2 = st.columns(2)
                        with f1:
                            bull_fvg = tech["nearest_bull_fvg"]
                            if bull_fvg:
                                st.success(f"最近多头 FVG：{bull_fvg['date']} | 区间 {bull_fvg['bottom']:.2f} - {bull_fvg['top']:.2f}")
                            else:
                                st.info("最近未检测到明显多头 FVG")
                            if smc["latest_bull_ob"]:
                                st.success(f"最近多头 OB：{smc['latest_bull_ob']['date']} | 区间 {smc['latest_bull_ob']['bottom']:.2f} - {smc['latest_bull_ob']['top']:.2f}")
                            else:
                                st.info("最近未检测到明显多头 OB")

                        with f2:
                            bear_fvg = tech["nearest_bear_fvg"]
                            if bear_fvg:
                                st.error(f"最近空头 FVG：{bear_fvg['date']} | 区间 {bear_fvg['bottom']:.2f} - {bear_fvg['top']:.2f}")
                            else:
                                st.info("最近未检测到明显空头 FVG")
                            if smc["latest_bear_ob"]:
                                st.error(f"最近空头 OB：{smc['latest_bear_ob']['date']} | 区间 {smc['latest_bear_ob']['bottom']:.2f} - {smc['latest_bear_ob']['top']:.2f}")
                            else:
                                st.info("最近未检测到明显空头 OB")

                        st.markdown("##### 🏗️ 市场结构补充")
                        s1, s2, s3 = st.columns(3)
                        eqh_count = len(smc["eqh"]) if smc["eqh"] else 0
                        eql_count = len(smc["eql"]) if smc["eql"] else 0
                        pd_zone = smc["pd_zone"]["zone"] if smc["pd_zone"] else "N/A"
                        s1.metric("MSS", smc["mss"])
                        s2.metric("EQH / EQL", f"{eqh_count} / {eql_count}")
                        s3.metric("P/D Zone", pd_zone)

                        latest_close = tech["latest_close"]
                        support_zone = min(tech["ema20"], tech["ema60"])
                        pressure_zone = max(tech["ema20"], tech["ema60"])

                        st.markdown("##### 🎯 动态支撑 / 压力")
                        z1, z2, z3 = st.columns(3)
                        z1.metric("最新收盘", f"{latest_close:.2f}")
                        z2.metric("动态支撑参考", f"{support_zone:.2f}")
                        z3.metric("动态压力参考", f"{pressure_zone:.2f}")

                        with st.expander("📚 技术面模型说明"):
                            st.write("""
- EMA20/EMA60/EMA120：判断短中长期趋势
- RSI14：判断超买超卖与动量强弱
- MACD：判断动量拐点与趋势延续
- ATR14：判断波动率，辅助止损空间评估
- FVG (Fair Value Gap)：观察价格失衡区与回补机会
- BOS (Break of Structure)：判断结构是否有效突破
- Order Block：寻找潜在机构承接/抛压区域
- MSS (Market Structure Shift)：趋势结构切换信号
- EQH/EQL：识别流动性池
- Premium/Discount Zone：判断当前位置贵/便宜
- 流动性扫盘：识别假突破、诱多诱空
""")

                        with st.spinner("🧠 首席策略官进行多维深度解构(基本面+资金面+买卖点测算)..."):
                            ema60_val = f"{tech['ema60']:.2f}" if pd.notna(tech['ema60']) else "数据不足"
                            ema120_val = f"{tech['ema120']:.2f}" if pd.notna(tech['ema120']) else "数据不足"

                            prompt = f"""
你现在是顶级私募基金的操盘手（精通基本面与量价资金博弈）。

请对股票 {name}({symbol_input}) 做一份极具实战价值的【估值 + 资金流 + 支撑/压力 + 精准买卖点】综合研判。

【基础与资金博弈数据】
- 现价: {price} (日涨跌幅: {pct}%)
- 总市值: {quote['market_cap']} 亿 | 动态 PE: {quote['pe']} | 市净率 PB: {quote['pb']}
- 当日换手率: {quote['turnover']}%
- 近期量能状态: {tech['vol_state']}

【核心技术与结构数据】
- 趋势状态: {tech['trend']} | RSI14: {tech['rsi14']}
- 最新收盘: {tech['latest_close']}
- 短期生命线 (EMA20): {tech['ema20']}
- 中长期基准 (EMA60/120): {ema60_val} / {ema120_val}
- 结构特征: BOS({tech['bos_state']}), MSS({smc['mss']})
- 异常流动性: 扫盘({tech['sweep_state']})
- 核心磁区 (FVG/OB):
  近期多头 FVG: {tech['nearest_bull_fvg']}
  近期空头 FVG: {tech['nearest_bear_fvg']}

【请务必按以下维度输出，不要说正确的废话】：
1. 🏦 基本面与估值定位：结合市值与 PE/PB，判断当前估值是杀跌透支还是泡沫溢价
2. 🌊 资金面穿透：结合今日换手率、量能状态及近期结构，推演主力机构是在悄悄吸筹、接力洗盘，还是派发跑路
3. 🎯 支撑与压力测算：结合均线和空头/多头 FVG，给出具体的短线强支撑位和上行重压位
4. ⚔️ 布局进入与离场推演：
   - 【短期波段】进入点、离场点、止损位
   - 【中长期配置】建仓逻辑与离场目标
5. 结论定调：[看多 / 观察 / 谨慎 / 偏空]
"""
                            st.markdown(call_ai(prompt))

                    # ===== 新增：多周期分析 =====
                    st.markdown("##### ⏱️ 多周期技术分析（新增）")
                    m1, m2, m3 = st.columns(3)

                    with m1:
                        tf = mtf["15m"]
                        st.markdown("**15分钟级别**")
                        st.metric("偏向", tf["bias"])
                        st.metric("趋势", tf["trend"])
                        st.metric("MACD", tf["macd_state"])
                        if tf["rsi"] is not None:
                            st.metric("RSI", f"{tf['rsi']:.2f}")
                        if tf["support"] is not None:
                            st.caption(f"支撑: {tf['support']:.2f}")
                        if tf["pressure"] is not None:
                            st.caption(f"压力: {tf['pressure']:.2f}")

                    with m2:
                        tf = mtf["60m"]
                        st.markdown("**60分钟级别**")
                        st.metric("偏向", tf["bias"])
                        st.metric("趋势", tf["trend"])
                        st.metric("MACD", tf["macd_state"])
                        if tf["rsi"] is not None:
                            st.metric("RSI", f"{tf['rsi']:.2f}")
                        if tf["support"] is not None:
                            st.caption(f"支撑: {tf['support']:.2f}")
                        if tf["pressure"] is not None:
                            st.caption(f"压力: {tf['pressure']:.2f}")

                    with m3:
                        tf = mtf["120m"]
                        st.markdown("**120分钟级别**")
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

                    with st.spinner("🧠 多周期综合推演中..."):
                        prompt = f"""
你现在是职业交易员。
请基于以下多周期数据，对 {name}({symbol_input}) 做多周期综合判断。

【15分钟】
{mtf['15m']}

【60分钟】
{mtf['60m']}

【120分钟】
{mtf['120m']}

【综合结论预判】
{mtf['final_view']}

请输出：
1. 三个周期是否共振
2. 当前更适合追涨、低吸、等回踩还是观望
3. 短线应该看哪个级别信号为主
4. 最后给一句明确结论：强势看多 / 偏多观察 / 震荡等待 / 谨慎偏空
"""
                        st.markdown(call_ai(prompt))


# ================= Tab 2: 宏观大盘推演 =================
with tab2:
    with st.container(border=True):
        st.markdown("#### 📊 全盘系统级推演")
        st.write("结合全局宏观看板与近期市场结构，进行大局观研判。")

        if st.button("运行大盘沙盘推演", type="primary"):
            if not api_key:
                st.error("配置缺失: GROQ_API_KEY")
            else:
                with st.spinner("推演引擎初始化..."):
                    prompt = f"""
你现在是高盛首席宏观策略师。请基于当前 A 股与外汇的精准数据进行大局观推演：

实时数据：{str(pulse_data)}

请输出：
1. 市场全景定调（分化还是普涨）
2. 北向资金意愿推断（基于汇率）
3. 短期沙盘推演方向
"""
                    st.markdown(call_ai(prompt, temperature=0.4))


# ================= Tab 3: 热点资金板块 =================
with tab3:
    with st.container(border=True):
        st.markdown("#### 🔥 当日主力资金狂欢地 (附实战标的推荐)")
        st.write("追踪全天涨幅最猛的行业板块，揪出领涨龙头，识别主线题材，并生成配置标的清单。")

        if st.button("扫描板块与生成配置推荐", type="primary"):
            if not api_key:
                st.error("配置缺失: GROQ_API_KEY")
            else:
                with st.spinner("深潜获取东方财富板块异动数据... (若遇熔断将自动切换备用数据源)"):
                    blocks = get_hot_blocks()
                    if blocks:
                        df_blocks = pd.DataFrame(blocks)
                        st.dataframe(df_blocks, use_container_width=True, hide_index=True)

                        with st.spinner("🧠 首席游资操盘手拆解逻辑并筛选跟进标的..."):
                            blocks_str = "\n".join([f"{b['板块名称']} (涨幅:{b['涨跌幅']}%, 领涨龙头:{b['领涨股票']})" for b in blocks[:5]])

                            prompt = f"""
作为顶级游资操盘手，请深度解读今日最强的 5 个板块及其领涨龙头：

{blocks_str}

请输出：
1. 【核心驱动】这些板块背后的底层逻辑或共振政策利好是什么？
2. 【行情定性】这是存量博弈的一日游情绪宣泄，还是具备中线发酵潜力的主线？
3. 🎯 【个股配置与实战推荐】：
   基于上述板块逻辑和领涨股票，为散户推荐 2-3 只可以进行重点配置或埋伏的股票。
   对于推荐的每一只股票，请务必写明：
   - 股票名称与行业归属
   - 核心配置理由
   - 建议的入场姿势
"""
                            st.markdown(call_ai(prompt, temperature=0.4))
                    else:
                        st.error("获取板块数据失败，所有接口均处于熔断保护期。")


# ================= Tab 4: 高阶情报终端 =================
with tab4:
    st.markdown("#### 📡 机构级事件图谱与智能评级矩阵")
    st.write("追踪彭博、推特、美联储、特朗普等宏观变量。已深度适配移动端，引入极客量化风控模块。")

    if st.button("🚨 截获并解析全球突发", type="primary"):
        if not api_key:
            st.error("配置缺失: GROQ_API_KEY")
        else:
            with st.spinner("监听全网节点并执行深度 NLP 解析..."):
                global_news = get_global_news()
                if not global_news:
                    st.warning("当前信号静默或被防火墙拦截。")
                else:
                    news_text = "\n".join(global_news)

                    with st.expander("🕵️‍♂️ 查看底层监听流 (Raw Data)"):
                        st.text(news_text)

                    with st.spinner("🧠 情报官正在生成自适应移动端的情报卡片..."):
                        prompt = f"""
你现在是华尔街顶级对冲基金的【首席宏观情报官】与【高阶量化风控专家】。

我截获了全球金融市场的底层快讯流。请你挑选出最具爆炸性和市场影响力的 5-8 条动态。

重点寻猎靶标：彭博社 (Bloomberg)、推特 (X)、特朗普 (Trump)、马斯克 (Musk)、美联储，以及任何可能引发流动性危机或资金抱团退潮的事件。

⚠️【排版严令：禁止使用 Markdown 表格】⚠️
为了适配移动端设备的终端显示，你绝对不能使用表格！必须为每一个事件生成一个独立的情报卡片。

请【严格根据快讯内容重写】下面方括号里的内容，绝对不要原样保留占位符文本。

输出格式必须如下：
### [评级Emoji] [[信源/人物]] [用5-15个字高度概括真实发生的事件标题]
* ⏰ **时间截获**: [提取对应时间]
* 📝 **情报简述**: [用1-2句话清晰说明发生了什么]
* 🎯 **受波及资产**: [指出利好/利空资产]
* 🧠 **沙盘推演**: [一句话指出实质影响]
* ☢️ **风控预警**: [一个简短硬核预警]
---

评级标准：
🔴 核心：直接引发巨震的突发、大选级人物强硬表态、黑天鹅事件
🟡 重要：关键经济数据、行业重磅政策、流动性显著异动
🔵 一般：常规宏观事件

底层情报数据流：
{news_text}
"""
                        report = call_ai(prompt, temperature=0.2)
                        st.markdown("---")
                        st.markdown(report)