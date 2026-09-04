"""The "?" control and its "About this site" modal, shared by home and topic pages.

The control is site chrome, not content: on a topic page both the button and the modal
are injected by the chrome script (``chrome_about_js``) so no approved content document
changes a byte; the home page, which owns its markup, renders the same button and modal
server-side (``about_button_html`` / ``about_modal_html``) and wires them with
``HOME_ABOUT_JS``.  One copy table below feeds both paths.

The zh-CN flow diagram is the authoritative wording: its node texts and edge labels are
the user's own words and must not be reworded here.  The other locales are translations
*of that table* (operator-editable drafts like the rest of the copy) and follow the same
structure.  The diagram is drawn in HTML/CSS (no mermaid at
runtime); its four node kinds take their colours from the site's own design tokens.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from newsab_schema import EXTRA_HALO_LOCALES

from .brand import TRANSPARENT_DARK_ASSET_URL as DARK_LOGO_URL
from .brand import TRANSPARENT_LIGHT_ASSET_URL as LIGHT_LOGO_URL
from .identity import site_identity
from .suggest import TOOLKIT_REPO_URL


_IDENTITY = site_identity()


def _esc(value: str) -> str:
    return html.escape(value)


def _attr(value: str) -> str:
    return html.escape(value, quote=True)


# --------------------------------------------------------------------------------------
# FOUNDER-EDITABLE DRAFT COPY — placeholder wording, meant to be rewritten in place.
# Keys must stay symmetric across locales; the strings are free.
# --------------------------------------------------------------------------------------

_COPY: dict[str, dict] = {
    "en": {
        "button_label": "About this site",
        "title": "About this site",
        "intro": [
            _IDENTITY.about["en"],
            "This is an experimental work. The AI-generated conclusions pass a "
            "strictly supervised automated pipeline and statistical testing, and "
            "every piece of evidence traces back to specific source sentences — yet "
            "errors and omissions remain possible. Before relying on any "
            "conclusion, please verify the original reporting yourself.",
        ],
        "flow_title": "Methodology",
        "flow_note": "The diagram below details the full process from a one-sentence "
        "topic to a published report page. Its design draws on best practices from "
        "comparative journalism, statistics, data visualization, and AI-agent "
        "orchestration.",
        "flow_repo": "The code and documentation are in the {link}.",
        "flow_repo_link": "GitHub repository",
        "legend": {
            "process": "AI Step",
            "data": "data artifact",
            "human": "human touchpoint",
            "code": "code",
        },
        "disclaimer_title": "Please note",
        "disclaimers": [
            "Everything on this site describes only the collected corpus of reports "
            "itself; it is not an endorsement of any side's position.",
            "Collection strictly follows each news site's robots.txt rules and copyright "
            "notices, and this site does not provide the original articles.",
            "Because of the exploratory nature of the collecting AI and the limits "
            "of its internet tools, the sample of reports analyzed is incomplete "
            "and may violate statistical sampling assumptions.",
            "The site is in a test phase: pages, data and features may change at "
            "any time.",
        ],
        "contact_title": "Contact",
        "contact": _IDENTITY.contact["en"],
        "close_label": "Close",
    },
    "zh-CN": {
        "button_label": "关于本站",
        "title": "关于本站",
        "intro": [
            _IDENTITY.about["zh-CN"],
            "这是一个实验性作品。AI 生成的结论虽已经过严格的自动化流程监督、统计方法检验，"
            "且证据均可溯源至具体原句，但仍可能存在错误或遗漏。在采用其结论之前，请务必手动核验原报道。",
        ],
        "flow_title": "方法论",
        "flow_note": "下图展示了「从一句话议题到正式页面上线」的完整流程。"
        "其中的方法设计借鉴了比较新闻学、统计学与数据可视化、以及 AI Agent 编排的最佳实践。",
        "flow_repo": "具体代码和文档见 {link}。",
        "flow_repo_link": "GitHub 仓库",
        "legend": {
            "process": "AI 步骤",
            "data": "数据/产出",
            "human": "人工审核",
            "code": "纯代码",
        },
        "disclaimer_title": "使用须知",
        "disclaimers": [
            "本站所有内容仅描述被采集的报道语料库本身，不代表本站认可任何一方的立场。",
            "报道采集过程严格遵守各新闻网站的 robots.txt 规则和版权声明。本站不提供报道原文。",
            "由于采集 AI 的探索能力与工具有限，报道样本并不完整。可能会违背统计采样假设。",
            "本站仍在测试阶段，页面、数据与功能都可能随时调整。",
        ],
        "contact_title": "联系方式",
        "contact": _IDENTITY.contact["zh-CN"],
        "close_label": "关闭",
    },
}

#: The halo's other seven locales, merged in from versioned package data.  The
#: existing shape-assertion loop below (unchanged) validates them the same way it
#: already validates en/zh-CN, since it simply walks ``_COPY.items()``.  As for en/zh-CN
#: above, the first intro paragraph and the contact line are ``SiteIdentity`` fields, not
#: translated copy: the JSON carries only the site-independent paragraphs, so the file is
#: identity-free and a public clone's neutral identity flows through unchanged.
_i18n_path = Path(__file__).with_name("data") / "about_i18n.v1.json"
_i18n_data = json.loads(_i18n_path.read_text(encoding="utf-8"))
for _lang in EXTRA_HALO_LOCALES:
    _entry = dict(_i18n_data["copy"][_lang])
    _entry["intro"] = [_IDENTITY.about[_lang], *_entry["intro"]]
    _entry["contact"] = _IDENTITY.contact[_lang]
    _COPY[_lang] = _entry

ABOUT_LOCALES: tuple[str, ...] = tuple(_COPY)

_expected = {key: type(value) for key, value in _COPY["en"].items()}
for _locale, _table in _COPY.items():
    if {key: type(value) for key, value in _table.items()} != _expected:
        raise RuntimeError(f"asymmetric about copy for {_locale}")


# --------------------------------------------------------------------------------------
# The flow diagram, one table per locale.  zh-CN is the authoritative wording — do not
# reword it here; en is a translation draft the user edits like the rest of the copy.
# ``(kind, lines, loops, edge_label)``: *kind* is the node's class, *lines* the node text
# split at its <br/>, *loops* the dashed back-edges leaving this node as
# ``(edge label, first line of the target node)``,
# *edge_label* the label on the solid edge to the next node below.  Structure (kinds,
# loop counts, labelled edges) must stay parallel across locales — asserted below.
# --------------------------------------------------------------------------------------

_FlowSteps = tuple[tuple[str, tuple[str, ...], tuple[tuple[str, str], ...], str | None], ...]

_FLOW: dict[str, _FlowSteps] = {
    "zh-CN": (
        ("data", ("一句话任务：", "议题 + A/B 分组 + 时间窗"), (), None),
        ("process", ("1. scope", "撰写详细采集计划"), (), None),
        ("human", ("确认采集范围+批准参考问题", "（触点一）"), (("改", "1. scope"),), None),
        ("process", ("2. collect", "分侧独立采集 + 平衡性检查"), (), None),
        ("data", ("句子化语料 + 独立报道组", "数据集"), (), None),
        (
            "process",
            ("3. annotate", "生成问题集（模板/参考/定制）", "标注回答与否、答案和证据"),
            (),
            None,
        ),
        ("data", ("问题 × 答案标注集",), (), None),
        ("code", ("4. analyze", "统计、回答率比较、", "答案比较、置信区间、排序"), (), None),
        (
            "data",
            ("经统计检验的视角发现：", "共识 / 分歧 / 沉默"),
            (("发现新问题", "3. annotate"), ("某侧某类样本太薄", "2. collect")),
            None,
        ),
        (
            "process",
            ("5. write", "数据新闻撰稿：", "提要 → 视角选择 →", "结论解释 + 句级溯源"),
            (),
            None,
        ),
        ("data", ("页面文案内容", "（英文母版）"), (), None),
        (
            "process",
            ("6. render + localize", "自动渲染建页", "+ 独立多轮评审", "+ 译成审核人语言"),
            (),
            None,
        ),
        ("data", ("成品预览页", "（审核人语言）"), (), None),
        (
            "human",
            ("7. review", "审核内容 + 批准上线", "（触点二）"),
            (("打回迭代：由审核评论定位回具体步骤", "5. write"),),
            "通过",
        ),
        ("code", ("8. publish", "冻结版本，校验，上线", "（并本地化至各阅读语言）"), (), None),
    ),
    "en": (
        ("data", ("One-sentence task:", "topic + A/B grouping + time window"), (), None),
        ("process", ("1. scope", "flesh out the detailed collection plan"), (), None),
        (
            "human",
            ("Confirm the scope + approve reference questions", "(touchpoint one)"),
            (("revise", "1. scope"),),
            None,
        ),
        ("process", ("2. collect", "independent per-side collection + balance checks"), (), None),
        (
            "data",
            ("sentence-segmented corpus +", "independent reporting clusters · data store"),
            (),
            None,
        ),
        (
            "process",
            ("3. annotate", "build the question set (templates/reference/custom)", "annotate: answered/answers/sources"),
            (),
            None,
        ),
        ("data", ("question × answer annotation set",), (), None),
        (
            "code",
            ("4. analyze", "stats, answer-rate comparison,", "answer comparison, confidence intervals, ranking"),
            (),
            None,
        ),
        (
            "data",
            ("statistically tested findings by angle:", "consensus / divergence / silence"),
            (("new questions surface", "3. annotate"), ("a side's sample too thin", "2. collect")),
            None,
        ),
        (
            "process",
            ("5. write", "data-journalism writing:", "summary → angle selection →", "explained conclusions + sentence-level tracing"),
            (),
            None,
        ),
        ("data", ("page copy", "(English master)"), (), None),
        (
            "process",
            ("6. render + localize", "automatic page build/checks", "+ independent judge reviews", "+ localized into the reviewer's language"),
            (),
            None,
        ),
        ("data", ("finished preview page", "(reviewer's language)"), (), None),
        (
            "human",
            ("7. review", "review + approve", "(touchpoint two)"),
            (("sent back: review comments pinpoint the exact step", "5. write"),),
            "approved",
        ),
        ("code", ("8. publish", "freeze the version, verify, go live", "(plus localized into each reading language)"), (), None),
    ),
}

#: The same seven locales' flow-diagram text, merged in from the same JSON file
#: as ``_COPY`` above.  Stage-name node labels (``"1. scope"`` etc.) and every loop's
#: back-edge target text are machinery shared verbatim across every locale already
#: (compare the en/zh-CN tuples above) — the localized data only carries the
#: translatable lines/loop-labels/edge-label, and the loop targets here are always the
#: (fixed, untranslated) first line of the node they point at, exactly as en/zh-CN do.
for _lang in EXTRA_HALO_LOCALES:
    _nodes = []
    for _node in _i18n_data["flow"][_lang]:
        _loops = tuple((_label, _target) for _label, _target in _node["loops"])
        _nodes.append((_node["kind"], tuple(_node["lines"]), _loops, _node["edge_label"]))
    _FLOW[_lang] = tuple(_nodes)

_flow_shape = tuple(
    (kind, len(loops), edge_label is not None)
    for kind, _lines, loops, edge_label in _FLOW["zh-CN"]
)
for _locale, _steps in _FLOW.items():
    if (
        tuple((k, len(l), e is not None) for k, _t, l, e in _steps) != _flow_shape
        or set(_FLOW) != set(_COPY)
    ):
        raise RuntimeError(f"about flow diagram out of step for {_locale}")

#: The ``?`` glyph, drawn in the same outlined stroke as the other tool icons.
_ICON_ABOUT = (
    '<svg viewBox="0 0 20 20" aria-hidden="true" fill="none" stroke="currentColor" '
    'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M6.5 6.9a3.5 3.5 0 1 1 5.45 2.92c-1.23.8-1.95 1.5-1.95 2.98"/>'
    '<circle cx="10" cy="16.1" r=".65" fill="currentColor" stroke="none"/></svg>'
)

_ICON_CLOSE = (
    '<svg viewBox="0 0 20 20" aria-hidden="true" fill="none" stroke="currentColor" '
    'stroke-width="1.6" stroke-linecap="round"><path d="M5.5 5.5l9 9M14.5 5.5l-9 9"/></svg>'
)


def _copy(locale: str) -> dict:
    try:
        return _COPY[locale]
    except KeyError as exc:
        raise ValueError(f"about copy has no locale {locale}") from exc


def about_button_html(locale: str) -> str:
    label = _copy(locale)["button_label"]
    return (
        '<button class="toolbtn" id="aboutbtn" type="button" aria-haspopup="dialog" '
        'aria-expanded="false" aria-controls="about-modal" '
        f'aria-label="{_attr(label)}" title="{_attr(label)}">{_ICON_ABOUT}</button>'
    )


def _repo_sentence(strings: dict) -> str:
    """The one sentence after the flow note that names where the code lives.

    The ``{link}`` slot is filled after escaping, so the anchor is the only markup the
    sentence carries; the URL is the public toolkit repository, the same one the footer
    and the suggest modal point at.
    """
    link = (
        f'<a href="{_attr(TOOLKIT_REPO_URL)}" target="_blank" rel="noopener noreferrer">'
        f'{_esc(strings["flow_repo_link"])}</a>'
    )
    return _esc(strings["flow_repo"]).replace("{link}", link)


def _flow_html(strings: dict, locale: str) -> str:
    steps = _FLOW[locale]
    legend = "".join(
        f'<span class="alg alg--{kind}">{_esc(strings["legend"][kind])}</span>'
        for kind in ("process", "data", "human", "code")
    )
    parts = [f'<p class="about-legend">{legend}</p>', '<div class="about-flow">']
    last = len(steps) - 1
    for index, (kind, lines, loops, edge_label) in enumerate(steps):
        text = "<br>".join(_esc(line) for line in lines)
        parts.append(f'<div class="afnode afnode--{kind}"><span>{text}</span></div>')
        for loop_label, target in loops:
            parts.append(
                '<span class="afloop"><span aria-hidden="true">⟲</span> '
                f"{_esc(loop_label)} → {_esc(target)}</span>"
            )
        if index != last:
            label = (
                f'<span class="afdlab">{_esc(edge_label)}</span>' if edge_label else ""
            )
            parts.append(f'<div class="afdown" aria-hidden="true">{label}</div>')
    parts.append("</div>")
    return "".join(parts)


def about_modal_html(locale: str) -> str:
    strings = _copy(locale)
    intro = "".join(f"<p>{_esc(text)}</p>" for text in strings["intro"])
    disclaimers = "".join(f"<li>{_esc(text)}</li>" for text in strings["disclaimers"])
    return (
        '<div class="about-modal" id="about-modal" role="dialog" aria-modal="true" '
        'aria-labelledby="about-title" hidden>'
        '<div class="about-card" tabindex="-1">'
        f'<button class="about-x" type="button" aria-label="{_attr(strings["close_label"])}" '
        f'title="{_attr(strings["close_label"])}">{_ICON_CLOSE}</button>'
        '<span class="about-logo" aria-hidden="true">'
        f'<img class="about-logo-img about-logo-light" src="{_attr(LIGHT_LOGO_URL)}" alt="" '
        'width="440" height="372">'
        f'<img class="about-logo-img about-logo-dark" src="{_attr(DARK_LOGO_URL)}" alt="" '
        'width="440" height="372"></span>'
        f'<h3 id="about-title">{_esc(strings["title"])}</h3>'
        f'<div class="about-sec">{intro}</div>'
        '<div class="about-sec">'
        f'<h4>{_esc(strings["flow_title"])}</h4>'
        f'<p class="about-note">{_esc(strings["flow_note"])} {_repo_sentence(strings)}</p>'
        f"{_flow_html(strings, locale)}</div>"
        '<div class="about-sec">'
        f'<h4>{_esc(strings["disclaimer_title"])}</h4>'
        f'<ul class="about-dis">{disclaimers}</ul></div>'
        '<div class="about-sec">'
        f'<h4>{_esc(strings["contact_title"])}</h4>'
        f'<p class="about-mail">{_esc(strings["contact"])}</p></div>'
        "</div></div>"
    )


# --------------------------------------------------------------------------------------
# styling — shared verbatim by the home page and the chrome stylesheet.  Both documents
# define the same design tokens (--panel/--rule/--ink/--sans/…), so one block serves.
# --------------------------------------------------------------------------------------

ABOUT_CSS = """
/* ------------------------------------------------------------- about this site
   The "?" beside the home control opens one modal: what the site is, how a page is
   produced (the site's flow chart, drawn in the site's own palette) and the small
   print.  Both the home page and the chrome stylesheet carry this same block. */
