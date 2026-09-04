"""Homepage-only suggestion and invited full-report submission entrance.

The public site is static. The modal therefore discovers the public Turnstile site key
and current copy versions from the intake Worker's origin-gated ``GET /v1/config`` only
when a reader opens the suggestion form. If that request or any dependency fails, the
form remains closed; no topic page and no approved content document includes this UI.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from newsab_schema import EXTRA_HALO_LOCALES

from .identity import official_site, site_identity
from .legal import privacy_notice_url


INTAKE_ORIGIN = "https://intake.news-ab.com"
#: The public toolkit repository: the footer mark, the about note and the suggest
#: modal all point here.
TOOLKIT_REPO_URL = "https://github.com/wenruofeng/newsab"


def suggestion_entrance_enabled() -> bool:
    """Keep the official site's intake out of neutral public-toolkit homepages."""
    return official_site()


def _esc(value: str) -> str:
    return html.escape(value)


def _attr(value: str) -> str:
    return html.escape(value, quote=True)


_COPY = {
    "en": {
        "button": "Suggest a topic or submit a report",
        "close": "Close",
        "title": "Bring a topic to {site_name}",
        "lead": "There are two ways to put a comparison into motion.",
        "suggest_title": "Suggest a topic",
        "suggest_desc": "Tell us what happened, which two media groups to compare, and why their narratives may differ. We may choose to make the report ourselves.",
        "suggest_note": "A suggestion is not a commission: we do not guarantee adoption, processing, or a reply.",
        "suggest_cta": "I want to suggest one",
        "agent_title": "Let your AI agent make it",
        "agent_desc": "Give the open-source toolkit link to your coding agent. It can build the same kind of auditable comparison report in your own local workspace.",
        "github_cta": "Open the GitHub toolkit",
        "github_note": "Public, open-source repository; its README tells your agent where to start.",
        "submit_desc": "If you finished a report with the toolkit and received an invitation, upload its verified archive here for review.",
        "submit_cta": "I want to submit my report",
        "submit_form_title": "Submit an invited report",
        "invite": "Single-use invitation code",
        "archive": "Verified submission archive (.tgz)",
        "control": "Control credential (required for withdraw)",
        "submit_consent": "I am entitled to submit this archive, I have read and accept the {notice} including its submission terms, and understand that upload does not guarantee review, acceptance, or publication.",
        "archive_summary": "Archive: {topic} · {operation} · {size}",
        "upload": "Upload for review",
        "upload_loading": "Loading the invitation-only upload form…",
        "upload_paused": "Report submissions are currently invitation-only or paused.",
        "upload_hashing": "Checking archive…",
        "upload_sending": "Uploading directly to the private archive store…",
        "upload_done": "Your report archive has been received.",
        "save_control": "Save this control credential now. It is shown only once and is required to withdraw:",
        "upload_failed": "The archive was not received. Check the invitation, archive, and connection, then retry.",
        "err_invite": "That invitation code is not valid, has expired, or has already been used. Each code works once.",
        "err_verify": "Human verification did not pass. Complete the check again, then resend.",
        "err_rate": "Too many attempts from here just now. Wait a minute and try again.",
        "err_unavailable": "The intake service is temporarily unreachable. Nothing you typed was lost — try again shortly.",
        "err_reload": "The notice or terms changed while this form was open. Reload the page and submit again.",
        "err_duplicate": "This archive was already submitted. Wait for the review instead of uploading it again.",
        "err_control": "The control credential is missing or was refused. It is the one shown once when the original report was submitted.",
        "err_archive": "This file is not a readable submission archive. Upload the .tgz the toolkit produced, unchanged.",
        "err_too_large": "The archive is larger than the {size} upload limit.",
        "err_expired": "The upload window expired. Choose the archive again and resubmit.",
        "form_title": "Suggest a topic",
        "topic": "What is the topic?",
        "topic_hint": "One sentence: what happened or what question should be compared?",
        "group_a": "Media group A",
        "group_b": "Media group B",
        "window": "Approximate time and language range",
        "urls": "Reference links (one per line; at most 5)",
        "attribution": "Credit me publicly",
        "name": "Name",
        "contact": "Email",
        "notice_title": "Privacy and Submission Notice",
        "consent": "I have read and accept the {notice}, and understand that {site_name} does not guarantee adoption, processing, or a reply.",
        "send": "Send suggestion",
        "loading": "Loading the protected form…",
        "paused": "Suggestions are temporarily paused. Please try again later.",
        "sending": "Sending…",
        "done_title": "Your suggestion has been submitted!",
        "done_ok": "OK",
        "failed": "The suggestion was not sent. Please review the form or try again later.",
    },
    "zh-CN": {
        "button": "建议议题或投稿",
        "close": "关闭",
        "title": "提交你自己感兴趣的议题",
        "lead": "想让新议题出现在 news-ab.com 上？有两种方式：",
        "suggest_title": "向我们提议",
        "suggest_desc": "告诉我们是什么事件/话题、希望比较哪两组媒体，以及为何两边的叙事差异值得一看。我们或许会替你完成并上线一份报告。",
        "suggest_note": "本站不保证采纳、处理或回复你的提议。",
        "suggest_cta": "我要提议",
        "agent_title": "自己动手",
        "agent_desc": "如果你使用如 Claude Code 或 Codex 这样可运行代码的 AI 助手，且愿意用自己的 token 额度来进行议题研究，请把如下开源代码库的网页链接粘贴给你的 AI。它会引导你提出需求，并自动完成从采集到报告的流程，最终生成网页报告。",
        "github_cta": "打开 GitHub",
        "github_note": "公开的开源仓库；README 会告诉你的 AI 从哪里开始。",
        "submit_desc": "如果你希望把你自制的报告分享给更多人，不妨让 AI 把报告产物打成标准稿件包，然后上传投稿。如果通过质量审核，你的报告会在本站上发布。",
        "submit_cta": "我要投稿",
        "submit_form_title": "上传投稿",
        "invite": "单次邀请代码",
        "archive": "AI 按流程生成的投稿包（.tgz）",
        "control": "撤稿密钥",
        "submit_consent": "我有权提交此投稿包，已阅读并同意{notice}（含其中的投稿条款），并理解上传不保证审核、接收或发布。",
        "archive_summary": "投稿包：{topic} · {operation} · {size}",
        "upload": "上传",
        "upload_loading": "正在载入上传表单……",
        "upload_paused": "完整投稿目前仅限受邀用户，或暂时关闭。",
        "upload_hashing": "正在检查投稿包……",
        "upload_sending": "正在上传到云……",
        "upload_done": "你的完整投稿包已收到。",
        "save_control": "请立即保存下面的撤稿密钥。它只显示一次，后续申请撤稿时必须使用：",
        "upload_failed": "投稿包未收到。请检查邀请、文件和网络后重试。",
        "err_invite": "邀请代码无效、已过期或已被使用。每个代码只能用一次。",
        "err_verify": "人机验证未通过。请重新完成验证后再提交。",
        "err_rate": "短时间内尝试次数过多。请稍等一分钟再试。",
        "err_unavailable": "投稿服务暂时不可用。你填写的内容没有丢失，请稍后重试。",
        "err_reload": "本页打开期间声明或条款有更新。请刷新页面后重新提交。",
        "err_duplicate": "这份投稿包已经提交过了。不必重复上传，等待审核结果即可。",
        "err_control": "撤稿密钥缺失或不正确。它是原投稿提交成功时只显示一次的那串字符。",
        "err_archive": "这个文件不是可读的投稿包。请上传工具链生成的 .tgz 原始文件，不要改动或重新打包。",
        "err_too_large": "投稿包超过了 {size} 的上传上限。",
        "err_expired": "上传时限已过。请重新选择投稿包后再提交。",
        "form_title": "建议议题",
        "topic": "事件/话题",
        "topic_hint": "用一句话说明发生了什么，或你想比较什么",
        "group_a": "A 组媒体",
        "group_b": "B 组媒体",
        "window": "大致时间和语言范围",
        "urls": "参考链接（每行一个，最多 5 个）",
        "attribution": "公开署名",
        "name": "姓名",
        "contact": "邮箱",
        "notice_title": "《隐私与投稿声明》",
        "consent": "我已阅读并同意{notice}，并理解 {site_name} 不保证采纳、处理或回复。",
        "send": "提交建议",
        "loading": "正在载入表单……",
        "paused": "建议入口暂时关闭，请稍后再试。",
        "sending": "正在提交……",
        "done_title": "你的建议已提交！",
        "done_ok": "好的",
        "failed": "建议未能提交。请检查表单，或稍后再试。",
    },
}

