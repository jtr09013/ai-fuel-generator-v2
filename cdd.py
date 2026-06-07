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
st.caption("本系統已整合「台股個股前日收盤價 (PREV_CLOSE) 錨點機制」與「單一個股台美市場 AI 拷問指令自動分流邏輯」。")

# --- 核心數據抓取函式 ---
def get_tw_index_data():
    data = {
        "taiex_p": 0.0, 
        "taiex_c": 0.0, 
        "taiex_pct": 0.0, 
        "taiex_v": "待計算",
        "otc_p": 0.0, 
        "otc_c": 0.0, 
        "otc_pct": 0.0, 
        "otc_v": "待確認"
    }
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
    except:
        pass
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
                data[name] = {
                    "p": latest['Close'], "c": chg, "pct": pct,
                    "h": latest['High'], "l": latest['Low']
                }
            else:
                data[name] = {"p": 0.0, "c": 0.0, "pct": 0.0, "h": 0.0, "l": 0.0}
        except:
            data[name] = {"p": 0.0, "c": 0.0, "pct": 0.0, "h": 0.0, "l": 0.0}
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
            chg_pct = tnx['Close'].iloc[-1] - tnx['Close'].iloc[-2]
            macro["US10Y_CHG_BPS"] = chg_pct * 100  
            
        dxy = yf.Ticker("DX-Y.NYB").history(period="2d")
        if not dxy.empty:
            latest = dxy.iloc[-1]
            macro["DXY"] = latest['Close']
            macro["DXY_CHG"] = ((latest['Close'] - latest['Open']) / latest['Open']) * 100
    except:
        pass
    return macro

def get_vix_data():
    try:
        vix = yf.Ticker("^VIX").history(period="2d")
        if not vix.empty:
            latest = vix.iloc[-1]
            return latest['Close'], (latest['Close'] - latest['Open'])
    except:
        pass
    return 0.0, 0.0

def get_yahoo_news_titles(ticker, limit=1):
    try:
        stock = yf.Ticker(ticker)
        news_list = stock.news[:limit]
        titles = [n.get('title', '').strip() for n in news_list if n.get('title')]
        return "、".join([f"{t}" for t in titles]) if titles else ""
    except:
        return ""

# --- 介面分流頁籤 ---
tab1, tab2, tab3 = st.tabs(["🟢 台灣股市大包", "🔵 美國股市大包", "🔍 個股獨立單抓"])

