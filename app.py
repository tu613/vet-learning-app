import streamlit as st
import pymongo 
import os
from pymongo import MongoClient
import google.generativeai as genai

# ==============================================================================
# 1. CONFIGURATION & SETUP
# ==============================================================================
st.set_page_config(page_title="Vet Learning Companion App", page_icon="🐾", layout="wide")

# ชื่อ Database และ Collection
CASE_DATABASE_NAME = 'case_scenario'
GVCCCM_DATABASE_NAME = 'GVCCCM'
GVCCCM_STEP_COLLECTION = 'Step'
GVCCCM_SCORE_COLLECTION = 'Score'
LOG_COLLECTION_NAME = 'practice_logs'

# *** แก้ชื่อโมเดลให้ถูกต้อง (แนะนำ 1.5-flash เพื่อความชัวร์) ***
MODEL_NAME = 'gemini-2.5-flash'

# --- ฟังก์ชันช่วยดึงค่า Key (แก้ใหม่ให้รองรับ section) ---
def get_secret(key, section=None):
    """
    ดึงค่า Secret โดยลำดับความสำคัญ:
    1. os.environ (สำหรับ Render)
    2. st.secrets (สำหรับ Local)
    """
    # 1. ลองดึงจาก Environment Variable ก่อน (Render มักเก็บแบบ Flat key)
    # เช่น MONGODB_URI ก็จะเก็บชื่อนั้นเลย ไม่สน section
    value = os.environ.get(key)
    if value:
        return value

    # 2. ถ้าไม่เจอ ให้ลองดึงจาก st.secrets (สำหรับ Run ในเครื่องตัวเอง)
    try:
        if section and section in st.secrets:
            return st.secrets[section][key]
        return st.secrets[key]
    except (FileNotFoundError, KeyError):
        return None

# เรียกใช้ฟังก์ชัน (Render ใช้ชื่อ GEMINI_API_KEY ตรงๆ)
api_key = get_secret("GEMINI_API_KEY")

# ตรวจสอบว่าได้ Key มาไหม
if not api_key:
    st.error("🚨 ไม่พบ API Key! กรุณาตั้งค่า 'GEMINI_API_KEY' ใน Render Environment Variables")
    st.stop()

# ตั้งค่า Gemini
genai.configure(api_key=api_key)

# ==============================================================================
# 2. MONGODB FUNCTIONS
# ==============================================================================

@st.cache_data(ttl=3600)
def fetch_gvcccm_data():
    """ดึงข้อมูลขั้นตอน GVCCCM (Step)"""
    client = None
    try:
        # เรียกใช้แบบระบุ section ได้แล้ว เพราะแก้ฟังก์ชัน get_secret แล้ว
        mongo_uri = get_secret("MONGODB_URI", section="mongo")
        if not mongo_uri: return []
        
        client = MongoClient(mongo_uri)
        db = client[GVCCCM_DATABASE_NAME]
        collection = db[GVCCCM_STEP_COLLECTION]
        gvcccm_data_list = list(collection.find(
            {},
            {"_id": 0, "step_number": 1, "step_name_th": 1, "summary_detail": 1}
        ).sort("step_number", pymongo.ASCENDING))
        return gvcccm_data_list
    except Exception as e:
        st.error(f"❌ Error fetching GVCCCM steps: {e}")
        return []
    finally:
        if client: client.close()

@st.cache_data(ttl=3600)
def fetch_score_checklist():
    """ดึงข้อมูล Checklist"""
    client = None
    try:
        mongo_uri = get_secret("MONGODB_URI", section="mongo")
        if not mongo_uri: return []

        client = MongoClient(mongo_uri)
        db = client[GVCCCM_DATABASE_NAME]
        collection = db[GVCCCM_SCORE_COLLECTION]
        checklist_data = collection.find_one({"checklist_name": "Calgary-Cambridge Consultation Communication Skills List"})
        if checklist_data:
            return checklist_data.get('assessment_stages', [])
        else:
            return []
    except Exception as e:
        st.error(f"❌ Error fetching score checklist: {e}")
        return []
    finally:
        if client: client.close()

