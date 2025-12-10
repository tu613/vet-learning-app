import streamlit as st
import pymongo 
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

# *** เพิ่ม Collection สำหรับเก็บ Log ***
LOG_COLLECTION_NAME = 'practice_logs'

# *** แนะนำให้ใช้ 1.5-flash เพื่อความชัวร์ (2.5 ยังไม่มีให้ใช้ทั่วไป) ***
MODEL_NAME = 'gemini-2.5-flash'

# ฟังก์ชันช่วยตรวจสอบ Secrets
def get_secret(key, section=None):
    try:
        if section:
            return st.secrets[section][key]
        return st.secrets[key]
    except FileNotFoundError:
        st.error("🚨 ไม่พบไฟล์ .streamlit/secrets.toml")
        st.stop()
    except KeyError:
        st.error(f"🚨 ไม่พบ Key: '{key}' ใน secrets.toml")
        st.stop()

# ตั้งค่า API Key
try:
    genai.configure(api_key=get_secret("GEMINI_API_KEY"))
except:
    pass

# ==============================================================================
# 2. MONGODB FUNCTIONS (ดึงข้อมูล, แคช, และ **บันทึก**)
# ==============================================================================

@st.cache_data(ttl=3600)
def fetch_gvcccm_data():
    """ดึงข้อมูลขั้นตอน GVCCCM (Step)"""
    client = None
    try:
        mongo_uri = get_secret("MONGODB_URI", section="mongo")
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
def case_scenario():
    client = None
    mongo_uri = get_secret("MONGODB_URI", section="mongo")
    client = MongoClient(mongo_uri)
    db = client.case_scenario
    collection = db.dog.find()
    items = list(collection)
    return items

items = case_scenario()

# --- ฟังก์ชันใหม่: บันทึกประวัติการใช้งาน ---
def save_practice_log(user_info, case_info, conversation_history, feedback_text):
    """บันทึกข้อมูลการฝึกซ้อมลง MongoDB"""
    client = None
    try:
        mongo_uri = get_secret("MONGODB_URI", section="mongo")
        client = MongoClient(mongo_uri)
        
        # เลือก Database ที่จะเก็บ Log (เก็บไว้ในที่เดียวกับ Case ก็ได้ หรือจะแยกก็ได้)
        db = client[CASE_DATABASE_NAME] 
        collection = db[LOG_COLLECTION_NAME]

        # สร้าง Document ที่จะบันทึก
        log_document = {
            "user": user_info,                    # ข้อมูลคนเล่น (ชื่อ/role)
            "case_id": case_info.get('id'),       # ID เคส
            "case_name": case_info.get('name'),   # ชื่อเคส
            "chat_history": conversation_history, # ประวัติการคุยทั้งหมด
            "ai_feedback": feedback_text          # ผลประเมินจาก AI
        }

        # สั่งบันทึก
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
    """ส่งประวัติการสนทนาให้ AI ประเมินผล และบันทึกลง Database"""
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
            
            # เก็บผลลัพธ์ลง Session State
            st.session_state.final_feedback = response.text
            
            # --- ส่วนที่เพิ่ม: บันทึกลง Database ทันทีที่ได้ผลลัพธ์ ---
            with st.spinner("💾 กำลังบันทึกผลการฝึกซ้อม..."):
                save_success = save_practice_log(
                    st.session_state.user,        # ข้อมูลผู้ใช้จาก Login
                    st.session_state.current_case, # ข้อมูลเคสปัจจุบัน
                    conversation_history,          # ประวัติแชท
                    response.text                  # ผลประเมิน
                )
                
                if save_success:
                    st.toast("✅ บันทึกข้อมูลลง Database เรียบร้อยแล้ว!", icon="💾")
                else:
                    st.toast("⚠️ ไม่สามารถบันทึกข้อมูลได้", icon="❌")
            # -----------------------------------------------------

            st.session_state.page = 'feedback'
            st.rerun()

    except Exception as e:
        st.error(f"❌ Error during evaluation: {e}")

