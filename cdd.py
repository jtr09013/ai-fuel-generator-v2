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
# 頁面設定
# ==========================================
st.set_page_config(page_title="AI 數據燃料生產器 v5.0", layout="wide")
st.title("🚀 AI 財經數據燃料生產器")
st.caption("台股資料來源：富果 API (即時個股/指數) + yfinance (盤後備援) | 美股：Yahoo Finance")

# ==========================================
# 上方大按鈕（取代 expander 摺疊）
# ==========================================
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "台股大包"

col_tab1, col_tab2, col_tab3 = st.columns(3)
with col_tab1:
    if st.button("🟢 台灣股市大包", use_container_width=True):
        st.session_state.active_tab = "台股大包"
with col_tab2:
    if st.button("🔵 美國股市大包", use_container_width=True):
        st.session_state.active_tab = "美股大包"
with col_tab3:
    if st.button("🔍 個股獨立單抓", use_container_width=True):
        st.session_state.active_tab = "個股單抓"

st.divider()

# ==========================================
# 富果 API 輔助函數
# ==========================================
def get_fugle_client():
    """取得富果 RestClient 實例"""
    try:
        api_key = st.secrets["FUGLE_API_KEY"]
        return RestClient(api_key=api_key)
    except Exception as e:
        st.error(f"富果 API 初始化失敗: {e}")
        return None

# ==========================================
# 台股即時報價 (使用富果 API)
# ==========================================
@st.cache_data(ttl=300)  # 5分鐘快取
def get_tw_stock_realtime(ticker):
    """使用富果 API 取得即時報價，失敗時降級至 yfinance"""
    ticker_clean = ticker.split('.')[0]  # 富果需要純數字代號
    client = get_fugle_client()
    if client:
        try:
            quote = client.stock.intraday.quote(symbol=ticker_clean)
            if quote and quote.get('data'):
                d = quote['data']
                price = d.get('price')
                if price and price > 0:
                    change = d.get('change', 0)
                    pct = d.get('changePercent', 0)
                    volume = d.get('volume', 0)
                    # 富果的 quote 不直接提供前日收盤，需從 change 反推
                    prev_close = price - change
                    vol_fmt = f"{volume/1000:.2f}萬張" if volume > 0 else "0張"
                    return {
                        "price": price,
                        "prev_close": prev_close,
                        "chg": change,
                        "pct": pct,
                        "vol": vol_fmt
                    }
        except Exception as e:
            st.warning(f"富果個股 {ticker_clean} 即時報價失敗: {e}，改用備援")

    # 備援：yfinance 盤中快照
    try:
        yf_ticker = f"{ticker_clean}.TW"
        stock = yf.Ticker(yf_ticker)
        hist = stock.history(period="2d")
        if len(hist) >= 2:
            prev_close = hist['Close'].iloc[-2]
            price = stock.fast_info.get('last_price', prev_close)
            if price > 0:
                volume = stock.fast_info.get('last_volume', 0)
                change = price - prev_close
                pct = (change / prev_close) * 100 if prev_close != 0 else 0
                vol_fmt = f"{volume/1000:.2f}萬張" if volume > 0 else "0張"
                return {
                    "price": price,
                    "prev_close": prev_close,
                    "chg": change,
                    "pct": pct,
                    "vol": vol_fmt
                }
    except Exception as e:
        st.warning(f"yfinance 備援 {ticker_clean} 失敗: {e}")
    return None

# ==========================================
# 台股盤後報價 (直接使用 yfinance 日線，穩定)
# ==========================================
@st.cache_data(ttl=3600)
def get_tw_stock_after(ticker):
    """盤後個股：使用 yfinance 日線收盤 (因富果歷史日線需付費，此處保持 yfinance)"""
    ticker_clean = ticker.split('.')[0]
    yf_ticker = f"{ticker_clean}.TW"
    try:
        df = yf.Ticker(yf_ticker).history(period="5d")
        if not df.empty and len(df) >= 2:
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            price = latest['Close']
            prev_close = prev['Close']
            chg = price - prev_close
            pct = (chg / prev_close) * 100 if prev_close != 0 else 0
            volume = latest['Volume']
            vol_str = f"{volume/1000:.2f}萬張" if volume >= 10000 else f"{volume:.0f}張"
            return {"price": price, "prev_close": prev_close, "chg": chg, "pct": pct, "vol": vol_str}
    except Exception as e:
        st.warning(f"yfinance 盤後 {ticker_clean} 失敗: {e}")
    return None

