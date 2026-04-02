import streamlit as st
from groq import Groq
import pandas as pd
import requests
import json
from datetime import datetime

st.set_page_config(page_title="AI股票投研系统", page_icon="📈", layout="wide")

st.title("📈 AI 股票投研系统 (量化追踪 & 多智能体宏观)")

api_key = st.secrets.get("GROQ_API_KEY", "")

# ================= 核心数据抓取函数 =================
def get_market_code(symbol):
    return "1" if str(symbol).startswith(('6', '9')) else "0"

def get_realtime_quote(symbol):
    market = get_market_code(symbol)
    # 特殊处理指数代码
    if symbol == "000001": market = "1" # 上证指数
    if symbol == "399001": market = "0" # 深证成指
    if symbol == "399006": market = "0" # 创业板指
    if symbol == "000300": market = "1" # 沪深300
    
    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={market}.{symbol}&fields=f57,f58,f43,f170,f169,f47,f48,f60,f44,f45,f46,f168"
    try:
        res = requests.get(url, timeout=5).json()
        return res.get('data')
    except:
        return None

def get_kline_data(symbol, days=60):
    market = get_market_code(symbol)
    url = f"http://push2his.eastmoney.com/api/qt/stock/kline/get?secid={market}.{symbol}&klt=101&fqt=1&lmt={days}&end=20500101&iscca=1&fields1=f1,f2,f3,f4,f5&fields2=f51,f52,f53,f54,f55,f56,f57"
    try:
        res = requests.get(url, timeout=5).json()
        klines = res['data']['klines']
        parsed = [line.split(',')[:6] for line in klines]
        df = pd.DataFrame(parsed, columns=['date', 'open', 'close', 'high', 'low', 'vol'])
        df = df.astype({'open': float, 'close': float, 'high': float, 'low': float, 'vol': float})
        return df
    except:
        return None

def get_aggregated_news():
    """替代20个平台爬虫，直接获取全网聚合财经快讯前10条"""
    # 这里使用东财的滚动资讯接口作为全网情绪平替
    url = "https://np-anotice-stock.eastmoney.com/api/security/ann?page_size=10&page_index=1&ann_type=A"
    try:
        res = requests.get(url, timeout=5).json()
        news_list = res.get('data', {}).get('list', [])
        news_texts = [f"- {item['title']}" for item in news_list]
        return "\n".join(news_texts) if news_texts else "暂无最新消息"
    except:
        return "新闻接口暂时受限，请依赖 AI 自身的宏观时间戳知识。"

# ================= 界面分栏设计 =================
tab1, tab2 = st.tabs(["🎯 个股量化追踪与聪明钱", "🌍 宏观大盘与多智能体研判"])

# ----------------- Tab 1: 个股量化追踪 -----------------
with tab1:
    st.write("集成主力资金异动监控、量化支撑/压力位计算。")
    symbol = st.text_input("请输入股票代码", placeholder="例如：600821 (无需后缀)", key="stock_input")

    if st.button("开始深度量化分析"):
        if not api_key:
            st.error("❌ 未配置 GROQ_API_KEY")
        elif not symbol.strip() or len(symbol.strip()) != 6:
            st.warning("⚠️ 请输入 6 位 A 股代码")
        else:
            with st.spinner("正在扫描行情、计算量化指标..."):
                quote = get_realtime_quote(symbol)
                df_kline = get_kline_data(symbol)
                
                if quote and df_kline is not None and not df_kline.empty:
                    name = quote['f58']
                    price = quote['f43'] / 100
                    change_percent = quote['f170'] / 100
                    
                    recent_20 = df_kline.tail(20)
                    support_level = recent_20['low'].min()
                    resistance_level = recent_20['high'].max()
                    
                    avg_vol = recent_20['vol'].mean()
                    latest_vol = recent_20.iloc[-1]['vol']
                    vol_ratio = latest_vol / avg_vol
                    
                    smart_money_signal = "无明显异常"
                    if vol_ratio > 2.0 and change_percent > 3.0:
                        smart_money_signal = "⚠️ 发现强劲资金介入痕迹 (放量大涨，疑似游资建仓)"
                    elif vol_ratio > 2.0 and change_percent < -3.0:
                        smart_money_signal = "⚠️ 发现主力资金撤离痕迹 (放量大跌)"
                    
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric(f"{name} 现价", f"{price:.2f}", f"{change_percent:.2f}%")
                    c2.metric("资金监控", f"{vol_ratio:.1f}倍量", delta_color="off")
                    c3.metric("近期支撑", f"{support_level:.2f}")
                    c4.metric("近期压力", f"{resistance_level:.2f}")
                    
                    st.write("**近60个交易日收盘价走势：**")
                    df_kline.set_index('date', inplace=True)
                    st.line_chart(df_kline['close'])
                    
                    with st.spinner("Groq 正在生成个股研报..."):
                        try:
                            client = Groq(api_key=api_key)
                            prompt = f"你是量化分析师。股票{name}({symbol})现价{price}，涨幅{change_percent}%。资金流向：{smart_money_signal}。支撑位{support_level}，压力位{resistance_level}。请给出简短的进出场策略。中文回答。"
                            completion = client.chat.completions.create(
                                messages=[{"role": "user", "content": prompt}],
                                model="llama-3.3-70b-versatile"
                            )
                            st.info(completion.choices[0].message.content)
                        except Exception as e:
                            st.error(f"AI 调用失败: {e}")
                else:
                    st.error("❌ 无法获取该股票数据。")

