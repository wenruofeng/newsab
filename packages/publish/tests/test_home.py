from __future__ import annotations

import re
from datetime import date, datetime, timezone

import pytest

from newsab_publish.home import PAGE_STEP, daily_catalog_order, render_home
from newsab_publish.identity import site_identity
from newsab_publish.metadata import default_metadata_path, load_site_metadata


def _region(section_id: str, rendered: str) -> str:
    return rendered.split(f'id="{section_id}"', 1)[1].split("</section>", 1)[0]


def _ids(section_id: str, rendered: str) -> list[str]:
    return re.findall(r'data-publication-id="([^"]+)"', _region(section_id, rendered))


def test_home_is_byte_deterministic_and_latest_has_stable_tie_break(catalog_factory, metadata):
    moment = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)
    older = catalog_factory(1, published_at=datetime(2026, 8, 20, tzinfo=timezone.utc))
    tied_a = catalog_factory(2, published_at=moment)
    tied_b = catalog_factory(3, published_at=moment)
    records = [older, tied_a, tied_b]

    first = render_home(records, locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25))
    second = render_home(reversed(records), locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25))
    assert first == second
    # The lead card is the newest publication; the explorer holds the whole catalogue in
    # the same order, so a reader without JavaScript still reads newest first.
    tied = sorted((tied_a, tied_b), key=lambda row: row.publication_id)
    assert _ids("latest", first) == [tied[0].publication_id]
    assert _ids("browse", first) == [
        tied[0].publication_id,
        tied[1].publication_id,
        older.publication_id,
    ]
    assert '<link rel="icon" type="image/svg+xml" href="/assets/favicon.svg">' in first
    assert "data:image/svg+xml" not in first


def test_daily_order_uses_only_explicit_date_and_publication_id(catalog_factory):
    records = [catalog_factory(serial) for serial in range(5)]
    first = daily_catalog_order(records, date(2026, 8, 25))
    repeated = daily_catalog_order(reversed(records), date(2026, 8, 25))
    next_day = daily_catalog_order(records, date(2026, 8, 26))
    assert [row.publication_id for row in first] == [row.publication_id for row in repeated]
    assert [row.publication_id for row in first] != [row.publication_id for row in next_day]


def test_daily_order_is_carried_as_a_card_attribute_not_a_second_render(catalog_factory, metadata):
    """The shuffle is a re-ordering of the very cards the build wrote, never new markup.

    Both orders are stated per card, so switching between them cannot show a reader
    anything the deterministic build did not put on the page.
    """
    records = [catalog_factory(serial) for serial in range(5)]
    rendered = render_home(
        records, locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25)
    )
    browse = _region("browse", rendered)
    latest_indices = [int(value) for value in re.findall(r'data-i="(\d+)"', browse)]
    daily_indices = sorted(int(value) for value in re.findall(r'data-d="(\d+)"', browse))
    assert latest_indices == list(range(5))
    assert daily_indices == list(range(5))
    expected = [
        row.publication_id for row in daily_catalog_order(records, date(2026, 8, 25))
    ]
    ordered = sorted(
        re.findall(
            r'data-publication-id="([^"]+)" data-cats="[^"]*" data-read="[^"]*" '
            r'data-media="[^"]*" data-i="\d+" data-d="(\d+)"',
            browse,
        ),
        key=lambda pair: int(pair[1]),
    )
    assert [pair[0] for pair in ordered] == expected


def test_home_renders_the_masthead_the_lead_and_the_explorer(catalog_factory, metadata):
    records = [catalog_factory(0), catalog_factory(1)]
    rendered = render_home(
        records,
        locale="zh-CN",
        metadata=metadata,
        build_date=date(2026, 8, 25),
    )
    assert 'id="latest"' in rendered
    assert 'id="browse"' in rendered
    assert 'id="search"' in rendered
    assert 'data-lf="cat"' in rendered
    assert 'id="daily" data-build-date="2026-08-25"' in rendered
    assert "articleBody" not in rendered
    # every category some topic sits in is offered as a filter choice
    assert "公共生活" in rendered
    assert "环境" in rendered
    # the card states the sides and deep-links the first question
    assert "虚构甲组样本" in rendered
    assert "#angle-QST-" in rendered
    # the name reaches assistive technology whole; the split lockup is official brand
    # art, so a neutral public-toolkit identity opens on a plain name instead
    if site_identity().domain_label == "news-ab.com":
        assert f'<span class="vh">{site_identity().site_name}</span>' in rendered
        assert '<span class="wm-a">A</span>' in rendered
    else:
        assert 'class="masthead masthead--plain"' in rendered
        assert '<span class="wm-a">A</span>' not in rendered


