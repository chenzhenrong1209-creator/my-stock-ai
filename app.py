import streamlit as st
from groq import Groq
import pandas as pd
import requests
import json

st.set_page_config(page_title="AI股票助手 (极简稳定版)", page_icon="📈")

st.title("📈 AI 股票助手 (云端兼容版)")
st.write("直接输入 6 位 A 股代码（如 600821），无需加后缀。")

api_key = st.secrets.get("GROQ_API_KEY", "")

# 核心：直接请求数据接口，避开权限报错
def get_stock_data(symbol):
    # 自动判断沪深市场
    market = "1" if symbol.startswith(('6', '9')) else "0"
    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={market}.{symbol}&fields=f57,f58,f43,f170,f169,f47,f48,f60,f44,f45,f46,f168"
    try:
        response = requests.get(url, timeout=5)
        data = response.json()
        if data['data'] is None:
            return None
        return data['data']
    except:
        return None

symbol = st.text_input("请输入股票代码", placeholder="例如：600821")

if st.button("开始分析"):
    if not api_key:
        st.error("❌ 错误：未配置 GROQ_API_KEY")
    elif not symbol.strip() or len(symbol.strip()) != 6:
        st.warning("⚠️ 请输入 6 位 A 股代码")
    else:
        with st.spinner("正在获取实时行情..."):
            stock = get_stock_data(symbol)
            
            if stock:
                name = stock['f58']
                price = stock['f43'] / 100 # 原始数据通常是分，需要转换
                change_percent = stock['f170'] / 100
                
                # 页面展示
                st.subheader(f"📊 {name} ({symbol})")
                c1, c2, c3 = st.columns(3)
                c1.metric("当前价格", f"{price:.2f} 元")
                c2.metric("今日涨跌幅", f"{change_percent:.2f}%")
                c3.metric("成交额", f"{stock['f48']/100000000:.2f} 亿")

                # AI 分析
                with st.spinner("Groq 正在进行深度分析..."):
                    try:
                        client = Groq(api_key=api_key)
                        prompt = f"""
                        你是一名A股分析师。股票{name}({symbol})当前价格{price:.2f}元，涨跌幅{change_percent:.2f}%。
                        请根据这个表现给出简短的点评和风险提示。中文回答。
                        """
                        completion = client.chat.completions.create(
                            messages=[{"role": "user", "content": prompt}],
                            model="llama-3.3-70b-versatile",
                        )
                        st.markdown("---")
                        st.markdown("### 🤖 AI 分析建议")
                        st.success(completion.choices[0].message.content)
                    except Exception as e:
                        st.error(f"AI 调用失败: {e}")
            else:
                st.error("❌ 无法获取该股票数据，请检查代码是否正确。")
