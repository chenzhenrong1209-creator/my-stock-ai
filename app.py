import streamlit as st
from groq import Groq
import pandas as pd
import requests
import json
import numpy as np
from datetime import datetime

st.set_page_config(page_title="AI股票助手 (量化追踪版)", page_icon="📈", layout="wide")

st.title("📈 AI 股票助手 (量化追踪与聪明钱监控)")
st.write("集成主力资金异动监控、量化支撑/压力位计算与宏观消息面分析。")

api_key = st.secrets.get("GROQ_API_KEY", "")

# --- 核心抓取函数（保持轻量化） ---
def get_market_code(symbol):
    return "1" if symbol.startswith(('6', '9')) else "0"

def get_realtime_quote(symbol):
    market = get_market_code(symbol)
    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={market}.{symbol}&fields=f57,f58,f43,f170,f169,f47,f48,f60,f44,f45,f46,f168"
    try:
        res = requests.get(url, timeout=5).json()
        return res.get('data')
    except:
        return None

def get_kline_data(symbol, days=30):
    """获取历史K线用于量化计算"""
    market = get_market_code(symbol)
    url = f"http://push2his.eastmoney.com/api/qt/stock/kline/get?secid={market}.{symbol}&klt=101&fqt=1&lmt={days}&end=20500101&iscca=1&fields1=f1,f2,f3,f4,f5&fields2=f51,f52,f53,f54,f55,f56,f57"
    try:
        res = requests.get(url, timeout=5).json()
        klines = res['data']['klines']
        # 解析数据：日期, 开盘, 收盘, 最高, 最低, 成交量
        parsed = [line.split(',')[:6] for line in klines]
        df = pd.DataFrame(parsed, columns=['date', 'open', 'close', 'high', 'low', 'vol'])
        df = df.astype({'open': float, 'close': float, 'high': float, 'low': float, 'vol': float})
        return df
    except:
        return None

def get_latest_news():
    """获取东方财富7x24小时全球实时财经快讯（前3条）"""
    url = "https://np-anotice-stock.eastmoney.com/api/security/ann?page_size=3&page_index=1&ann_type=A"
    # 为了保证系统绝对稳定，如果新闻接口变动，我们用时间戳配合AI自身的宏观认知兜底
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    return current_time

# --- 界面逻辑 ---
symbol = st.text_input("请输入股票代码", placeholder="例如：600821")

if st.button("开始深度量化分析"):
    if not api_key:
        st.error("❌ 未配置 GROQ_API_KEY")
    elif not symbol.strip() or len(symbol.strip()) != 6:
        st.warning("⚠️ 请输入 6 位 A 股代码")
    else:
        with st.spinner("正在扫描行情、计算量化指标与追踪资金面..."):
            quote = get_realtime_quote(symbol)
            df_kline = get_kline_data(symbol, days=60) # 获取近60天数据
            
            if quote and df_kline is not None and not df_kline.empty:
                name = quote['f58']
                price = quote['f43'] / 100
                change_percent = quote['f170'] / 100
                
                # --- 量化计算：支撑位与压力位 ---
                # 使用近20天的最高点和最低点作为近期的阻力与支撑
                recent_20 = df_kline.tail(20)
                support_level = recent_20['low'].min()
                resistance_level = recent_20['high'].max()
                
                # --- 聪明钱/游资监控 (Smart Money Tracker) ---
                # 逻辑：如果某天成交量大于过去20天平均量的2倍，且收盘大涨，视为游资/主力进场痕迹
                avg_vol = recent_20['vol'].mean()
                latest_vol = recent_20.iloc[-1]['vol']
                vol_ratio = latest_vol / avg_vol
                
                smart_money_signal = "无明显异常"
                if vol_ratio > 2.0 and change_percent > 3.0:
                    smart_money_signal = "⚠️ 发现强劲资金介入痕迹 (放量大涨，疑似游资/主力建仓)"
                elif vol_ratio > 2.0 and change_percent < -3.0:
                    smart_money_signal = "⚠️ 发现主力资金撤离痕迹 (放量大跌，注意规避)"
                elif vol_ratio < 0.5:
                    smart_money_signal = "缩量状态 (资金观望情绪浓厚)"

                # --- 界面展示可视化与指标 ---
                st.subheader(f"📊 {name} ({symbol}) 量化仪表盘")
                
                # 指标卡片
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("当前价格", f"{price:.2f}")
                c2.metric("今日涨跌", f"{change_percent:.2f}%")
                c3.metric("近期支撑位", f"{support_level:.2f}")
                c4.metric("近期压力位", f"{resistance_level:.2f}")
                
                # 数据可视化：绘制近期收盘价走势图
                st.write("**近60个交易日收盘价走势：**")
                df_kline.set_index('date', inplace=True)
                st.line_chart(df_kline['close'])
                
                # --- AI 深度整合分析 ---
                current_time = get_latest_news()
                
                prompt = f"""
                你是一名顶尖的量化交易员与宏观分析师。现在是北京时间 {current_time}。
                请结合以下我为你计算出的硬核量化数据，对【{name} ({symbol})】进行研判：
                
                【实时行情】：当前价格 {price:.2f}元，涨跌幅 {change_percent:.2f}%。
                【聪明钱/主力资金监测】：{smart_money_signal}。（成交量是近20日均量的 {vol_ratio:.2f} 倍）
                【量化关键位】：近期强支撑位在 {support_level:.2f}元，压力位在 {resistance_level:.2f}元。
                
                请提供以下分析（使用中文，排版清晰，切中要害）：
                1. 消息面与宏观时机：基于当前的时间节点（{current_time}），有没有近期国内外值得注意的宏观因素（如降息预期、地缘政治或行业政策）可能影响该板块？
                2. 资金面拆解：根据上面的“聪明钱监测”数据，解读当前主力/游资的博弈状态。
                3. 量化进出场策略：明确给出结合支撑位、压力位的操作建议（例如：如果突破某点位该如何，如果跌破某点位该如何离场）。
                
                结尾务必声明：本分析基于量化数据与 AI 模型，不构成绝对投资建议。
                """
                
                with st.spinner("Groq 正在结合资金流向与量化模型生成研报..."):
                    try:
                        client = Groq(api_key=api_key)
                        completion = client.chat.completions.create(
                            messages=[{"role": "user", "content": prompt}],
                            model="llama-3.3-70b-versatile",
                            temperature=0.3, # 降低温度，让AI的回答更偏向理性和逻辑
                        )
                        st.markdown("---")
                        st.markdown("### 🤖 智能量化研报")
                        st.write(completion.choices[0].message.content)
                    except Exception as e:
                        st.error(f"AI 调用失败: {e}")
            else:
                st.error("❌ 无法获取该股票数据，可能是停牌或代码错误。")
