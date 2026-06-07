# --- 1. 永遠存在的輸入區 ---
st.divider()
st.subheader("🤖 軍師團決策支援")

if "context_data" not in st.session_state:
    st.session_state.context_data = ""

st.session_state.context_data = st.text_area(
    "請貼入剛剛產生的燃料包數據：", 
    value=st.session_state.context_data, 
    height=200
)

# --- 2. 召喚按鈕 ---
if st.button("召喚軍師團進行分析"):
    if st.session_state.context_data:
        with st.status("軍師團研議中...", expanded=True) as status:
            analysis_a = analyst_ai(st.session_state.context_data)
            final_verdict = critic_ai(analysis_a)
            st.session_state.analysis_a = analysis_a
            st.session_state.final_verdict = final_verdict
            st.session_state.show_revision = True
            # 清除舊的修正紀錄
            if "new_analysis_a" in st.session_state: del st.session_state.new_analysis_a
            if "machine_json" in st.session_state: del st.session_state.machine_json
            status.update(label="✅ 初步分析完成", state="complete")
            st.rerun() 
    else:
        st.warning("請先產生並貼入數據！")

# --- 3. 顯示結果與決策流程 ---
if st.session_state.get("show_revision", False):
    st.markdown("### 📊 初步分析報告")
    st.write(st.session_state.analysis_a)
    st.info(f"### 🔍 軍師 B 的審查意見\n{st.session_state.final_verdict}")
    
    # 修正按鈕
    if st.button("🔄 要求分析官針對質疑進行修正"):
        with st.spinner("軍師修正中..."):
            correction_prompt = f"針對質疑：{st.session_state.final_verdict}，原始數據：{st.session_state.context_data}，請修正。"
            st.session_state.new_analysis_a = analyst_ai(correction_prompt)
            st.rerun()

# --- 4. 修正後的輸出與審計 ---
if "new_analysis_a" in st.session_state:
    st.markdown("---")
    st.markdown("### 🔄 修正後的最終報告")
    st.write(st.session_state.new_analysis_a)
    
    if st.button("🔍 進行最後審計並輸出機器數據包"):
        audit_prompt = f"審計報告：{st.session_state.new_analysis_a}。請輸出嚴格 JSON。"
        st.session_state.machine_json = critic_ai(audit_prompt)
        st.rerun()

if "machine_json" in st.session_state:
    st.success("✅ 決策數據包已準備就緒")
    st.code(st.session_state.machine_json, language='json')
