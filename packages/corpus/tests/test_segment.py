"""Segmentation is the foundation of every sentence ID, so it is tested tightly."""

import pytest

from newsab_corpus.segment import (
    SPLITTER_VERSION,
    normalize_text,
    segment,
    split_paragraphs,
    split_sentences,
)


def test_chinese_terminals_and_closing_quotes():
    text = "新规改为固定停留期限。该规定于九月生效！他们说：“这太突然了。”"
    assert split_sentences(text, "zh-CN") == [
        "新规改为固定停留期限。",
        "该规定于九月生效！",
        "他们说：“这太突然了。”",
    ]


def test_chinese_ellipsis_is_one_terminal():
    assert split_sentences("原有规划被打乱……他们很担心。", "zh-CN") == [
        "原有规划被打乱……",
        "他们很担心。",
    ]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("The U.S. Dept. of State spoke. Dr. Smith disagreed.", 2),
        ("It takes effect Sept. 15, 2026.", 1),
        ("More than 3.5 percent were affected. That is a lot.", 2),
        ('"It is abrupt," she said. He agreed.', 2),
    ],
)
def test_english_abbreviations_do_not_split(text, expected):
    assert len(split_sentences(text, "en")) == expected


def test_unknown_language_uses_the_fallback_and_says_so():
    result = segment("Kebijakan itu disajikan. Ini kedua.", "id")
    assert result.used_fallback
    assert result.sentence_count == 2

    known = segment("这是一句。这是第二句。", "zh-CN")
    assert not known.used_fallback


def test_paragraphs_split_on_blank_lines_and_join_soft_wraps():
    assert split_paragraphs("one\nstill one\n\ntwo") == ["one still one", "two"]


def test_segmentation_is_deterministic():
    text = "第一句。第二句！第三句？"
    assert segment(text, "zh-CN") == segment(text, "zh-CN")
    assert segment(text, "zh-CN").splitter_version == SPLITTER_VERSION


def test_normalisation_does_not_touch_punctuation():
    """§2.5 promises Ctrl-F works on the original page, so we must not 'tidy' quotes."""
    text = '“智能”引号 and "straight" ones stay as-is。'
    (sentence,) = split_sentences(text, "zh-CN")
    assert "“智能”" in sentence and '"straight"' in sentence


# --- JSON-LD bodies mark paragraphs with a single newline --------------------------------
# Standard 2013 in a real corpus was captured from a JSON-LD `articleBody`, whose
# paragraph breaks are lone "\n".  Read as blank-line-separated, the whole article became
# one paragraph: sentence anchors stayed correct, but "which paragraph" stopped meaning
# anything.  The collector declares the convention; the builder never guesses.


def test_single_newline_bodies_keep_their_paragraph_boundaries():
    body = "First graf runs on.\nSecond graf.\nThird graf."
    assert split_paragraphs(body, "single_newline") == [
        "First graf runs on.",
        "Second graf.",
        "Third graf.",
    ]
    # …and the default reading is what produced the bug: one paragraph.
    assert split_paragraphs(body) == ["First graf runs on. Second graf. Third graf."]


def test_single_newline_bodies_tolerate_blank_lines_too():
    """A JSON-LD body that also carries blank lines must not sprout empty paragraphs."""
    assert split_paragraphs("One.\n\nTwo.\n \nThree.", "single_newline") == [
        "One.",
        "Two.",
        "Three.",
    ]


def test_paragraph_break_reaches_sentence_ids():
    body = "Kwanza ni sentensi. Bado kwanza.\nPili ni sentensi."
    result = segment(body, "sw", "single_newline")
    assert [len(p) for p in result.paragraphs] == [2, 1]
    assert [len(p) for p in segment(body, "sw").paragraphs] == [3]


def test_an_unknown_paragraph_break_is_refused_not_guessed():
    with pytest.raises(ValueError, match="paragraph_break"):
        split_paragraphs("One.\nTwo.", "sometimes")


def test_japanese_splits_on_cjk_terminals_without_a_following_space():
    """Japanese prose puts no space after 。 — the conservative fallback never split it.

    Regression for split-0.4.0: the first Japanese corpus came out with one "sentence"
    per paragraph, which makes every anchor a whole paragraph.
    """
    text = "政府観光局は19日、7月の訪日客数を発表した。中国からの旅行者は8か月連続で減少した。"
    assert split_sentences(text, "ja") == [
        "政府観光局は19日、7月の訪日客数を発表した。",
        "中国からの旅行者は8か月連続で減少した。",
    ]


def test_japanese_keeps_a_closing_bracket_with_its_sentence():
    text = "担当者は「厳しい状況が続く」と話した。今後の見通しは不透明だ。"
    assert split_sentences(text, "ja") == [
        "担当者は「厳しい状況が続く」と話した。",
        "今後の見通しは不透明だ。",
    ]


