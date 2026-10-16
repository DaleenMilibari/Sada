"""Registry of official SBA YouTube channels tracked by the Data Collector agent.

Handles verified against YouTube's verified-badge search results (2026-10).
`default_topic` is the fallback topic when no keyword rule matches a title
(see backend/topics.py).
"""

from __future__ import annotations

SBA_CHANNELS: list[dict[str, str]] = [
    {"entity_key": "sba", "handle": "@SBAgovSA", "name_ar": "هيئة الإذاعة والتلفزيون", "default_topic": "other"},
    {"entity_key": "saudiya", "handle": "@SaudiChannelOne", "name_ar": "قناة السعودية", "default_topic": "other"},
    {"entity_key": "ekhbariya", "handle": "@SaudiNewsTV", "name_ar": "قناة الإخبارية", "default_topic": "news"},
    {"entity_key": "sbc", "handle": "@SBCChannelSBA", "name_ar": "قناة SBC", "default_topic": "entertainment"},
    {"entity_key": "riyadiya", "handle": "@Riyadiyatv", "name_ar": "القنوات الرياضية السعودية", "default_topic": "sports"},
    {"entity_key": "quran_tv", "handle": "@SaudiQuranTv", "name_ar": "قناة القرآن الكريم", "default_topic": "religious"},
    {"entity_key": "sunnah_tv", "handle": "@SaudiSunnahTv", "name_ar": "قناة السنة النبوية", "default_topic": "religious"},
    {"entity_key": "thikrayat", "handle": "@Thikrayat_tv", "name_ar": "قناة ذكريات", "default_topic": "entertainment"},
    {"entity_key": "quran_radio", "handle": "@QuranRadio_ksa", "name_ar": "إذاعة القرآن الكريم", "default_topic": "religious"},
]

BY_ENTITY = {c["entity_key"]: c for c in SBA_CHANNELS}


# Official SBA Instagram accounts, read via the Graph API's Business Discovery
# (backend/agents/instagram_collector.py). Only business/creator accounts can be read.
#
# STATUS: UNVERIFIED. Only "saudiyatv" came from our source list. Whoever sets up
# the Meta app verifies each handle in the Graph API Explorer and adds the rest
# (steps in DATA_COLLECTION.md). An unknown/non-business handle is skipped and
# reported in the collector run's error field - it never breaks the run.
SBA_INSTAGRAM_ACCOUNTS = [
    {"entity_key": "sba", "username": "sbagovsa"},
]

