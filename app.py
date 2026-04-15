import streamlit as st
from groq import Groq
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import re
import akshare as ak
import tushare as ts
import random
from datetime import datetime
import plotly.graph_objects as go

# =================  页面与终端  UI  配置  =================
st.set_page_config(
    page_title="AI  智能投研终端  Pro Max",
    page_icon=" 🏦 ",
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

st.title(" 🏦  AI  智能量化投研终端 ")
st.markdown(
    f"<div class='terminal-header'>TERMINAL BUILD v5.4.1 | SYS_TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | MOBILE OPTIMIZED</div>",
    unsafe_allow_html=True
)

api_key = st.secrets.get("GROQ_API_KEY", "")

# =================  侧边栏  =================
with st.sidebar:
    st.header(" ⚙️   终端控制台 ")
    ts_token = st.text_input(" 🔑  Tushare Token", type="password", help=" 仅作极致容灾兜底 ")
    DEBUG_MODE = st.checkbox(" 🛠️   开启底层日志嗅探 ")
    
    st.markdown("---")
    st.markdown("###  📡  数据连通性 ")
    st.success(" 行情引流 : ACTIVE")
    st.success("7x24 快讯 : ACTIVE")
    st.success(" 板块扫描 : ACTIVE")
    st.success(" 技术结构引擎 : ACTIVE")

if ts_token:
    ts.set_token(ts_token)

# =================  网络底座  =================
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

# =================  技术面核心函数  =================
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # EMA
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema60"] = df["close"].ewm(span=60, adjust=False).mean()
    df["ema120"] = df["close"].ewm(span=120, adjust=False).mean()
    
    # MACD
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]
    
    # RSI14
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    df["rsi14"] = 100 - (100 / (1 + rs))
    
    # ATR14
    prev_close = df["close"].shift(1)
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - prev_close).abs()
    tr3 = (df["low"] - prev_close).abs()
    df["tr"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["atr14"] = df["tr"].rolling(14).mean()
    
    # Bollinger
    ma20 = df["close"].rolling(20).mean()
    std20 = df["close"].rolling(20).std()
    df["bb_mid"] = ma20
    df["bb_up"] = ma20 + 2 * std20
    df["bb_low"] = ma20 - 2 * std20
    
    # Volume MA
    df["vol_ma20"] = df["volume"].rolling(20).mean()
    return df

def detect_swings(df: pd.DataFrame, left=2, right=2):
    swing_highs = []
    swing_lows = []
    if len(df) < left + right + 1:
        return swing_highs, swing_lows
    for i in range(left, len(df) - right):
        high = df.loc[i, "high"]
        low = df.loc[i, "low"]
        if high == df.loc[i-left:i+right, "high"].max():
            swing_highs.append((i, high))
        if low == df.loc[i-left:i+right, "low"].min():
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
        return " 样本不足 "
    recent = df.tail(20).copy()
    latest = recent.iloc[-1]
    prev_high = recent.iloc[:-1]["high"].max()
    prev_low = recent.iloc[:-1]["low"].min()
    
    if latest["high"] > prev_high and latest["close"] < prev_high:
        return " 向上扫流动性后回落 "
    if latest["low"] < prev_low and latest["close"] > prev_low:
        return " 向下扫流动性后收回 "
    return " 未见明显扫流动性 "

def detect_bos(df: pd.DataFrame):
    swing_highs, swing_lows = detect_swings(df)
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return " 结构样本不足 "
    
    latest_close = df.iloc[-1]["close"]
    last_swing_high = swing_highs[-1][1]
    last_swing_low = swing_lows[-1][1]
    
    if latest_close > last_swing_high:
        return " 向上 BOS（结构突破） "
    if latest_close < last_swing_low:
        return " 向下 BOS（结构破坏） "
    return " 结构未突破 "

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
        return " 样本不足 "
        
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    last_high = swing_highs[-1][1]
    last_low = swing_lows[-1][1]
    
    if prev["close"] < last_high and latest["close"] > last_high:
        return "Bullish MSS （多头结构转换） "
    if prev["close"] > last_low and latest["close"] < last_low:
        return "Bearish MSS （空头结构转换） "
    return " 暂无明显 MSS "

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
    
    trend = " 震荡 "
    if latest["close"] > latest["ema20"] > latest["ema60"]:
        trend = " 多头趋势 "
    elif latest["close"] < latest["ema20"] < latest["ema60"]:
        trend = " 空头趋势 "
        
    momentum = " 中性 "
    rsi = latest["rsi14"]
    if pd.notna(rsi):
        if rsi >= 70:
            momentum = " 超买 "
        elif rsi <= 30:
            momentum = " 超卖 "
        elif rsi > 55:
            momentum = " 偏强 "
        elif rsi < 45:
            momentum = " 偏弱 "
            
    macd_state = " 中性 "
    if latest["macd"] > latest["macd_signal"] and latest["macd_hist"] > prev["macd_hist"]:
        macd_state = " 金叉后增强 "
    elif latest["macd"] < latest["macd_signal"] and latest["macd_hist"] < prev["macd_hist"]:
        macd_state = " 死叉后走弱 "
        
    bb_state = " 带内运行 "
    if latest["close"] > latest["bb_up"]:
        bb_state = " 突破布林上轨 "
    elif latest["close"] < latest["bb_low"]:
        bb_state = " 跌破布林下轨 "
        
    vol_state = " 量能平稳 "
    if pd.notna(latest["vol_ma20"]) and latest["vol_ma20"] > 0:
        if latest["volume"] > latest["vol_ma20"] * 1.8:
            vol_state = " 显著放量 "
        elif latest["volume"] < latest["vol_ma20"] * 0.7:
            vol_state = " 明显缩量 "
            
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
        name="K 线 "
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
        xaxis_title=" 日期 ",
        yaxis_title=" 价格 ",
        xaxis_rangeslider_visible=False,
        legend_title=" 图层 ",
        margin=dict(l=20, r=20, t=30, b=20)
    )
    return fig

