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
    initial_sidebar_state="expanded",
)

st.markdown(
    """
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
.small-note {
    color: #6b7280;
    font-size: 0.85rem;
}
</style>
""",
    unsafe_allow_html=True,
)

st.title("🏦 AI 智能量化投研终端")
st.markdown(
    f"<div class='terminal-header'>TERMINAL BUILD v6.5.0 | SYS_TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | ENHANCED ANALYTICS SUITE</div>",
    unsafe_allow_html=True,
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
        help="手动指定底层计算模型，精准控制分析逻辑",
    )

    st.markdown("### 🎛️ 策略参数微调")
    with st.expander("自定义均线周期", expanded=False):
        ema_short = st.number_input("短期 EMA", min_value=5, max_value=50, value=20, step=1)
        ema_mid = st.number_input("中期 EMA", min_value=10, max_value=120, value=60, step=1)
        ema_long = st.number_input("长期 EMA", min_value=20, max_value=250, value=120, step=1)

    with st.expander("风险控制参数", expanded=False):
        stop_atr_mult = st.slider("止损 ATR 倍数", 0.5, 5.0, 1.5, 0.1)
        target_rr = st.slider("目标盈亏比", 1.0, 5.0, 2.0, 0.1)
        breakout_buffer = st.slider("突破确认缓冲(%)", 0.1, 3.0, 0.5, 0.1)

    ts_token = st.text_input("🔑 Tushare Token", type="password", help="仅作极致容灾兜底")
    DEBUG_MODE = st.checkbox("🛠️ 开启底层日志嗅探")

    st.markdown("---")
    st.markdown("### 📡 数据连通性")
    st.success("行情引流 : ACTIVE")
    st.success("7x24快讯 : ACTIVE")
    st.success("板块扫描 : ACTIVE")
    st.success("技术结构引擎 : ACTIVE")
    st.success("多周期分析 : ACTIVE (15m / 60m / 120m)")
    st.success("交易计划引擎 : ACTIVE")

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


# ================= 价格归一化 =================
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
    return min(candidates, key=lambda x: abs(x - raw_price))


# ================= 指标函数 =================
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
    df["pct_change"] = df["close"].pct_change() * 100
    df["ret_5d"] = df["close"].pct_change(5) * 100
    df["ret_20d"] = df["close"].pct_change(20) * 100
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
            zones.append({
                "type": "bullish",
                "start_idx": i - 2,
                "end_idx": i,
                "top": c3["low"],
                "bottom": c1["high"],
                "date": str(pd.to_datetime(c3["date"]).date()),
            })
        if c3["high"] < c1["low"]:
            zones.append({
                "type": "bearish",
                "start_idx": i - 2,
                "end_idx": i,
                "top": c1["low"],
                "bottom": c3["high"],
                "date": str(pd.to_datetime(c3["date"]).date()),
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
                "bottom": min(curr["open"], curr["close"]),
            })
        if curr["close"] > curr["open"] and nxt["close"] < curr["low"] and body_curr < atr * 1.2:
            zones.append({
                "type": "bearish_ob",
                "date": str(pd.to_datetime(curr["date"]).date()),
                "top": max(curr["open"], curr["close"]),
                "bottom": min(curr["open"], curr["close"]),
            })
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
    return {
        "range_high": range_high,
        "range_low": range_low,
        "equilibrium": eq,
        "zone": zone,
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
        "pd_zone": pd_zone,
    }


def calc_relative_position(df: pd.DataFrame, lookback=60):
    recent = df.tail(lookback)
    if recent.empty:
        return None
    high = recent["high"].max()
    low = recent["low"].min()
    close = recent.iloc[-1]["close"]
    if high == low:
        return None
    return (close - low) / (high - low) * 100


def calc_trend_score(df: pd.DataFrame):
    latest = df.iloc[-1]
    score = 0
    if latest["close"] > latest["ema_short"]:
        score += 1
    if latest["ema_short"] > latest["ema_mid"]:
        score += 1
    if latest["ema_mid"] > latest["ema_long"]:
        score += 1
    if pd.notna(latest["rsi14"]) and latest["rsi14"] > 55:
        score += 1
    if latest["macd"] > latest["macd_signal"]:
        score += 1
    return score


