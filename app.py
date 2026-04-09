import streamlit as st
from groq import Groq
import pandas as pd
import requests
from datetime import datetime

st.set_page_config(page_title="AI股票投研系统", page_icon="📈", layout="wide")

st.title("📈 AI 股票投研系统 (宏观政策与北向资金版)")

api_key = st.secrets.get("GROQ_API_KEY", "")

# ================= 核心数据抓取与清洗 =================
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

def safe_float(val, default=0.0):
    if val is None or val == '-' or str(val).strip() == '':
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

def get_market_code(symbol):
    symbol = str(symbol).strip()
    if symbol.startswith(('6', '9', '5', '7')):
        return "1" 
    return "0"

def get_realtime_quote(symbol_or_secid):
    symbol = str(symbol_or_secid).strip()
    if "." in symbol:
        secid = symbol
    else:
        market = get_market_code(symbol)
        secid = f"{market}.{symbol}"
        
    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&ut=fa5fd1943c7b386f172d6893dbfba10b&fltt=2&invt=2&fields=f57,f58,f43,f170,f169,f47,f48,f60,f44,f45,f46,f168,f116,f162,f167"
    try:
        res = requests.get(url, headers=HEADERS, timeout=5).json()
        if res and res.get('data'):
            return res['data']
        return None
    except:
        return None

def get_forex_data():
    """专门获取美元/离岸人民币汇率，作为北向资金流向的锚定指标"""
    url = "https://push2.eastmoney.com/api/qt/stock/get?secid=133.USDCNH&ut=fa5fd1943c7b386f172d6893dbfba10b&fltt=2&fields=f43,f170"
    try:
        res = requests.get(url, headers=HEADERS, timeout=5).json()
        if res and res.get('data'):
            return safe_float(res['data'].get('f43')), safe_float(res['data'].get('f170'))
        return None, None
    except:
        return None, None

def get_kline_data(symbol_or_secid, days=60):
    symbol = str(symbol_or_secid).strip()
    if "." in symbol:
        secid = symbol
    else:
        market = get_market_code(symbol)
        secid = f"{market}.{symbol}"

    url = f"https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}&klt=101&fqt=1&lmt={days}&end=20500101&iscca=1&fields1=f1,f2,f3,f4,f5&fields2=f51,f52,f53,f54,f55,f56,f57"
    try:
        res = requests.get(url, headers=HEADERS, timeout=5).json()
        if not res or 'data' not in res or not res['data']:
            return None
        klines = res['data'].get('klines', [])
        if not klines:
            return None
            
        parsed = [line.split(',')[:6] for line in klines]
        df = pd.DataFrame(parsed, columns=['date', 'open', 'close', 'high', 'low', 'vol'])
        df = df[df['close'] != '-']
        df.replace('-', '0', inplace=True)
        df = df.astype({'open': float, 'close': float, 'high': float, 'low': float, 'vol': float})
        return df
    except:
        return None

def get_aggregated_news():
    url = "https://np-anotice-stock.eastmoney.com/api/security/ann?page_size=8&page_index=1&ann_type=A"
    try:
        res = requests.get(url, headers=HEADERS, timeout=5).json()
        news_list = res.get('data', {}).get('list', [])
        news_texts = [f"- {item['title']}" for item in news_list]
        return "\n".join(news_texts) if news_texts else "暂无新闻"
    except:
        return "暂无新闻"

# ================= 界面分栏设计 =================
tab1, tab2 = st.tabs(["🎯 个股全维解析 (含政策与外资)", "🌍 宏观大盘与多智能体研判"])

# ----------------- Tab 1: 个股全维解析 -----------------
with tab1:
    st.write("深度整合：基本面 + 政策解读 + 美联储宏观影响 + 北向资金偏好。")
    symbol_input = st.text_input("请输入股票代码", placeholder="例如：000001 (平安银行)", key="stock_input")

    if st.button("开始全维深度解析"):
        if not api_key:
            st.error("❌ 未配置 GROQ_API_KEY")
        elif not symbol_input.strip() or len(symbol_input.strip()) != 6:
            st.warning("⚠️ 请输入 6 位 A 股代码")
        else:
            with st.spinner("正在安全拉取基本面并计算量化指标..."):
                quote = get_realtime_quote(symbol_input)
                df_kline = get_kline_data(symbol_input)
                macro_news = get_aggregated_news()
                cnh_price, cnh_pct = get_forex_data() # 获取汇率

                if quote and df_kline is not None and not df_kline.empty:
                    try:
                        name = quote.get('f58', '未知')
                        price = safe_float(quote.get('f43')) 
                        change_percent = safe_float(quote.get('f170'))
                        
                        market_cap_raw = safe_float(quote.get('f116'))
                        market_cap = market_cap_raw / 100000000 
                        
                        pe_ratio = quote.get('f162', '-')
                        pb_ratio = quote.get('f167', '-')
                        turnover = safe_float(quote.get('f168'))

                        recent_20 = df_kline.tail(20)
                        support_level = recent_20['low'].min()
                        resistance_level = recent_20['high'].max()

                        avg_vol = recent_20['vol'].mean()
                        latest_vol = recent_20.iloc[-1]['vol']
                        vol_ratio = latest_vol / avg_vol if avg_vol > 0 else 0

                        smart_money_signal = "无明显异常"
                        if vol_ratio > 2.0 and change_percent > 3.0:
                            smart_money_signal = "放量大涨 (疑似主力/游资抢筹)"
                        elif vol_ratio > 2.0 and change_percent < -3.0:
                            smart_money_signal = "放量大跌 (主力资金撤离)"

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
                        df_kline.set_index('date', inplace=True)
                        st.line_chart(df_kline['close'])

                        with st.spinner("🧠 AI 正在进行 宏观+政策+北向外资 多维度深度分析..."):
                            client = Groq(api_key=api_key)
                            
                            cnh_text = f"当前离岸人民币汇率为 {cnh_price}，日内波动 {cnh_pct}%" if cnh_price else "汇率数据暂未获取"
                            
                            prompt = f"""
                            你是一家顶级私募的首席投研官。请为股票【{name} ({symbol_input})】撰写一份极度专业的全维分析报告。
                            
                            【数据底座】：
                            - 基本面：总市值 {market_cap:.2f}亿，PE {pe_ratio}，PB {pb_ratio}。
                            - 技术面：现价 {price}，涨幅 {change_percent}%，近期支撑 {support_level}，压力 {resistance_level}。
                            - 资金面异动：{smart_money_signal}。
                            - 宏观外汇锚定：{cnh_text}。
                            
                            请分段输出以下内容：
                            1. 🏛️ **宏观政策与美联储影响**：基于当前的中美CPI环境及美联储降息/加息预期，结合国内稳增长政策，分析该股所属行业是处于政策风口还是承压期？
                            2. 💸 **北向资金与汇率共振**：结合刚刚获取的人民币汇率波动表现，推测当前北向资金（外资）的风险偏好。这只股票的市值和PE特征，是否符合外资抢筹的“审美”？
                            3. 🏢 **基本面估值诊断**：综合上述宏观条件，目前的估值是否合理？
                            4. 🎯 **实战量化策略**：结合支撑/压力位给出具体的操作思路。
                            
                            要求：语言极其干练，直击要害，体现出机构视角。
                            """
                            completion = client.chat.completions.create(
                                messages=[{"role": "user", "content": prompt}],
                                model="llama-3.3-70b-versatile",
                                temperature=0.3
                            )
                            st.markdown("---")
                            st.markdown("### 📝 AI 宏观全维深度研报")
                            st.write(completion.choices[0].message.content)
                    except Exception as e:
                        st.error(f"渲染数据时出错：{e}")
                else:
                    st.error("❌ 无法获取该股票数据，请检查网络或确认该股未退市。")