def test_the_masthead_states_the_word_in_the_scripts_the_site_samples(catalog_factory, metadata):
    """The ring is decoration — the whole lockup is ``aria-hidden`` and the name reaches
    assistive technology once, whole — but every word has to be a real word in its own
    script, and English has to be one of the nine rather than the label above them."""
    rendered = render_home(
        [catalog_factory(0)], locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25)
    )
    if site_identity().domain_label != "news-ab.com":
        assert '<span class="wm-halo">' not in rendered
        return
    halo = rendered.split('<span class="wm-halo">', 1)[1].split("</span></span></span>", 1)[0]
    for word in ("News", "新闻", "ニュース", "뉴스", "समाचार", "أخبار", "Новости", "Noticias"):
        assert word in halo
    assert 'lang="ar" dir="rtl"' in halo
    # The ring sits inside the lockup and is measured in its em, so it holds its distance
    # from the letters at every size.
    assert 'class="wm-ab" aria-hidden="true"' in rendered
    assert "em;--y:" in halo and "rem;--y:" not in halo
    # Words beside the letters hang by their inner edge and leave sideways; the word above
    # the seam hangs by its middle, leaves straight up, and is the only neutral grey.
    assert "--ax:-100%;--x:-1.0000em;" in halo and "--dx:-1.0000;--dy:0.0000" in halo
    assert "--ax:0%;--x:0.9800em;" in halo and "--dx:1.0000;--dy:0.0000" in halo
    assert "--ax:-50%;--x:0.0000em;" in halo and "--tint:var(--ink2)" in halo
    assert "--tint:var(--a)" in halo and "--tint:var(--b)" in halo
    # No seam rule down the hero, no kicker over the letters, no gloss or stat line.
    assert ".masthead::after" not in rendered
    assert "wm-kicker" not in rendered
    assert 'class="gloss"' not in rendered and 'class="stats"' not in rendered


def test_the_tagline_is_each_locales_own_saying_not_a_translation(catalog_factory, metadata):
    zh = render_home([catalog_factory(0)], locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25))
    en = render_home(
        [catalog_factory(0, locale="en")], locale="en", metadata=metadata, build_date=date(2026, 8, 25)
    )
    # The band rotates through all nine halo languages' sayings, but the page opens on
    # the reader's own: it is the ``on`` item, the only one a no-JS reader sees, and it
    # comes from ``site_strings`` so editing a tagline there cannot leave the band
    # behind.
    identity = site_identity()
    if identity.domain_label == "news-ab.com":
        assert f'<span class="tagline-item on" lang="zh-Hans" dir="ltr">{identity.tagline["zh-CN"]}</span>' in zh
        assert f'<span class="tagline-item on" lang="en" dir="ltr">{identity.tagline["en"]}</span>' in en
        # The other languages ride along hidden, ready for the rotation.
        assert '<span class="tagline-item" aria-hidden="true" lang="en"' in zh
        assert 'lang="ar" dir="rtl"' in zh and 'lang="ja"' in zh
        assert "data-taglines" in zh and "prefers-reduced-motion" in zh
    else:
        # The sayings band is official brand art; a neutral build carries none of it.
        assert "data-taglines" not in zh.split("<body>", 1)[1]
    # A four-word saying is not a page description, so the meta tags keep their own line.
    assert f'<title>{identity.site_name} — {identity.tagline["zh-CN"]}</title>' in zh
    assert "看看两组媒体如何用不同方式讲述同一件事" in zh.split("<body>", 1)[0]


def test_a_card_states_the_window_the_reports_and_the_angles_not_the_publish_date(
    catalog_factory, metadata
):
    """Two dates on one card read as one fact, so only the sample window survives."""
    record = catalog_factory(0, published_at=datetime(2026, 8, 20, tzinfo=timezone.utc))
    rendered = render_home(
        [record], locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25)
    )
    assert "2026-05-01 – 2026-08-01" in rendered
    assert "2026-08-20" not in rendered
    assert "<time datetime=\"2026-08-20\"" not in rendered
    assert f">{record.report_count} 篇独立报道<" in rendered
    assert f">{len(record.angles)} 个视角<" in rendered
    assert "个问题" not in rendered



def test_a_record_written_before_the_readable_count_keeps_its_own_unit(
    catalog_factory, metadata
):
    """`report_count` counted raw articles before catalog-0.4.0.

    The unit belongs to the record: labelling an old number "independent reports" would
    misstate a publication nobody had rebuilt yet.
    """
    old = catalog_factory(0).model_copy(update={"catalog_version": "catalog-0.3.0"})
    rendered = render_home([old], locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25))
    assert f">{old.report_count} 篇文章<" in rendered
    assert "篇独立报道" not in rendered

def test_the_question_mark_is_the_same_in_every_locale(catalog_factory, metadata):
    for locale, other in (("zh-CN", "问"), ("en", "Question")):
        rendered = render_home(
            [catalog_factory(0, locale=locale)],
            locale=locale,
            metadata=metadata,
            build_date=date(2026, 8, 25),
        )
        assert '<span class="qm">Q:</span>' in rendered
        assert f'<span class="qm">{other}</span>' not in rendered