# ==========================================
# 大盤指數即時 (富果 API 支援 TAIEX / TPEX)
# ==========================================
@st.cache_data(ttl=300)
def get_tw_index_realtime():
    data = {
        "taiex_p": 0.0, "taiex_c": 0.0, "taiex_pct": 0.0, "taiex_v": "查閱盤中",
        "otc_p": 0.0, "otc_c": 0.0, "otc_pct": 0.0, "otc_v": "查閱盤中"
    }
    client = get_fugle_client()
    if client:
        # 加權指數 TAIEX
        try:
            taiex_quote = client.stock.intraday.quote(symbol="TAIEX")
            if taiex_quote and taiex_quote.get('data'):
                d = taiex_quote['data']
                data["taiex_p"] = d.get('price', 0)
                data["taiex_c"] = d.get('change', 0)
                data["taiex_pct"] = d.get('changePercent', 0)
        except Exception as e:
            st.warning(f"富果加權指數即時報價失敗: {e}")
        # 櫃買指數 TPEX
        try:
            tpex_quote = client.stock.intraday.quote(symbol="TPEX")
            if tpex_quote and tpex_quote.get('data'):
                d = tpex_quote['data']
                data["otc_p"] = d.get('price', 0)
                data["otc_c"] = d.get('change', 0)
                data["otc_pct"] = d.get('changePercent', 0)
        except Exception as e:
            st.warning(f"富果櫃買指數即時報價失敗: {e}")
    else:
        # 備援：yfinance (僅櫃買指數，加權指數仍然為0)
        try:
            otc = yf.Ticker("^TWOII")
            hist = otc.history(period="2d")
            if len(hist) >= 2:
                prev_o = hist['Close'].iloc[-2]
                now_o = hist['Close'].iloc[-1]
                data["otc_p"] = now_o
                data["otc_c"] = now_o - prev_o
                data["otc_pct"] = (data["otc_c"] / prev_o) * 100
        except Exception as e:
            st.warning(f"櫃買指數備援抓取失敗: {e}")
    return data

# ==========================================
# 盤後大盤指數 (加權改用 twstock，櫃買維持 yfinance)
# ==========================================
@st.cache_data(ttl=7200)  # 快取2小時，盤後資料不常變
def get_tw_index_after():
    data = {"taiex_p": 0.0, "taiex_c": 0.0, "taiex_pct": 0.0, "taiex_v": "待計算",
            "otc_p": 0.0, "otc_c": 0.0, "otc_pct": 0.0, "otc_v": "待確認"}

    # 1. 加權指數：使用 twstock 從證交所抓取歷史收盤 (無限制，穩定)
    try:
        # twstock.twse.daily_index() 回傳 list of dict，每個 dict 包含 date, open, high, low, close, change, change_percent
        idx_list = twstock.twse.daily_index()
        if idx_list and len(idx_list) >= 2:
            # 最近兩筆（最新為最後一筆）
            latest = idx_list[-1]
            prev = idx_list[-2]
            data["taiex_p"] = latest['close']
            data["taiex_c"] = latest['close'] - prev['close']
            data["taiex_pct"] = latest['change_percent']  # 直接使用內建的漲跌幅
            # 成交量不一定有，保留預設文字
        else:
            st.warning("twstock 加權指數資料不足")
    except Exception as e:
        st.warning(f"twstock 加權指數盤後抓取失敗: {e}，嘗試 yfinance 備援")
        # 備援：yfinance (萬一 twstock 失效)
        try:
            taiex = yf.Ticker("^TWII").history(period="5d")
            if len(taiex) >= 2:
                latest = taiex.iloc[-1]
                prev = taiex.iloc[-2]
                data["taiex_p"] = latest['Close']
                data["taiex_c"] = latest['Close'] - prev['Close']
                data["taiex_pct"] = (data["taiex_c"] / prev['Close']) * 100
                data["taiex_v"] = f"{latest['Volume']/1e6:.2f}百萬股"
        except Exception as e2:
            st.warning(f"yfinance 加權指數備援也失敗: {e2}")

    # 2. 櫃買指數 (維持 yfinance，目前穩定)
    try:
        otc = yf.Ticker("^TWOII").history(period="5d")
        if len(otc) >= 2:
            lo = otc.iloc[-1]
            po = otc.iloc[-2]
            data["otc_p"] = lo['Close']
            data["otc_c"] = lo['Close'] - po['Close']
            data["otc_pct"] = (data["otc_c"] / po['Close']) * 100
    except Exception as e:
        st.warning(f"櫃買指數盤後抓取失敗: {e}")

    return data