@st.cache_data(ttl=3600)
def fetch_case_scenario():
    """ดึงข้อมูลเคสจาก Mongo (เปลี่ยนชื่อฟังก์ชันให้ชัดเจนขึ้น)"""
    client = None
    try:
        mongo_uri = get_secret("MONGODB_URI", section="mongo")
        if not mongo_uri: return []

        client = MongoClient(mongo_uri)
        db = client.case_scenario
        # ดึงมาแค่บางส่วนหรือทั้งหมด แปลง ObjectId เป็น str เพื่อกัน Error เวลา cache
        items = []
        for doc in db.dog.find():
            doc['_id'] = str(doc['_id']) # แปลง ObjectId เป็น String
            items.append(doc)
        return items
    except Exception as e:
        # st.error(f"❌ Error fetching cases: {e}") # ปิด error ไว้ก่อนเพื่อไม่ให้รกหน้าจอถ้า connect ไม่ได้
        return []
    finally:
        if client: client.close()

# เรียกใช้ฟังก์ชันดึงข้อมูล (ย้ายมาไว้ใน main จะปลอดภัยกว่า แต่ประกาศตัวแปรไว้ก่อนได้)
items = [] 

def save_practice_log(user_info, case_info, conversation_history, feedback_text):
    """บันทึกข้อมูลการฝึกซ้อมลง MongoDB"""
    client = None
    try:
        mongo_uri = get_secret("MONGODB_URI", section="mongo")
        client = MongoClient(mongo_uri)
        
        db = client[CASE_DATABASE_NAME] 
        collection = db[LOG_COLLECTION_NAME]

        log_document = {
            "user": user_info,                    
            "case_id": case_info.get('id'),       
            "case_name": case_info.get('name'),   
            "chat_history": conversation_history, 
            "ai_feedback": feedback_text          
        }

        collection.insert_one(log_document)
        return True

    except Exception as e:
        st.error(f"❌ Error saving practice log: {e}")
        return False
    finally:
        if client: client.close()


def create_gvcccm_context(gvcccm_data):
    if not gvcccm_data: return "ไม่พบข้อมูลมาตรฐาน GVCCCM"
    context_str = "--- หลักการ GVCCCM ---\n"
    for step in gvcccm_data:
        context_str += f"- ขั้นตอนที่ {step.get('step_number')}: {step.get('step_name_th')} ({step.get('summary_detail', '')})\n"
    return context_str

def create_score_context(assessment_stages):
    if not assessment_stages: return "ไม่พบรายการทักษะ"
    context_str = "--- เกณฑ์การให้คะแนน Calgary-Cambridge (1-5) ---\n"
    for stage in assessment_stages:
        context_str += f"\n## {stage.get('stage_name_th')}\n"
        for skill in stage.get('skills', []):
            context_str += f" - [ ] {skill.get('skill_item')}\n"
    context_str += "\nคำแนะนำ: ให้คะแนน 1-5 และระบุเหตุผล"
    return context_str

# ==============================================================================
# 3. GEMINI FUNCTIONS
# ==============================================================================

def final_evaluation(conversation_history, gvcccm_context, score_context):
    try:
        with st.spinner("🧠 AI กำลังวิเคราะห์ผลการซักประวัติ..."):
            history_text = "\n".join([f"{item['role']}: {item['content']}" for item in conversation_history])
            
            system_instruction = (
                "คุณคืออาจารย์สัตวแพทย์ผู้เชี่ยวชาญ หน้าที่คือประเมินนักศึกษาตามหลัก GVCCCM "
                "โดยใช้ข้อมูลต่อไปนี้:\n"
                f"{score_context}\n"
                f"{gvcccm_context}\n"
                "โปรดให้ Feedback 3 ส่วน: 1. คะแนนรายทักษะ 2. สรุปภาพรวม 3. ข้อเสนอแนะ"
            )
            
            model = genai.GenerativeModel(
                model_name=MODEL_NAME,
                system_instruction=system_instruction
            )
            
            response = model.generate_content(f"ประวัติการสนทนา:\n{history_text}\n\nประเมินผลตามคำสั่ง")
            
            st.session_state.final_feedback = response.text
            
            with st.spinner("💾 กำลังบันทึกผลการฝึกซ้อม..."):
                save_success = save_practice_log(
                    st.session_state.user,        
                    st.session_state.current_case, 
                    conversation_history,          
                    response.text                  
                )
                
                if save_success:
                    st.toast("✅ บันทึกข้อมูลลง Database เรียบร้อยแล้ว!", icon="💾")
                else:
                    st.toast("⚠️ ไม่สามารถบันทึกข้อมูลได้", icon="❌")

            st.session_state.page = 'feedback'
            st.rerun()

    except Exception as e:
        st.error(f"❌ Error during evaluation: {e}")

