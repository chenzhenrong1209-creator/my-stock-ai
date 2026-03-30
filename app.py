import streamlit as st
from groq import Groq
import yfinance as yf

st.set_page_config(page_title="AI股票助手 (实时数据版)", page_icon="📈", layout="centered")

st.title("📈 AI 股票助手 (接入实时数据)")
st.write("输入股票代码（美股直接输，A股请加后缀，如：**000001.SZ** 或 **AAPL**）")

api_key = st.secrets.get("GROQ_API_KEY", "")

# 增加一点提示，防止 A 股代码输错格式
symbol = st.text_input("股票代码", placeholder="例如：AAPL, TSLA, 000001.SZ, 600519.SS")

if st.button("开始分析"):
    if not api_key:
        st.error("请先在 Streamlit Secrets 中配置 GROQ_API_KEY")
    elif not symbol.strip():
        st.warning("请输入股票代码。")
    else:
        # === 环节一：抓取实时数据 ===
        with st.spinner("1. 正在全网抓取最新行情数据..."):
            try:
                stock = yf.Ticker(symbol.upper())
                hist = stock.history(period="1mo") # 获取最近一个月的走势
                
                if hist.empty:
                    st.error(f"找不到 {symbol} 的数据！\n如果是A股，请务必加上后缀：深市加 .SZ (如 000001.SZ)，沪市加 .SS (如 600519.SS)")
                    st.stop() # 停止运行，不再往下消耗 AI 额度
                    
                # 计算最新价格和涨跌
                current_price = hist['Close'].iloc[-1]
                price_change = current_price - hist['Close'].iloc[-2]
                
                # 在界面上直接显示一个漂亮的“价格牌”
                st.metric(label=f"{symbol.upper()} 最新收盘价", value=f"{current_price:.2f}", delta=f"{price_change:.2f}")
                
                # 把数据打包成一段话，准备发给 AI
                real_time_data = f"""
                股票代码：{symbol.upper()}
                最新收盘价：{current_price:.2f}
                近一个月最高价：{hist['High'].max():.2f}
                近一个月最低价：{hist['Low'].min():.2f}
                """
            except Exception as e:
                st.error(f"数据抓取失败：{e}")
                st.stop()
                
        # === 环节二：AI 结合数据进行推理 ===
        with st.spinner("2. Groq 正在结合实时数据进行深度分析..."):
            try:
                client = Groq(api_key=api_key)
                
                # 这里是重点：我们改变了 Prompt，强迫 AI 根据我们提供的数据说话
                prompt = f"""
                你是一名专业的股票分析助手。请基于我提供的最新真实数据，分析股票 {symbol}。
                
                【最新真实行情数据】：
                {real_time_data}
                
                请结合以上价格数据，从基本面猜测、当前技术面（结合最高/低价和当前价）、风险点三个方面给出简洁分析。
                请明确说明这不是投资建议。必须使用中文回答。
                """
                
                # 明确指定模型，防止系统默认切换
                completion = client.chat.completions.create(
                    model="llama-3.3-70b-versatile", 
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                )
                
                answer = completion.choices[0].message.content
                st.success("分析完成！")
                st.markdown(answer)

            except Exception as e:
                st.error("AI 分析失败，请稍后再试。")
                st.info(f"错误细节: {e}")
