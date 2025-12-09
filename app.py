import streamlit as st
import google.generativeai as genai

st.title("🔍 Gemini Model Checker")
st.write("โค้ดนี้จะช่วยเช็กว่า API Key ของคุณมองเห็นโมเดลชื่ออะไรบ้าง")

# 1. ดึง Key และตั้งค่า
try:
    api_key = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=api_key)
    st.success("✅ พบ API Key และตั้งค่าสำเร็จ")
except Exception as e:
    st.error(f"❌ ไม่พบ API Key หรือตั้งค่าไม่สำเร็จ: {e}")
    st.stop()

# 2. สั่ง List รายชื่อโมเดลออกมาดู
st.write("---")
st.write("### 📋 รายชื่อโมเดลที่ใช้งานได้ (Available Models):")

try:
    found_models = []
    # วนลูปดูทุกโมเดล
    for m in genai.list_models():
        # กรองเฉพาะตัวที่ใช้คุยได้ (generateContent)
        if 'generateContent' in m.supported_generation_methods:
            # ตัดคำว่า models/ ออกเพื่อให้ได้ชื่อที่เอาไปใช้ได้จริง
            clean_name = m.name.replace("models/", "") 
            st.code(f"MODEL_NAME = '{clean_name}'")
            found_models.append(clean_name)
            
    if not found_models:
        st.warning("⚠️ เชื่อมต่อได้ แต่ไม่พบโมเดลที่รองรับ generateContent เลย")
        
except Exception as e:
    st.error(f"❌ เกิดข้อผิดพลาดตอนดึงรายชื่อโมเดล: {e}")
    st.info("ลองตรวจสอบ requirements.txt ว่าเป็น 'google-generativeai' หรือยัง")