def calc_risk_score(df: pd.DataFrame):
    latest = df.iloc[-1]
    score = 0
    if pd.notna(latest["rsi14"]) and latest["rsi14"] >= 75:
        score += 2
    if latest["close"] > latest["bb_up"]:
        score += 1
    if pd.notna(latest["atr14"]) and latest["atr14"] > df["atr14"].tail(20).median():
        score += 1
    if latest["close"] < latest["ema_short"]:
        score += 1
    return score


def summarize_technicals(df: pd.DataFrame):
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else latest

    trend = "震荡"
    if latest["close"] > latest["ema_short"] > latest["ema_mid"]:
        trend = "多头趋势"
    elif latest["close"] < latest["ema_short"] < latest["ema_mid"]:
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
    vol_ratio = None
    if pd.notna(latest["vol_ma20"]) and latest["vol_ma20"] > 0:
        vol_ratio = latest["volume"] / latest["vol_ma20"]
        if vol_ratio > 1.8:
            vol_state = "显著放量"
        elif vol_ratio < 0.7:
            vol_state = "明显缩量"

    fvg_zones = detect_fvg(df)
    bos_state = detect_bos(df)
    sweep_state = detect_liquidity_sweep(df)
    nearest_bull_fvg = next((z for z in reversed(fvg_zones) if z["type"] == "bullish"), None)
    nearest_bear_fvg = next((z for z in reversed(fvg_zones) if z["type"] == "bearish"), None)

    smc = build_smc_summary(df)
    relative_position = calc_relative_position(df)
    trend_score = calc_trend_score(df)
    risk_score = calc_risk_score(df)

    return {
        "trend": trend,
        "momentum": momentum,
        "macd_state": macd_state,
        "bb_state": bb_state,
        "vol_state": vol_state,
        "vol_ratio": vol_ratio,
        "atr14": latest["atr14"],
        "rsi14": latest["rsi14"],
        "bos_state": bos_state,
        "sweep_state": sweep_state,
        "nearest_bull_fvg": nearest_bull_fvg,
        "nearest_bear_fvg": nearest_bear_fvg,
        "latest_close": latest["close"],
        "ema_short": latest["ema_short"],
        "ema_mid": latest["ema_mid"],
        "ema_long": latest["ema_long"],
        "smc": smc,
        "relative_position": relative_position,
        "trend_score": trend_score,
        "risk_score": risk_score,
        "ret_5d": latest.get("ret_5d"),
        "ret_20d": latest.get("ret_20d"),
    }


def build_trade_plan(df: pd.DataFrame, tech: dict):
    latest = tech["latest_close"]
    atr = tech["atr14"] if pd.notna(tech["atr14"]) else 0
    support_zone = min(tech["ema_short"], tech["ema_mid"])
    pressure_zone = max(tech["ema_short"], tech["ema_mid"])

    aggressive_entry = max(support_zone, latest - 0.5 * atr) if atr else support_zone
    conservative_entry = support_zone
    stop_loss = aggressive_entry - atr * stop_atr_mult if atr else aggressive_entry * 0.97
    target_1 = aggressive_entry + (aggressive_entry - stop_loss) * target_rr
    breakout_trigger = pressure_zone * (1 + breakout_buffer / 100)

    return {
        "aggressive_entry": aggressive_entry,
        "conservative_entry": conservative_entry,
        "stop_loss": stop_loss,
        "target_1": target_1,
        "breakout_trigger": breakout_trigger,
        "support_zone": support_zone,
        "pressure_zone": pressure_zone,
    }


