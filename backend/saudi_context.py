"""Saudi context shared by every LLM prompt: how SBA should sound, and how its audience talks.

- writing_voice(tone): a Saudi media voice for post suggestions. "تفاعلي" uses the light,
  widely understood Saudi white dialect (لهجة بيضاء); "رسمي"/"إخباري" stay in Saudi
  broadcast Modern Standard Arabic. Never Egyptian/Levantine expressions.
- local_moment(now): Riyadh date/day, whether it is the Saudi weekend (Fri-Sat) and any
  national occasion close enough to be relevant - so suggestions fit the calendar.
- AUDIENCE_GUIDE: Saudi dialect cues for reading audience comments (praise, criticism,
  requests, sarcasm, club banter, patriotic prayers) so classification doesn't misread them.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

RIYADH = timezone(timedelta(hours=3))
DAYS_AR = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
MONTHS_AR = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
# Fixed-date (Gregorian) national occasions. Hijri occasions (Ramadan, Eid, Hajj) move every
# year and are left to the posts' own context rather than guessed here.
OCCASIONS = [
    ((2, 22), "يوم التأسيس"),
    ((3, 11), "يوم العلم"),
    ((9, 23), "اليوم الوطني السعودي"),
]
OCCASION_WINDOW_DAYS = 21

_VOICE_BASE = (
    "اكتب بصوت إعلامي سعودي يناسب هيئة الإذاعة والتلفزيون السعودية: قريب من الجمهور السعودي، محترم، وواثق. "
    "استخدم المفردات المتداولة في السعودية، وتجنّب تماماً التعابير المصرية والشامية (مثل: إزيكم، دلوقتي، هلأ، شو، كتير، منيح). "
    "احترم الثوابت الدينية والوطنية، واجعل الإشارة للوطن والقيادة بصيغة لائقة ومن دون مبالغة. "
    "الأرقام بالأرقام العربية المعتادة (1، 2، 3)، والوقت بتوقيت الرياض. "
)
_VOICE_BY_TONE = {
    "تفاعلي": (
        "النبرة تفاعلية: لهجة سعودية بيضاء خفيفة يفهمها الجميع، مثل: «وش رأيكم؟»، «لا يفوتكم»، «تابعونا»، «شاركونا»، «كفو»، «يا هلا». "
        "سؤال أو دعوة للتفاعل في النهاية، وإيموجي واحد أو اثنان على الأكثر عند الحاجة."
    ),
    "رسمي": "النبرة رسمية: فصحى إعلامية سعودية رصينة كما في نشرات وبيانات الهيئة، دون لهجة عامية ولا إيموجي.",
    "إخباري": "النبرة إخبارية: فصحى مختصرة ومباشرة بأسلوب الإخبارية، تبدأ بالمعلومة الأهم، دون عامية ولا مبالغة.",
}
_VOICE_DEFAULT = "استخدم فصحى إعلامية سعودية سهلة، مع لمسة سعودية خفيفة عند المناسب."


def writing_voice(tone: str | None = None) -> str:
    tone = (tone or "").strip()
    if tone and tone not in _VOICE_BY_TONE:
        # A custom one-word tone typed by the user (OptimizerView "أخرى").
        word = tone.split()[0][:20]
        return _VOICE_BASE + f"النبرة المطلوبة: «{word}» - اكتب بهذه النبرة. " + _VOICE_DEFAULT
    return _VOICE_BASE + _VOICE_BY_TONE.get(tone, _VOICE_DEFAULT)


def upcoming_occasions(today: date, window_days: int = OCCASION_WINDOW_DAYS) -> list[tuple[str, int]]:
    """(name, days until it) for fixed national occasions within the window (0 = today)."""
    out = []
    for (month, day), name in OCCASIONS:
        for year in (today.year, today.year + 1):
            d = date(year, month, day)
            delta = (d - today).days
            if 0 <= delta <= window_days:
                out.append((name, delta))
                break
    return sorted(out, key=lambda x: x[1])


def local_moment(now: datetime | None = None) -> str:
    now = (now or datetime.now(timezone.utc)).astimezone(RIYADH)
    today = now.date()
    day = DAYS_AR[today.weekday()]
    weekend = today.weekday() in (4, 5)  # Friday, Saturday
    parts = [f"اليوم {day} {today.day} {MONTHS_AR[today.month - 1]} {today.year} بتوقيت الرياض"
             + (" (عطلة نهاية الأسبوع في السعودية)." if weekend else ".")]
    for name, delta in upcoming_occasions(today):
        parts.append(f"{name} {'اليوم' if delta == 0 else f'بعد {delta} يوماً'} - اربط به المحتوى فقط إن كان الموضوع مناسباً.")
    return " ".join(parts)


AUDIENCE_GUIDE = (
    "إرشادات لفهم تعليقات الجمهور السعودي (لهجة سعودية وخليجية):\n"
    "- إشادة: «كفو»، «يعطيكم العافية»، «الله يعطيكم العافية»، «مبدعين»، «ابدعتوا»، «فخر»، «تستاهلون»، «👏🔥❤️» عند مدح القناة أو البرنامج أو المذيع.\n"
    "- انتقاد: «ما له لزوم»، «وش ذا»، «خربتوا»، «مستوى ضعيف»، «تحيز»، «فشلتونا»، «ليش ما تنقلون»، وتعليقات «ههه» أو «طقطقة» "
    "المصحوبة بلوم للقناة = سخرية أي انتقاد.\n"
    "- طلب: «يا ليت»، «ياليت»، «نبي»، «نبغى»، «ودنا»، «عسى»، «حطوا لنا»، «رجعوا البرنامج».\n"
    "- سؤال: «متى بيعرض؟»، «متى تنزل الحلقة؟»، «وين أقدر أشوف؟»، «وش اسم...؟»، «وين...؟».\n"
    "- تفاعل مع الحدث وليس مع القناة: الأدعية الوطنية مثل «الله يحفظ بلادنا»، «حفظ الله المملكة وقيادتها»، "
    "والمناكفات بين جماهير الأندية (هلالي، نصراوي، اتحادي، أهلاوي) والآراء في الحكام واللاعبين، "
    "والتعليق على أطراف الخبر. هذه مشاعر وطنية أو رياضية وليست مدحاً أو انتقاداً للهيئة.\n"
    "- «الإخبارية»، «الرياضية»، «السعودية»، «SBC»، «ذكريات»، «القرآن» أسماء قنوات الهيئة؛ ذِكرها مع مدح أو نقد يعني أن الكلام موجّه للهيئة.\n"
)