.site-tools[data-toolbar]{justify-content:flex-start}
body.about-open{overflow:hidden}
.about-modal{position:fixed;inset:0;z-index:90;display:flex;align-items:center;
  justify-content:center;padding:max(1rem,env(safe-area-inset-top))
  max(1rem,env(safe-area-inset-right)) max(1rem,env(safe-area-inset-bottom))
  max(1rem,env(safe-area-inset-left));background:rgba(10,12,14,.55)}
.about-modal[hidden]{display:none}
.about-card{position:relative;width:min(38rem,100%);max-height:min(88dvh,60rem);
  overflow-y:auto;overscroll-behavior:contain;background:var(--panel);
  border:1px solid var(--rule);border-radius:7px;padding:1.5rem 1.6rem 1.8rem;
  box-shadow:0 18px 60px rgba(0,0,0,.32);outline:none}
.about-x{position:absolute;top:.55rem;right:.6rem;display:flex;align-items:center;
  justify-content:center;width:2.2rem;height:2.2rem;border:0;border-radius:50%;
  background:none;color:var(--muted);cursor:pointer}
.about-x:hover{color:var(--ink);background:var(--sunk)}
.about-x svg{width:1.1rem;height:1.1rem;display:block}
.about-logo{display:block;position:relative;width:clamp(4.75rem,18vw,6.25rem);
  aspect-ratio:440/372;margin:.15rem auto .9rem}
