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
    f"<div class='terminal-header'>TERMINAL BUILD v5.2.0 | SYS_TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | MOBILE OPTIMIZED</div>",
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
    st.success("行情引流: ACTIVE")
    st.success("7x24快讯: ACTIVE")
    st.success("板块扫描: ACTIVE")
    st.success("技术结构引擎: ACTIVE")

if ts_token:
    ts.set_token(ts_token)


# ================= 网络底座 =================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:115.0) Gecko/20100101 Firefox/115.0",
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36"
]


@st.cache_resource
def get_session():
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[403, 429, 500, 502, 503, 504]
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

    # Bollinger Bands
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
    for i in range(2, len(df)):
        c1 = df.iloc[i-2]
        c3 = df.iloc[i]

        # Bullish FVG
        if c3["low"] > c1["high"]:
            zones.append({
                "type": "bullish",
                "start_idx": i - 2,
                "end_idx": i,
                "top": c3["low"],
                "bottom": c1["high"],
                "date": str(pd.to_datetime(c3["date"]).date())
            })

        # Bearish FVG
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
        return "向上 BOS（结构突破）"
    if latest_close < last_swing_low:
        return "向下 BOS（结构破坏）"
    return "结构未突破"


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
    }


# ================= 核心数据流 =================
@st.cache_data(ttl=60)
def get_global_news():
    """全球7x24小时事件嗅探"""
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
    """获取宏观三大指数及外汇"""
    pulse = {}
    indices = {"上证指数": "1.000001", "深证成指": "0.399001", "创业板指": "0.399006"}
    for name, code in indices.items():
        url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={code}&ut=fa5fd1943c7b386f172d6893dbfba10b&fltt=2&fields=f43,f170"
        res = fetch_json(url)
        if res and res.get("data"):
            pulse[name] = {
                "price": safe_float(res["data"].get("f43")),
                "pct": safe_float(res["data"].get("f170"))
            }

    cnh_url = "https://push2.eastmoney.com/api/qt/stock/get?secid=133.USDCNH&ut=fa5fd1943c7b386f172d6893dbfba10b&fltt=2&fields=f43,f170"
    cnh_res = fetch_json(cnh_url)
    if cnh_res and cnh_res.get("data"):
        pulse["USD/CNH(离岸)"] = {
            "price": safe_float(cnh_res["data"].get("f43")),
            "pct": safe_float(cnh_res["data"].get("f170"))
        }

    return pulse


@st.cache_data(ttl=300)
def get_hot_blocks():
    """获取当天涨幅最猛的热门板块"""
    try:
        df = ak.stock_board_industry_name_em()
        if df is not None and not df.empty:
            top_blocks = df.sort_values(by="涨跌幅", ascending=False).head(10)
            return top_blocks[["板块名称", "涨跌幅", "上涨家数", "下跌家数", "领涨股票"]].to_dict("records")
    except Exception:
        pass
    return None


def get_stock_quote(symbol):
    """个股行情获取"""
    market = "1" if str(symbol).startswith(("6", "9", "5", "7")) else "0"
    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={market}.{symbol}&ut=fa5fd1943c7b386f172d6893dbfba10b&fltt=2&fields=f58,f43,f170,f116,f162,f168,f167"
    res = fetch_json(url)
    if res and res.get("data"):
        d = res["data"]
        raw_price = safe_float(d.get("f43"))
        price = raw_price / 1000 if raw_price > 1000 else raw_price
        return {
            "name": d.get("f58", "未知"),
            "price": price,
            "pct": safe_float(d.get("f170")),
            "market_cap": safe_float(d.get("f116")) / 100000000,
            "pe": d.get("f162", "-"),
            "pb": d.get("f167", "-"),
            "turnover": safe_float(d.get("f168"))
        }
    return None


def get_kline(symbol, days=180):
    try:
        df = ak.stock_zh_a_hist(symbol=str(symbol), period="daily", adjust="qfq")
        if df is not None and not df.empty:
            df = df.rename(columns={
                "日期": "date",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
                "成交额": "amount",
                "换手率": "turnover_rate"
            })

            keep_cols = ["date", "open", "high", "low", "close", "volume"]
            for col in keep_cols:
                if col not in df.columns:
                    return None

            df = df[keep_cols].copy()
            df["date"] = pd.to_datetime(df["date"])
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")

            df = df.dropna().tail(days).reset_index(drop=True)
            return df
    except Exception:
        pass
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


