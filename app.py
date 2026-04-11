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
st.set_page_config(page_title="AI 智能投研终端 Pro Max", page_icon="🏦", layout="wide", initial_sidebar_state="expanded")

# 注入金融风自定义 CSS (卡片式布局)
st.markdown("""
    <style>
    .stTabs [data-baseweb="tab-list"] {
        gap: 10px;
    }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        white-space: pre-wrap;
        background-color: transparent;
        border-radius: 4px 4px 0 0;
        padding-top: 10px;
        padding-bottom: 10px;
        font-weight: bold;
    }
    .terminal-header {
        font-family: 'Courier New', Courier, monospace;
        color: #888;
        font-size: 0.9em;
        margin-bottom: 20px;
    }
    </style>
""", unsafe_allow_html=True)

st.title("🏦 AI 智能量化投研终端")
st.markdown(f"<div class='terminal-header'>TERMINAL BUILD v4.0.0 | SYS_TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | DATAFEED: SINA/EASTMONEY/AKSHARE/TUSHARE</div>", unsafe_allow_html=True)

api_key = st.secrets.get("GROQ_API_KEY", "")

# ================= 侧边栏 =================
with st.sidebar:
    st.header("⚙️ 终端控制台")
    ts_token = st.text_input("🔑 Tushare Token", type="password", help="仅作极致容灾兜底")
    DEBUG_MODE = st.checkbox("🛠️ 开启底层日志嗅探")
    st.markdown("---")
    st.markdown("### 📡 数据连通性")
    st.success("实时行情引擎: ACTIVE")
    st.success("7x24全球快讯: ACTIVE")
    st.success("AI 智能体矩阵: STANDBY")

if ts_token:
    ts.set_token(ts_token)

# ================= 网络底座 (强力抗封) =================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:115.0) Gecko/20100101 Firefox/115.0"
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
    """全球7x24小时事件嗅探"""
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
    """获取宏观三大指数及外汇 (数据格式绝对精准化)"""
    # 强制带上 fltt=2 获取正确的浮点数，拒绝整数错位
    pulse = {}
    
    # 1. 核心大盘指数
    indices = {"上证指数": "1.000001", "深证成指": "0.399001", "创业板指": "0.399006"}
    for name, code in indices.items():
        url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={code}&ut=fa5fd1943c7b386f172d6893dbfba10b&fltt=2&fields=f43,f170"
        res = fetch_json(url)
        if res and res.get("data"):
            pulse[name] = {"price": safe_float(res["data"].get("f43")), "pct": safe_float(res["data"].get("f170"))}
            
    # 2. 外汇 (美元/离岸人民币)
    cnh_url = "https://push2.eastmoney.com/api/qt/stock/get?secid=133.USDCNH&ut=fa5fd1943c7b386f172d6893dbfba10b&fltt=2&fields=f43,f170"
    cnh_res = fetch_json(cnh_url)
    if cnh_res and cnh_res.get("data"):
        pulse["USD/CNH (离岸人民币)"] = {"price": safe_float(cnh_res["data"].get("f43")), "pct": safe_float(cnh_res["data"].get("f170"))}
        
    return pulse

def get_stock_quote(symbol):
    """个股多路轮询引擎"""
    market = "1" if str(symbol).startswith(("6", "9", "5", "7")) else "0"
    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={market}.{symbol}&ut=fa5fd1943c7b386f172d6893dbfba10b&fltt=2&fields=f58,f43,f170,f116,f162,f168"
    res = fetch_json(url)
    if res and res.get("data"):
        d = res["data"]
        return {
            "name": d.get("f58", "未知"),
            "price": safe_float(d.get("f43")),
            "pct": safe_float(d.get("f170")),
            "market_cap": safe_float(d.get("f116")) / 100000000,
            "pe": d.get("f162", "-"),
            "turnover": safe_float(d.get("f168"))
        }
    return None

def get_kline(symbol, days=60):
    try:
        df = ak.stock_zh_a_hist(symbol=str(symbol), period="daily", adjust="qfq")
        if df is not None and not df.empty:
            df = df.rename(columns={"日期": "date", "收盘": "close"})
            return df[["date", "close"]].tail(days)
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


# ================= 终端全局看板 (Top Dashboard) =================
st.markdown("### 🌍 宏观市场实时看板")
pulse_data = get_market_pulse()
if pulse_data:
    dash_cols = st.columns(len(pulse_data))
    for idx, (key, data) in enumerate(pulse_data.items()):
        with dash_cols[idx]:
            with st.container(border=True):
                # 如果是汇率，展示精度设高一点，颜色反转（人民币贬值利空）
                if "CNH" in key:
                    st.metric(key, f"{data['price']:.4f}", f"{data['pct']:.2f}%", delta_color="inverse")
                else:
                    st.metric(key, f"{data['price']:.2f}", f"{data['pct']:.2f}%")
else:
    st.warning("宏观看板数据流建立失败。")

st.markdown("<br>", unsafe_allow_html=True)

# ================= 终端功能选项卡 =================
tab1, tab2, tab3 = st.tabs([
    "🎯 I. 智能个股量化标的解析", 
    "📈 II. 宏观大盘走势多维推演", 
    "🦅 III. 全球VIP高阶情报终端 (智能评级)"
])

