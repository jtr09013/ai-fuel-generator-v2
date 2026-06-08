import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import google.generativeai as genai
from openai import OpenAI
from duckduckgo_search import DDGS
from FinMind.data import DataLoader
import requests

# --- 初始化 FinMind ---
try:
    if "FINMIND_TOKEN" in st.secrets and st.secrets["FINMIND_TOKEN"].strip() != "":
        fm_token = st.secrets["FINMIND_TOKEN"]
        fm = DataLoader()
        fm.login_by_token(fm_token)
    else:
        fm = DataLoader()
except Exception as e:
    print(f"FinMind Token Login Failed, status: bypass. Error: {e}")
    fm = DataLoader()

# --- 核心軍師模組 ---

def search_web(query):
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
        return str(results)
    except Exception as e:
        return f"無法聯網搜尋新聞: {e}"

def analyst_ai(data):
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    system_instruction = """
你是一位頂尖的市場分析官。任務是基於結構化數據與新聞，輸出「客觀事實」與「主觀推測」分離的報告。
嚴格遵守格式：
### [已知事實]
- 列出關鍵數據（標註來源與時間）
- 歸納新聞核心事件（不帶評價）

### [推測與邏輯鏈]
- 若 A (數據) 則 B (推測)，拆解推理過程。
- 針對不確定性，給上具體機率預估（如：約 65%）。

### [結論摘要]
- 對台股/個股的短線影響判斷（方向：漲/跌；強度：強/中/弱）。
- 禁止模糊詞（如：可能、或許），一律用「數據顯示」、「根據模型推測」開頭。
"""
    # 修正：將原本不存在的 gemini-3.5-flash 修正為穩定的官方標準名稱
    model = genai.GenerativeModel('gemini-1.5-flash', system_instruction=system_instruction)
    news = search_web("美股與台股今日重點財經新聞")
    response = model.generate_content(f"請分析這些數據與新聞，並嚴格依照格式輸出: {data} \n 新聞參考: {news}")
    return response.text

def critic_ai(analysis):
    client = OpenAI(api_key=st.secrets["DEEPSEEK_API_KEY"], base_url="https://api.deepseek.com")
    system_prompt = """
你是一位嚴格的風險評估官，任務是對報告進行邏輯審計。請針對以下五大維度逐項檢查，若無問題標註「無異常」，若有疑慮請點出具體盲點並建議修正：
1. 時間滯後：檢查數據是否過期。
2. 因果倒置：檢查是否將波動結果解釋為原因。
3. 矛盾信號：檢查解讀是否衝突。
4. 倖存者偏差：檢查是否忽略反向指標。
5. 歸因謬誤：檢查是否將系統性風險誤認為公司基本面。
"""
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"審計此報告:\n{analysis}"}
        ]
    )
    return response.choices[0].message.content

# 網頁基本設定
st.set_page_config(page_title="AI 數據燃料生產器 v4.5", layout="wide")
st.title("🚀 AI 財經數據燃料生產器 (台股雙軌即時+美股Y精準版)")
st.caption("台股升級：盤中採用證交所官方即時報價，盤後採用 FinMind 歷史清算數據。")

# --- 核心數據抓取函式 (修正盤前與暫緩撮合的 "-" 字串死穴) ---

def clean_twse_float(val, fallback=0.0):
    """ 安全轉換證交所欄位，防範 '-' 字串引發 ValueError """
    if not val or str(val).strip() in ["-", ""]:
        return fallback
    try:
        return float(val)
    except:
        return fallback

