import streamlit as st
from groq import Groq
import pandas as pd
import akshare as ak
import random
from datetime import datetime
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time

# ================= 页面与终端 UI 配置 =================
st.set_page_config(page_title="AI 智能投研终端 v8", page_icon="🏦", layout="wide")

st.markdown("""
<style>
.terminal-header { font-family: 'Courier New', Courier, monospace; color: #00ff00; background-color: #000; padding: 10px; border-radius: 5px; font-size: 0.85em; margin-bottom: 20px;}
.metric-box { border: 1px solid #e5e7eb; padding: 15px; border-radius: 8px; text-align: center; }
</style>
""", unsafe_allow_html=True)

st.markdown(f"<div class='terminal-header'>[SYSTEM BOOT] TERMINAL v8.0.0 | ENGINE: QUANT+AI COMMITTEE | SYS_TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>", unsafe_allow_html=True)

api_key = st.secrets.get("GROQ_API_KEY", "")

# ================= 侧边栏与参数调优 =================
with st.sidebar:
    st.header("⚙️ 终端控制台")
    selected_model = st.selectbox("主理大模型", ["llama-3.3-70b-versatile", "mixtral-8x7b-32768", "gemma2-9b-it"], index=0)
    
    with st.expander("技术参数微调", expanded=False):
        ema_short = st.number_input("短期 EMA", value=20)
        ema_mid = st.number_input("中期 EMA", value=60)
        ema_long = st.number_input("长期 EMA", value=120)
        stop_atr_mult = st.slider("止损 ATR 倍数", 0.5, 5.0, 1.5, 0.1)

# ================= 核心数据流 (修复与增强) =================
@st.cache_data(ttl=60)
def get_market_temperature():
    """创意功能：获取全市场情绪温度计"""
    try:
        df = ak.stock_zh_a_spot_em()
        up_count = len(df[df["涨跌幅"] > 0])
        down_count = len(df[df["涨跌幅"] < 0])
        limit_up = len(df[df["涨跌幅"] >= 9.8])
        limit_down = len(df[df["涨跌幅"] <= -9.8])
        total = up_count + down_count
        sentiment_score = (up_count / total * 100) if total > 0 else 50
        return {"up": up_count, "down": down_count, "limit_up": limit_up, "limit_down": limit_down, "score": sentiment_score}
    except: return None

@st.cache_data(ttl=60)
def get_stock_quote(symbol):
    try:
        df = ak.stock_zh_a_spot_em()
        row = df[df["代码"] == symbol]
        if row.empty: return None
        return {
            "name": row.iloc[0]["名称"],
            "price": float(row.iloc[0]["最新价"]),
            "pct": float(row.iloc[0]["涨跌幅"]),
            "market_cap": float(row.iloc[0]["总市值"]) / 100000000,
            "pe": float(row.iloc[0]["市盈率-动态"]),
            "turnover": float(row.iloc[0]["换手率"])
        }
    except: return None

@st.cache_data(ttl=300)
def get_kline(symbol, days=250):
    try:
        df = ak.stock_zh_a_hist(symbol=symbol, period="daily", adjust="qfq")
        df.rename(columns={"日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "volume"}, inplace=True)
        df["date"] = pd.to_datetime(df["date"])
        return df.tail(days).reset_index(drop=True)
    except: return None

@st.cache_data(ttl=300)
def get_intraday_data(symbol):
    """修复：真实获取15分钟数据并执行MTF聚合"""
    try:
        df_15m = ak.stock_zh_a_hist_min_em(symbol=symbol, period="15", adjust="qfq")
        df_15m.rename(columns={"时间": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "volume"}, inplace=True)
        df_15m["date"] = pd.to_datetime(df_15m["date"])
        
        # 聚合 60m
        df_15m.set_index("date", inplace=True)
        df_60m = df_15m.resample("60min", closed="right", label="right").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna().reset_index()
        # 聚合 120m
        df_120m = df_15m.resample("120min", closed="right", label="right").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna().reset_index()
        df_15m = df_15m.reset_index()
        
        return df_15m.tail(100), df_60m.tail(50), df_120m.tail(50)
    except Exception as e:
        return None, None, None

@st.cache_data(ttl=1800)
def get_lhb_data(symbol):
    try:
        df = ak.stock_lhb_stock_detail_em()
        row = df[df["代码"] == symbol]
        if row.empty: return "近期资金潜水（无龙虎榜记录）"
        net_buy = float(row.iloc[0].get("净买额", 0)) / 10000
        return f"异动原因: {row.iloc[0].get('上榜原因', '未知')} | 净买入: {net_buy:.2f}万元"
    except: return "龙虎榜通道静默"

# ================= 技术指标与 MTF 引擎 =================
def add_indicators(df):
    df["ema_short"] = df["close"].ewm(span=ema_short).mean()
    df["ema_mid"] = df["close"].ewm(span=ema_mid).mean()
    df["ema_long"] = df["close"].ewm(span=ema_long).mean()
    df["macd"] = df["close"].ewm(span=12).mean() - df["close"].ewm(span=26).mean()
    df["macd_signal"] = df["macd"].ewm(span=9).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    df["rsi14"] = 100 - (100 / (1 + (gain / loss.replace(0, pd.NA))))
    df["atr14"] = (df["high"] - df["low"]).rolling(14).mean()
    return df

def analyze_tf(df, name):
    if df is None or len(df) < 20: return f"{name}: 样本不足"
    latest = df.iloc[-1]
    bias = "偏多" if latest["close"] > df["close"].rolling(20).mean().iloc[-1] and latest["macd"] > latest["macd_signal"] else "偏空"
    return f"{name}: {bias} (RSI: {latest['rsi14']:.1f})"

# ================= AI 辩论引擎 =================
def call_ai_committee(prompt_data):
    if not api_key: return "❌ 未检测到 API_KEY"
    client = Groq(api_key=api_key)
    
    system_prompt = """你现在是一个量化基金的投研委员会。请以【多头代表】、【空头代表】、【首席风控官】三个角色的口吻，对给定的股票数据进行深度剖析。
要求：
1. 多头代表：只看好的基本面、资金流入、支撑位和突破机会。
2. 空头代表：疯狂挑刺，寻找顶背离、套牢盘、资金流出迹象。
3. 首席风控官：总结双方观点，给出最冷酷、客观的【最终交易计划】（包含具体入场区间和止损位）。
输出格式清晰，直接切入正题，禁止废话。"""

    try:
        completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt_data}
            ],
            model=selected_model,
            temperature=0.5,
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"AI 节点故障: {e}"