# ==========================================
# 🟢 頁籤一：台股大盤 + 關注個股
# ==========================================
with tab1:
    st.header("台股大盤 + 關注個股綜合燃料包")
    tw_time_mode = st.radio("台股市場時間狀態", ["☀️ 盤中即時模式 (INTRA)", "🌙 盤後清算模式 (AFTER)"], horizontal=True)
    tw_watchlist_input = st.text_input("輸入關注台股代號（用逗號隔開）", value="2317, 3016")
    
    if st.button("🔥 產生台股融合數據包"):
        with st.spinner("正在打包台股數據..."):
            idx = get_tw_index_data()
            macro = get_macro_raw()
            
            watchlist_text = ""
            ticker_list = [t.strip() for t in tw_watchlist_input.split(",") if t.strip()]
            
            for t in ticker_list:
                formatted_ticker = f"{t}.TW"
                stock = yf.Ticker(formatted_ticker)
                hist = stock.history(period="2d")
                info = stock.info
                if not hist.empty:
                    latest = hist.iloc[-1]
                    chg = latest['Close'] - latest['Open']
                    pct = (chg / latest['Open']) * 100
                    
                    # 🔴 核心優化：從現有 2d 歷史數據中安全撈取「前日收盤價」作為 AI 計算錨點
                    prev_close = hist['Close'].iloc[-2] if len(hist) >= 2 else latest['Open']
                    
                    # 換算「萬張」公式 = Volume / 10000000
                    vol_tw_val = latest['Volume'] / 10000000
                    vol_w = f"{vol_tw_val:.2f}萬張"
                    
                    name = info.get('shortName', f"個股_{t}")
                    news_summary = get_yahoo_news_titles(formatted_ticker, limit=1)
                    
                    if "盤中即時" in tw_time_mode:
                        watchlist_text += f"{name}({t}): NOW: {latest['Close']:.2f} | PREV_CLOSE: {prev_close:.2f} | CHG: {chg:+.2f} ({pct:+.2f}%) | EST_VOL: {vol_w}\n"
                    else:
                        news_str = f" | NEWS: {news_summary}" if news_summary else ""
                        watchlist_text += f"{name}({t}): CLOSE: {latest['Close']:.2f} | PREV_CLOSE: {prev_close:.2f} | CHG: {chg:+.2f} ({pct:+.2f}%) | VOL: {vol_w}{news_str} | FOREIGN_NET: \n"
            
            if "盤中即時" in tw_time_mode:
                final_tw = f"""<TW_MARKET_OVERVIEW_INTRA>
TAIEX_NOW: {idx['taiex_p']:.2f} | CHG: {idx['taiex_c']:+.2f} ({idx['taiex_pct']:+.2f}%) | EST_VOL: {idx['taiex_v']}
OTC_NOW: {idx['otc_p']:.2f} | CHG: {idx['otc_c']:+.2f} ({idx['otc_pct']:+.2f}%) | EST_VOL: {idx['otc_v']}
</TW_MARKET_OVERVIEW_INTRA>

<STOCK_WATCHLIST_INTRA>
{watchlist_text.strip()}
</STOCK_WATCHLIST_INTRA>

<MACRO_EVENTS_INTRA>
DXY: {macro['DXY']:.2f} ({macro['DXY_CHG']:+.2f}%)
OIL_WTI: {macro['WTI']:.2f} ({macro['WTI_CHG']:+.1f}%)
MIDEAST: 美伊衝突升溫，談判仍陷僵局
FOMC_WATCH: 7月升息機率約11% (請AI聯網交互驗證)
</MACRO_EVENTS_INTRA>"""
            else:
                final_tw = f"""<TW_MARKET_OVERVIEW_AFTER>
TAIEX_CLOSE: {idx['taiex_p']:.2f} | CHG: {idx['taiex_c']:+.2f} ({idx['taiex_pct']:+.2f}%) | VOL: {idx['taiex_v']}
OTC_CLOSE: {idx['otc_p']:.2f} | CHG: {idx['otc_c']:+.2f} ({idx['otc_pct']:+.2f}%) | VOL: {idx['otc_v']}
ADVANCE_DECLINE_RATIO: 
# 註解：⚠️[盤後已公告，請AI強制聯網搜尋今日最新的上市與櫃買漲跌家數比並補上]
</TW_MARKET_OVERVIEW_AFTER>

<TW_INSTITUTIONAL_CHIPS_AFTER>
FOREIGN_NET_TWD: 
INVESTMENT_TRUST_NET_TWD: 
DEALERS_TOTAL_NET_TWD: 
FUTURES_NET_SHORT: 
# 註解：📊 ⚠️[盤後已公告，請AI強制聯網搜尋補上今日最新三大法人買賣超與外資台指期淨空單口數]
</TW_INSTITUTIONAL_CHIPS_AFTER>

<TW_MARGIN_BALANCE_AFTER>
MARGIN_PURCHASE_CHG: 
SHORT_SALE_CHG: 
MARGIN_BALANCE_TOTAL: 
# 註解：💰 ⚠️[盤後已公告，請AI強制聯網搜尋補上今日最新融資增減、融券增減與融資餘額總計]
</TW_MARGIN_BALANCE_AFTER>

<STOCK_WATCHLIST_AFTER>
{watchlist_text.strip()}
# 註解：🔍 個股若無重大新聞則留空；請AI聯網補上今日三大法人對上述個股的買賣超張數
</STOCK_WATCHLIST_AFTER>

<MACRO_EVENTS_AFTER>
DXY: {macro['DXY']:.2f} ({macro['DXY_CHG']:+.2f}%)
OIL_WTI: {macro['WTI']:.2f} ({macro['WTI_CHG']:+.1f}%)
US_10Y_YIELD: {macro['US10Y']:.2f}%
# 註解：🌍 ⚠️[請AI強制聯網搜尋最新國際總經焦點與地緣政治談判局勢]
</MACRO_EVENTS_AFTER>"""

            st.success("🎉 台股燃料包輸出成功！")
            st.code(final_tw, language="text")