# ==============================================================================
# 4. PAGE FUNCTIONS
# ==============================================================================

def login_page():
    st.title("🔐 Veterinary Learning Companion")
    with st.form("login_form"):
        username = st.text_input("ชื่อผู้ใช้งาน")
        role = st.selectbox("สถานะ", ["นักศึกษา", "อาจารย์"])
        if st.form_submit_button("เข้าสู่ระบบ"):
            st.session_state.user = {'name': username, 'role': role}
            st.session_state.page = 'case_selection'
            st.rerun()

def case_selection_page():
    st.title("📋 เลือกเคสฝึกซ้อม")
    # ตรงนี้อนาคตควรดึง list เคสจาก Database
    cases = [
        {"id": 1, "name": "สุนัขชื่อ 'Philippe' (Vaccination)", "level": "Easy" },
        {"id": 2, "name": "แมวชื่อ 'มิมิ' (Vomiting)", "level": "Medium"}
    ]
    
    st.write(f"ผู้ใช้งาน: **{st.session_state.user['name']}** ({st.session_state.user['role']})")

    for case in cases:
        with st.container(border=True):
            c1, c2 = st.columns([3, 1])
            c1.markdown(f"**{case['name']}**")
            c1.caption(case['owner_persona'])
            if c2.button("เริ่มฝึก", key=case['id']):
                sys_instruct = (
                    f"คุณคือเจ้าของสัตว์ในเคส: {items}\n"
                    "จงตอบคำถามนักศึกษาตามบทบาท ห้ามหลุดบท ห้ามให้คะแนน ตอบสั้นๆกระชับแบบคนทั่วไปคุยกัน"
                )
                st.session_state.owner_system_prompt = sys_instruct
                st.session_state.current_case = case
                st.session_state.chat_history = []
                st.session_state.chat_session = None
                st.session_state.page = 'chat'
                st.rerun()

def chat_page(gvcccm_context, score_context):
    st.title(f"💬 ห้องตรวจ: {st.session_state.current_case['name']}")
    
    if 'chat_session' not in st.session_state or st.session_state.chat_session is None:
        model = genai.GenerativeModel(
            model_name=MODEL_NAME,
            system_instruction=st.session_state.owner_system_prompt
        )
        st.session_state.chat_session = model.start_chat(history=[])

    with st.sidebar:
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
    st.success("✅ บันทึกข้อมูลการฝึกซ้อมลงในระบบเรียบร้อยแล้ว") # แจ้งเตือนผู้ใช้
    st.markdown(st.session_state.final_feedback)
    if st.button("กลับหน้าหลัก"):
        st.session_state.page = 'case_selection'
        st.session_state.final_feedback = None
        st.rerun()

# ==============================================================================
# 5. MAIN APP
# ==============================================================================

if 'page' not in st.session_state: st.session_state.page = 'login'
if 'chat_history' not in st.session_state: st.session_state.chat_history = []
# ตรวจสอบว่ามีข้อมูล user หรือยัง ถ้าไม่มีให้เด้งไปหน้า login (กรณี refresh หน้าจอ)
if 'user' not in st.session_state and st.session_state.page != 'login':
    st.session_state.page = 'login'

if __name__ == "__main__":
    gvcccm_data = fetch_gvcccm_data()
    score_stages = fetch_score_checklist()
    
    if gvcccm_data and score_stages:
        ctx_gvcccm = create_gvcccm_context(gvcccm_data)
        ctx_score = create_score_context(score_stages)
        
        if st.session_state.page == 'login': login_page()
        elif st.session_state.page == 'case_selection': case_selection_page()
        elif st.session_state.page == 'chat': chat_page(ctx_gvcccm, ctx_score)
        elif st.session_state.page == 'feedback': feedback_page()
    else:
        st.error("ไม่สามารถโหลดข้อมูลระบบได้ กรุณาตรวจสอบการเชื่อมต่อ Database")