# ----------------- Tab 2: 宏观多智能体研判 -----------------
with tab2:
    st.write("📊 联动核心指数与全网新闻样本，启动 5 大 AI 智能体进行宏观映射分析。")
    
    if st.button("启动多智能体宏观推演", type="primary"):
        if not api_key:
            st.error("❌ 未配置 GROQ_API_KEY")
        else:
            with st.spinner("1. 正在抓取市场快照与全网热点样本..."):
                # 获取四大指数快照
                indices = {
                    "上证指数": "000001",
                    "深证成指": "399001",
                    "创业板指": "399006",
                    "沪深300": "000300"
                }
                index_data_str = ""
                cols = st.columns(4)
                
                for idx, (name, code) in enumerate(indices.items()):
                    quote = get_realtime_quote(code)
                    if quote:
                        price = quote['f43'] / 100
                        pct = quote['f170'] / 100
                        cols[idx].metric(name, f"{price:.2f}", f"{pct:.2f}%")
                        index_data_str += f"{name}: {price:.2f} ({pct:.2f}%)\n"
                
                # 获取新闻快讯
                news_text = get_aggregated_news()
                with st.expander("📰 实时全网热点新闻样本 (已抓取)"):
                    st.write(news_text)

            with st.spinner("2. 唤醒 5 大 AI 智能体进行深度推演与行业映射..."):
                try:
                    current_date = datetime.now().strftime("%Y-%m-%d")
                    client = Groq(api_key=api_key)
                    
                    # 极其强大的 Multi-Agent Prompt
                    multi_agent_prompt = f"""
                    你现在不是一个普通的AI，你是一个由 5 位顶尖金融专家组成的【量化投研委员会】。
                    今天是 {current_date}。请基于以下最新的大盘数据和全网热点新闻，进行联合研判。
                    
                    【大盘快照】：
                    {index_data_str}
                    
                    【全网最新热点样本】：
                    {news_text}
                    
                    请务必按照以下 5 个专家的视角，结构化输出一份极其硬核的研报：
                    
                    1. 🧑‍💼【宏观总量分析师】：结合最新新闻和当前中国经济大背景（如CPI/PPI趋势、降息降准预期），点评宏观基本面。
                    2. 🏦【政策流动性分析师】：分析当前大盘表现（尤其是四大指数的涨跌互现），推测央行或国家队的资金流动性态度。
                    3. 🏭【行业映射分析师】(重点)：基于宏观和新闻，明确指出未来 1-2 个季度【绝对受益】的 2 个板块，以及【面临承压/利空】的 1 个板块，并给出严密逻辑。
                    4. 🎯【优质标的分析师】(重点)：为你刚才看好的板块，分别推荐 1-2 只代表性A股龙头标的（带股票代码），并说明推荐理由。
                    5. 🧙‍♂️【首席策略官总结】：给出一句凝练的市场定调，并制定本周的仓位控制建议（例如：防守反击、全线做多、半仓观望）。
                    
                    排版要求：使用 Markdown，每个专家的发言要有独立标题和 Emoji。语言必须极度专业、干脆，像券商内部密报。
                    """
                    
                    completion = client.chat.completions.create(
                        messages=[{"role": "user", "content": multi_agent_prompt}],
                        model="llama-3.3-70b-versatile",
                        temperature=0.4, # 偏向逻辑推理
                        max_tokens=2048
                    )
                    
                    st.markdown("---")
                    st.markdown("### 🧠 投研委员会联合决策报告")
                    st.write(completion.choices[0].message.content)
                    
                except Exception as e:
                    st.error(f"智能体推演失败: {e}")