# ================= Tab 1: 个股解析（增强版） =================
with tab1:
    with st.container(border=True):
        st.markdown("#### 🔎 个股雷达锁定（增强技术结构版）")

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
                with st.spinner("量子计算与数据提取中..."):
                    quote = get_stock_quote(symbol_input)
                    df_kline = get_kline(symbol_input, days=180)

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

                    if df_kline is None or df_kline.empty or len(df_kline) < 60:
                        st.warning("K线样本不足，无法进行增强技术分析。")
                        if df_kline is not None and not df_kline.empty:
                            temp = df_kline.copy()
                            temp["date"] = temp["date"].dt.strftime("%Y-%m-%d")
                            st.line_chart(temp.set_index("date")["close"])
                    else:
                        df_kline = add_indicators(df_kline)
                        tech = summarize_technicals(df_kline)

                        chart_df = df_kline.copy()
                        chart_df["date"] = chart_df["date"].dt.strftime("%Y-%m-%d")
                        st.line_chart(chart_df.set_index("date")[["close", "ema20", "ema60", "ema120"]])

                        st.markdown("#### 📐 技术面结构总览")
                        t1, t2, t3, t4 = st.columns(4)
                        t1.metric("趋势", tech["trend"])
                        t2.metric("RSI14", f"{tech['rsi14']:.2f}" if pd.notna(tech["rsi14"]) else "N/A")
                        t3.metric("ATR14", f"{tech['atr14']:.2f}" if pd.notna(tech["atr14"]) else "N/A")
                        t4.metric("MACD状态", tech["macd_state"])

                        s1, s2, s3, s4 = st.columns(4)
                        s1.metric("布林状态", tech["bb_state"])
                        s2.metric("量能状态", tech["vol_state"])
                        s3.metric("结构状态", tech["bos_state"])
                        s4.metric("流动性状态", tech["sweep_state"])

                        st.markdown("#### 🧩 FVG / 结构信息")
                        f1, f2 = st.columns(2)

                        with f1:
                            bull_fvg = tech["nearest_bull_fvg"]
                            if bull_fvg:
                                st.success(
                                    f"最近多头FVG：{bull_fvg['date']} | 区间 {bull_fvg['bottom']:.2f} - {bull_fvg['top']:.2f}"
                                )
                            else:
                                st.info("最近未检测到明显多头 FVG")

                        with f2:
                            bear_fvg = tech["nearest_bear_fvg"]
                            if bear_fvg:
                                st.error(
                                    f"最近空头FVG：{bear_fvg['date']} | 区间 {bear_fvg['bottom']:.2f} - {bear_fvg['top']:.2f}"
                                )
                            else:
                                st.info("最近未检测到明显空头 FVG")

                        latest_close = tech["latest_close"]
                        support_zone = min(tech["ema20"], tech["ema60"])
                        pressure_zone = max(tech["ema20"], tech["ema60"])

                        st.markdown("#### 🎯 动态支撑 / 压力")
                        z1, z2, z3 = st.columns(3)
                        z1.metric("最新收盘", f"{latest_close:.2f}")
                        z2.metric("动态支撑参考", f"{support_zone:.2f}")
                        z3.metric("动态压力参考", f"{pressure_zone:.2f}")

                        with st.expander("📚 技术面模型说明"):
                            st.write("""
- EMA20 / EMA60 / EMA120：判断短中长期趋势
- RSI14：判断超买超卖与动量强弱
- MACD：判断动量拐点与趋势延续
- ATR14：判断波动率，辅助止损空间评估
- FVG（Fair Value Gap）：观察价格失衡区与回补机会
- BOS（Break of Structure）：判断结构是否有效突破
- 流动性扫盘：识别假突破、诱多诱空
""")

                        with st.spinner("🧠 首席策略官撰写资产评估报告..."):
                            prompt = f"""
你现在是顶级私募基金的首席技术策略官 + 基本面投资经理。
请对股票 {name}({symbol_input}) 做一份“基本面 + 高阶技术结构 + 交易计划”综合报告。

【基础数据】
- 现价: {price}
- 日涨跌幅: {pct}%
- 总市值: {quote['market_cap']} 亿
- 动态PE: {quote['pe']}
- 市净率PB: {quote['pb']}
- 换手率: {quote['turnover']}%

【技术面核心指标】
- 趋势: {tech['trend']}
- RSI14: {tech['rsi14']}
- ATR14: {tech['atr14']}
- MACD状态: {tech['macd_state']}
- 布林状态: {tech['bb_state']}
- 量能状态: {tech['vol_state']}
- BOS结构: {tech['bos_state']}
- 流动性扫盘: {tech['sweep_state']}
- EMA20: {tech['ema20']}
- EMA60: {tech['ema60']}
- EMA120: {tech['ema120']}
- 最近收盘: {tech['latest_close']}

【FVG结构】
- 最近多头FVG: {tech['nearest_bull_fvg']}
- 最近空头FVG: {tech['nearest_bear_fvg']}

【请输出】
1. 基本面与估值是否匹配当前走势
2. 趋势、动量、波动、结构的综合判断
3. FVG、BOS、流动性扫盘分别说明了什么
4. 当前更像趋势延续、回撤中的二次启动，还是冲高衰竭
5. 给出交易计划：
   - 激进型做法
   - 稳健型做法
   - 失效点 / 风险点
6. 最后给一句结论：看多 / 观察 / 谨慎 / 偏空

要求：
- 语言专业、简洁、机构化
- 不要空话
- 尽量像真正交易员在写盘前计划
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
你现在是高盛首席宏观策略师。请基于当前A股与外汇的精准数据进行大局观推演：

实时数据：{str(pulse_data)}

请输出：1. 市场全景定调（分化还是普涨）。2. 北向资金意愿推断（基于汇率）。3. 短期沙盘推演方向。
"""
                    st.markdown(call_ai(prompt, temperature=0.4))


