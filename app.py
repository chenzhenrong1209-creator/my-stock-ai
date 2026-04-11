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

# ================= 页面配置 =================
st.set_page_config(page_title="AI股票投研系统 Pro Max", page_icon="📈", layout="wide")
st.title("📈 AI股票投研系统 Pro Max (全维监控与智能分级版)")

# 获取 API Key
api_key = st.secrets.get("GROQ_API_KEY", "")

# 随机 User-Agent 库，降低被封锁概率
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:115.0) Gecko/20100101 Firefox/115.0"
]

# ================= 侧边栏设置 =================
with st.sidebar:
    st.header("⚙️ 系统与数据源设置")
    ts_token = st.text_input("Tushare Token (可选)", type="password", help="仅在其他免费接口全部挂掉时作为最后兜底使用。")
    DEBUG_MODE = st.checkbox("显示底层运行日志", value=False)
    st.markdown("### 📡 运行状态")
    st.success("网络容灾模块：在线")
    st.success("多源轮询机制：在线")

if ts_token:
    ts.set_token(ts_token)

# ================= 网络层 (强力容灾) =================
@st.cache_resource
def get_session():
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[403, 429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

SESSION = get_session()

def get_headers():
    return {"User-Agent": random.choice(USER_AGENTS)}

def safe_float(val, default=0.0):
    if val is None or val == "-" or str(val).strip() == "":
        return default
    try:
        return float(val)
    except:
        return default

def safe_get_json(url, timeout=8, extra_headers=None):
    headers = get_headers()
    if extra_headers:
        headers.update(extra_headers)
    try:
        res = SESSION.get(url, headers=headers, timeout=timeout)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        if DEBUG_MODE:
            st.error(f"❌ 请求失败: {url} -> {e}")
        return None

# ================= 数据获取模块 =================

@st.cache_data(ttl=60)
def get_global_7x24_news():
    """抓取全球7x24小时电报 (涵盖彭博、推特转译、外媒突发)"""
    url = "https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size=60&zhibo_id=152&tag_id=0&dire=f&dpc=1"
    res = safe_get_json(url, extra_headers={"Referer": "https://finance.sina.com.cn/"})
    
    news_list = []
    if res and res.get("result", {}).get("data", {}).get("feed", {}).get("list"):
        items = res["result"]["data"]["feed"]["list"]
        for item in items:
            text = str(item.get("rich_text", "")).strip()
            text = re.sub(r'<[^>]+>', '', text) # 清洗 HTML
            if text and len(text) > 15:
                news_list.append(f"[{item.get('create_time', '')}] {text}")
    return news_list

def get_realtime_quote(symbol):
    """个股实时行情轮询: 新浪 -> 东财 -> AKShare"""
    # 1. 新浪
    market = "sh" if str(symbol).startswith(("6", "9", "5")) else "sz"
    url_sina = f"http://hq.sinajs.cn/list={market}{symbol}"
    try:
        headers = get_headers()
        headers["Referer"] = "http://finance.sina.com.cn/"
        res = SESSION.get(url_sina, headers=headers, timeout=5)
        res.encoding = 'gbk'
        content = res.text
        if "=\"\";" not in content and len(content) > 20:
            parts = content.split('="')[1].split('";')[0].split(',')
            if len(parts) > 30:
                return {
                    "_source": "新浪财经",
                    "name": parts[0],
                    "price": safe_float(parts[3]),
                    "change_pct": (safe_float(parts[3]) - safe_float(parts[2])) / safe_float(parts[2]) * 100 if safe_float(parts[2]) > 0 else 0,
                }
    except: pass
    
    # 2. 东财
    market_em = "1" if str(symbol).startswith(("6", "9", "5", "7")) else "0"
    url_em = f"https://push2.eastmoney.com/api/qt/stock/get?secid={market_em}.{symbol}&fields=f58,f43,f170"
    res_em = safe_get_json(url_em)
    if res_em and res_em.get("data"):
        d = res_em["data"]
        p = safe_float(d.get("f43"))
        return {
            "_source": "东方财富",
            "name": d.get("f58", "未知"),
            "price": p / 1000 if p > 1000 else p,
            "change_pct": safe_float(d.get("f170")),
        }
    return None

def get_kline_data(symbol, days=60):
    """个股历史K线轮询"""
    try:
        df = ak.stock_zh_a_hist(symbol=str(symbol), period="daily", adjust="qfq")
        if df is not None and not df.empty:
            df = df.rename(columns={"日期": "date", "收盘": "close"})
            return df[["date", "close"]].tail(days)
    except: pass
    return None

@st.cache_data(ttl=300)
def get_market_indices():
    """获取宏观三大指数 (上证、深证、创业板)"""
    indices = {"上证指数": "1.000001", "深证成指": "0.399001", "创业板指": "0.399006"}
    results = {}
    for name, code in indices.items():
        url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={code}&fields=f43,f170"
        res = safe_get_json(url)
        if res and res.get("data"):
            d = res["data"]
            p = safe_float(d.get("f43"))
            results[name] = {
                "price": p / 100 if p > 10000 else p, # 指数价格修正
                "change_pct": safe_float(d.get("f170"))
            }
    return results

@st.cache_data(ttl=300)
def get_hot_blocks():
    """获取当天涨幅最猛的热门板块"""
    try:
        df = ak.stock_board_industry_name_em()
        if df is not None and not df.empty:
            top_blocks = df.sort_values(by="涨跌幅", ascending=False).head(10)
            return top_blocks[["板块名称", "涨跌幅", "上涨家数", "下跌家数", "领涨股票"]].to_dict('records')
    except: pass
    return None

# ================= AI 模型调用 =================
def call_groq_analysis(prompt, model="llama-3.3-70b-versatile", temperature=0.3):
    try:
        client = Groq(api_key=api_key)
        completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            temperature=temperature
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"❌ AI 调用失败: {str(e)}"

# ================= UI 布局 =================
tab1, tab2, tab3, tab4 = st.tabs([
    "🎯 个股深度解析", 
    "🌍 宏观大盘推演", 
    "🔥 热点板块监控",
    "🦅 全球VIP宏观言论雷达 (智能评级版)"
])

# =========== Tab 1: 个股深度 ===========
with tab1:
    col1, col2 = st.columns([1, 3])
    with col1:
        symbol_input = st.text_input("请输入股票代码", placeholder="例如：600276")
        analyze_btn = st.button("全维深度解析", type="primary")
        
    if analyze_btn:
        if not api_key: st.error("❌ 未配置 GROQ_API_KEY")
        elif len(symbol_input.strip()) != 6: st.warning("⚠️ 请输入 6 位有效代码")
        else:
            with st.spinner("抓取多源数据中..."):
                quote = get_realtime_quote(symbol_input)
                df_kline = get_kline_data(symbol_input)

            if not quote:
                st.error("❌ 数据源无响应，请稍后再试或检查代码是否正确。")
            else:
                name, price, pct = quote.get("name"), quote.get("price"), quote.get("change_pct")
                
                with col2:
                    st.subheader(f"{name} ({symbol_input})")
                    st.metric("现价", f"{price:.2f}", f"{pct:.2f}%")
                
                if df_kline is not None and not df_kline.empty:
                    st.line_chart(df_kline.set_index("date")["close"])

                with st.spinner("🧠 首席AI研究员正在撰写研报..."):
                    prompt = f"""
                    你是一名顶级股票分析师。分析股票 {name} ({symbol_input})。
                    当前价格: {price}, 今日涨跌幅: {pct}%。
                    请结合技术面和市场心理，输出结构化的简明研报：
                    1. 核心支撑位与压力位预判。
                    2. 资金博弈倾向（主力洗盘还是拉升？）。
                    3. 操作建议（轻仓观望/逢低布局等）。
                    """
                    st.markdown(call_groq_analysis(prompt))

# =========== Tab 2: 宏观大盘推演 ===========
with tab2:
    st.markdown("### 📊 A股核心指数实时监控")
    if st.button("更新大盘推演"):
        if not api_key:
            st.error("❌ 未配置 GROQ_API_KEY")
        else:
            with st.spinner("获取指数数据..."):
                indices = get_market_indices()
                if indices:
                    cols = st.columns(3)
                    for idx, (name, data) in enumerate(indices.items()):
                        cols[idx].metric(name, f"{data['price']:.2f}", f"{data['change_pct']:.2f}%")
                    
                    with st.spinner("🧠 AI 大局观推演中..."):
                        indices_str = str(indices)
                        prompt = f"""
                        作为宏观策略师，请基于以下实时的A股三大指数数据进行大势研判：
                        数据：{indices_str}
                        请分析：
                        1. 今日市场整体情绪（普涨、分化、还是普跌？）。
                        2. 资金偏好（是在主板抱团还是在创业板炒作？）。
                        3. 明日宏观大盘可能的剧本演绎。
                        """
                        st.markdown(call_groq_analysis(prompt))
                else:
                    st.error("无法获取指数数据，接口可能受限。")

# =========== Tab 3: 热点板块监控 ===========
with tab3:
    st.markdown("### 🔥 当日主力资金狂欢地 (Top 10)")
    if st.button("扫描今日热点"):
        if not api_key:
            st.error("❌ 未配置 GROQ_API_KEY")
        else:
            with st.spinner("扫描东方财富板块数据..."):
                blocks = get_hot_blocks()
                if blocks:
                    df_blocks = pd.DataFrame(blocks)
                    st.dataframe(df_blocks, use_container_width=True)
                    
                    with st.spinner("🧠 挖掘热点背后的底层逻辑..."):
                        blocks_str = "\n".join([f"{b['板块名称']} (涨幅:{b['涨跌幅']}%, 领涨:{b['领涨股票']})" for b in blocks[:5]])
                        prompt = f"""
                        作为游资操盘手，请解读今日最强的5个板块：
                        {blocks_str}
                        分析：
                        1. 领涨板块的核心驱动事件是什么？
                        2. 这个热点是“一日游”还是“主线行情”？
                        3. 推荐关注的延伸低位概念。
                        """
                        st.markdown(call_groq_analysis(prompt))
                else:
                    st.error("获取板块数据失败，请重试。")

# =========== Tab 4: 全球VIP宏观言论雷达 (评级版) ===========
with tab4:
    st.markdown("### 🦅 智能分级宏观舆情系统")
    st.write("通过分析底层新闻流，AI 将自动锁定 **彭博(Bloomberg)、推特(X)、美联储、特朗普、马斯克** 等核心信源，并划定事件等级。")
    
    if st.button("📡 扫描并生成评级简报", type="primary"):
        if not api_key:
            st.error("❌ 未配置 GROQ_API_KEY")
        else:
            with st.spinner("正在监听全球 7x24 网络并截获情报..."):
                global_news = get_global_7x24_news()
                
                if not global_news:
                    st.warning("暂未抓取到数据，可能触发了反爬策略，请稍后再试。")
                else:
                    # 将情报合成一段文本给大模型
                    news_text = "\n".join(global_news)
                    
                    # 使用 expander 收纳原始数据，不让页面眼花缭乱
                    with st.expander("🔍 查看底层原始监听流 (折叠以保持整洁)"):
                        st.text(news_text)

                    with st.spinner("🧠 首席情报官正在过滤噪音，并进行【核心 / 重要 / 一般】智能定级..."):
                        prompt = f"""
你现在是华尔街顶级投行的首席宏观情报官。我刚刚截获了全球金融市场的海量新闻快讯流。
请你仔细阅读以下快讯，过滤掉无用的噪音，挑出最重要的 5-10 条动态。

重点寻找以下特征的内容：
- **顶级信源**：彭博社(Bloomberg)、路透、推特(X)大V动态。
- **关键人物**：特朗普(Trump)、马斯克(Musk)、美联储官员、大国首脑。
- **宏观事件**：加息/降息、地缘政治冲突、重大加密货币政策。

任务：
请使用严格的 Markdown 表格形式输出你的情报分析结果。不要有多余的废话。
表格的列名必须是：`评级` | `时间` | `信源/人物` | `核心事件精简版` | `对A股或加密市场的潜在影响`

在`评级`列，你必须严格使用以下三种分类，并带上对应的 Emoji：
1. 🔴 **核心**：能立刻引发市场巨震的突发事件、核心人物明确表态。
2. 🟡 **重要**：重要的经济数据公布、投行预测、行业政策。
3. 🔵 **一般**：普通的行业动态、常规公司新闻。

底层情报数据流：
{news_text}
"""
                        report = call_groq_analysis(prompt, temperature=0.1) # 调低温度，让格式更严格
                        st.markdown("---")
                        st.markdown("### 🚨 提纯后的全球高优先级情报矩阵")
                        st.markdown(report)
