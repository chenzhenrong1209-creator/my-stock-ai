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

st.markdown("""
    <style>
    .stTabs [data-baseweb="tab-list"] { gap: 10px; flex-wrap: wrap; }
    .stTabs [data-baseweb="tab"] { height: auto; min-height: 40px; white-space: normal; background-color: transparent; border-radius: 4px 4px 0 0; padding: 8px 12px; font-weight: bold; }
    .terminal-header { font-family: 'Courier New', Courier, monospace; color: #888; font-size: 0.8em; margin-bottom: 20px; word-wrap: break-word; }
    [data-testid="stMetricValue"] { font-size: 1.5rem; }
    </style>
""", unsafe_allow_html=True)

st.title("🏦 AI 智能量化投研终端")
st.markdown(f"<div class='terminal-header'>TERMINAL BUILD v5.0 (AI + DRL + FVG) | SYS_TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>", unsafe_allow_html=True)

api_key = st.secrets.get("GROQ_API_KEY", "")

# ================= 侧边栏 =================
with st.sidebar:
    st.header("⚙️ 终端控制台")
    ts_token = st.text_input("🔑 Tushare Token", type="password", help="仅作极致容灾兜底")
    DEBUG_MODE = st.checkbox("🛠️ 开启底层日志嗅探")
    st.markdown("---")
    st.markdown("### 📡 引擎状态")
    st.success("替代数据融合 (Alt Data): ACTIVE")
    st.success("FVG 量化引擎: ACTIVE")
    st.success("DRL 推理中心: STANDBY")

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
    except Exception as e:
        if DEBUG_MODE: st.error(f"Feed Error: {e}")
        return None

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

@st.cache_data(ttl=300)
def get_hot_blocks():
    try:
        df = ak.stock_board_industry_name_em()
        if df is not None and not df.empty:
            return df.sort_values(by="涨跌幅", ascending=False).head(10)[["板块名称", "涨跌幅", "领涨股票"]].to_dict('records')
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

def get_kline(symbol, days=60):
    try:
        df = ak.stock_zh_a_hist(symbol=str(symbol), period="daily", adjust="qfq")
        if df is not None and not df.empty:
            df = df.rename(columns={"日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "vol"})
            df['open'] = df['open'].astype(float)
            df['close'] = df['close'].astype(float)
            df['high'] = df['high'].astype(float)
            df['low'] = df['low'].astype(float)
            return df.tail(days).reset_index(drop=True)
    except: pass
    return None

# ================= 高阶量化特征提取引擎 (FVG & 因子) =================
def extract_quant_features(df):
    if df is None or len(df) < 20:
        return {"fvg_status": "数据不足", "fvg_gap": "N/A", "volatility": "N/A", "momentum": "N/A"}
    
    # 1. 寻找最近的 FVG (Fair Value Gap) - 三根K线的流动性缺口
    fvg_status = "未检测到近期缺口"
    fvg_gap = "无"
    for i in range(len(df)-1, 1, -1): # 倒序查找最近的缺口
        candle1_high = df.loc[i-2, 'high']
        candle1_low = df.loc[i-2, 'low']
        candle3_high = df.loc[i, 'high']
        candle3_low = df.loc[i, 'low']
        
        if candle1_low > candle3_high: # 看跌缺口 Bearish FVG
            fvg_status = "📉 Bearish FVG (看跌缺口)"
            fvg_gap = f"{candle3_high:.2f} - {candle1_low:.2f}"
            break
        elif candle1_high < candle3_low: # 看涨缺口 Bullish FVG
            fvg_status = "📈 Bullish FVG (看涨缺口)"
            fvg_gap = f"{candle1_high:.2f} - {candle3_low:.2f}"
            break

    # 2. 因子模型：20日波动率 (风险平价因子) 与动量
    returns = df['close'].pct_change()
    volatility_20d = returns.tail(20).std() * np.sqrt(252) * 100 # 年化波动率
    momentum_10d = (df['close'].iloc[-1] / df['close'].iloc[-11] - 1) * 100 if len(df) > 10 else 0
    
    return {
        "fvg_status": fvg_status,
        "fvg_gap": fvg_gap,
        "volatility": f"{volatility_20d:.2f}%",
        "momentum": f"{momentum_10d:.2f}%"
    }

# ================= AI 计算核心 =================
def call_ai(prompt, model="llama-3.3-70b-versatile", temperature=0.3):
    try:
        client = Groq(api_key=api_key)
        completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}], model=model, temperature=temperature
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
                if "CNH" in key: st.metric(key, f"{data['price']:.4f}", f"{data['pct']:.2f}%", delta_color="inverse")
                else: st.metric(key, f"{data['price']:.2f}", f"{data['pct']:.2f}%")

