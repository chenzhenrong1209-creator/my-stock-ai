import streamlit as st
from groq import Groq
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from datetime import datetime
import re

# ================= 页面配置 =================
st.set_page_config(page_title="AI股票投研系统", page_icon="📈", layout="wide")
st.title("📈 AI 股票投研系统 Pro（宏观 / 北向资金 / 热点监控）")

api_key = st.secrets.get("GROQ_API_KEY", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# ================= 调试开关 =================
with st.sidebar:
    st.header("⚙️ 系统设置")
    DEBUG_MODE = st.checkbox("显示调试信息", value=True)
    st.caption("打开后会显示接口原始返回和错误信息，便于排查云端数据源问题。")

# ================= 网络层优化 =================
@st.cache_resource
def get_session():
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.8,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(HEADERS)
    return session

SESSION = get_session()

def safe_float(val, default=0.0):
    if val is None or val == '-' or str(val).strip() == '':
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

def debug_show(title, obj):
    if DEBUG_MODE:
        with st.expander(f"🔍 调试信息：{title}", expanded=False):
            st.write(obj)

def safe_get_json(url, timeout=8):
    try:
        res = SESSION.get(url, timeout=timeout)
        res.raise_for_status()
        data = res.json()
        if DEBUG_MODE:
            debug_show("JSON 请求成功", {
                "url": url,
                "status_code": res.status_code,
                "data_preview": data if isinstance(data, dict) else str(data)[:1000]
            })
        return data
    except Exception as e:
        st.error(f"❌ 请求失败\nURL: {url}\n错误: {e}")
        return None

def safe_get_text(url, timeout=8):
    try:
        res = SESSION.get(url, timeout=timeout)
        res.raise_for_status()
        if DEBUG_MODE:
            debug_show("TEXT 请求成功", {
                "url": url,
                "status_code": res.status_code,
                "text_preview": res.text[:1500]
            })
        return res.text
    except Exception as e:
        st.error(f"❌ 文本请求失败\nURL: {url}\n错误: {e}")
        return None

# ================= 工具函数 =================
def get_market_code(symbol):
    symbol = str(symbol).strip()
    if symbol.startswith(('6', '9', '5', '7')):
        return "1"
    return "0"

def normalize_news_item(title, source, url="", summary="", ts=""):
    return {
        "title": str(title).strip(),
        "source": str(source).strip(),
        "url": str(url).strip(),
        "summary": str(summary).strip(),
        "timestamp": str(ts).strip()
    }

def deduplicate_news_items(news_list):
    seen = set()
    result = []
    for item in news_list:
        key = re.sub(r"\s+", "", item["title"]).lower()
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result[:80]

# ================= 行情 / K线 / 汇率 =================
@st.cache_data(ttl=30)
def get_realtime_quote(symbol_or_secid):
    symbol = str(symbol_or_secid).strip()
    if "." in symbol:
        secid = symbol
    else:
        market = get_market_code(symbol)
        secid = f"{market}.{symbol}"

    url = (
        f"https://push2.eastmoney.com/api/qt/stock/get?"
        f"secid={secid}&ut=fa5fd1943c7b386f172d6893dbfba10b&fltt=2&invt=2"
        f"&fields=f57,f58,f43,f170,f169,f47,f48,f60,f44,f45,f46,f168,f116,f162,f167"
    )
    res = safe_get_json(url)
    if DEBUG_MODE:
        debug_show("实时行情原始返回", res)

    if res and res.get("data"):
        return res["data"]
    return None

@st.cache_data(ttl=300)
def get_forex_data():
    url = (
        "https://push2.eastmoney.com/api/qt/stock/get?"
        "secid=133.USDCNH&ut=fa5fd1943c7b386f172d6893dbfba10b&fltt=2&fields=f43,f170"
    )
    res = safe_get_json(url)
    if DEBUG_MODE:
        debug_show("汇率原始返回", res)

    if res and res.get("data"):
        return safe_float(res["data"].get("f43")), safe_float(res["data"].get("f170"))
    return None, None

@st.cache_data(ttl=300)
def get_kline_data(symbol_or_secid, days=60):
    symbol = str(symbol_or_secid).strip()
    if "." in symbol:
        secid = symbol
    else:
        market = get_market_code(symbol)
        secid = f"{market}.{symbol}"

    url = (
        f"https://push2his.eastmoney.com/api/qt/stock/kline/get?"
        f"secid={secid}&klt=101&fqt=1&lmt={days}&end=20500101&iscca=1"
        f"&fields1=f1,f2,f3,f4,f5&fields2=f51,f52,f53,f54,f55,f56,f57"
    )
    res = safe_get_json(url)
    if DEBUG_MODE:
        debug_show("K线原始返回", res)

    if not res or "data" not in res or not res["data"]:
        return None

    klines = res["data"].get("klines", [])
    if not klines:
        return None

    parsed = [line.split(",")[:6] for line in klines]
    df = pd.DataFrame(parsed, columns=["date", "open", "close", "high", "low", "vol"])
    df = df[df["close"] != "-"]
    df.replace("-", "0", inplace=True)
    df = df.astype({"open": float, "close": float, "high": float, "low": float, "vol": float})
    return df

# ================= 基础新闻 =================
@st.cache_data(ttl=300)
def get_aggregated_news():
    url = "https://np-anotice-stock.eastmoney.com/api/security/ann?page_size=8&page_index=1&ann_type=A"
    res = safe_get_json(url)
    if not res:
        return []

    news_list = res.get("data", {}).get("list", [])
    result = []
    for item in news_list:
        result.append(
            normalize_news_item(
                title=item.get("title", ""),
                source="东财公告",
                summary=item.get("title", "")
            )
        )
    return result

# ================= 热点聚合：stock-news.ws4.cn =================
@st.cache_data(ttl=600)
def get_ws4_hotspots():
    url = "https://stock-news.ws4.cn"
    html = safe_get_text(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)

    lines = [x.strip() for x in text.split("\n") if x.strip()]
    hotspot_candidates = []
    start = False
    for line in lines:
        if "热点排行榜" in line:
            start = True
            continue
        if start:
            if len(line) > 5 and len(line) < 80 and "K值" not in line and "热度" not in line:
                hotspot_candidates.append(line)
            if len(hotspot_candidates) >= 20:
                break

    result = []
    for title in hotspot_candidates:
        result.append(
            normalize_news_item(
                title=title,
                source="stock-news.ws4.cn",
                summary="A股热点流量聚合"
            )
        )
    return result

# ================= 多平台热点监控（可插拔） =================
@st.cache_data(ttl=600)
def get_hotspot_news_multi_source():
    all_items = []

    # 1) 基础源
    all_items.extend(get_aggregated_news())

    # 2) 聚合热点源
    all_items.extend(get_ws4_hotspots())

    # 3) 平台占位
    platform_keywords = [
        "百度热搜", "微博热搜", "东方财富", "财联社", "抖音热点", "B站热点",
        "雪球", "同花顺", "第一财经", "证券时报", "上证报", "中证报",
        "腾讯新闻财经", "新浪财经", "网易财经", "今日头条财经",
        "知乎热榜", "快手热点", "小红书财经", "界面新闻"
    ]

    for kw in platform_keywords:
        all_items.append(
            normalize_news_item(
                title=f"{kw} 监控中",
                source=kw,
                summary=f"{kw} 实时热点监控占位，建议后续接入官方/自有中间层接口"
            )
        )

    return deduplicate_news_items(all_items)

# ================= AI 分析 =================
def call_groq_analysis(prompt, model="llama-3.3-70b-versatile", temperature=0.3):
    client = Groq(api_key=api_key)
    completion = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        temperature=temperature
    )
    return completion.choices[0].message.content

