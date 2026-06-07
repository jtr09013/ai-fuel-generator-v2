import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
import google.generativeai as genai
from openai import OpenAI
from duckduckgo_search import DDGS

# --- 核心軍師模組 ---

def search_web(query):
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=3))
    return str(results)

def analyst_ai(data):
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-3.5-flash')
    news = search_web("美股與台股今日重點財經新聞")
    response = model.generate_content(f"請分析這些數據與新聞，給出專業觀點: {data} \n 新聞參考: {news}")
    return response.text

def critic_ai(analysis):
    client = OpenAI(api_key=st.secrets["DEEPSEEK_API_KEY"], base_url="https://api.deepseek.com")
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "你是一位專業的風險評估官，請針對分析官的報告進行嚴苛的邏輯審查，點出數據中可能存在的盲點。"},
            {"role": "user", "content": f"分析官報告: {analysis}"}
        ]
    )
    return response.choices[0].message.content
    
# 網頁基本設定
st.set_page_config(page_title="AI 數據燃料生產器 v4.4", layout="wide")
st.title("🚀 AI 財經數據燃料生產器 (台美精準分流版)")

# --- 數據抓取函式區 ---
def get_tw_index_data():
    data = {"taiex_p": 0.0, "taiex_c": 0.0, "taiex_pct": 0.0, "taiex_v": "待計算", "otc_p": 0.0, "otc_c": 0.0, "otc_pct": 0.0, "otc_v": "待確認"}
    try:
        taiex = yf.Ticker("^TWII").history(period="2d")
        if not taiex.empty:
            latest = taiex.iloc[-1]
            data["taiex_p"] = latest['Close']
            data["taiex_c"] = latest['Close'] - latest['Open']
            data["taiex_pct"] = (data["taiex_c"] / latest['Open']) * 100
        otc = yf.Ticker("^TWOII").history(period="2d")
        if not otc.empty:
            latest = otc.iloc[-1]
            data["otc_p"] = latest['Close']
            data["otc_c"] = latest['Close'] - latest['Open']
            data["otc_pct"] = (data["otc_c"] / latest['Open']) * 100
    except: pass
    return data

def get_us_index_data():
    indices = {"DOW": "^DJI", "NAS": "^IXIC", "SPX": "^GSPC", "SOX": "^SOX"}
    data = {}
    for name, ticker in indices.items():
        try:
            df = yf.Ticker(ticker).history(period="2d")
            if not df.empty:
                latest = df.iloc[-1]
                chg = latest['Close'] - latest['Open']
                pct = (chg / latest['Open']) * 100
                data[name] = {"p": latest['Close'], "c": chg, "pct": pct, "h": latest['High'], "l": latest['Low']}
            else: data[name] = {"p": 0.0, "c": 0.0, "pct": 0.0, "h": 0.0, "l": 0.0}
        except: data[name] = {"p": 0.0, "c": 0.0, "pct": 0.0, "h": 0.0, "l": 0.0}
    return data

def get_macro_raw():
    macro = {"WTI": 0.0, "WTI_CHG": 0.0, "US10Y": 0.0, "US10Y_CHG_BPS": 0.0, "DXY": 0.0, "DXY_CHG": 0.0}
    try:
        wti = yf.Ticker("CL=F").history(period="2d")
        if not wti.empty:
            latest = wti.iloc[-1]
            macro["WTI"] = latest['Close']
            macro["WTI_CHG"] = ((latest['Close'] - latest['Open']) / latest['Open']) * 100
        tnx = yf.Ticker("^TNX").history(period="2d")
        if len(tnx) >= 2:
            macro["US10Y"] = tnx['Close'].iloc[-1]
            macro["US10Y_CHG_BPS"] = (tnx['Close'].iloc[-1] - tnx['Close'].iloc[-2]) * 100
        dxy = yf.Ticker("DX-Y.NYB").history(period="2d")
        if not dxy.empty:
            latest = dxy.iloc[-1]
            macro["DXY"] = latest['Close']
            macro["DXY_CHG"] = ((latest['Close'] - latest['Open']) / latest['Open']) * 100
    except: pass
    return macro

def get_vix_data():
    try:
        vix = yf.Ticker("^VIX").history(period="2d")
        if not vix.empty:
            latest = vix.iloc[-1]
            return latest['Close'], (latest['Close'] - latest['Open'])
    except: pass
    return 0.0, 0.0

def get_yahoo_news_titles(ticker, limit=1):
    try:
        stock = yf.Ticker(ticker)
        news_list = stock.news[:limit]
        return "、".join([n.get('title', '').strip() for n in news_list if n.get('title')])
    except: return ""

# --- 介面區 ---
tab1, tab2, tab3 = st.tabs(["🟢 台灣股市", "🔵 美國股市", "🔍 個股單抓"])

with tab1:
    if st.button("🔥 產生台股數據包"):
        idx = get_tw_index_data()
        st.code(f"TAIEX: {idx['taiex_p']:.2f} | OTC: {idx['otc_p']:.2f}", language="text")

with tab2:
    if st.button("🔥 產生美股數據包"):
        us_idx = get_us_index_data()
        st.code(f"DOW: {us_idx['DOW']['p']:.2f} | NAS: {us_idx['NAS']['p']:.2f}", language="text")

# --- 軍師團決策支援 ---
st.divider()
st.subheader("🤖 軍師團決策支援")
if "context_data" not in st.session_state: st.session_state.context_data = ""

st.session_state.context_data = st.text_area("貼入數據燃料包：", value=st.session_state.context_data, height=150)

if st.button("召喚軍師團"):
    if st.session_state.context_data:
        with st.status("研議中...", expanded=True):
            st.session_state.analysis_a = analyst_ai(st.session_state.context_data)
            st.session_state.final_verdict = critic_ai(st.session_state.analysis_a)
            st.session_state.show_revision = True
            st.rerun()

if st.session_state.get("show_revision"):
    st.write("### 📊 初步分析", st.session_state.analysis_a)
    st.info(f"### 🔍 審查意見\n{st.session_state.final_verdict}")
    if st.button("🔄 修正報告"):
        st.session_state.new_analysis_a = analyst_ai(f"根據質疑修正: {st.session_state.final_verdict}")
        st.rerun()

if st.session_state.get("new_analysis_a"):
    st.write("### 🔄 最終報告", st.session_state.new_analysis_a)
    if st.button("🔍 輸出 JSON"):
        st.session_state.machine_json = critic_ai("輸出 JSON 格式: " + st.session_state.new_analysis_a)
        st.rerun()

if st.session_state.get("machine_json"):
    st.code(st.session_state.machine_json, language='json')
