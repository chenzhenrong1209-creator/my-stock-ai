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

# 注入金融风自定义 CSS，优化移动端显示
st.markdown("""
    <style>
    .stTabs [data-baseweb="tab-list"] {
        gap: 10px;
        flex-wrap: wrap; /* 允许在手机端换行 */
    }
    .stTabs [data-baseweb="tab"] {
        height: auto;
        min-height: 40px;
        white-space: normal; /* 允许文字换行 */
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
    /* 优化手机端指标卡片间距 */
    [data-testid="stMetricValue"] {
        font-size: 1.5rem; 
    }
    </style>
""", unsafe_allow_html=True)

st.title("🏦 AI 智能量化投研终端")
st.markdown(f"<div class='terminal-header'>TERMINAL BUILD v4.1.0 | SYS_TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | MOBILE OPTIMIZED</div>", unsafe_allow_html=True)

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

if ts_token:
    ts.set_token(ts_token)

# ================= 网络底座 (强力抗封) =================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:115.0) Gecko/20100101 Firefox/115.0",
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36" # 增加移动端UA
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
    """获取宏观三大指数及外汇"""
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
    """获取当天涨幅最猛的热门板块 (被复活的核心功能)"""
    try:
        df = ak.stock_board_industry_name_em()
        if df is not None and not df.empty:
            top_blocks = df.sort_values(by="涨跌幅", ascending=False).head(10)
            return top_blocks[["板块名称", "涨跌幅", "上涨家数", "下跌家数", "领涨股票"]].to_dict('records')
    except: pass
    return None

def get_stock_quote(symbol):
    """个股行情获取"""
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


# ================= 终端全局看板 (适配移动端折行) =================
st.markdown("### 🌍 宏观市场实时看板")
pulse_data = get_market_pulse()
if pulse_data:
    # 手机端自动换行，不再固定列宽
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

# ================= 终端功能选项卡 (恢复为 4 个 Tab) =================
tab1, tab2, tab3, tab4 = st.tabs([
    "🎯 I. 个股标的解析", 
    "📈 II. 宏观大盘推演", 
    "🔥 III. 资金热点板块",
    "🦅 IV. 高阶情报终端"
])

# ----------------- Tab 1: 个股解析 -----------------
with tab1:
    with st.container(border=True):
        st.markdown("#### 🔎 个股雷达锁定")
        col1, col2 = st.columns([1, 1]) # 手机端自适应更好
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
                    st.markdown("---")
                    name, price, pct = quote["name"], quote["price"], quote["pct"]
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric(f"{name}", f"{price:.2f}", f"{pct:.2f}%")
                    c2.metric("总市值(亿)", f"{quote['market_cap']:.1f}")
                    c3.metric("动态PE", f"{quote['pe']}")
                    c4.metric("换手率", f"{quote['turnover']:.2f}%")
                    
                    st.line_chart(df_kline.set_index("date")["close"] if df_kline is not None else [])
                    
                    with st.spinner("🧠 首席策略官撰写资产评估报告..."):
                        prompt = f"""
                        作为顶级私募经理，基于资产 {name}({symbol_input}) 的最新状态：现价: {price}, 涨幅: {pct}%, 市值: {quote['market_cap']}亿, 换手: {quote['turnover']}%。
                        请输出专业量化分析：1.基本面与估值诊断。2.资金意图预判。3.支撑/阻力操作建议。
                        """
                        st.markdown(call_ai(prompt))

# ----------------- Tab 2: 宏观大盘推演 -----------------
with tab2:
    with st.container(border=True):
        st.markdown("#### 📊 全盘系统级推演")
        st.write("结合全局宏观看板与近期市场结构，进行大局观研判。")
        if st.button("运行大盘沙盘推演", type="primary"):
            if not api_key: st.error("配置缺失: GROQ_API_KEY")
            else:
                with st.spinner("推演引擎初始化..."):
                    prompt = f"""
                    你现在是高盛首席宏观策略师。请基于当前A股与外汇的精准数据进行大局观推演：
                    实时数据：{str(pulse_data)}
                    请输出：1. 市场全景定调（分化还是普涨）。2. 北向资金意愿推断（基于汇率）。3. 短期沙盘推演方向。
                    """
                    st.markdown(call_ai(prompt, temperature=0.4))

# ----------------- Tab 3: 热点资金板块 (满血复活) -----------------
with tab3:
    with st.container(border=True):
        st.markdown("#### 🔥 当日主力资金狂欢地 (Top 10)")
        st.write("追踪全天涨幅最猛的行业板块，揪出领涨龙头，识别主线题材。")
        
        if st.button("扫描今日热点板块", type="primary"):
            if not api_key: st.error("配置缺失: GROQ_API_KEY")
            else:
                with st.spinner("深潜获取东方财富板块异动数据..."):
                    blocks = get_hot_blocks()
                    if blocks:
                        df_blocks = pd.DataFrame(blocks)
                        # 手机端友好的表格展示
                        st.dataframe(df_blocks, use_container_width=True, hide_index=True)
                        
                        with st.spinner("🧠 首席游资操盘手拆解底层逻辑..."):
                            blocks_str = "\n".join([f"{b['板块名称']} (涨幅:{b['涨跌幅']}%, 领涨:{b['领涨股票']})" for b in blocks[:5]])
                            prompt = f"""
                            作为顶级游资操盘手，请解读今日最强的5个板块：
                            {blocks_str}
                            请输出：
                            1. 【核心驱动】领涨板块背后的底层逻辑或政策利好是什么？
                            2. 【行情定性】这是“一日游”情绪宣泄，还是具备中线潜力的“主线行情”？
                            3. 【低位延展】散户不能盲目追高，请推荐 1-2 个可能被资金轮动到的低位关联延伸概念。
                            """
                            st.markdown(call_ai(prompt, temperature=0.4))
                    else:
                        st.error("获取板块数据失败，接口可能正处于熔断保护期。")

# ----------------- Tab 4: 高阶情报终端 (移动端卡片式重构) -----------------
with tab4:
    st.markdown("#### 📡 机构级事件图谱与智能评级矩阵")
    st.write("追踪彭博、推特、美联储、特朗普等宏观变量。**已深度适配移动端，告别表格左右滑动烦恼！**")
    
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

                    with st.spinner("🧠 情报官正在生成自适应移动端的情报卡片..."):
                        # 终极提示词修改：强力禁止 Markdown 表格，改用卡片排版
                        prompt = f"""
你现在是华尔街对冲基金的【首席地缘与宏观情报官】。
我截获了全球金融市场的底层快讯流。请你挑选出最具爆炸性和市场影响力的 5-8 条动态。

重点寻猎靶标：彭博社(Bloomberg)、推特(X)、特朗普(Trump)、马斯克(Musk)、美联储。

⚠️【排版严令：禁止使用 Markdown 表格】⚠️
为了适配我的手机端屏幕，你绝对不能使用表格！必须为每一个事件生成一个独立的“信息卡片”，格式如下：

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