def test_the_two_language_filters_ask_two_different_questions(catalog_factory, metadata):
    """Reading language starts at the page's own locale and widens; media language starts
    unrestricted and narrows.  Both read attributes the build wrote onto the cards."""
    record = catalog_factory(0)
    rendered = render_home(
        [record], locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25)
    )
    read = rendered.split('data-lf="read"', 1)[1].split("</div></div>", 1)[0]
    media = rendered.split('data-lf="media"', 1)[1].split("</div></div>", 1)[0]
    # the reader's own locale is the only one ticked, and there is no "any" escape hatch
    assert '<input type="checkbox" value="zh-CN" checked>' in read
    assert '<input type="checkbox" value="en">' in read
    assert "data-lf-any" not in read
    # media starts at "no restriction", named in the reader's language
    assert "data-lf-any" in media and "不限定" in media
    assert 'checked' not in media
    assert "中文（简体）" in media and "英语" in media
    # and every card carries the two lists the filters match against
    assert 'data-read="en zh-CN"' in rendered
    assert 'data-media="en zh-CN"' in rendered


def test_media_filter_folds_hong_kong_into_traditional_chinese_and_names_urdu(
    catalog_factory, metadata
):
    """The catalog keeps exact source tags; the reader gets one Traditional choice."""
    record = catalog_factory(0).model_copy(
        update={"source_languages": ["zh-HK", "zh-TW", "ur"]}
    )
    rendered = render_home(
        [record], locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25)
    )
    media = rendered.split('data-lf="media"', 1)[1].split("</div></div>", 1)[0]
    assert media.count('value="zh-TW"') == 1
    assert 'value="zh-HK"' not in media
    assert "中文（繁体）" in media
    assert 'value="ur"' in media and "乌尔都语" in media
    # A topic carrying either precise tag matches the one reader-facing value.
    assert 'data-media="ur zh-TW"' in rendered


def test_mobile_masthead_gives_the_language_halo_a_little_more_room(
    catalog_factory, metadata
):
    rendered = render_home(
        [catalog_factory(0)],
        locale="zh-CN",
        metadata=metadata,
        build_date=date(2026, 8, 25),
        canonical_url="/zh-CN/",
    )
    assert ".wm-slot{font-size:.92em}" in rendered


def test_the_answer_card_gives_everything_left_over_to_the_answer(
    catalog_factory, metadata
):
    """Side tag centred and hugging the top, count in the corner beside it, and the whole
    remaining box for the answer, which centres in it both ways."""
    record = catalog_factory(0)
    angle = record.angles[0].model_copy(update={"counts": {"aa": "7/11", "bb": "4/6"}})
    record = record.model_copy(update={"angles": [angle, *record.angles[1:]]})
    rendered = render_home(
        [record], locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25)
    )
    # the tag is centred on its own line, not pushed to one end of a shared row
    assert ".thead{display:flex;align-items:center;justify-content:center" in rendered
    # ...and the card starts at the tag, with no band reserved above it
    assert "  padding:.5rem .55rem .7rem;" in rendered
    # the count is out of the flow, so it costs the answer nothing
    assert ".tside .cnt{position:absolute;" in rendered
    # ``margin:auto 0`` is what centres the answer in whatever is left
    assert ".tside .ans{margin:auto 0;" in rendered


def test_the_relation_is_joined_to_both_answers_in_their_own_colours(
    catalog_factory, metadata
):
    """The topic page draws a lead from the mark to each answer card, in that side's
    colour, dotted where the side said nothing.  The card-scale copy does the same."""
    record = catalog_factory(0)
    rendered = render_home(
        [record], locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25)
    )
    # Each lead is sized by the gap it closes — card edge to mark — rather than by a
    # guessed length, which is what left a hole at both ends of it.
    assert ".trel::before{left:0;right:calc(50% + var(--markw) / 2);background:var(--a)}" in rendered
    assert ".trel::after{right:0;left:calc(50% + var(--markw) / 2);background:var(--b)}" in rendered
    # ...and the relation column is the gap, so there is no grid gutter beside it either
    assert "grid-template-columns:1fr auto 1fr;align-items:stretch;gap:0" in rendered
    assert 'class="trel"' in rendered

    # A silent side is a fact about the card next to the relation column, so the build
    # states it: CSS in that column cannot ask its siblings anything.
    silent = record.angles[0].model_copy(
        update={"answers": {"aa": record.angles[0].answers["aa"], "bb": None}}
    )
    quiet = render_home(
        [record.model_copy(update={"angles": [silent, *record.angles[1:]]})],
        locale="zh-CN",
        metadata=metadata,
        build_date=date(2026, 8, 25),
    )
    assert 'class="trel trel--bsilent"' in quiet
    assert ".trel--bsilent::after" in quiet


