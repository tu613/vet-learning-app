from pymongo import MongoClient
import pymongo
from google import genai
from google.genai.errors import APIError
import streamlit as st
import time
import os
import json

# ==============================================================================
# 1. CONFIGURATION & SETUP (จาก testplusfeedscore.py)
# ==============================================================================
# *** กรุณาตั้งค่า GEMINI_API_KEY ใน Environment Variable หรือ st.secrets ก่อนรันโค้ด ***
# MONGODB_URI: ใช้สำหรับเชื่อมต่อ MongoDB (ควรเก็บไว้ใน st.secrets)
MONGODB_URI = 'mongodb+srv://tuchtiew1JJJ:TuchKwyKNG@testproject.pd7m3ia.mongodb.net/?appName=testproject'
CASE_DATABASE_NAME = 'case_scenario'
GVCCCM_DATABASE_NAME = 'GVCCCM'
GVCCCM_STEP_COLLECTION = 'Step'
GVCCCM_SCORE_COLLECTION = 'Score'
MODEL_NAME = 'gemini-2.5-pro'

st.set_page_config(page_title="Vet Learning Companion App (Integrated)", page_icon="🐾", layout="wide")

# ==============================================================================
# 2. MONGO DB & CONTEXT FUNCTIONS (จาก testplusfeedscore.py, เพิ่ม @st.cache_data)
# ==============================================================================

@st.cache_data(ttl=3600) # แคชข้อมูล 1 ชั่วโมง
def fetch_gvcccm_data():
    """ดึงข้อมูลขั้นตอน GVCCCM (Step) ทั้งหมดจาก MongoDB และแคชไว้"""
    client = None
    try:
        client = MongoClient(MONGODB_URI)
        db = client[GVCCCM_DATABASE_NAME]
        collection = db[GVCCCM_STEP_COLLECTION]
        gvcccm_data_list = list(collection.find(
            {},
            {"_id": 0, "step_number": 1, "step_name_th": 1, "summary_detail": 1}
        ).sort("step_number", pymongo.ASCENDING))
        
        print(f"✅ ดึงข้อมูล GVCCCM Steps ได้ {len(gvcccm_data_list)} ขั้นตอน (Cached)")
        return gvcccm_data_list

    except Exception as e:
        st.error(f"❌ Error fetching GVCCCM steps: {e}")
        return []
    finally:
        if client:
            client.close()
            
@st.cache_data(ttl=3600)
def fetch_score_checklist():
    """ดึงข้อมูล Checklist สำหรับการให้คะแนน (Calgary-Cambridge Skills List) และแคชไว้"""
    client = None
    try:
        client = MongoClient(MONGODB_URI)
        db = client[GVCCCM_DATABASE_NAME]
        collection = db[GVCCCM_SCORE_COLLECTION]
        checklist_data = collection.find_one({"checklist_name": "Calgary-Cambridge Consultation Communication Skills List"})

        if checklist_data:
            print(f"✅ ดึงข้อมูล Checklist ({checklist_data.get('version')}) ได้สำเร็จ (Cached)")
            return checklist_data.get('assessment_stages', [])
        else:
            st.warning("❌ ไม่พบ Checklist สำหรับการให้คะแนน")
            return []

    except Exception as e:
        st.error(f"❌ Error fetching score checklist: {e}")
        return []
    finally:
        if client:
            client.close()

def create_gvcccm_context(gvcccm_data):
    """สร้าง String Context สำหรับ Prompt จากข้อมูล GVCCCM Step"""
    if not gvcccm_data:
        return "ไม่พบข้อมูลมาตรฐาน GVCCCM สำหรับการอ้างอิง"

    context_str = "--- หลักการ GVCCCM (Good Veterinary Communication and Clinical Method) ---\n"
    for step in gvcccm_data:
        context_str += (
            f"- **ขั้นตอนที่ {step.get('step_number')}: {step.get('step_name_th')}**\n"
            f"  * หลักการ: {step.get('summary_detail', '')}\n"
        )
    return context_str

def create_score_context(assessment_stages):
    """สร้าง String Context สำหรับ Prompt จากข้อมูล Checklist เพื่อให้คะแนน"""
    if not assessment_stages:
        return "ไม่พบรายการทักษะการสื่อสารสำหรับการให้คะแนน"

    context_str = "--- รายการทักษะการสื่อสาร Calgary-Cambridge (สำหรับการให้คะแนน 1-5) ---\n"
    
    for stage in assessment_stages:
        context_str += f"\n## {stage.get('stage_id').upper()}. {stage.get('stage_name_th')} ({stage.get('stage_name_en')})\n"
        for skill in stage.get('skills', []):
            # ใส่ [ ] เพื่อให้ AI รู้ว่านี่คือรายการที่ต้องให้คะแนน
            context_str += f" - [ ] **{skill.get('skill_item')}**\n" 
            
    context_str += "\n------------------------------------------------------------------------------------------------------"
    context_str += "\nคำแนะนำ: AI จะต้องให้คะแนนแต่ละทักษะ (Skill Item) จาก 1-5 (1=ไม่ทำเลย, 5=ทำได้ดีเยี่ยม) และระบุเหตุผลที่ให้คะแนนโดยอ้างอิงจากประวัติการสนทนา"
    return context_str