# ================= Tab 3: 热点资金板块 =================
with tab3:
    with st.container(border=True):
        st.markdown("#### 🔥 当日主力资金狂欢地 (Top 10)")
        st.write("追踪全天涨幅最猛的行业板块，揪出领涨龙头，识别主线题材。")

        if st.button("扫描今日热点板块", type="primary"):
            if not api_key:
                st.error("配置缺失: GROQ_API_KEY")
            else:
                with st.spinner("深潜获取东方财富板块异动数据..."):
                    blocks = get_hot_blocks()
                    if blocks:
                        df_blocks = pd.DataFrame(blocks)
                        st.dataframe(df_blocks, use_container_width=True, hide_index=True)

                        with st.spinner("🧠 首席游资操盘手拆解底层逻辑..."):
                            blocks_str = "\n".join(
                                [f"{b['板块名称']} (涨幅:{b['涨跌幅']}%, 领涨:{b['领涨股票']})" for b in blocks[:5]]
                            )
                            prompt = f"""
作为顶级游资操盘手，请解读今日最强的5个板块：

{blocks_str}

请输出：
1. 【核心驱动】领涨板块背后的底层逻辑或政策利好是什么？
2. 【行情定性】这是一日游情绪宣泄，还是具备中线潜力的主线行情？
3. 【低位延展】散户不能盲目追高，请推荐 1-2 个可能被资金轮动到的低位关联延伸概念。
"""
                            st.markdown(call_ai(prompt, temperature=0.4))
                    else:
                        st.error("获取板块数据失败，接口可能正处于熔断保护期。")


# ================= Tab 4: 高阶情报终端 =================
with tab4:
    st.markdown("#### 📡 机构级事件图谱与智能评级矩阵")
    st.write("追踪彭博、推特、美联储、特朗普等宏观变量。已深度适配移动端，告别表格左右滑动烦恼。")

    if st.button("🚨 截获并解析全球突发", type="primary"):
        if not api_key:
            st.error("配置缺失: GROQ_API_KEY")
        else:
            with st.spinner("监听全网节点并执行深度NLP解析..."):
                global_news = get_global_news()
                if not global_news:
                    st.warning("当前信号静默或被防火墙拦截。")
                else:
                    news_text = "\n".join(global_news)

                    with st.expander("🕵️‍♂️ 查看底层监听流 (Raw Data)"):
                        st.text(news_text)

                    with st.spinner("🧠 情报官正在生成自适应移动端的情报卡片..."):
                        prompt = f"""
你现在是华尔街对冲基金的【首席地缘与宏观情报官】。

我截获了全球金融市场的底层快讯流。请你挑选出最具爆炸性和市场影响力的 5-8 条动态。

重点寻猎靶标：彭博社(Bloomberg)、推特(X)、特朗普(Trump)、马斯克(Musk)、美联储。

⚠️【排版严令：禁止使用 Markdown 表格】⚠️
为了适配我的手机端屏幕，你绝对不能使用表格！必须为每一个事件生成一个独立的信息卡片，格式如下：

### [评级Emoji] [信源/人物] 事件核心提炼标题
* ⏰ **时间**: [提取对应时间]
* 🎯 **受影响资产**: [具象化指出利好/利空的资产或板块，如：农业板块、加密货币、出口链]
* 🧠 **深度推演**: [一句话精炼指出对金融市场的实质影响]
---

在 [评级Emoji] 处，严格使用以下三种：
🔴 核心：直接引发巨震的突发、大选级人物表态。
🟡 重要：关键经济数据、行业政策。
🔵 一般：常规事件。

底层情报数据流：
{news_text}
"""
                        report = call_ai(prompt, temperature=0.1)
                        st.markdown("---")
                        st.markdown(report)