def test_the_card_top_rule_is_one_quiet_accent_not_a_second_a_b_pairing(
    catalog_factory, metadata
):
    rendered = render_home(
        [catalog_factory(0)], locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25)
    )
    assert "border-radius:3px 3px 0 0;background:var(--accent);opacity:.42" in rendered
    assert "linear-gradient(90deg,var(--a) 0 50%,var(--b) 50% 100%)" not in rendered
    # the answer cards still wear the two sides, which is why the card top no longer does
    assert ".tside--a{border-top-color:var(--a);" in rendered


def test_the_answer_pair_is_the_topic_pages_answer_pair(catalog_factory, metadata):
    """One component, one set of colours.  The home card's pair mixed its tint into
    --paper while the topic page's mixed into a card surface, which in the dark theme
    drew the two answers darker than the card holding them."""
    from newsab_editorial.render.theme import CSS as TOPIC_CSS

    rendered = render_home(
        [catalog_factory(0)], locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25)
    )
    shared = [
        "--answer-surface:#FFFFFF",
        "--answer-surface:#262C33",
        "color-mix(in oklab,var(--a) 7%,var(--answer-surface))",
        "color-mix(in oklab,var(--b) 8%,var(--answer-surface))",
        "color-mix(in oklab,var(--muted) 7%,var(--answer-surface))",
    ]
    for fragment in shared:
        assert fragment in rendered, fragment
        assert fragment in TOPIC_CSS, fragment
    # Both dark states carry the token, or one of them falls back to the light value.
    assert rendered.count("--answer-surface:#262C33") == 2
    # The side chip on that card is part of it, so it takes the same percentages too.
    tight = TOPIC_CSS.replace(" ", "")
    for token in ("--a-soft:", "--b-soft:", "--a-line:", "--b-line:"):
        for line in [ln for ln in rendered.split("\n") if token in ln]:
            assert line.strip().replace(" ", "") in tight, line


def test_the_three_filters_share_one_row_in_one_shape(catalog_factory, metadata):
    """One strip of controls that narrows one grid, so it wraps as one strip rather than
    stacking into blocks on a phone.  The category filter became the same dropdown the
    language filters are, not a row of chips."""
    rendered = render_home(
        [catalog_factory(0)], locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25)
    )
    bar = rendered.split('<div class="exp-filters">', 1)[1].split("</div></div></div>", 1)[0]
    assert bar.index('data-lf="cat"') < bar.index('data-lf="read"') < bar.index('data-lf="media"')
    assert 'class="chip"' not in rendered and 'id="categories"' not in rendered
    assert ".exp-filters{display:flex;align-items:center;gap:.55rem;flex-wrap:wrap" in rendered
    # Never a sideways-scrolling rail: on a narrow screen the controls wrap like
    # everything else beside them.
    assert "flex-wrap:nowrap;overflow-x:auto" not in rendered


def test_category_filter_is_a_dropdown_that_starts_unrestricted(catalog_factory, metadata):
    """Named "分类", offering only categories some topic has, with the same "不限定" escape
    hatch the media filter has; the cards keep their category list for it to match."""
    record = catalog_factory(0)
    rendered = render_home(
        [record], locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25)
    )
    cat = rendered.split('data-lf="cat"', 1)[1].split("</div></div>", 1)[0]
    assert '<span class="lfl">分类</span>' in cat
    assert "data-lf-any" in cat and "不限定" in cat
    assert "checked" not in cat
    for category_id in record.category_ids:
        assert f'<input type="checkbox" value="{category_id}">' in cat
    offered = set(re.findall(r'value="([^"]+)"', cat))
    assert offered == set(record.category_ids)
    assert f'data-cats="{" ".join(record.category_ids)}"' in rendered
    # the script filters on the ticked categories like it does on languages
    assert "const langPick={cat:[],read:[],media:[]}" in rendered
    assert "cat.some(code=>row.cats.indexOf(code)>=0)" in rendered


def test_filtering_the_grid_never_removes_another_section(catalog_factory, metadata):
    """The explorer owns its own grid and nothing else on the page.

    It used to hide the featured story whenever a filter was on, which made the lead
    section blink out of existence as soon as anyone typed.
    """
    rendered = render_home(
        [catalog_factory(0)], locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25)
    )
    assert "getElementById('latest')" not in rendered
    assert 'id="latest"' in rendered


def test_the_daily_shuffle_no_longer_carries_a_promise_line(catalog_factory, metadata):
    """It was printed twice — once under the control, once in the footer, where it had
    nothing to do with the language links beside it."""
    rendered = render_home(
        [catalog_factory(0)], locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25)
    )
    assert "不画像" not in rendered
    assert "每日随机" in rendered


