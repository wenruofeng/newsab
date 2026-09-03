"""Site-owned en/zh-CN UI copy, independent of editorial render strings."""

from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from newsab_schema import EXTRA_HALO_LOCALES, halo_locale
from newsab_schema.common import normalize_lang

from .identity import site_identity


_IDENTITY = site_identity()


_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "site_name": _IDENTITY.site_name,
        # The tagline is the one line under the wordmark.  Every locale gets a saying of
        # its own that states the site's point in that language's idiom — it is never a
        # translation of the English one.
        "tagline": _IDENTITY.tagline["en"],
        "meta_description": "See how two groups of media tell the same story differently, with every count traceable to source sentences.",
        "latest": "Latest",
        "categories": "Categories",
        "daily_random": "Shuffled",
        "search": "Search",
        "search_placeholder": "Search titles, briefs, questions, answers...",
        "search_empty": "No topics matched your search.",
        "search_count": "topics",
        "scope": "Sample window",
        # Deliberately not localized: ``Q:`` marks a question the same way in every
        # locale, exactly as it does on a topic page.
        "question": "Q:",
        "read_topic": "Read",
        "category_empty": "No published topics in this category yet.",
        "language": "Language",
        # A language's own name for itself: ``HALO_LOCALES``' endonym is the one place
        # this is written, so the home page's language menu can never drift from the
        # topic page's.
        "locale_native": halo_locale("en").endonym,
        "skip_to_content": "Skip to the topics",
        "how_1": "One event, two sets of media",
        "how_1_text": "We collect how media in different countries and languages covered the same story.",
        "how_2": "Ask questions, compare answers",
        "how_2_text": "Questions written from many angles surface agreement, divergence and one-sided silence.",
        "how_3": "Significant, and traceable to the sentence",
        "how_3_text": "Every finding passes a statistical test; every piece of evidence traces back to the source text.",
        "browse": "Browse",
        "filter_all": "All",
        "order": "Order",
        "show_more": "Show more",
        "search_clear": "Clear the search",
        "catalog_empty": "No topics have been published yet.",
        "card_reports": "{n} independent reports",
        "card_reports_articles": "{n} articles",
        "card_angles": "{n} angles",
        "filter_reading": "Topic language",
        "filter_media": "Media language",
        "filter_media_any": "Any",
        "filter_category": "Category",
        "count_tip": "{n} of {d} sampled reports gave this answer.",
        "kind_consensus": "Agreement",
        "kind_divergence": "Divergence",
        "kind_attention_gap": "Silence",
        "theme": "Switch between light and dark mode",
        "back_to_top": "Back to top",
        "share_angle": "Share angle",
        "share_copied": "Angle link copied.",
        "share_failed": "Could not share or copy this link.",
        "fallback_notice": "This topic is not yet available in {site_locale}. The full article below is shown in {content_locale}.",
        "fallback_open": "Open the {content_locale} version",
    },
    "zh-CN": {
        "site_name": _IDENTITY.site_name,
        "tagline": _IDENTITY.tagline["zh-CN"],
        "meta_description": "看看两组媒体如何用不同方式讲述同一件事，每个计数都能追溯到来源句子。",
        "latest": "最新发布",
        "categories": "按分类浏览",
        "daily_random": "每日随机",
        "search": "搜索议题",
        "search_placeholder": "标题、简介、问题、答案……",
        "search_empty": "没有找到匹配的议题。",
        "search_count": "个议题",
        "scope": "报道时间窗",
        "question": "Q:",
        "read_topic": "阅读比较",
        "category_empty": "此分类暂无议题。",
        "language": "语言",
        "locale_native": halo_locale("zh-CN").endonym,
        "skip_to_content": "跳到议题列表",
        "how_1": "一个事件，两组媒体",
        "how_1_text": "采集不同国家、不同语言的媒体对同一话题的报道。",
        "how_2": "提出问题，比较答案",
        "how_2_text": "设计视角多样的问题，发现共识、分歧和单边沉默。",
        "how_3": "统计显著，逐句追溯",
        "how_3_text": "每个发现均通过统计检验，每处证据均可追溯到原文。",
        "browse": "浏览全部议题",
        "filter_all": "全部",
        "order": "排序",
        "show_more": "显示更多",
        "search_clear": "清除搜索",
        "catalog_empty": "还没有已发布的议题。",
        "card_reports": "{n} 篇独立报道",
        "card_reports_articles": "{n} 篇文章",
        "card_angles": "{n} 个视角",
        "filter_reading": "议题阅读语言",
        "filter_media": "媒体报道语言",
        "filter_media_any": "不限定",
        "filter_category": "分类",
        "count_tip": "样本中 {d} 篇报道有 {n} 篇给出该答案。",
        "kind_consensus": "共识",
        "kind_divergence": "分歧",
        "kind_attention_gap": "沉默",
        "theme": "切换浅色 / 深色主题",
        "back_to_top": "回到顶部",
        "share_angle": "分享视角",
        "share_copied": "已复制该视角的链接。",
        "share_failed": "无法分享或复制该链接。",
        "fallback_notice": "该议题暂不提供{site_locale}翻译；内容保持为{content_locale}。",
        "fallback_open": "直接打开{content_locale}文章",
    },
}

