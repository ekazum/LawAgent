import os

import google.generativeai as genai
import streamlit as st

api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    st.error("משתנה הסביבה GEMINI_API_KEY אינו מוגדר. יש להגדיר אותו לפני הפעלת האפליקציה.")
    st.stop()

genai.configure(api_key=api_key)

SYSTEM_INSTRUCTION = (
    "You are an expert Israeli Employment Law Attorney and Senior Litigator. "
    "Your role is to assist legal professionals in drafting pleadings, analyzing evidentiary documents, "
    "preparing cross-examinations, and formulating legal summations. "
    "Your expertise is strictly confined to Israeli Labor Law. "
    "Never hallucinate legal facts. "
    "Always respond in high-level, formal Hebrew legal terminology unless requested otherwise."
)

model = genai.GenerativeModel(
    model_name="gemini-1.5-pro",
    system_instruction=SYSTEM_INSTRUCTION,
)

st.title("⚖️ סוכן משפטי - דיני עבודה")

st.markdown(
    "הזן פרטי תיק או הוראות כדי ליצור טיוטה משפטית. "
    "הסוכן מתמחה בדיני עבודה ישראליים ומספק מסמכים משפטיים ברמה גבוהה."
)

user_input = st.text_area(
    "הוראות / פרטי התיק",
    height=250,
    placeholder="לדוגמה: נסח כתב תביעה בגין פיטורים שלא כדין...",
)

if st.button("צור מסמך"):
    if not user_input.strip():
        st.warning("נא להזין הוראות או פרטי תיק לפני יצירת המסמך.")
    else:
        try:
            with st.spinner("מייצר מסמך משפטי..."):
                response = model.generate_content(user_input)
                if not response.text:
                    st.error("לא התקבלה תשובה מהמודל. אנא נסה שנית.")
                    st.stop()
                generated_text = response.text

            st.markdown(generated_text)

            st.download_button(
                label="הורד מסמך (.txt)",
                data=generated_text,
                file_name="legal_document.txt",
                mime="text/plain",
            )
        except Exception as e:
            st.error(f"אירעה שגיאה בעת יצירת המסמך: {e}")
