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
st.set_page_config(page_title="AI 智能投研终端 Pro Max", page_icon="🏦", layout="wide", initial_sidebar_state="expanded")

# 注入金融风自定义 CSS
st.markdown("""
    <style>
    .stTabs [data-baseweb="tab-list"] { gap: 10px; flex-wrap: wrap; }
    .stTabs [data-baseweb="tab"] { height: auto; min-height: 40px; white-space: normal; background-color: transparent; border-radius: 4px 4px 0 0; padding: 8px 12px; font-weight: bold; }
    .terminal-header { font-family: 'Courier New', Courier, monospace; color: #888; font-size: 0.8em; margin-bottom: 20px; word-wrap: break-word; }
    [data-testid="stMetricValue"] { font-size: 1.5rem; }
    .buy-signal { color: #ff4b4b; font-weight: bold; }
    .sell-signal { color: #00ff00; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

st.title("🏦 AI 智能量化投研终端")
st.markdown(f"<div class='terminal-header'>TERMINAL BUILD v6.2.0 | TrendIQ + FVG + DRL + Quant 5.0 | SYS_TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>", unsafe_allow_html=True)

api_key = st.secrets.get("GROQ_API_KEY", "")

# ================= 侧边栏 (原版保留) =================
with st.sidebar:
    st.header("⚙️ 终端控制台")
    ts_token = st.text_input("🔑 Tushare Token", type="password", help="仅作极致容灾兜底")
    DEBUG_MODE = st.checkbox("🛠️ 开启底层日志嗅探")
    st.markdown("---")
    st.markdown("### 📡 策略引擎状态")
    st.success("TrendIQ 交易验证: ACTIVE")
    st.success("FVG/RSI/MACD 扫描: ACTIVE")
    st.success("DRL 奖励函数计算: ACTIVE")

if ts_token:
    ts.set_token(ts_token)

# ================= 网络底座 (原版保留) =================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
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
    except Exception as e:
        if DEBUG_MODE: st.error(f"Feed Error: {e}")
        return None

# ================= 核心数据流 (原版保留) =================

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

@st.cache_data(ttl=300)
def get_hot_blocks():
    try:
        df = ak.stock_board_industry_name_em()
        if df is not None and not df.empty:
            top_blocks = df.sort_values(by="涨跌幅", ascending=False).head(10)
            return top_blocks[["板块名称", "涨跌幅", "上涨家数", "下跌家数", "领涨股票"]].to_dict('records')
    except: pass
    return None

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

def get_kline(symbol, days=120): # 增加天数以计算长线指标
    try:
        df = ak.stock_zh_a_hist(symbol=str(symbol), period="daily", adjust="qfq")
        if df is not None and not df.empty:
            df = df.rename(columns={"日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "vol"})
            df[['open', 'close', 'high', 'low']] = df[['open', 'close', 'high', 'low']].astype(float)
            return df.tail(days).reset_index(drop=True)
    except: pass
    return None

# ================= 新增：技术面与量化因子计算引擎 =================
def calculate_advanced_indicators(df):
    if df is None or len(df) < 30: return None
    
    # 1. 均线 MA
    df['ma5'] = df['close'].rolling(window=5).mean()
    df['ma10'] = df['close'].rolling(window=10).mean()
    df['ma20'] = df['close'].rolling(window=20).mean()
    
    # 2. RSI (14)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # 3. MACD (12, 26, 9)
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    
    # 4. FVG (公允价值缺口)
    fvg_status, fvg_gap = "未发现缺口", "N/A"
    for i in range(len(df)-1, 1, -1):
        if df.loc[i-2, 'low'] > df.loc[i, 'high']:
            fvg_status, fvg_gap = "📉 Bearish FVG (空头缺口)", f"{df.loc[i, 'high']:.2f}-{df.loc[i-2, 'low']:.2f}"
            break
        elif df.loc[i-2, 'high'] < df.loc[i, 'low']:
            fvg_status, fvg_gap = "📈 Bullish FVG (多头缺口)", f"{df.loc[i-2, 'high']:.2f}-{df.loc[i, 'low']:.2f}"
            break
            
    # 5. 支撑压力位
    recent_20 = df.tail(20)
    resistance = recent_20['high'].max()
    support = recent_20['low'].min()
    
    # 6. DRL/风险平价因子 (波动率)
    returns = df['close'].pct_change()
    volatility = returns.tail(20).std() * np.sqrt(252) * 100
    
    last = df.iloc[-1]
    return {
        "rsi": last['rsi'], "macd": last['macd'], "ma5": last['ma5'], 
        "ma20": last['ma20'], "fvg_status": fvg_status, "fvg_gap": fvg_gap,
        "support": support, "resistance": resistance, "volatility": volatility
    }

# ================= AI 计算核心 (原版保留) =================
def call_ai(prompt, model="llama-3.3-70b-versatile", temperature=0.3):
    try:
        client = Groq(api_key=api_key)
        completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=model, temperature=temperature
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"❌ AI 节点故障: {e}"

# ================= 终端全局看板 (原版保留) =================
st.markdown("### 🌍 宏观市场实时看板")
pulse_data = get_market_pulse()
if pulse_data:
    dash_cols = st.columns(len(pulse_data))
    for idx, (key, data) in enumerate(pulse_data.items()):
        with dash_cols[idx]:
            with st.container(border=True):
                if "CNH" in key: st.metric(key, f"{data['price']:.4f}", f"{data['pct']:.2f}%", delta_color="inverse")
                else: st.metric(key, f"{data['price']:.2f}", f"{data['pct']:.2f}%")

st.markdown("<br>", unsafe_allow_html=True)

# ================= 终端功能选项卡 (原版 4 Tab) =================
tab1, tab2, tab3, tab4 = st.tabs([
    "🎯 I. 个股解析 (TrendIQ+FVG)", 
    "📈 II. 宏观大盘推演", 
    "🔥 III. 资金热点板块",
    "🦅 IV. 高阶情报终端"
])

# ----------------- Tab 1: 个股解析 (增强版：加入指标与实战) -----------------
with tab1:
    with st.container(border=True):
        st.markdown("#### 🔎 个股雷达锁定")
        col1, col2 = st.columns([1, 1])
        with col1:
            symbol_input = st.text_input("标的代码", placeholder="例：600519")
            analyze_btn = st.button("启动核心算法", type="primary", use_container_width=True)
            
        if analyze_btn:
            if not api_key: st.error("配置缺失: GROQ_API_KEY")
            elif len(symbol_input.strip()) != 6: st.warning("代码规范验证失败")
            else:
                with st.spinner("量子计算与技术指标提取中..."):
                    quote = get_stock_quote(symbol_input)
                    df_kline = get_kline(symbol_input)
                    tech = calculate_advanced_indicators(df_kline)
                    
                if not quote or tech is None:
                    st.error("数据捕获失败。")
                else:
                    st.markdown("---")
                    name, price, pct = quote["name"], quote["price"], quote["pct"]
                    
                    # 第一排：基础行情
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric(f"{name}", f"{price:.2f}", f"{pct:.2f}%")
                    c2.metric("MA20 趋势位", f"{tech['ma20']:.2f}")
                    c3.metric("RSI(14) 强弱", f"{tech['rsi']:.1f}")
                    c4.metric("动态支撑位", f"{tech['support']:.2f}")
                    
                    # 第二排：高阶指标卡片
                    st.markdown("##### 📍 技术面与量化核心参数")
                    q1, q2, q3 = st.columns(3)
                    with q1: st.info(f"**FVG 缺口状态**\n\n{tech['fvg_status']}\n\n区间: {tech['fvg_gap']}")
                    with q2: st.warning(f"**MACD 与动量**\n\nMACD: {tech['macd']:.3f}\n\n波动率: {tech['volatility']:.2f}%")
                    with q3: st.error(f"**压力防线**\n\n强压力位: {tech['resistance']:.2f}\n\n年化波幅参考")

                    st.line_chart(df_kline.set_index("date")["close"])
                    
                    with st.spinner("🧠 Agent 正在综合技术指标与 TrendIQ 策略生成报告..."):
                        # 核心提示词：融合 5 大量化框架 + 技术面 + TrendIQ 实战
                        prompt = f"""
作为顶级私募量化经理，请基于资产 {name}({symbol_input}) 的数据生成【TrendIQ 级实战指令】。
数据流：现价 {price}, 涨幅 {pct}%, RSI {tech['rsi']:.1f}, MACD {tech['macd']:.3f}, MA20 {tech['ma20']:.2f}。
支撑/压力：{tech['support']} / {tech['resistance']}。FVG状态: {tech['fvg_status']} ({tech['fvg_gap']})。

请严格按以下维度输出（禁废话）：
1. 🤖 **GenAI 与 DRL 叙事推演**：结合当前动量因子与 RSI，模拟深度强化学习的奖励函数，判断当前是“奖励区”还是“惩罚区”？
2. ⚙️ **自适应因子与风险平价**：基于 {tech['volatility']}% 的波动率，给出 ML 风险平价下的仓位权重建议。
3. 🌐 **Alternative Data 替代数据融合**：假设当前社交媒体情绪与板块资金流向共振，分析背后的庄家意图。
4. 📍 **技术面深度分析 (MA/MACD/FVG)**：解读当前价格与 MA20 的关系，FVG 缺口是否会引发回补？
5. 🎯 **TrendIQ 实战买卖建议**：
   - 【行动判定】: [Buy / Sell / Hold]
   - 【最佳买入/入场位】: [结合支撑位给出具体数字]
   - 【目标止盈位】: [结合压力位与FVG给出具体数字]
   - 【绝对止损位】: [给出具体防守数字]
"""
                        st.markdown(call_ai(prompt))

# ----------------- Tab 2: 宏观推演 (原版保留) -----------------
with tab2:
    with st.container(border=True):
        st.markdown("#### 📊 全盘系统级推演")
        if st.button("运行大盘沙盘推演", type="primary"):
            prompt = f"你现在是高盛首席策略师。基于数据 {str(pulse_data)}，输出全景定调、外资意愿和短期推演。"
            st.markdown(call_ai(prompt, temperature=0.4))

# ----------------- Tab 3: 热点板块 (原版保留) -----------------
with tab3:
    with st.container(border=True):
        st.markdown("#### 🔥 当日主力资金狂欢地 (Top 10)")
        if st.button("扫描今日热点板块", type="primary"):
            blocks = get_hot_blocks()
            if blocks:
                st.dataframe(pd.DataFrame(blocks), use_container_width=True, hide_index=True)
                blocks_str = "\n".join([f"{b['板块名称']} (涨幅:{b['涨跌幅']}%, 领涨:{b['领涨股票']})" for b in blocks[:5]])
                prompt = f"解读今日最强板块逻辑、行情定性和低位延展建议：\n{blocks_str}"
                st.markdown(call_ai(prompt, temperature=0.4))

# ----------------- Tab 4: 情报终端 (原版保留) -----------------
with tab4:
    st.markdown("#### 📡 机构级事件图谱 (卡片式适配)")
    if st.button("🚨 截获并解析全球突发", type="primary"):
        global_news = get_global_news()
        if global_news:
            prompt = f"作为宏观情报官，提取5-8条炸裂性动态（关注彭博/特朗普/马斯克/美联储），禁止表格，使用卡片格式输出：\n{chr(10).join(global_news)}"
            st.markdown(call_ai(prompt, temperature=0.1))