#: The halo's other seven locales, merged in from versioned package data.
_i18n_path = Path(__file__).with_name("data") / "suggest_i18n.v1.json"
_i18n_data = json.loads(_i18n_path.read_text(encoding="utf-8"))
for _lang in EXTRA_HALO_LOCALES:
    _COPY[_lang] = dict(_i18n_data[_lang])

#: The site's name is ``SiteIdentity.site_name``, never copy: every locale's table (the
#: literals above and the JSON alike) names it through a ``{site_name}`` slot, filled here
#: once, so the strings stay identity-free and a public clone's neutral identity flows
#: through without a rewrite.  ``{notice}`` is a different slot, filled per render
#: by ``_consent_html`` — it is left alone here.
_SITE_NAME = site_identity().site_name
for _lang, _table in _COPY.items():
    _COPY[_lang] = {key: value.replace("{site_name}", _SITE_NAME) for key, value in _table.items()}

_expected_suggest = {key: type(value) for key, value in _COPY["en"].items()}
for _locale, _table in _COPY.items():
    if {key: type(value) for key, value in _table.items()} != _expected_suggest:
        raise RuntimeError(f"asymmetric suggestion-modal copy for {_locale}")


_ICON_PLUS = (
    '<svg viewBox="0 0 20 20" aria-hidden="true" fill="none" stroke="currentColor" '
    'stroke-width="1.6" stroke-linecap="round"><path d="M10 4.5v11M4.5 10h11"/></svg>'
)
_ICON_CLOSE = (
    '<svg viewBox="0 0 20 20" aria-hidden="true" fill="none" stroke="currentColor" '
    'stroke-width="1.6" stroke-linecap="round"><path d="M5.5 5.5l9 9M14.5 5.5l-9 9"/></svg>'
)