def test_japanese_is_no_longer_reported_as_a_fallback_language():
    result = segment("7月の訪日客は344万人だった。前年より増えた。", "ja")
    assert result.used_fallback is False
    assert result.paragraphs == [
        ["7月の訪日客は344万人だった。", "前年より増えた。"]
    ]


def test_korean_splits_sentences_with_quote_closers():
    text = '정부 관계자는 "합의에 이르지 못했다."라고 밝혔다. 유가족은 별도 행사에 참석했다.'
    assert split_sentences(text, "ko") == [
        '정부 관계자는 "합의에 이르지 못했다."라고 밝혔다.',
        "유가족은 별도 행사에 참석했다.",
    ]


def test_korean_keeps_decimal_points_inside_a_sentence():
    assert split_sentences("응답률은 3.5%였다. 전년보다 낮았다.", "ko-KR") == [
        "응답률은 3.5%였다.",
        "전년보다 낮았다.",
    ]


def test_korean_is_no_longer_reported_as_a_fallback_language():
    result = segment("추도식이 열렸다. 한국 측은 별도 행사를 열었다.", "ko")
    assert result.used_fallback is False
    assert result.paragraphs == [
        ["추도식이 열렸다.", "한국 측은 별도 행사를 열었다."]
    ]


def test_indonesian_still_uses_the_fallback_and_says_so():
    """The fallback is right for a space-after-period language; only CJK needed the fix."""
    result = segment("Kunjungan wisatawan turun. Pemerintah menanggapi.", "id")
    assert result.used_fallback is True
    assert result.paragraphs == [
        ["Kunjungan wisatawan turun.", "Pemerintah menanggapi."]
    ]


# --- German and Turkish (split-0.6.0) ----------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        # The ordinal-date period is the failure the fallback made on every German article.
        ("Der Antrag wurde am 24. April 2024 veröffentlicht.", 1),
        ("Im 20. Jahrhundert kam das Gericht nach Berlin. Das war so.", 2),
        ("Die Branche setzt rund 2.400 Millionen Euro um.", 1),
        ("Das sind ca. 2,4 Mrd. Euro, d. h. sehr viel.", 1),
        ("Dr. Müller sprach mit Prof. Schmidt. Beide widersprachen.", 2),
        # Attribution after a closing quote must not become its own sentence.
        ('"Der Döner gehört zu Deutschland!" sagte Özdemir. Die Branche jubelte.', 2),
        ("Der Streit ist beendet. Der Antrag wurde zurückgezogen.", 2),
    ],
)
def test_german_periods_that_are_not_sentence_ends(text, expected):
    assert len(split_sentences(text, "de")) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Bu, 2. kez oldu.", 1),
        ("Sektörün cirosu 2.400 milyon avro.", 1),
        ("Prof. Dr. Ahmet Yılmaz konuyu değerlendirdi. Sonra sustu.", 2),
        ('UDOFED Başkanı, "Döner Türk mutfağıdır." dedi. Almanya itiraz etti.', 2),
        ("Başvuru yayımlandı. Almanya itiraz etti. Süreç durdu.", 3),
    ],
)
def test_turkish_periods_that_are_not_sentence_ends(text, expected):
    assert len(split_sentences(text, "tr")) == expected


def test_german_and_turkish_are_no_longer_fallback_languages():
    for lang in ("de", "tr"):
        result = segment("Erster Satz. Zweiter Satz.", lang)
        assert not result.used_fallback, lang
        assert result.splitter_version == SPLITTER_VERSION


def test_a_german_year_still_ends_a_sentence():
    # Only one- and two-digit numbers are read as ordinals; a four-digit year is not.
    assert split_sentences("Das geschah im Jahr 2024. Danach war Ruhe.", "de") == [
        "Das geschah im Jahr 2024.",
        "Danach war Ruhe.",
    ]


# --- French and Mongolian (split-0.7.0) --------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        # "M." on second reference is the abbreviation French copy cannot do without.
        ("M. Macron a salué l'accord. Orano investira à Zuuvch-Ovoo.", 2),
        ("Voir p. ex. le rapport de l'AIEA. Il date de 2024.", 2),
        ("L'accord a été signé av. J.-C. par personne, évidemment.", 1),
        # Attribution running on after a closing guillemet.
        ("« C'est un accord historique », a-t-il dit. Paris s'en félicite.", 2),
        ("Le gisement contient 90 000 tonnes. La production démarrera en 2028.", 2),
    ],
)
def test_french_periods_that_are_not_sentence_ends(text, expected):
    assert len(split_sentences(text, "fr")) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        # A personal initial precedes almost every Mongolian surname in news prose.
        ("Л. Оюун-Эрдэнэ хэлэв. УИХ хэлэлцэнэ.", 2),
        ("Ц.Батсайхан гэж хэлэв. Тэр УИХ-ын гишүүн.", 2),
        ("Хөрөнгө оруулалт 1.6 тэрбум ам.доллар болно.", 1),
        ('"Зөөвч-Овоо" ордыг ашиглана." гэж мэдэгдэв. Ард түмэн эсэргүүцэв.', 2),
    ],
)
def test_mongolian_periods_that_are_not_sentence_ends(text, expected):
    assert len(split_sentences(text, "mn")) == expected