def build_hotspot_report_prompt(news_items):
    text_block = "\n".join([f"- [{x['source']}] {x['title']} | {x['summary']}" for x in news_items[:40]])

    return f"""
你是一家顶级A股私募的“热点事件映射分析师 + 板块策略分析师 + 风险官”。

以下是最近抓取的多平台热点样本（可能来自：百度、微博、东财、财联社、抖音、B站等聚合/监控源）：

{text_block}

请输出一份《A股热点影响监测报告》，必须包含以下内容：

1. 今日最强热点主线（按重要性排序列出 5 条）
2. 每条热点对应的：
   - 受益板块
   - 受压板块
   - 可能受影响的A股个股（每条给 3~5 只）
   - 影响逻辑
   - 持续性判断（短线/波段/中期）
3. 哪些热点更可能只是情绪炒作，哪些可能演化成产业趋势
4. 结合A股风格，给出：
   - 最值得盯盘的 3 个板块
   - 最值得跟踪的 5 只股票
5. 风险提示：
   - 追高风险
   - 消息证伪风险
   - 一日游题材风险
   - 大盘风格不匹配风险

要求：
- 语言极其专业、简洁、机构化
- 直接输出 Markdown 报告
- 明确区分“高确定性”和“高情绪性”热点
"""

# ================= 页面布局 =================
tab1, tab2, tab3 = st.tabs([
    "🎯 个股全维解析（含政策与外资）",
    "🌍 宏观大盘与多智能体研判",
    "🔥 20平台热点监控与A股映射"
])

