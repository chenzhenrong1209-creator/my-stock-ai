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
        with st.spinner("Gemini 正在分析中..."):
            try:
                # 重新配置，确保密钥生效
                genai.configure(api_key=api_key)
                
                # 尝试使用最稳定的模型路径
                model = genai.GenerativeModel(model_name='gemini-1.5-flash')
                
                prompt = f"你是一名专业的股票分析助手。请分析股票 {symbol}，从基本面、技术面、风险点三个方面给出简洁分析，并明确说明这不是投资建议。请使用中文回答。"
                
                response = model.generate_content(prompt)
                
                if response.text:
                    st.success("分析完成")
                    st.markdown(response.text)
                else:
                    st.error("AI 返回了空内容，请稍后再试。")

            except Exception as e:
                # 给出更详细的错误提示
                st.error(f"分析出错。如果是404，请确认您的API Key是否已在 Google AI Studio 激活。")
                st.info(f"详细错误信息：{e}")
