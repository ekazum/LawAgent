import logging

import db
from ingestion import embed_query
from tools import format_chunks

logger = logging.getLogger("lawagent")

TEMPLATES = {
    "pleading": {
        "label": "טיוטת כתב טענות",
        "description": "ניסוח טיוטת כתב תביעה או כתב הגנה לבית הדין לעבודה על בסיס עובדות המקרה",
        "instruction": (
            "המשימה: נסח טיוטת כתב טענות (כתב תביעה או כתב הגנה, לפי ההקשר) "
            "לבית הדין האזורי לעבודה, על בסיס עובדות המקרה שמסר המשתמש. "
            "הקפד על מבנה מקובל: כותרת והצדדים, מבוא, פירוט העובדות, הטיעון "
            "המשפטי לפי עילות, הסעדים המבוקשים, וסיום. התבסס על ההנחיות ועל "
            "מסמכי הדוגמה מהמאגר, ושמור על סגנונם."
        ),
        "doc_types": ["guideline", "example"],
    },
    "analysis": {
        "label": "ניתוח מסמך ראייתי",
        "description": "ניתוח מסמך מצורף: חוזקות, חולשות, סתירות ומשמעות ראייתית",
        "instruction": (
            "המשימה: נתח את המסמך או העובדות שמסר המשתמש מנקודת מבט ראייתית. "
            "פרט: עיקרי המסמך, חוזקות ראייתיות, חולשות וסתירות, השלכות משפטיות "
            "לפי דיני העבודה, והמלצות להמשך טיפול (ראיות משלימות, שאלות לעדים)."
        ),
        "doc_types": ["guideline", "precedent"],
    },
    "cross": {
        "label": "הכנת חקירה נגדית",
        "description": "בניית שאלות לחקירה נגדית של עד על בסיס גרסתו והעובדות",
        "instruction": (
            "המשימה: הכן חקירה נגדית לעד שפרטיו וגרסתו נמסרו על ידי המשתמש. "
            "בנה רצף שאלות ממוקדות: שאלות פתיחה לקיבוע גרסה, שאלות לחשיפת "
            "סתירות, ושאלות סגירה. ציין ליד כל קבוצת שאלות את מטרתה ואת הסיכון שבה."
        ),
        "doc_types": ["guideline", "example"],
    },
    "summation": {
        "label": "טיוטת סיכומים",
        "description": "ניסוח סיכומים משפטיים על בסיס הראיות והעדויות בתיק",
        "instruction": (
            "המשימה: נסח טיוטת סיכומים לבית הדין לעבודה על בסיס חומר התיק "
            "שמסר המשתמש. מבנה: מבוא ותמצית, ניתוח הראיות והעדויות, הטיעון "
            "המשפטי בשילוב אסמכתאות, מענה לטענות הצד שכנגד, וסיכום הסעדים."
        ),
        "doc_types": ["guideline", "example", "precedent"],
    },
}


def template_context(query: str, doc_types: list[str]) -> str:
    try:
        query_embedding = embed_query(query)
        results = db.search_chunks(query_embedding, top_k=6, doc_types=doc_types)
    except Exception as error:
        logger.warning("template pre-retrieval failed: %s", error)
        return ""
    if not results:
        return ""
    return format_chunks(results)