# ==============================================================================
# 3. GEMINI EVALUATION FUNCTION (จาก testplusfeedscore.py)
# ==============================================================================

def final_evaluation(conversation_history, gvcccm_context, score_context):
    """
    ส่งประวัติการสนทนาทั้งหมดไปยัง AI เพื่อประเมินตามมาตรฐาน GVCCCM และ Checklist
    """
    try:
        ai_client = genai.Client()
        st.info("🧠 กำลังส่งประวัติการสนทนาทั้งหมดเพื่อรับการประเมิน...")

        # 1. เตรียมประวัติการสนทนา (User: text, AI (Owner): text)
        history_text = "\n".join([f"{item['role']}: {item['content']}" for item in conversation_history])
        
        # 2. สร้าง System Instruction
        system_instruction = (
            "คุณคือผู้เชี่ยวชาญด้านการสื่อสารและการซักประวัติทางการแพทย์สัตว์ "
            "หน้าที่ของคุณคือ **ประเมินการซักประวัติที่ปรากฏใน 'ประวัติการสนทนา'** "
            "โดยใช้หลักการ GVCCCM เป็นแนวทางในการสรุป และใช้รายการทักษะ Calgary-Cambridge เพื่อให้คะแนน.\n"
            
            f"{score_context}\n"
            f"--- หลักการ GVCCCM (สำหรับ Feedback สรุป) ---\n{gvcccm_context}\n"
            
            "การตอบกลับของคุณต้องประกอบด้วย 3 ส่วน เรียงตามลำดับ:\n"
            "1. **การประเมินคะแนนรายทักษะ (Skill Scoring)**: ให้คะแนนทุกทักษะในรายการ Calgary-Cambridge (1-5) พร้อมเหตุผลสั้นๆ \n"
            "2. **ภาพรวมการซักประวัติ (Overall Summary)**: สรุปว่าการซักประวัติครอบคลุมขั้นตอนใดของ GVCCCM (Step) ไปแล้วบ้าง และให้คะแนนเฉลี่ยรวมโดยประมาณ.\n"
            "3. **คำแนะนำสำหรับการปรับปรุง (Suggestion)**: ให้คำแนะนำสั้นๆ เพื่อปรับปรุงการสื่อสาร/การซักประวัติโดยรวม.\n"
            "ใช้ภาษาไทยที่สุภาพและเป็นมืออาชีพ"
        )
        
        prompt_content = [
            f"ประวัติการสนทนาทั้งหมด (การซักประวัติ):\n\n{history_text}\n\n"
            "โปรดทำการประเมินและให้ Feedback สรุปตามรูปแบบที่กำหนดโดยอิงจากประวัติการสนทนาข้างต้น"
        ]

        # 3. เรียกใช้ API เพื่อประเมิน
        config = genai.types.GenerateContentConfig(
            system_instruction=system_instruction
        )
        
        response = genai.Client().models.generate_content(
            model=MODEL_NAME,
            contents=prompt_content,
            config=config
        )

        st.success("🎉 ประเมินผลสำเร็จ!")
        st.markdown("---")
        st.markdown(response.text)
        st.markdown("---")
        st.session_state.page = 'feedback'
        st.rerun()

    except APIError as e:
        st.error(f"❌ An API error occurred during final evaluation: {e}")
    except Exception as e:
        st.error(f"❌ An unexpected error occurred during final evaluation: {e}")
        st.code(f"Error details: {e}")

# ==============================================================================
# 4. STREAMLIT UI INTEGRATION
# ==============================================================================

# --- Session State Initialization ---
if 'page' not in st.session_state:
    st.session_state.page = 'login'
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []
if 'owner_config' not in st.session_state:
    st.session_state.owner_config = None # เก็บ config ของ AI เจ้าของสัตว์
if 'current_case' not in st.session_state:
    st.session_state.current_case = None 
if 'final_feedback' not in st.session_state:
    st.session_state.final_feedback = None 

