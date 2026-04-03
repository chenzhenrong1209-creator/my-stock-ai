import streamlit as st
from groq import Groq
import pandas as pd
import requests
from datetime import datetime

st.set_page_config(page_title="AI股票投研系统", page_icon="📈", layout="wide")

st.title("📈 AI 股票投研系统 (全维深度解析版)")

api_key = st.secrets.get("GROQ_API_KEY", "")

# ================= 核心数据抓取函数 =================
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

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
        
    # 偷偷加料：f116(总市值), f162(动态市盈率), f167(市净率), f168(换手率)
    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f57,f58,f43,f170,f169,f47,f48,f60,f44,f45,f46,f168,f116,f162,f167"
    try:
        res = requests.get(url, headers=HEADERS, timeout=5).json()
        if res and res.get('data'):
            return res['data']
        return None
    except:
        return None

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
tab1, tab2 = st.tabs(["🎯 个股全维解析 (基本面+技术面)", "🌍 宏观大盘与多智能体研判"])

# ----------------- Tab 1: 个股全维解析 -----------------
with tab1:
    st.write("深度整合：公司基本面 + 行业趋势 + 聪明钱异动 + 量化关键位。")
    symbol_input = st.text_input("请输入股票代码", placeholder="例如：000001 (平安银行)", key="stock_input")

    if st.button("开始全维深度解析"):
        if not api_key:
            st.error("❌ 未配置 GROQ_API_KEY")
        elif not symbol_input.strip() or len(symbol_input.strip()) != 6:
            st.warning("⚠️ 请输入 6 位 A 股代码")
        else:
            with st.spinner("正在扫描基本面、计算量化指标..."):
                quote = get_realtime_quote(symbol_input)
                df_kline = get_kline_data(symbol_input)
                macro_news = get_aggregated_news() # 顺便抓点宏观新闻做大盘背景

                if quote and df_kline is not None and not df_kline.empty:
                    try:
                        name = quote['f58']
                        price = float(quote.get('f43', 0)) / 100 if str(quote.get('f43')).replace('.','').isdigit() else 0.0
                        change_percent = float(quote.get('f170', 0)) / 100 if str(quote.get('f170')).replace('.','').replace('-','').isdigit() else 0.0
                        
                        # --- 提取基本面数据 ---
                        market_cap = float(quote.get('f116', 0)) / 100000000 if str(quote.get('f116')).replace('-','').isdigit() else 0.0 # 转换成亿元
                        pe_ratio = quote.get('f162', '亏损/暂无')
                        pb_ratio = quote.get('f167', '暂无')
                        turnover = quote.get('f168', 0)

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

                        # --- 界面展示优化 ---
                        st.subheader(f"📊 {name} ({symbol_input}) 数据扫描")
                        
                        st.markdown("**【核心基本面】**")
                        col_b1, col_b2, col_b3, col_b4 = st.columns(4)
                        col_b1.metric("总市值", f"{market_cap:.2f} 亿")
                        col_b2.metric("动态市盈率 (PE)", f"{pe_ratio}")
                        col_b3.metric("市净率 (PB)", f"{pb_ratio}")
                        col_b4.metric("今日换手率", f"{turnover}%")
                        
                        st.markdown("**【量化技术面】**")
                        col_t1, col_t2, col_t3, col_t4 = st.columns(4)
                        col_t1.metric("现价", f"{price:.2f}", f"{change_percent:.2f}%")
                        col_t2.metric("资金监控", f"{vol_ratio:.1f}倍量", delta_color="off")
                        col_t3.metric("近期支撑位", f"{support_level:.2f}")
                        col_t4.metric("近期压力位", f"{resistance_level:.2f}")

                        st.write("**近60个交易日收盘价走势：**")
                        df_kline.set_index('date', inplace=True)
                        st.line_chart(df_kline['close'])

                        with st.spinner("🧠 首席策略师 AI 正在整合 基本面+技术面+宏观面 生成研报..."):
                            client = Groq(api_key=api_key)
                            
                            # 终极 Prompt：逼迫 AI 进行多维度思考
                            prompt = f"""
                            你是一家顶级私募的首席投研官。请为股票【{name} ({symbol_input})】撰写一份极度专业的全维分析报告。
                            
                            【已抓取的数据底座】：
                            - 公司基本面：总市值 {market_cap:.2f}亿，市盈率(PE) {pe_ratio}，市净率(PB) {pb_ratio}。
                            - 量化技术面：现价 {price}，今日涨幅 {change_percent}%，换手率 {turnover}%。近期支撑位 {support_level}，压力位 {resistance_level}。
                            - 聪明钱监控：当前成交量是20日均量的 {vol_ratio:.1f} 倍，异动判定：{smart_money_signal}。
                            - 今日大盘宏观新闻参考：{macro_news}
                            
                            请分段输出以下内容：
                            1. 🏢 **基本面与行业定性**：基于市值和PE/PB，判断它是蓝筹、成长还是题材股？并调用你的知识库，指出该公司所属的核心行业，以及该行业当前的宏观发展趋势（例如政策利好还是内卷周期）。
                            2. ⚔️ **大盘与资金面共振**：结合今日宏观新闻参考，分析该股今天的资金面（异动判定与换手率）是否是在迎合大盘风口，主力意欲何为？
                            3. 🎯 **实战量化策略**：结合支撑/压力位给出具体的操作思路（如击穿某点位止损，突破某点位看多）。
                            
                            要求：语言极其干练，直击要害，像发给基金经理的内部密报。
                            """
                            completion = client.chat.completions.create(
                                messages=[{"role": "user", "content": prompt}],
                                model="llama-3.3-70b-versatile",
                                temperature=0.3 # 偏向客观理性的推理
                            )
                            st.markdown("---")
                            st.markdown("### 📝 AI 全维深度研报")
                            st.write(completion.choices[0].message.content)
                    except Exception as e:
                        st.error(f"处理数据时出错，可能是股票停牌或数据异常：{e}")
                else:
                    st.error("❌ 无法获取该股票数据。")