.about-logo-img{position:absolute;inset:0;display:block;width:100%;height:100%;
  filter:drop-shadow(0 5px 10px rgba(0,0,0,.16))}
.about-logo-dark{display:none}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]) .about-logo-light{display:none}
  :root:not([data-theme="light"]) .about-logo-dark{display:block}
}
:root[data-theme="dark"] .about-logo-light{display:none}
:root[data-theme="dark"] .about-logo-dark{display:block}
:root[data-theme="light"] .about-logo-light{display:block}
:root[data-theme="light"] .about-logo-dark{display:none}
.about-card h3{font:600 clamp(19px,2.2vw,23px)/1.3 var(--serif);color:var(--ink);
  letter-spacing:-.01em;margin:0 2.2rem .75rem 0}
.about-sec{margin-top:1.05rem}
.about-sec h4{font:600 12px/1.5 var(--sans);color:var(--muted);letter-spacing:.09em;
  text-transform:uppercase;margin-bottom:.45rem;display:flex;align-items:center;gap:.55rem}
.about-sec h4::after{content:"";flex:1;height:1px;background:var(--rule)}
.about-sec p{font:400 13.5px/1.75 var(--serif);color:var(--ink2);margin:0 0 .6rem;
  text-wrap:pretty}
.about-sec p:last-child{margin-bottom:0}
.about-note{font-size:12.5px;color:var(--muted)}
.about-dis{list-style:none;margin:0;padding:0;display:grid;gap:.45rem}
.about-dis li{position:relative;padding-left:.95rem;font:400 12.5px/1.7 var(--serif);
  color:var(--ink2);text-wrap:pretty}