def test_the_footer_is_one_placeholder_byline(catalog_factory, metadata):
    """The method blurb came out; the stamp holds the corner until
    the real site facts are written, and language stays with the globe that owns it."""
    rendered = render_home(
        [catalog_factory(0)], locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25)
    )
    footer = rendered.split("<footer>", 1)[1].split("</footer>", 1)[0]
    assert "简体中文" not in footer and "English" not in footer
    assert "方法" not in footer and "Method" not in footer
    assert 'by rwen @ <time datetime="2026-08-25">' in footer
    # The producer version that used to follow the bar is now the GitHub mark, linking
    # to the same placeholder repository URL the suggest modal offers; the version
    # itself survives only as a data attribute.
    assert 'data-producer="publish-0.' in footer
    assert "publish-0." not in footer.split("data-producer=", 1)[1].split('"', 2)[2]
    assert '<a class="fgit" href="https://github.com/wenruofeng/newsab"' in footer
    assert 'aria-label="GitHub"' in footer and "<svg" in footer
    assert "justify-content:center" in rendered.split(".foot{", 1)[1].split("}", 1)[0]
    # the chooser itself is still exactly where it was
    assert 'id="site-language-menu"' in rendered


def test_the_home_page_can_get_back_to_the_top_like_a_topic_page(catalog_factory, metadata):
    rendered = render_home(
        [catalog_factory(0)], locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25)
    )
    assert 'id="page-top"' in rendered
    assert 'class="top-fab" id="backtotop" href="#page-top"' in rendered
    assert "回到顶部" in rendered
    assert ".js .top-fab:not(.shown)" in rendered


def test_tips_are_the_pages_own_and_never_cost_the_page_its_width(catalog_factory, metadata):
    """A native ``title`` dwells for about a second before it says anything, which reads
    as the page being slow.  The replacement must not be laid out while it is idle."""
    rendered = render_home(
        [catalog_factory(0)], locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25)
    )
    cards = "".join(
        chunk.split("</article>", 1)[0]
        for chunk in rendered.split('<article class="tcard')[1:]
    )
    assert "data-tip=" in cards
    # Not one native tooltip is left on a card.  (Icon-only controls elsewhere keep
    # theirs: there a ``title`` is the hover label of a control with no text at all.)
    assert " title=" not in cards
    assert "[data-tip]::after{content:attr(data-tip);display:none" in rendered
    # the side definition is not lost to a reader who cannot hover
    assert '<span class="vh">虚构甲组样本</span>' in rendered


def test_search_reads_the_cards_and_carries_no_second_catalogue(catalog_factory, metadata):
    """The old page shipped every row twice: once as a card, once as a JSON island."""
    rendered = render_home(
        [catalog_factory(0)], locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25)
    )
    assert "catalog-search-data" not in rendered
    assert 'data-search="' in rendered
    assert "data-site-search" in rendered


def test_english_pivot_words_are_searchable_on_every_other_homepage(catalog_factory, metadata):
    """English is the master every locale was translated from, so a reader on the zh-CN
    homepage who types an English word finds the topic whose card says it in Chinese.
    The English page carries its own words once, not twice."""
    record = catalog_factory(0)
    english = record.model_copy(
        update={
            "locale": "en",
            "title": record.title.model_copy(update={"text": "Pivot Title Uniqueword", "lang": "en"}),
        }
    )
    without = render_home(
        [record], locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25)
    )
    assert "uniqueword" not in without
    with_pivot = render_home(
        [record],
        locale="zh-CN",
        metadata=metadata,
        build_date=date(2026, 8, 25),
        pivot_records={record.publication_id: english},
    )
    haystack = re.search(r'data-search="([^"]*)"', with_pivot).group(1)
    assert "pivot title uniqueword" in haystack
    assert record.title.text.casefold() in haystack
    # the visible card is untouched: English words live only in the search attribute
    assert with_pivot.count("Uniqueword") == 0
    # on the English homepage the pivot row is the card itself, so nothing is doubled
    own = render_home(
        [english],
        locale="en",
        metadata=metadata,
        build_date=date(2026, 8, 25),
        pivot_records={record.publication_id: english},
    )
    own_hay = re.search(r'data-search="([^"]*)"', own).group(1)
    assert own_hay.count("pivot title uniqueword") == 1


def test_every_card_shows_both_answers_and_the_relation_between_them(catalog_factory, metadata):
    record = catalog_factory(0)
    rendered = render_home(
        [record], locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25)
    )
    for side in record.sides:
        assert side.short_label.text in rendered
    assert 'class="tside tside--a"' in rendered
    assert 'class="tside tside--b"' in rendered
    # divergence in the fixture, and the relation is named for a reader who cannot see it
    assert "#i-divergence" in rendered
    assert "分歧" in rendered


def test_counts_are_shown_with_the_denominator_they_came_from(catalog_factory, metadata):
    record = catalog_factory(0)
    angle = record.angles[0].model_copy(update={"counts": {"aa": "7/11", "bb": "4/6"}})
    record = record.model_copy(update={"angles": [angle, *record.angles[1:]]})
    rendered = render_home(
        [record], locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25)
    )
    assert ">7/11<" in rendered
    assert "样本中 11 篇报道有 7 篇给出该答案。" in rendered