#: The languages the site chrome ships, in halo order — the halo's full nine, ``ar``
#: included (RTL: the web gate owns the direction and mirroring assertions).
#: ``site_metadata.v1.json``'s ``locales`` names the same set for the article half, and
#: the two are checked against each other by ``resolve_publication_locales``.
SITE_LOCALES: tuple[str, ...] = (
    "zh-CN",
    "en",
    "ru",
    "fr",
    "ko",
    "hi",
    "es",
    "ja",
    "ar",
)

#: The halo's other seven locales, merged in from versioned package data.
#: ``site_name``/``tagline`` are not translated text — they come
#: from ``SiteIdentity`` the same way the en/zh-CN entries above already do, and
#: ``locale_native`` comes from ``HALO_LOCALES`` the same way, so the JSON copy below can
#: never drift from it.
_i18n_path = Path(__file__).with_name("data") / "site_strings_i18n.v1.json"
_i18n_data = json.loads(_i18n_path.read_text(encoding="utf-8"))
for _lang in EXTRA_HALO_LOCALES:
    _translated = dict(_i18n_data["site_strings"][_lang])
    _translated["site_name"] = _IDENTITY.site_name
    _translated["tagline"] = _IDENTITY.tagline[_lang]
    _translated["locale_native"] = halo_locale(_lang).endonym
    _STRINGS[_lang] = _translated

_expected_keys = set(_STRINGS[SITE_LOCALES[0]])
for _locale in _STRINGS:
    if set(_STRINGS[_locale]) != _expected_keys:
        missing = sorted(_expected_keys - set(_STRINGS[_locale]))
        extra = sorted(set(_STRINGS[_locale]) - _expected_keys)
        raise RuntimeError(f"asymmetric site dictionary for {_locale}: missing={missing}, extra={extra}")

#: ``SiteIdentity``'s per-locale maps (``identity.py``) cannot assert this coverage
#: themselves — ``SITE_LOCALES`` lives here, one layer above ``identity``, to avoid a
#: circular import — so this is the one place that checks a live site locale is never
#: missing its tagline/about/contact text.
for _locale in SITE_LOCALES:
    for _field_name, _values in (
        ("tagline", _IDENTITY.tagline),
        ("about", _IDENTITY.about),
        ("contact", _IDENTITY.contact),
    ):
        if _locale not in _values:
            raise RuntimeError(f"site identity {_field_name!r} is missing locale {_locale!r}")


#: Reader-facing names for the languages a *sample* can report in, in each site locale.
#: This is the media-language filter's vocabulary, not the site's own locale list: it has
#: to name any language the corpus turns up, so a code with no entry falls back to itself
#: rather than dropping the filter row.
_LANGUAGE_NAMES: dict[str, dict[str, str]] = {
    "en": {
        "ar": "Arabic",
        "de": "German",
        "en": "English",
        "es": "Spanish",
        "fa": "Persian",
        "fr": "French",
        "hi": "Hindi",
        "id": "Indonesian",
        "it": "Italian",
        "ja": "Japanese",
        "ko": "Korean",
        "mn": "Mongolian",
        "ms": "Malay",
        "pt": "Portuguese",
        "ru": "Russian",
        "sw": "Swahili",
        "th": "Thai",
        "tr": "Turkish",
        "uk": "Ukrainian",
        "ur": "Urdu",
        "vi": "Vietnamese",
        "zh-CN": "Chinese (Simplified)",
        "zh-TW": "Chinese (Traditional)",
    },
    "zh-CN": {
        "ar": "阿拉伯语",
        "de": "德语",
        "en": "英语",
        "es": "西班牙语",
        "fa": "波斯语",
        "fr": "法语",
        "hi": "印地语",
        "id": "印尼语",
        "it": "意大利语",
        "ja": "日语",
        "ko": "韩语",
        "mn": "蒙古语",
        "ms": "马来语",
        "pt": "葡萄牙语",
        "ru": "俄语",
        "sw": "斯瓦希里语",
        "th": "泰语",
        "tr": "土耳其语",
        "uk": "乌克兰语",
        "ur": "乌尔都语",
        "vi": "越南语",
        "zh-CN": "中文（简体）",
        "zh-TW": "中文（繁体）",
    },
}

for _lang in EXTRA_HALO_LOCALES:
    _LANGUAGE_NAMES[_lang] = dict(_i18n_data["language_names"][_lang])

_expected_languages = set(_LANGUAGE_NAMES[SITE_LOCALES[0]])
for _locale in _LANGUAGE_NAMES:
    if set(_LANGUAGE_NAMES[_locale]) != _expected_languages:
        raise RuntimeError(f"asymmetric language-name table for {_locale}")


def site_strings(locale: str) -> Mapping[str, str]:
    """Return immutable site copy; unsupported locales fail instead of half-localizing."""
    canonical = normalize_lang(locale)
    try:
        return MappingProxyType(_STRINGS[canonical])
    except KeyError as exc:
        raise ValueError(f"unsupported site locale: {canonical}") from exc


def language_name(code: str, locale: str) -> str:
    """Name one source language in the reader's locale, or echo the code back."""
    canonical = normalize_lang(locale)
    if canonical not in _LANGUAGE_NAMES:
        raise ValueError(f"unsupported site locale: {canonical}")
    return _LANGUAGE_NAMES[canonical].get(code, code)