def _copy(locale: str) -> dict[str, str]:
    try:
        return _COPY[locale]
    except KeyError as exc:
        raise ValueError(f"suggestion copy has no locale {locale}") from exc


def _consent_html(s: dict[str, str], key: str, locale: str) -> str:
    """The consent sentence with its ``{notice}`` slot filled by a link to the notice.

    The notice is the whole privacy and terms text (``legal.py``); the modal carries no
    summary of it, only the link, so the two can never disagree.  Opens in a new tab so
    a half-filled form is not lost.
    """
    before, _, after = s[key].partition("{notice}")
    if not _:
        raise ValueError(f"consent copy for {locale} lacks the {{notice}} slot: {key}")
    link = (
        f'<a href="{_attr(privacy_notice_url(locale))}" target="_blank" '
        f'rel="noopener noreferrer">{_esc(s["notice_title"])}</a>'
    )
    return f"{_esc(before)}{link}{_esc(after)}"


def suggest_button_html(locale: str) -> str:
    label = _copy(locale)["button"]
    return (
        '<button class="toolbtn" id="suggestbtn" type="button" aria-haspopup="dialog" '
        'aria-expanded="false" aria-controls="suggest-modal" '
        f'aria-label="{_attr(label)}" title="{_attr(label)}">{_ICON_PLUS}</button>'
    )


def suggest_modal_html(locale: str) -> str:
    s = _copy(locale)
    return f'''<div class="suggest-modal" id="suggest-modal" role="dialog" aria-modal="true"
 aria-labelledby="suggest-title" hidden><div class="suggest-card" tabindex="-1">
<button class="suggest-x" type="button" aria-label="{_attr(s["close"])}" title="{_attr(s["close"])}">{_ICON_CLOSE}</button>
<h3 id="suggest-title">{_esc(s["title"])}</h3><p class="suggest-lead">{_esc(s["lead"])}</p>
<div class="suggest-paths">
 <section class="suggest-path suggest-path--idea"><span class="suggest-num">01</span>
  <h4>{_esc(s["suggest_title"])}</h4><p>{_esc(s["suggest_desc"])}</p>
  <p class="suggest-note">{_esc(s["suggest_note"])}</p>
  <button class="suggest-cta" type="button" data-show-suggestion aria-expanded="false" aria-controls="suggest-formbox-idea">{_esc(s["suggest_cta"])}</button>
 </section>
 <section class="suggest-path suggest-path--agent"><span class="suggest-num">02</span>
  <h4>{_esc(s["agent_title"])}</h4><p>{_esc(s["agent_desc"])}</p>
  <a class="suggest-cta suggest-cta--line" href="{_attr(TOOLKIT_REPO_URL)}" target="_blank" rel="noopener noreferrer">{_esc(s["github_cta"])} <span aria-hidden="true">↗</span></a>
  <p class="suggest-meta">{_esc(s["github_note"])}</p>
  <p>{_esc(s["submit_desc"])}</p>
  <button class="suggest-cta" type="button" data-show-submission aria-expanded="false" aria-controls="suggest-formbox-upload">{_esc(s["submit_cta"])}</button>
 </section>
</div>
<section class="suggest-formbox" id="suggest-formbox-idea" data-suggestion-formbox hidden>
 <h4>{_esc(s["form_title"])}</h4><p class="suggest-load" data-suggest-load>{_esc(s["loading"])}</p>
 <form data-suggestion-form hidden>
  <label class="sf-wide"><span class="sf-req">{_esc(s["topic"])}</span><textarea name="topic" required minlength="10" maxlength="500" rows="2" aria-describedby="sf-topic-hint"></textarea><small id="sf-topic-hint">{_esc(s["topic_hint"])}</small></label>
  <div class="sf-pair"><label><span class="sf-req">{_esc(s["group_a"])}</span><input name="group_a" required maxlength="160"></label><label><span class="sf-req">{_esc(s["group_b"])}</span><input name="group_b" required maxlength="160"></label></div>
  <label><span>{_esc(s["window"])}</span><input name="rough_window" maxlength="160"></label>
  <label><span>{_esc(s["urls"])}</span><textarea name="start_urls" rows="3" maxlength="10240"></textarea></label>
  <label class="suggest-consent sf-attr"><input name="attribution" type="checkbox"><span>{_esc(s["attribution"])}</span></label>
  <div class="sf-pair"><label><span>{_esc(s["name"])}</span><input name="name" maxlength="160" autocomplete="name"></label><label><span>{_esc(s["contact"])}</span><input name="contact" type="email" maxlength="320" autocomplete="email"></label></div>
  <label class="sf-trap" aria-hidden="true">Website<input name="website" tabindex="-1" autocomplete="off"></label>
  <div class="suggest-turnstile" data-turnstile></div>
  <label class="suggest-consent"><input name="accepted" type="checkbox" required><span>{_consent_html(s, "consent", locale)}</span></label>
  <button class="suggest-cta" type="submit">{_esc(s["send"])}</button>
  <p class="suggest-status" data-suggest-status role="status" aria-live="polite"></p>
 </form>
</section>
<section class="suggest-formbox" id="suggest-formbox-upload" data-submission-formbox hidden>
 <h4>{_esc(s["submit_form_title"])}</h4><p class="suggest-load" data-submission-load>{_esc(s["upload_loading"])}</p>
 <form data-submission-form hidden>
  <label><span class="sf-req">{_esc(s["invite"])}</span><input name="invite_token" required minlength="32" maxlength="512" autocomplete="off"></label>
  <label><span class="sf-req">{_esc(s["archive"])}</span><input name="archive" type="file" required accept=".tgz,.tar.gz,application/gzip,application/octet-stream"></label>
  <p class="suggest-status" data-archive-summary role="status" aria-live="polite"></p>
  <label data-control-field hidden><span class="sf-req">{_esc(s["control"])}</span><input name="control_credential" maxlength="256" autocomplete="off"></label>
  <label><span>{_esc(s["contact"])}</span><input name="contact" type="email" maxlength="320" autocomplete="email"></label>
  <label class="sf-trap" aria-hidden="true">Website<input name="website" tabindex="-1" autocomplete="off"></label>
  <div class="suggest-turnstile" data-submission-turnstile></div>
  <label class="suggest-consent"><input name="accepted" type="checkbox" required><span>{_consent_html(s, "submit_consent", locale)}</span></label>
  <button class="suggest-cta" type="submit">{_esc(s["upload"])}</button>
  <p class="suggest-status" data-submission-status role="status" aria-live="polite"></p>
 </form>
</section></div></div>
<div class="suggest-modal" id="suggest-done" role="alertdialog" aria-modal="true"
 aria-labelledby="suggest-done-title" hidden><div class="suggest-card suggest-card--done" tabindex="-1">
<h3 id="suggest-done-title">{_esc(s["done_title"])}</h3>
<button class="suggest-cta" type="button" data-done-ok>{_esc(s["done_ok"])}</button>
</div></div>
<div class="suggest-modal" id="submission-done" role="alertdialog" aria-modal="true"
 aria-labelledby="submission-done-title" hidden><div class="suggest-card suggest-card--done" tabindex="-1">
<h3 id="submission-done-title">{_esc(s["upload_done"])}</h3>
<p data-control-copy hidden>{_esc(s["save_control"])}</p><code data-control-credential hidden></code>
<button class="suggest-cta" type="button" data-upload-done-ok>{_esc(s["done_ok"])}</button>
</div></div>'''