# ==========================================
# 美股、總經函數 (沿用 yfinance，完全不動)
# ==========================================
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

# ==========================================
# 動態顯示三個大頁面內容 (完全保留原樣)
# ==========================================
# ----- 頁面1：台股大包 -----
if st.session_state.active_tab == "台股大包":
    st.header("🇹🇼 台股大盤 + 關注個股")
    tw_time_mode = st.radio("台股市場時間狀態", ["☀️ 盤中即時模式 (INTRA)", "🌙 盤後清算模式 (AFTER)"], horizontal=True)
    tw_watchlist_input = st.text_input("輸入關注台股代號（用逗號隔開）", value="2317, 3016, 3374")
    
    if st.button("🔥 產生台股融合數據包", type="primary"):
        with st.spinner("正在打包台股數據..."):
            idx = get_tw_index_realtime() if "盤中即時" in tw_time_mode else get_tw_index_after()
            macro = get_macro_raw()
            watchlist_text = ""
            tickers = [t.strip() for t in tw_watchlist_input.split(",") if t.strip()]
            
            for t in tickers:
                if "盤中即時" in tw_time_mode:
                    res = get_tw_stock_realtime(t)
                else:
                    res = get_tw_stock_after(t)
                if res:
                    name = t
                    if "盤中即時" in tw_time_mode:
                        watchlist_text += f"{name}({t}): NOW: {res['price']:.2f} | PREV_CLOSE: {res['prev_close']:.2f} | CHG: {res['chg']:+.2f} ({res['pct']:+.2f}%) | EST_VOL: {res['vol']}\n"
                    else:
                        news_summary = get_yahoo_news_titles(f"{t}.TW", limit=1)
                        news_str = f" | NEWS: {news_summary}" if news_summary else ""
                        watchlist_text += f"{name}({t}): CLOSE: {res['price']:.2f} | PREV_CLOSE: {res['prev_close']:.2f} | CHG: {res['chg']:+.2f} ({res['pct']:+.2f}%) | VOL: {res['vol']}{news_str} | FOREIGN_NET: \n"
            
            # 建構詳細 XML 輸出（完全比照舊程式格式）
            if "盤中即時" in tw_time_mode:
                output = f"""<TW_MARKET_OVERVIEW_INTRA>
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
                output = f"""<TW_MARKET_OVERVIEW_AFTER>
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
            st.code(output, language="text")

