import argparse
import base64
import os
from typing import List, Literal, Optional

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

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


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class FileInput(BaseModel):
    mime_type: str = "application/octet-stream"
    data_base64: str
    name: Optional[str] = None


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    history: List[ChatMessage] = Field(default_factory=list)
    file: Optional[FileInput] = None


class ChatResponse(BaseModel):
    response: str
    history: List[ChatMessage]


app = FastAPI()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _to_genai_history(history: List[ChatMessage]) -> list[types.Content]:
    return [
        types.Content(
            role="model" if item.role == "assistant" else "user",
            parts=[types.Part.from_text(text=item.content)],
        )
        for item in history
    ]


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest, x_api_key: str = Header(...)) -> ChatResponse:
    try:
        api_key = x_api_key.strip()
        if not api_key:
            raise HTTPException(status_code=400, detail="X-API-Key header is required")

        client = genai.Client(api_key=api_key)
        chat_config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            tools=[search_legal_database],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=False
            ),
        )
        chat_session = client.chats.create(
            model="gemini-2.5-pro",
            config=chat_config,
            history=_to_genai_history(req.history),
        )

        payload: list[str | types.Part] = [req.message]
        if req.file:
            payload.append(
                types.Part.from_bytes(
                    data=base64.b64decode(req.file.data_base64),
                    mime_type=req.file.mime_type or "application/octet-stream",
                )
            )

        response = chat_session.send_message(payload)
        response_text = (response.text or "").strip()
        assistant_message = (
            response_text or "לא התקבלה תשובה מהמודל. אנא נסה שנית."
        )

        updated_history = [
            *req.history,
            ChatMessage(role="user", content=req.message),
            ChatMessage(role="assistant", content=assistant_message),
        ]

        return ChatResponse(response=assistant_message, history=updated_history)
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"שגיאה במהלך השיחה: {error}") from error


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, reload=False)
