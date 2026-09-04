"""Every word the renderer owns, in one place.

Nothing here is a writer's sentence.  These are the labels, tooltips and template
paragraphs the page says identically on every topic: the statistical vocabulary, the
modal furniture, the methodology text.  A writer never types any of it, and a localizer
never edits it — it is translated here, once, for every page there will ever be.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Optional

from newsab_schema import EXTRA_HALO_LOCALES, merge_lang_leaf

#: The three angle kinds a reader meets, plus the two the appendix still has to name.
#: One word each — 共识 / 分歧 / 沉默.
KIND_LABEL = {
    "consensus": {"en": "Agreement", "zh-CN": "共识"},
    "divergence": {"en": "Divergence", "zh-CN": "分歧"},
    "attention_gap": {"en": "Silence", "zh-CN": "沉默"},
    "no_significant_relation": {"en": "No pattern", "zh-CN": "无明显规律"},
    "too_thin": {"en": "Thin data", "zh-CN": "数据不足"},
}

#: What each kind means, in the thresholds' own terms.  ``{...}`` fields are filled from
#: the pinned analyze run, so a page never quotes a threshold it was not produced under.
KIND_TIP = {
    "consensus": {
        "en": "The most common answer is the same on both sides.",
        "zh-CN": "双方对该问题的最常见的答案相同",
    },
    "divergence": {
        "en": "The most common answer differs between the two sides.",
        "zh-CN": "双方对该问题的最常见的答案不同",
    },
    # The rule is a *rate difference*, not an absolute rate on the loud side
    # (``qa_analyze.py``: ``rq < silent_max_rate and rl - rq >= attention_gap_min_abs_diff``).
    # "the other side's rate exceeds 25%" described neither half of it.
    "attention_gap": {
        "en": "One side's response rate is below {silent_max_rate:.0%}; the other side's is at least {attention_gap_min_abs_diff:.0%} higher.",
        "zh-CN": "一方回答率低于 {silent_max_rate:.0%}，另一方至少高出 {attention_gap_min_abs_diff:.0%}",
    },
    # Runs older than qa-0.4.0 pin no ``silent_max_rate``; ``kind_chip`` routes them here
    # rather than formatting a threshold their own run never set.
    "attention_gap_rate_legacy": {
        "en": "One side barely addresses this question; the other side's response rate is at least {coverage_gap_min_abs_diff:.0%} higher.",
        "zh-CN": "一方几乎未谈及该问题，另一方回答率至少高出 {coverage_gap_min_abs_diff:.0%}",
    },
    "attention_gap_silence": {
        "en": "No sampled report on one side addresses this question.",
        "zh-CN": "某一方完全没有谈及这个问题",
    },
    # The observation-vs-signal pairing (audit P9): the chart shows observed tops, the
    # label says why no assertion is made of them.
    "no_significant_relation": {
        "en": "The data are insufficient to assert a clear pattern.",
        "zh-CN": "数据不足以呈现出明显规律",
    },
    "too_thin": {
        "en": "One side has too little data to support a judgment.",
        "zh-CN": "某一方数据不足",
    },
}

#: The empty state of a storyline tab.  A kind with no angle is itself the page's
#: loudest signal on some topics, so the tab is drawn with its zero rather than hidden.
KIND_EMPTY = {
    "consensus": {
        "en": "We found no supported agreement on any question in this topic.",
        "zh-CN": "未发现有数据支持的双方共识。",
    },
    "divergence": {
        "en": "We found no supported divergence on any question in this topic.",
        "zh-CN": "未发现有数据支持的双方分歧。",
    },
    "attention_gap": {
        "en": "We found no supported one-sided silence on any question in this topic.",
        "zh-CN": "未发现有数据支持的单边沉默。",
    },
}

STRENGTH_LABEL = {
    "supported": {"en": "strong", "zh-CN": "证据充分"},
    "weak": {"en": "weak", "zh-CN": "证据偏弱"},
    "unsupported": {"en": "no evidence", "zh-CN": "无证据"},
}

_UNSUPPORTED_TIP = {
    "en": "This finding's resampling stability is below {weak_min_probability:.0%}.",
    "zh-CN": "该结论的统计可复现率低于 {weak_min_probability:.0%}。",
}

STRENGTH_TIP_POSTERIOR = {
    "supported": {
        "en": "This finding's resampling stability is above {supported_min_probability:.0%}{stability_clause}.",
        "zh-CN": "该结论的统计可复现率大于 {supported_min_probability:.0%}{stability_clause}。",
    },
    "weak": {
        "en": "This finding's resampling stability is between {weak_min_probability:.0%} "
        "and {supported_min_probability:.0%}{stability_clause}.",
        "zh-CN": "该结论的统计可复现率介于 {weak_min_probability:.0%} 和 {supported_min_probability:.0%} 之间 {stability_clause}。",
    },
    "unsupported": _UNSUPPORTED_TIP,
}

TIER_LABEL = {
    "template": {"en": "standard", "zh-CN": "标准问题"},
    "reader": {"en": "custom", "zh-CN": "议题问题"},
}

TIER_TIP = {
    "template": {
        "en": "A standard template question for every topic.",
        "zh-CN": "适用于所有议题的标准问题。",
    },
    "reader": {
        "en": "A question written for this topic alone.",
        "zh-CN": "专为该议题撰写的问题。",
    },
}

SOURCE_CATEGORY = {
    "serious": {"en": "original-reporting outlet", "zh-CN": "自采署名的新闻机构"},
    "other": {"en": "magazine, trade or portal", "zh-CN": "杂志、行业媒体或门户"},
}

BEAT_SCOPE = {
    "general": {"en": "general news", "zh-CN": "综合新闻"},
    "vertical": {"en": "one industry or subject", "zh-CN": "单一行业或题材"},
}

#: Reader words for the codes the registry stores.  Only the places and languages this
#: repo's topics actually use; anything else falls back to the code itself, which is
#: honest rather than wrong.
COUNTRY_LABEL = {
    "CN": {"en": "China", "zh-CN": "中国"},
    "US": {"en": "the United States", "zh-CN": "美国"},
    "ID": {"en": "Indonesia", "zh-CN": "印度尼西亚"},
    "KE": {"en": "Kenya", "zh-CN": "肯尼亚"},
    "TZ": {"en": "Tanzania", "zh-CN": "坦桑尼亚"},
    "UG": {"en": "Uganda", "zh-CN": "乌干达"},
    "ZA": {"en": "South Africa", "zh-CN": "南非"},
    "NG": {"en": "Nigeria", "zh-CN": "尼日利亚"},
    "HK": {"en": "Hong Kong", "zh-CN": "中国香港"},
    "SG": {"en": "Singapore", "zh-CN": "新加坡"},
    "GB": {"en": "the United Kingdom", "zh-CN": "英国"},
    "IN": {"en": "India", "zh-CN": "印度"},
    "JP": {"en": "Japan", "zh-CN": "日本"},
}

LANG_LABEL = {
    "zh": {"en": "Chinese", "zh-CN": "中文"},
    "zh-CN": {"en": "Chinese", "zh-CN": "中文"},
    "en": {"en": "English", "zh-CN": "英文"},
    "id": {"en": "Indonesian", "zh-CN": "印尼语"},
    "sw": {"en": "Swahili", "zh-CN": "斯瓦希里语"},
    "ja": {"en": "Japanese", "zh-CN": "日语"},
    "ko": {"en": "Korean", "zh-CN": "韩语"},
    "de": {"en": "German", "zh-CN": "德语"},
    "fr": {"en": "French", "zh-CN": "法语"},
    "tr": {"en": "Turkish", "zh-CN": "土耳其语"},
    "mn": {"en": "Mongolian", "zh-CN": "蒙古语"},
}

ORIGIN_LABEL = {
    "original": {"en": "original reporting", "zh-CN": "原创报道"},
    "domestic_wire": {"en": "domestic wire copy", "zh-CN": "本国通讯社稿"},
    "foreign_wire_rewrite": {"en": "foreign wire rewrite", "zh-CN": "外电改写"},
    "syndication": {"en": "syndicated copy", "zh-CN": "转载稿"},
    "press_release": {"en": "statement rewrite", "zh-CN": "据书面声明改写"},
}

STRINGS = {
    "quote_source": {"en": "original", "zh-CN": "原文"},
    "of_clusters": {"en": "independent reports", "zh-CN": "独立报道"},
    "runs": {"en": "Pinned runs", "zh-CN": "钉定运行"},
    "shared_answer": {"en": "Both sides' answer", "zh-CN": "双方的回答"},
    # The quiet side of an attention gap says one thing, whether it answered once or not
    # at all: the rate is too low to assert an answer from.  Two wordings invited the
    # reader to read the near-silent one as a small answer rather than as no answer; the
    # exact counts are one badge away, on the same card.
    "silent_answer": {
        "en": "(answer rate too low)",
        "zh-CN": "（回答率过低）",
    },
    #: The silent side's evidence button: its answer is not a claim, so the button cannot
    #: promise "the reports behind this answer" the way the speaking side's does.
    "evidence_title_silent": {
        "en": "Every annotated report on this side",
        "zh-CN": "该侧全部报道的标注明细",
    },
    "more_evidence": {
        "en": "Show {n} more",
        "zh-CN": "展示其他 {n} 篇报道",
    },
    "timeline_title": {"en": "Timeline", "zh-CN": "新闻时间线"},
    "perspectives_title": {"en": "Angles", "zh-CN": "视角分析"},
    "window": {
        "en": "{first} – {last} · {sides} · {articles} independent reports in total",
        "zh-CN": "{first} – {last} · {sides} · 合计 {articles} 篇独立报道",
    },
    "window_counts": {
        "en": "{sides} · {articles} independent reports in total",
        "zh-CN": "{sides} · 合计 {articles} 篇独立报道",
    },
    "window_side": {"en": "{who}: {n} reports", "zh-CN": "{who} {n} 篇"},
    # the concept cloud: the mechanism sentence is the renderer's, identical on every page
    "cc_lede": {
        "en": "We combine all classified answers on each side, regardless of question. "
        "The larger a concept's share of that side's answers, the larger it appears and "
        "the higher it ranks. Each column is ranked independently — highlight a concept "
        "to see where it ranks on both sides.",
        "zh-CN": "把每一侧所有已归类的回答放在一起数，不分问题：一个概念占该侧回答总数的份额"
        "越大，字就越大、排得越靠前。两列各自排各自的序——点亮一个概念，就能看到它在两边"
        "分别排在哪里。",
    },
    #: The topics_raised source: the unit is the reporting cluster, not the
    #: answer, so the sentence that explains the picture has to change with it.
    "cc_lede_topics": {
        "en": "How often each side mentions key concepts.",
        "zh-CN": "双方提及某些关键概念的频率对比",
    },
    "cc_title": {"en": "Concept Cloud", "zh-CN": "概念云"},
    "cc_info_title": {"en": "How to read the concept cloud", "zh-CN": "如何阅读概念云"},
    "cc_info_open": {
        "en": "How the concept cloud is calculated",
        "zh-CN": "概念云如何计算",
    },
    "cc_total": {"en": "{n} classified answers", "zh-CN": "共 {n} 条已归类回答"},
    "cc_total_topics": {"en": "{n} independent reports", "zh-CN": "共 {n} 条独立报道"},
    "cc_foot": {
        "en": "Shown: concepts appearing in at least {min_count} answers and at or above "
        "{threshold} of a side's answers, at most "
        "{cap} per side ({hidden}). Share = that concept's count ÷ every classified "
        "answer on that side ({totals}). Hover or tap any concept to see the exact figures "
        "for both sides, whether or not it appears in the cloud.",
        "zh-CN": "只画出至少出现在 {min_count} 条回答中、且占该侧回答 {threshold} 及以上的"
        "概念，每侧最多 {cap} 个（{hidden}）。"
        "百分比 = 该概念计数 ÷ 该侧全部已归类回答（{totals}）。悬停或点击任一概念，可以看到"
        "两侧各自的真实数字——没画出来的也有。",
    },
    "cc_foot_topics": {
        "en": "Shown: concepts mentioned in at least {min_count} independent reports and in "
        "at least {threshold} of one side's reports, at most {cap} per side ({hidden}). "
        "Share = reports mentioning that concept ÷ all independent reports on that side "
        "({totals}). ",
        "zh-CN": "概念云图按出现频率展示至少在 {min_count} 条独立报道中被谈到、且占该侧报道 {threshold} 及以上"
        "的概念化短语，每侧最多 {cap} 个（{hidden}）。显示的百分比数值 = 谈到该短语的独立报道数 ÷ 该侧全部独立"
        "报道（{totals}）。",
    },
    "cc_hidden_side": {
        "en": "{who}: {below} below the threshold",
        "zh-CN": "{who}有 {below} 个低于阈值",
    },
    "cc_hidden_capped": {
        "en": ", {capped} past the cap",
        "zh-CN": "、{capped} 个超出上限",
    },
    "cc_hidden_sep": {"en": "; ", "zh-CN": "；"},
    "cc_side_total": {"en": "{who} {n}", "zh-CN": "{who} {n}"},
    "cc_absent": {"en": "not found", "zh-CN": "未出现"},
    "cc_below": {
        "en": "(below the threshold, not drawn)",
        "zh-CN": "（频率低于阈值，未显示）",
    },
    "cc_capped": {
        "en": "(past the per-side cap, not drawn)",
        "zh-CN": "（排名低于阈值，未显示）",
    },
    "search_title": {"en": "Search", "zh-CN": "搜索报道"},
    "search_clear": {"en": "Clear search", "zh-CN": "清空搜索"},
    "search_lede": {
        "en": "Search report details by keyword (article text excluded).",
        "zh-CN": "用关键词匹配报道属性（除正文）",
    },
    "search_placeholder": {
        "en": "Title, phrase, concept, date, outlet…",
        "zh-CN": "输入标题、短语、概念、日期、媒体名等…",
    },
    "search_count": {
        "en": "Matches: {n}",
        "zh-CN": "找到 {n} 篇相关报道",
    },
    "search_more": {
        "en": "Showing the first {shown} of {total} related reports.",
        "zh-CN": "显示前 {shown} 篇，共找到 {total} 篇。",
    },
    "search_none": {
        "en": "No report matches all of those keywords.",
        "zh-CN": "没有报道同时匹配这些关键词。",
    },
    "search_phrases": {"en": "key phrases", "zh-CN": "关键短语"},
    "search_answers": {"en": "Q&A", "zh-CN": "问答标注"},
    "search_open": {"en": "Open report record", "zh-CN": "打开报道记录"},
    "scope_open": {"en": "Scope", "zh-CN": "采集范围"},
    "scope_title": {"en": "Scope", "zh-CN": "采集范围"},
    "scope_period": {"en": "Window", "zh-CN": "时间窗"},
    "scope_collected_end": {
        "en": "{date} (the day we collected)",
        "zh-CN": "{date}（采集当日）",
    },
    "scope_include": {"en": "In scope", "zh-CN": "收录"},
    "scope_exclude": {"en": "Out of scope", "zh-CN": "排除"},
    "scope_target": {
        "en": "Target independent reports per side",
        "zh-CN": "每侧目标独立报道数",
    },
    "scope_note": {
        "en": "Scope confirmed before news collection began",
        "zh-CN": "采集新闻之前确认的范围",
    },
    "scope_tip": {
        "en": "How reports were collected",
        "zh-CN": "新闻报道如何被采集",
    },
    "appendix_title": {
        "en": "Q&A Data",
        "zh-CN": "所有问答数据",
    },
    "appendix_intro": {
        "en": "A complete data view of every question asked and every answer annotated.",
        "zh-CN": "下面是所有提出的问题和标注的答案的完整数据展示。",
    },
    "appendix_expand": {"en": "Expand all", "zh-CN": "全部展开"},
    "appendix_collapse": {"en": "Collapse all", "zh-CN": "全部收起"},
    "annotations": {"en": "Details", "zh-CN": "详细数据"},
    "open_annotations": {
        "en": "Show all source sentences and annotations",
        "zh-CN": "显示所有相关原文及标注",
    },
    "open_stats": {"en": "Statistics", "zh-CN": "统计证据"},
    "stats_title": {"en": "Statistics", "zh-CN": "统计证据"},
    "not_addressed": {"en": "did not answer", "zh-CN": "未回答"},
    "delta": {"en": "Difference", "zh-CN": "差值"},
    "stability": {"en": "direction stability", "zh-CN": "方向稳定性"},
    "interval": {"en": "interval", "zh-CN": "区间"},
    "cluster": {"en": "report", "zh-CN": "报道"},
    "cluster_article": {"en": "{n} article", "zh-CN": "{n} 篇"},
    "cluster_articles": {"en": "{n} articles", "zh-CN": "{n} 篇"},
    "category": {"en": "answer", "zh-CN": "答案"},
    "summary": {"en": "annotation notes", "zh-CN": "标注笔记"},
    #: The annotation summary column is the English pivot master and
    #: is not localized (intended), so its prefix stays English on every page — a Chinese
    #: label in front of English text reads as a translation failure.
    "note": {"en": "Notes", "zh-CN": "Notes"},
    "modal_position": {"en": "position", "zh-CN": "位置"},
    "modal_para": {"en": "paragraph {p}, sentence {s}", "zh-CN": "第 {p} 段第 {s} 句"},
    "modal_cluster": {"en": "report group", "zh-CN": "独立报道组"},
    "modal_origin": {"en": "reporting origin", "zh-CN": "报道来源类型"},
    "modal_fetched": {"en": "collected on", "zh-CN": "报道采集时间"},
    "modal_topics": {"en": "key phrases", "zh-CN": "报道关键短语"},
    "modal_topics_tip": {
        "en": "Switch between the article's original wording and its localized concept.",
        "zh-CN": "在报道原文与其本地化概念之间切换",
    },
    "modal_topics_switch": {"en": "wording ↔ concept", "zh-CN": "原文 ↔ 概念"},
    "modal_topics_source": {"en": "wording", "zh-CN": "原文"},
    "modal_topics_concept": {"en": "concept", "zh-CN": "概念"},
    "modal_out": {"en": "Full article at publisher ↗", "zh-CN": "去原站阅读全文 ↗"},
    "modal_note": {
        "en": "This site does not store the full article.",
        "zh-CN": "本站不保存整篇文章。",
    },
    "modal_close": {"en": "Close", "zh-CN": "关闭"},
    "cluster_title": {"en": "Report group", "zh-CN": "独立报道组"},
    "cluster_lede": {
        "en": "These articles were identified as versions of the same report.",
        "zh-CN": "以下文章被判定为同一篇报道。",
    },
    "cluster_col_outlet": {"en": "outlet", "zh-CN": "媒体"},
    "cluster_col_date": {
        "en": "date",
        "zh-CN": "日期",
    },
    "cluster_col_title": {"en": "headline", "zh-CN": "标题"},
    #: The tag on the cluster member that did the reporting the rest carry.
    "cluster_original": {"en": "orig.", "zh-CN": "原创"},
    "cluster_tip": {
        "en": "Open this report group",
        "zh-CN": "查看报道组",
    },
    "withheld": {
        "en": "We never show more than half of any one article, so this anchor is "
        "listed by address only — read it at the publisher.",
        "zh-CN": "同一篇文章我们最多只展示其中一半的句子，因此这条锚点只列出位置，"
        "原句请到原站阅读。",
    },
    "quote_tip": {
        "en": "Open our record of this sentence — outlet, date, report group, where it "
        "appears in the article, and the link to the publisher.",
        "zh-CN": "打开我们对这句话的记录：媒体、日期、报道组、它在原文中的位置，以及到原站的链接。",
    },
    "toggle_tr": {
        "en": "Switch every quote on this page between its verbatim original and our "
        "translation.",
        "zh-CN": "切换整页引文：显示原文，还是显示我们的译文。",
    },
    "tr_original": {"en": "original", "zh-CN": "原文"},
    "tr_translated": {"en": "translation", "zh-CN": "译文"},
    "theme_tip": {"en": "Switch between light and dark mode", "zh-CN": "切换浅色 / 深色主题"},
    "home_link": {"en": "Back to home", "zh-CN": "返回首页"},
    "back_to_top": {"en": "Back to top", "zh-CN": "回到顶部"},
    "nav_tip": {"en": "Jump to angle {n}", "zh-CN": "跳到第 {n} 个角度"},
    "featured": {"en": "featured", "zh-CN": "精选"},
    "featured_tip": {
        "en": "Angle selected by AI based on statistical evidence and news value",
        "zh-CN": "AI 根据统计证据和新闻价值综合挑选出的视角",
    },
    "caveat_label": {"en": "important", "zh-CN": "注意"},
    "detail_label": {"en": "more", "zh-CN": "补充"},
    "media_country": {"en": "location", "zh-CN": "所在地"},
    "media_lang": {"en": "language", "zh-CN": "出版语言"},
    "media_category": {"en": "type", "zh-CN": "媒体类型"},
    "media_beat": {"en": "coverage", "zh-CN": "报道范围"},
    "media_site": {"en": "Visit outlet ↗", "zh-CN": "打开该媒体网站 ↗"},
    "media_tip": {"en": "About this outlet", "zh-CN": "这家媒体是谁"},
    "rate_label": {
        "en": "answered {addressed}/{total}",
        "zh-CN": "回答率 {addressed}/{total}",
    },
    # ⓘ next to a side's badge, e.g. "9 / 12 独立报道".
    "badge_tip_top": {
        "en": "{denominator} independent reports answered this question; {numerator} of "
        "them gave the answer above.",
        "zh-CN": "{denominator} 篇独立报道回答了此问题，其中 {numerator} 篇给出了上述答案。"
        "",
    },
    "badge_tip_top_full": {
        "en": "Of the {total} readable independent reports counted in this analysis, "
        "{denominator} answered "
        "this question; {numerator} of them gave the answer above.",
        "zh-CN": "本次分析计入的 {total} 篇可读独立报道中，{denominator} 篇回答了此问题，"
        "其中 {numerator} 篇给出了本答案。",
    },
    "badge_tip_addressed": {
        "en": "Of the {denominator} readable independent reports counted in this analysis, "
        "{numerator} answered this question.",
        "zh-CN": "本次分析计入的 {denominator} 篇可读独立报道中，{numerator} 篇回答了此问题。",
    },
    "evidence_title": {
        "en": "Reports supporting “{answer}”",
        "zh-CN": "支持答案「{answer}」的报道原文",
    },
    "evidence_report": {"en": "report source", "zh-CN": "报道来源"},
    "evidence_quote": {"en": "quoted text", "zh-CN": "引文"},
    "rate_tip": {
        "en": "Of the {total} readable independent reports counted in this analysis, "
        "{addressed} answered this question.",
        "zh-CN": "本次分析计入的 {total} 篇可读独立报道中，有 {addressed} 篇回答了此问题。",
    },
    "rank_tip": {
        "en": "Q&A pairs are ranked automatically by statistical significance and effect size",
        "zh-CN": "所有问答按统计显著性与现象幅度的自动排序",
    },
    "tied_label": {"en": "tied lead", "zh-CN": "并列第一"},
    "tied_tip": {
        "en": "Two or more answers are tied for first place on one side",
        "zh-CN": "某侧有若干并列第一的答案",
    },
    "secondary_label": {"en": "secondary", "zh-CN": "次要发现"},
    "secondary_tip": {
        "en": "Tracks how often the question is addressed, not how it is answered. It may "
        "support an angle but cannot be an angle on its own.",
        "zh-CN": "这类发现说的是“问题被谈到的频率”，而不是“答案是什么”。它可以作为角度里的"
        "补充，但不能单独成为一个角度。",
    },
    # -- the two footer modals ----------------------------------------------------------
    "method_open": {"en": "Method", "zh-CN": "统计方法"},
    "method_title": {"en": "Method", "zh-CN": "统计方法"},
    "disclosure_open": {"en": "About this page", "zh-CN": "本页说明"},
    "disclosure_title": {"en": "About this page", "zh-CN": "本页说明"},
    "disclosure_lede": {
        "en": "What you should know about how this particular page was produced.",
        "zh-CN": "关于这一页具体是怎么做出来的，你应该知道的事。",
    },
    "disclosure_collected": {"en": "Collection finished", "zh-CN": "采集完成于"},
    "disclosure_ai": {
        "en": "Every stage of this page — collection, annotation, the writing and the "
        "translations — was produced by AI systems and audited by a human before "
        "publication. Translations are ours, not the publisher's; the verbatim original "
        "of every quote is one click away and is always the record.",
        "zh-CN": "本页的每一个环节——采集、标注、写作与翻译——都由 AI 系统完成，并在发布前经过"
        "人工审核。译文由我们提供，不是媒体自己的版本；每条引文的原句都在一次点击之外，"
        "并且原句才是记录本身。",
    },
    # The tagline names the product's point (one piece of news, two tellings) and
    # carries the site's own name beside it — the footer is where a reader who arrived on
    # a shared angle link finds out whose page they are on.
    "footer_note": {
        "en": "One story, two tales",
        "zh-CN": "一条新闻，两组故事",
    },
}

_identity_path = Path(__file__).with_name("data") / "site_identity.v1.json"
_identity = json.loads(_identity_path.read_text(encoding="utf-8"))

# This renderer-owned record supersedes the old writer-authored disclosure copy.
# Keep the override separate so legacy keys can remain loadable while no rendered page
# reads them.
STRINGS.update(
    {
        "disclosure_open": {"en": "Page record", "zh-CN": "页面记录"},
        "disclosure_title": {"en": "Page record", "zh-CN": "页面记录"},
        "disclosure_lede": {
            "en": "A snapshot of the data and process versions behind this page.",
            "zh-CN": "本页各项数据和流程的版本快照",
        },
        "provenance_scope": {"en": "Signed scope", "zh-CN": "签署范围"},
        "provenance_corpus": {
            "en": "Corpus snapshot",
            "zh-CN": "语料快照",
        },
        "provenance_questions": {"en": "Question set", "zh-CN": "问题集"},
        "provenance_answers": {"en": "Annotations", "zh-CN": "标注"},
        "provenance_normalization": {
            "en": "Category map",
            "zh-CN": "类别映射",
        },
        "provenance_analysis": {"en": "Analysis", "zh-CN": "分析"},
        "provenance_write": {"en": "Writing", "zh-CN": "写作"},
        "provenance_page": {"en": "Page snapshot", "zh-CN": "页面快照"},
        "provenance_contributor": {"en": "Contributor", "zh-CN": "投稿人"},
        "provenance_anonymous": {"en": "Anonymous", "zh-CN": "匿名"},
        "provenance_scope_actor": {"en": "Signed by {who}", "zh-CN": "由 {who} 签署"},
        "provenance_scope_actor_ai": {
            "en": "Signed by {who}, standing in for the human reviewer",
            "zh-CN": "由 {who} 代签，代表人工审核员",
        },
        "provenance_page_actor": {"en": "Reviewed by {who}", "zh-CN": "由 {who} 审核"},
        "provenance_page_actor_ai": {
            "en": "Reviewed by {who}, standing in for the human reviewer",
            "zh-CN": "由 {who} 代审，代表人工审核员",
        },
        #: Appended to either of the two above when the topic manifest names the language
        #: the reviewer read.  A review is of one rendering in one language; saying which
        #: is the difference between "a human read this" and "a human read *this*".
        "provenance_review_lang": {
            "en": " (review language: {lang})",
            "zh-CN": "（审核语言：{lang}）",
        },
    }
)

#: What each step produced, in the reader's language.  Keys are manifest counter names;
#: a counter the run did not record simply does not appear.  This is the only part of the
#: page record a non-technical reader can actually use, so it is worded as a result
#: ("18 articles"), never as a field name.
PROVENANCE_COUNTS: dict[str, tuple[tuple[str, dict], ...]] = {
    "corpus": (
        ("articles", {"en": "{n} articles", "zh-CN": "{n} 篇文章"}),
        (
            "reporting_clusters",
            {"en": "{n} independent reports", "zh-CN": "{n} 个独立报道组"},
        ),
    ),
    "questions": (("questions", {"en": "{n} questions", "zh-CN": "{n} 个问题"}),),
    "answers": (
        ("answers", {"en": "{n} answers", "zh-CN": "{n} 条答案"}),
        (
            "clusters",
            {"en": "across {n} reports", "zh-CN": "覆盖 {n} 个报道组"},
        ),
    ),
    "normalization": (
        (
            "categories_merged",
            {"en": "{n} categories merged", "zh-CN": "合并 {n} 个类别"},
        ),
    ),
    "analysis": (
        ("findings", {"en": "{n} findings", "zh-CN": "{n} 项发现"}),
        ("supported", {"en": "{n} above the bar", "zh-CN": "{n} 项达到支持线"}),
    ),
    "write": (
        ("angles", {"en": "{n} angles", "zh-CN": "{n} 个角度"}),
        ("quotes", {"en": "{n} quotes", "zh-CN": "{n} 段引文"}),
    ),
    "page": (("languages", {"en": "{n} languages", "zh-CN": "{n} 种语言"}),),
}

#: The methodology modal, identical on every page there will ever be.  It
#: lives here rather than in ``how_we_counted.notes`` because it is not about this topic:
#: when the site grows a standing methodology page, this text moves there unchanged.
METHOD_SECTIONS = [
    (
        {"en": "Counting unit", "zh-CN": "计数单位"},
        {
            "en": "Most statistics on this site use independent reports, not articles, as their base unit. "
            "Multiple versions of the same report — such as a press release republished by several websites — are grouped and counted once.",
            "zh-CN": "本页所有统计量的计数单位是一条独立报道，并非一篇文章。同一份报道的多个版本——一条通稿"
            "和转载它的若干家网站——会被归入同一个独立报道组，只计一次。",
        },
    ),
    (
        {"en": "Q&A", "zh-CN": "问与答"},
        {
            "en": "We ask every independent report on both sides the same set of questions. "
            "Answers (or \"no answer\") are normalized to a shared vocabulary so "
            "the two sides can be compared.",
            "zh-CN": "我们对双方的每一条独立报道提出同一组问题。"
            "答案（或「没有答案」）会被归一为一套两侧共用的词汇，从而可被比较。",
        },
    ),
    (
        {"en": "Statistics", "zh-CN": "统计证据"},
        {
            "en": "We statistically test each candidate pattern using all reports. Only patterns that reappear consistently enough are presented as findings/angles.",
            "zh-CN": "为了从问答数据中发现坚实稳定的规律，每一个假设都经过了统计检验。"
            "只有在一定程度上可复现的统计规律，才会被展示为结论、视角。",
        },
    ),
    (
        {"en": "Sources", "zh-CN": "追溯原文"},
        {
            "en": "Every number and judgment on this page traces back to source sentences or AI annotations. AI annotations can be wrong, but the record makes any errors traceable and auditable.",
            "zh-CN": "本页的每一个数字和判断都可以追溯到报道的原文摘句或 AI 标注的结果。"
            "AI 标注可能存在错误，但这些错误能被追溯和问责。",
        },
    ),
]

#: The statistics modal's three templates.  One paragraph per kind,
#: generated from the pinned finding — a writer never sees these numbers.
STAT_TEMPLATE = {
    "consensus": {
        "en": "Both sides have the same most common answer: **{answer}**. Averaged across "
        "the two sides, it accounts for **{value:.0%}** of reports that answered "
        "(90% interval [{lo:.0%}, {hi:.0%}]) — {left_share} and {right_share}.",
        "zh-CN": "双方最常见的答案是同一个：**{answer}**。它在两侧作答报道中所占份额的平均值为"
        "**{value:.0%}**（90% 区间 [{lo:.0%}, {hi:.0%}]）——{left_share}，{right_share}。",
    },
    "divergence": {
        "en": "The most common answer differs between the two sides: {left_answer} versus "
        "{right_answer}. Averaged across those two answers, the cross-side difference in "
        "share is **{value:.0%}** (90% interval [{lo:.0%}, {hi:.0%}]).",
        "zh-CN": "两侧最常见的答案不同：{left_answer}，对上{right_answer}。把这两个答案各自在"
        "两侧的份额之差取平均，为 **{value:.0%}**（90% 区间 [{lo:.0%}, {hi:.0%}]）。",
    },
    "attention_gap": {
        "en": "One side addresses this question far less often than the other: the two "
        "sides' rates of answering it differ by **{value:+.0%}** "
        "(90% interval [{lo:+.0%}, {hi:+.0%}]) — {left_rate} against {right_rate}.",
        "zh-CN": "一侧谈到这个问题的频率远低于另一侧：两侧回答率之差为 **{value:+.0%}**"
        "（90% 区间 [{lo:+.0%}, {hi:+.0%}]）——{left_rate}，对上{right_rate}。",
    },
}

STAT_STABILITY = {
    "en": "When the reports are resampled, the same pattern reappears **{stability:.0%}** "
    "of the time.",
    "zh-CN": "把报道重新抽样，同样的图景有 **{stability:.0%}** 的次数会再次出现。",
}

STAT_RATE_LINE = {
    "en": "Share of reports that answered at all: {left_rate}, {right_rate} "
    "(difference {value:+.0%}, 90% interval [{lo:+.0%}, {hi:+.0%}]).",
    "zh-CN": "两侧各自的回答率：{left_rate}，{right_rate}"
    "（差值 {value:+.0%}，90% 区间 [{lo:+.0%}, {hi:+.0%}]）。",
}

STAT_SHARE = {
    "en": "{who}: {numerator}/{denominator} ({share:.0%})",
    "zh-CN": "{who} {numerator}/{denominator}（{share:.0%}）",
}

#: The statistics modal's live sentence generator (``render.stats.stat_blocks``) never
#: used ``STAT_TEMPLATE``/``STAT_STABILITY``/``STAT_RATE_LINE`` above — it was rewritten
#: (three separate bullets instead of one combined paragraph per kind) with the
#: English/Chinese text typed straight into ``if lang.startswith("zh") else`` branches,
#: bypassing every ``pick()``/``STRINGS`` table the halo-locale merge filled in. That is
#: *why* those ~2,870 entries never reached this modal: they filled tables this function
#: does not read. These twelve keys are that function's actual live vocabulary, named
#: after the local variable each one fills; ``en``/``zh-CN`` are copied verbatim from the
#: literals they replace (a fix must not change bytes the user already reviewed), the
#: other seven locales are new.
STAT_STRENGTH_CLAUSE = {
    "en": "; observed stability: {stability:.0%}",
    "zh-CN": "（{stability:.0%}）",
}

STAT_LOUD_CLAUSE_FLOOR = {
    "en": "at least {floor:.0%}",
    "zh-CN": "不低于 {floor:.0%}",
}

STAT_LOUD_CLAUSE_SPREAD = {
    "en": "at least {spread:.0%} higher",
    "zh-CN": "比前者高出 {spread:.0%} 以上",
}

STAT_PHENOMENON_SILENCE = {
    "en": "The two sides' answer rates are **{quiet_rate:.0%}** (below {smax:.0%}) and "
    "**{loud_rate:.0%}** ({loud_clause})",
    "zh-CN": "双方的回答率分别是 **{quiet_rate:.0%}**（低于 {smax:.0%}）和 "
    "**{loud_rate:.0%}**（{loud_clause}）",
}

STAT_PHENOMENON_CONSENSUS = {
    "en": "Both sides' most common answer is the same: **{shared}**",
    "zh-CN": "双方最常见的答案是同一个：**{shared}**",
}

STAT_PHENOMENON_DIVERGENCE = {
    "en": "The sides' most common answers differ: {left_short} **{lanswer}**; "
    "{right_short} **{ranswer}**",
    "zh-CN": "双方最常见的答案不同：{left_short} **{lanswer}**，{right_short} **{ranswer}**",
}

STAT_PHENOMENON_ATTENTION_GAP_GENERIC = {
    "en": "One side barely answers this question while the other answers it "
    "substantially more often",
    "zh-CN": "一方几乎不回答这个问题，而另一方明显更常回答",
}

STAT_REPRODUCIBILITY = {
    "en": "After resampling all reports {draws} times, the same pattern reappeared in "
    "**{stable:.0%}** of draws (that is, > {gate:.0%} statistical reproducibility).",
    "zh-CN": "把全体报道重新抽样 {draws} 次，上述现象在 **{stable:.0%}** 的情况下再次出现"
    "（即 > {gate:.0%} 统计可复现率）。",
}

STAT_RATE_LEAD = {
    "en": "Difference in answer rates: **{value:+.0%}**. {left_phrase}; {right_phrase}",
    "zh-CN": "双方的回答率差值：**{value:+.0%}**。{left_phrase}，{right_phrase}",
}

#: Keyed ``"same"``/``"diff"`` — whether the rate difference's 90% interval crosses zero.
STAT_READING = {
    "same": {
        "en": "no statistical difference in answer rates",
        "zh-CN": "回答率在统计上无差别",
    },
    "diff": {
        "en": "a statistical gap in answer rates",
        "zh-CN": "回答率在统计上有差距",
    },
}

STAT_RATE_DETAIL = {
    "en": "Across {draws} resamples, its 90% confidence interval is "
    "**[{lo:+.0%}, {hi:+.0%}]** ({reading}).",
    "zh-CN": "把全体报道重新抽样 {draws} 次，该值的 90% 置信区间是 "
    "**[{lo:+.0%}, {hi:+.0%}]**（即{reading}）。",
}

STAT_EFFECT_LEAD_CONSENSUS = {
    "en": "The average support for the shared leading answer is **{value:.0%}**. "
    "{left_phrase}; {right_phrase}",
    "zh-CN": "双方最常见的答案支持率的平均值为 **{value:.0%}**。{left_phrase}，{right_phrase}",
}

STAT_EFFECT_LEAD_DIVERGENCE = {
    "en": "The average cross-side support gap for the two leading answers is "
    "**{value:.0%}**.",
    "zh-CN": "双方最常见的答案支持率与对方同答案支持率之差的平均值为 **{value:.0%}**。",
}

#: Keyed ``"consensus"``/``"divergence"`` — what the effect-size interval is an estimate of.
STAT_ESTIMATE = {
    "consensus": {
        "en": "an estimate of agreement support",
        "zh-CN": "共识支持率的估计",
    },
    "divergence": {
        "en": "an estimate of divergence magnitude",
        "zh-CN": "分歧程度的估计",
    },
}

STAT_EFFECT_DETAIL = {
    "en": "Across {draws} resamples, its 90% confidence interval is "
    "**[{lo:+.0%}, {hi:+.0%}]** ({estimate}).",
    "zh-CN": "把全体报道重新抽样 {draws} 次，该值的 90% 置信区间是 "
    "**[{lo:+.0%}, {hi:+.0%}]**（{estimate}）。",
}


#: The halo's other seven locales, merged in from versioned package data rather
#: than typed out ~190 times over per language.  Every leaf here is still a plain
#: ``{"en": ..., "zh-CN": ..., "ru": ..., ...}`` dict — nothing downstream has to know
#: these keys arrived from a JSON merge instead of a literal.  Shape rule:
#: ``newsab_schema.i18n_merge``.
_I18N_CONSTANTS: dict[str, object] = {
    "KIND_LABEL": KIND_LABEL,
    "KIND_TIP": KIND_TIP,
    "KIND_EMPTY": KIND_EMPTY,
    "STRENGTH_LABEL": STRENGTH_LABEL,
    "STRENGTH_TIP_POSTERIOR": STRENGTH_TIP_POSTERIOR,
    "TIER_LABEL": TIER_LABEL,
    "TIER_TIP": TIER_TIP,
    "SOURCE_CATEGORY": SOURCE_CATEGORY,
    "BEAT_SCOPE": BEAT_SCOPE,
    "COUNTRY_LABEL": COUNTRY_LABEL,
    "LANG_LABEL": LANG_LABEL,
    "ORIGIN_LABEL": ORIGIN_LABEL,
    "STRINGS": STRINGS,
    "PROVENANCE_COUNTS": PROVENANCE_COUNTS,
    "METHOD_SECTIONS": METHOD_SECTIONS,
    "STAT_TEMPLATE": STAT_TEMPLATE,
    "STAT_STABILITY": STAT_STABILITY,
    "STAT_RATE_LINE": STAT_RATE_LINE,
    "STAT_SHARE": STAT_SHARE,
}
_i18n_path = Path(__file__).with_name("data") / "chrome_strings_i18n.v1.json"
_i18n_data = json.loads(_i18n_path.read_text(encoding="utf-8"))
for _const_name, _by_lang in _i18n_data.items():
    _live_const = _I18N_CONSTANTS[_const_name]
    for _lang in EXTRA_HALO_LOCALES:
        merge_lang_leaf(_live_const, _by_lang[_lang], _lang)

#: ``footer_site`` is the site's domain label from ``site_identity.v1.json``, not prose:
#: it is identical in every locale and is set after the merge above so the translation
#: file never carries it (a public clone's neutral identity must flow through).
STRINGS["footer_site"] = {
    lang: _identity["domain_label"] for lang in ("en", "zh-CN", *EXTRA_HALO_LOCALES)
}

#: See the comment on ``STAT_STRENGTH_CLAUSE`` above: the statistics modal's actual live
#: templates, merged in the same shape from a second versioned file so this fix stays a
#: separate, reviewable diff from the halo-locale merge's.
_STAT_PANEL_I18N_CONSTANTS: dict[str, object] = {
    "STAT_STRENGTH_CLAUSE": STAT_STRENGTH_CLAUSE,
    "STAT_LOUD_CLAUSE_FLOOR": STAT_LOUD_CLAUSE_FLOOR,
    "STAT_LOUD_CLAUSE_SPREAD": STAT_LOUD_CLAUSE_SPREAD,
    "STAT_PHENOMENON_SILENCE": STAT_PHENOMENON_SILENCE,
    "STAT_PHENOMENON_CONSENSUS": STAT_PHENOMENON_CONSENSUS,
    "STAT_PHENOMENON_DIVERGENCE": STAT_PHENOMENON_DIVERGENCE,
    "STAT_PHENOMENON_ATTENTION_GAP_GENERIC": STAT_PHENOMENON_ATTENTION_GAP_GENERIC,
    "STAT_REPRODUCIBILITY": STAT_REPRODUCIBILITY,
    "STAT_RATE_LEAD": STAT_RATE_LEAD,
    "STAT_READING": STAT_READING,
    "STAT_RATE_DETAIL": STAT_RATE_DETAIL,
    "STAT_EFFECT_LEAD_CONSENSUS": STAT_EFFECT_LEAD_CONSENSUS,
    "STAT_EFFECT_LEAD_DIVERGENCE": STAT_EFFECT_LEAD_DIVERGENCE,
    "STAT_ESTIMATE": STAT_ESTIMATE,
    "STAT_EFFECT_DETAIL": STAT_EFFECT_DETAIL,
}
_stat_panel_i18n_path = Path(__file__).with_name("data") / "stat_panel_i18n.v1.json"
_stat_panel_i18n_data = json.loads(_stat_panel_i18n_path.read_text(encoding="utf-8"))
for _const_name, _by_lang in _stat_panel_i18n_data.items():
    _live_const = _STAT_PANEL_I18N_CONSTANTS[_const_name]
    for _lang in EXTRA_HALO_LOCALES:
        merge_lang_leaf(_live_const, _by_lang[_lang], _lang)


def e(text: object) -> str:
    return html.escape(str(text), quote=True)


def t(record, lang: str) -> str:
    """Pick a language from a MultiLangText, falling back to English."""
    if record is None:
        return ""
    return record.get(lang) or record.get("en") or next(iter(record.values.values()))


def pick(mapping: dict, key: str, lang: str) -> str:
    entry = mapping.get(key)
    if entry is None:
        return key
    return entry.get(lang, entry["en"])


def s(key: str, lang: str) -> str:
    return STRINGS[key].get(lang, STRINGS[key]["en"])


def rich(text: str) -> str:
    """Escape, then honour the one piece of markup the template strings use: ``**bold**``.

    The modal paragraphs above are the only reader-facing text this renderer authors at
    paragraph length, and a number that carries the sentence deserves to be visible.
    """
    out = e(text)
    parts = out.split("**")
    if len(parts) % 2 == 0:  # unbalanced — leave it alone rather than guess
        return out
    return "".join(
        part if index % 2 == 0 else f"<strong>{part}</strong>"
        for index, part in enumerate(parts)
    )


def maybe(value: Optional[str]) -> str:
    return value or ""