# ==========================================
# 🔵 頁籤二：美股大盤 + 關注個股
# ==========================================
with tab2:
    st.header("美股大盤 + 關注個股綜合燃料包")
    us_time_mode = st.radio("美股市場時間狀態", ["☀️ 盤中即時模式 (INTRA)", "🌙 盤後清算模式 (AFTER)"], horizontal=True)
    us_watchlist_input = st.text_input("輸入關注美股代號（用逗號隔開）", value="NVDA, MU, TSM")
    
    if st.button("🔥 產生美股融合數據包"):
        with st.spinner("正在打包美股數據..."):
            us_idx = get_us_index_data()
            macro = get_macro_raw()
            vix_p, vix_c = get_vix_data()
            
            us_watchlist_text = ""
            us_ticker_list = [u.strip().upper() for u in us_watchlist_input.split(",") if u.strip()]
            
            for ut in us_ticker_list:
                stock = yf.Ticker(ut)
                hist = stock.history(period="2d")
                info = stock.info
                if not hist.empty:
                    latest = hist.iloc[-1]
                    chg_pct = ((latest['Close'] - latest['Open']) / latest['Open']) * 100
                    
                    # 美股 1億股 = 10000萬股。故直接除以 10,000 即為「萬股」
                    vol_val = latest['Volume'] / 10000
                    vol_m = f"{vol_val:,.0f}萬股" if vol_val >= 1000 else f"{vol_val:.2f}萬股"
                    
                    if "盤中即時" in us_time_mode:
                        inst_str = " | INST_OWN_PCT: 約65%" if ut == "NVDA" else ""
                        us_watchlist_text += f"{ut}: PRICE: {latest['Close']:.2f} | CHG: {chg_pct:+.2f}% | VOL: {vol_m}{inst_str}\n"
                    else:
                        news_summary = get_yahoo_news_titles(ut, limit=1)
                        news_str = f" | NEWS: {news_summary}" if news_summary else " | NEWS: "
                        inst_str = " | INST_OWN_PCT: 約65%" if ut == "NVDA" else ""
                        us_watchlist_text += f"{ut}: PRICE: {latest['Close']:.2f} | CHG: {chg_pct:+.2f}% | VOL: {vol_m}{inst_str}{news_str}\n"

            if "盤中即時" in us_time_mode:
                final_us = f"""<US_MARKET_OVERVIEW>
DOW: {us_idx['DOW']['p']:.2f} | CHG: {us_idx['DOW']['c']:+.2f} ({us_idx['DOW']['pct']:+.2f}%) | HIGH: {us_idx['DOW']['h']:.2f} | LOW: {us_idx['DOW']['l']:.2f}
NAS: {us_idx['NAS']['p']:.2f} | CHG: {us_idx['NAS']['c']:+.2f} ({us_idx['NAS']['pct']:+.2f}%)
SPX: {us_idx['SPX']['p']:.2f} | CHG: {us_idx['SPX']['c']:+.2f} ({us_idx['SPX']['pct']:+.2f}%)
SOX: {us_idx['SOX']['p']:.2f} | CHG: {us_idx['SOX']['c']:+.2f} ({us_idx['SOX']['pct']:+.2f}%)
VOL_NYSE: 約45億股 | NASDAQ: 約52億股
</US_MARKET_OVERVIEW>

<US_SENTIMENT>
VIX: {vix_p:.2f} | CHG: {vix_c:+.2f} | NOTE: 仍在歷史低位
PUT_CALL_RATIO: 1.07 | CHG: +0.618 | NOTE: 選擇權市場避險情緒顯著升溫
MARGIN_DEBT: (每月公布，FINRA報告)
SHORT_INTEREST: (每兩周公布)
</US_SENTIMENT>

<STOCK_WATCHLIST>
{us_watchlist_text.strip()}
</STOCK_WATCHLIST>

<FUTURES_COT>
LAST_REPORT: 2026-05-30
E_MINIS&P500_NET_COMMERCIAL: -125,000口 (商業空頭)
E_MINIS&P500_NONCOM_NET: +98,000口 (投機淨多頭)
NOTE: 每週五公布，下期報告預計今日傍晚(6/5)或明晨更新，反映大戶最新留倉
</FUTURES_COT>

<MACRO_EVENTS>
DXY: {macro['DXY']:.2f} | CHG: {macro['DXY_CHG']:+.2f}%
FED_RATE_EXPECT: CME FedWatch顯示7月升息機率約11%，年底前約55%
OIL_WTI: {macro['WTI']:.2f} | CHG: {macro['WTI_CHG']:+.1f}%
US_10Y_YIELD: {macro['US10Y']:.2f}% | CHG: {macro['US10Y_CHG_BPS']:+.2f}bps
MIDEAST_TALKS: 美伊衝突持續，談判陷入僵局，油價劇烈波動
</MACRO_EVENTS>"""
            else:
                final_us = f"""<US_MARKET_OVERVIEW_AFTER>
DOW: {us_idx['DOW']['p']:.2f} | CHG: {us_idx['DOW']['c']:+.2f} ({us_idx['DOW']['pct']:+.2f}%) | HIGH: {us_idx['DOW']['h']:.2f} | LOW: {us_idx['DOW']['l']:.2f}
NAS: {us_idx['NAS']['p']:.2f} | CHG: {us_idx['NAS']['c']:+.2f} ({us_idx['NAS']['pct']:+.2f}%)
SPX: {us_idx['SPX']['p']:.2f} | CHG: {us_idx['SPX']['c']:+.2f} ({us_idx['SPX']['pct']:+.2f}%)
SOX: {us_idx['SOX']['p']:.2f} | CHG: {us_idx['SOX']['c']:+.2f} ({us_idx['SOX']['pct']:+.2f}%)
VOL_NYSE: 約45億股 | NASDAQ: 約52億股
# 註解：此為最終收盤數據。
</US_MARKET_OVERVIEW_AFTER>

<US_SENTIMENT_AFTER>
VIX: {vix_p:.2f} | CHG: {vix_c:+.2f}
PUT_CALL_RATIO: 1.07 | CHG: +0.618
MARGIN_DEBT: 
SHORT_INTEREST: 
# 註解：⚠️[請AI強制聯網確認今日FINRA最新融資餘額與近兩週最新券商放空餘額數據]
</US_SENTIMENT_AFTER>

<US_STOCK_WATCHLIST_AFTER>
{us_watchlist_text.strip()}
# 註解：個股若無重大新聞則留空；請AI聯網補上今日盤後各大投行對上述個股的評級變動或重大公告。
</US_STOCK_WATCHLIST_AFTER>

<US_FUTURES_COT_AFTER>
LAST_REPORT: 2026-05-30
E_MINIS&P500_NET_COMMERCIAL: -125,000口
E_MINIS&P500_NONCOM_NET: +98,000口
# 註解：🚨[請AI強制聯網搜尋CFTC官網，確認當日最新公布的非商業與商業持倉淨變動數據]
</US_FUTURES_COT_AFTER>

<US_MACRO_EVENTS_AFTER>
DXY: {macro['DXY']:.2f} | CHG: {macro['DXY_CHG']:+.2f}%
OIL_WTI: {macro['WTI']:.2f} | CHG: {macro['WTI_CHG']:+.1f}%
US_10Y_YIELD: {macro['US10Y']:.2f}% | CHG: {macro['US10Y_CHG_BPS']:+.2f}bps
FED_RATE_EXPECT: CME FedWatch顯示7月升息機率約11%
MIDEAST_TALKS: 
# 註解：🌍[請AI強制聯網搜尋收盤後最新的國際總經、聯準會官員談話與國際衝突事件]
</US_MACRO_EVENTS_AFTER>"""

            st.success("🎉 美股燃料包輸出成功！")
            st.code(final_us, language="text")