def get_tw_index_data_realtime():
    data = {"taiex_p": 0.0, "taiex_c": 0.0, "taiex_pct": 0.0, "taiex_v": "查閱盤中",
            "otc_p": 0.0, "otc_c": 0.0, "otc_pct": 0.0, "otc_v": "查閱盤中"}
    try:
        r = requests.get("https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_t00.tw", timeout=5)
        res = r.json()
        if "msgArray" in res and len(res["msgArray"]) > 0:
            info = res["msgArray"][0]
            y_close = clean_twse_float(info.get('y'), 0.0)
            # 防呆：如果 z 是 "-"，就拿開盤價 o，再不行就拿昨收 y
            current = clean_twse_float(info.get('z'), clean_twse_float(info.get('o'), y_close))
            
            if y_close > 0 and current > 0:
                data["taiex_p"] = current
                data["taiex_c"] = current - y_close
                data["taiex_pct"] = (data["taiex_c"] / y_close) * 100

        r_otc = requests.get("https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=otc_o00.tw", timeout=5)
        res_otc = r_otc.json()
        if "msgArray" in res_otc and len(res_otc["msgArray"]) > 0:
            info_o = res_otc["msgArray"][0]
            y_close_o = clean_twse_float(info_o.get('y'), 0.0)
            current_o = clean_twse_float(info_o.get('z'), clean_twse_float(info_o.get('o'), y_close_o))
            
            if y_close_o > 0 and current_o > 0:
                data["otc_p"] = current_o
                data["otc_c"] = current_o - y_close_o
                data["otc_pct"] = (data["otc_c"] / y_close_o) * 100
    except:
        pass
    return data

def get_tw_index_data_after():
    data = {"taiex_p": 0.0, "taiex_c": 0.0, "taiex_pct": 0.0, "taiex_v": "待計算",
            "otc_p": 0.0, "otc_c": 0.0, "otc_pct": 0.0, "otc_v": "待確認"}
    try:
        end_date = datetime.today().strftime('%Y-%m-%d')
        start_date = (datetime.today() - timedelta(days=7)).strftime('%Y-%m-%d')
        df_taiex = fm.taiwan_stock_daily(stock_id='0000', start_date=start_date, end_date=end_date)
        if not df_taiex.empty and len(df_taiex) >= 2:
            latest = df_taiex.iloc[-1]
            prev = df_taiex.iloc[-2]
            data["taiex_p"] = latest['close']
            data["taiex_c"] = latest['close'] - prev['close']
            data["taiex_pct"] = (data["taiex_c"] / prev['close']) * 100
    except:
        pass
    return data

def get_tw_stock_realtime(ticker):
    try:
        url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_{ticker}.tw|otc_{ticker}.tw"
        res = requests.get(url, timeout=5).json()
        if "msgArray" in res and len(res["msgArray"]) > 0:
            info = res["msgArray"][0]
            y_close = clean_twse_float(info.get('y'), 0.0)
            curr = clean_twse_float(info.get('z'), clean_twse_float(info.get('o'), y_close))
            vol = info.get('v', '0')
            
            chg = curr - y_close
            pct = (chg / y_close) * 100 if y_close > 0 else 0.0
            return {"price": curr, "prev_close": y_close, "chg": chg, "pct": pct, "vol": f"{float(vol)/1000:.2f}萬張" if vol.isdigit() else "0萬張"}
    except:
        pass
    return None

def get_us_index_data():
    indices = {"DOW": "^DJI", "NAS": "^IXIC", "SPX": "^GSPC", "SOX": "^SOX"}
    data = {}
    for name, ticker in indices.items():
        try:
            df = yf.Ticker(ticker).history(period="5d")
            if len(df) >= 2:
                latest = df.iloc[-1]
                prev = df.iloc[-2]
                chg = latest['Close'] - prev['Close']
                pct = (chg / prev['Close']) * 100
                data[name] = {"p": latest['Close'], "c": chg, "pct": pct, "h": latest['High'], "l": latest['Low']}
            else:
                data[name] = {"p": 0.0, "c": 0.0, "pct": 0.0, "h": 0.0, "l": 0.0}
        except:
            data[name] = {"p": 0.0, "c": 0.0, "pct": 0.0, "h": 0.0, "l": 0.0}
    return data