# ==============================================================================
# 4. PAGE FUNCTIONS (UPDATED)
# ==============================================================================

def login_page():
    st.title("🔐 Veterinary Learning Companion")
    with st.form("login_form"):
        username = st.text_input("ชื่อผู้ใช้งาน")
        role = st.selectbox("สถานะ", ["นักศึกษา", "อาจารย์"])
        if st.form_submit_button("เข้าสู่ระบบ"):
            if username:
                st.session_state.user = {'name': username, 'role': role}
                st.session_state.page = 'case_selection'
                st.rerun()
            else:
                st.warning("กรุณากรอกชื่อผู้ใช้งาน")

def case_selection_page():
    st.title("📋 เลือกเคสฝึกซ้อม")
    st.write(f"ผู้ใช้งาน: **{st.session_state.user['name']}** ({st.session_state.user['role']})")
    
    # ดึงข้อมูลจาก Global variable 'items' ที่โหลดมาจาก Mongo
    global items
    if not items:
        # ลองโหลดใหม่เผื่อตอนแรกโหลดไม่ติด
        items = fetch_case_scenario()

    if not items:
        st.info("ไม่พบข้อมูลเคสในระบบ หรือกำลังโหลดข้อมูล...")
        return

    # Loop แสดงรายการเคสจาก MongoDB
    # (สมมติว่าใน Mongo มี field: pet_name, difficulty_level, short_description)
    for case in items:
        with st.container(border=True):
            c1, c2 = st.columns([4, 1])
            
            # ส่วนแสดงผลข้อมูลเบื้องต้นในหน้าเลือก
            pet_name = case.get('pet_name', 'ไม่ระบุชื่อ')
            
            with c1:
                st.subheader(f"🐾 {pet_name} ")
                # แสดงคำโปรยสั้นๆ (ถ้ามี) หรือแสดงบางส่วนของ detail

            with c2:
                # ปุ่มกดเพื่อไปดูรายละเอียด (ยังไม่เริ่มแชท)
                if st.button("ดูข้อมูลเคส", key=f"btn_{case['_id']}"):
                    st.session_state.current_case = case
                    st.session_state.page = 'case_detail' # ย้ายไปหน้า Detail
                    st.rerun()

# --- หน้าใหม่: แสดงรายละเอียดเคสก่อนเริ่ม ---
def case_detail_page():
    # ตรวจสอบว่ามีเคสถูกเลือกมาจริงไหม
    if 'current_case' not in st.session_state or not st.session_state.current_case:
        st.error("เกิดข้อผิดพลาด: ไม่พบข้อมูลเคส")
        if st.button("กลับหน้าเลือกเคส"):
            st.session_state.page = 'case_selection'
            st.rerun()
        return

    case = st.session_state.current_case
    
    st.title(f"📄 ข้อมูลสัตว์ป่วย: {case.get('pet_name', '-')}")
    
    # 1. แสดงรายละเอียดสัตว์ป่วย (Signalment & History)
    st.info("### 🐶 ข้อมูลสัตว์ป่วย (Pet Details)")
    st.write(case.get('pet_details', 'ไม่ระบุรายละเอียด'))

    # 2. แสดงบทบาทสมมติของเจ้าของ (Owner Role)
    st.warning("### 👤 ข้อมูลเจ้าของสัตว์ (Owner Profile)")
    st.write(f"**บทบาท:** {case.get('role_th', 'ไม่ระบุ')}")
    # (Optional) อาจจะซ่อน Persona ลึกๆ ไว้ไม่ให้นักศึกษาเห็น หรือจะโชว์ก็ได้ตาม Design
    # st.caption(f"Note: {case.get('owner_persona', '')}") 

    st.divider()

    col_back, col_start = st.columns([1, 1])
    
    with col_back:
        if st.button("⬅️ ย้อนกลับ"):
            st.session_state.page = 'case_selection'
            st.session_state.current_case = None # Clear selection
            st.rerun()
            
    with col_start:
        if st.button("🚀 เริ่มซักประวัติ (Start Chat)", type="primary"):
            # --- สร้าง System Prompt ตรงนี้ ---
            # ดึงข้อมูลจาก MongoDB มาใส่ใน Prompt
            pet_name = case.get('pet_name', 'สัตว์เลี้ยง')
            pet_details = case.get('pet_details', '-')
            owner_persona = case.get('owner_persona', 'ตอบคำถามตามปกติ')
            owner_role = case.get('owner_role_th', '-')

            sys_instruct = (
                f"คุณคือเจ้าของสัตว์เลี้ยงชื่อ '{pet_name}'\n"
                f"ข้อมูลสัตว์เลี้ยงและอาการ: {pet_details}\n"
                f"บทบาทของคุณคือ: {owner_role}\n"
                f"บุคลิกและอารมณ์ของคุณ (Persona): {owner_persona}\n"
                "--------------------------------------------------\n"
                "คำสั่ง:\n"
                "1. จงสวมบทบาทเป็นเจ้าของสัตว์อย่างสมจริง ตามข้อมูลด้านบน\n"
                "2. ตอบคำถามนักสัตวแพทย์ (User) ตามอาการที่เป็นจริง\n"
                "3. ห้ามหลุดบท ห้ามบอกว่าเป็น AI\n"
                "4. ตอบสั้นๆ กระชับ เหมือนบทสนทนาจริง ไม่ต้องทางการมาก\n"
            )
            
            # Setup Session
            st.session_state.owner_system_prompt = sys_instruct
            st.session_state.chat_history = []
            st.session_state.chat_session = None
            st.session_state.page = 'chat' # ไปหน้าแชท
            st.rerun()

