"""Auto-classification of uploaded documents via Claude."""

import logging
from typing import Any, Optional

import anthropic

from constants import CHAT_MODEL
from schemas import DocumentClassification

logger = logging.getLogger("lawagent")


def classify_document(
    api_key: str, filename: str, text: str, categories: list[str]
) -> Optional[DocumentClassification]:
    client = anthropic.Anthropic(api_key=api_key)
    prompt = (
        f"סווג את המסמך המשפטי הבא (שם הקובץ: {filename}).\n"
        f"קטגוריות זמינות: {', '.join(categories) or 'אין'}.\n"
        "קבע האם זהו פסק דין או החלטה שיפוטית, ובחר קטגוריה אחת מהרשימה בלבד "
        "(אם אף אחת אינה מתאימה בחר 'כללי' אם קיימת, אחרת השאר ריק). "
        "אם זהו פסק דין, חלץ גם: מספר הליך, ערכאה, שמות הצדדים ותאריך ההחלטה.\n\n"
        f"--- תחילת המסמך ---\n{text[:6000]}"
    )
    classification_messages: list[Any] = [{"role": "user", "content": prompt}]
    try:
        response = client.messages.parse(
            model=CHAT_MODEL,
            max_tokens=1024,
            messages=classification_messages,
            output_format=DocumentClassification,
        )
        classification = response.parsed_output
        if classification and classification.category not in categories:
            classification.category = None
        return classification
    except Exception as error:
        logger.warning("document classification failed: %s", error)
        return None