# ==========================================
# 🔍 頁籤三：個股獨立單抓與輸出 (單獨詢問用)
# ==========================================
with tab3:
    st.header("🔍 個股獨立單抓工具")
    st.caption("當您只想針對某一檔股票單獨拷問 AI 時使用。")
    
    market_type = st.radio("股票市場類型", ["台灣股市 (TW Stock)", "美國股市 (US Stock)"], horizontal=True)
    single_ticker = st.text_input("輸入單一股票代號 (例如: 2330 或 NVDA)", value="2330").upper().strip()
    
    if st.button("⚡ 產生單一個股專屬 AI 數據包"):
        with st.spinner(f"正在抽取 {single_ticker} 的獨立數據燃料..."):
            yf_ticker = f"{single_ticker}.TW" if market_type == "台灣股市 (TW Stock)" else single_ticker
            stock = yf.Ticker(yf_ticker)
            hist = stock.history(period="5d")
            info = stock.info
            
            if not hist.empty:
                latest = hist.iloc[-1]
                chg = latest['Close'] - latest['Open']
                pct = (chg / latest['Open']) * 100
                
                # 🔴 核心優化 1：台美股個股數據與指令邏輯全面精準分流
                if market_type == "台灣股市 (TW Stock)":
                    vol_tw_single = latest['Volume'] / 10000000
                    vol_formatted = f"{vol_tw_single:.2f}萬張"
                    
                    # 強制加固台股專屬前日收盤價錨點
                    s_prev_close = hist['Close'].iloc[-2] if len(hist) >= 2 else latest['Open']
                    price_line = f"PRICE_CLOSE: {latest['Close']:.2f} | PREV_CLOSE: {s_prev_close:.2f} | OPEN: {latest['Open']:.2f} | HIGH: {latest['High']:.2f} | LOW: {latest['Low']:.2f}"
                    
                    # 台股籌碼面、分點拷問指令
                    instruction_text = "⚠️提示：此為單一個股獨立查詢。請AI強制聯網搜尋今日該個股最新的「法人買賣超籌碼面」、「主力分點進出明細」並結合最新公告給出獨立的操作建議。"
                else:
                    s_vol_val = latest['Volume'] / 10000
                    vol_formatted = f"{s_vol_val:,.0f}萬股" if s_vol_val >= 1000 else f"{s_vol_val:.2f}萬股"
                    
                    # 美股維持標準現況輸出 (不強制加註 PREV_CLOSE)
                    price_line = f"PRICE_CLOSE: {latest['Close']:.2f} | OPEN: {latest['Open']:.2f} | HIGH: {latest['High']:.2f} | LOW: {latest['Low']:.2f}"
                    
                    # 🔴 核心優化 2：美股精準專屬指令（自動略過每日三大法人與分點，改抓美股特有宏觀指標）
                    instruction_text = "⚠️提示：此為單一個股獨立查詢。請AI強制聯網搜尋該個股最新消息，並結合大盤 VIX、Put/Call Ratio、近期期權大單異動或機構持倉流向（13F 季報）給出獨立的操作建議。（註：美股無台股每日法人與分點數據，請勿虛構）。"
                
                hist_60 = stock.history(period="60d")
                ma5 = hist_60['Close'].iloc[-5:].mean() if len(hist_60) >= 5 else 0
                ma20 = hist_60['Close'].iloc[-20:].mean() if len(hist_60) >= 20 else 0
                single_news = get_yahoo_news_titles(yf_ticker, limit=3)
                
                single_packet = f"""<SINGLE_STOCK_ANALYSIS_REQUEST>
TICKER: {single_ticker}
NAME: {info.get('shortName', 'N/A')}
MARKET: {'TAIWAN' if market_type == "台灣股市 (TW Stock)" else 'USA'}

[CURRENT_SESSION]
{price_line}
CHANGE: {chg:+.2f} ({pct:+.2f}%) | VOLUME: {vol_formatted}

[TECHNICAL_SNAPSHOT]
MA_5_DAY: {ma5:.2f}
MA_20_DAY: {ma20:.2f}

[LATEST_NEWS_HEADLINES]
{single_news if single_news else '無重大新聞'}

[CHIPS_AND_EVENTS_INSTRUCTION]
{instruction_text}
</SINGLE_STOCK_ANALYSIS_REQUEST>"""
                st.success(f"🎉 {single_ticker} 專屬數據包已就緒！")
                st.code(single_packet, language="text")
            else:
                st.error("找不到該股票數據，請確認代號與市場選擇。")

