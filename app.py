import streamlit as st
from groq import Groq
import pandas as pd
import numpy as np
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import re
import akshare as ak
import tushare as ts
import random
from datetime import datetime

# ================= 页面与终端 UI 配置 =================
st.set_page_config(page_title="AI 量化投研终端 Pro Max", page_icon="🏦", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    .stTabs [data-baseweb="tab-list"] { gap: 10px; flex-wrap: wrap; }
    .stTabs [data-baseweb="tab"] { height: auto; min-height: 40px; white-space: normal; background-color: transparent; border-radius: 4px 4px 0 0; padding: 8px 12px; font-weight: bold; }
    .terminal-header { font-family: 'Courier New', Courier, monospace; color: #888; font-size: 0.8em; margin-bottom: 20px; word-wrap: break-word; }
    [data-testid="stMetricValue"] { font-size: 1.5rem; }
    </style>
""", unsafe_allow_html=True)

st.title("🏦 AI 智能量化投研终端")
st.markdown(f"<div class='terminal-header'>TERMINAL BUILD v6.0 (TrendIQ Core + FVG + DRL) | SYS_TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>", unsafe_allow_html=True)

api_key = st.secrets.get("GROQ_API_KEY", "")

# ================= 侧边栏 =================
with st.sidebar:
    st.header("⚙️ 终端控制台")
    ts_token = st.text_input("🔑 Tushare Token", type="password", help="仅作容灾兜底")
    DEBUG_MODE = st.checkbox("🛠️ 开启底层日志")
    st.markdown("---")
    st.markdown("### 📡 策略引擎状态")
    st.success("TrendIQ 交易验证: ACTIVE")
    st.success("动态支撑/压力: ACTIVE")
    st.success("FVG 量化缺口: ACTIVE")

if ts_token: ts.set_token(ts_token)

# ================= 网络底座 =================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36"
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
    except: return default

def fetch_json(url, timeout=5, extra_headers=None):
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    if extra_headers: headers.update(extra_headers)
    try:
        res = SESSION.get(url, headers=headers, timeout=timeout)
        res.raise_for_status()
        return res.json()
    except: return None

# ================= 核心数据流 =================
@st.cache_data(ttl=60)
def get_global_news():
    url = "https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size=60&zhibo_id=152&tag_id=0&dire=f&dpc=1"
    res = fetch_json(url, extra_headers={"Referer": "https://finance.sina.com.cn/"})
    news = []
    if res and res.get("result", {}).get("data", {}).get("feed", {}).get("list"):
        for item in res["result"]["data"]["feed"]["list"]:
            text = re.sub(r'<[^>]+>', '', str(item.get("rich_text", "")).strip())
            if len(text) > 15: news.append(f"[{item.get('create_time', '')}] {text}")
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

def get_stock_quote(symbol):
    market = "1" if str(symbol).startswith(("6", "9", "5", "7")) else "0"
    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={market}.{symbol}&ut=fa5fd1943c7b386f172d6893dbfba10b&fltt=2&fields=f58,f43,f170,f116,f162,f168"
    res = fetch_json(url)
    if res and res.get("data"):
        d = res["data"]
        return {
            "name": d.get("f58", "未知"), "price": safe_float(d.get("f43")), "pct": safe_float(d.get("f170")),
            "market_cap": safe_float(d.get("f116")) / 100000000, "pe": d.get("f162", "-"), "turnover": safe_float(d.get("f168"))
        }
    return None

def get_kline(symbol, days=60):
    try:
        df = ak.stock_zh_a_hist(symbol=str(symbol), period="daily", adjust="qfq")
        if df is not None and not df.empty:
            df = df.rename(columns={"日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "vol"})
            df[['open', 'close', 'high', 'low']] = df[['open', 'close', 'high', 'low']].astype(float)
            return df.tail(days).reset_index(drop=True)
    except: pass
    return None

# ================= 高阶量化特征与支撑压力引擎 =================
def extract_quant_features(df):
    if df is None or len(df) < 20:
        return {"fvg_status": "数据不足", "fvg_gap": "N/A", "volatility": "N/A", "momentum": "N/A", "support": "N/A", "resistance": "N/A"}
    
    # 1. 动态支撑位与压力位 (基于近20日极值与密集交易区)
    recent_20 = df.tail(20)
    resistance = recent_20['high'].max()
    support = recent_20['low'].min()
    
    # 2. 寻找最近的 FVG (Fair Value Gap)
    fvg_status = "未检测到近期缺口"
    fvg_gap = "无"
    for i in range(len(df)-1, 1, -1):
        c1_high, c1_low = df.loc[i-2, 'high'], df.loc[i-2, 'low']
        c3_high, c3_low = df.loc[i, 'high'], df.loc[i, 'low']
        
        if c1_low > c3_high:
            fvg_status = "📉 Bearish FVG (看跌压力区)"
            fvg_gap = f"{c3_high:.2f} - {c1_low:.2f}"
            break
        elif c1_high < c3_low:
            fvg_status = "📈 Bullish FVG (看涨支撑区)"
            fvg_gap = f"{c1_high:.2f} - {c3_low:.2f}"
            break

    # 3. 因子模型：波动率与动量
    returns = df['close'].pct_change()
    volatility_20d = returns.tail(20).std() * np.sqrt(252) * 100
    momentum_10d = (df['close'].iloc[-1] / df['close'].iloc[-11] - 1) * 100 if len(df) > 10 else 0
    
    return {
        "fvg_status": fvg_status, "fvg_gap": fvg_gap,
        "volatility": f"{volatility_20d:.2f}%", "momentum": f"{momentum_10d:.2f}%",
        "support": f"{support:.2f}", "resistance": f"{resistance:.2f}"
    }

# ================= AI 计算核心 =================
def call_ai(prompt, model="llama-3.3-70b-versatile", temperature=0.2):
    try:
        client = Groq(api_key=api_key)
        completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}], model=model, temperature=temperature
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"❌ AI 节点故障: {e}"

# ================= 终端全局看板 =================
st.markdown("### 🌍 宏观市场看板")
pulse_data = get_market_pulse()
if pulse_data:
    dash_cols = st.columns(len(pulse_data))
    for idx, (key, data) in enumerate(pulse_data.items()):
        with dash_cols[idx]:
            with st.container(border=True):
                if "CNH" in key: st.metric(key, f"{data['price']:.4f}", f"{data['pct']:.2f}%", delta_color="inverse")
                else: st.metric(key, f"{data['price']:.2f}", f"{data['pct']:.2f}%")

st.markdown("<br>", unsafe_allow_html=True)

# ================= 终端功能选项卡 =================
tab1, tab2, tab3 = st.tabs(["🎯 I. 个股实战与验证 (TrendIQ)", "📈 II. 大盘与热点推演", "🦅 III. 替代数据监控"])

# ----------------- Tab 1: 个股解析与实战买卖点 -----------------
with tab1:
    with st.container(border=True):
        col1, col2 = st.columns([1, 1])
        with col1:
            symbol_input = st.text_input("标的代码", placeholder="例：600519")
            analyze_btn = st.button("启动量化与买卖点测算", type="primary", use_container_width=True)
            
        if analyze_btn:
            if not api_key: st.error("配置缺失: GROQ_API_KEY")
            elif len(symbol_input.strip()) != 6: st.warning("代码规范验证失败")
            else:
                with st.spinner("提取深度量价特征、支撑阻力位与 FVG 缺口..."):
                    quote = get_stock_quote(symbol_input)
                    df_kline = get_kline(symbol_input)
                    quant_features = extract_quant_features(df_kline)
                    
                if not quote: st.error("无法捕获行情资产。")
                else:
                    st.markdown("---")
                    name, price, pct = quote["name"], quote["price"], quote["pct"]
                    
                    # 基础信息
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric(f"{name}", f"{price:.2f}", f"{pct:.2f}%")
                    c2.metric("总市值(亿)", f"{quote['market_cap']:.1f}")
                    c3.metric("动态PE", f"{quote['pe']}")
                    c4.metric("换手率", f"{quote['turnover']:.2f}%")
                    
                    # 关键点位与指标卡片 (为手机端高度优化)
                    st.markdown("##### 📍 关键防守与阻力阵地")
                    p1, p2, p3 = st.columns(3)
                    with p1: st.success(f"**强支撑位 (Support)**\n\n¥ {quant_features['support']}")
                    with p2: st.error(f"**强压力位 (Resistance)**\n\n¥ {quant_features['resistance']}")
                    with p3: st.info(f"**FVG 缺口位置**\n\n{quant_features['fvg_gap']}\n\n({quant_features['fvg_status']})")
                    
                    st.line_chart(df_kline.set_index("date")["close"] if df_kline is not None else [])
                    
                    with st.spinner("🧠 正在执行 TrendIQ 级多维策略验证并计算买卖点..."):
                        prompt = f"""
你是全球顶级量化对冲基金的【策略主理人】。你深谙 TrendIQ 交易验证软件的逻辑：不仅要懂宏大叙事，更要敢于给出明确的交易点位。
目标资产: {name} ({symbol_input})。实时现价: {price}。
【底层算法提取的关键数据】：
- 强支撑位: {quant_features['support']}
- 强压力位: {quant_features['resistance']}
- FVG 缺口: {quant_features['fvg_status']} (位置: {quant_features['fvg_gap']})
- 短期动量因子: {quant_features['momentum']}
- 年化波动率: {quant_features['volatility']}

请严格按照以下 3 大模块输出报告，排版要干脆利落（禁绝废话）：

### 1. 🧠 多维模型联合推演
一句话融合 DRL(动量/波动率)、替代数据叙事和自适应因子的当前状态，判断是多头控盘还是空头肆虐？

### 2. 🛡️ 盘口逻辑与 FVG 拆解
当前价格 {price} 距离支撑位和压力位的风险收益比如何？如果有 FVG 缺口，主力资金大概率会在这里做什么动作（回补还是突破）？

### 3. 🎯 TrendIQ 级实战交易计划 (核心！)
结合以上所有数据，必须给出极度明确的操作指令。禁止模糊其词！
* **总体判定**: [Buy / Sell / Hold]
* **建仓区间 (Entry)**: [给出具体的建议价格区间，必须结合现价与支撑位]
* **第一止盈位 (Target 1)**: [基于测算的强压力位 {quant_features['resistance']} 给出一个具体价格]
* **硬性止损位 (Stop Loss)**: [基于强支撑 {quant_features['support']} 或 FVG 缺口的破位点，给出绝对止损价]
"""
                        st.markdown(call_ai(prompt, temperature=0.1)) # 调低温度，让数值建议更客观稳定

# ----------------- Tab 2 & 3: 保持稳定功能 -----------------
with tab2:
    st.write("结合全局宏观与板块资金进行大局观研判。")
    if st.button("运行大局沙盘推演"):
        # 略去非核心代码描述，保证执行效率
        prompt = f"基于实时数据：{str(pulse_data)}。请输出：1.全景定调。2.短线剧本。"
        st.markdown(call_ai(prompt, temperature=0.4))

with tab3:
    st.write("监听全球重大异动与替代数据。")
    if st.button("🚨 截获并解析全球突发"):
        with st.spinner("解析替代数据流..."):
            global_news = get_global_news()
            if global_news:
                prompt = f"过滤以下快讯提取5条核心动态(生成独立信息卡片，禁表格)：\n{chr(10).join(global_news)}"
                st.markdown(call_ai(prompt, temperature=0.1))