st.markdown("<br>", unsafe_allow_html=True)

# ================= 终端功能选项卡 =================
tab1, tab2, tab3, tab4 = st.tabs([
    "🎯 I. 量化Agent解析 (FVG+DRL)", 
    "📈 II. 宏观大盘推演", 
    "🔥 III. 资金热点板块",
    "🦅 IV. 高阶替代数据终端"
])

# ----------------- Tab 1: 个股解析 -----------------
with tab1:
    with st.container(border=True):
        st.markdown("#### 🔎 Agentic 量化雷达锁定")
        col1, col2 = st.columns([1, 1])
        with col1:
            symbol_input = st.text_input("标的代码", placeholder="例：600519")
            analyze_btn = st.button("启动核心算法", type="primary", use_container_width=True)
            
        if analyze_btn:
            if not api_key: st.error("配置缺失: GROQ_API_KEY")
            elif len(symbol_input.strip()) != 6: st.warning("代码规范验证失败")
            else:
                with st.spinner("提取深度量价特征与 FVG 缺口..."):
                    quote = get_stock_quote(symbol_input)
                    df_kline = get_kline(symbol_input)
                    quant_features = extract_quant_features(df_kline)
                    
                if not quote: st.error("无法捕获行情资产。")
                else:
                    st.markdown("---")
                    name, price, pct = quote["name"], quote["price"], quote["pct"]
                    
                    # 基础信息卡片
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric(f"{name}", f"{price:.2f}", f"{pct:.2f}%")
                    c2.metric("总市值(亿)", f"{quote['market_cap']:.1f}")
                    c3.metric("动态PE", f"{quote['pe']}")
                    c4.metric("换手率", f"{quote['turnover']:.2f}%")
                    
                    # 高阶量化特征卡片
                    st.markdown("##### ⚙️ 核心算法参数映射")
                    q1, q2, q3 = st.columns(3)
                    with q1:
                        st.info(f"**FVG 缺口检测**\n\n{quant_features['fvg_status']}\n\n区间: {quant_features['fvg_gap']}")
                    with q2:
                        st.warning(f"**自适应因子 (动量)**\n\n10日相对动量: {quant_features['momentum']}")
                    with q3:
                        st.error(f"**风险平价基准 (波动)**\n\n20日年化波动率: {quant_features['volatility']}")
                    
                    st.line_chart(df_kline.set_index("date")["close"] if df_kline is not None else [])
                    
                    with st.spinner("🧠 Agent 正在利用 DRL 与大语言框架生成多维策略报告..."):
                        prompt = f"""
你是一名部署在量化对冲基金的【超级投研 Agent】。
目标资产: {name} ({symbol_input})。
实时状态: 现价 {price}, 涨幅 {pct}%, 市值 {quote['market_cap']}亿, PE {quote['pe']}。
【量化特征引擎提取数据】：
- FVG 缺口: {quant_features['fvg_status']} (缺口位置: {quant_features['fvg_gap']})
- 动量因子: {quant_features['momentum']}
- 历史波动率: {quant_features['volatility']}

请基于以上数据，严格按照以下 5 个维度的硬核量化框架，撰写极度专业的分析简报：

1. 🤖 **Generative AI 与大语言模型叙事**：基于当前市场语境，该股票所属题材的“叙事逻辑（Narrative）”是否性感？
2. 🕹️ **DRL (深度强化学习) 奖励函数推演**：假设你在训练一个交易 Agent，基于当前的动量因子和波动率，当前的“Reward (风险收益比)”是正向还是负向？建议 Agent 执行 Hold、Buy 还是 Sell 动作？
3. 🌐 **Alternative Data (替代数据) 融合**：假设结合近期社交媒体情绪或名流言论风向，该板块的潜在流动性如何？
4. ⚙️ **自适应因子模型 (Adaptive Factors)**：当前市场风格是偏向价值、动量还是小盘？结合其PE和动量，因子是否共振？
5. ⚖️ **ML 风险平价 (Risk Parity 2.0) 与 FVG 策略**：结合检测到的 FVG 缺口（流动性失衡区）和波动率（{quant_features['volatility']}），给出具体的仓位控制建议和进出场狙击点。
"""
                        st.markdown(call_ai(prompt))

