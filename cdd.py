import os
import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
os.environ["ANYIO_BACKEND"] = "asyncio"

# 富果行情 API
from fugle_marketdata import RestClient

from google import genai
from google.genai import types

from openai import OpenAI
from duckduckgo_search import DDGS
import requests

# ==========================================
# 核心功能：富果 API 行情取得（含備援）
# ==========================================

@st.cache_data(ttl=5)
def get_tw_stock_realtime(ticker):
    """使用富果 API 取得個股即時報價，失敗時備援至 yfinance 或證交所"""
    try:
        api_key = st.secrets["FUGLE_API_KEY"]
        client = RestClient(api_key=api_key)
        stock = client.stock
        quote = stock.intraday.quote(symbol=ticker)
        if quote and 'data' in quote:
            data = quote['data']
            price = data.get('price', 0)
            change = data.get('change', 0)
            change_percent = data.get('changePercent', 0)
            volume = data.get('volume', 0)
            prev_close = price - change
            vol_formatted = f"{volume/1000:.2f}萬張" if volume > 0 else "0張"
            return {"price": price, "prev_close": prev_close, "chg": change, "pct": change_percent, "vol": vol_formatted}
    except Exception as e:
        st.warning(f"富果個股 {ticker} 報價失敗，使用備援: {e}")
    # 備援1: yfinance
    try:
        stock = yf.Ticker(f"{ticker}.TW")
        info = stock.fast_info
        price = info.get('last_price', 0)
        if price > 0:
            prev_close = info.get('regular_market_previous_close', 0)
            if prev_close == 0:
                hist = stock.history(period="2d")
                if len(hist) >= 2:
                    prev_close = hist['Close'].iloc[-2]
            change = price - prev_close
            pct = (change / prev_close) * 100 if prev_close != 0 else 0
            volume = info.get('last_volume', 0)
            vol_fmt = f"{volume/1000:.2f}萬張" if volume > 0 else "0張"
            return {"price": price, "prev_close": prev_close, "chg": change, "pct": pct, "vol": vol_fmt}
    except Exception as e2:
        st.warning(f"yfinance 個股 {ticker} 備援失敗: {e2}")
    # 備援2: 證交所 API (原有邏輯，可選擇是否保留)
    # 若以上都失敗則回傳 None
    return None

@st.cache_data(ttl=10)
def get_tw_index_data_realtime():
    """取得大盤即時數據（因富果免費版不支援指數，直接使用 yfinance）"""
    data = {
        "taiex_p": 0.0, "taiex_c": 0.0, "taiex_pct": 0.0, "taiex_v": "查閱盤中",
        "otc_p": 0.0, "otc_c": 0.0, "otc_pct": 0.0, "otc_v": "查閱盤中"
    }
    try:
        # 加權指數 ^TWII
        taiex = yf.Ticker("^TWII")
        hist = taiex.history(period="2d")
        if len(hist) >= 2:
            prev_close = hist['Close'].iloc[-2]
            # 獲取當日盤中最新價（使用1分鐘線）
            intraday = taiex.history(period="1d", interval="1m")
            if not intraday.empty:
                current = intraday['Close'].iloc[-1]
            else:
                current = hist['Close'].iloc[-1]  # 無盤中則用昨日收盤
            data["taiex_p"] = current
            data["taiex_c"] = current - prev_close
            data["taiex_pct"] = (data["taiex_c"] / prev_close) * 100
            data["taiex_v"] = "即時(延遲)"
        # 櫃買指數 ^TWOII
        otc = yf.Ticker("^TWOII")
        hist_o = otc.history(period="2d")
        if len(hist_o) >= 2:
            prev_close_o = hist_o['Close'].iloc[-2]
            intraday_o = otc.history(period="1d", interval="1m")
            current_o = intraday_o['Close'].iloc[-1] if not intraday_o.empty else hist_o['Close'].iloc[-1]
            data["otc_p"] = current_o
            data["otc_c"] = current_o - prev_close_o
            data["otc_pct"] = (data["otc_c"] / prev_close_o) * 100
            data["otc_v"] = "即時(延遲)"
    except Exception as e:
        st.warning(f"取得大盤即時數據失敗: {e}")
    return data

