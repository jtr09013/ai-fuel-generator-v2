# --- 修正後的數據顯示區段範例 ---

# 針對 VIX 的邏輯修改
st.subheader("📊 市場情緒指標")
vix_value = 18.86 # 假設這是您抓到的即時數值
if vix_value > 18:
    vix_note = "恐慌情緒顯著升溫"
else:
    vix_note = "市場相對平穩"
st.write(f"**VIX:** {vix_value} | **NOTE:** {vix_note}")

# 針對 PCR 的邏輯修改
pcr_value = 1.07
prev_pcr = 0.452
st.write(f"**PUT/CALL RATIO:** {pcr_value} | **NOTE:** 較前日（{prev_pcr}）大幅上升，避險情緒顯著升溫")
