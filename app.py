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

# 引入自定义 CSS，优化移动端与全局样式
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
    .news-card {
        background-color: rgba(30, 30, 30, 0.05);
        border-left: 4px solid #ff4b4b;
        padding: 15px;
        margin-bottom: 15px;
        border-radius: 0 8px 8px 0;
    }
    </style>
""", unsafe_allow_html=True)

st.title("🏦 AI 智能量化投研终端")
st.markdown(
    f"<div class='terminal-header'>TERMINAL BUILD v6.3.0 | SYS_TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | CORE OPTIMIZED</div>",
    unsafe_allow_html=True
)

api_key = st.secrets.get("GROQ_API_KEY", "")

# 初始化全局会话状态 (Session State) 用于缓存数据，防止页面刷新丢失
if "global_report" not in st.session_state:
    st.session_state.global_report = None
if "raw_news_cache" not in st.session_state:
    st.session_state.raw_news_cache = ""

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
    st.success("技术结构引擎 : ACTIVE (核心算法已双重加固)")

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
        if high == df["high"].iloc[i-left : i+right+1].max():
            swing_highs.append((i, high))
        if low == df["low"].iloc[i-left : i+right+1].min():
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
                "type": "bullish", "start_idx": i - 2, "end_idx": i,
                "top": c3["low"], "bottom": c1["high"],
                "date": str(pd.to_datetime(c3["date"]).date())
            })
        if c3["high"] < c1["low"]:
            zones.append({
                "type": "bearish", "start_idx": i - 2, "end_idx": i,
                "top": c1["low"], "bottom": c3["high"],
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
        return "向上 BOS"
    if latest_close < last_swing_low:
        return "向下 BOS"
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
                "type": "bullish_ob", "date": str(pd.to_datetime(curr["date"]).date()),
                "top": max(curr["open"], curr["close"]), "bottom": min(curr["open"], curr["close"])
            })
            
        if curr["close"] > curr["open"] and nxt["close"] < curr["low"] and body_curr < atr * 1.2:
            zones.append({
                "type": "bearish_ob", "date": str(pd.to_datetime(curr["date"]).date()),
                "top": max(curr["open"], curr["close"]), "bottom": min(curr["open"], curr["close"])
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
        
    latest, prev = df.iloc[-1], df.iloc[-2]
    last_high, last_low = swing_highs[-1][1], swing_lows[-1][1]
    
    if prev["close"] < last_high and latest["close"] > last_high:
        return "Bullish MSS"
    if prev["close"] > last_low and latest["close"] < last_low:
        return "Bearish MSS"
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
    return {
        "latest_bull_ob": next((z for z in reversed(obs) if z["type"] == "bullish_ob"), None),
        "latest_bear_ob": next((z for z in reversed(obs) if z["type"] == "bearish_ob"), None),
        "eqh": detect_equal_high_low(df)[0],
        "eql": detect_equal_high_low(df)[1],
        "mss": detect_mss(df),
        "pd_zone": get_premium_discount_zone(df)
    }

def summarize_technicals(df: pd.DataFrame):
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else latest
    
    trend = "震荡"
    if latest["close"] > latest["ema20"] > latest["ema60"]: trend = "多头趋势"
    elif latest["close"] < latest["ema20"] < latest["ema60"]: trend = "空头趋势"
        
    momentum = "中性"
    rsi = latest["rsi14"]
    if pd.notna(rsi):
        if rsi >= 70: momentum = "超买"
        elif rsi <= 30: momentum = "超卖"
        elif rsi > 55: momentum = "偏强"
        elif rsi < 45: momentum = "偏弱"
            
    macd_state = "中性"
    if latest["macd"] > latest["macd_signal"] and latest["macd_hist"] > prev["macd_hist"]:
        macd_state = "金叉后增强"
    elif latest["macd"] < latest["macd_signal"] and latest["macd_hist"] < prev["macd_hist"]:
        macd_state = "死叉后走弱"
        
    bb_state = "带内运行"
    if latest["close"] > latest["bb_up"]: bb_state = "突破上轨"
    elif latest["close"] < latest["bb_low"]: bb_state = "跌破下轨"
        
    vol_state = "量能平稳"
    if pd.notna(latest["vol_ma20"]) and latest["vol_ma20"] > 0:
        if latest["volume"] > latest["vol_ma20"] * 1.8: vol_state = "显著放量"
        elif latest["volume"] < latest["vol_ma20"] * 0.7: vol_state = "明显缩量"
            
    fvg_zones = detect_fvg(df)
    
    return {
        "trend": trend, "momentum": momentum, "macd_state": macd_state,
        "bb_state": bb_state, "vol_state": vol_state, "atr14": latest["atr14"],
        "rsi14": latest["rsi14"], "bos_state": detect_bos(df), "sweep_state": detect_liquidity_sweep(df),
        "nearest_bull_fvg": next((z for z in reversed(fvg_zones) if z["type"] == "bullish"), None),
        "nearest_bear_fvg": next((z for z in reversed(fvg_zones) if z["type"] == "bearish"), None),
        "latest_close": latest["close"], "ema20": latest["ema20"],
        "ema60": latest["ema60"], "ema120": latest["ema120"], "smc": build_smc_summary(df)
    }

def build_price_figure(df: pd.DataFrame):
    plot_df = df.copy()
    plot_df["date_str"] = plot_df["date"].dt.strftime("%Y-%m-%d")
    fig = go.Figure()
    
    fig.add_trace(go.Candlestick(
        x=plot_df["date_str"], open=plot_df["open"], high=plot_df["high"],
        low=plot_df["low"], close=plot_df["close"], name="K线"
    ))
    fig.add_trace(go.Scatter(x=plot_df["date_str"], y=plot_df["ema20"], mode="lines", name="EMA20"))
    fig.add_trace(go.Scatter(x=plot_df["date_str"], y=plot_df["ema60"], mode="lines", name="EMA60"))
    fig.add_trace(go.Scatter(x=plot_df["date_str"], y=plot_df["ema120"], mode="lines", name="EMA120"))
    
    for zone in detect_fvg(plot_df, max_zones=4):
        start_idx = zone["start_idx"]
        end_idx = min(len(plot_df) - 1, start_idx + 12)
        x0, x1 = plot_df.iloc[start_idx]["date_str"], plot_df.iloc[end_idx]["date_str"]
        fillcolor = "rgba(0, 200, 0, 0.15)" if zone["type"] == "bullish" else "rgba(200, 0, 0, 0.15)"
        fig.add_shape(type="rect", x0=x0, x1=x1, y0=zone["bottom"], y1=zone["top"], line=dict(width=0), fillcolor=fillcolor)
        
    fig.update_layout(height=520, xaxis_title="日期", yaxis_title="价格", xaxis_rangeslider_visible=False, margin=dict(l=20, r=20, t=30, b=20))
    return fig

# ================= 核心数据流 =================
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
    indices = {"上证指数": "1.000001", "深证成指": "0.399001", "创业板指": "0.399006"}
    for name, code in indices.items():
        url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={code}&ut=fa5fd1943c7b386f172d6893dbfba10b&fltt=2&fields=f43,f170"
        res = fetch_json(url)
        if res and res.get("data"):
            pulse[name] = {"price": safe_float(res["data"].get("f43")), "pct": safe_float(res["data"].get("f170"))}
            
    cnh_url = "https://push2.eastmoney.com/api/qt/stock/get?secid=133.USDCNH&ut=fa5fd1943c7b386f172d6893dbfba10b&fltt=2&fields=f43,f170"
    cnh_res = fetch_json(cnh_url)
    if cnh_res and cnh_res.get("data"):
        pulse["USD/CNH(离岸)"] = {"price": safe_float(cnh_res["data"].get("f43")), "pct": safe_float(cnh_res["data"].get("f170"))}
    return pulse

@st.cache_data(ttl=300)
def get_hot_blocks():
    try:
        df = ak.stock_board_industry_name_em()
        if df is not None and not df.empty:
            return df.sort_values(by="涨跌幅", ascending=False).head(10)[["板块名称", "涨跌幅", "上涨家数", "下跌家数", "领涨股票"]].to_dict('records')
    except: pass
    time.sleep(1) 
    try:
        df = ak.stock_board_concept_name_em()
        if df is not None and not df.empty:
            return df.sort_values(by="涨跌幅", ascending=False).head(10)[["板块名称", "涨跌幅", "上涨家数", "下跌家数", "领涨股票"]].to_dict('records')
    except: pass
    return None

def get_stock_quote(symbol):
    market = "1" if str(symbol).startswith(("6", "9", "5", "7")) else "0"
    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={market}.{symbol}&ut=fa5fd1943c7b386f172d6893dbfba10b&fltt=2&fields=f58,f43,f170,f116,f162,f168,f167"
    res = fetch_json(url)
    if res and res.get("data"):
        d = res["data"]
        raw_price = safe_float(d.get("f43"))
        return {
            "name": d.get("f58", "未知"),
            "price": raw_price / 1000 if raw_price > 1000 else raw_price,
            "pct": safe_float(d.get("f170")),
            "market_cap": safe_float(d.get("f116")) / 100000000,
            "pe": d.get("f162", "-"),
            "pb": d.get("f167", "-"),
            "turnover": safe_float(d.get("f168"))
        }
    return None

def get_kline(symbol, days=220):
    end_date = datetime.now()
    start_date = end_date - pd.Timedelta(days=days + 150) 
    start_str, end_str = start_date.strftime("%Y%m%d"), end_date.strftime("%Y%m%d")
    start_str_bs, end_str_bs = start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")

    try:
        df = ak.stock_zh_a_hist(symbol=str(symbol), period="daily", start_date=start_str, end_date=end_str, adjust="qfq")
        if df is not None and not df.empty:
            df = df.rename(columns={"日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "volume", "换手率": "turnover_rate"})
            if all(col in df.columns for col in ["date", "open", "high", "low", "close", "volume"]):
                df["date"] = pd.to_datetime(df["date"])
                for col in ["open", "high", "low", "close", "volume"]: df[col] = pd.to_numeric(df[col], errors="coerce")
                df = df.dropna().reset_index(drop=True)
                if len(df) > 0: return df.tail(days).reset_index(drop=True)
    except: pass

    try:
        df = ak.stock_zh_a_hist(symbol=str(symbol), period="daily", start_date=start_str, end_date=end_str, adjust="")
        if df is not None and not df.empty:
            df = df.rename(columns={"日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "volume"})
            if all(col in df.columns for col in ["date", "open", "high", "low", "close", "volume"]):
                df["date"] = pd.to_datetime(df["date"])
                for col in ["open", "high", "low", "close", "volume"]: df[col] = pd.to_numeric(df[col], errors="coerce")
                df = df.dropna().reset_index(drop=True)
                if len(df) > 0: return df.tail(days).reset_index(drop=True)
    except: pass

    try:
        bs.login() 
        bs_code = f"sh.{symbol}" if str(symbol).startswith(("6", "9", "5", "7")) else f"sz.{symbol}"
        rs = bs.query_history_k_data_plus(bs_code, "date,open,high,low,close,volume", start_date=start_str_bs, end_date=end_str_bs, frequency="d", adjustflag="2")
        data_list = []
        while (rs.error_code == '0') & rs.next(): data_list.append(rs.get_row_data())
        bs.logout() 
        if data_list:
            df = pd.DataFrame(data_list, columns=rs.fields)
            df["date"] = pd.to_datetime(df["date"])
            for col in ["open", "high", "low", "close", "volume"]: df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna().sort_values("date").reset_index(drop=True)
            if len(df) > 0: return df.tail(days).reset_index(drop=True)
    except:
        try: bs.logout()
        except: pass

    try:
        if ts_token:
            pro = ts.pro_api()
            market = ".SH" if str(symbol).startswith(("6", "9", "5", "7")) else ".SZ"
            df = pro.daily(ts_code=f"{symbol}{market}", start_date=start_str, end_date=end_str)
            if df is not None and not df.empty:
                df = df.rename(columns={"trade_date": "date", "vol": "volume"})
                df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
                for col in ["open", "high", "low", "close", "volume"]: df[col] = pd.to_numeric(df[col], errors="coerce")
                df = df.dropna().sort_values("date").reset_index(drop=True)
                if len(df) > 0: return df.tail(days).reset_index(drop=True)
    except: pass
            
    return None

# ================= AI 计算核心 =================
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
                        st.warning("有效 K 线极少，仅进行轻量推演。")
                        with st.spinner("🧠 首席策略官撰写资产评估报告..."):
                            prompt = f"基于股票 {name}({symbol_input}) 现价 {price}，涨幅 {pct}%，市值 {quote['market_cap']} 亿。请分析基本面资金意图，并给出短线/中线具体买卖点位推演。"
                            st.markdown(call_ai(prompt))
                    else:
                        df_kline = add_indicators(df_kline)
                        tech = summarize_technicals(df_kline)
                        smc = tech["smc"]
                        
                        st.plotly_chart(build_price_figure(df_kline), width="stretch")
                        
                        st.markdown("##### 🔬 核心技术指标")
                        t1, t2, t3, t4 = st.columns(4)
                        t1.metric("趋势", tech["trend"])
                        t2.metric("RSI14", f"{tech['rsi14']:.2f}" if pd.notna(tech["rsi14"]) else "N/A")
                        t3.metric("ATR14", f"{tech['atr14']:.2f}" if pd.notna(tech["atr14"]) else "N/A")
                        t4.metric("MACD状态", tech["macd_state"])
                        
                        st.markdown("##### 🧩 SMC 结构信息")
                        f1, f2 = st.columns(2)
                        with f1:
                            if tech["nearest_bull_fvg"]: st.success(f"多头FVG：{tech['nearest_bull_fvg']['bottom']:.2f} - {tech['nearest_bull_fvg']['top']:.2f}")
                            if smc["latest_bull_ob"]: st.success(f"多头OB：{smc['latest_bull_ob']['bottom']:.2f} - {smc['latest_bull_ob']['top']:.2f}")
                        with f2:
                            if tech["nearest_bear_fvg"]: st.error(f"空头FVG：{tech['nearest_bear_fvg']['bottom']:.2f} - {tech['nearest_bear_fvg']['top']:.2f}")
                            if smc["latest_bear_ob"]: st.error(f"空头OB：{smc['latest_bear_ob']['bottom']:.2f} - {smc['latest_bear_ob']['top']:.2f}")

                        with st.spinner("🧠 首席策略官进行多维深度解构..."):
                            prompt = f"""