def get_macro_raw():
    macro = {"WTI": 0.0, "WTI_CHG": 0.0, "US10Y": 0.0, "US10Y_CHG_BPS": 0.0, "DXY": 0.0, "DXY_CHG": 0.0}
    try:
        wti = yf.Ticker("CL=F").history(period="5d")
        if len(wti) >= 2:
            macro["WTI"] = wti['Close'].iloc[-1]
            macro["WTI_CHG"] = ((wti['Close'].iloc[-1] - wti['Close'].iloc[-2]) / wti['Close'].iloc[-2]) * 100
        tnx = yf.Ticker("^TNX").history(period="5d")
        if len(tnx) >= 2:
            macro["US10Y"] = tnx['Close'].iloc[-1]
            macro["US10Y_CHG_BPS"] = (tnx['Close'].iloc[-1] - tnx['Close'].iloc[-2]) * 100  
            
        # 修正：DXY 有時在 yfinance 用 DX-Y.NYB 會斷線，加入標準代號 ^DXY 作為備援
        dxy_ticker = "DX-Y.NYB"
        dxy = yf.Ticker(dxy_ticker).history(period="5d")
        if dxy.empty:
            dxy = yf.Ticker("^DXY").history(period="5d")
            
        if len(dxy) >= 2:
            macro["DXY"] = dxy['Close'].iloc[-1]
            macro["DXY_CHG"] = ((dxy['Close'].iloc[-1] - dxy['Close'].iloc[-2]) / dxy['Close'].iloc[-2]) * 100
    except:
        pass
    return macro

def get_vix_data():
    try:
        vix = yf.Ticker("^VIX").history(period="5d")
        if len(vix) >= 2: return vix['Close'].iloc[-1], (vix['Close'].iloc[-1] - vix['Close'].iloc[-2])
    except: pass
    return 0.0, 0.0

def get_yahoo_news_titles(ticker, limit=1):
    try:
        stock = yf.Ticker(ticker)
        titles = [n.get('title', '').strip() for n in stock.news[:limit] if n.get('title')]
        return "、".join(titles) if titles else ""
    except: return ""

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
            macro = get_macro_raw()
            watchlist_text = ""
            ticker_list = [t.strip() for t in tw_watchlist_input.split(",") if t.strip()]
             
            if "盤中即時" in tw_time_mode:
                idx = get_tw_index_data_realtime()
                for t in ticker_list:
                    res = get_tw_stock_realtime(t)
                    if res:
                        watchlist_text += f"個股_{t}({t}): NOW: {res['price']:.2f} | PREV_CLOSE: {res['prev_close']:.2f} | CHG: {res['chg']:+.2f} ({res['pct']:+.2f}%) | EST_VOL: {res['vol']}\n"
                 
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
FOMC_WATCH: 7月升息機率約11%
</MACRO_EVENTS_INTRA>"""
             
            else:
                idx = get_tw_index_data_after()
                end_date = datetime.today().strftime('%Y-%m-%d')
                start_date = (datetime.today() - timedelta(days=7)).strftime('%Y-%m-%d')
                 
                for t in ticker_list:
                    df_hist = fm.taiwan_stock_daily(stock_id=t, start_date=start_date, end_date=end_date)
                    if not df_hist.empty and len(df_hist) >= 2:
                        latest = df_hist.iloc[-1]
                        prev_close = df_hist['close'].iloc[-2]
                        chg = latest['close'] - prev_close
                        pct = (chg / prev_close) * 100
                        vol_w = f"{latest['Trading_Volume'] / 10000000:.2f}萬張"
                        news_summary = get_yahoo_news_titles(f"{t}.TW", limit=1)
                        news_str = f" | NEWS: {news_summary}" if news_summary else ""
                        watchlist_text += f"個股_{t}({t}): CLOSE: {latest['close']:.2f} | PREV_CLOSE: {prev_close:.2f} | CHG: {chg:+.2f} ({pct:+.2f}%) | VOL: {vol_w}{news_str} | FOREIGN_NET: \n"
                 
                # 優化：移除可能會被 AI 當成普通程式碼註解忽略的 '#' 符號，改為明確指令標籤
                final_tw = f"""<TW_MARKET_OVERVIEW_AFTER>