# ----- 頁面2：美股大包 (完全不動) -----
elif st.session_state.active_tab == "美股大包":
    st.header("🇺🇸 美股大盤 + 關注個股")
    us_time_mode = st.radio("美股市場時間狀態", ["☀️ 盤中即時模式 (INTRA)", "🌙 盤後清算模式 (AFTER)"], horizontal=True)
    us_watchlist = st.text_input("輸入美股代號（逗號隔開）", value="NVDA, MU, TSM")
    
    if st.button("🔥 產生美股融合數據包", type="primary"):
        with st.spinner("正在打包美股數據..."):
            us_idx = get_us_index_data()
            macro = get_macro_raw()
            vix_p, vix_c = get_vix_data()
            watch_text = ""
            for sym in [s.strip().upper() for s in us_watchlist.split(",") if s.strip()]:
                stock = yf.Ticker(sym)
                hist = stock.history(period="2d")
                if not hist.empty:
                    latest = hist.iloc[-1]
                    chg_pct = ((latest['Close'] - latest['Open']) / latest['Open']) * 100
                    vol_val = latest['Volume'] / 10000
                    vol_fmt = f"{vol_val:,.0f}萬股" if vol_val >= 1000 else f"{vol_val:.2f}萬股"
                    if "盤中即時" in us_time_mode:
                        inst_str = " | INST_OWN_PCT: 約65%" if sym == "NVDA" else ""
                        watch_text += f"{sym}: PRICE: {latest['Close']:.2f} | CHG: {chg_pct:+.2f}% | VOL: {vol_fmt}{inst_str}\n"
                    else:
                        news_summary = get_yahoo_news_titles(sym, limit=1)
                        news_str = f" | NEWS: {news_summary}" if news_summary else " | NEWS: "
                        inst_str = " | INST_OWN_PCT: 約65%" if sym == "NVDA" else ""
                        watch_text += f"{sym}: PRICE: {latest['Close']:.2f} | CHG: {chg_pct:+.2f}% | VOL: {vol_fmt}{inst_str}{news_str}\n"
            
            if "盤中即時" in us_time_mode:
                output = f"""<US_MARKET_OVERVIEW>
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
{watch_text.strip()}
</STOCK_WATCHLIST>

<FUTURES_COT>
LAST_REPORT: 2026-05-30
E_MINIS&P500_NET_COMMERCIAL: -125,000口 (商業空頭)
E_MINIS&P500_NONCOM_NET: +98,000口 (投機淨多頭)
NOTE: 反映大戶期貨留倉動向，最新報告請AI聯網查證。
</FUTURES_COT>

<MACRO_EVENTS>
DXY: {macro['DXY']:.2f} | CHG: {macro['DXY_CHG']:+.2f}%
FED_RATE_EXPECT: CME FedWatch顯示7月升息機率約11%，年底前約55%
OIL_WTI: {macro['WTI']:.2f} | CHG: {macro['WTI_CHG']:+.1f}%
US_10Y_YIELD: {macro['US10Y']:.2f}% | CHG: {macro['US10Y_CHG_BPS']:+.2f}bps
MIDEAST_TALKS: 美伊衝突持續，談判陷入僵局，油價劇烈波動
</MACRO_EVENTS>"""
            else:
                output = f"""<US_MARKET_OVERVIEW_AFTER>
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
{watch_text.strip()}
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
            st.code(output, language="text")

# ----- 頁面3：個股單抓（詳細版） -----
else:
    st.header("🔍 個股獨立資料包")
    st.caption("當您只想針對某一檔股票單獨拷問 AI 時使用。")
    market = st.radio("股票市場類型", ["台灣股市 (TW Stock)", "美國股市 (US Stock)"], horizontal=True)
    single_code = st.text_input("輸入單一股票代號 (例如: 2330 或 NVDA)", value="2330").strip().upper()

    if st.button("⚡ 產生單一個股專屬 AI 數據包", type="primary"):
        with st.spinner(f"正在抽取 {single_code} 的獨立數據燃料..."):
            if market == "台灣股市 (TW Stock)":
                # 先嘗試富果即時報價，失敗則用 yfinance 盤後
                res = get_tw_stock_realtime(single_code)
                if not res:
                    res = get_tw_stock_after(single_code)
                if res:
                    # 計算均線 (使用 yfinance 歷史日線)
                    ticker_clean = single_code.split('.')[0]
                    yf_ticker = f"{ticker_clean}.TW"
                    try:
                        hist = yf.Ticker(yf_ticker).history(period="90d")
                        if not hist.empty and len(hist) >= 20:
                            ma5 = hist['Close'].iloc[-5:].mean()
                            ma20 = hist['Close'].iloc[-20:].mean()
                        else:
                            ma5 = ma20 = res['price']
                    except:
                        ma5 = ma20 = res['price']
                    news = get_yahoo_news_titles(yf_ticker, limit=3)
                    news_str = news if news else "無重大新聞"
                    output = f"""<SINGLE_STOCK_ANALYSIS_REQUEST>
