import streamlit as st
import requests

st.set_page_config(page_title="AI股票助手", page_icon="📈", layout="centered")

st.title("📈 AI 股票助手")
st.write("输入股票代码，获取 AI 分析。")

api_key = st.secrets.get("DEEPSEEK_API_KEY", "")
base_url = st.secrets.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
model_name = st.secrets.get("DEFAULT_MODEL_NAME", "deepseek-chat")

symbol = st.text_input("股票代码", placeholder="例如：000001 或 AAPL")

if st.button("开始分析"):
    if not api_key:
        st.error("没有读取到 DEEPSEEK_API_KEY，请先去 Streamlit Secrets 里配置。")
    elif not symbol.strip():
        st.warning("请输入股票代码。")
    else:
        with st.spinner("正在分析中..."):
            try:
                url = f"{base_url}/chat/completions"
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": model_name,
                    "messages": [
                        {
                            "role": "system",
                            "content": "你是一名谨慎、清晰的股票分析助手。请从基本面、技术面、风险点三个方面给出简洁分析，并明确说明这不是投资建议。"
                        },
                        {
                            "role": "user",
                            "content": f"请分析股票 {symbol}。"
                        }
                    ],
                    "temperature": 0.7,
                }

                resp = requests.post(url, headers=headers, json=payload, timeout=60)
                resp.raise_for_status()
                data = resp.json()
                answer = data["choices"][0]["message"]["content"]

                st.success("分析完成")
                st.write(answer)

            except Exception as e:
                st.error(f"调用失败：{e}")