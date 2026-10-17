"""Topic taxonomy for collected SBA content, plus the rule-based classifier.

Every collected video gets a rule-based topic immediately (keywords, then the
channel's default); the Data Collector agent later refines a capped number per
run with Gemini (topic_source "rule" -> "llm").

Taxonomy v2 (2026-10) split the broad v1 buckets - "أخبار" held a third of all
posts, "ديني" mixed live prayers with fatwa programs, and "أخرى" hid tourism,
health, tech and heritage - into decisions a content team actually makes. The v1
keys are kept (with narrower meanings), so stored drafts and patterns stay valid;
migrate_taxonomy() re-sorts stored posts once.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("sada.topics")

TAXONOMY_VERSION = "2"

TOPICS: dict[str, str] = {
    "news": "أخبار محلية",
    "politics": "سياسة وشؤون دولية",
    "sports": "رياضة",
    "quran_prayer": "قرآن وصلوات",
    "religious": "برامج دينية وفتاوى",
    "hajj_umrah": "حج وعمرة",
    "national_event": "مناسبات وطنية",
    "economy": "اقتصاد وأعمال",
    "tech": "تقنية وعلوم",
    "health": "صحة وأسلوب حياة",
    "tourism": "سياحة ومناطق",
    "culture": "ثقافة وتراث وفنون",
    "documentary": "وثائقي وتاريخ",
    "talk_show": "برامج حوارية",
    "drama": "مسلسلات ودراما",
    "entertainment": "ترفيه ومسابقات",
    "other": "أخرى",
}

# One line per topic for the LLM classifier, so neighbouring topics are told apart.
TOPIC_HINTS: dict[str, str] = {
    "news": "أخبار داخل المملكة: قرارات حكومية، خدمات، تعليم، طقس، دفاع مدني، أمن",
    "politics": "سياسة خارجية وشؤون دولية: زيارات رسمية، دبلوماسية، نزاعات، اليمن والحوثي، الأمم المتحدة",
    "sports": "مباريات، دوري، منتخب، أندية، لاعبون، بطولات",
    "quran_prayer": "نقل الصلوات من الحرمين، تلاوات، خطب الجمعة، أذان",
    "religious": "برامج دينية: تفسير، فتاوى، دروس، محاضرات، حديث",
    "hajj_umrah": "موسم الحج والعمرة وخدمة ضيوف الرحمن",
    "national_event": "اليوم الوطني، يوم التأسيس، يوم العلم، رؤية 2030",
    "economy": "اقتصاد، أسواق، شركات، استثمار، صناعة، أسعار",
    "tech": "تقنية، ذكاء اصطناعي، أمن سيبراني، فضاء، ابتكار",
    "health": "صحة، طب، تغذية، طبخ، رياضة بدنية، أسلوب حياة",
    "tourism": "سياحة، مناطق المملكة ومدنها، وجهات، مواسم",
    "culture": "تراث، شعر، أدب، فنون، معارض، متاحف، لغة عربية",
    "documentary": "أفلام وثائقية، تاريخ، أرشيف ومشاهد قديمة",
    "talk_show": "لقاءات، حوارات، بودكاست، برامج نقاش مثل الشارع السعودي",
    "drama": "مسلسلات وأفلام ومقاطع منها",
    "entertainment": "مسابقات، تحديات، كوميديا، حفلات وأغانٍ",
    "other": "لا يناسب أي موضوع أعلاه",
}

# Checked in order - first match wins, so the more specific topics come first.
# Substrings of the title padded with a space on each side, so each keyword is chosen not to sit inside
# unrelated words ("هدف" is inside "يهدف", "الحج" inside "الحجر") - a leading/trailing space marks a word edge.
_KEYWORD_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("national_event", ("اليوم الوطني", "اليوم_الوطني", "يوم التأسيس", "يوم_التأسيس", "يوم العلم", "يوم_العلم", "رؤية 2030", "رؤية_2030", "عزنا_بطبعنا")),
    ("hajj_umrah", (" الحج ", " الحج،", " الحج.", "#الحج", "موسم الحج", "مناسك", " حج 14", " حاج ", "الحجاج", "حجاج", "الحجيج", "ضيوف الرحمن", "عرفة", "مزدلفة", "الجمرات", "مشعر منى", "التروية", "العمرة", "المعتمرين", "معتمر")),
    ("religious", ("تفسير", "التفسير", "فتاوى", "فتوى", "نور على الدرب", "محاضرة", "الحديث الشريف", "هدايات", "البيان القرآني", "درس ", "الفقه", "هل يجوز", " حكم ", "الآداب المشروعة")),
    ("quran_prayer", ("صلاة الفجر", "صلاة الظهر", "صلاة العصر", "صلاة المغرب", "صلاة العشاء", "صلاة الجمعة", "صلاة التراويح", "خطبة", "تلاوة", "سورة", "القرآن", "أذان", "تراويح", "قيام الليل", "ختمة")),
    ("sports", ("مباراة", "الدوري", "دوري", "كأس", "منتخب", "روشن", "الهلال", "النصر", "الأهلي", "الشباب", "خليجي", "بطولة", "لاعب", "مدرب", "ملعب", "الرياضية_السعودية", "فورمولا")),
    ("economy", ("اقتصاد", "الاقتصاد", "أسهم", "الأسهم", "السوق المالية", "تاسي", "نفط", "أرامكو", "ميزانية", "التضخم", "استثمار", "مليار", "الصناعة", "التجارة", "الأسعار", "أسعار", "تأمين", "العقار")),
    ("politics", ("الحوثي", "ميليشيا", "إيران", "الإيراني", "اليمن", "العراق", "سوريا", "لبنان", "فلسطين", "غزة", "إسرائيل", "الاحتلال", "الأمم المتحدة", "مجلس الأمن", "حقوق الإنسان", "وزير الخارجية", "مباحثات", "سفير", "دبلوماسي", "صاروخ", "صواريخ", "عسكري", "القوات المسلحة", "باريس", "الإليزيه", "فرنسا", "واشنطن", "روسيا", "أوكرانيا", "الصين")),
    ("tech", ("الذكاء الاصطناعي", "الذكاء_الاصطناعي", "تقنية", "التقنية", "التقني", "الرقمية", "سيبراني", "السيبراني", "روبوت", "الفضاء", "ابتكار", "ليب 20")),
    ("health", ("الصحة", "صحة ", "صحية", "طبيب", "الطبية", " الطبي ", "مرض", "علاج", "مستشفى", "تغذية", "غذائي", "الشيف", "وصفة", "وصفات", "مطبخ", "رجيم", "سمنة", "السكري", "المفصل", "التجميل", "التوأم", "سعرة", "سعرات", "السكر")),
    ("tourism", ("ديرتنا", "سياحة", "السياحة", "سياحي", "القدية", "العلا", "منتزه", "وجهة", "موسم الرياض", "موسم جدة", "شتاء السعودية")),
    ("documentary", ("وثائقي", "فيلم وثائقي", "تاريخية", "التاريخي", "أرشيف", "الملك عبدالعزيز", "طيب الله ثراه")),
    ("culture", ("تراث", "التراث", "الموروث", "قصيد", "الشعر ", "شاعر_", "الأدب", "أديب", "فنون", " الفن ", "المعرض الثقافي", "معرض الكتاب", "معرض فني", "متحف", "الخط العربي", "الثقافة", "ثقافي", "اللغة العربية", "رواية")),
    ("talk_show", ("بودكاست", "لقاء", "حوار", "ضيف", "مقابلة", "الشارع السعودي", "الشارع_السعودي")),
    ("drama", ("مسلسل", "المسلسل", "دراما", "الحلقة", "فيلم")),
    ("entertainment", ("مسابقة", "مسابقات", "تحدي", "التحدي", "كوميدي", "حفل", "أغنية", "غناء", "طرب", "فكر واكسب")),
    ("news", ("عاجل", "نشرة", "أخبار", "الأخبار", "مراسل", "مؤتمر صحفي", "الدفاع المدني", "الجوازات", "مجلس الوزراء", "الأرصاد", "الأمطار", "الطقس", "المدارس", "العام الدراسي", "إنفوغرافيك", "انفوغرافيك", "خادم الحرمين", "خادم_الحرمين", "ولي العهد", "ولي_العهد", "الخطاب الملكي")),
]


def classify_by_rules(title: str, default_topic: str) -> str:
    text = f" {title or ''} "
    for topic, keywords in _KEYWORD_RULES:
        if any(k in text for k in keywords):
            return topic
    return default_topic if default_topic in TOPICS else "other"


def migrate_taxonomy(engine: Any = None) -> int:
    """Re-sort every stored post into the current taxonomy, once per TAXONOMY_VERSION.

    Posts are re-classified by the rules and marked topic_source="rule", so the Data
    Collector's Gemini pass refines them again (COLLECTOR_LLM_CLASSIFY_PER_RUN per run)
    against the new topic list. Returns how many posts changed topic.
    """
    from sqlalchemy import bindparam, insert, select, update

    from backend import db
    from backend.sba_channels import BY_ENTITY

    engine = engine or db.get_engine()
    with engine.begin() as conn:
        current = conn.execute(select(db.app_meta.c.value).where(db.app_meta.c.key == "topic_taxonomy")).scalar()
        if current == TAXONOMY_VERSION:
            return 0
        v, c = db.videos.c, db.channels.c
        rows = conn.execute(select(v.video_id, v.title, v.topic, v.topic_source, c.entity_key).join(db.channels, v.channel_id == c.channel_id)).all()
        updates, changed = [], 0
        for vid, title, topic, source, entity in rows:
            new = classify_by_rules(title, BY_ENTITY.get(entity, {}).get("default_topic", "other"))
            changed += new != topic
            if new != topic or source != "rule":
                updates.append({"vid": vid, "t": new})
        if updates:
            conn.execute(
                update(db.videos).where(db.videos.c.video_id == bindparam("vid")).values(topic=bindparam("t"), topic_source="rule"),
                updates,
            )
        if current is None:
            conn.execute(insert(db.app_meta).values(key="topic_taxonomy", value=TAXONOMY_VERSION))
        else:
            conn.execute(update(db.app_meta).where(db.app_meta.c.key == "topic_taxonomy").values(value=TAXONOMY_VERSION))
    logger.info("Topic taxonomy v%s: re-sorted %d post(s), %d changed topic.", TAXONOMY_VERSION, len(rows), changed)
    return changed