# ----------------- Tab 2: 宏观多智能体研判 (保持不变) -----------------
with tab2:
    st.write("📊 联动核心指数与全网新闻样本，启动 5 大 AI 智能体进行宏观映射分析。")
    if st.button("启动多智能体宏观推演", type="primary"):
        if not api_key:
            st.error("❌ 未配置 GROQ_API_KEY")
        else:
            with st.spinner("1. 正在抓取市场快照与全网热点样本..."):
                indices = {"上证指数": "1.000001", "深证成指": "0.399001", "创业板指": "0.399006", "沪深300": "1.000300"}
                index_data_str = ""
                cols = st.columns(4)
                for idx, (index_name, secid) in enumerate(indices.items()):
                    quote = get_realtime_quote(secid)
                    if quote:
                        price = float(quote.get('f43', 0)) / 100 if str(quote.get('f43')).replace('.','').isdigit() else 0.0
                        pct = float(quote.get('f170', 0)) / 100 if str(quote.get('f170')).replace('.','').replace('-','').isdigit() else 0.0
                        cols[idx].metric(index_name, f"{price:.2f}", f"{pct:.2f}%")
                        index_data_str += f"{index_name}: {price:.2f} ({pct:.2f}%)\n"

                news_text = get_aggregated_news()
                with st.expander("📰 实时全网热点新闻样本 (已抓取)"):
                    st.write(news_text)

            with st.spinner("2. 唤醒 5 大 AI 智能体进行深度推演与行业映射..."):
                try:
                    current_date = datetime.now().strftime("%Y-%m-%d")
                    client = Groq(api_key=api_key)
                    multi_agent_prompt = f"""
                    你现在是一个由 5 位顶尖金融专家组成的【量化投研委员会】。今天是 {current_date}。
                    【大盘快照】：\n{index_data_str}\n
                    【全网最新热点样本】：\n{news_text}\n
                    请按照以下 5 个专家的视角输出研报：
                    1. 🧑‍💼【宏观总量分析师】：点评宏观基本面。
                    2. 🏦【政策流动性分析师】：推测资金流动性态度。
                    3. 🏭【行业映射分析师】(重点)：指出未来1-2季度绝对受益的2个板块及承压的1个板块。
                    4. 🎯【优质标的分析师】(重点)：推荐板块龙头标的（带代码）。
                    5. 🧙‍♂️【首席策略官总结】：市场定调与仓位建议。
                    使用 Markdown，极度专业干脆。
                    """
                    completion = client.chat.completions.create(
                        messages=[{"role": "user", "content": multi_agent_prompt}],
                        model="llama-3.3-70b-versatile",
                        temperature=0.4
                    )
                    st.markdown("---")
                    st.markdown("### 🧠 投研委员会联合决策报告")
                    st.write(completion.choices[0].message.content)
                except Exception as e:
                    st.error(f"智能体推演失败: {e}")