SUGGEST_CSS = r"""
/* Homepage-only suggestion entrance. Topic pages intentionally never receive these rules. */
.toolgroup--left{margin-left:0;margin-right:.4rem}
body.suggest-open{overflow:hidden}
.suggest-modal{position:fixed;inset:0;z-index:92;display:flex;align-items:center;
  justify-content:center;padding:max(1rem,env(safe-area-inset-top))
  max(1rem,env(safe-area-inset-right)) max(1rem,env(safe-area-inset-bottom))
  max(1rem,env(safe-area-inset-left));background:rgba(10,12,14,.58)}
.suggest-modal[hidden]{display:none}
.suggest-card{position:relative;width:min(52rem,100%);max-height:min(90dvh,65rem);
  overflow-y:auto;overscroll-behavior:contain;background:var(--panel);border:1px solid var(--rule);
  border-radius:7px;padding:1.65rem 1.75rem 1.9rem;box-shadow:0 18px 60px rgba(0,0,0,.34);outline:none}
.suggest-x{position:absolute;top:.55rem;right:.6rem;display:flex;align-items:center;
  justify-content:center;width:2.2rem;height:2.2rem;border:0;border-radius:50%;background:none;
  color:var(--muted);cursor:pointer}
.suggest-x:hover{color:var(--ink);background:var(--sunk)}
.suggest-x svg{width:1.1rem;height:1.1rem}
.suggest-card>h3{font:600 clamp(21px,2.4vw,27px)/1.3 var(--serif);margin:0 2.4rem .35rem 0;color:var(--ink)}
.suggest-lead{font:400 14px/1.7 var(--serif);color:var(--muted);margin:0 0 1.15rem}
.suggest-paths{display:grid;grid-template-columns:1fr 1fr;gap:.8rem}
.suggest-path{position:relative;display:flex;flex-direction:column;align-items:flex-start;padding:1.1rem;
  min-width:0;border:1px solid var(--rule);border-top:3px solid var(--a);border-radius:5px;background:var(--paper)}
.suggest-path--agent{border-top-color:var(--b)}
.suggest-num{font:500 10px/1 var(--mono);color:var(--muted);letter-spacing:.08em}
.suggest-path h4,.suggest-formbox h4{font:600 16px/1.4 var(--serif);color:var(--ink);margin:.45rem 0 .45rem}
.suggest-path p{font:400 13px/1.68 var(--serif);color:var(--ink2);margin:0 0 .65rem}
.suggest-path .suggest-note{font-weight:600;color:var(--accent)}
.suggest-meta{font-size:11.5px!important;color:var(--muted)!important}
.suggest-cta{display:inline-flex;align-items:center;justify-content:center;gap:.3rem;min-height:2.45rem;
  margin-top:auto;padding:.48rem .78rem;border:1px solid var(--accent);border-radius:4px;
  background:var(--accent);color:var(--panel);font:600 12.5px/1.35 var(--sans);text-decoration:none;cursor:pointer}
.suggest-cta--line{margin:0 0 .5rem;background:transparent;color:var(--accent)}
/* The three calls to action sit on the centre line of their column; the copy above
   them stays left-aligned reading text. */
.suggest-path>.suggest-cta{align-self:center}
.suggest-path>.suggest-meta{align-self:center;text-align:center}
.suggest-cta--disabled{margin-top:.15rem;background:var(--sunk);border-color:var(--rule);color:var(--muted);cursor:not-allowed}
.suggest-cta small{font:500 9.5px/1 var(--sans);padding:.18rem .3rem;border:1px solid currentColor;border-radius:2px}
.suggest-formbox{margin-top:1rem;padding-top:1rem;border-top:1px solid var(--rule);scroll-margin-top:1rem}
.suggest-formbox form{display:grid;gap:.78rem}
.suggest-formbox label{display:grid;gap:.28rem;font:500 12px/1.4 var(--sans);color:var(--ink2)}
.suggest-formbox label>span:first-child{font-weight:600}
.suggest-formbox input,.suggest-formbox textarea{width:100%;border:1px solid var(--rule);border-radius:4px;
  padding:.58rem .65rem;background:var(--paper);color:var(--ink);font:400 13px/1.5 var(--sans)}
.suggest-formbox textarea{resize:vertical}
.suggest-formbox input:focus,.suggest-formbox textarea:focus{outline:2px solid color-mix(in oklab,var(--accent) 35%,transparent);border-color:var(--accent)}
.suggest-formbox small{font:400 10.5px/1.45 var(--sans);color:var(--muted)}
.sf-pair{display:grid;grid-template-columns:1fr 1fr;gap:.7rem}
.sf-req::after{content:" *";color:#a33b32;font-weight:700}
.sf-attr{margin-bottom:-.35rem}
.sf-trap{position:absolute!important;left:-10000px!important;width:1px!important;height:1px!important;overflow:hidden!important}
.suggest-load,.suggest-status{font:400 12px/1.65 var(--sans);color:var(--muted);margin:0}
.suggest-consent{display:flex!important;align-items:flex-start;grid-template-columns:none!important;gap:.5rem!important}
.suggest-consent input{width:auto;margin:.2rem 0 0;flex:none}
.suggest-consent span{font-weight:500!important}
.suggest-status[data-state="error"]{color:#a33b32;font-weight:600}
.suggest-card--done{width:min(24rem,100%);text-align:center;padding:1.8rem 1.5rem 1.6rem}
.suggest-card--done h3{margin:0 0 1.2rem;font:600 19px/1.45 var(--serif);color:var(--ink)}
.suggest-card--done p{font:400 12px/1.6 var(--sans);color:var(--muted);margin:0 0 .6rem}
.suggest-card--done code{display:block;overflow-wrap:anywhere;padding:.65rem;margin:0 0 1rem;
  border:1px solid var(--rule);background:var(--sunk);font:600 11px/1.5 var(--mono);user-select:all}
.suggest-card--done .suggest-cta{margin:0 auto;min-width:7rem}
@media(max-width:42rem){.suggest-card{padding:1.25rem .95rem 1.5rem}.suggest-paths,.sf-pair{grid-template-columns:1fr}}
""".strip()


