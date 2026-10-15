"""Topic taxonomy for collected SBA content, plus the rule-based classifier.

Every collected video gets a rule-based topic immediately (keywords, then the
channel's default); the Data Collector agent later refines a capped number per
run with Gemini (topic_source "rule" -> "llm").
"""

from __future__ import annotations

TOPICS: dict[str, str] = {
    "news": "أخبار",
    "sports": "رياضة",
    "religious": "ديني",
    "national_event": "مناسبات وطنية",
    "economy": "اقتصاد",
    "talk_show": "برامج حوارية",
    "documentary": "وثائقي وثقافة",
    "entertainment": "ترفيه ودراما",
    "other": "أخرى",
}

# Checked in order - first match wins, so the more specific topics come first.
_KEYWORD_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("national_event", ("اليوم الوطني", "اليوم_الوطني", "يوم التأسيس", "يوم_التأسيس", "يوم العلم", "يوم_العلم", "رؤية 2030", "رؤية_2030")),
    ("economy", ("اقتصاد", "الاقتصاد", "أسهم", "الأسهم", "السوق المالية", "تاسي", "نفط", "أرامكو", "ميزانية", "التضخم", "استثمار")),
    ("sports", ("مباراة", "الدوري", "دوري", "كأس", "منتخب", "أهداف", "هدف", "روشن", "الهلال", "النصر", "الأهلي", "الشباب", "ملخص مباراة")),
    ("religious", ("القرآن", "سورة", "تلاوة", "صلاة", "الحرم", "المسجد النبوي", "خطبة", "الحج", "العمرة", "أذان", "تراويح")),
    ("documentary", ("وثائقي", "فيلم وثائقي")),
    ("talk_show", ("بودكاست", "لقاء", "حوار", "ضيف", "مقابلة")),
    ("news", ("عاجل", "نشرة", "أخبار", "الأخبار", "مراسل", "مؤتمر صحفي")),
]


def classify_by_rules(title: str, default_topic: str) -> str:
    text = title or ""
    for topic, keywords in _KEYWORD_RULES:
        if any(k in text for k in keywords):
            return topic
    return default_topic if default_topic in TOPICS else "other"
