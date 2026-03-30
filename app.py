import streamlit as st
from groq import Groq

st.set_page_config(page_title="AI股票助手 (Groq极速版)", page_icon="📈", layout="centered")

st.title("📈 AI 股票助手 (Groq)")
st.write("输入股票代码，获取免费、极速的 AI 分析。")

# 从 Streamlit Secrets 后台读取 Key
api_key = st.secrets.get("GROQ_API_KEY", "")

symbol = st.text_input("股票代码", placeholder="例如：000001 或 NVDA")

if st.button("开始分析"):
    if not api_key:
        st.error("请先在 Streamlit Secrets 中配置 GROQ_API_KEY")
    elif not symbol.strip():
        st.warning("请输入股票代码。")
    else:
        with st.spinner("Groq 正在极速分析中..."):
            try:
                # 初始化 Groq 客户端
                client = Groq(api_key=api_key)
                
                # 调用 Llama 3.3 模型 (目前 Groq 上最强的免费模型)
                completion = client.chat.completions.create(
                    model="llama-3.3-70b-versatile", 
                    messages=[
                        {
                            "role": "system",
                            "content": "你是一名专业的股票分析助手。请从基本面、技术面、风险点三个方面给出简洁分析，并明确说明这不是投资建议。请使用中文回答。"
                        },
                        {
                            "role": "user",
                            "content": f"请详细分析股票 {symbol}。"
                        }
                    ],
                    temperature=0.7,
                )
                
                # 获取并展示结果
                answer = completion.choices[0].message.content
                st.success("分析完成")
                st.markdown(answer)

            except Exception as e:
                st.error("分析失败。可能是 Key 填错了，或者 Groq 服务器繁忙。")
                st.info(f"错误细节: {e}")
