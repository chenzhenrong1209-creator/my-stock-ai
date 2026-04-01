import streamlit as st
from groq import Groq
import efinance as ef
import pandas as pd
import time

st.set_page_config(page_title="AI股票助手 (稳定版)", page_icon="📈")

st.title("📈 AI 股票助手 (极速稳定版)")
st.write("输入 6 位 A 股代码，支持实时行情与 AI 深度分析。")

# 从 Secrets 获取 API KEY
api_key = st.secrets.get("GROQ_API_KEY", "")

symbol = st.text_input("请输入股票代码", placeholder="例如：600821")

if st.button("开始分析"):
    if not api_key:
        st.error("❌ 错误：未检测到 GROQ_API_KEY，请在 Streamlit 管理后台配置。")
    elif not symbol.strip() or len(symbol.strip()) != 6:
        st.warning("⚠️ 请输入正确的 6 位 A 股数字代码。")
    else:
        # === 环节一：抓取实时数据 ===
        with st.spinner("1. 正在调取实时行情数据..."):
            try:
                # 使用 efinance 获取实时行情，它对云服务器 IP 更友好
                df = ef.stock.get_quote_history(symbol)
                
                if df is None or df.empty:
                    st.error(f"❌ 未能找到代码 {symbol} 的数据，请核对代码是否正确。")
                else:
                    # 获取最新的一行数据
                    latest = df.iloc[-1]
                    name = latest['股票名称']
                    price = latest['收盘']
                    pct_chg = latest['涨跌幅']
                    vol = latest['成交量']
                    
                    # 页面展示
                    st.subheader(f"📊 {name} ({symbol}) 当前表现")
                    col1, col2, col3 = st.columns(3)
                    col1.metric("当前价格", f"{price} 元")
                    col2.metric("今日涨跌", f"{pct_chg}%")
                    col3.metric("成交量", f"{vol} 手")
                    
                    # 整理给 AI 的上下文
                    stock_context = f"""
                    股票名称：{name}
                    股票代码：{symbol}
                    当前收盘价：{price} 元
                    涨跌幅：{pct_chg}%
                    成交量：{vol}
                    最高价：{latest['最高']}
                    最低价：{latest['最低']}
                    换手率：{latest.get('换手率', '暂无')}%
                    """
                    
                    # === 环节二：AI 分析 ===
                    with st.spinner(f"2. 正在通过 Groq (Llama-3) 进行 AI 分析..."):
                        client = Groq(api_key=api_key)
                        
                        prompt = f"""
                        你是一位资深的 A 股市场策略分析师。请针对以下提供的实时行情数据，给出你的专业见解：
                        
                        {stock_context}
                        
                        要求：
                        1. 简要评价今日股价表现（是强力支撑、缩量震荡还是破位下跌？）。
                        2. 分析成交量和换手率反映出的市场情绪。
                        3. 给投资者提供 2-3 点短期的技术性建议。
                        4. 结尾必须声明：以上分析仅供参考，不构成投资建议。
                        请直接使用中文回答，保持专业、干练。
                        """
                        
                        chat_completion = client.chat.completions.create(
                            messages=[{"role": "user", "content": prompt}],
                            model="llama-3.3-70b-versatile", # 使用目前 Groq 最快的 70B 模型
                        )
                        
                        st.markdown("---")
                        st.markdown("### 🤖 AI 分析报告")
                        st.success(chat_completion.choices[0].message.content)

            except Exception as e:
                st.error(f"😢 数据抓取遇到技术阻碍：{str(e)}")
                st.info("💡 提示：这通常是由于数据接口请求繁忙，建议稍等 30 秒再次点击。")

