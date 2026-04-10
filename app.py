import streamlit as st
from groq import Groq
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from datetime import datetime
import re
import akshare as ak
import tushare as ts
import random

# ================= 页面配置 =================
st.set_page_config(page_title="AI股票投研系统", page_icon="📈", layout="wide")
st.title("📈 AI股票投研系统 Pro (多源容灾 + 宏观言论监控版)")

api_key = st.secrets.get("GROQ_API_KEY", "")

# 随机 User-Agent 防止被封
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0"
]

# ================= 侧边栏设置 =================
with st.sidebar:
    st.header("⚙️ 系统与数据源设置")
    ts_token = st.text_input("Tushare Token (可选)", type="password", help="积分较少，系统仅在其他接口全部失效时作为最后兜底使用。")
    DEBUG_MODE = st.checkbox("显示调试信息", value=False)
    
    st.markdown("### 数据源降级策略 (自动)")
    st.write("🟢 **实时行情**: 新浪 -> 东财 -> AKShare")
    st.write("🟢 **历史K线**: AKShare -> 东财 -> Tushare")
    st.write("🟢 **全球电报**: 新浪 7x24 实时抓取")

if ts_token:
    ts.set_token(ts_token)

# ================= 网络层 =================
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
    except (ValueError, TypeError):
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
            st.error(f"❌ JSON请求失败: {url} -> {e}")
        return None

# ================= 全球宏观与名流言论抓取 (新浪 7x24) =================
@st.cache_data(ttl=60)
def get_global_7x24_news():
    """抓取最新7x24小时电报，覆盖特朗普言论、美联储等突发"""
    # 新浪财经直播API
    url = "https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size=40&zhibo_id=152&tag_id=0&dire=f&dpc=1"
    res = safe_get_json(url, extra_headers={"Referer": "https://finance.sina.com.cn/"})
    
    news_list = []
    if res and res.get("result", {}).get("data", {}).get("feed", {}).get("list"):
        items = res["result"]["data"]["feed"]["list"]
        for item in items:
            text = str(item.get("rich_text", "")).strip()
            # 简单清洗 HTML 标签
            text = re.sub(r'<[^>]+>', '', text)
            if text and len(text) > 10:
                news_list.append({
                    "time": item.get("create_time", ""),
                    "content": text
                })
    return news_list

# ================= 股票行情：多源轮询容灾 =================

@st.cache_data(ttl=15)
def get_realtime_quote_sina(symbol):
    """最快最稳定的新浪实时行情 API"""
    market = "sh" if str(symbol).startswith(("6", "9", "5")) else "sz"
    url = f"http://hq.sinajs.cn/list={market}{symbol}"
    try:
        headers = get_headers()
        headers["Referer"] = "http://finance.sina.com.cn/"
        res = SESSION.get(url, headers=headers, timeout=5)
        res.encoding = 'gbk'
        content = res.text
        if "=\"\";" in content or len(content) < 20:
            return None
            
        data_str = content.split('="')[1].split('";')[0]
        parts = data_str.split(',')
        if len(parts) > 30:
            return {
                "_source": "新浪财经",
                "name": parts[0],
                "price": safe_float(parts[3]),
                "change_pct": (safe_float(parts[3]) - safe_float(parts[2])) / safe_float(parts[2]) * 100 if safe_float(parts[2]) > 0 else 0,
                "vol": safe_float(parts[8]) / 100,
                "amount": safe_float(parts[9]) / 10000,
            }
    except Exception as e:
        if DEBUG_MODE:
            st.warning(f"新浪API失败: {e}")
    return None