.about-dis li::before{content:"";position:absolute;left:0;top:.6em;width:.3rem;
  height:.3rem;border-radius:1px;background:var(--accent);opacity:.55}
.about-mail{font-family:var(--mono);font-size:12.5px;letter-spacing:.02em;
  color:var(--ink2)}

/* The chart itself: four node kinds, hexagons for the two human nodes, dashed chips
   for the back-edges.  The palette is derived from the site's own design tokens — the
   A-side blue for AI steps, neutral greys for data artifacts, the accent for the two
   human touchpoints, the B-side ochre for pure code — so it follows both themes (and a
   topic page's own accent) with no separate dark block. */
.about-legend{display:flex;flex-wrap:wrap;justify-content:flex-end;
  gap:.35rem .45rem;margin:0 0 .8rem}
.alg{font:500 10.5px/1.5 var(--sans);letter-spacing:.02em;padding:.12rem .5rem;
  border:1.5px solid;border-radius:2px}
.about-flow{display:flex;flex-direction:column;align-items:center;margin:0 0 .2rem}
.about-flow,.about-legend{
  --af-p-fill:var(--a-soft);--af-p-line:var(--a-line);--af-p-ink:var(--a);
  --af-d-fill:var(--sunk);
  --af-d-line:color-mix(in oklab,var(--muted) 45%,var(--panel));
  --af-d-ink:var(--ink2);
  --af-h-fill:color-mix(in oklab,var(--accent) 11%,var(--panel));
  --af-h-line:color-mix(in oklab,var(--accent) 42%,var(--panel));
  --af-h-ink:var(--accent);
  --af-c-fill:var(--b-soft);--af-c-line:var(--b-line);--af-c-ink:var(--b)}