TICKER: {single_code}
NAME: {single_code}
MARKET: TAIWAN

[CURRENT_SESSION]
PRICE_CLOSE: {res['price']:.2f} | PREV_CLOSE: {res['prev_close']:.2f}
CHANGE: {res['chg']:+.2f} ({res['pct']:+.2f}%) | VOLUME: {res['vol']}

[TECHNICAL_SNAPSHOT]
MA_5_DAY: {ma5:.2f}
MA_20_DAY: {ma20:.2f}

[LATEST_NEWS_HEADLINES]
{news_str}

[CHIPS_AND_EVENTS_INSTRUCTION]
⚠️提示：此為單一個股獨立查詢。請AI強制聯網搜尋今日該個股最新的「法人買賣超籌碼面」、「主力分點進出明細」並結合最新公告給出獨立的操作建議。
</SINGLE_STOCK_ANALYSIS_REQUEST>"""
                    st.success(f"🎉 {single_code} 專屬數據包已就緒！")
                    st.code(output, language="text")
                else:
                    st.error("找不到該股票數據")
            else:
                # 美股維持 yfinance
                stock = yf.Ticker(single_code)
                hist = stock.history(period="5d")
                info = stock.info
                if not hist.empty:
                    latest = hist.iloc[-1]
                    chg = latest['Close'] - latest['Open']
                    pct = (chg / latest['Open']) * 100
                    vol_fmt = f"{latest['Volume']/10000:.2f}萬股"
                    price_line = f"PRICE_CLOSE: {latest['Close']:.2f} | OPEN: {latest['Open']:.2f} | HIGH: {latest['High']:.2f} | LOW: {latest['Low']:.2f}"
                    hist_60 = stock.history(period="60d")
                    ma5 = hist_60['Close'].iloc[-5:].mean() if len(hist_60) >= 5 else 0
                    ma20 = hist_60['Close'].iloc[-20:].mean() if len(hist_60) >= 20 else 0
                    news = get_yahoo_news_titles(single_code, limit=3)
                    news_str = news if news else "無重大新聞"
                    output = f"""<SINGLE_STOCK_ANALYSIS_REQUEST>
TICKER: {single_code}
NAME: {info.get('shortName', 'N/A')}
MARKET: USA

[CURRENT_SESSION]
{price_line}
CHANGE: {chg:+.2f} ({pct:+.2f}%) | VOLUME: {vol_fmt}

[TECHNICAL_SNAPSHOT]
MA_5_DAY: {ma5:.2f}
MA_20_DAY: {ma20:.2f}

[LATEST_NEWS_HEADLINES]
{news_str}

[CHIPS_AND_EVENTS_INSTRUCTION]
⚠️提示：此為單一個股獨立查詢。請AI強制聯網搜尋該個股最新消息，並結合大盤 VIX、Put/Call Ratio、近期期權大單異動或機構持倉流向（13F 季報）給出獨立的操作建議。（註：美股無台股每日法人與分點數據，請勿虛構）。
</SINGLE_STOCK_ANALYSIS_REQUEST>"""
                    st.success(f"🎉 {single_code} 專屬數據包已就緒！")
                    st.code(output, language="text")
                else:
                    st.error("找不到該股票數據")

# ==========================================
# 軍師團決策支援模組（與舊程式完全相同）
# ==========================================
st.divider()
st.subheader("🤖 軍師團決策支援")

if "analysis_log" not in st.session_state:
    st.session_state.analysis_log = []
if "show_buttons" not in st.session_state:
    st.session_state.show_buttons = False

context_data = st.text_area("請貼入數據燃料包：", height=150)

def search_web(query):
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
        return str(results)
    except Exception as e:
        return f"無法聯網搜尋新聞: {e}"

def analyst_ai(data):
    client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
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
    news = search_web("美股與台股今日重點財經新聞")
    full_prompt = f"請分析這些數據與新聞，並嚴格依照格式輸出: {data} \n 新聞參考: {news}"
    response = client.models.generate_content(
        model="gemini-1.5-flash",
        contents=full_prompt,
        config=types.GenerateContentConfig(system_instruction=system_instruction)
    )
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