# ================= 图表渲染 =================
def build_advanced_chart(df):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.05)
    fig.add_trace(go.Candlestick(x=df["date"], open=df["open"], high=df["high"], low=df["low"], close=df["close"], name="K线"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df["date"], y=df["ema_short"], line=dict(color='orange', width=1), name=f"EMA{ema_short}"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df["date"], y=df["ema_long"], line=dict(color='blue', width=1), name=f"EMA{ema_long}"), row=1, col=1)
    
    colors = ['red' if row['close'] < row['open'] else 'green' for _, row in df.iterrows()]
    fig.add_trace(go.Bar(x=df["date"], y=df["volume"], marker_color=colors, name="成交量"), row=2, col=1)
    fig.update_layout(height=600, xaxis_rangeslider_visible=False, template="plotly_white", margin=dict(l=10, r=10, t=10, b=10))
    return fig

# ================= UI 展现 =================
temp = get_market_temperature()
if temp:
    st.markdown("### 🌡️ 市场情绪温度计")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("情绪温度", f"{temp['score']:.1f} °C", "过热" if temp['score']>70 else "冰点" if temp['score']<30 else "温和")
    c2.metric("上涨家数", temp["up"], f"涨停: {temp['limit_up']}")
    c3.metric("下跌家数", temp["down"], f"跌停: {temp['limit_down']}")
    c4.metric("市场赚钱效应", "强" if temp['score'] > 55 else "弱")
    st.divider()

st.markdown("### 🎯 精确打击雷达")
col1, col2 = st.columns([1, 2])
with col1:
    symbol_input = st.text_input("目标代码 (严格 6 位)", placeholder="例: 000001")
    analyze_btn = st.button("⚡ 启动多维解构引擎", type="primary", use_container_width=True)

if analyze_btn:
    if len(symbol_input.strip()) != 6:
        st.error("⚠️ 协议拦截：为确保游资与链上数据穿透的绝对精确，请输入严格的 6 位数字代码。")
    else:
        with st.spinner("正在穿透底层数据链路..."):
            quote = get_stock_quote(symbol_input)
            df_kline = get_kline(symbol_input)
            df_15m, df_60m, df_120m = get_intraday_data(symbol_input)
            lhb = get_lhb_data(symbol_input)
            
        if not quote or df_kline is None:
            st.error("📡 标的资产捕获失败，请检查代码或网络环境。")
        else:
            df_kline = add_indicators(df_kline)
            if df_15m is not None:
                df_15m = add_indicators(df_15m)
                df_60m = add_indicators(df_60m)
                df_120m = add_indicators(df_120m)
            
            latest = df_kline.iloc[-1]
            
            # 渲染顶部指标
            k1, k2, k3, k4 = st.columns(4)
            k1.metric(f"{quote['name']} ({symbol_input})", f"{quote['price']:.2f}", f"{quote['pct']:.2f}%")
            k2.metric("当前换手率", f"{quote['turnover']:.2f}%")
            k3.metric("日线 RSI", f"{latest['rsi14']:.1f}")
            k4.metric("游资龙虎榜", "异动触发" if "净买入" in lhb else "静默", help=lhb)
            
            st.info(f"🐲 **资金追踪口径**：{lhb}")
            
            # 图表与MTF
            st.plotly_chart(build_advanced_chart(df_kline), use_container_width=True)
            
            st.markdown("#### ⏱️ MTF 多周期共振矩阵")
            m1, m2, m3 = st.columns(3)
            m1.code(analyze_tf(df_15m, "15分钟级别"))
            m2.code(analyze_tf(df_60m, "60分钟级别"))
            m3.code(analyze_tf(df_120m, "120分钟级别"))
            
            # 呼叫 AI 投研委员会
            st.markdown("#### 🧠 AI 投研委员会 (多空博弈沙盘)")
            with st.spinner("投研委员会激烈辩论中..."):
                prompt_data = f"""
标的: {quote['name']} ({symbol_input})
现价: {quote['price']} (涨跌幅: {quote['pct']}%)
换手率: {quote['turnover']}%
龙虎榜数据: {lhb}
日线指标: RSI={latest['rsi14']:.1f}, MACD={latest['macd']:.3f}, EMA20={latest['ema_short']:.2f}
多周期状态: 
- 15m: {analyze_tf(df_15m, '15m')}
- 60m: {analyze_tf(df_60m, '60m')}
- 120m: {analyze_tf(df_120m, '120m')}
基于以上真实数据，开始推演。
"""
                debate_result = call_ai_committee(prompt_data)
                st.markdown(debate_result)