# ================= Tab1：个股全维解析 =================
with tab1:
    st.write("深度整合：基本面 + 政策解读 + 美联储宏观影响 + 北向资金偏好。")
    symbol_input = st.text_input("请输入股票代码", placeholder="例如：000001 (平安银行)", key="stock_input")

    if st.button("开始全维深度解析"):
        if not api_key:
            st.error("❌ 未配置 GROQ_API_KEY")
        elif not symbol_input.strip() or len(symbol_input.strip()) != 6:
            st.warning("⚠️ 请输入 6 位 A 股代码")
        else:
            with st.spinner("正在拉取个股基础数据..."):
                quote = get_realtime_quote(symbol_input)
                df_kline = get_kline_data(symbol_input)
                base_news = get_aggregated_news()
                cnh_price, cnh_pct = get_forex_data()

            # 更明确的错误定位
            if quote is None:
                st.error("❌ 实时行情接口没有拿到数据。更可能是云端访问东财接口失败，不一定是股票本身有问题。")
            if df_kline is None or df_kline.empty if df_kline is not None else True:
                st.error("❌ K线接口没有拿到数据。更可能是云端访问东财历史行情接口失败。")

            if quote and df_kline is not None and not df_kline.empty:
                try:
                    name = quote.get("f58", "未知")
                    price = safe_float(quote.get("f43"))
                    change_percent = safe_float(quote.get("f170"))
                    market_cap_raw = safe_float(quote.get("f116"))
                    market_cap = market_cap_raw / 100000000
                    pe_ratio = quote.get("f162", "-")
                    pb_ratio = quote.get("f167", "-")
                    turnover = safe_float(quote.get("f168"))

                    recent_20 = df_kline.tail(20)
                    support_level = recent_20["low"].min()
                    resistance_level = recent_20["high"].max()

                    avg_vol = recent_20["vol"].mean()
                    latest_vol = recent_20.iloc[-1]["vol"]
                    vol_ratio = latest_vol / avg_vol if avg_vol > 0 else 0

                    smart_money_signal = "无明显异常"
                    if vol_ratio > 2.0 and change_percent > 3.0:
                        smart_money_signal = "放量大涨（疑似主力/游资抢筹）"
                    elif vol_ratio > 2.0 and change_percent < -3.0:
                        smart_money_signal = "放量大跌（主力资金撤离）"

                    st.subheader(f"📊 {name} ({symbol_input}) 实时盘口与基本面")

                    st.markdown("**【核心基本面】**")
                    col_b1, col_b2, col_b3, col_b4 = st.columns(4)
                    col_b1.metric("总市值", f"{market_cap:.2f} 亿")
                    col_b2.metric("动态市盈率 (PE)", f"{pe_ratio}")
                    col_b3.metric("市净率 (PB)", f"{pb_ratio}")
                    col_b4.metric("今日换手率", f"{turnover:.2f}%")

                    st.markdown("**【量化技术面】**")
                    col_t1, col_t2, col_t3, col_t4 = st.columns(4)
                    col_t1.metric("现价", f"{price:.3f}", f"{change_percent:.2f}%")
                    col_t2.metric("资金监控", f"{vol_ratio:.1f}倍量", delta_color="off")
                    col_t3.metric("近期支撑位", f"{support_level:.2f}")
                    col_t4.metric("近期压力位", f"{resistance_level:.2f}")

                    st.write("**近60个交易日收盘价走势：**")
                    st.line_chart(df_kline.set_index("date")["close"])

                    with st.spinner("🧠 AI 正在进行 宏观+政策+北向外资 多维度深度分析..."):
                        cnh_text = f"当前离岸人民币汇率为 {cnh_price}，日内波动 {cnh_pct}%" if cnh_price else "汇率数据暂未获取"
                        base_news_text = "\n".join([f"- {x['title']}" for x in base_news[:8]])

                        prompt = f"""
你是一家顶级私募的首席投研官。请为股票【{name} ({symbol_input})】撰写一份极度专业的全维分析报告。

【数据底座】：
- 基本面：总市值 {market_cap:.2f}亿，PE {pe_ratio}，PB {pb_ratio}。
- 技术面：现价 {price}，涨幅 {change_percent}%，近期支撑 {support_level}，压力 {resistance_level}。
- 资金面异动：{smart_money_signal}。
- 宏观外汇锚定：{cnh_text}。
- 基础新闻样本：
{base_news_text}

请分段输出：
1. 宏观政策与美联储影响
2. 北向资金与汇率共振
3. 基本面估值诊断
4. 实战量化策略
5. 风险提示

要求：语言极其干练，直击要害，体现机构视角。
"""
                        report = call_groq_analysis(prompt)
                        st.markdown("---")
                        st.markdown("### 📝 AI 宏观全维深度研报")
                        st.write(report)

                except Exception as e:
                    st.error(f"❌ 渲染数据时出错：{e}")
            else:
                st.info("ℹ️ 当前应用已经正常运行，但云端数据源没有返回有效股票数据。建议先打开左侧“显示调试信息”，再重试一次查看真实报错。")