.alg--process{background:var(--af-p-fill);border-color:var(--af-p-line);color:var(--af-p-ink)}
.alg--data{background:var(--af-d-fill);border-color:var(--af-d-line);color:var(--af-d-ink)}
.alg--human{background:var(--af-h-fill);border-color:var(--af-h-line);color:var(--af-h-ink)}
.alg--code{background:var(--af-c-fill);border-color:var(--af-c-line);color:var(--af-c-ink)}
/* Sized by its own text, the way mermaid draws a node — never wider than the card. */
.afnode{width:fit-content;max-width:100%;text-align:center;border:1.5px solid;
  border-radius:4px;font:500 12.5px/1.6 var(--sans)}
.afnode>span{display:block;padding:.5rem 1.1rem}
.afnode--process{background:var(--af-p-fill);border-color:var(--af-p-line);color:var(--af-p-ink)}
.afnode--data{background:var(--af-d-fill);border-color:var(--af-d-line);color:var(--af-d-ink);
  border-radius:999px}
.afnode--data>span{padding-inline:1.4rem}
.afnode--code{background:var(--af-c-fill);border-color:var(--af-c-line);color:var(--af-c-ink)}
/* The two human nodes are the doc's hexagons.  clip-path drops the border, so the outer
   box is the border colour and an inset inner span carries the fill — the corner angles
   differ by the 2px inset, which is invisible at this size. */