# --- Page Functions ---

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
    
    # ข้อมูลจำลอง (Mock Data) - ควรเปลี่ยนเป็นดึงจาก MongoDB จริง
    cases = [
        {"id": 1, "name": "สุนัขชื่อ 'Philippe' (ตรวจสุขภาพและฉีดวัคซีนประจำปี)", "level": "Easy", 
         "owner_persona": "เจ้าของที่พูดกำกวม ไม่ค่อยให้ข้อมูล แต่มีความรักสัตว์สูง"},
        {"id": 2, "name": "แมวชื่อ 'มิมิ' (อาการ: อาเจียน)", "level": "Medium",
         "owner_persona": "เจ้าของที่กังวลและกลัวค่าใช้จ่าย"},
    ]
    
    for case in cases:
        with st.container(border=True):
            col1, col2 = st.columns([3, 1])
            col1.markdown(f"**{case['name']}**")
            col1.caption(f"บุคลิก: {case['owner_persona']}")
            if col2.button("เริ่มฝึกเคสนี้", key=case['id']):
                # 1. กำหนด System Instruction สำหรับบทบาทเจ้าของสัตว์เลี้ยง
                owner_system_instruction = (
                    f"คุณคือเจ้าของสัตว์เลี้ยงในเคส: {case['name']} บุคลิกของเจ้าของ: {case['owner_persona']} "
                    "หน้าที่ของคุณคือตอบคำถามของผู้ใช้ในฐานะเจ้าของสัตว์เลี้ยง "
                    "ห้ามให้ Feedback หรือประเมิน GVCCCM ใดๆ ใช้ภาษาไทยที่สุภาพ"
                )
                owner_config = genai.types.GenerateContentConfig(
                    system_instruction=owner_system_instruction
                )
                
                st.session_state.current_case = case
                st.session_state.owner_config = owner_config
                st.session_state.chat_history = []
                st.session_state.page = 'chat'
                st.rerun()

def chat_page(gvcccm_context, score_context):
    st.title(f"💬 ห้องตรวจ: {st.session_state.current_case['name']}")
    st.info("💡 Tip: การสนทนาจะถูกประเมินโดย AI ตามหลัก GVCCCM เมื่อคุณกด 'จบการซักประวัติ'")
    
    with st.sidebar:
        st.markdown(f"**เคส:** {st.session_state.current_case['name']}")
        st.markdown(f"**บุคลิก:** {st.session_state.current_case['owner_persona']}")
        if st.button("🛑 จบการซักประวัติและดู Feedback", type="primary"):
            # เรียกฟังก์ชันประเมินทันที
            final_evaluation(st.session_state.chat_history, gvcccm_context, score_context)
    
    # แสดงประวัติแชท
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            
    # ช่องกรอกข้อความ (User Input)
    if prompt := st.chat_input("พิมพ์คำถามของคุณ..."):
        # 1. แสดงคำถามของผู้ใช้
        with st.chat_message("User"):
            st.write(prompt)
        st.session_state.chat_history.append({"role": "User", "content": prompt})
            
        try:
            # 2. AI ตอบกลับ (ในฐานะเจ้าของสัตว์)
            with st.spinner("🤖 AI (เจ้าของสัตว์เลี้ยง) กำลังตอบ..."):
                response = genai.Client().models.generate_content(
                    model=MODEL_NAME,
                    contents=prompt,
                    config=st.session_state.owner_config
                )
            
            owner_answer = response.text
            
            # 3. บันทึกและแสดงคำตอบของ AI
            st.session_state.chat_history.append({"role": "AI (Owner)", "content": owner_answer})
            with st.chat_message("AI (Owner)"):
                st.write(owner_answer)

        except APIError as e:
            st.error(f"❌ API Error: {e}")
        except Exception as e:
            st.error(f"❌ An unexpected error occurred: {e}")


def feedback_page():
    st.title("✅ ผลการประเมิน GVCCCM")
    st.markdown(st.session_state.final_feedback)
    if st.button("⬅️ กลับหน้าเลือกเคส"):
        st.session_state.page = 'case_selection'
        st.session_state.final_feedback = None
        st.rerun()


# ==============================================================================
# 5. MAIN EXECUTION BLOCK
# ==============================================================================

if __name__ == "__main__":
    
    # 1. โหลดข้อมูล GVCCCM/Checklist (ทำครั้งเดียว)
    with st.spinner("กำลังโหลดข้อมูล GVCCCM และ Checklist จาก MongoDB..."):
        gvcccm_data = fetch_gvcccm_data()
        score_stages = fetch_score_checklist()
        
        if not gvcccm_data or not score_stages:
            st.error("ไม่สามารถโหลดข้อมูลพื้นฐานสำหรับการประเมินได้ กรุณาตรวจสอบ MongoDB URI และ Collections")
            st.stop()
            
    # 2. สร้าง Context String (ใช้ซ้ำได้)
    gvcccm_context = create_gvcccm_context(gvcccm_data)
    score_context = create_score_context(score_stages)

    # 3. Router
    if st.session_state.page == 'login':
        login_page()
    elif st.session_state.page == 'case_selection':
        case_selection_page()
    elif st.session_state.page == 'chat':
        chat_page(gvcccm_context, score_context)
    elif st.session_state.page == 'feedback':
        feedback_page()