# ================= Tab2：宏观多智能体 =================
with tab2:
    st.write("📊 联动核心指数、外汇市场与新闻样本，启动多智能体进行宏观映射分析。")

    if st.button("启动多智能体宏观推演", type="primary"):
        if not api_key:
            st.error("❌ 未配置 GROQ_API_KEY")
        else:
            with st.spinner("正在抓取大盘快照、外汇波动与新闻样本..."):
                indices = {
                    "上证指数": "1.000001",
                    "深证成指": "0.399001",
                    "创业板指": "0.399006",
                    "沪深300": "1.000300"
                }

                index_data_str = ""
                cols = st.columns(5)

                for idx, (index_name, secid) in enumerate(indices.items()):
                    quote = get_realtime_quote(secid)
                    if quote:
                        price = safe_float(quote.get("f43"))
                        pct = safe_float(quote.get("f170"))
                        cols[idx].metric(index_name, f"{price:.2f}", f"{pct:.2f}%")
                        index_data_str += f"{index_name}: {price:.2f} ({pct:.2f}%)\n"
                    else:
                        cols[idx].metric(index_name, "N/A", "N/A")

                cnh_price, cnh_pct = get_forex_data()
                if cnh_price:
                    cols[4].metric("美元/离岸人民币", f"{cnh_price:.4f}", f"{cnh_pct:.2f}%", delta_color="inverse")
                    cnh_text = f"美元/离岸人民币: {cnh_price:.4f} (涨跌幅: {cnh_pct:.2f}%)"
                else:
                    cols[4].metric("美元/离岸人民币", "N/A", "N/A")
                    cnh_text = "汇率数据暂未获取"

                news_items = get_aggregated_news()
                news_text = "\n".join([f"- {x['title']}" for x in news_items])

                with st.expander("📰 实时新闻样本"):
                    st.write(news_text if news_text else "暂无新闻")

            with st.spinner("AI 正在进行宏观联合推演..."):
                try:
                    current_date = datetime.now().strftime("%Y-%m-%d")
                    prompt = f"""
你现在是一个由 6 位顶尖金融专家组成的【量化投研委员会】。今天是 {current_date}。

【大盘快照】：
{index_data_str}

【外汇风向标】：
{cnh_text}

【全网新闻样本】：
{news_text}

请按照以下 6 个专家视角输出研报：
1. 全球宏观分析师
2. 国内政策解读师
3. 跨境资金分析师（重点分析北向资金）
4. 行业映射分析师
5. 优质标的分析师
6. 首席策略官总结

要求：Markdown 输出，极度专业干脆。
"""
                    report = call_groq_analysis(prompt, temperature=0.4)
                    st.markdown("---")
                    st.markdown("### 🧠 投研委员会宏观联合决策报告")
                    st.write(report)
                except Exception as e:
                    st.error(f"❌ 智能体推演失败: {e}")

# ================= Tab3：20平台热点监控 =================
with tab3:
    st.write("实时监控热点聚合源，并由 AI 分析其对 A 股板块与个股的影响。")

    if st.button("启动热点监控与A股映射分析"):
        if not api_key:
            st.error("❌ 未配置 GROQ_API_KEY")
        else:
            with st.spinner("正在抓取多平台热点样本..."):
                hotspot_items = get_hotspot_news_multi_source()

            st.subheader("🔥 热点样本池")
            df_hot = pd.DataFrame(hotspot_items)
            st.dataframe(df_hot, use_container_width=True)

            with st.spinner("🧠 AI 正在进行 热点 → 板块 → 个股 映射分析..."):
                try:
                    prompt = build_hotspot_report_prompt(hotspot_items)
                    report = call_groq_analysis(prompt, temperature=0.35)

                    st.markdown("---")
                    st.markdown("### 📝 A股热点影响监测报告")
                    st.write(report)

                except Exception as e:
                    st.error(f"❌ 热点分析失败：{e}")