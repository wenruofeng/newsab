"""G-2a — navigation/copyright residue rules.

Every fixture line below is a real shape from the Phase 0 id-side corpus.  Since
split-0.2.0 the rules ARE applied by ``build_paragraphs`` to
every staged body before segmentation; the enabling shipped, as G-2a requires, together
with the SPLITTER_VERSION bump and the Q×A re-annotation.
"""

import pytest

from datetime import date

from newsab_corpus import RESIDUE_RULES_VERSION, SPLITTER_VERSION, strip_residue
from newsab_corpus.staging import StagingArticle, build_paragraphs


def test_baca_juga_lines_are_dropped():
    body = (
        "Pemerintah menetapkan kuota produksi nikel.\n\n"
        "Baca juga: Airlangga-Luhut Sebut Kenaikan Harga CPO-Nikel Jadi Kompensasi Minyak Mahal\n\n"
        "Kebijakan itu berlaku mulai tahun depan."
    )
    result = strip_residue(body)
    assert "Baca juga" not in result.body
    assert result.removed == [
        (
            "baca_juga",
            "Baca juga: Airlangga-Luhut Sebut Kenaikan Harga CPO-Nikel Jadi Kompensasi Minyak Mahal",
        )
    ]
    # The surviving body keeps its paragraph structure.
    assert result.body.split("\n\n") == [
        "Pemerintah menetapkan kuota produksi nikel.",
        "Kebijakan itu berlaku mulai tahun depan.",
    ]


def test_antara_footer_both_spellings():
    # Both real variants: glued "SavitriEditor" with "Copyright ©" and the spaced
    # "Pewarta :" with "COPYRIGHT ©".
    for footer in (
        "Pewarta: Putu Indah SavitriEditor: Agus Salim Copyright © ANTARA 2026",
        "Pewarta : Putu Indah Savitri Editor: Faidin COPYRIGHT © ANTARA 2026",
    ):
        result = strip_residue(f"Harga nikel stabil.\n\n{footer}")
        assert result.body == "Harga nikel stabil."
        assert result.removed[0][0] == "antara_footer"


def test_gambas_placeholder_and_scroll_prompt():
    body = (
        "Perusahaan menghentikan operasi.\n\n"
        "[Gambas:Video 20detik]\n\n"
        "Scroll ke bawah untuk melanjutkan membaca\n\n"
        "Produksi turun tiga persen."
    )
    result = strip_residue(body)
    assert result.body.split("\n\n") == [
        "Perusahaan menghentikan operasi.",
        "Produksi turun tiga persen.",
    ]
    assert [rule for rule, _ in result.removed] == ["gambas_placeholder", "scroll_prompt"]


def test_tempo_tail_byline_and_contributor():
    body = (
        "Perusahaan menyetop operasi karena izin belum terbit.\n\n"
        "Rani Wijaya berkontribusi dalam penulisan artikel ini.\n\n"
        "Dewi Pratama"
    )
    result = strip_residue(body)
    assert result.body == "Perusahaan menyetop operasi karena izin belum terbit."
    assert {rule for rule, _ in result.removed} == {"tempo_contributor", "tail_byline"}


def test_a_name_in_the_middle_of_the_body_is_not_a_byline():
    body = (
        "Direktur utama menolak berkomentar.\n\n"
        "Dewi Pratama\n\n"
        "Perusahaan tetap beroperasi seperti biasa."
    )
    result = strip_residue(body)
    # Only the article *tail* is trusted for byline shapes; mid-body stays.
    assert "Dewi Pratama" in result.body
    assert result.removed == []


def test_a_sentence_ending_tail_line_is_not_a_byline():
    body = "Produksi naik.\n\nAktif sebagai anggota Aliansi Jurnalis Independen."
    result = strip_residue(body)
    assert result.body == body
    assert result.removed == []


def test_clean_body_passes_through_unchanged():
    body = "第一段。\n\n第二段。"
    assert strip_residue(body) == (body, [])
    assert RESIDUE_RULES_VERSION == "strip-0.4.0"
    assert SPLITTER_VERSION == "split-0.9.0"