# =================  核心数据流  =================
@st.cache_data(ttl=60)
def get_global_news():
    url = "https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size=60&zhibo_id=152&tag_id=0&dire=f&dpc=1"
    res = fetch_json(url, extra_headers={"Referer": "https://finance.sina.com.cn/"})
    news = []
    if res and res.get("result", {}).get("data", {}).get("feed", {}).get("list"):
        for item in res["result"]["data"]["feed"]["list"]:
            text = re.sub(r'<[^>]+>', '', str(item.get("rich_text", "")).strip())
            if len(text) > 15:
                news.append(f"[{item.get('create_time', '')}] {text}")
    return news

@st.cache_data(ttl=60)
def get_market_pulse():
    pulse = {}
    indices = {" 上证指数 ": "1.000001", " 深证成指 ": "0.399001", " 创业板指 ": "0.399006"}
    for name, code in indices.items():
        url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={code}&ut=fa5fd1943c7b386f172d6893dbfba10b&fltt=2&fields=f43,f170"
        res = fetch_json(url)
        if res and res.get("data"):
            pulse[name] = {"price": safe_float(res["data"].get("f43")), "pct": safe_float(res["data"].get("f170"))}
            
    cnh_url = "https://push2.eastmoney.com/api/qt/stock/get?secid=133.USDCNH&ut=fa5fd1943c7b386f172d6893dbfba10b&fltt=2&fields=f43,f170"
    cnh_res = fetch_json(cnh_url)
    if cnh_res and cnh_res.get("data"):
        pulse["USD/CNH( 离岸 )"] = {"price": safe_float(cnh_res["data"].get("f43")), "pct": safe_float(cnh_res["data"].get("f170"))}
    return pulse

@st.cache_data(ttl=300)
def get_hot_blocks():
    try:
        df = ak.stock_board_industry_name_em()
        if df is not None and not df.empty:
            top_blocks = df.sort_values(by=" 涨跌幅 ", ascending=False).head(10)
            return top_blocks[[" 板块名称 ", " 涨跌幅 ", " 上涨家数 ", " 下跌家数 ", " 领涨股票 "]].to_dict('records')
    except Exception:
        pass
    return None