def make_signal_table(tech: dict, mtf: dict):
    rows = [
        ["日线趋势", tech["trend"]],
        ["动量状态", tech["momentum"]],
        ["MACD", tech["macd_state"]],
        ["量能", tech["vol_state"]],
        ["BOS", tech["bos_state"]],
        ["扫流动性", tech["sweep_state"]],
        ["15m", mtf["15m"]["bias"]],
        ["60m", mtf["60m"]["bias"]],
        ["120m", mtf["120m"]["bias"]],
        ["多周期综合", mtf["final_view"]],
    ]
    return pd.DataFrame(rows, columns=["维度", "结论"])


def build_price_figure(df: pd.DataFrame):
    plot_df = df.copy()
    plot_df["date_str"] = plot_df["date"].dt.strftime("%Y-%m-%d")

    fig = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.50, 0.16, 0.17, 0.17],
        subplot_titles=("K线与结构", "成交量", "MACD", "RSI"),
    )

    fig.add_trace(go.Candlestick(
        x=plot_df["date_str"], open=plot_df["open"], high=plot_df["high"], low=plot_df["low"], close=plot_df["close"], name="K线"
    ), row=1, col=1)

    fig.add_trace(go.Scatter(x=plot_df["date_str"], y=plot_df["ema_short"], mode="lines", name=f"EMA{ema_short}", line=dict(width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=plot_df["date_str"], y=plot_df["ema_mid"], mode="lines", name=f"EMA{ema_mid}", line=dict(width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=plot_df["date_str"], y=plot_df["ema_long"], mode="lines", name=f"EMA{ema_long}", line=dict(width=1)), row=1, col=1)

    colors = ["red" if row["open"] >= row["close"] else "green" for _, row in plot_df.iterrows()]
    fig.add_trace(go.Bar(x=plot_df["date_str"], y=plot_df["volume"], marker_color=colors, name="成交量"), row=2, col=1)

    hist_colors = ["red" if x < 0 else "green" for x in plot_df["macd_hist"].fillna(0)]
    fig.add_trace(go.Bar(x=plot_df["date_str"], y=plot_df["macd_hist"], marker_color=hist_colors, name="MACD柱"), row=3, col=1)
    fig.add_trace(go.Scatter(x=plot_df["date_str"], y=plot_df["macd"], mode="lines", name="MACD"), row=3, col=1)
    fig.add_trace(go.Scatter(x=plot_df["date_str"], y=plot_df["macd_signal"], mode="lines", name="Signal"), row=3, col=1)

    fig.add_trace(go.Scatter(x=plot_df["date_str"], y=plot_df["rsi14"], mode="lines", name="RSI14"), row=4, col=1)
    fig.add_hline(y=70, line_dash="dash", row=4, col=1)
    fig.add_hline(y=30, line_dash="dash", row=4, col=1)

    for zone in detect_fvg(plot_df, max_zones=4):
        start_idx = zone["start_idx"]
        end_idx = min(len(plot_df) - 1, start_idx + 12)
        x0 = plot_df.iloc[start_idx]["date_str"]
        x1 = plot_df.iloc[end_idx]["date_str"]
        fillcolor = "rgba(0, 200, 0, 0.15)" if zone["type"] == "bullish" else "rgba(200, 0, 0, 0.15)"
        fig.add_shape(type="rect", x0=x0, x1=x1, y0=zone["bottom"], y1=zone["top"], line=dict(width=0), fillcolor=fillcolor, row=1, col=1)

    fig.update_layout(height=900, xaxis_rangeslider_visible=False, margin=dict(l=20, r=20, t=40, b=20), legend_title="图层")
    return fig


# ================= 多周期数据与分析 =================
@st.cache_data(ttl=120)
def get_intraday_15m(symbol, max_rows=320):
    try:
        df = ak.stock_zh_a_hist_min_em(symbol=str(symbol), period="15", adjust="")
        df = normalize_min_df(df)
        if df is not None and not df.empty:
            return df.tail(max_rows).reset_index(drop=True)
    except Exception as e:
        if DEBUG_MODE:
            st.warning(f"15分钟数据获取失败: {e}")
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
        return {
            "label": label,
            "status": "无数据",
            "trend": "N/A",
            "rsi": None,
            "macd_state": "N/A",
            "support": None,
            "pressure": None,
            "close": None,
            "bias": "无法判断",
        }

    df = df.copy()
    if len(df) < 12:
        latest = df.iloc[-1]
        support = df["low"].min()
        pressure = df["high"].max()
        return {
            "label": label,
            "status": "样本较少",
            "trend": "简化观察",
            "rsi": None,
            "macd_state": "N/A",
            "support": support,
            "pressure": pressure,
            "close": latest["close"],
            "bias": "轻量判断",
        }

    df = add_indicators(df)
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest
    trend = "震荡"
    if pd.notna(latest["ema_short"]) and latest["close"] > latest["ema_short"] > latest["ema_mid"]:
        trend = "多头"
    elif pd.notna(latest["ema_short"]) and latest["close"] < latest["ema_short"] < latest["ema_mid"]:
        trend = "空头"
    elif pd.notna(latest["ema_short"]) and latest["close"] > latest["ema_short"]:
        trend = "偏强"

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
        "bias": bias,
    }


def get_multi_timeframe_analysis(symbol: str):
    df15 = get_intraday_15m(symbol)
    df60 = aggregate_minutes(df15, 4) if df15 is not None else None
    df120 = aggregate_minutes(df15, 8) if df15 is not None else None

    tf15 = summarize_intraday_tf(df15, "15分钟")
    tf60 = summarize_intraday_tf(df60, "60分钟")
    tf120 = summarize_intraday_tf(df120, "120分钟")

    score = 0
    mapping = {"多头占优": 2, "轻量判断": 0, "震荡分歧": 0, "空头占优": -2}
    score += mapping.get(tf15["bias"], 0)
    score += mapping.get(tf60["bias"], 0)
    score += mapping.get(tf120["bias"], 0)

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
        "final_view": final_view,
    }