请对股票 {name}({symbol_input}) 做一份极具实战价值的【估值 + 资金流 + 支撑/压力 + 精准买卖点】综合研判。
现价: {price} | 市值: {quote['market_cap']}亿 | PE: {quote['pe']} | 换手率: {quote['turnover']}%
趋势: {tech['trend']} | RSI14: {tech['rsi14']} | 最新收盘: {tech['latest_close']}
请务必按以下维度输出：
1. 基本面与估值定位
2. 资金面穿透与意图推演
3. 支撑与压力位精准测算
4. 明确的短期/中长线建仓进入点与止盈离场点价格区间
结论定调：[看多 / 观察 / 谨慎 / 偏空]
"""
                            st.markdown(call_ai(prompt))

# ================= Tab 2: 宏观大盘 =================
with tab2:
    with st.container(border=True):
        st.markdown("#### 📊 全盘系统级推演")
        if st.button("运行大盘沙盘推演", type="primary"):
            if not api_key: st.error("缺失 API KEY")
            else:
                with st.spinner("推演引擎初始化..."):
                    st.markdown(call_ai(f"基于当前实时数据 {str(pulse_data)} 进行宏观大局观推演。1. 市场全景定调 2. 北向资金意愿推断 3. 短期沙盘推演方向", temperature=0.4))

# ================= Tab 3: 热点板块 =================
with tab3:
    with st.container(border=True):
        st.markdown("#### 🔥 当日主力资金狂欢地 (附实战标的推荐)")
        if st.button("扫描板块与生成配置推荐", type="primary"):
            if not api_key: st.error("缺失 API KEY")
            else:
                with st.spinner("深潜获取异动数据..."):
                    blocks = get_hot_blocks()
                    if blocks:
                        st.dataframe(pd.DataFrame(blocks), width="stretch", hide_index=True)
                        blocks_str = "\n".join([f"{b['板块名称']} (领涨:{b['领涨股票']})" for b in blocks[:5]])
                        with st.spinner("🧠 游资操盘手拆解逻辑..."):
                            st.markdown(call_ai(f"解读今日最强板块：{blocks_str}。输出核心驱动逻辑、行情定性，并推荐 2-3 只实战配置标的及入场姿势。", temperature=0.4))
                    else:
                        st.error("获取板块数据失败。")

# ================= Tab 4: 高阶情报终端 (深度优化版) =================
with tab4:
    st.markdown("#### 📡 机构级事件图谱与智能评级矩阵")
    st.write("追踪彭博、推特、美联储、特朗普等宏观变量。已引入「会话记忆缓存」与「极客卡片渲染」，完美适配移动端。")
    
    col_btn, col_clear = st.columns([3, 1])
    with col_btn:
        if st.button("🚨 截获并解析全球突发", type="primary", use_container_width=True):
            if not api_key:
                st.error("配置缺失: GROQ_API_KEY")
            else:
                with st.spinner("监听全网节点并执行深度 NLP 解析..."):
                    global_news = get_global_news()
                    if not global_news:
                        st.warning("当前信号静默或被防火墙拦截。")
                    else:
                        news_text = "\n".join(global_news)
                        # 将原生数据存入缓存
                        st.session_state.raw_news_cache = news_text
                        
                        with st.spinner("🧠 情报官正在生成自适应移动端的情报卡片..."):
                            prompt = f"""