def chat_page(gvcccm_context, score_context):
    st.title(f"💬 ห้องตรวจ: {st.session_state.current_case.get('pet_name', 'Case')}")
    
    if 'chat_session' not in st.session_state or st.session_state.chat_session is None:
        model = genai.GenerativeModel(
            model_name=MODEL_NAME,
            system_instruction=st.session_state.owner_system_prompt
        )
        st.session_state.chat_session = model.start_chat(history=[])

    with st.sidebar:
        # แสดงข้อมูลย่อๆ เผื่อลืม
        st.caption(f"กำลังซักประวัติเคส: **{st.session_state.current_case.get('pet_name')}**")
        st.divider()
        st.info("เมื่อกดจบการซักประวัติ ระบบจะประเมินผลและ **บันทึกข้อมูลอัตโนมัติ**")
        if st.button("🛑 จบการซักประวัติและประเมินผล", type="primary"):
            final_evaluation(st.session_state.chat_history, gvcccm_context, score_context)
    
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            
    if prompt := st.chat_input("พิมพ์คำถามของคุณ..."):
        st.session_state.chat_history.append({"role": "User", "content": prompt})
        with st.chat_message("User"):
            st.write(prompt)
            
        try:
            with st.spinner("..."):
                response = st.session_state.chat_session.send_message(prompt)
                ai_msg = response.text
                
            st.session_state.chat_history.append({"role": "AI (Owner)", "content": ai_msg})
            with st.chat_message("AI (Owner)"):
                st.write(ai_msg)
        except Exception as e:
            st.error(f"Error: {e}")

def feedback_page():
    st.title("📊 ผลการประเมิน")
    st.success("✅ บันทึกข้อมูลการฝึกซ้อมลงในระบบเรียบร้อยแล้ว") 
    st.markdown(st.session_state.final_feedback)
    if st.button("กลับหน้าหลัก"):
        st.session_state.page = 'case_selection'
        st.session_state.final_feedback = None
        st.session_state.current_case = None
        st.rerun()

# ==============================================================================
# 5. MAIN APP (UPDATED)
# ==============================================================================

if 'page' not in st.session_state: st.session_state.page = 'login'
if 'chat_history' not in st.session_state: st.session_state.chat_history = []
if 'user' not in st.session_state and st.session_state.page != 'login':
    st.session_state.page = 'login'

if __name__ == "__main__":
    # โหลดข้อมูลต่างๆ
    gvcccm_data = fetch_gvcccm_data()
    score_stages = fetch_score_checklist()
    items = fetch_case_scenario() # โหลดเคสจาก Mongo
    
    ctx_gvcccm = create_gvcccm_context(gvcccm_data) if gvcccm_data else ""
    ctx_score = create_score_context(score_stages) if score_stages else ""
    
    # เพิ่ม Logic การเปลี่ยนหน้า case_detail
    if st.session_state.page == 'login': login_page()
    elif st.session_state.page == 'case_selection': case_selection_page()
    elif st.session_state.page == 'case_detail': case_detail_page() # <-- หน้าใหม่ที่เพิ่มเข้ามา
    elif st.session_state.page == 'chat': chat_page(ctx_gvcccm, ctx_score)
    elif st.session_state.page == 'feedback': feedback_page()