# ================= AI =================
def call_ai(prompt, model=None, temperature=0.3):
    try:
        exec_model = model if model else selected_model
        client = Groq(api_key=api_key)
        completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=exec_model,
            temperature=temperature,
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"❌ AI 计算节点故障: {e}"


def build_report_text(name, symbol, quote, tech, mtf, plan):
    lines = [
        f"{name}({symbol}) 分析摘要",
        f"现价: {quote['price']:.2f}  涨跌幅: {quote['pct']:.2f}%",
        f"总市值: {quote['market_cap']:.1f}亿  动态PE: {quote['pe']}  换手率: {quote['turnover']:.2f}%",
        f"趋势: {tech['trend']}  动量: {tech['momentum']}  MACD: {tech['macd_state']}",
        f"量能: {tech['vol_state']}  RSI14: {tech['rsi14']:.2f if pd.notna(tech['rsi14']) else 'N/A'}",
        f"多周期: 15m={mtf['15m']['bias']} / 60m={mtf['60m']['bias']} / 120m={mtf['120m']['bias']}",
        f"综合: {mtf['final_view']}",
        f"激进介入: {plan['aggressive_entry']:.2f}",
        f"稳健介入: {plan['conservative_entry']:.2f}",
        f"止损: {plan['stop_loss']:.2f}",
        f"第一目标: {plan['target_1']:.2f}",
        f"突破触发: {plan['breakout_trigger']:.2f}",
    ]
    return "\n".join(lines)


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


# ================= Tabs =================
tab1, tab2, tab3, tab4 = st.tabs([
    "🎯 I. 个股标的解析",
    "📈 II. 宏观大盘推演",
    "🔥 III. 资金热点板块",
    "🦅 IV. 高阶情报终端",
])


