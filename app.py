import streamlit as st
import google.generativeai as genai

st.set_page_config(page_title="AI股票助手 (Gemini版)", page_icon="📈", layout="centered")

st.title("📈 AI 股票助手 (Gemini)")
st.write("输入股票代码，获取免费的 AI 分析。")

# 从 Streamlit 后台获取 Gemini 密钥
api_key = st.secrets.get("GEMINI_API_KEY", "")

symbol = st.text_input("股票代码", placeholder="例如：000001 或 AAPL")

if st.button("开始分析"):
    if not api_key:
        st.error("请先在 Streamlit Secrets 中配置 GEMINI_API_KEY")
    elif not symbol.strip():
        st.warning("请输入股票代码。")
    else:
        with st.spinner("Gemini 正在思考中..."):
            try:
                # 配置 Gemini
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel('gemini-1.5-flash')
                
                # 发送指令
                prompt = f"你是一名专业的股票分析助手。请分析股票 {symbol}，从基本面、技术面、风险点三个方面给出简洁分析，并明确说明这不是投资建议。请使用中文回答。"
                
                response = model.generate_content(prompt)
                
                st.success("分析完成")
                st.write(response.text)

            except Exception as e:
                st.error(f"分析失败，请检查密钥是否正确或网络是否通畅。错误信息：{e}")
