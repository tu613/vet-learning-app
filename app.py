import streamlit as st
import time

# ตั้งค่าหน้าเว็บ
st.set_page_config(page_title="Vet Learning Companion", page_icon="🐾", layout="wide")

# --- ส่วนจัดการ Session (ความจำของแอป) ---
if 'page' not in st.session_state:
    st.session_state.page = 'login'
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []

# --- หน้าต่างๆ ของแอป ---

def login_page():
    st.title("🔐 Veterinary Learning Companion")
    st.subheader("ระบบจำลองสถานการณ์เพื่อฝึกซักประวัติสัตว์ป่วย")
    
    with st.form("login_form"):
        st.write("เข้าสู่ระบบเพื่อเริ่มการฝึกฝน")
        username = st.text_input("ชื่อผู้ใช้งาน")
        role = st.selectbox("สถานะ", ["นักศึกษา", "อาจารย์"])
        submitted = st.form_submit_button("เข้าสู่ระบบ")
        
        if submitted:
            st.success(f"ยินดีต้อนรับคุณ {username} ({role})")
            time.sleep(1)
            st.session_state.page = 'case_selection'
            st.rerun()

def case_selection_page():
    st.title("📋 เลือกเคสฝึกซ้อม (Case Scenarios)")
    
    # ข้อมูลจำลอง (Mock Data)
    cases = [
        {"id": 1, "name": "สุนัขชื่อ 'Philippe' (ตรวจสุขภาพและฉีดวัคซีนประจำปี)", "level": "Easy"},
        {"id": 2, "name": "แมวชื่อ 'มิมิ' (อาการ: อาเจียน)", "level": "Medium"},
    ]
    
    for case in cases:
        with st.container(border=True):
            col1, col2 = st.columns([3, 1])
            col1.markdown(f"**{case['name']}**")
            col1.caption(f"ความยาก: {case['level']}")
            if col2.button("เลือกเคสนี้", key=case['id']):
                st.session_state.page = 'chat'
                st.session_state.current_case = case['name']
                st.rerun()

def chat_page():
    st.title(f"💬 ห้องตรวจ: {st.session_state.current_case}")
    st.info("💡 Tip: ลองถามคำถามเช่น 'น้องเป็นมานานหรือยังครับ?' หรือ 'กินอาหารได้ไหม?'")
    
    # ปุ่มย้อนกลับ
    if st.button("⬅️ เปลี่ยนเคส"):
        st.session_state.page = 'case_selection'
        st.session_state.chat_history = []
        st.rerun()
    
    # แสดงประวัติแชท
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            
    # ช่องกรอกข้อความ
    if prompt := st.chat_input("พิมพ์คำถามของคุณ..."):
        # 1. แสดงข้อความเรา
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)
            
        # 2. AI ตอบกลับ (จำลอง)
        time.sleep(1) # แกล้งทำเป็นคิด
        ai_reply = f"หมอครับ... เรื่อง '{prompt}' ผมก็ไม่แน่ใจ แต่หมาผมมันดูซึมๆ ตั้งแต่เมื่อวานครับ"
        
        st.session_state.chat_history.append({"role": "assistant", "content": ai_reply})
        with st.chat_message("assistant"):
            st.write(ai_reply)

# --- ตัวควบคุมหลัก ---
if st.session_state.page == 'login':
    login_page()
elif st.session_state.page == 'case_selection':
    case_selection_page()
elif st.session_state.page == 'chat':
    chat_page()