# ================= Tab 1 =================
with tab1:
    with st.container(border=True):
        st.markdown("#### 🔎 个股雷达锁定（增强版）")
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
                    c3.metric("动态 PE", f"{quote['pe']}")
                    c4.metric("换手率", f"{quote['turnover']:.2f}%")

                    if df_kline is None or len(df_kline) < 30:
                        st.warning("日线 K 线样本偏少，仅提供轻量分析。")
                    else:
                        df_kline = add_indicators(df_kline)
                        tech = summarize_technicals(df_kline)
                        plan = build_trade_plan(df_kline, tech)

                        fig = build_price_figure(df_kline)
                        st.plotly_chart(fig, width="stretch")

                        k1, k2, k3, k4 = st.columns(4)
                        k1.metric("趋势评分", f"{tech['trend_score']}/5")
                        k2.metric("风险评分", f"{tech['risk_score']}/5")
                        k3.metric("区间位置", f"{tech['relative_position']:.1f}%" if tech['relative_position'] is not None else "N/A")
                        k4.metric("量比(近20日)", f"{tech['vol_ratio']:.2f}" if tech['vol_ratio'] is not None else "N/A")

                        t1, t2, t3, t4 = st.columns(4)
                        t1.metric("趋势", tech["trend"])
                        t2.metric("RSI14", f"{tech['rsi14']:.2f}" if pd.notna(tech["rsi14"]) else "N/A")
                        t3.metric("ATR14", f"{tech['atr14']:.2f}" if pd.notna(tech["atr14"]) else "N/A")
                        t4.metric("MACD 状态", tech["macd_state"])

                        t5, t6, t7, t8 = st.columns(4)
                        t5.metric("布林状态", tech["bb_state"])
                        t6.metric("量能状态", tech["vol_state"])
                        t7.metric("BOS", tech["bos_state"])
                        t8.metric("扫流动性", tech["sweep_state"])

                        st.markdown("##### 📍 关键价位与计划")
                        p1, p2, p3, p4, p5 = st.columns(5)
                        p1.metric("激进介入", f"{plan['aggressive_entry']:.2f}")
                        p2.metric("稳健介入", f"{plan['conservative_entry']:.2f}")
                        p3.metric("止损", f"{plan['stop_loss']:.2f}")
                        p4.metric("第一目标", f"{plan['target_1']:.2f}")
                        p5.metric("突破触发", f"{plan['breakout_trigger']:.2f}")

                        st.markdown("##### 🧩 信号总表")
                        st.dataframe(make_signal_table(tech, mtf), width="stretch", hide_index=True)

                        st.markdown("##### ⏱️ 多周期技术分析")
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

                        st.markdown("##### 🧠 多周期综合结论")
                        st.info(f"综合结论：**{mtf['final_view']}**")

                        report_text = build_report_text(name, symbol_input, quote, tech, mtf, plan)
                        st.download_button(
                            "📥 下载分析摘要(txt)",
                            data=report_text.encode("utf-8"),
                            file_name=f"{symbol_input}_analysis_report.txt",
                            mime="text/plain",
                        )

                        with st.spinner(f"🧠 首席策略官正在使用 {selected_model} 深度解构..."):
                            prompt = f"""
你现在是顶级私募基金的操盘手（精通基本面、量价资金博弈、多周期共振）。

请对股票 {name}({symbol_input}) 做一份极具实战价值的【估值 + 资金流 + 支撑/压力 + 精准买卖点 + 多周期共振】综合研判。

【基础与资金博弈数据】
- 现价: {price} (日涨跌幅: {pct}%)
- 总市值: {quote['market_cap']} 亿 | 动态 PE: {quote['pe']} | 市净率 PB: {quote['pb']}
- 当日换手率: {quote['turnover']}%

【核心日线技术与结构数据】
- 趋势状态: {tech['trend']} | 动量: {tech['momentum']} | RSI14: {tech['rsi14']}
- 最新收盘: {tech['latest_close']}
- EMA{ema_short}/{ema_mid}/{ema_long}: {tech['ema_short']} / {tech['ema_mid']} / {tech['ema_long']}
- MACD: {tech['macd_state']} | 布林: {tech['bb_state']} | 量能: {tech['vol_state']}
- 结构特征: BOS({tech['bos_state']}), MSS({tech['smc']['mss']})
- 异常流动性: {tech['sweep_state']}
- FVG: 多头{tech['nearest_bull_fvg']} / 空头{tech['nearest_bear_fvg']}
- 多头OB: {tech['smc']['latest_bull_ob']} / 空头OB: {tech['smc']['latest_bear_ob']}
- 趋势评分: {tech['trend_score']}/5 | 风险评分: {tech['risk_score']}/5 | 区间位置: {tech['relative_position']}

【多周期分析】
- 15分钟: {mtf['15m']}
- 60分钟: {mtf['60m']}
- 120分钟: {mtf['120m']}
- 多周期综合结论: {mtf['final_view']}

【交易计划参数】
- 激进介入: {plan['aggressive_entry']}
- 稳健介入: {plan['conservative_entry']}
- 止损: {plan['stop_loss']}
- 第一目标: {plan['target_1']}
- 突破触发: {plan['breakout_trigger']}
- 使用止损 ATR 倍数: {stop_atr_mult}
- 使用目标盈亏比: {target_rr}

请输出：
1. 基本面与估值定位
2. 资金面穿透
3. 支撑与压力测算
4. 布局进入与离场推演（短期波段 / 中长期配置）
5. 多周期共振判断
6. 风险提示
7. 最后给一句明确结论：强势看多 / 偏多观察 / 震荡等待 / 谨慎偏空

要求：
- 语言专业、直接、机构化
- 不要空话
- 尽量像真正交易员盘前计划
"""
                            st.markdown(call_ai(prompt))