.afnode--human{--hex:polygon(1rem 0,calc(100% - 1rem) 0,100% 50%,
  calc(100% - 1rem) 100%,1rem 100%,0 50%);
  border:0;border-radius:0;background:var(--af-h-line);clip-path:var(--hex);
  color:var(--af-h-ink);font-weight:600}
.afnode--human>span{margin:2px;background:var(--af-h-fill);clip-path:var(--hex);
  padding:.55rem 1.6rem}
.afdown{position:relative;width:2px;height:1.15rem;flex:none;
  background:color-mix(in oklab,var(--muted) 75%,transparent)}
.afdown::after{content:"";position:absolute;left:50%;bottom:-1px;
  transform:translateX(-50%);border:4px solid transparent;border-bottom:0;
  border-top-color:color-mix(in oklab,var(--muted) 90%,transparent)}
.afdlab{position:absolute;left:.55rem;top:50%;transform:translateY(-50%);
  font:500 10.5px/1 var(--sans);color:var(--muted);white-space:nowrap}
.afloop{margin:.3rem 0 0;font:400 11px/1.5 var(--sans);color:var(--muted);
  padding:.14rem .55rem;border:1px dashed color-mix(in oklab,var(--muted) 55%,transparent);
  border-radius:999px;max-width:100%;text-align:center;text-wrap:pretty}
