from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class FileInput(BaseModel):
    mime_type: str = "application/octet-stream"
    data_base64: str
    name: Optional[str] = None


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    conversation_id: Optional[int] = None
    template: Optional[str] = None
    file: Optional[FileInput] = None  # kept for older clients
    files: Optional[List[FileInput]] = None

    @property
    def all_files(self) -> List[FileInput]:
        combined = list(self.files or [])
        if self.file:
            combined.append(self.file)
        return combined


class DocumentInfo(BaseModel):
    id: int
    name: str
    doc_type: str
    chunk_count: int
    created_at: str
    category: Optional[str] = None
    case_number: Optional[str] = None
    court: Optional[str] = None
    parties: Optional[str] = None
    decision_date: Optional[str] = None


class DocumentUpdate(BaseModel):
    doc_type: Optional[str] = None
    category: Optional[str] = None
    case_number: Optional[str] = None
    court: Optional[str] = None
    parties: Optional[str] = None
    decision_date: Optional[str] = None


class CategoryInfo(BaseModel):
    id: int
    name: str


class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class ConversationInfo(BaseModel):
    id: int
    title: str
    updated_at: str


class TemplateInfo(BaseModel):
    key: str
    label: str
    description: str


class DocumentClassification(BaseModel):
    is_court_decision: bool
    category: Optional[str] = None
    case_number: Optional[str] = None
    court: Optional[str] = None
    parties: Optional[str] = None
    decision_date: Optional[str] = None