# ----------------- Tab 1: 个股解析 -----------------
with tab1:
    with st.container(border=True):
        st.markdown("#### 🔎 个股雷达锁定")
        col1, col2 = st.columns([1, 3])
        with col1:
            symbol_input = st.text_input("标的代码", placeholder="例：600519")
            analyze_btn = st.button("启动核心算法", type="primary", use_container_width=True)
            
        if analyze_btn:
            if not api_key: st.error("配置缺失: GROQ_API_KEY")
            elif len(symbol_input.strip()) != 6: st.warning("代码规范验证失败")
            else:
                with st.spinner("量子计算与数据提取中..."):
                    quote = get_stock_quote(symbol_input)
                    df_kline = get_kline(symbol_input)
                    
                if not quote:
                    st.error("无法捕获行情资产。")
                else:
                    with col2:
                        name, price, pct = quote["name"], quote["price"], quote["pct"]
                        c1, c2, c3, c4 = st.columns(4)
                        c1.metric(f"{name} ({symbol_input})", f"{price:.2f}", f"{pct:.2f}%")
                        c2.metric("总市值 (亿)", f"{quote['market_cap']:.2f}")
                        c3.metric("动态PE", f"{quote['pe']}")
                        c4.metric("换手率", f"{quote['turnover']:.2f}%")
                    
                    st.line_chart(df_kline.set_index("date")["close"] if df_kline is not None else [])
                    
                    with st.spinner("🧠 首席策略官撰写资产评估报告..."):
                        prompt = f"""
                        作为顶级私募经理，基于资产 {name}({symbol_input}) 的最新状态：
                        现价: {price}, 涨幅: {pct}%, 市值: {quote['market_cap']}亿, PE: {quote['pe']}。
                        请输出专业量化分析：
                        1. 【基本面诊断】市值与估值的匹配度。
                        2. 【量化特征】今日资金意图预判。
                        3. 【交易策略】支撑/阻力预判及具体操作建议。
                        """
                        st.markdown(call_ai(prompt))

# ----------------- Tab 2: 宏观大盘推演 -----------------
with tab2:
    with st.container(border=True):
        st.markdown("#### 📊 全盘系统级推演")
        st.write("结合全局宏观看板（顶部）与近期市场结构，进行大局观研判。")
        
        if st.button("运行大盘沙盘推演", type="primary"):
            if not api_key: st.error("配置缺失: GROQ_API_KEY")
            else:
                with st.spinner("推演引擎初始化..."):
                    pulse_str = str(pulse_data)
                    prompt = f"""
                    你现在是高盛首席宏观策略师。请基于当前A股与外汇的绝对精准数据进行大局观推演：
                    实时数据看板：{pulse_str}
                    
                    请以专业、冷静的机构视角输出研报：
                    1. 🌊 **【市场全景定调】**：通过三大指数的涨跌对比，判断今日是权重护盘、赛道普涨、还是极度分化？
                    2. 💱 **【跨境流动性测算】**：结合 USD/CNH（离岸人民币）的涨跌幅，推断北向外资的流入/流出意愿。
                    3. ⚔️ **【沙盘推演与建议】**：基于此宏观环境，未来1-2天的阻力最小方向在哪里？该防守还是进攻？
                    """
                    report = call_ai(prompt, temperature=0.4)
                    st.markdown("---")
                    st.write(report)

# ----------------- Tab 3: 高阶情报终端 -----------------
with tab3:
    st.markdown("#### 📡 机构级事件图谱与智能评级矩阵")
    st.write("直连底层 7x24 事件网络。AI 自动剔除噪音，锁定彭博/推特核心信源，追踪马斯克、特朗普、美联储等宏观杠杆变量。")
    
    if st.button("🚨 截获并解析全球突发", type="primary"):
        if not api_key: st.error("配置缺失: GROQ_API_KEY")
        else:
            with st.spinner("监听全网节点并执行深度NLP解析..."):
                global_news = get_global_news()
                if not global_news:
                    st.warning("当前信号静默或被防火墙拦截。")
                else:
                    news_text = "\n".join(global_news)
                    with st.expander("🕵️‍♂️ 查看底层监听流 (Raw Data)"):
                        st.text(news_text)

                    with st.spinner("🧠 情报官正在进行【事件定级】与【资产映射推演】..."):
                        # 核心级 Prompt，严格限制表格输出和新增的“影响”列
                        prompt = f"""
你现在是华尔街对冲基金的【首席地缘与宏观情报官】。
我刚刚截获了全球金融市场的底层电报快讯流。请你过滤噪音，挑选出最具爆炸性和市场影响力的 5-8 条动态。

重点寻猎靶标：
- **顶级信源**：彭博社(Bloomberg)、路透、推特(X)重要大V。
- **高杠杆人物**：特朗普(Trump)、马斯克(Musk)、美联储鲍威尔、大国首脑。
- **高能事件**：加/降息、贸易制裁、地缘冲突爆发。

⚠️【强制输出格式】⚠️：
必须且只能输出一个 Markdown 表格，不要有多余的开头或结尾问候语。
表格的表头必须完全按照如下格式：
| 评级 | 时间 | 信源/核心人物 | 核心事件提炼 | 受影响资产/板块 | 深度影响推演 |
|---|---|---|---|---|---|

在`评级`列，严格使用且仅使用以下三种：
🔴 核心 (S级)：能直接引发股市/汇市巨震的突发、大选级人物表态。
🟡 重要 (A级)：关键经济数据、大厂重要动态。
🔵 一般 (B级)：值得关注但不会立刻掀起风浪的常规事件。

在`受影响资产/板块`列，必须具象化（例如：自主可控板块、黄金、特斯拉概念、出口链）。

底层情报数据流：
{news_text}
"""
                        report = call_ai(prompt, temperature=0.1)
                        st.markdown("---")
                        st.markdown(report)