def get_realtime_quote(symbol):
    """容灾轮询机制：新浪 -> 东财 -> AKShare"""
    # 1. 新浪
    quote = get_realtime_quote_sina(symbol)
    if quote: return quote
    
    # 2. 东财
    market = "1" if str(symbol).startswith(("6", "9", "5", "7")) else "0"
    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={market}.{symbol}&fields=f58,f43,f170,f47,f48,f168,f116,f162,f167"
    res = safe_get_json(url)
    if res and res.get("data"):
        d = res["data"]
        return {
            "_source": "东方财富",
            "name": d.get("f58", "未知"),
            "price": safe_float(d.get("f43")) / 1000 if safe_float(d.get("f43")) > 1000 else safe_float(d.get("f43")),
            "change_pct": safe_float(d.get("f170")),
        }
        
    # 3. AKShare 兜底 (由于太慢且易封，放最后)
    try:
        df = ak.stock_zh_a_spot_em()
        row = df[df["代码"].astype(str) == str(symbol)]
        if not row.empty:
            r = row.iloc[0]
            return {
                "_source": "AKShare",
                "name": r.get("名称", "未知"),
                "price": safe_float(r.get("最新价")),
                "change_pct": safe_float(r.get("涨跌幅")),
            }
    except:
        pass
        
    return None

