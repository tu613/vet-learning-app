import streamlit as st
import time
import os
import pymongo
from pymongo import MongoClient
import google.generativeai as genai # เปลี่ยนมาใช้ตัวมาตรฐาน

# ==============================================================================
# 1. CONFIGURATION & SETUP
# ==============================================================================
st.set_page_config(page_title="Vet Learning Companion App", page_icon="🐾", layout="wide")

# ชื่อ Database และ Collection
CASE_DATABASE_NAME = 'case_scenario'
GVCCCM_DATABASE_NAME = 'GVCCCM'
GVCCCM_STEP_COLLECTION = 'Step'
GVCCCM_SCORE_COLLECTION = 'Score'

# *** ใช้ชื่อโมเดลนี้ รับรองผ่านชัวร์ ***
MODEL_NAME = 'gemini-1.5-flash' 

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

# ตั้งค่า API Key ให้ Library ทันทีที่เริ่มแอป
try:
    genai.configure(api_key=get_secret("GEMINI_API_KEY"))
except:
    pass # ปล่อยผ่านไปก่อน ถ้ายังไม่ใส่ Key เดี๋ยวไปแจ้งเตือนตอนรัน

# ==============================================================================
# 2. MONGODB FUNCTIONS (ดึงข้อมูลและแคช)
# ==============================================================================

@st.cache_data(ttl=3600)
def fetch_gvcccm_data():
    """ดึงข้อมูลขั้นตอน GVCCCM (Step) จาก MongoDB"""
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
        if client:
            client.close()

@st.cache_data(ttl=3600)
def fetch_score_checklist():
    """ดึงข้อมูล Checklist สำหรับการให้คะแนน"""
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
            st.warning("❌ ไม่พบ Checklist ใน Database")
            return []

    except Exception as e:
        st.error(f"❌ Error fetching score checklist: {e}")
        return []
    finally:
        if client:
            client.close()

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
# 3. GEMINI FUNCTIONS (ปรับมาใช้ google.generativeai ตัวมาตรฐาน)
# ==============================================================================

def final_evaluation(conversation_history, gvcccm_context, score_context):
    """ส่งประวัติการสนทนาให้ AI ประเมินผล"""
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
            
            # สร้าง Model
            model = genai.GenerativeModel(
                model_name=MODEL_NAME,
                system_instruction=system_instruction
            )
            
            # ส่งคำสั่ง
            response = model.generate_content(f"ประวัติการสนทนา:\n{history_text}\n\nประเมินผลตามคำสั่ง")
            
            # บันทึกผลและเปลี่ยนหน้า
            st.session_state.final_feedback = response.text
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
    cases = [
        {"id": 1, "name": "สุนัขชื่อ 'Philippe' (Vaccination)", "level": "Easy", 
         "owner_persona": "รักสัตว์มาก แต่พูดวกวน ให้ข้อมูลไม่ค่อยตรงประเด็น"},
        {"id": 2, "name": "แมวชื่อ 'มิมิ' (Vomiting)", "level": "Medium",
         "owner_persona": "กังวลเรื่องค่าใช้จ่าย หงุดหงิดง่าย"},
    ]
    
    for case in cases:
        with st.container(border=True):
            c1, c2 = st.columns([3, 1])
            c1.markdown(f"**{case['name']}**")
            c1.caption(case['owner_persona'])
            if c2.button("เริ่มฝึก", key=case['id']):
                # เตรียม Prompt สำหรับเจ้าของสัตว์
                sys_instruct = (
                    f"คุณคือเจ้าของสัตว์ในเคส: {case['name']} บุคลิก: {case['owner_persona']} "
                    "จงตอบคำถามนักศึกษาตามบทบาท ห้ามหลุดบท ห้ามให้คะแนน ตอบสั้นๆกระชับแบบคนทั่วไปคุยกัน"
                )
                
                # เก็บ System Instruction ไว้สร้าง Chat Session
                st.session_state.owner_system_prompt = sys_instruct
                st.session_state.current_case = case
                st.session_state.chat_history = []
                st.session_state.chat_session = None # Reset Chat Session
                st.session_state.page = 'chat'
                st.rerun()

def chat_page(gvcccm_context, score_context):
    st.title(f"💬 ห้องตรวจ: {st.session_state.current_case['name']}")
    
    # เริ่ม Chat Session ถ้ายังไม่มี
    if 'chat_session' not in st.session_state or st.session_state.chat_session is None:
        model = genai.GenerativeModel(
            model_name=MODEL_NAME,
            system_instruction=st.session_state.owner_system_prompt
        )
        st.session_state.chat_session = model.start_chat(history=[])

    with st.sidebar:
        if st.button("🛑 จบการซักประวัติและประเมินผล", type="primary"):
            final_evaluation(st.session_state.chat_history, gvcccm_context, score_context)
    
    # แสดง Chat History
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            
    # รับ Input
    if prompt := st.chat_input("พิมพ์คำถามของคุณ..."):
        st.session_state.chat_history.append({"role": "User", "content": prompt})
        with st.chat_message("User"):
            st.write(prompt)
            
        try:
            with st.spinner("..."):
                # ส่งข้อความไปหา AI (ใช้ chat_session ที่สร้างไว้)
                response = st.session_state.chat_session.send_message(prompt)
                ai_msg = response.text
                
            st.session_state.chat_history.append({"role": "AI (Owner)", "content": ai_msg})
            with st.chat_message("AI (Owner)"):
                st.write(ai_msg)
                
        except Exception as e:
            st.error(f"Error: {e}")

def feedback_page():
    st.title("📊 ผลการประเมิน")
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
