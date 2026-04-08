import os

import streamlit as st
from google import genai
from google.genai import types

api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    st.error("משתנה הסביבה GEMINI_API_KEY אינו מוגדר. יש להגדיר אותו לפני הפעלת האפליקציה.")
    st.stop()

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


def _to_genai_history(history: list[dict[str, str]]) -> list[types.Content]:
    return [
        types.Content(
            role="model" if item["role"] == "assistant" else "user",
            parts=[types.Part.from_text(text=item["content"])],
        )
        for item in history
    ]


def _create_chat(history: list[dict[str, str]]):
    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        tools=[search_legal_database],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=False),
    )
    return client.chats.create(
        model="gemini-2.5-pro",
        config=config,
        history=_to_genai_history(history),
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

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

prompt = st.chat_input("כתוב הוראות או שאלת המשך...")

if prompt:
    previous_messages = list(st.session_state.messages)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("user"):
        st.markdown(prompt)

    try:
        message_payload: list[str | types.Part] = [prompt]

        if uploaded_file is not None:
            message_payload.append(
                types.Part.from_bytes(
                    data=uploaded_file.getvalue(),
                    mime_type=uploaded_file.type or "application/octet-stream",
                )
            )

        with st.spinner("מנתח ומנסח..."):
            chat_session = _create_chat(previous_messages)
            response = chat_session.send_message(message_payload)

        assistant_text = response.text or "לא התקבלה תשובה מהמודל. אנא נסה שנית."
        st.session_state.messages.append({"role": "assistant", "content": assistant_text})

        with st.chat_message("assistant"):
            st.markdown(assistant_text)

        if uploaded_file is not None:
            st.session_state.uploader_key += 1
            st.rerun()
    except Exception as e:
        st.session_state.messages = previous_messages
        st.error(f"אירעה שגיאה במהלך השיחה: {e}")