TAIEX_CLOSE: {idx['taiex_p']:.2f} | CHG: {idx['taiex_c']:+.2f} ({idx['taiex_pct']:+.2f}%) | VOL: {idx['taiex_v']}
OTC_CLOSE: {idx['otc_p']:.2f} | CHG: {idx['otc_c']:+.2f} ({idx['otc_pct']:+.2f}%) | VOL: {idx['otc_v']}
AI_REQUIRED_TASK_1: 請AI聯網搜尋今日最新的「上市與櫃買漲跌家數比」並補在此處。
</TW_MARKET_OVERVIEW_AFTER>

<TW_INSTITUTIONAL_CHIPS_AFTER>
FOREIGN_NET_TWD: 
INVESTMENT_TRUST_NET_TWD: 
DEALERS_TOTAL_NET_TWD: 
FUTURES_NET_SHORT: 
AI_REQUIRED_TASK_2: 請AI強制聯網搜尋補上今日最新「三大法人買賣超金額」與「外資台指期淨空單口數」。
</TW_INSTITUTIONAL_CHIPS_AFTER>

<TW_MARGIN_BALANCE_AFTER>
MARGIN_PURCHASE_CHG: 
SHORT_SALE_CHG: 
MARGIN_BALANCE_TOTAL: 
AI_REQUIRED_TASK_3: 請AI強制聯網搜尋補上今日最新「融資增減」、「融券增減」與「融資餘額總計」。
</TW_MARGIN_BALANCE_AFTER>

<STOCK_WATCHLIST_AFTER>
{watchlist_text.strip()}
AI_REQUIRED_TASK_4: 請AI聯網補上今日三大法人對上述個股的買賣超張數。
</STOCK_WATCHLIST_AFTER>