def test_whole_catalogue_is_in_the_markup_beyond_the_first_page(catalog_factory, metadata):
    """Progressive reveal is a viewing decision; it must never truncate the document."""
    records = [
        catalog_factory(serial, topic_id=None, published_at=datetime(2026, 8, 1, serial % 24, tzinfo=timezone.utc))
        for serial in range(PAGE_STEP + 4)
    ]
    rendered = render_home(
        records, locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25)
    )
    assert len(_ids("browse", rendered)) == PAGE_STEP + 4
    assert "data-more" in rendered


def test_root_and_relative_url_modes_are_explicit(catalog_factory, metadata):
    record = catalog_factory(0)
    rooted = render_home(
        [record], locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25), url_mode="root"
    )
    relative = render_home(
        [record], locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25), url_mode="relative"
    )
    assert f'href="/zh-CN/topics/{record.topic_id}/"' in rooted
    assert f'href="topics/{record.topic_id}/"' in relative
    assert 'href="../en/"' in relative


def test_catalog_text_is_escaped_in_markup_and_in_the_search_attribute(catalog_factory, metadata):
    record = catalog_factory(0, title='Safe </script><script>alert("x")</script>')
    rendered = render_home([record], locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25))
    assert 'Safe &lt;/script&gt;&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;' in rendered
    assert 'Safe </script><script>alert("x")</script>' not in rendered
    # the same text folded into the card's own search attribute, escaped as an attribute
    assert 'safe &lt;/script&gt;&lt;script&gt;alert(&quot;x&quot;)' in rendered


def test_catalog_category_drift_from_metadata_is_refused(catalog_factory, metadata):
    record = catalog_factory(0)
    changed = record.model_copy(update={"category_ids": ["civic-life"]})
    with pytest.raises(ValueError, match="differ from versioned site metadata"):
        render_home([changed], locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25))


def test_m2_home_declares_canonical_and_real_alternates(catalog_factory, metadata):
    rendered = render_home(
        [catalog_factory(0)],
        locale="zh-CN",
        metadata=metadata,
        build_date=date(2026, 8, 25),
        canonical_url="/zh-CN/",
        alternate_urls={"en": "/en/", "zh-CN": "/zh-CN/"},
    )
    assert '<link rel="canonical" href="/zh-CN/">' in rendered
    assert '<link rel="alternate" hreflang="en" href="/en/">' in rendered
    assert '<link rel="alternate" hreflang="zh-CN" href="/zh-CN/">' in rendered
    assert "@media (pointer:coarse)" in rendered


def test_home_carries_the_site_level_controls(catalog_factory, metadata):
    """The home page is where a reader first meets the site, so the choice starts here.

    It shares the topic pages' preference key and their control shape, so one choice
    holds across the whole site and the corner row looks like one site, not two.
    """
    rendered = render_home(
        [catalog_factory(0)], locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25)
    )
    assert 'id="themebtn"' in rendered
    assert 'class="toolbtn"' in rendered
    assert "newsab.prefs" in rendered
    # the locale chooser names each language in that language
    assert 'id="langbtn"' in rendered
    assert ">English<" in rendered and ">中文（简体）<" in rendered
    # Three theme states: bare light palette, a guarded system default, an explicit choice.
    assert ':root:not([data-theme="light"])' in rendered
    assert ':root[data-theme="dark"]' in rendered
    # The stored choice is applied in <head>, before the first paint.
    assert rendered.index("newsab.prefs") < rendered.index("<body>")
    assert '<symbol id="i-moon"' in rendered and '<symbol id="i-sun"' in rendered


def test_language_menu_is_locale_code_alphabetical_like_the_topic_page(catalog_factory):
    """Chrome audit: the home page's language menu used to follow the
    halo's ring order (zh-CN, en, ru, fr, ko, hi, es, ja, ar); the topic page's own
    switcher (``page.py``'s ``_site_tools``) has always sorted by locale code. One
    control, two page kinds, so the reader must see the same order in both.
    """
    real_metadata = load_site_metadata(default_metadata_path())
    rendered = render_home(
        [catalog_factory(0)], locale="en", metadata=real_metadata, build_date=date(2026, 8, 25)
    )
    nav = rendered.split('id="site-language-menu"', 1)[1].split("</nav>", 1)[0]
    codes = re.findall(r'hreflang="([^"]+)"', nav)
    assert codes == sorted(codes)
    assert codes == ["ar", "en", "es", "fr", "hi", "ja", "ko", "ru", "zh-CN"]


def test_zh_cn_endonym_matches_the_topic_page_switcher(catalog_factory, metadata):
    """Chrome audit: the topic page's locale switcher used to say
    "简体中文" (``HALO_LOCALES``' own zh-CN endonym) while the home page said
    "中文（简体）" (a hand-typed duplicate in ``site_strings``). Both now read the one
    ``HALO_LOCALES`` entry, so "简体中文" can never resurface here.
    """
    rendered = render_home(
        [catalog_factory(0)], locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25)
    )
    assert ">中文（简体）<" in rendered
    assert "简体中文" not in rendered