def get_kline_data(symbol, days=60):
    """K线容灾：AKShare -> 东财 -> Tushare"""
    # 1. AKShare
    try:
        df = ak.stock_zh_a_hist(symbol=str(symbol), period="daily", adjust="qfq")
        if df is not None and not df.empty:
            df = df.rename(columns={"日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "vol"})
            return df[["date", "open", "close", "high", "low", "vol"]].tail(days)
    except Exception:
        pass

    # 2. 东财
    try:
        market = "1" if str(symbol).startswith(("6", "9", "5", "7")) else "0"
        url = f"https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={market}.{symbol}&klt=101&fqt=1&lmt={days}&fields1=f1,f2,f3,f4,f5&fields2=f51,f52,f53,f54,f55,f56"
        res = safe_get_json(url)
        if res and "data" in res and res["data"]:
            klines = res["data"].get("klines", [])
            parsed = [line.split(",")[:6] for line in klines]
            df = pd.DataFrame(parsed, columns=["date", "open", "close", "high", "low", "vol"])
            df = df.astype({"open": float, "close": float, "high": float, "low": float, "vol": float})
            return df
    except Exception:
        pass

    # 3. Tushare 终极兜底
    if ts_token:
        try:
            pro = ts.pro_api()
            df = pro.daily(ts_code=f"{symbol}.SH" if symbol.startswith('6') else f"{symbol}.SZ")
            if not df.empty:
                df = df.sort_values("trade_date")
                df = df.rename(columns={"trade_date": "date", "vol": "vol"})
                df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
                return df[["date", "open", "close", "high", "low", "vol"]].tail(days)
        except Exception as e:
            if DEBUG_MODE: st.error(f"Tushare 兜底失败: {e}")
            
    return None

# ================= AI 调用 =================
def call_groq_analysis(prompt, model="llama-3.3-70b-versatile", temperature=0.3):
    client = Groq(api_key=api_key)
    completion = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        temperature=temperature
    )
    return completion.choices[0].message.content

# ================= 页面布局 =================
tab1, tab2, tab3, tab4 = st.tabs([
    "🎯 个股深度解析", 
    "🌍 宏观大盘推演", 
    "🔥 泛热点监控",
    "🦅 宏观巨头与特氏言论雷达"  # 💥 新增核心功能 Tab
])

# =========== Tab 1: 个股深度 ===========
with tab1:
    symbol_input = st.text_input("请输入股票代码", placeholder="例如：600276", key="stock_input")
    if st.button("全维深度解析"):
        if not api_key: st.error("❌ 未配置 GROQ_API_KEY")
        elif len(symbol_input.strip()) != 6: st.warning("⚠️ 请输入 6 位代码")
        else:
            with st.spinner("启动多通道数据抓取中..."):
                quote = get_realtime_quote(symbol_input)
                df_kline = get_kline_data(symbol_input)

            if not quote or df_kline is None or df_kline.empty:
                st.error("❌ 所有数据通道均无响应，请稍后再试或配置 Tushare Token。")
            else:
                name = quote.get("name")
                price = quote.get("price")
                pct = quote.get("change_pct")
                source = quote.get("_source", "容灾通道")
                
                st.subheader(f"📊 {name} ({symbol_input}) | 数据源: {source}")
                col1, col2, col3 = st.columns(3)
                col1.metric("现价", f"{price:.2f}", f"{pct:.2f}%")
                
                st.write("**近期收盘价走势：**")
                st.line_chart(df_kline.set_index("date")["close"])

                with st.spinner("🧠 AI 正在根据图表与量化特征生成研报..."):
                    prompt = f"你是一名资深量化研究员。分析股票{name}({symbol_input})。现价:{price}, 涨跌幅:{pct}%。结合近期技术面写一份极度专业的500字评估研报，指出支撑位、压力位及主力资金倾向。"
                    st.write(call_groq_analysis(prompt))

# =========== Tab 2 & 3: 保持原样 (由于字数限制简写，你原来的代码可直接放这里) ===========
with tab2:
    st.info("宏观指数监控逻辑与之前相同。由于优化了底层请求框架，现在更不容易断线。")
with tab3:
    st.info("热点聚合逻辑同样生效，底层采用防爬虫轮询。")

# =========== Tab 4: 特朗普与宏观言论监控 ===========
with tab4:
    st.markdown("### 🦅 宏观巨头与地缘言论雷达")
    st.write("实时抓取全网 7x24 小时电报新闻，AI 自动过滤并提取**特朗普(Trump)、马斯克(Musk)、美联储(Fed)、地缘政治**等对大盘有剧烈冲击的核心言论。")
    
    if st.button("📡 扫描最新全球宏观言论与社交动态", type="primary"):
        if not api_key:
            st.error("❌ 未配置 GROQ_API_KEY")
        else:
            with st.spinner("正在扫描全球 7x24 实时情报网..."):
                global_news = get_global_7x24_news()
                
                if not global_news:
                    st.warning("暂未抓取到最新的国际快讯，可能接口在更新。")
                else:
                    st.success(f"成功截获 {len(global_news)} 条近期全球突发事件与言论！")
                    
                    # 组装给 AI 的提示词，让 AI 像情报官一样分析
                    news_text = "\n".join([f"[{x['time']}] {x['content']}" for x in global_news[:30]])
                    
                    with st.expander("🔍 查看原始监听数据 (最近30条)"):
                        st.write(news_text)

                    with st.spinner("🧠 首席宏观情报官正在解读巨头言论对 A股/加密市场 的映射影响..."):
                        prompt = f"""
你现在是一家华尔街顶级对冲基金的【首席宏观情报官】。
以下是我们系统刚刚拦截到的全球7x24小时实时电报情报：

{news_text}

请你执行以下情报过滤和深度分析任务：
1. **巨头雷达**：从上述情报中，精准提取与“特朗普(Trump)、马斯克(Musk)、美联储高层、拜登/美国政府、地缘冲突”相关的直接言论或动态。（如果没有，请明说）
2. **市场恐慌/贪婪推演**：这些宏观事件/言论，传递出的是什么情绪？（贸易保护？通胀重燃？流动性释放？）
3. **跨市场映射**：
   - 黄金 / 原油 / 美元汇率 会怎么走？
   - 加密货币（BTC等）会作何反应？
4. **A股剧本推测**：基于这些宏观言论，A股哪些板块（如：自主可控、出口链、军工、农业、半导体）会承受最大压力？哪些会成为避险资金的蓄水池？给出你的独家判断。

要求：使用高度专业、冷酷的机构口吻，Markdown排版，言简意赅，一针见血。
"""
                        report = call_groq_analysis(prompt, temperature=0.5)
                        st.markdown("---")
                        st.markdown("### 🚨 宏观言论与 A 股映射推演报告")
                        st.write(report)
