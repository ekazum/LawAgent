"""Chat streaming service: builds the SSE event stream for /api/chat.

ChatService holds its Database collaborator; the Anthropic client is
created per request inside stream() because the API key is per-request
(server env key or X-API-Key header override). The route wraps
chat_service.stream(...) in a StreamingResponse.
"""

import base64
import json
import logging
from typing import Any, Iterator, Optional

import anthropic

from constants import (
    CHAT_MODEL,
    IMAGE_MEDIA_TYPES,
    MAX_RESPONSE_TOKENS,
    MAX_TOOL_ITERATIONS,
)
from db import Database, database
from ingestion import UnsupportedFileError
from prompts import SYSTEM_INSTRUCTION
from schemas import ChatRequest, FileInput
from templates import TEMPLATES, template_context
from tools import (
    CLIENT_TOOL_STATUS,
    SERVER_TOOL_STATUS,
    build_chat_tools,
    collect_web_sources,
    run_client_tool,
)

logger = logging.getLogger("lawagent")


def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def b64_decoded_size(data_b64: str) -> int:
    s = data_b64.strip()
    if not s:
        return 0
    padding = 2 if s.endswith("==") else 1 if s.endswith("=") else 0
    return (len(s) // 4) * 3 - padding


class ChatService:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _file_content_block(file: FileInput) -> dict:
        media_type = (file.mime_type or "application/octet-stream").lower()

        if media_type in IMAGE_MEDIA_TYPES:
            return {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": file.data_base64,
                },
            }

        if media_type == "application/pdf":
            return {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": file.data_base64,
                },
            }

        if media_type.startswith("text/"):
            text = base64.b64decode(file.data_base64).decode("utf-8", errors="replace")
            name = file.name or "קובץ מצורף"
            return {"type": "text", "text": f"--- תוכן הקובץ המצורף ({name}) ---\n{text}"}

        raise UnsupportedFileError(
            f"סוג קובץ לא נתמך בצ'אט: {media_type}. נתמכים: PDF, תמונות, טקסט."
        )

    def stream(self, req: ChatRequest, api_key: str, owner: str) -> Iterator[str]:
        template = TEMPLATES.get(req.template) if req.template else None
        if template is not None:
            template_label: Optional[str] = template["label"]
            template_instruction: Optional[str] = template["instruction"]
            template_doc_types: list[str] = template["doc_types"]
        else:
            template_label = None
            template_instruction = None
            template_doc_types = []

        # Resolve conversation + history. If the DB is down, chat still works
        # statelessly — the conversation just isn't persisted.
        history: list[dict] = []
        conversation_id = req.conversation_id
        persist = True
        try:
            if conversation_id is not None:
                stored = self.db.get_conversation_messages(conversation_id, owner)
                if stored is None:
                    yield sse({"type": "error", "detail": "השיחה לא נמצאה."})
                    return
                history = stored
            else:
                prefix = f"[{template_label}] " if template_label else ""
                title = (prefix + req.message).strip()[:80]
                conversation_id = self.db.create_conversation(title, owner)["id"]
        except Exception as error:
            logger.warning("conversation persistence unavailable: %s", error)
            persist = False
            conversation_id = None

        yield sse({"type": "start", "conversation_id": conversation_id})

        user_blocks: list[dict] = []
        if template_instruction is not None:
            yield sse({"type": "status", "text": "שולף מקורות רלוונטיים מהמאגר..."})
            context = template_context(req.message, template_doc_types)
            instruction = template_instruction
            if context:
                instruction += "\n\nמקורות רלוונטיים שאותרו במאגר הידע:\n\n" + context
            user_blocks.append({"type": "text", "text": instruction})
        user_blocks.append({"type": "text", "text": req.message})
        for attached in req.all_files:
            try:
                user_blocks.append(self._file_content_block(attached))
            except UnsupportedFileError as error:
                yield sse({"type": "error", "detail": str(error)})
                return

        messages: list[Any] = [
            {"role": item["role"], "content": item["content"]} for item in history
        ]
        messages.append({"role": "user", "content": user_blocks})

        client = anthropic.Anthropic(api_key=api_key)
        # noinspection PyBroadException
        try:
            category_names = [item["name"] for item in self.db.list_categories()]
        except Exception:
            category_names = []
        chat_tools: list[Any] = build_chat_tools(category_names)

        collected: list[str] = []
        response = None
        seen_sources: set = set()
        sources: list[dict] = []
        try:
            for _ in range(MAX_TOOL_ITERATIONS):
                with client.messages.stream(
                    model=CHAT_MODEL,
                    max_tokens=MAX_RESPONSE_TOKENS,
                    system=SYSTEM_INSTRUCTION,
                    tools=chat_tools,
                    messages=messages,
                ) as stream:
                    for event in stream:
                        if (
                            event.type == "content_block_start"
                            and event.content_block.type == "server_tool_use"
                        ):
                            status = SERVER_TOOL_STATUS.get(event.content_block.name)
                            if status:
                                yield sse({"type": "status", "text": status})
                        elif (
                            event.type == "content_block_delta"
                            and event.delta.type == "text_delta"
                        ):
                            collected.append(event.delta.text)
                            yield sse({"type": "delta", "text": event.delta.text})
                    response = stream.get_final_message()

                collect_web_sources(response, seen_sources, sources)

                if response.stop_reason == "pause_turn":
                    # Server-side tool loop paused mid-turn; resend to resume.
                    messages.append({"role": "assistant", "content": response.content})
                    continue

                if response.stop_reason != "tool_use":
                    break

                messages.append({"role": "assistant", "content": response.content})
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        yield sse(
                            {
                                "type": "status",
                                "text": CLIENT_TOOL_STATUS.get(block.name, "מפעיל כלי..."),
                            }
                        )
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": run_client_tool(block.name, block.input or {}),
                            }
                        )
                messages.append({"role": "user", "content": tool_results})
        except anthropic.AuthenticationError:
            yield sse({"type": "error", "detail": "מפתח ה-API של Anthropic אינו תקין."})
            return
        except anthropic.RateLimitError:
            yield sse(
                {
                    "type": "error",
                    "detail": "חריגה ממגבלת הקצב של Anthropic. נסה שוב בעוד רגע.",
                }
            )
            return
        except anthropic.APIError as error:
            yield sse({"type": "error", "detail": f"שגיאה משירות Anthropic: {error.message}"})
            return
        except Exception as error:
            logger.exception("chat stream failed")
            yield sse({"type": "error", "detail": f"שגיאה במהלך השיחה: {error}"})
            return

        if sources:
            sources_text = "\n\n**מקורות (פסיקה ורשת):**\n" + "\n".join(
                f"- [{item['title']}]({item['url']})" for item in sources
            )
            collected.append(sources_text)
            yield sse({"type": "delta", "text": sources_text})

        final_text = "".join(collected).strip()
        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "refusal" and not final_text:
            final_text = "הבקשה נדחתה משיקולי בטיחות. נסח את הפנייה מחדש."
            yield sse({"type": "delta", "text": final_text})
        if not final_text:
            final_text = "לא התקבלה תשובה מהמודל. אנא נסה שנית."
            yield sse({"type": "delta", "text": final_text})

        if persist and conversation_id is not None:
            stored_user = req.message
            if template_label:
                stored_user = f"[{template_label}]\n{stored_user}"
            if req.file and req.file.name:
                stored_user += f"\n[צורף קובץ: {req.file.name}]"
            try:
                self.db.add_message(conversation_id, "user", stored_user)
                self.db.add_message(conversation_id, "assistant", final_text)
            except Exception as error:
                logger.warning("failed to persist conversation: %s", error)

        yield sse({"type": "done", "conversation_id": conversation_id})


# Process-wide singleton wired to the shared Database.
chat_service = ChatService(database)


def get_chat_service() -> ChatService:
    return chat_service