.afloop+.afdown,.afloop+.afloop{margin-top:.3rem}
@media (max-width:30rem){
  .about-card{padding:1.2rem .95rem 1.4rem}
  .afnode--human>span{padding-inline:1.1rem}
}
""".strip()


# --------------------------------------------------------------------------------------
# behaviour — one wiring function, used verbatim by both documents
# --------------------------------------------------------------------------------------

_WIRE_JS = r"""
function wireAbout(btn,modal){
  var card=modal.querySelector('.about-card');
  var closer=modal.querySelector('.about-x');
  var last=null;
  function open(){last=document.activeElement;modal.hidden=false;
    document.body.classList.add('about-open');
    btn.setAttribute('aria-expanded','true');
    (closer||card).focus()}
  function close(){modal.hidden=true;
    document.body.classList.remove('about-open');
    btn.setAttribute('aria-expanded','false');
    if(last&&last.focus)last.focus()}
  btn.addEventListener('click',function(){modal.hidden?open():close()});
  modal.addEventListener('mousedown',function(event){
    if(!card.contains(event.target))close()});
  if(closer)closer.addEventListener('click',close);
  document.addEventListener('keydown',function(event){
    if(event.key==='Escape'&&!modal.hidden)close()});
}
""".strip()

#: The home page carries the button and the modal in its own markup; this only wires.
HOME_ABOUT_JS = (
    "(function(){"
    + _WIRE_JS
    + "\nvar btn=document.getElementById('aboutbtn');"
    "var modal=document.getElementById('about-modal');"
    "if(btn&&modal)wireAbout(btn,modal)})();"
)


def chrome_about_js() -> str:
    """The chrome script's injector for topic pages.

    An approved content document must not change a byte, so the button and the modal
    are created client-side: the button lands beside the relocated home control (the
    chrome toolbar has already been built by the time this runs), the modal lands at
    the end of ``<body>``, and the locale is read off the document itself.
    """
    data = {
        locale: {
            "label": _COPY[locale]["button_label"],
            "button": about_button_html(locale),
            "modal": about_modal_html(locale),
        }
        for locale in ABOUT_LOCALES
    }
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True)
    body = r"""
function pick(){
  var lang=document.documentElement.lang||'';
  if(DATA[lang])return DATA[lang];
  var base=lang.split('-')[0];
  for(var key in DATA)if(key.split('-')[0]===base)return DATA[key];
  return DATA['en'];
}
var tools=document.querySelector('.site-tools');
if(!tools||document.getElementById('aboutbtn'))return;
var entry=pick();if(!entry)return;
var holder=document.createElement('div');
holder.innerHTML=entry.button;
var btn=holder.firstChild;
var home=tools.querySelector('.home-link');
if(home&&home.parentNode===tools){home.insertAdjacentElement('afterend',btn)}
else{tools.insertBefore(btn,tools.firstChild)}
holder.innerHTML=entry.modal;
var modal=holder.firstChild;
document.body.appendChild(modal);
wireAbout(btn,modal);
""".strip()
    return (
        "(function(){\n" + _WIRE_JS + "\nvar DATA=" + payload + ";\n" + body + "\n})();"
    )