def suggestion_js(locale: str) -> str:
    strings = json.dumps(_copy(locale), ensure_ascii=False, separators=(",", ":"))
    script = r"""
(function(){
var STRINGS=__STRINGS__;
var ORIGIN=__ORIGIN__;
var btn=document.getElementById('suggestbtn');
var modal=document.getElementById('suggest-modal');
if(!btn||!modal)return;
var card=modal.querySelector('.suggest-card');var closer=modal.querySelector('.suggest-x');
var show=modal.querySelector('[data-show-suggestion]');var box=modal.querySelector('[data-suggestion-formbox]');
var form=modal.querySelector('[data-suggestion-form]');var load=modal.querySelector('[data-suggest-load]');
var status=modal.querySelector('[data-suggest-status]');var last=null;var config=null;var widget=null;var pendingKey=null;
var done=document.getElementById('suggest-done');var doneCard=done.querySelector('.suggest-card');var doneOk=done.querySelector('[data-done-ok]');
var showUpload=modal.querySelector('[data-show-submission]');var uploadBox=modal.querySelector('[data-submission-formbox]');
var uploadForm=modal.querySelector('[data-submission-form]');var uploadLoad=modal.querySelector('[data-submission-load]');
var uploadStatus=modal.querySelector('[data-submission-status]');var archiveStatus=modal.querySelector('[data-archive-summary]');
var uploadWidget=null,uploadKey=null,parsedArchive=null;
var uploadDone=document.getElementById('submission-done');var uploadDoneCard=uploadDone.querySelector('.suggest-card');
var uploadDoneOk=uploadDone.querySelector('[data-upload-done-ok]');var controlCopy=uploadDone.querySelector('[data-control-copy]');
var controlValue=uploadDone.querySelector('[data-control-credential]');
function open(){last=document.activeElement;modal.hidden=false;document.body.classList.add('suggest-open');
 btn.setAttribute('aria-expanded','true');(closer||card).focus()}
function close(){modal.hidden=true;document.body.classList.remove('suggest-open');btn.setAttribute('aria-expanded','false');
 if(last&&last.focus)last.focus()}
btn.addEventListener('click',function(){modal.hidden?open():close()});
modal.addEventListener('mousedown',function(event){if(!card.contains(event.target))close()});
closer.addEventListener('click',close);
function openDone(){done.hidden=false;document.body.classList.add('suggest-open');doneOk.focus()}
function closeDone(){done.hidden=true;document.body.classList.remove('suggest-open');btn.focus()}
doneOk.addEventListener('click',closeDone);
done.addEventListener('mousedown',function(event){if(!doneCard.contains(event.target))closeDone()});
function closeUploadDone(){uploadDone.hidden=true;document.body.classList.remove('suggest-open');btn.focus()}
uploadDoneOk.addEventListener('click',closeUploadDone);
uploadDone.addEventListener('mousedown',function(event){if(!uploadDoneCard.contains(event.target))closeUploadDone()});
document.addEventListener('keydown',function(event){if(event.key!=='Escape')return;
 if(!uploadDone.hidden)closeUploadDone();else if(!done.hidden)closeDone();else if(!modal.hidden)close()});
function script(){return new Promise(function(resolve,reject){
 if(window.turnstile){resolve();return}var existing=document.querySelector('script[data-newsab-turnstile]');
 if(existing){existing.addEventListener('load',resolve,{once:true});existing.addEventListener('error',reject,{once:true});return}
 var tag=document.createElement('script');tag.src='https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
 tag.async=true;tag.defer=true;tag.dataset.newsabTurnstile='1';tag.onload=resolve;tag.onerror=reject;document.head.appendChild(tag)})}
async function getConfig(){if(config)return config;var response=await fetch(ORIGIN+'/v1/config',{headers:{Accept:'application/json'}});
 if(!response.ok)throw new Error('config');config=await response.json();return config}
/* Each path button always switches which form box is open; the box's config and
   Turnstile widget are prepared once, and a button is never left disabled (a disabled
   button was what stopped the second switch back to an already-loaded form). */
function reveal(target,other){other.hidden=true;target.hidden=false;target.scrollIntoView({behavior:'smooth',block:'nearest'})}
function pressed(active,inactive){active.setAttribute('aria-expanded','true');inactive.setAttribute('aria-expanded','false')}
var preparing=false,uploadPreparing=false;
async function prepare(){reveal(box,uploadBox);pressed(show,showUpload);if(widget!==null||preparing)return;preparing=true;
 try{await getConfig();if(!config.suggestions_open)throw new Error('paused');await script();
 form.hidden=false;load.hidden=true;widget=window.turnstile.render(form.querySelector('[data-turnstile]'),{
  sitekey:config.turnstile_sitekey,action:config.turnstile_action,theme:'auto'});
 }catch(error){load.textContent=STRINGS.paused;load.hidden=false}finally{preparing=false}}
show.addEventListener('click',prepare);
async function prepareUpload(){reveal(uploadBox,box);pressed(showUpload,show);if(uploadWidget!==null||uploadPreparing)return;uploadPreparing=true;
 try{await getConfig();if(!config.submissions_open)throw new Error('paused');await script();
 uploadForm.hidden=false;uploadLoad.hidden=true;uploadWidget=window.turnstile.render(uploadForm.querySelector('[data-submission-turnstile]'),{
  sitekey:config.turnstile_sitekey,action:config.submission_turnstile_action||config.turnstile_action,theme:'auto'});
 }catch(error){uploadLoad.textContent=STRINGS.upload_paused;uploadLoad.hidden=false}finally{uploadPreparing=false}}
showUpload.addEventListener('click',prepareUpload);
function lines(value){return value.split(/\r?\n/u).map(function(item){return item.trim()}).filter(Boolean)}
/* The worker answers a refusal with a machine code, and folding every one of them
   into a single sentence left a reader who mistyped an invitation with nothing to act on
   but the browser console.  Only codes a *reader* can actually fix
   or wait out are named here; anything else keeps the form's own catch-all sentence.
   Local failures thrown by the archive reader use the same table, so "this file is not a
   submission archive" and "the invitation was refused" never read alike. */
var ERRORS={INVITE_REQUIRED:'err_invite',
 TURNSTILE_FAILED:'err_verify',BOT_CHECK_FAILED:'err_verify',
 RATE_LIMITED:'err_rate',COPY_VERSION_CHANGED:'err_reload',
 DUPLICATE_ARCHIVE:'err_duplicate',INVITE_OR_SUBMISSION_ALREADY_USED:'err_duplicate',
 CONTROL_REQUIRED:'err_control',CONTROL_REFUSED:'err_control',
 UPLOAD_SLOT_EXPIRED:'err_expired',SUBMISSION_STATE_CONFLICT:'err_expired',
 BODY_TOO_LARGE:'err_too_large',UPLOAD_SIZE_MISMATCH:'err_too_large','archive-size':'err_too_large',
 envelope:'err_archive','gzip-unsupported':'err_archive',
 INTAKE_UNAVAILABLE:'err_unavailable',SUBMISSION_CONFIG_UNAVAILABLE:'err_unavailable',
 SUBMISSION_BUDGET_UNAVAILABLE:'err_unavailable',OBJECT_STORE_UNAVAILABLE:'err_unavailable',
 OBJECT_SEAL_FAILED:'err_unavailable',upload:'err_unavailable'};
/* The same pause means two different sentences depending on which form asked, so the
   caller names its own paused string rather than the table carrying both. */
var PAUSED={INTAKE_PAUSED:1,DAILY_BUDGET_REACHED:1,SUBMISSIONS_PAUSED:1,SUBMISSION_BUDGET_REACHED:1};
function explain(error,pausedKey,fallbackKey){
 var code=(error&&error.message)||'';var key=PAUSED[code]?pausedKey:ERRORS[code];
 var text=String(STRINGS[key]||STRINGS[fallbackKey]);if(text.indexOf('{size}')<0)return text;
 /* A sentence that names the limit is only better than the catch-all while the limit is
    known; the config request that carries it is also what fails first when it is not. */
 var limit=Number((config&&config.max_archive_bytes)||0);
 return limit?text.replace('{size}',humanBytes(limit)):String(STRINGS[fallbackKey])}
function key(){if(crypto.randomUUID)return crypto.randomUUID()+crypto.randomUUID();var a=new Uint32Array(8);crypto.getRandomValues(a);return Array.from(a).map(function(v){return v.toString(16).padStart(8,'0')}).join('')}
form.addEventListener('submit',async function(event){event.preventDefault();if(!config||!form.reportValidity())return;
 var submit=form.querySelector('[type="submit"]');submit.disabled=true;status.dataset.state='';status.textContent=STRINGS.sending;
 var data=new FormData(form);var token=window.turnstile.getResponse(widget);
 var payload={topic:data.get('topic'),group_a:data.get('group_a'),group_b:data.get('group_b'),
  rough_window:data.get('rough_window'),
  start_urls:lines(String(data.get('start_urls')||'')),attribution:data.get('attribution')==='on',
  name:data.get('name'),contact:data.get('contact'),website:data.get('website'),
  accepted:data.get('accepted')==='on',terms_version:config.terms_version,privacy_version:config.privacy_version,
  turnstile_token:token};
 if(!pendingKey)pendingKey=key();
 try{var response=await fetch(ORIGIN+'/v1/suggestions',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':pendingKey},body:JSON.stringify(payload)});
  var result=await response.json();if(!response.ok)throw new Error(result.error&&result.error.code||'request');
  status.dataset.state='';status.textContent='';form.reset();pendingKey=null;window.turnstile.reset(widget);close();openDone();
 }catch(error){status.dataset.state='error';status.textContent=explain(error,'paused','failed');if(window.turnstile)window.turnstile.reset(widget)}finally{submit.disabled=false}
});
form.addEventListener('input',function(){if(status.dataset.state!==''){status.dataset.state='';status.textContent=''}pendingKey=null});

function appendBytes(parts,total){var out=new Uint8Array(total),at=0;parts.forEach(function(part){out.set(part,at);at+=part.length});return out}
async function readEnvelope(file){
 if(!config||file.size>Number(config.max_archive_bytes||0))throw new Error('archive-size');
 if(typeof DecompressionStream==='undefined')throw new Error('gzip-unsupported');
 var reader=file.stream().pipeThrough(new DecompressionStream('gzip')).getReader(),parts=[],total=0,needed=null;
 try{for(;;){var step=await reader.read();if(step.done)break;parts.push(step.value);total+=step.value.length;
   if(total>=512&&needed===null){var head=appendBytes(parts,total);var name=new TextDecoder().decode(head.slice(0,100)).replace(/\0.*$/u,'');
    var sizeText=new TextDecoder().decode(head.slice(124,136)).replace(/\0.*$/u,'').trim();var size=parseInt(sizeText,8);
    if(name!=='submission.json'||!Number.isSafeInteger(size)||size<2||size>262144)throw new Error('envelope');needed=512+size}
   if(needed!==null&&total>=needed)break}
 }finally{await reader.cancel().catch(function(){})}
 if(needed===null||total<needed)throw new Error('envelope');var bytes=appendBytes(parts,total);
 var value=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes.slice(512,needed)));
 if(!value||value.magic!=='newsab-submission'||!/^SUB-[0-9a-f]{16}$/u.test(value.submission_id))throw new Error('envelope');return value
}
function humanBytes(size){if(size<1048576)return Math.ceil(size/1024)+' KiB';return (size/1048576).toFixed(1)+' MiB'}
var controlField=uploadForm.querySelector('[data-control-field]'),controlInput=controlField.querySelector('input');
/* The worker issues the control credential for a `create` upload and the done card shows
   it once; a reader types one only to prove control of a prior publication, so the field
   appears only once the chosen archive's envelope names another operation. */
function askControl(envelope){var needed=!!envelope&&envelope.operation!=='create';controlField.hidden=!needed;controlInput.required=needed;if(!needed)controlInput.value=''}
uploadForm.querySelector('[name=archive]').addEventListener('change',async function(){parsedArchive=null;uploadKey=null;archiveStatus.dataset.state='';archiveStatus.textContent=STRINGS.upload_hashing;askControl(null);
 try{var file=this.files&&this.files[0];if(!file)throw new Error('missing');var envelope=await readEnvelope(file);parsedArchive={file:file,envelope:envelope};askControl(envelope);
  archiveStatus.textContent=STRINGS.archive_summary.replace('{topic}',envelope.topic_id).replace('{operation}',envelope.operation).replace('{size}',humanBytes(file.size));
 }catch(error){archiveStatus.dataset.state='error';archiveStatus.textContent=explain(error,'upload_paused','err_archive')}}
);
async function digest(file){var hash=await crypto.subtle.digest('SHA-256',await file.arrayBuffer());return Array.from(new Uint8Array(hash)).map(function(v){return v.toString(16).padStart(2,'0')}).join('')}
uploadForm.addEventListener('submit',async function(event){event.preventDefault();if(!config||!uploadForm.reportValidity()||!parsedArchive)return;
 var submit=uploadForm.querySelector('[type="submit"]');submit.disabled=true;uploadStatus.dataset.state='';uploadStatus.textContent=STRINGS.upload_hashing;
 var data=new FormData(uploadForm),env=parsedArchive.envelope,file=parsedArchive.file;
 try{var sha=await digest(file),token=window.turnstile.getResponse(uploadWidget);uploadStatus.textContent=STRINGS.upload_sending;
  var payload={submission_id:env.submission_id,operation:env.operation,prior_publication_id:env.prior_publication_id,
   topic_id:env.topic_id,page_run_id:env.page_run_id,protocol_version:env.protocol_version,
   toolkit_version:env.toolkit_version,toolkit_ref:env.toolkit_ref,source_statement:env.source_statement,
   requested_locales:env.requested_locales||[],sponsor:env.sponsor,terms_version:env.terms_version,
   declared_archive_bytes:file.size,declared_archive_sha256:'sha256:'+sha,contact:data.get('contact'),invite_token:data.get('invite_token'),
   control_credential:controlField.hidden?null:data.get('control_credential'),accepted:data.get('accepted')==='on',website:data.get('website'),turnstile_token:token};
  if(!uploadKey)uploadKey=key();var slotResponse=await fetch(ORIGIN+'/v1/submission-slots',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':uploadKey},body:JSON.stringify(payload)});
  var slot=await slotResponse.json();if(!slotResponse.ok)throw new Error(slot.error&&slot.error.code||'slot');
  if(slot.status!=='received'){var put=await fetch(slot.upload_url,{method:'PUT',headers:{'Content-Type':'application/octet-stream'},body:file});if(!put.ok)throw new Error('upload')}
  var completeResponse=await fetch(ORIGIN+'/v1/submissions/'+encodeURIComponent(env.submission_id)+'/complete',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':uploadKey+':complete'},body:'{}'});
  var complete=await completeResponse.json();if(!completeResponse.ok)throw new Error(complete.error&&complete.error.code||'complete');
  controlValue.textContent=complete.control_credential||'';controlValue.hidden=!complete.control_credential;controlCopy.hidden=!complete.control_credential;
  uploadForm.reset();askControl(null);parsedArchive=null;uploadKey=null;archiveStatus.textContent='';window.turnstile.reset(uploadWidget);close();uploadDone.hidden=false;document.body.classList.add('suggest-open');uploadDoneOk.focus();
 }catch(error){uploadStatus.dataset.state='error';uploadStatus.textContent=explain(error,'upload_paused','upload_failed');if(window.turnstile)window.turnstile.reset(uploadWidget)}finally{submit.disabled=false}
});
uploadForm.addEventListener('input',function(event){if(event.target.name!=='archive')uploadKey=null;if(uploadStatus.dataset.state!==''){uploadStatus.dataset.state='';uploadStatus.textContent=''}});
})();
"""
    return script.replace("__STRINGS__", strings).replace(
        "__ORIGIN__", json.dumps(INTAKE_ORIGIN)
    ).strip()