# --- inline page-control residue --------------------------------------------------------
# Real shape from a real corpus: CN_42baf108:P13:S04 ended with a leaked CMS call,
# glued to the last real sentence of the article.  A line rule cannot fix this — dropping
# the line would drop the reporting — so the rule cuts the call out and keeps the line.


def test_a_leaked_page_control_call_is_cut_out_of_its_line():
    body = (
        "中国大使馆正在为姆瓦玛卡·沙里夫争取奖学金。今年9月，她就将如愿来中国上大学。"
        "pageTop(gb/longhoo/news2004/njnews/city/index.html,都市);"
    )
    result = strip_residue(body)
    assert result.body == (
        "中国大使馆正在为姆瓦玛卡·沙里夫争取奖学金。今年9月，她就将如愿来中国上大学。"
    )
    assert result.removed == [
        ("page_control_call", "pageTop(gb/longhoo/news2004/njnews/city/index.html,都市);")
    ]


def test_the_rule_matches_the_shape_not_the_function_name():
    """The next CMS will name it something else and leak the same shape."""
    body = "Harga nikel naik.\n\nshowRelated(/news/2026/kuota.jsp,Ekonomi); Produksi turun."
    result = strip_residue(body)
    assert result.body == "Harga nikel naik.\n\nProduksi turun."
    assert result.removed == [("page_control_call", "showRelated(/news/2026/kuota.jsp,Ekonomi);")]


def test_a_line_that_is_only_a_page_control_call_disappears_entirely():
    body = "第一段。\n\npageTop(gb/longhoo/index.html,都市);\n\n第二段。"
    result = strip_residue(body)
    assert result.body == "第一段。\n\n第二段。"
    assert [rule for rule, _ in result.removed] == ["page_control_call"]


def test_prose_with_parentheses_is_not_residue():
    """The rule needs a page filename inside the parentheses, which prose does not have."""
    for body in (
        "研究显示（见图1），产量下降。",
        "The report (published Aug. 3) says output fell.",
        "Pemerintah (Kementerian ESDM) menetapkan kuota.",
        "他提到了 file(name) 这个概念。",
    ):
        assert strip_residue(body) == (body, []), body


def test_build_paragraphs_applies_stripping_and_reports_it():
    staged = StagingArticle(
        group_id="id",
        source_id="detik_id",
        url="https://finance.detik.com/example",
        title="Kuota nikel ditetapkan",
        publish_date=date(2026, 5, 1),
        lang="id",
        body=(
            "Pemerintah menetapkan kuota produksi nikel.\n\n"
            "Baca juga: Harga Nikel Naik\n\n"
            "Kebijakan itu berlaku mulai tahun depan."
        ),
    )
    paragraphs, _, removed = build_paragraphs(staged)
    texts = [s.text for p in paragraphs for s in p.sentences]
    assert not any("Baca juga" in t for t in texts)
    assert removed == [("baca_juga", "Baca juga: Harga Nikel Naik")]


def test_paragraph_break_reaches_build_paragraphs():
    """End to end: the staged declaration decides the P numbers, not the builder."""
    jsonld_body = "Mzee alisema hivyo.\nHabari hiyo ilienea.\nSerikali ilijibu."
    common = dict(
        group_id="ea",
        source_id="standard_ke",
        url="https://www.standardmedia.co.ke/article/2000001",
        title="Sharifu",
        publish_date=date(2013, 6, 1),
        lang="sw",
        body=jsonld_body,
    )
    declared, _, _ = build_paragraphs(
        StagingArticle(**common, paragraph_break="single_newline")
    )
    default, _, _ = build_paragraphs(StagingArticle(**common))

    # P00 is the headline block in both; the body is three paragraphs or one.
    assert [len(p.sentences) for p in declared] == [1, 1, 1, 1]
    assert [len(p.sentences) for p in default] == [1, 3]


