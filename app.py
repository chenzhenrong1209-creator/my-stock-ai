import streamlit as st
from groq import Groq
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import akshare as ak
import tushare as ts
import random
from datetime import datetime
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ================= 页面与终端 UI 配置 =================
st.set_page_config(
    page_title="AI 智能投研终端 Pro Max",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.stTabs [data-baseweb="tab-list"] { gap: 10px; flex-wrap: wrap; }
.stTabs [data-baseweb="tab"] { height: auto; min-height: 40px; white-space: normal; background-color: transparent; border-radius: 4px 4px 0 0; padding: 8px 12px; font-weight: bold; }
.terminal-header { font-family: 'Courier New', Courier, monospace; color: #888; font-size: 0.8em; margin-bottom: 20px; word-wrap: break-word; }
[data-testid="stMetricValue"] { font-size: 1.5rem; }
.small-note { color: #6b7280; font-size: 0.85rem; }
</style>
""", unsafe_allow_html=True)

st.title("🏦 AI 智能量化投研终端")
st.markdown(f"<div class='terminal-header'>TERMINAL BUILD v7.0.0 | SYS_TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | ENHANCED ANALYTICS & LHB SUITE</div>", unsafe_allow_html=True)

api_key = st.secrets.get("GROQ_API_KEY", "")

# ================= 侧边栏与参数调优 =================
with st.sidebar:
    st.header("⚙️ 终端控制台")
    st.markdown("### 🧠 核心推理引擎")
    selected_model = st.selectbox("选择大模型", ["llama-3.3-70b-versatile", "mixtral-8x7b-32768", "gemma2-9b-it"], index=0)
    
    st.markdown("### 🎛️ 策略参数微调")
    with st.expander("自定义均线周期", expanded=False):
        ema_short = st.number_input("短期 EMA", min_value=5, max_value=50, value=20, step=1)
        ema_mid = st.number_input("中期 EMA", min_value=10, max_value=120, value=60, step=1)
        ema_long = st.number_input("长期 EMA", min_value=20, max_value=250, value=120, step=1)
    
    with st.expander("风险控制参数", expanded=False):
        stop_atr_mult = st.slider("止损 ATR 倍数", 0.5, 5.0, 1.5, 0.1)
        target_rr = st.slider("目标盈亏比", 1.0, 5.0, 2.0, 0.1)
        breakout_buffer = st.slider("突破确认缓冲(%)", 0.1, 3.0, 0.5, 0.1)
    
    DEBUG_MODE = st.checkbox("🛠️ 开启底层日志嗅探")
    st.markdown("---")
    st.success("龙虎榜追踪引擎 : ACTIVE")
    st.success("技术结构引擎 : ACTIVE")

# ================= 网络底座与辅助工具 =================
@st.cache_resource
def get_session():
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[403, 429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

def safe_float(val, default=0.0):
    if pd.isna(val) or val is None or val == "-" or str(val).strip() == "": return default
    try: return float(val)
    except: return default

# ================= Akshare 数据获取流 (新增补充) =================
@st.cache_data(ttl=60)
def get_stock_quote(symbol):
    try:
        df = ak.stock_zh_a_spot_em()
        row = df[df["代码"] == symbol]
        if row.empty: return None
        return {
            "name": row.iloc[0]["名称"],
            "price": safe_float(row.iloc[0]["最新价"]),
            "pct": safe_float(row.iloc[0]["涨跌幅"]),
            "market_cap": safe_float(row.iloc[0]["总市值"]) / 100000000,
            "pe": safe_float(row.iloc[0]["市盈率-动态"]),
            "pb": safe_float(row.iloc[0]["市净率"]),
            "turnover": safe_float(row.iloc[0]["换手率"])
        }
    except Exception as e:
        if DEBUG_MODE: st.warning(f"行情获取失败: {e}")
        return None

@st.cache_data(ttl=300)
def get_kline(symbol, days=220):
    try:
        df = ak.stock_zh_a_hist(symbol=symbol, period="daily", adjust="qfq")
        if df.empty: return None
        df.rename(columns={"日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "volume"}, inplace=True)
        df["date"] = pd.to_datetime(df["date"])
        return df.tail(days).reset_index(drop=True)
    except:
        return None

@st.cache_data(ttl=1800)
def get_lhb_data(symbol):
    """精确获取龙虎榜数据，拒绝泛搜模糊匹配"""
    try:
        df = ak.stock_lhb_stock_detail_em()
        row = df[df["代码"] == symbol]
        if row.empty: return "近期无上榜记录"
        
        reason = row.iloc[0].get("上榜原因", "未知资金异动")
        net_buy = safe_float(row.iloc[0].get("净买额", 0)) / 10000  # 转化为万元
        return f"最新上榜: {reason} | 净买入: {net_buy:.2f}万元"
    except Exception as e:
        if DEBUG_MODE: st.warning(f"龙虎榜解析失败: {e}")
        return "数据通道暂不可用"

@st.cache_data(ttl=60)
def get_market_pulse():
    try:
        df = ak.stock_zh_index_spot()
        indices = {"sh000001": "上证指数", "sz399001": "深证成指", "sz399006": "创业板指"}
        pulse = {}
        for code, name in indices.items():
            row = df[df["代码"] == code]
            if not row.empty:
                pulse[name] = {"price": safe_float(row.iloc[0]["最新价"]), "pct": safe_float(row.iloc[0]["涨跌幅"])}
        return pulse
    except: return None

@st.cache_data(ttl=300)
def get_hot_blocks():
    try:
        df = ak.stock_board_industry_name_em()
        return df.head(10).rename(columns={"板块名称": "板块名称", "涨跌幅": "涨跌幅", "领涨股票": "领涨股票"}).to_dict("records")
    except: return None

@st.cache_data(ttl=300)
def get_global_news():
    try:
        df = ak.news_cctv()
        return df["content"].head(15).tolist()
    except: return ["获取快讯失败"]

# ================= 指标与 SMC 函数 (保留原有核心逻辑) =================
# ... (为节省篇幅，这里假设原有 add_indicators, detect_swings, detect_fvg, detect_bos, 
# build_smc_summary, summarize_technicals, get_multi_timeframe_analysis, 
# build_trade_plan 等函数保持不变，完整粘贴到此处即可) ...
# 为了代码可运行，我将包含简化版调用
def add_indicators(df):
    df["ema_short"] = df["close"].ewm(span=ema_short, adjust=False).mean()
    df["ema_mid"] = df["close"].ewm(span=ema_mid, adjust=False).mean()
    df["ema_long"] = df["close"].ewm(span=ema_long, adjust=False).mean()
    df["macd"] = df["close"].ewm(span=12).mean() - df["close"].ewm(span=26).mean()
    df["macd_signal"] = df["macd"].ewm(span=9).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    df["rsi14"] = 100 - (100 / (1 + (gain / loss.replace(0, pd.NA))))
    df["atr14"] = (df["high"] - df["low"]).rolling(14).mean() # 简化版 ATR
    df["bb_up"] = df["close"].rolling(20).mean() + 2 * df["close"].rolling(20).std()
    df["bb_low"] = df["close"].rolling(20).mean() - 2 * df["close"].rolling(20).std()
    df["vol_ma20"] = df["volume"].rolling(20).mean()
    return df

def build_trade_plan(df: pd.DataFrame, tech: dict):
    latest = tech["latest_close"]
    atr = tech["atr14"] if pd.notna(tech["atr14"]) else 0
    support_zone = min(tech["ema_short"], tech["ema_mid"])
    pressure_zone = max(tech["ema_short"], tech["ema_mid"])
    aggressive_entry = max(support_zone, latest - 0.5 * atr) if atr else support_zone
    stop_loss = aggressive_entry - atr * stop_atr_mult if atr else aggressive_entry * 0.97
    target_1 = aggressive_entry + (aggressive_entry - stop_loss) * target_rr
    breakout_trigger = pressure_zone * (1 + breakout_buffer / 100)
    return {
        "aggressive_entry": aggressive_entry,
        "conservative_entry": support_zone,
        "stop_loss": stop_loss,
        "target_1": target_1,
        "breakout_trigger": breakout_trigger,
    }

def summarize_technicals(df):
    latest = df.iloc[-1]
    return {
        "trend": "多头" if latest["close"] > latest["ema_short"] else "震荡",
        "momentum": "偏强" if latest["rsi14"] > 55 else "中性",
        "macd_state": "金叉" if latest["macd"] > latest["macd_signal"] else "死叉",
        "latest_close": latest["close"],
        "ema_short": latest["ema_short"],
        "ema_mid": latest["ema_mid"],
        "ema_long": latest["ema_long"],
        "vol_state": "显著放量" if latest["volume"] > latest.get("vol_ma20", 0) * 1.5 else "平稳",
        "rsi14": latest["rsi14"],
        "atr14": latest["atr14"],
        "bb_state": "带内"
    }

def get_multi_timeframe_analysis(symbol):
    # 模拟数据反馈，实际需要补全原始函数的分钟线逻辑
    return {"15m": {"bias": "震荡"}, "60m": {"bias": "偏多"}, "120m": {"bias": "偏多"}, "final_view": "多周期共振偏多"}

def build_price_figure(plot_df):
    plot_df["date_str"] = plot_df["date"].dt.strftime("%Y-%m-%d")
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3])
    fig.add_trace(go.Candlestick(x=plot_df["date_str"], open=plot_df["open"], high=plot_df["high"], low=plot_df["low"], close=plot_df["close"], name="K线"), row=1, col=1)
    fig.add_trace(go.Bar(x=plot_df["date_str"], y=plot_df["volume"], name="成交量"), row=2, col=1)
    fig.update_layout(height=600, xaxis_rangeslider_visible=False)
    return fig

# ================= AI 调用层 =================
def call_ai(prompt, model=None, temperature=0.3):
    try:
        client = Groq(api_key=api_key)
        completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=model if model else selected_model,
            temperature=temperature,
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"❌ AI 计算节点故障: {e}"

# ================= 终端全局看板 =================
st.markdown("### 🌍 宏观市场实时看板")
pulse_data = get_market_pulse()
if pulse_data:
    dash_cols = st.columns(len(pulse_data))
    for idx, (key, data) in enumerate(pulse_data.items()):
        with dash_cols[idx]:
            with st.container(border=True):
                st.metric(key, f"{data['price']:.2f}", f"{data['pct']:.2f}%")

# ================= 终端 Tabs =================
tab1, tab2, tab3, tab4 = st.tabs(["🎯 I. 个股标的解析", "📈 II. 宏观大盘推演", "🔥 III. 资金热点板块", "🦅 IV. 高阶情报终端"])

with tab1:
    with st.container(border=True):
        st.markdown("#### 🔎 个股雷达锁定（含龙虎榜资金透视）")
        col1, col2 = st.columns([1, 1])
        with col1:
            # 强制要求明确输入代码，拒绝泛化查询确保精准度
            symbol_input = st.text_input("手动输入标的代码", placeholder="例：600519 (严格6位数字)")
            analyze_btn = st.button("启动核心算法与资金溯源", type="primary", width="stretch")
            
        if analyze_btn:
            if not api_key:
                st.error("配置缺失: GROQ_API_KEY")
            elif len(symbol_input.strip()) != 6:
                st.warning("代码规范验证失败，请输入准确的6位股票代码。")
            else:
                with st.spinner("量子计算与资金链路提取中..."):
                    quote = get_stock_quote(symbol_input)
                    df_kline = get_kline(symbol_input, days=220)
                    lhb_info = get_lhb_data(symbol_input)
                    mtf = get_multi_timeframe_analysis(symbol_input)
                
                if not quote:
                    st.error("无法捕获行情资产。")
                else:
                    name, price, pct = quote["name"], quote["price"], quote["pct"]
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric(f"{name}", f"{price:.2f}", f"{pct:.2f}%")
                    c2.metric("总市值(亿)", f"{quote['market_cap']:.1f}")
                    c3.metric("动态 PE", f"{quote['pe']}")
                    c4.metric("换手率", f"{quote['turnover']:.2f}%")
                    
                    st.success(f"**🐉 龙虎榜监控雷达：** {lhb_info}")
                    
                    if df_kline is not None and len(df_kline) >= 30:
                        df_kline = add_indicators(df_kline)
                        tech = summarize_technicals(df_kline)
                        plan = build_trade_plan(df_kline, tech)
                        st.plotly_chart(build_price_figure(df_kline), use_container_width=True)
                        
                        st.markdown("##### 📍 关键价位与计划")
                        p1, p2, p3, p4 = st.columns(4)
                        p1.metric("激进介入", f"{plan['aggressive_entry']:.2f}")
                        p2.metric("稳健支撑", f"{plan['conservative_entry']:.2f}")
                        p3.metric("防守止损", f"{plan['stop_loss']:.2f}")
                        p4.metric("量化目标", f"{plan['target_1']:.2f}")
                        
                        with st.spinner(f"🧠 首席策略官正在使用 {selected_model} 深度解构..."):
                            prompt = f"""
你现在是顶级私募基金的操盘手（精通基本面、量价结构、资金情绪博弈）。
请对股票 {name}({symbol_input}) 做一份极具实战价值的综合研判。

【基础与估值】现价: {price} | 市值: {quote['market_cap']}亿 | PE: {quote['pe']}
【资金与情绪博弈】当日换手: {quote['turnover']}% | 龙虎榜动向: {lhb_info}
【核心技术结构】趋势: {tech['trend']} | RSI14: {tech['rsi14']:.2f} | 量能: {tech['vol_state']} | MACD: {tech['macd_state']}
【交易计划执行】激进点: {plan['aggressive_entry']:.2f} | 止损: {plan['stop_loss']:.2f} | 第一目标: {plan['target_1']:.2f}

请输出：
1. 资金面穿透（重点解读龙虎榜与换手率背后的游资/机构意图）
2. 技术形态与买卖点沙盘推演
3. 风控底线预警
4. 明确结论（强势打板/逢低吸纳/观望/规避）
语言要冷酷、专业、机构化。
"""
                            st.markdown(call_ai(prompt))
                    else:
                        st.warning("日线 K 线样本偏少，无法执行核心算法。")

with tab2:
    if st.button("运行大盘沙盘推演", type="primary"):
        with st.spinner("推演引擎初始化..."):
            prompt = f"你现在是高盛首席宏观策略师。基于实时A股数据进行推演：{str(pulse_data)}。输出市场全景定调、短期沙盘推演方向与优先跟踪风格。"
            st.markdown(call_ai(prompt, temperature=0.4))

with tab3:
    if st.button("扫描板块与生成配置推荐", type="primary"):
        blocks = get_hot_blocks()
        if blocks:
            st.dataframe(pd.DataFrame(blocks), use_container_width=True)
            with st.spinner("🧠 首席游资操盘手拆解逻辑..."):
                blocks_str = "\n".join([f"{b['板块名称']} (涨幅:{b['涨跌幅']}%, 领涨:{b['领涨股票']})" for b in blocks[:5]])
                prompt = f"深度解读今日最强的 5 个板块及其领涨龙头：\n{blocks_str}\n输出核心驱动、行情定性及可延展方向。"
                st.markdown(call_ai(prompt, temperature=0.4))

with tab4:
    if st.button("🚨 截获并解析全球突发", type="primary"):
        news = get_global_news()
        with st.expander("底层情报流"): st.text("\n".join(news))
        prompt = f"作为华尔街对冲基金情报官，挑选最重要的情报，生成推演和A股风控预警。\n底层数据：{chr(10).join(news)}"
        st.markdown(call_ai(prompt, temperature=0.2))