<MACRO_EVENTS_AFTER>
DXY: {macro['DXY']:.2f} ({macro['DXY_CHG']:+.2f}%)
OIL_WTI: {macro['WTI']:.2f} ({macro['WTI_CHG']:+.1f}%)
US_10Y_YIELD: {macro['US10Y']:.2f}%
AI_REQUIRED_TASK_5: 請AI強制聯網搜尋最新國際總經焦點與地緣政治談判局勢。
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
                hist = stock.history(period="5d")
                if len(hist) >= 2:
                    latest = hist.iloc[-1]
                    u_prev_close = hist['Close'].iloc[-2]
                    chg_pct = ((latest['Close'] - u_prev_close) / u_prev_close) * 100
                    vol_val = latest['Volume'] / 10000
                    vol_m = f"{vol_val:,.0f}萬股" if vol_val >= 1000 else f"{vol_val:.2f}萬股"
                     
                    if "盤中即時" in us_time_mode:
                        us_watchlist_text += f"{ut}: PRICE: {latest['Close']:.2f} | CHG: {chg_pct:+.2f}% | VOL: {vol_m}\n"
                    else:
                        news_summary = get_yahoo_news_titles(ut, limit=1)
                        news_str = f" | NEWS: {news_summary}" if news_summary else " | NEWS: "
                        us_watchlist_text += f"{ut}: PRICE: {latest['Close']:.2f} | CHG: {chg_pct:+.2f}% | VOL: {vol_m}{news_str}\n"

            if "盤中即時" in us_time_mode:
                final_us = f"""<US_MARKET_OVERVIEW>
DOW: {us_idx['DOW']['p']:.2f} | CHG: {us_idx['DOW']['c']:+.2f} ({us_idx['DOW']['pct']:+.2f}%)
NAS: {us_idx['NAS']['p']:.2f} | CHG: {us_idx['NAS']['c']:+.2f} ({us_idx['NAS']['pct']:+.2f}%)
SPX: {us_idx['SPX']['p']:.2f} | CHG: {us_idx['SPX']['c']:+.2f} ({us_idx['SPX']['pct']:+.2f}%)
SOX: {us_idx['SOX']['p']:.2f} | CHG: {us_idx['SOX']['c']:+.2f} ({us_idx['SOX']['pct']:+.2f}%)
</US_MARKET_OVERVIEW>

<US_SENTIMENT>
VIX: {vix_p:.2f} | CHG: {vix_c:+.2f}
PUT_CALL_RATIO: 1.07
</US_SENTIMENT>

<STOCK_WATCHLIST>
{us_watchlist_text.strip()}
</STOCK_WATCHLIST>

<MACRO_EVENTS>
DXY: {macro['DXY']:.2f} | CHG: {macro['DXY_CHG']:+.2f}%
OIL_WTI: {macro['WTI']:.2f} | CHG: {macro['WTI_CHG']:+.1f}%
US_10Y_YIELD: {macro['US10Y']:.2f}%
</MACRO_EVENTS>"""
            else:
                final_us = f"""<US_MARKET_OVERVIEW_AFTER>
DOW: {us_idx['DOW']['p']:.2f} | CHG: {us_idx['DOW']['c']:+.2f} ({us_idx['DOW']['pct']:+.2f}%)
NAS: {us_idx['NAS']['p']:.2f} | CHG: {us_idx['NAS']['c']:+.2f} ({us_idx['NAS']['pct']:+.2f}%)
SPX: {us_idx['SPX']['p']:.2f} | CHG: {us_idx['SPX']['c']:+.2f} ({us_idx['SPX']['pct']:+.2f}%)
SOX: {us_idx['SOX']['p']:.2f} | CHG: {us_idx['SOX']['c']:+.2f} ({us_idx['SOX']['pct']:+.2f}%)
</US_MARKET_OVERVIEW_AFTER>

<US_SENTIMENT_AFTER>
VIX: {vix_p:.2f} | CHG: {vix_c:+.2f}
PUT_CALL_RATIO: 1.07
</US_SENTIMENT_AFTER>

<US_STOCK_WATCHLIST_AFTER>
{us_watchlist_text.strip()}
</US_STOCK_WATCHLIST_AFTER>

<US_MACRO_EVENTS_AFTER>
DXY: {macro['DXY']:.2f} | CHG: {macro['DXY_CHG']:+.2f}%
OIL_WTI: {macro['WTI']:.2f} | CHG: {macro['WTI_CHG']:+.1f}%
US_10Y_YIELD: {macro['US10Y']:.2f}%
</US_MACRO_EVENTS_AFTER>"""

            st.success("🎉 美股燃料包輸出成功！")
            st.code(final_us, language="text")