@pytest.mark.parametrize("paragraph_break,separator", [("blank_line", "\n\n"), ("single_newline", "\n")])
def test_a_missing_standfirst_is_prepended_with_the_declared_paragraph_break(
    paragraph_break, separator
):
    staged = StagingArticle(
        group_id="in",
        source_id="paper_in",
        url="https://example.com/standfirst",
        title="Treaty update",
        subtitle="The court said the treaty remains in force.",
        publish_date=date(2026, 5, 1),
        lang="en",
        body=f"Officials welcomed the ruling.{separator}Talks will continue.",
        paragraph_break=paragraph_break,
    )
    paragraphs, _, _ = build_paragraphs(staged)

    assert [sentence.text for sentence in paragraphs[0].sentences] == [
        "Treaty update",
        "The court said the treaty remains in force.",
    ]
    assert [paragraph.sentences[0].text for paragraph in paragraphs[1:]] == [
        "The court said the treaty remains in force.",
        "Officials welcomed the ruling.",
        "Talks will continue.",
    ]


def test_a_standfirst_already_at_the_body_head_is_not_duplicated():
    standfirst = "The court said the treaty remains in force."
    staged = StagingArticle(
        group_id="in",
        source_id="paper_in",
        url="https://example.com/existing-standfirst",
        title="Treaty update",
        subtitle=standfirst,
        publish_date=date(2026, 5, 1),
        lang="en",
        body=f"{standfirst}\n\nOfficials welcomed the ruling.",
    )
    paragraphs, _, _ = build_paragraphs(staged)
    body_texts = [sentence.text for paragraph in paragraphs[1:] for sentence in paragraph.sentences]
    assert body_texts.count(standfirst) == 1


# --- strip-0.4.0: measured author/comment/related-card tails -----------------------------


@pytest.mark.parametrize(
    "tail,rule",
    [
        (
            "Govt snubs 'misleading' foreign media news on Imran's well-being, prison conditions\n\n"
            "Bilawal Bhutto's wedding buzz takes social media by storm\n\n"
            "Copyright © 2026. Geo Television Network. All Rights Reserved.",
            "geo_related_tail",
        ),
        (
            "APP is Pakistan's government-operated national news agency, headquartered in Islamabad.\n\n"
            "No comments yet.\nBe the first to join the discussion!\n\nA Treaty on the Brink",
            "pakistan_today_author_tail",
        ),
        (
            "Follow the latest breaking news, major developments and agenda-setting stories "
            "from India and around the world with the newsdesk at Hindustan Times.\n\n"
            "The HT News Desk covers politics and business.\n\nRead More",
            "ht_author_tail",
        ),
        (
            "Follow The New Indian Express channel on WhatsApp\n\n"
            "Download the TNIE app to stay with us and follow the latest",
            "tnie_promo_tail",
        ),
    ],
)
def test_measured_tail_blocks_are_cut_from_the_first_furniture_marker(tail, rule):
    body = f"The court issued its award.\n\nPakistan said it would comply.\n\n{tail}"
    result = strip_residue(body)
    assert result.body == "The court issued its award.\n\nPakistan said it would comply."
    assert result.removed
    assert {name for name, _ in result.removed} == {rule}


def test_tail_words_in_reporting_are_not_furniture():
    body = (
        "The spokesperson said there were no comments yet from the other party.\n\n"
        "Officials asked readers to follow the latest breaking news during the emergency.\n\n"
        "The negotiations continued overnight."
    )
    assert strip_residue(body) == (body, [])


def test_a_chinese_reprint_footer_is_dropped():
    """Real shape from guancha.cn, inside the body container rather than the page chrome."""
    body = (
        "该公司负责人强调，外部投资和技术是重要因素。\n\n"
        "本文系观察者网独家稿件，未经授权，不得转载。"
    )
    result = strip_residue(body)
    assert result.body == "该公司负责人强调，外部投资和技术是重要因素。"
    assert [rule for rule, _ in result.removed] == ["cn_reprint_footer"]


def test_reporting_about_a_reprint_dispute_is_not_a_footer():
    """The rule needs the boilerplate's own shape, not the words 转载 or 授权 anywhere."""
    body = "该公司称，已就未经授权使用其技术一事提起诉讼，并要求平台停止转载相关内容。"
    assert strip_residue(body) == (body, [])


def test_standalone_publishing_metadata_lines_are_dropped():
    """Real shapes from guancha.cn and chinanews.com.cn, all inside the body container."""
    body = (
        "对于已经深度参与全球产业链竞争的中国企业来说，供应体系的韧性值得思考。\n\n"
        "来源|心智观察所\n\n禁止转载\n\n【编辑:张三】"
    )
    result = strip_residue(body)
    assert result.body == (
        "对于已经深度参与全球产业链竞争的中国企业来说，供应体系的韧性值得思考。"
    )
    assert sorted({rule for rule, _ in result.removed}) == [
        "cn_editor_credit",
        "cn_reprint_footer",
        "cn_source_credit",
    ]