# ================= Tab 2 =================
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
4. 优先跟踪的市场风格（红利/成长/题材/周期）
"""
                    st.markdown(call_ai(prompt, temperature=0.4))


# ================= Tab 3 =================
with tab3:
    with st.container(border=True):
        st.markdown("#### 🔥 当日主力资金狂欢地 (附实战标的推荐)")
        st.write("追踪全天涨幅最猛的行业板块，揪出领涨龙头，识别主线题材，并生成配置标的清单。")

        if st.button("扫描板块与生成配置推荐", type="primary"):
            if not api_key:
                st.error("配置缺失: GROQ_API_KEY")
            else:
                blocks = get_hot_blocks()
                if blocks:
                    df_blocks = pd.DataFrame(blocks)
                    st.dataframe(df_blocks, width="stretch", hide_index=True)

                    with st.spinner("🧠 首席游资操盘手拆解逻辑并筛选跟进标的..."):
                        blocks_str = "\n".join([f"{b['板块名称']} (涨幅:{b['涨跌幅']}%, 领涨龙头:{b['领涨股票']})" for b in blocks[:5]])
                        prompt = f"""
作为顶级游资操盘手，请深度解读今日最强的 5 个板块及其领涨龙头：

{blocks_str}

请输出：
1. 核心驱动
2. 行情定性（主线 / 轮动 / 一日游）
3. 低位延展方向
4. 可重点跟踪的 2-3 只标的及原因
"""
                        st.markdown(call_ai(prompt, temperature=0.4))
                else:
                    st.error("获取板块数据失败。")


# ================= Tab 4 =================
with tab4:
    st.markdown("#### 📡 机构级事件图谱与智能评级矩阵")
    st.write("追踪宏观与全球市场快讯，并生成风控提示。")

    if st.button("🚨 截获并解析全球突发", type="primary"):
        if not api_key:
            st.error("配置缺失: GROQ_API_KEY")
        else:
            global_news = get_global_news()
            if not global_news:
                st.warning("当前信号静默或被防火墙拦截。")
            else:
                with st.expander("🕵️‍♂️ 查看底层监听流 (Raw Data)"):
                    st.text("\n".join(global_news))

                prompt = f"""
你现在是华尔街对冲基金的首席宏观情报官。
请从以下快讯中挑选最重要的 5-8 条，生成适合手机阅读的情报卡片。

底层情报：
{chr(10).join(global_news)}

要求：
- 不要使用表格
- 每条包括：时间、事件、受影响资产、推演、风控预警
- 最后补一段：今晚到明早 A 股最值得防的风险点
"""
                st.markdown(call_ai(prompt, temperature=0.2))