def test_home_only_suggestion_entrance_precedes_about_and_explains_both_paths(
    catalog_factory, metadata
):
    rendered = render_home(
        [catalog_factory(0)], locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25)
    )
    from newsab_publish.identity import site_identity

    if site_identity().domain_label != "news-ab.com":
        assert 'id="suggestbtn"' not in rendered
        return
    assert 'id="suggestbtn"' in rendered
    assert rendered.index('id="suggestbtn"') < rendered.index('id="aboutbtn"')
    assert 'id="suggest-modal"' in rendered
    assert "不保证采纳、处理或回复" in rendered
    assert "自己动手" in rendered
    assert 'href="https://github.com/wenruofeng/newsab"' in rendered
    assert "data-show-submission" in rendered
    assert "data-submission-form" in rendered
    assert "上传投稿" in rendered
    # Both path buttons toggle between the two form boxes in either order: neither is
    # ever disabled once its form has loaded.
    assert 'data-show-suggestion aria-expanded="false" aria-controls="suggest-formbox-idea"' in rendered
    assert 'data-show-submission aria-expanded="false" aria-controls="suggest-formbox-upload"' in rendered
    assert "show.disabled" not in rendered and "showUpload.disabled" not in rendered
    assert "reveal(box,uploadBox)" in rendered and "reveal(uploadBox,box)" in rendered


def test_a_neutral_identity_homepage_carries_no_official_brand_art(
    catalog_factory, metadata, monkeypatch
):
    """A public-toolkit build must not open on News A/B's masthead —
    no A/B lockup, no nine-script halo, no rotating sayings — only its own plain name."""
    import newsab_publish.home as home_mod

    monkeypatch.setattr(home_mod, "official_site", lambda: False)
    rendered = render_home(
        [catalog_factory(0)], locale="zh-CN", metadata=metadata, build_date=date(2026, 8, 25)
    )
    body = rendered.split("<body>", 1)[1]
    assert 'class="masthead masthead--plain"' in body
    assert 'id="page-top"' in body
    assert '<h1 class="plainmark">' in body
    assert "wm-halo" not in body and "wm-ab" not in body
    assert "data-taglines" not in body


def test_suggestion_form_is_closed_schema_turnstile_protected_and_fail_closed(
    catalog_factory, metadata
):
    rendered = render_home(
        [catalog_factory(0)], locale="en", metadata=metadata, build_date=date(2026, 8, 25)
    )
    from newsab_publish.identity import site_identity

    if site_identity().domain_label != "news-ab.com":
        assert 'id="suggest-modal"' not in rendered
        return
    for field in (
        "topic", "group_a", "group_b", "rough_window",
        "start_urls", "attribution", "name", "contact", "website", "accepted",
    ):
        assert f'name="{field}"' in rendered
    # the retired questions must stay retired
    assert 'name="why"' not in rendered
    assert 'name="source_languages"' not in rendered
    # only topic and the two media groups are required, marked with the red asterisk
    suggestion_form = rendered.split("data-suggestion-form", 1)[1].split("</form>", 1)[0]
    assert suggestion_form.count('class="sf-req"') == 3
    assert "https://intake.news-ab.com/v1/config" not in rendered  # assembled safely in JS
    assert "ORIGIN+'/v1/config'" in rendered
    assert "ORIGIN+'/v1/suggestions'" in rendered
    assert "turnstile/v0/api.js?render=explicit" in rendered
    assert "Idempotency-Key" in rendered
    assert "pendingKey" in rendered
    # The modal carries no privacy summary of its own; the consent sentence links
    # the full notice, so the two texts cannot drift apart.
    assert "contact details stay out of Git" not in rendered
    assert 'href="/en/legal/privacy/" target="_blank" rel="noopener noreferrer">Privacy and Submission Notice</a>' in rendered
    assert 'class="suggest-privacy"' not in rendered


def test_invited_submission_upload_is_direct_to_presigned_r2_and_fail_closed(
    catalog_factory, metadata
):
    rendered = render_home(
        [catalog_factory(0)], locale="en", metadata=metadata, build_date=date(2026, 8, 25)
    )
    from newsab_publish.identity import site_identity

    if site_identity().domain_label != "news-ab.com":
        assert "data-submission-form" not in rendered
        return
    assert 'name="invite_token"' in rendered
    assert 'name="archive" type="file"' in rendered
    # The control credential is issued by the worker on a create upload and shown once
    # on the done card; the field to *type* one exists only for a withdraw/revise
    # archive, so it ships hidden and the JS reveals it from the envelope's operation.
    assert '<label data-control-field hidden>' in rendered
    assert 'name="control_credential"' in rendered
    assert "envelope.operation!=='create'" in rendered
    assert "control_credential:controlField.hidden?null:data.get('control_credential')" in rendered
    assert "new DecompressionStream('gzip')" in rendered
    assert "crypto.subtle.digest('SHA-256'" in rendered
    assert "ORIGIN+'/v1/submission-slots'" in rendered
    assert "fetch(slot.upload_url,{method:'PUT'" in rendered
    assert "ORIGIN+'/v1/submissions/'" in rendered
    assert "complete.control_credential" in rendered
    assert "config.submissions_open" in rendered
    assert "declared_archive_sha256:'sha256:'+sha" in rendered
    assert "page_run_id:env.page_run_id" in rendered
    assert "source_statement:env.source_statement" in rendered
    assert "if(slot.status!=='received')" in rendered