def test_an_in_sentence_attribution_is_not_a_credit_line():
    """The rules need a line that is *only* metadata; reporting that cites a source stays."""
    for body in (
        "据来源：新华社的报道，该政策将于九月生效。",
        "他说，来源|不明的说法不应被采信。",
    ):
        assert strip_residue(body) == (body, []), body


# --- French in-body recommendation slots and publication stamps --------------------------
# Real shapes from the fr corpus: RFI and La Croix put cross-links and the publication time
# *inside* the body container, so they arrive as body sentences and occupy sentence IDs.


@pytest.mark.parametrize(
    "line,rule",
    [
        ("À lire aussi Uranium: le Français Orano engage «un arbitrage»", "fr_lire_aussi"),
        ("À écouter aussi Mongolie: populations nomades et environnement", "fr_lire_aussi"),
        ("Lire aussi : Orano signe avec la Mongolie", "fr_lire_aussi"),
        ("Sur le même sujet", "fr_lire_aussi"),
        ("Publié le : 17/01/2025 - 18:28", "fr_publish_stamp"),
        ("Modifié le : 07/05/2025 - 00:58", "fr_publish_stamp"),
        ("Les plus lus", "fr_most_read"),
    ],
)
def test_french_residue_lines_are_dropped(line, rule):
    result = strip_residue(f"Orano a signé l'accord.\n\n{line}\n\nLa mine ouvrira en 2028.")
    assert line not in result.body
    assert [r[0] for r in result.removed] == [rule]
    assert "Orano a signé l'accord." in result.body
    assert "La mine ouvrira en 2028." in result.body


def test_french_rules_do_not_eat_prose_that_merely_contains_the_words():
    """The rules are anchored at the start of a line; mid-sentence wording is reporting."""
    body = (
        "Il a dit qu'il fallait lire aussi le rapport de l'AIEA.\n\n"
        "Le texte a été publié le 17 janvier et les plus lus des articles le citent."
    )
    result = strip_residue(body)
    assert result.body == body
    assert result.removed == []


def test_le_monde_metered_wall_marker_is_dropped():
    """The wall talking about the article, not reporting — and the reason it is partial."""
    body = "Orano a signé.\n\nIl vous reste 68.35% de cet article à lire. La suite est réservée aux abonnés."
    result = strip_residue(body)
    assert "Il vous reste" not in result.body
    assert [r[0] for r in result.removed] == ["fr_paywall_marker"]


# --- Mongolian portal furniture ----------------------------------------------------------


@pytest.mark.parametrize(
    "line,rule",
    [
        ("Хэвлэл мэдээллийн байгууллагууд (Телевиз, Радио) манай мэдээллийг", "mn_reuse_notice"),
        ("ба зөвхөн зөвшилцсөн тохиолдолд эх сурвалжийг (ikon.mn) дурдах замаар", "mn_reuse_notice"),
        ("бүрэн ба хэсэгчлэн авч ашиглах хориотой", "mn_reuse_notice"),
        ("Холбоотой мэдээ", "mn_related_rail"),
        ("Бусад мэдээ", "mn_related_rail"),
        ("Анхааруулга", "mn_disclaimer_header"),
        ("|", "punctuation_only"),
        ("«", "punctuation_only"),
        ("— — —", "punctuation_only"),
    ],
)
def test_mongolian_portal_furniture_is_dropped(line, rule):
    result = strip_residue(f"Гэрээнд гарын үсэг зурлаа.\n\n{line}\n\nУран олборлоно.")
    assert line not in result.body
    assert [r[0] for r in result.removed] == [rule]


def test_a_real_mongolian_sentence_survives_the_rail_rules():
    body = "Холбоотой мэдээллийг сайдын хэлсэн үгээс авав.\n\nЭнэ бол шуурхай мэдээ биш юм."
    result = strip_residue(body)
    assert result.body == body
    assert result.removed == []