# ==========================================
# 🔍 頁籤三：個股獨立單抓與輸出
# ==========================================
with tab3:
    st.header("🔍 個股獨立單抓工具")
    market_type = st.radio("股票市場類型", ["台灣股市 (TW Stock)", "美國股市 (US Stock)"], horizontal=True)
    single_ticker = st.text_input("輸入單一股票代號", value="2330").upper().strip()
     
    if st.button("⚡ 產生單一個股專屬 AI 數據包"):
        with st.spinner(f"正在抽取 {single_ticker} 的數據..."):
            valid = False
             
            if market_type == "台灣股市 (TW Stock)":
                res = get_tw_stock_realtime(single_ticker)
                if res:
                    price_line = f"PRICE_NOW: {res['price']:.2f} | PREV_CLOSE: {res['prev_close']:.2f}"
                    chg, pct, vol_formatted = res['chg'], res['pct'], res['vol']
                    start_date = (datetime.today() - timedelta(days=90)).strftime('%Y-%m-%d')
                    df_hist = fm.taiwan_stock_daily(stock_id=single_ticker, start_date=start_date, end_date=datetime.today().strftime('%Y-%m-%d'))
                    ma5 = df_hist['close'].iloc[-5:].mean() if len(df_hist) >= 5 else res['price']
                    ma20 = df_hist['close'].iloc[-20:].mean() if len(df_hist) >= 20 else res['price']
                    single_news = get_yahoo_news_titles(f"{single_ticker}.TW", limit=3)
                    instruction_text = "AI_REQUIRED_TASK: 請AI強制聯網搜尋今日該台股最新的「法人買賣超」、「主力分點進出」並給出獨立操作建議。"
                    valid = True
            else:
                stock = yf.Ticker(single_ticker)
                hist = stock.history(period="60d")
                if not hist.empty and len(hist) >= 2:
                    latest = hist.iloc[-1]
                    u_s_prev_close = hist['Close'].iloc[-2]
                    chg = latest['Close'] - u_s_prev_close
                    pct = (chg / u_s_prev_close) * 100
                    vol_formatted = f"{latest['Volume']/10000:.2f}萬股"
                    price_line = f"PRICE_CLOSE: {latest['Close']:.2f} | OPEN: {latest['Open']:.2f}"
                    ma5 = hist['Close'].iloc[-5:].mean()
                    ma20 = hist['Close'].iloc[-20:].mean()
                    single_news = get_yahoo_news_titles(single_ticker, limit=3)
                    instruction_text = "AI_REQUIRED_TASK: 請AI聯網搜尋最新消息，並結合大盤 VIX、期權動向給出獨立的操作建議。"
                    valid = True
                     
            if valid:
                single_packet = f"""<SINGLE_STOCK_ANALYSIS_REQUEST>
TICKER: {single_ticker}
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
                st.success(f"🎉 {single_ticker} 專專屬數據包已就緒！")
                st.code(single_packet, language="text")
            else:
                st.error("找不到該股票數據。")

# --- 軍師團決策支援模組 ---
st.divider()
st.subheader("🤖 軍師團決策支援")

if "analysis_log" not in st.session_state: st.session_state.analysis_log = []
if "show_buttons" not in st.session_state: st.session_state.show_buttons = False

context_data = st.text_area("請貼入數據燃料包：", height=150)

if st.button("🚀 開始軍師審議"):
    with st.status("軍師團研議中...", expanded=True):
        a1 = analyst_ai(context_data)
        b1 = critic_ai(a1)
        st.session_state.analysis_log.append({"report": a1, "critic": b1})
        st.session_state.show_buttons = True
        st.rerun()

if st.session_state.analysis_log:
    latest = st.session_state.analysis_log[-1]
    st.markdown("### 📊 目前分析報告")
    st.write(latest["report"])
    st.info(f"### 🔍 軍師 B 的審查意見\n{latest['critic']}")

    if st.session_state.show_buttons:
        col1, col2 = st.columns(2)
        if col1.button("🔄 根據審查意見進行修正"):
            with st.spinner("軍師修正中..."):
                prompt = f"針對質疑：{latest['critic']}，原始數據：{context_data}，請補強數據並修正報告。"
                new_a = analyst_ai(prompt)
                new_b = critic_ai(new_a)
                st.session_state.analysis_log.append({"report": new_a, "critic": new_b})
                st.rerun()
         
        if col2.button("✅ 內容無誤，強制輸出 JSON"):
            with st.spinner("最後審計與格式化中..."):
                prompt = f"將此報告轉換為嚴格的 JSON: {latest['report']}"
                final_json = critic_ai(prompt)
                st.session_state.final_json = final_json
                st.rerun()

if "final_json" in st.session_state:
    st.success("🎉 決策數據包已產生！")
    st.code(st.session_state.final_json, language='json')
