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


def search_legal_database(query: str) -> str:
    normalized_query = query.lower()

    if "overtime" in normalized_query or "שעות נוספות" in normalized_query:
        return (
            "תקדים מדומה: בית הדין הארצי לעבודה קבע כי אי-תשלום גמול שעות נוספות "
            "בניגוד לחוק שעות עבודה ומנוחה מזכה את העובד בהפרשי שכר, פיצויי הלנה "
            "והוצאות משפט, בכפוף להוכחת היקף השעות ונטל הרישום החל על המעסיק."
        )

    if "severance" in normalized_query or "פיצויי פיטורים" in normalized_query:
        return (
            "תקדים מדומה: נפסק כי עובד שפוטר לאחר שנת עבודה מלאה זכאי לפיצויי פיטורים "
            "מלאים לפי חוק פיצויי פיטורים, אלא אם המעסיק הוכיח חריג סטטוטורי ברור "
            "המצדיק שלילה או הפחתה."
        )

    return (
        "תקדים מדומה: בתי הדין לעבודה מדגישים כי יש לבחון את מכלול נסיבות יחסי העבודה, "
        "חובת תום הלב, והמסגרת הראייתית לפני קביעת זכויות כספיות וסעדים."
    )


model = genai.GenerativeModel(
    model_name="gemini-1.5-pro",
    system_instruction=SYSTEM_INSTRUCTION,
    tools=[search_legal_database],
)

st.title("⚖️ סוכן משפטי - דיני עבודה")

st.markdown(
    "שוחח עם הסוכן לצורך ניתוח משפטי, ניסוח כתבי טענות ובחינת ראיות בדיני עבודה ישראליים."
)

with st.sidebar:
    st.subheader("ראיות ומסמכים")
    if "uploader_key" not in st.session_state:
        st.session_state.uploader_key = 0
    uploaded_file = st.file_uploader(
        "העלה מסמך לניתוח",
        type=["pdf", "txt", "png", "jpg", "jpeg"],
        help="הקובץ יצורף להודעה הבאה שתשלח בצ'אט.",
        key=f"evidence_uploader_{st.session_state.uploader_key}",
    )

if "chat" not in st.session_state:
    st.session_state.chat = model.start_chat(enable_automatic_function_calling=True)

for message in st.session_state.chat.history:
    role = "assistant" if message.role == "model" else "user"
    with st.chat_message(role):
        text_parts = []
        for part in message.parts:
            part_text = getattr(part, "text", None)
            if part_text:
                text_parts.append(part_text)
        if text_parts:
            st.markdown("\n\n".join(text_parts))

prompt = st.chat_input("כתוב הוראות או שאלת המשך...")

if prompt:
    with st.chat_message("user"):
        st.markdown(prompt)

    try:
        message_payload = [prompt]

        if uploaded_file is not None:
            message_payload.append(
                {
                    "mime_type": uploaded_file.type or "application/octet-stream",
                    "data": uploaded_file.getvalue(),
                }
            )

        with st.spinner("מנתח ומנסח..."):
            response = st.session_state.chat.send_message(message_payload)

        with st.chat_message("assistant"):
            if response.text:
                st.markdown(response.text)
            else:
                st.error("לא התקבלה תשובה מהמודל. אנא נסה שנית.")

        if uploaded_file is not None:
            st.session_state.uploader_key += 1
            st.rerun()
    except Exception as e:
        st.error(f"אירעה שגיאה במהלך השיחה: {e}")