# ----------------- Tab 2: 宏观大盘推演 -----------------
with tab2:
    with st.container(border=True):
        st.markdown("#### 📊 全盘系统级推演")
        if st.button("运行大盘沙盘推演", type="primary"):
            if not api_key: st.error("配置缺失")
            else:
                with st.spinner("推演引擎初始化..."):
                    prompt = f"基于实时数据：{str(pulse_data)}。请输出：1.市场全景定调。2.北向外资流动性测算(结合汇率)。3.短期演化剧本。"
                    st.markdown(call_ai(prompt, temperature=0.4))

# ----------------- Tab 3: 热点资金板块 -----------------
with tab3:
    with st.container(border=True):
        st.markdown("#### 🔥 当日主力资金狂欢地 (Top 10)")
        if st.button("扫描今日热点板块", type="primary"):
            if not api_key: st.error("配置缺失")
            else:
                with st.spinner("获取底层板块数据..."):
                    blocks = get_hot_blocks()
                    if blocks:
                        st.dataframe(pd.DataFrame(blocks), use_container_width=True, hide_index=True)
                        with st.spinner("🧠 首席游资操盘手拆解逻辑..."):
                            blocks_str = "\n".join([f"{b['板块名称']} (涨幅:{b['涨跌幅']}%, 领涨:{b['领涨股票']})" for b in blocks[:5]])
                            prompt = f"解读今日最强板块：{blocks_str}。输出：1.核心驱动。2.行情定性(一日游还是主线)。3.低位关联概念挖掘。"
                            st.markdown(call_ai(prompt, temperature=0.4))

# ----------------- Tab 4: 高阶情报终端 -----------------
with tab4:
    st.markdown("#### 📡 机构级 Alternative Data (替代数据) 终端")
    st.write("追踪彭博、推特、美联储、特朗普等核心变量。卡片式排版，完美适配移动端。")
    if st.button("🚨 截获并解析全球突发", type="primary"):
        if not api_key: st.error("配置缺失")
        else:
            with st.spinner("执行深度NLP解析..."):
                global_news = get_global_news()
                if global_news:
                    with st.expander("🕵️‍♂️ 查看底层监听流"): st.text("\n".join(global_news))
                    with st.spinner("🧠 提取 Alternative Data 并分级..."):
                        prompt = f"""
作为宏观情报官，过滤以下快讯，提取5-8条炸裂性动态（关注：彭博、推特、特朗普、美联储）。
【禁止使用表格】，必须为每个事件生成独立卡片：

### [评级Emoji] [信源/人物] 事件核心提炼
* ⏰ **时间**: [时间]
* 🎯 **受影响资产**: [如: 黄金、加密货币、出口链]
* 🧠 **深度推演**: [实质影响]
---
评级Emoji要求：🔴 核心，🟡 重要，🔵 一般。
底层数据：
{"\n".join(global_news)}
"""
                        st.markdown(call_ai(prompt, temperature=0.1))