# --- 軍師團決策支援模組 (取代原本結尾的接入點) ---
st.divider()
st.subheader("🤖 軍師團決策支援")

# 初始化 session_state
if "context_data" not in st.session_state: st.session_state.context_data = ""
if "show_revision" not in st.session_state: st.session_state.show_revision = False

# 1. 數據輸入框
st.session_state.context_data = st.text_area(
    "請貼入剛剛產生的數據燃料包：", 
    value=st.session_state.context_data, 
    height=200
)

# 2. 召喚與初步分析
if st.button("召喚軍師團進行分析"):
    if st.session_state.context_data:
        with st.status("軍師團研議中...", expanded=True) as status:
            analysis_a = analyst_ai(st.session_state.context_data)
            final_verdict = critic_ai(analysis_a)
            
            st.session_state.analysis_a = analysis_a
            st.session_state.final_verdict = final_verdict
            st.session_state.show_revision = True
            if "new_analysis_a" in st.session_state: del st.session_state.new_analysis_a
            if "machine_json" in st.session_state: del st.session_state.machine_json
            status.update(label="✅ 初步分析完成", state="complete")
            st.rerun()
    else:
        st.warning("請先產生並貼入數據！")

# 3. 審視初步報告與觸發修正
if st.session_state.get("show_revision", False):
    st.markdown("### 📊 初步分析報告")
    st.write(st.session_state.analysis_a)
    st.info(f"### 🔍 軍師 B 的審查意見\n{st.session_state.final_verdict}")
    
    col1, col2 = st.columns(2)
    if col1.button("🔄 要求分析官針對質疑進行修正"):
        with st.spinner("軍師修正中..."):
            prompt = f"針對質疑：{st.session_state.final_verdict}，原始數據：{st.session_state.context_data}，請補強數據並修正報告。"
            st.session_state.new_analysis_a = analyst_ai(prompt)
            st.rerun()

# 4. 修正後報告與最終機器審計
if "new_analysis_a" in st.session_state:
    st.markdown("---")
    st.markdown("### 🔄 修正後的最終報告")
    st.write(st.session_state.new_analysis_a)
    
    if st.button("🔍 進行最後審計並輸出機器數據包 (JSON)"):
        with st.spinner("軍師 B 審計與格式化中..."):
            prompt = f"""
            請審計這份修正後的報告，並輸出嚴格的 JSON 格式：
            {st.session_state.new_analysis_a}
            格式要求: {{ "risk_score": 1-10, "action": "...", "allocation_percent": int, "trigger": "...", "reasoning": "..." }}
            """
            st.session_state.machine_json = critic_ai(prompt)
            st.rerun()

# 5. 輸出結果
if "machine_json" in st.session_state:
    st.success("✅ 決策數據包已產生")
    st.code(st.session_state.machine_json, language='json')