def test_the_card_footer_wraps_so_it_cannot_widen_the_card(catalog_factory, metadata):
    """The footer holds two runs that refuse to break — the counts and the read link.
    In English they add up to more than a 20rem column, and on one line their sum became
    the card's minimum width: every row of the card was pushed out past its own border,
    at every desktop width, and the grid scrolled sideways on a phone.  Wrapped, the
    card's floor is the wider of the two runs instead of their sum."""
    # the phone rules ride in the M2 sheet, which only a canonical page carries
    rendered = render_home(
        [catalog_factory(0)],
        locale="en",
        metadata=metadata,
        build_date=date(2026, 8, 25),
        canonical_url="/en/",
        alternate_urls={"en": "/en/", "zh-CN": "/zh-CN/"},
    )
    assert ".tf{display:flex;flex-wrap:wrap;" in rendered
    # the two runs still each keep their own line unbroken; only their pairing gives way
    assert ".tf .read{color:var(--accent);font-weight:600;white-space:nowrap}" in rendered
    assert ".tf .qn>span{white-space:nowrap}" in rendered
    # one card per row leaves the kicker nothing to align with, so it may wrap too
    assert ".tk{flex-wrap:wrap}" in rendered


def test_rtl_direction_and_masthead_split_stay_unmirrored(catalog_factory, metadata):
    """ar carries dir="rtl"; the A/B masthead split and each card's mini answer
    pair keep the same forced-ltr treatment as the topic page's own `.duo`.

    Also a regression guard for a real bug this task found: the skip-to-content link
    used to hide itself with `left:-9999px`.  That is direction-blind — in a `dir="rtl"`
    document a huge negative x-offset extends the document's *scrollable* overflow
    (RTL scrolls toward negative x) instead of merely leaving the viewport the way it
    does under ltr, so on a real browser this turned a hidden link into an ~11,000px
    wide page.  No property value in the stylesheet may use that trick again.
    """
    # The fixture metadata's own two categories carry only en/zh-CN labels (the halo's
    # other seven languages are in the real site_metadata.v1.json, not in this synthetic
    # fixture), so this borrows the real one and keeps its own record/category pairing
    # irrelevant: `_explorer` only needs every real category to resolve a label.
    real_metadata = load_site_metadata(default_metadata_path())
    ar_metadata = real_metadata.model_copy(update={"locales": [*real_metadata.locales, "ar"]})
    rendered = render_home([catalog_factory(0)], locale="ar", metadata=ar_metadata, build_date=date(2026, 8, 25))
    assert '<html lang="ar" dir="rtl"' in rendered
    assert '[dir="rtl"] .wm-ab,' in rendered and '[dir="rtl"] .tduo{direction:ltr}' in rendered
    assert "left:-9999px" not in rendered
    en_rendered = render_home([catalog_factory(0)], locale="en", metadata=metadata, build_date=date(2026, 8, 25))
    assert '<html lang="en" dir="ltr"' in en_rendered
    assert "left:-9999px" not in en_rendered


def test_grid_card_never_widens_past_its_track(catalog_factory, metadata):
    """A grid card's own column has to be stated, and the kicker has to have
    something that gives.

    Under `@supports (grid-template-rows:subgrid)` each card becomes its own grid.  Its
    single implicit column was left at `auto`, whose floor is the content's *min-content*
    width — and the kicker's min-content width is unbreakable: a category label beside a
    `white-space:nowrap` sample window.  On `/ru/` ("Международные отношения" is 203px
    where "Diplomacy" is 83px) that floor came out 10-43px wider than the card the grid
    had already sized, so the row printed out through the card's own border while the
    page width stayed correct and no page-level overflow check saw it.

    Both halves are load-bearing: `minmax(0,1fr)` pins the card to its track, and the
    category — the one part of the row that survives being cut short — must be able to
    shrink inside it while the window keeps its full width.  The stylesheet is the same
    in every language, so the render locale below is immaterial (the fixture metadata
    carries no `ru`); the browser-side proof is `web-gate`'s per-card containment check.
    """
    rendered = render_home(
        [catalog_factory(0)], locale="en", metadata=metadata, build_date=date(2026, 8, 25)
    )
    assert ".grid>.tcard{display:grid;grid-template-columns:minmax(0,1fr);" in rendered
    assert ".tk .cat{flex:0 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;" in rendered
    assert ".tk .win{flex:none;" in rendered