# ----------------- Tab 2: 宏观多智能体研判 -----------------
with tab2:
    st.write("📊 联动核心指数、外汇市场与全网新闻，启动 6 大 AI 智能体进行宏观映射分析。")
    if st.button("启动多智能体宏观推演", type="primary"):
        if not api_key:
            st.error("❌ 未配置 GROQ_API_KEY")
        else:
            with st.spinner("1. 正在抓取大盘快照、外汇波动与全网热点样本..."):
                indices = {"上证指数": "1.000001", "深证成指": "0.399001", "创业板指": "0.399006", "沪深300": "1.000300"}
                index_data_str = ""
                
                # 改为5列，新增汇率展示
                cols = st.columns(5)
                
                for idx, (index_name, secid) in enumerate(indices.items()):
                    quote = get_realtime_quote(secid)
                    if quote:
                        price = safe_float(quote.get('f43')) 
                        pct = safe_float(quote.get('f170')) 
                        cols[idx].metric(index_name, f"{price:.2f}", f"{pct:.2f}%")
                        index_data_str += f"{index_name}: {price:.2f} ({pct:.2f}%)\n"

                cnh_price, cnh_pct = get_forex_data()
                if cnh_price:
                    cols[4].metric("美元/离岸人民币", f"{cnh_price:.4f}", f"{cnh_pct:.2f}%", delta_color="inverse")
                    cnh_text = f"美元/离岸人民币: {cnh_price:.4f} (涨跌幅: {cnh_pct:.2f}%)"
                else:
                    cnh_text = "汇率数据暂未获取"

                news_text = get_aggregated_news()
                with st.expander("📰 实时全网热点新闻样本 (已抓取)"):
                    st.write(news_text)

            with st.spinner("2. 唤醒 6 大 AI 智能体进行深度宏观推演..."):
                try:
                    current_date = datetime.now().strftime("%Y-%m-%d")
                    client = Groq(api_key=api_key)
                    
                    # 提示词升级：加入汇率数据，并增加【跨境资金分析师】
                    multi_agent_prompt = f"""
                    你现在是一个由 6 位顶尖金融专家组成的【量化投研委员会】。今天是 {current_date}。
                    【大盘快照】：\n{index_data_str}\n
                    【外汇风向标】：\n{cnh_text} (注：人民币升值利好北向资金流入)\n
                    【全网最新热点样本】：\n{news_text}\n
                    
                    请按照以下 6 个专家的视角输出研报：
                    1. 🌍【全球宏观分析师】：结合近期美联储动作与中美CPI通胀环境，点评对全球资本市场的影响。
                    2. 📜【国内政策解读师】：解读近期国内稳增长政策、产业政策的托底效应。
                    3. 💸【跨境资金分析师】(重点)：基于刚刚抓取的美元/人民币汇率异动，深度剖析**北向资金（外资）**近期的流入/流出意愿。
                    4. 🏭【行业映射分析师】：基于上述宏观条件，指出未来1-2季度绝对受益的2个板块。
                    5. 🎯【优质标的分析师】：为看好的板块推荐龙头标的（带代码）。
                    6. 🧙‍♂️【首席策略官总结】：市场定调与仓位建议。
                    使用 Markdown，极度专业干脆。
                    """
                    completion = client.chat.completions.create(
                        messages=[{"role": "user", "content": multi_agent_prompt}],
                        model="llama-3.3-70b-versatile",
                        temperature=0.4
                    )
                    st.markdown("---")
                    st.markdown("### 🧠 投研委员会宏观联合决策报告")
                    st.write(completion.choices[0].message.content)
                except Exception as e:
                    st.error(f"智能体推演失败: {e}")
