"""Saudi context shared by every LLM prompt: how SBA should sound, and how its audience talks.

- writing_voice(tone): a Saudi media voice for post suggestions. "تفاعلي" uses the light,
  widely understood Saudi white dialect (لهجة بيضاء); "رسمي"/"إخباري" stay in Saudi
  broadcast Modern Standard Arabic. Never Egyptian/Levantine expressions.
- local_moment(now): Riyadh date (Gregorian and Hijri), the Saudi weekend (Fri-Sat), Friday
  prayer, the season we are in (Ramadan, Eid, Hajj) and any national or religious occasion close
  enough to be relevant, each with how to mention it - so suggestions fit the calendar.
- AUDIENCE_GUIDE: Saudi dialect cues for reading audience comments (praise, criticism,
  requests, sarcasm, club banter, patriotic prayers, regional dialects, intensifiers, spam)
  so classification doesn't misread them.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from math import ceil

RIYADH = timezone(timedelta(hours=3))
DAYS_AR = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
MONTHS_AR = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
HIJRI_MONTHS_AR = ["محرم", "صفر", "ربيع الأول", "ربيع الآخر", "جمادى الأولى", "جمادى الآخرة",
                   "رجب", "شعبان", "رمضان", "شوال", "ذو القعدة", "ذو الحجة"]
# Fixed-date (Gregorian) national occasions, with how SBA content usually marks them.
OCCASIONS = [
    ((2, 22), "يوم التأسيس", "ذكرى تأسيس الدولة السعودية الأولى عام 1727م؛ يُحتفى بالتاريخ والموروث والأزياء التراثية."),
    ((3, 11), "يوم العلم", "اعتزاز بالعلم ورمزيته؛ العلم يحمل الشهادة فلا يُستخدم في سياق يمتهنه ولا يُنكّس."),
    ((9, 23), "اليوم الوطني السعودي", "فخر وطني وإنجازات المملكة؛ تهنئة لائقة بالوطن والقيادة والشعب دون مبالغة."),
]
# Hijri occasions as (month, day). Their Gregorian dates come from the arithmetic Hijri calendar,
# which can differ from Umm al-Qura and the official moon sighting by a day - so they are always
# presented as approximate.
HIJRI_OCCASIONS = [
    ((1, 1), "رأس السنة الهجرية", "تهنئة هادئة بالعام الهجري الجديد."),
    ((9, 1), "شهر رمضان", "«مبارك عليكم الشهر»، «رمضان كريم»؛ محتوى روحاني وعائلي ومسلسلات وبرامج رمضان."),
    ((10, 1), "عيد الفطر", "«عيدكم مبارك»، «كل عام وأنتم بخير»، «عساكم من عواده»."),
    ((12, 9), "يوم عرفة", "يوم عبادة ودعاء؛ محتوى الحج ونقل المشاعر المقدسة بنبرة خاشعة دون مزاح."),
    ((12, 10), "عيد الأضحى", "«عيدكم مبارك»، «كل عام وأنتم بخير»، وتهنئة الحجاج بسلامة الحج."),
]
OCCASION_WINDOW_DAYS = 21

_VOICE_BASE = (
    "اكتب بصوت إعلامي سعودي يناسب هيئة الإذاعة والتلفزيون السعودية: قريب من الجمهور السعودي، محترم، وواثق. "
    "استخدم المفردات المتداولة في السعودية، وتجنّب تماماً التعابير المصرية والشامية (مثل: إزيكم، دلوقتي، هلأ، شو، كتير، منيح). "
    "احترم الثوابت الدينية والوطنية، واجعل الإشارة للوطن والقيادة بصيغة لائقة ومن دون مبالغة. "
    "الأرقام بالأرقام العربية المعتادة (1، 2، 3)، والوقت بتوقيت الرياض. "
    "الوسوم (الهاشتاقات) بالعربية وبشرطة سفلية بين الكلمات مثل #اليوم_الوطني_السعودي، وواحد أو اثنان فقط. "
    "سمِّ الأشياء بأسمائها السعودية: المملكة، الرياض، دوري روشن، رؤية 2030، موسم الرياض. "
    "لا تخترع أرقاماً أو تصريحات أو أسماء، ولا تتناول قضايا سياسية أو دينية خلافية، ولا تسخر من منطقة أو قبيلة أو جنسية. "
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


def _hijri_to_ordinal(year: int, month: int, day: int) -> int:
    return day + ceil(29.5 * (month - 1)) + (year - 1) * 354 + (3 + 11 * year) // 30 + 227014


def to_hijri(d: date) -> tuple[int, int, int]:
    """(year, month, day) in the arithmetic Hijri calendar - within a day of Umm al-Qura."""
    o = d.toordinal()
    year = (30 * (o - 227014) + 10646) // 10631
    month = min(12, ceil((o - 29 - _hijri_to_ordinal(year, 1, 1)) / 29.5) + 1)
    return year, month, o - _hijri_to_ordinal(year, month, 1) + 1


def from_hijri(year: int, month: int, day: int) -> date:
    return date.fromordinal(_hijri_to_ordinal(year, month, day))


def upcoming_occasions(today: date, window_days: int = OCCASION_WINDOW_DAYS) -> list[tuple[str, int]]:
    """(name, days until it) for national and Hijri occasions within the window (0 = today)."""
    return [(name, delta) for name, delta, _, _ in _upcoming(today, window_days)]


def _upcoming(today: date, window_days: int) -> list[tuple[str, int, str, bool]]:
    """(name, days until it, how to mark it, approximate date?) within the window, soonest first."""
    out = []
    for (month, day), name, note in OCCASIONS:
        for year in (today.year, today.year + 1):
            delta = (date(year, month, day) - today).days
            if 0 <= delta <= window_days:
                out.append((name, delta, note, False))
                break
    hijri_year = to_hijri(today)[0]
    for (month, day), name, note in HIJRI_OCCASIONS:
        for year in (hijri_year, hijri_year + 1):
            delta = (from_hijri(year, month, day) - today).days
            if 0 <= delta <= window_days:
                out.append((name, delta, note, True))
                break
    return sorted(out, key=lambda x: x[1])


def current_season(today: date) -> str | None:
    """What the audience is living through right now, if it changes when and how they engage."""
    _, month, day = to_hijri(today)
    if month == 9:
        late = " نحن في العشر الأواخر: ذروة العبادة وليلة القدر." if day >= 21 else ""
        return (f"نحن في شهر رمضان (اليوم {day} تقريباً).{late} يرتفع تفاعل الجمهور بعد الإفطار وبعد التراويح وحتى السحور، "
                "ويقل وقت الصيام نهاراً. نبرة رمضانية دافئة ومحترمة، وتجنّب ما لا يناسب الشهر.")
    if month == 10 and day <= 3:
        return "أيام عيد الفطر: نبرة احتفالية عائلية وتهاني العيد («عيدكم مبارك»، «عساكم من عواده»)."
    if month == 12 and 8 <= day <= 13:
        eid = " وأيام عيد الأضحى والتشريق" if day >= 10 else ""
        return (f"موسم الحج{eid}: المحتوى عن الحجاج والمشاعر المقدسة وخدمات الحج يتصدّر، والنبرة خاشعة ولائقة. "
                "تهاني العيد مناسبة («عيدكم مبارك»، «حج مبرور»).")
    return None


def _in_days(n: int) -> str:
    if n <= 2:
        return ("اليوم", "غداً", "بعد يومين")[n]
    return f"بعد {n} أيام" if n <= 10 else f"بعد {n} يوماً"


def local_moment(now: datetime | None = None) -> str:
    now = (now or datetime.now(timezone.utc)).astimezone(RIYADH)
    today = now.date()
    day = DAYS_AR[today.weekday()]
    weekend = today.weekday() in (4, 5)  # Friday, Saturday
    h_year, h_month, h_day = to_hijri(today)
    parts = [f"اليوم {day} {today.day} {MONTHS_AR[today.month - 1]} {today.year}م "
             f"(نحو {h_day} {HIJRI_MONTHS_AR[h_month - 1]} {h_year}هـ) بتوقيت الرياض"
             + (" (عطلة نهاية الأسبوع في السعودية)." if weekend else ".")]
    if today.weekday() == 4:
        parts.append("يوم الجمعة: تجنّب النشر وقت صلاة الجمعة (قرابة 11:30 ص - 1:00 م)، وتحية «جمعة مباركة» مناسبة صباحاً.")
    season = current_season(today)
    if season:
        parts.append(season)
    for name, delta, note, approx in _upcoming(today, OCCASION_WINDOW_DAYS):
        when = _in_days(delta)
        if approx:
            when += " تقريباً (حسب إعلان الرؤية الرسمي)"
        parts.append(f"{name} {when}: {note} اربط به المحتوى فقط إن كان الموضوع مناسباً.")
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
    "- مفردات اللهجات السعودية: «مرة» و«حيل» = جداً (مثل «مرة حلو» = مدح)، «مو» و«ما هو» = ليس، "
    "«زين» = جيد، «إيش» و«وش» = ماذا، «أبغى» و«أبي» = أريد، «خرافي» و«أسطوري» و«قوية» = مدح، "
    "«ملل» و«بايخ» و«ما فيه جديد» و«تكرار» = انتقاد. نجدية وحجازية وجنوبية وشرقية كلها لهجات سعودية.\n"
    "- الإيموجي: «😂🤣» مع لوم للقناة أو مع «وش ذا» = سخرية وانتقاد، ومع موقف طريف في المحتوى = تفاعل إيجابي؛ "
    "«😒🙄👎» = استياء، «🤍💚🇸🇦» = محبة أو فخر وطني.\n"
    "- الإنجليزية والعربيزي شائعة عند الشباب: «W» و«GOAT» و«🐐» = مدح، «L» و«cringe» = انتقاد.\n"
    "- «حسبي الله» و«الله يهديكم» موجّهة للقناة = انتقاد شديد، وموجّهة لطرف في الخبر = reaction.\n"
    "- إعلانات وروابط ودعوات للتواصل («للتواصل واتساب»، «متابعة متبادلة»، أرقام جوال، تسويق) = other.\n"
    "- «الإخبارية»، «الرياضية»، «السعودية»، «SBC»، «ذكريات»، «القرآن» أسماء قنوات الهيئة؛ ذِكرها مع مدح أو نقد يعني أن الكلام موجّه للهيئة.\n"
)