@pytest.mark.parametrize("lang", ["fr", "mn"])
def test_a_small_number_still_ends_a_french_or_mongolian_sentence(lang):
    """The German ordinal clause is off for these two: they write 1er / 1-р, not "1."."""
    texts = {
        "fr": ("La production doit démarrer dans 4 ans. Elle atteindra 2 500 tonnes.", 2),
        "mn": ("Гэрээ 4 жил үргэлжилнэ. Дараа нь олборлолт эхэлнэ.", 2),
    }
    text, expected = texts[lang]
    assert len(split_sentences(text, lang)) == expected


def test_french_and_mongolian_are_no_longer_fallback_languages():
    samples = {"fr": "Première phrase. Deuxième phrase.", "mn": "Эхний өгүүлбэр. Хоёр дахь нь."}
    for lang, text in samples.items():
        result = segment(text, lang)
        assert not result.used_fallback, lang
        assert result.splitter_version == SPLITTER_VERSION


# --- Hindi and Urdu (split-0.8.0) --------------------------------------------------------


def test_hindi_splits_on_the_danda():
    # The failure split-0.8.0 fixes: the fallback knows no danda, so this was one sentence.
    assert split_sentences(
        "भारत ने संधि को स्थगित कर दिया। पाकिस्तान ने विरोध किया। विश्व बैंक चुप रहा।", "hi"
    ) == [
        "भारत ने संधि को स्थगित कर दिया।",
        "पाकिस्तान ने विरोध किया।",
        "विश्व बैंक चुप रहा।",
    ]


def test_hindi_danda_needs_no_following_space():
    # Like the Japanese "。": a danda ends the sentence even when no whitespace follows.
    assert split_sentences("संधि स्थगित है।पाकिस्तान ने विरोध किया।", "hi") == [
        "संधि स्थगित है।",
        "पाकिस्तान ने विरोध किया।",
    ]


@pytest.mark.parametrize(
    "text,expected",
    [
        # Some Hindi outlets end sentences with the ASCII period instead of the danda.
        ("भारत ने संधि स्थगित की. पाकिस्तान ने विरोध किया.", 2),
        # Honorific abbreviation and Devanagari name initials stay internal.
        ("डॉ. सिंह ने बयान दिया। जांच जारी है।", 2),
        ("जे. पी. नड्डा ने कहा कि संधि स्थगित रहेगी। विपक्ष ने विरोध किया।", 2),
        # A decimal point stays internal.
        ("नदी का प्रवाह 2.5 प्रतिशत घटा। किसान चिंतित हैं।", 2),
    ],
)
def test_hindi_periods_that_are_not_sentence_ends(text, expected):
    assert len(split_sentences(text, "hi")) == expected


def test_urdu_splits_on_the_urdu_full_stop():
    assert split_sentences(
        "بھارت نے معاہدہ معطل کر دیا۔ پاکستان نے احتجاج کیا۔ عالمی بینک خاموش رہا۔", "ur"
    ) == [
        "بھارت نے معاہدہ معطل کر دیا۔",
        "پاکستان نے احتجاج کیا۔",
        "عالمی بینک خاموش رہا۔",
    ]


def test_urdu_question_mark_and_missing_space_still_split():
    assert split_sentences("کیا معاہدہ بحال ہوگا؟کسی کو معلوم نہیں۔", "ur") == [
        "کیا معاہدہ بحال ہوگا؟",
        "کسی کو معلوم نہیں۔",
    ]


def test_urdu_keeps_a_closing_quote_with_its_sentence():
    sentences = split_sentences('انہوں نے کہا "معاہدہ بحال کریں گے۔" مذاکرات جاری ہیں۔', "ur")
    assert sentences[0].endswith('۔"')
    assert len(sentences) == 2


def test_hindi_and_urdu_are_no_longer_fallback_languages():
    samples = {"hi": "पहला वाक्य। दूसरा वाक्य।", "ur": "پہلا جملہ۔ دوسرا جملہ۔"}
    for lang, text in samples.items():
        result = segment(text, lang)
        assert not result.used_fallback, lang
        assert result.splitter_version == SPLITTER_VERSION


def test_the_narrow_no_break_space_is_folded_like_the_no_break_space():
    """French copy writes a narrow no-break space before ? ! ; : and inside guillemets."""
    assert normalize_text("Pourquoi la Mongolie ?") == "Pourquoi la Mongolie ?"