# ==========================================
# 其他抓取函數 (Yahoo Finance, 美股, 總經)
# ==========================================
def get_tw_index_data_after():
    """盤後模式：使用 yfinance 抓取台股大盤（^TWII）和櫃買（^TWOII）"""
    data = {"taiex_p": 0.0, "taiex_c": 0.0, "taiex_pct": 0.0, "taiex_v": "待計算",
            "otc_p": 0.0, "otc_c": 0.0, "otc_pct": 0.0, "otc_v": "待確認"}
    try:
        taiex = yf.Ticker("^TWII").history(period="5d")
        if not taiex.empty and len(taiex) >= 2:
            latest = taiex.iloc[-1]
            prev = taiex.iloc[-2]
            data["taiex_p"] = latest['Close']
            data["taiex_c"] = latest['Close'] - prev['Close']
            data["taiex_pct"] = (data["taiex_c"] / prev['Close']) * 100
            data["taiex_v"] = f"{latest['Volume']/1000000:.2f}百萬股"
        otc = yf.Ticker("^TWOII").history(period="5d")
        if not otc.empty and len(otc) >= 2:
            latest_o = otc.iloc[-1]
            prev_o = otc.iloc[-2]
            data["otc_p"] = latest_o['Close']
            data["otc_c"] = latest_o['Close'] - prev_o['Close']
            data["otc_pct"] = (data["otc_c"] / prev_o['Close']) * 100
    except Exception as e:
        st.warning(f"盤後大盤抓取失敗: {e}")
    return data

def get_tw_stock_after(ticker):
    """盤後個股：使用 yfinance"""
    try:
        stock = yf.Ticker(f"{ticker}.TW")
        hist = stock.history(period="5d")
        if len(hist) >= 2:
            latest = hist.iloc[-1]
            prev = hist.iloc[-2]
            price = latest['Close']
            prev_close = prev['Close']
            chg = price - prev_close
            pct = (chg / prev_close) * 100 if prev_close != 0 else 0
            vol = latest['Volume'] / 1000
            vol_str = f"{vol:.2f}萬張" if vol >= 10000 else f"{vol:.0f}張"
            return {"price": price, "prev_close": prev_close, "chg": chg, "pct": pct, "vol": vol_str}
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
        dxy = yf.Ticker("DX-Y.NYB").history(period="5d")
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
        if len(vix) >= 2:
            return vix['Close'].iloc[-1], (vix['Close'].iloc[-1] - vix['Close'].iloc[-2])
    except:
        pass
    return 0.0, 0.0

def get_yahoo_news_titles(ticker, limit=1):
    try:
        stock = yf.Ticker(ticker)
        titles = [n.get('title', '').strip() for n in stock.news[:limit] if n.get('title')]
        return "、".join(titles) if titles else ""
    except:
        return ""

# ==========================================
# Streamlit UI 設定
# ==========================================
st.set_page_config(page_title="AI 財經數據燃料生產器 v5.0", layout="wide")
st.title("🚀 AI 財經數據燃料生產器 (台股雙軌即時+美股Y精準版)")
st.caption("台股升級：盤中採用富果 API 即時報價，盤後採用 Yahoo Finance 歷史數據。")

# ========== 台股大包 ==========
with st.expander("🟢 台灣股市大包", expanded=True):
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
                for t in ticker_list:
                    res = get_tw_stock_after(t)
                    if res:
                        news_summary = get_yahoo_news_titles(f"{t}.TW", limit=1)
                        news_str = f" | NEWS: {news_summary}" if news_summary else ""
                        watchlist_text += f"個股_{t}({t}): CLOSE: {res['price']:.2f} | PREV_CLOSE: {res['prev_close']:.2f} | CHG: {res['chg']:+.2f} ({res['pct']:+.2f}%) | VOL: {res['vol']}{news_str}\n"
                 
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

# ========== 美股大包 ==========
with st.expander("🔵 美國股市大包", expanded=False):
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

# ========== 個股獨立單抓 ==========
with st.expander("🔍 個股獨立單抓", expanded=False):
    st.header("🔍 個股獨立單抓工具")
    market_type = st.radio("股票市場類型", ["台灣股市 (TW Stock)", "美國股市 (US Stock)"], horizontal=True)
    single_ticker = st.text_input("輸入單一股票代號", value="2330").upper().strip()
     
    if st.button("⚡ 產生單一個股專屬 AI 數據包"):
        with st.spinner(f"正在抽取 {single_ticker} 的數據..."):
            valid = False
             
            if market_type == "台灣股市 (TW Stock)":
                # 嘗試即時
                res = get_tw_stock_realtime(single_ticker)
                if not res:
                    res = get_tw_stock_after(single_ticker)
                if res:
                    price_line = f"PRICE_NOW: {res['price']:.2f} | PREV_CLOSE: {res['prev_close']:.2f}"
                    chg, pct, vol_formatted = res['chg'], res['pct'], res['vol']
                    # 技術線圖使用 yfinance 歷史
                    hist = yf.Ticker(f"{single_ticker}.TW").history(period="90d")
                    if not hist.empty:
                        ma5 = hist['Close'].iloc[-5:].mean() if len(hist) >= 5 else res['price']
                        ma20 = hist['Close'].iloc[-20:].mean() if len(hist) >= 20 else res['price']
                    else:
                        ma5 = ma20 = res['price']
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
                st.success(f"🎉 {single_ticker} 專屬數據包已就緒！")
                st.code(single_packet, language="text")
            else:
                st.error("找不到該股票數據。")
