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
# saudia.sa, alekhbariya.tv and riyadiyatv: each profile's display name is the channel's
# own name and its posts are that channel's programming (scrape of 2026-10-17).
# Verify any other handle (steps in DEPLOYMENT.md section 3). An unknown/non-business
# handle is skipped and reported in the collector run's error field - it never breaks the run.
# Scraped posts are in backend/data/dataset_instagram-scraper_*.json
# (loaded with python -m backend.instagram_import).
SBA_INSTAGRAM_ACCOUNTS: list[dict[str, str]] = [
    {"entity_key": "saudiya", "username": "saudia.sa"},
    {"entity_key": "ekhbariya", "username": "alekhbariya.tv"},
    {"entity_key": "riyadiya", "username": "riyadiyatv"},
    {"entity_key": "sbc", "username": "sbc_channel"},  # confirmed by the team lead, 2026-10-17
    {"entity_key": "sba", "username": "sbagovsa"},  # the authority's own account
]


# Official SBA X accounts, read with our own app-only bearer token
# (backend/agents/x_collector.py) - no SBA login needed.
#
# Verified: SBAgovSA (Wikidata, user id 2150846754); saudiatv, alekhbariyatv and
# riyadiyatv (each X profile calls itself the official channel - team registry, 2026-10).
# Verify any other handle on x.com before adding it: every account costs up to
# X_MAX_POSTS_PER_ACCOUNT post reads on its first run, and its entity_key must
# exist in SBA_CHANNELS. An unknown handle is skipped and reported in the run's error field.
#
# SBC_Channel confirmed by the team lead (2026-10-17).
# Candidates from the team registry, ownership not yet confirmed:
#   quran_tv: quranchannel, sunnah_tv: sunnahchannel,
#   thikrayat: Thikrayat_tv, quran_radio: QuranRadio_ksa
SBA_X_ACCOUNTS: list[dict[str, str]] = [
    {"entity_key": "sba", "username": "SBAgovSA"},
    {"entity_key": "saudiya", "username": "saudiatv"},
    {"entity_key": "ekhbariya", "username": "alekhbariyatv"},
    {"entity_key": "riyadiya", "username": "riyadiyatv"},
    {"entity_key": "sbc", "username": "SBC_Channel"},
]
