import streamlit as st
import requests

st.set_page_config(page_title="AI股票助手", layout="wide")

st.title("📈 AI 股票分析助手")

api_key = st.secrets.get("DEEPSEEK_API_KEY")

symbol = st.text_input("输入股票代码（如：000001）")

if st.button("开始分析"):

    if not api_key:
        st.error("❌ 没有配置 API Key")
    elif not symbol:
        st.warning("请输入股票代码")
    else:
        with st.spinner("AI 分析中..."):

            url = "https://api.deepseek.com/v1/chat/completions"

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }

            data = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": "你是专业股票分析师"},
                    {"role": "user", "content": f"分析股票 {symbol} 的走势和投资建议"}
                ]
            }

            try:
                res = requests.post(url, headers=headers, json=data)
                result = res.json()

                answer = result["choices"][0]["message"]["content"]

                st.success("分析完成")
                st.write(answer)

            except Exception as e:
                st.error(f"出错：{e}")