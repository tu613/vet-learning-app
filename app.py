import streamlit as st
import time
import os
import pymongo
from pymongo import MongoClient
import google.generativeai as genai
import datetime # <--- เพิ่ม import datetime

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