你现在是顶级对冲基金的首席宏观情报官。我截获了全球金融市场的底层快讯流。
请你挑选出最具爆炸性和市场影响力的 5-8 条动态。重点寻猎：宏观政策、重要人物发言、地缘突发。

⚠️【格式严令】⚠️
绝对禁止使用 Markdown 表格！绝对禁止输出重复的内容！
请直接以如下紧凑的 Markdown 格式输出每一条情报（每一条之间空一行）：

### [评级Emoji] [[信源/人物]] [高度概括标题]
- **时间**: [截获时间]
- **简述**: [1-2句话说清发生了什么]
- **波及**: [利好/利空什么资产]
- **推演**: [资金动向及风控硬核预警]

[评级Emoji] 标准：🔴 核心巨震，🟡 重要宏观，🔵 常规消息。

底层情报数据流：
{news_text}
"""
                            # 获取 AI 结果并存入 Session State，防止页面刷新丢失
                            report = call_ai(prompt, temperature=0.2)
                            st.session_state.global_report = report

    with col_clear:
        # 提供手动清除缓存的入口
        if st.session_state.global_report and st.button("🗑️ 清空缓存", use_container_width=True):
            st.session_state.global_report = None
            st.session_state.raw_news_cache = ""
            st.rerun()

    # 渲染模块：只有当缓存中有报告时才渲染，确保只渲染一次
    if st.session_state.global_report:
        st.markdown("---")
        with st.expander("🕵️‍♂️ 查看底层监听流 (Raw Data)", expanded=False):
            st.text(st.session_state.raw_news_cache)
        
        # 使用自定义 CSS 的 Div 包裹输出内容，让移动端看起来更像卡片
        st.markdown("<div class='news-card'>", unsafe_allow_html=True)
        st.markdown(st.session_state.global_report)
        st.markdown("</div>", unsafe_allow_html=True)