def get_stock_quote(symbol):
    market = "1" if str(symbol).startswith(("6", "9", "5", "7")) else "0"
    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={market}.{symbol}&ut=fa5fd1943c7b386f172d6893dbfba10b&fltt=2&fields=f58,f43,f170,f116,f162,f168,f167"
    res = fetch_json(url)
    if res and res.get("data"):
        d = res["data"]
        raw_price = safe_float(d.get("f43"))
        price = raw_price / 1000 if raw_price > 1000 else raw_price
        return {
            "name": d.get("f58", " 未知 "),
            "price": price,
            "pct": safe_float(d.get("f170")),
            "market_cap": safe_float(d.get("f116")) / 100000000,
            "pe": d.get("f162", "-"),
            "pb": d.get("f167", "-"),
            "turnover": safe_float(d.get("f168"))
        }
    return None

def get_kline(symbol, days=220):
    # 1) AKShare 前复权
    try:
        df = ak.stock_zh_a_hist(symbol=str(symbol), period="daily", adjust="qfq")
        if df is not None and not df.empty:
            df = df.rename(columns={
                " 日期 ": "date", " 开盘 ": "open", " 收盘 ": "close",
                " 最高 ": "high", " 最低 ": "low", " 成交量 ": "volume",
                " 成交额 ": "amount", " 换手率 ": "turnover_rate"
            })
            keep_cols = ["date", "open", "high", "low", "close", "volume"]
            if all(col in df.columns for col in keep_cols):
                df = df[keep_cols].copy()
                df["date"] = pd.to_datetime(df["date"])
                for col in ["open", "high", "low", "close", "volume"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                df = df.dropna().reset_index(drop=True)
                if len(df) > 0:
                    return df.tail(days)
    except Exception as e:
        if DEBUG_MODE:
            st.warning(f"AKShare qfq K 线失败 : {e}")
            
    # 2) AKShare 不复权
    try:
        df = ak.stock_zh_a_hist(symbol=str(symbol), period="daily", adjust="")
        if df is not None and not df.empty:
            df = df.rename(columns={
                " 日期 ": "date", " 开盘 ": "open", " 收盘 ": "close",
                " 最高 ": "high", " 最低 ": "low", " 成交量 ": "volume",
                " 成交额 ": "amount", " 换手率 ": "turnover_rate"
            })
            keep_cols = ["date", "open", "high", "low", "close", "volume"]
            if all(col in df.columns for col in keep_cols):
                df = df[keep_cols].copy()
                df["date"] = pd.to_datetime(df["date"])
                for col in ["open", "high", "low", "close", "volume"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                df = df.dropna().reset_index(drop=True)
                if len(df) > 0:
                    return df.tail(days)
    except Exception as e:
        if DEBUG_MODE:
            st.warning(f"AKShare raw K 线失败 : {e}")
            
    # 3) Tushare 兜底
    try:
        if ts_token:
            pro = ts.pro_api()
            market = ".SH" if str(symbol).startswith(("6", "9", "5", "7")) else ".SZ"
            ts_code = f"{symbol}{market}"
            df = pro.daily(ts_code=ts_code)
            if df is not None and not df.empty:
                df = df.rename(columns={
                    "trade_date": "date", "open": "open", "high": "high",
                    "low": "low", "close": "close", "vol": "volume"
                })
                keep_cols = ["date", "open", "high", "low", "close", "volume"]
                if all(col in df.columns for col in keep_cols):
                    df = df[keep_cols].copy()
                    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
                    for col in ["open", "high", "low", "close", "volume"]:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                    df = df.dropna().sort_values("date").reset_index(drop=True)
                    if len(df) > 0:
                        return df.tail(days)
    except Exception as e:
        if DEBUG_MODE:
            st.warning(f"Tushare K 线失败 : {e}")
    return None

# ================= AI  计算核心  =================
def call_ai(prompt, model="llama-3.3-70b-versatile", temperature=0.3):
    try:
        client = Groq(api_key=api_key)
        completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            temperature=temperature
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f" ❌  AI  计算节点故障 : {e}"

# =================  终端全局看板  =================
st.markdown("###  🌍  宏观市场实时看板 ")
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
    st.warning(" 宏观看板数据流建立失败。 ")
st.markdown("<br>", unsafe_allow_html=True)

# =================  终端功能选项卡  =================
tab1, tab2, tab3, tab4 = st.tabs([
    " 🎯  I.  个股标的解析 ",
    " 📈  II. 宏观大盘推演 ",
    " 🔥  III.  资金热点板块 ",
    " 🦅  IV. 高阶情报终端 "
])

# ================= Tab 1:  个股解析  =================
with tab1:
    with st.container(border=True):
        st.markdown("####  🔎  个股雷达锁定（增强技术结构版） ")
        col1, col2 = st.columns([1, 1])
        with col1:
            symbol_input = st.text_input(" 标的代码 ", placeholder=" 例： 600519")
            analyze_btn = st.button(" 启动核心算法 ", type="primary", width="stretch")
        
        if analyze_btn:
            if not api_key:
                st.error(" 配置缺失 : GROQ_API_KEY")
            elif len(symbol_input.strip()) != 6:
                st.warning(" 代码规范验证失败 ")
            else:
                with st.spinner(" 量子计算与数据提取中 ..."):
                    quote = get_stock_quote(symbol_input)
                    df_kline = get_kline(symbol_input, days=220)
                
                if not quote:
                    st.error(" 无法捕获行情资产。 ")
                else:
                    st.markdown("---")
                    name, price, pct = quote["name"], quote["price"], quote["pct"]
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric(f"{name}", f"{price:.2f}", f"{pct:.2f}%")
                    c2.metric(" 总市值 ( 亿 )", f"{quote['market_cap']:.1f}")
                    c3.metric(" 动态 PE", f"{quote['pe']}")
                    c4.metric(" 换手率 ", f"{quote['turnover']:.2f}%")
                    
                    # =====  分层降级逻辑  =====
                    if df_kline is None or df_kline.empty:
                        st.warning(" 未获取到 K 线数据，仅展示基础行情分析。 ")
                        with st.spinner(" 🧠  首席策略官撰写基础资产评估报告 ..."):
                            prompt = f"""
作为顶级私募经理，请基于股票  {name}({symbol_input})  当前状态：
现价  {price} ，涨跌幅  {pct}% ，市值  {quote['market_cap']}  亿，动态 PE {quote['pe']} ，市净率 PB {quote['pb']} ，换手率  {quote['turnover']}% 。
请输出：
1.  基本面与估值诊断
2.  资金意图预判
3.  当前适合追涨、观察还是回避
4.  风险提示
要求：简洁、专业、像机构日报。
"""
                            st.markdown(call_ai(prompt))
                    
                    elif len(df_kline) < 20:
                        st.warning(f"K 线样本仅  {len(df_kline)}  根，无法运行完整增强分析，切换为简化技术分析。 ")
                        temp = df_kline.copy()
                        temp["date"] = temp["date"].dt.strftime("%Y-%m-%d")
                        st.line_chart(temp.set_index("date")["close"])
                        
                        latest_close = temp["close"].iloc[-1]
                        recent_high = temp["close"].max()
                        recent_low = temp["close"].min()
                        
                        c1, c2, c3 = st.columns(3)
                        c1.metric(" 最新收盘 ", f"{latest_close:.2f}")
                        c2.metric(" 近阶段高点 ", f"{recent_high:.2f}")
                        c3.metric(" 近阶段低点 ", f"{recent_low:.2f}")
                        
                        with st.spinner(" 🧠  首席策略官撰写简化技术报告 ..."):
                            prompt = f"""
你现在是顶级私募基金经理。
股票  {name}({symbol_input})  当前数据如下：
-  现价 : {price}
-  日涨跌幅 : {pct}%
-  总市值 : {quote['market_cap']}  亿
-  动态 PE: {quote['pe']}
-  市净率 PB: {quote['pb']}
-  换手率 : {quote['turnover']}%
- K 线样本数量 : {len(df_kline)}
-  近期最高收盘 : {recent_high}
-  近期最低收盘 : {recent_low}
-  最新收盘 : {latest_close}
请输出：
1.  当前所处的大致位置（相对高位  /  中位  /  低位）
2.  趋势判断
3.  短线风险与机会
4.  简化交易计划
5.  结论：看多  /  观察  /  谨慎
要求：简洁、专业、机构化。
"""
                            st.markdown(call_ai(prompt))
                    
                    else:
                        df_kline = add_indicators(df_kline)
                        tech = summarize_technicals(df_kline)
                        smc = tech["smc"]
                        fig = build_price_figure(df_kline)
                        st.plotly_chart(fig, width="stretch")
                        
                        st.markdown("#####  🔬  核心技术指标与阻力测算 ")
                        t1, t2, t3, t4 = st.columns(4)
                        t1.metric(" 趋势 ", tech["trend"])
                        t2.metric("RSI14", f"{tech['rsi14']:.2f}" if pd.notna(tech["rsi14"]) else "N/A")
                        t3.metric("ATR14", f"{tech['atr14']:.2f}" if pd.notna(tech["atr14"]) else "N/A")
                        t4.metric("MACD 状态 ", tech["macd_state"])
                        
                        t5, t6, t7, t8 = st.columns(4)
                        t5.metric(" 布林状态 ", tech["bb_state"])
                        t6.metric(" 量能状态 ", tech["vol_state"])
                        t7.metric("BOS", tech["bos_state"])
                        t8.metric(" 流动性扫盘 ", tech["sweep_state"])
                        
                        st.markdown("#####  🧩  FVG / ICT / SMC  结构信息 ")
                        f1, f2 = st.columns(2)
                        with f1:
                            bull_fvg = tech["nearest_bull_fvg"]
                            if bull_fvg:
                                st.success(f" 最近多头 FVG ： {bull_fvg['date']} |  区间  {bull_fvg['bottom']:.2f} - {bull_fvg['top']:.2f}")
                            else:
                                st.info(" 最近未检测到明显多头 FVG")
                                
                            if smc["latest_bull_ob"]:
                                st.success(f" 最近多头 OB ： {smc['latest_bull_ob']['date']} |  区间  {smc['latest_bull_ob']['bottom']:.2f} - {smc['latest_bull_ob']['top']:.2f}")
                            else:
                                st.info(" 最近未检测到明显多头 OB")
                                
                        with f2:
                            bear_fvg = tech["nearest_bear_fvg"]
                            if bear_fvg:
                                st.error(f" 最近空头 FVG ： {bear_fvg['date']} |  区间  {bear_fvg['bottom']:.2f} - {bear_fvg['top']:.2f}")
                            else:
                                st.info(" 最近未检测到明显空头 FVG")
                                
                            if smc["latest_bear_ob"]:
                                st.error(f" 最近空头 OB ： {smc['latest_bear_ob']['date']} | 区间  {smc['latest_bear_ob']['bottom']:.2f} - {smc['latest_bear_ob']['top']:.2f}")
                            else:
                                st.info(" 最近未检测到明显空头 OB")
                                
                        st.markdown("#####  🏗️   市场结构补充 ")
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
                        
                        st.markdown("#####  🎯  动态支撑 / 压力 ")
                        z1, z2, z3 = st.columns(3)
                        z1.metric(" 最新收盘 ", f"{latest_close:.2f}")
                        z2.metric(" 动态支撑参考 ", f"{support_zone:.2f}")
                        z3.metric(" 动态压力参考 ", f"{pressure_zone:.2f}")
                        
                        with st.expander(" 📚  技术面模型说明 "):
                            st.write("""
- EMA20 / EMA60 / EMA120 ：判断短中长期趋势
- RSI14 ：判断超买超卖与动量强弱
- MACD ：判断动量拐点与趋势延续
- ATR14 ：判断波动率，辅助止损空间评估
- FVG （ Fair Value Gap ）：观察价格失衡区与回补机会
- BOS （ Break of Structure ）：判断结构是否有效突破
- Order Block ：寻找潜在机构承接 / 抛压区域
- MSS （ Market Structure Shift ）：趋势结构切换信号
- EQH / EQL ：识别流动性池
- Premium / Discount Zone ：判断当前位置贵 / 便宜
- 流动性扫盘：识别假突破、诱多诱空
""")
                        with st.spinner(" 🧠  首席策略官撰写资产评估报告 ..."):
                            prompt = f"""
你现在是顶级私募基金的首席技术策略官 + 基本面投资经理。
请对股票  {name}({symbol_input})  做一份 “ 基本面 + 高阶技术结构 + 交易计划 ” 综合报告。
【基础数据】
-  现价 : {price}
-  日涨跌幅 : {pct}%
-  总市值 : {quote['market_cap']}  亿
-  动态 PE: {quote['pe']}
-  市净率 PB: {quote['pb']}
-  换手率 : {quote['turnover']}%
【经典技术指标】
-  趋势 : {tech['trend']}
- RSI14: {tech['rsi14']}
- ATR14: {tech['atr14']}
- MACD 状态 : {tech['macd_state']}
-  布林状态 : {tech['bb_state']}
-  量能状态 : {tech['vol_state']}
- EMA20: {tech['ema20']}
- EMA60: {tech['ema60']}
- EMA120: {tech['ema120']}
-  最近收盘 : {tech['latest_close']}
【结构分析】
- BOS: {tech['bos_state']}
-  流动性扫盘 : {tech['sweep_state']}
- MSS: {smc['mss']}
- Premium/Discount: {smc['pd_zone']}
- EQH: {smc['eqh']}
- EQL: {smc['eql']}
【 FVG / Order Block 】
-  最近多头 FVG: {tech['nearest_bull_fvg']}
-  最近空头 FVG: {tech['nearest_bear_fvg']}
-  最近多头 OB: {smc['latest_bull_ob']}
-  最近空头 OB: {smc['latest_bear_ob']}
【请输出】
1.  基本面与估值是否匹配当前走势
2.  趋势、动量、波动、结构的综合判断
3. FVG 、 OB 、 BOS 、 MSS 、流动性扫盘分别说明了什么
4.  当前更像趋势延续、回撤中的二次启动，还是冲高衰竭
5.  给出交易计划：
   -  激进型做法
   -  稳健型做法
   -  失效点 / 风险点
6.  最后给一句结论：看多 / 观察 / 谨慎 / 偏空
要求：
-  语言专业、简洁、机构化
-  不要空话
-  尽量像真正交易员在写盘前计划
"""
                            st.markdown(call_ai(prompt))

# ================= Tab 2:  宏观大盘推演  =================
with tab2:
    with st.container(border=True):
        st.markdown("####  📊  全盘系统级推演 ")
        st.write(" 结合全局宏观看板与近期市场结构，进行大局观研判。 ")
        if st.button(" 运行大盘沙盘推演 ", type="primary"):
            if not api_key:
                st.error(" 配置缺失 : GROQ_API_KEY")
            else:
                with st.spinner(" 推演引擎初始化 ..."):
                    prompt = f"""
你现在是高盛首席宏观策略师。请基于当前 A 股与外汇的精准数据进行大局观推演：
实时数据： {str(pulse_data)}
请输出：
1.  市场全景定调（分化还是普涨）
2.  北向资金意愿推断（基于汇率）
3.  短期沙盘推演方向
"""
                    st.markdown(call_ai(prompt, temperature=0.4))

# ================= Tab 3:  热点资金板块  =================
with tab3:
    with st.container(border=True):
        st.markdown("####  🔥  当日主力资金狂欢地 (Top 10)")
        st.write(" 追踪全天涨幅最猛的行业板块，揪出领涨龙头，识别主线题材。 ")
        if st.button(" 扫描今日热点板块 ", type="primary"):
            if not api_key:
                st.error(" 配置缺失 : GROQ_API_KEY")
            else:
                with st.spinner(" 深潜获取东方财富板块异动数据 ..."):
                    blocks = get_hot_blocks()
                    if blocks:
                        df_blocks = pd.DataFrame(blocks)
                        st.dataframe(df_blocks, width="stretch", hide_index=True)
                        
                        with st.spinner(" 🧠  首席游资操盘手拆解底层逻辑 ..."):
                            blocks_str = "\n".join([f"{b[' 板块名称 ']} ( 涨幅 :{b[' 涨跌幅 ']}%,  领涨 :{b[' 领涨股票 ']})" for b in blocks[:5]])
                            prompt = f"""
作为顶级游资操盘手，请解读今日最强的 5 个板块：
{blocks_str}
请输出：
1.  【核心驱动】领涨板块背后的底层逻辑或政策利好是什么？
2.  【行情定性】这是一日游情绪宣泄，还是具备中线潜力的主线行情？
3.  【低位延展】散户不能盲目追高，请推荐 1-2 个可能被资金轮动到的低位关联延伸概念。
"""
                            st.markdown(call_ai(prompt, temperature=0.4))
                    else:
                        st.error(" 获取板块数据失败，接口可能正处于熔断保护期。 ")

# ================= Tab 4:  高阶情报终端 (优化版) =================
with tab4:
    st.markdown("####  📡  机构级事件图谱与智能评级矩阵 ")
    st.write(" 追踪彭博、推特、美联储、特朗普等宏观变量。已深度适配移动端，引入极客量化风控模块。 ")
    
    if st.button(" 🚨  截获并解析全球突发 ", type="primary"):
        if not api_key:
            st.error(" 配置缺失 : GROQ_API_KEY")
        else:
            with st.spinner(" 监听全网节点并执行深度 NLP 解析 ..."):
                global_news = get_global_news()
                if not global_news:
                    st.warning(" 当前信号静默或被防火墙拦截。 ")
                else:
                    news_text = "\n".join(global_news)
                    with st.expander(" 🕵️‍ ♂ ️   查看底层监听流 (Raw Data)"):
                        st.text(news_text)
                    
                    with st.spinner(" 🧠  情报官正在生成自适应移动端的情报卡片 ..."):
                        prompt = f"""
你现在是华尔街顶级对冲基金的【首席宏观情报官】与【高阶量化风控专家】。
我截获了全球金融市场的底层快讯流。请你挑选出最具爆炸性和市场影响力的 5-8 条动态。
重点寻猎靶标：彭博社 (Bloomberg)、推特 (X)、特朗普 (Trump)、马斯克 (Musk)、美联储，以及任何可能引发流动性危机或资金抱团退潮的事件。

⚠️【排版严令：禁止使用 Markdown 表格】⚠️
为了适配移动端设备的终端显示，你绝对不能使用表格！必须为每一个事件生成一个独立的情报卡片。
请【严格根据快讯内容重写】下面方括号里的内容，绝对不要原样保留“事件核心提炼标题”这种占位符文本！

输出格式必须如下：
### [评级Emoji] [[信源/人物]] [用5-15个字高度概括真实发生的事件标题]
* ⏰ **时间截获**: [提取对应时间]
* 📝 **情报简述**: [用1-2句话清晰说明到底发生了什么事、谁说了什么话、有什么具体动作]
* 🎯 **受波及资产**: [具象化指出利好/利空的资产，如：美债、加密市场(BTC/SOL)、A股某具体板块、原油等]
* 🧠 **沙盘推演**: [一句话精炼指出对金融市场的实质影响，以及资金潜在的做多/做空避险方向]
* ☢️ **风控预警**: [结合市场情绪，给出一个简短的硬核预警，例如：散户诱多风险、巨鲸砸盘预警、流动性抽干高危等]
---

在 [评级Emoji] 处，严格遵守以下标准：
🔴 核心：直接引发巨震的突发、大选级人物强硬表态、黑天鹅事件。
🟡 重要：关键经济数据、行业重磅政策、流动性显著异动。
🔵 一般：常规宏观事件。

底层情报数据流：
{news_text}
"""
                        report = call_ai(prompt, temperature=0.2) # 稍微调低一点温度让标题提炼更精准
                        st.markdown("---")
                        st.markdown(report)
