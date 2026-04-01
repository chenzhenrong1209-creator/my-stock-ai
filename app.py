import streamlit as st
from groq import Groq
import akshare as ak
import pandas as pd

st.set_page_config(page_title="AI股票助手 (A股专版)", page_icon="📈", layout="centered")

st.title("📈 AI 股票助手 (AkShare A股版)")
st.write("直接输入 6 位 A 股数字代码，例如：600821 或 000001")

api_key = st.secrets.get("GROQ_API_KEY", "")

symbol = st.text_input("股票代码", placeholder="例如：600821")

if st.button("开始分析"):
    if not api_key:
        st.error("请先在 Streamlit Secrets 中配置 GROQ_API_KEY")
    elif not symbol.strip() or len(symbol.strip()) != 6:
        st.warning("请输入正确的 6 位股票代码。")
    else:
        # === 环节一：抓取本土 A 股数据 ===
        with st.spinner("1. 正在通过东方财富网抓取实时数据..."):
            try:
                # 使用 akshare 获取 A 股历史行情（日频，前复权）
                hist_data = ak.stock_zh_a_hist(symbol=symbol, period="daily", adjust="qfq")
                
                if hist_data.empty:
                    st.error(f"找不到代码为 {symbol} 的数据，请检查代码是否正确。")
                    st.stop()
                    
                # 提取最近两天的收盘价来计算涨跌
                latest_data = hist_data.iloc[-1]
                prev_data = hist_data.iloc[-2]
                
                current_price = latest_data['收盘']
                price_change = current_price - prev_data['收盘']
                
                # 在界面展示指标
                st.metric(label=f"股票 {symbol} 最新收盘价", value=f"{current_price:.2f}", delta=f"{price_change:.2f}")
                
                # 提取换手率、成交额等更符合 A 股的指标
                real_time_data = f"""
                股票代码：{symbol}
                最新收盘价：{current_price:.2f}
                今日最高：{latest_data['最高']:.2f}
                今日最低：{latest_data['最低']:.2f}
                换手率：{latest_data['换手率']}%
                成交额：{latest_data['成交额']} 元
                """
            except Exception as e:
                st.error(f"数据抓取失败：{e}")
                st.stop()
                
        # === 环节二：AI 结合数据进行推理 ===
        with st.spinner("2. Groq 正在结合A股实时数据进行深度分析..."):
            try:
                client = Groq(api_key=api_key)
                
                prompt = f"""
                你是一名专业的中国A股分析师。请基于我提供的最新真实数据，分析股票代码 {symbol}。
                
                【最新真实行情数据】：
                {real_time_data}
                
                请结合以上数据（特别是换手率和价格波动），从资金面、技术面、可能的基本面风险三个方面给出简洁、专业的中文分析。
                请明确说明这不是投资建议。
                """
                
                completion = client.chat.completions.create(
                    model="llama-3.3-70b-versatile", 
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                )
                
                answer = completion.choices[0].message.content
                st.success("分析完成！")
                st.markdown(answer)

            except Exception as e:
                st.error("AI 分析失败，可能是 Groq API 遇到网络波动。")
                st.info(f"错误细节: {e}")
