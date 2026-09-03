"""M2 production-only responsive, touch, keyboard and sharing enhancements.

Preview and historical publication bytes keep using the original renderer unless a
``PageSiteContext`` is explicitly supplied by stage 8.  Keeping this layer additive is
what lets old immutable publications remain byte-restorable while new candidates gain
the M2 contract.

The ``CSS`` and ``JS`` below are no longer inlined into a production page: they are
inputs to the site chrome layer (``newsab_publish.chrome``), which a page references at a
stable URL.  Their content is unchanged; only who ships them moved.  A ``PageSiteContext``
therefore carries chrome *URLs* and the page's opaque ``theme_token``, never chrome bytes
— that is what keeps a user-approved content document stable across a chrome release.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Mapping, Optional

from newsab_schema.locales import HALO_LOCALES


@dataclass(frozen=True)
class PageSiteContext:
    site_locale: str
    content_locale: str
    canonical_url: str
    alternate_urls: Mapping[str, str]
    share_urls: Mapping[str, str]
    share_landing_urls: Mapping[str, str]
    #: The one crawler card image the page offers (``og:image``), root-relative.  The
    #: site owns it (a PNG in the chrome layer), so the page names it without binding
    #: its bytes.
    share_image_url: str
    language_label: str
    share_label: str
    share_copied: str
    share_failed: str
    fallback_notice: Optional[str] = None
    #: The registry token this page states.  The colours behind it live in the chrome
    #: stylesheet, so re-theming never rewrites an approved content document.
    theme_token: str = ""
    stylesheet_url: str = ""
    script_url: str = ""


CSS = r"""
/* M2 is an additive production layer; editorial desktop tokens above remain the baseline. */
:root{--tap:2.75rem;--ctl:1.65rem;--toolsize:2.75rem;--sharesize:var(--ctl);--topic-decoration:0px}

/* ------------------------------------------------------------------ the site toolbar
   Home, language and theme are site-level controls, not topic-level ones, so they sit
   together in one row above the title and share one shape: a circular icon button.
   The content document still states them as a link, a nav of locale links and a floating
   theme control; the chrome script relocates and re-labels them, which is why nothing
   here needs a re-approved page.  Without JavaScript the row degrades to the plain text
   links the document itself carries. */
.site-tools{display:flex;align-items:center;justify-content:space-between;gap:.6rem;
  flex-wrap:wrap;margin:-.25rem 0 1.2rem;font:500 12px/1.45 var(--sans)}
.site-tools nav{display:flex;gap:.4rem;align-items:center;flex-wrap:wrap}
.site-tools a{display:inline-flex;align-items:center;min-height:var(--tap);padding:.35rem .55rem;
  border:1px solid var(--rule);border-radius:2px;text-decoration:none;color:var(--muted)}
.site-tools a[aria-current="page"]{color:var(--ink);border-color:var(--ink2)}
.locale-fallback{padding:.75rem 1rem;border-left:3px solid var(--accent);background:var(--sunk);
  color:var(--ink2);font:500 13px/1.6 var(--sans);margin-bottom:1.2rem}

/* Pinned to the page's own corners, not to the reading column: these belong to the site,
   and a site control that lines up with the article reads as part of the article.  They
   are ``absolute``, not ``fixed`` — the same shape and shadow as the back-to-top control,
   but they sit at the top of the page and scroll away with it instead of following. */
.site-tools[data-toolbar]{position:absolute;z-index:46;
  top:max(1rem,env(safe-area-inset-top));
  left:max(1rem,calc(env(safe-area-inset-left) + .5rem));
  right:max(1rem,calc(env(safe-area-inset-right) + .5rem));
  margin:0;padding:0;gap:.4rem;align-items:flex-start;pointer-events:none}
/* The bar spans the page, so only the controls themselves may take a click. */
.site-tools[data-toolbar]>*{pointer-events:auto}
.site-tools[data-toolbar] .toolgroup{display:flex;align-items:center;gap:.4rem;margin-left:auto}
.toolbtn{position:relative;display:inline-flex;align-items:center;justify-content:center;
  flex:none;width:var(--toolsize);height:var(--toolsize);min-height:0;padding:0;
  border:1px solid var(--rule);border-radius:50%;background:var(--panel);color:var(--ink2);
  cursor:pointer;text-decoration:none;box-shadow:0 5px 18px rgba(0,0,0,.12);
  transition:color .12s ease,border-color .12s ease,background-color .12s ease}
.toolbtn:hover,.toolbtn:focus-visible{color:var(--accent);border-color:var(--accent);
  background:var(--panel)}
.toolbtn>svg{width:1.15rem;height:1.15rem;display:block;flex:none}
.toolbtn[aria-expanded="true"]{color:var(--accent);border-color:var(--accent)}
/* Kept in the accessibility tree, taken out of the visual row: the icons carry the label. */
.toollabel{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;
  clip-path:inset(50%);white-space:nowrap;border:0}
.site-tools[data-toolbar] .home-link{min-height:0;margin:0;border-radius:50%}
/* ``relative``, not ``static``: the control keeps its own containing block, so the
   touch-reach pseudo-element below stays the size of a finger and not of the viewport.
   Both physical offsets reset, not just ``right``: under `dir="rtl"` the fixed-corner
   base rule sets `left:1rem` instead (the RTL mirror of the LTR `right:1rem`), and a
   leftover `left` on a now-``relative`` box is still a real offset — it slid this
   button 1rem into its neighbour instead of leaving it in the flex flow (bug found
   rendering the real ar topic page and measuring the two boxes overlap). */
.site-tools[data-toolbar] .theme-fab{position:relative;top:auto;right:auto;left:auto;
  width:var(--toolsize);height:var(--toolsize);box-shadow:0 5px 18px rgba(0,0,0,.12)}
.site-tools[data-toolbar] .theme-fab svg{width:1.15rem;height:1.15rem}
/* The dark-mode glyph, outlined to match the sun beside it and the home page's own pair.
   The sprite is inlined in the content document, whose bytes a human approved, so the
   shape is corrected here instead of in the path: a ``<use>`` instance takes the computed
   style of the symbol it clones, and fill/stroke are chrome, not a claim the page makes. */
#i-moon path{fill:none;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;
  stroke-linejoin:round}
/* The bar left the flow, so the page has to make room for it — everywhere except the
   widths where the reading column stops well short of both corners. */
:root[data-sitebar] main{padding-top:calc(max(1rem,env(safe-area-inset-top))
  + var(--toolsize) + 1.2rem)}
@media (min-width:70rem){
  :root[data-sitebar] main{padding-top:clamp(1.8rem,4vw,3.2rem)}
}
.langmenu{position:relative;display:flex}
.langmenu>nav{position:absolute;z-index:60;top:calc(100% + .4rem);right:0;
  display:flex;flex-direction:column;gap:.1rem;min-width:8.5rem;padding:.3rem;
  border:1px solid var(--rule);border-radius:7px;background:var(--panel);
  box-shadow:0 8px 26px rgba(0,0,0,.18)}
.langmenu>nav[hidden]{display:none}
.langmenu>nav a{display:flex;align-items:center;gap:.5rem;min-height:2.3rem;
  padding:.3rem .55rem;border:0;border-radius:4px;color:var(--ink2);white-space:nowrap}
.langmenu>nav a:hover{background:var(--sunk);color:var(--ink)}
.langmenu>nav a[aria-current="page"]{color:var(--accent);font-weight:600}
.langmenu>nav a::before{content:"";flex:none;width:.4rem;height:.4rem;border-radius:50%;
  background:transparent}
.langmenu>nav a[aria-current="page"]::before{background:currentColor}
/* The toolbar's ``justify-content:space-between`` already mirrors the home
   link/toolgroup split under `dir="rtl"` (it packs from the logical start/end, which
   flips with direction) — these two physical properties are the ones that would not. */
[dir="rtl"] .site-tools[data-toolbar] .toolgroup{margin-left:0;margin-right:auto}
[dir="rtl"] .langmenu>nav{right:auto;left:0}

/* --------------------------------------------------------------- one control height
   Badges, icon buttons and the help control used to each pick their own box, which reads
   as three accidental sizes in the same row.  One token sets them all. */
.badge{min-height:var(--ctl)}
.iconbtn,.helpbtn,.apx-toggle,.acard .acontrol .iconbtn{width:var(--ctl);height:var(--ctl)}
.acard .acontrol .iconbtn{margin:0}
.acard .acontrol .iconbtn svg{width:.95rem;height:.95rem}
.helpbtn svg{width:1rem;height:1rem}
.tbtn,.qbtn,.tabs button,button.media,button.clusterid{min-height:var(--ctl)}

/* ------------------------------------------------------- the connector between cards
   Side by side, the leads stopped short of both cards: the column carried a gap on each
   side that the artwork never crossed.  The artwork is a fixed 56-unit box, so each lead
   is exactly 3/14 of whatever span it is given — choose the span so the remaining 8/14
   is the mark's own diameter, drop the gaps, and the line runs card → mark → card with
   nothing left over. */
.duo{column-gap:0}
.rel{width:4.46rem}
.rel .rel-leads{width:4.46rem;height:3.4rem}
.comm{grid-template-columns:1fr 4.46rem 1fr;column-gap:0}

/* The count and the table control are one pair of controls; only one of them was sunk
   into a grey well. */
.acard .acontrol .badge.count{background:none}

/* ------------------------------------------------------------------- angle sharing
   The share control belongs to the question, so it rides the Q line's right edge rather
   than claiming a row of its own; the icon is the whole label. */
.angle{--qh2:clamp(21px,2.4vw,28px);
  display:grid;grid-template-columns:minmax(0,1fr) auto;grid-auto-flow:row dense;
  align-items:start;row-gap:0}
.angle>h2{font-size:var(--qh2)}
.angle-top{display:contents}
.angle-top>.left{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:.3rem;align-items:center;
  margin-bottom:.55rem}
.angle-top>.left:empty{display:none}
.angle>h2{grid-column:1;min-width:0}
.angle>.duo,.angle>.comm,.angle>details.qdata{grid-column:1/-1}
/* Centred on the Q line rather than hung from the top of it: the control is taller than
   the line box, so aligning their tops reads as "slightly too low", worst at the smallest
   heading size.  Both halves of the offset come from the one heading token above. */
.angle-share{grid-column:2;justify-self:end;align-self:start;position:relative;
  display:inline-flex;align-items:center;justify-content:center;flex:none;
  width:var(--sharesize);height:var(--sharesize);min-width:0;min-height:0;padding:0;
  margin:calc((1.35 * var(--qh2) - var(--sharesize)) / 2) 0 0 .5rem;
  border:1px solid var(--rule);border-radius:50%;
  background:transparent;color:var(--muted);cursor:pointer}
.angle-share:hover,.angle-share:focus-visible{border-color:var(--accent);color:var(--accent)}
.angle-share svg{width:1rem;height:1rem;display:block}
.angle-share>span{position:absolute;width:1px;height:1px;margin:-1px;padding:0;
  overflow:hidden;clip-path:inset(50%);white-space:nowrap;border:0}
.share-status{position:fixed;z-index:95;left:50%;bottom:max(1rem,env(safe-area-inset-bottom));
  transform:translateX(-50%);max-width:calc(100% - 2rem);padding:.65rem .9rem;border-radius:3px;
  background:var(--tip-bg);color:var(--tip-ink);font:500 12px/1.4 var(--sans);
  box-shadow:0 7px 24px rgba(0,0,0,.25)}
.share-status:empty{display:none}
.story-tabs button:focus-visible,.tabs button:focus-visible,.iconbtn:focus-visible,
.theme-fab:focus-visible,.top-fab:focus-visible,.modal-x:focus-visible,
.toolbtn:focus-visible,.angle-share:focus-visible,
.qrow>summary:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
.storyline,.appendix{border-top-width:max(1px,var(--topic-decoration))}
.ann-scroll,table.clist{overscroll-behavior-x:contain;-webkit-overflow-scrolling:touch}
.ann-scroll:focus-visible{outline:2px solid var(--accent);outline-offset:2px}

@media (max-width:720px){
  /* A badge is a word with a box around it.  At desktop proportions on a narrow column
     the box grows taller than the word needs and the row reads as a stack of slabs. */
  :root{--ctl:1.8rem}
  main{padding-left:max(.85rem,env(safe-area-inset-left));
    padding-right:max(.85rem,env(safe-area-inset-right));padding-bottom:max(3rem,env(safe-area-inset-bottom))}
  .theme-fab{top:max(.75rem,env(safe-area-inset-top));
    right:max(.75rem,env(safe-area-inset-right));width:var(--tap);height:var(--tap)}
  [dir="rtl"] .theme-fab{right:auto;left:max(.75rem,env(safe-area-inset-left))}
  .top-fab{width:var(--tap);height:var(--tap)}
  .site-tools{padding-right:3.25rem}.home-link{min-height:var(--tap);margin-bottom:0}
  [dir="rtl"] .site-tools{padding-right:0;padding-left:3.25rem}
  /* Three tabs, three words: they fit the narrow column when the gaps stop insisting on
     desktop generosity, and a wrap is still better than a scrollbar. */
  .story-tabs{justify-content:center;flex-wrap:wrap;overflow:visible;
    gap:.1rem .15rem;padding-bottom:1px;scroll-snap-type:none}
  .story-tabs button{min-height:var(--tap);padding:.5rem .3rem;gap:.25rem;
    font-size:15px;scroll-snap-align:none}
  .story-tabs .kindicon{width:1.1rem;height:1.1rem}
  .story-tabs button .n{margin-left:.12em}
  .storyline{padding:.9rem .6rem}
  .duo{grid-template-columns:1fr;gap:0}
  /* The connector is rotated a quarter turn when the cards stack.  Its rotated extent is
     its own width, so width must equal the row height — otherwise the leads print over
     the card above, which paints under them. */
  .rel{width:auto;height:3.4rem;min-height:3.4rem}
  .rel .rel-leads{width:3.4rem;height:2.7rem;left:50%;right:auto;
    transform:translate(-50%,-50%) rotate(90deg)}
  /* Centring a fixed-height card drops the side tag to the middle while the count and
     table controls stay pinned to the top; let the card be as tall as it needs to be and
     both sit on one line again. */
  .acard{min-height:0;padding:1rem .85rem 1.15rem}
  .acard .acontrol{top:1rem;right:.85rem;gap:.35rem}
  .acard .acontrol+.ahead{padding-left:5.9rem;padding-right:5.9rem}
  .acard .alabel{font-size:1.18rem}
  .acard.silent .alabel{font-size:1.05rem}
  /* The editorial layer stacks the explanations at this width too, but it says so in a
     media query and this layer's own `.comm` rule is unconditional and later — so the
     three-column desktop grid won, and each explanation printed in a 2/5-wide column
     with the rest of the row blank. */
  .comm{grid-template-columns:1fr}
  .comm:not(.joint) p:last-child{grid-column:1}
  .comm p{padding:0 .35rem}
  /* The connector turns a quarter turn when the cards stack; the mark it carries has to
     turn with it, or a silence points sideways at a card that is now above or below.
     The three storyline tabs carry the same three icons and turn with them. */
  .relmark .kindicon,.story-tabs .kindicon{transform:rotate(90deg)}
  .relmark .kindicon.flip{transform:rotate(90deg) scaleX(-1)}
  .appendix{padding:.85rem .7rem}
  /* Four badges on one nowrap line squeeze the question into a column two words wide.
     The badges are the part that stacks. */
  .qrow>summary{--ctl:1.55rem;min-height:var(--tap);padding:.7rem .15rem;flex-wrap:wrap;
    column-gap:.4rem;row-gap:.3rem}
  .qrow>summary .qsum{flex:1 1 calc(100% - 2.1rem)}
  .qrow>summary .badge{font-size:10px;padding-inline:.4rem}
  /* The badges are the question's metadata, not its continuation: keep them on the
     right edge when they drop to their own line. */
  .qrow>summary .qsum+.badge{margin-left:auto}
  .apx-toggle,.iconbtn,.tabs button,.qbtn,.tbtn{min-width:var(--ctl);min-height:var(--ctl)}
  .qblock{padding:.9rem .65rem 1.1rem}
  .qhead{gap:.3rem .35rem}
  .axis3{grid-template-columns:minmax(0,1fr) minmax(0,46%) minmax(0,1fr);gap:.2rem}
  /* A long answer used to wrap to three lines and push its own bars apart; truncate and
     let a tap show the whole thing (the chrome script attaches the tip). */
  .axis3 .cat{font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .axis3.rates{display:flex;justify-content:space-between;align-items:center;gap:.4rem}
  .axis3.rates .cat{display:none}
  .axis3.rates .bf-left{justify-content:flex-start;flex-wrap:wrap}
  .axis3.rates .bf-right{justify-content:flex-end;flex-wrap:wrap}
  .ann-scroll{margin-inline:-.65rem;padding-inline:.65rem}
  table.ann{min-width:40rem}.search-field input{min-height:var(--tap)}
  .search-results{max-height:65dvh}.search-result{min-height:var(--tap)}
  .modal{align-items:flex-end;padding:0;padding-top:max(1rem,env(safe-area-inset-top))}
  .modal-card{width:100%;max-width:none;max-height:calc(100dvh - max(1rem,env(safe-area-inset-top)));
    border-radius:9px 9px 0 0;padding:1.15rem max(1rem,env(safe-area-inset-right))
      max(1.25rem,env(safe-area-inset-bottom)) max(1rem,env(safe-area-inset-left));
    overscroll-behavior:contain}
  .modal-x{top:.25rem;right:max(.25rem,env(safe-area-inset-right));width:var(--tap);height:var(--tap)}
  .modal-card h4{padding-right:2.6rem}.modal-dl{grid-template-columns:1fr;gap:.08rem}
  .modal-dl dd{margin-bottom:.55rem}.modal-out{display:flex;align-items:center;justify-content:center;
    min-height:var(--tap)}
  table.clist{display:block;overflow-x:auto;white-space:normal}table.clist tbody,table.clist thead{min-width:34rem}
}
/* A touch target must be 44px; a *box* that big turns a badge row into a fence.  The
   visible control keeps the shared height and the pseudo-element carries the reach. */
@media (pointer:coarse){
  button,a,summary{touch-action:manipulation}
  [data-tip]{cursor:pointer}
  .iconbtn,.helpbtn,.qbtn,.tbtn,.tabs button,button.media,button.clusterid,
  .angle-share,.toolbtn,button.badge,a.badge{position:relative}
  .iconbtn::after,.helpbtn::after,.qbtn::after,.tbtn::after,.tabs button::after,
  button.media::after,button.clusterid::after,.angle-share::after,.toolbtn::after,
  button.badge::after,a.badge::after{content:"";position:absolute;left:50%;top:50%;
    width:max(100%,var(--tap));height:max(100%,var(--tap));
    transform:translate(-50%,-50%)}
  .pill{min-height:var(--tap);align-items:center}
}
@media (prefers-reduced-motion:reduce){
  *,*::before,*::after{scroll-behavior:auto!important;transition-duration:.001ms!important;
    animation-duration:.001ms!important;animation-iteration-count:1!important}
}
"""


#: Endonyms for the locale-switcher nav: a language chooser that names languages in a
#: language the reader may not read is a chooser they cannot use.  The site's nine
#: target languages (``newsab_schema.locales.HALO_LOCALES`` — the halo's single source
#: of truth) plus a few extra codes an alternate link could plausibly carry ahead of
#: that set actually going live.  Built here, not hand-typed in the JS below, so this
#: table cannot drift from the halo's nine the way it used to.
_LOCALE_ENDONYM_EXTRAS: dict[str, str] = {
    "zh-TW": "繁體中文",
    "de": "Deutsch",
    "pt": "Português",
    "sw": "Kiswahili",
}
_LOCALE_ENDONYMS: dict[str, str] = {
    **_LOCALE_ENDONYM_EXTRAS,
    **{entry.locale: entry.endonym for entry in HALO_LOCALES},
    "zh-Hans": next(entry.endonym for entry in HALO_LOCALES if entry.locale == "zh-CN"),
}
_LOCALE_NAMES_JS = json.dumps(_LOCALE_ENDONYMS, ensure_ascii=False, sort_keys=True)


_JS_TEMPLATE = r"""
(function(){
  var strings = (function(){
    var node=document.getElementById('site-strings');
    if(!node)return {};
    try{return JSON.parse(node.textContent)||{}}catch(e){return {}}
  })();
  var status=document.getElementById('share-status');
  var statusTimer=null;

  // ------------------------------------------------------------------ the site toolbar
  // The content document states three site-level controls in three different shapes: a
  // text "back home" link, a nav of locale codes and a floating theme button.  Chrome
  // gathers them into one row of identical icon buttons.  Nothing is added or removed —
  // every label the document wrote survives as the control's accessible name — so this
  // stays a chrome change and no approved page is re-reviewed for it.
  var ICON_HOME='<svg viewBox="0 0 20 20" aria-hidden="true" fill="none" stroke="currentColor" '+
    'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">'+
    '<path d="M2.9 8.7 10 3.1l7.1 5.6V16a1.2 1.2 0 0 1-1.2 1.2h-3.4v-4.9H7.5v4.9H4.1A1.2 1.2 0 0 1 2.9 16Z"/></svg>';
  var ICON_LANG='<svg viewBox="0 0 20 20" aria-hidden="true" fill="none" stroke="currentColor" '+
    'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">'+
    '<circle cx="10" cy="10" r="7.1"/><path d="M2.9 10h14.2"/>'+
    '<path d="M10 2.9c1.9 2.1 2.9 4.5 2.9 7.1s-1 5-2.9 7.1c-1.9-2.1-2.9-4.5-2.9-7.1S8.1 5 10 2.9Z"/></svg>';
  // Endonyms: a language chooser that names languages in a language the reader may not
  // read is a chooser they cannot use.
  var LOCALE_NAMES=__LOCALE_NAMES_JSON__;

  function labelFor(node){
    var text=(node.textContent||'').replace(/[←→\s]+/g,' ').trim();
    return text||node.getAttribute('aria-label')||'';
  }
  function hideLabel(node,text){
    node.textContent='';
    var span=document.createElement('span');
    span.className='toollabel';span.textContent=text;
    return span;
  }
  function buildToolbar(){
    var tools=document.querySelector('.site-tools');
    if(!tools||tools.hasAttribute('data-toolbar'))return;
    var home=tools.querySelector('.home-link');
    var nav=tools.querySelector('nav');
    var theme=document.getElementById('themebtn');
    if(!home&&!nav&&!theme)return;
    var group=document.createElement('div');
    group.className='toolgroup';
    tools.appendChild(group);
    if(home){
      var homeLabel=labelFor(home);
      var homeText=hideLabel(home,homeLabel);
      home.insertAdjacentHTML('afterbegin',ICON_HOME);
      home.appendChild(homeText);
      home.classList.add('toolbtn');
      if(homeLabel){home.setAttribute('aria-label',homeLabel);home.setAttribute('title',homeLabel)}
    }
    if(nav){
      var navLabel=nav.getAttribute('aria-label')||'';
      var menu=document.createElement('div');
      menu.className='langmenu';
      var trigger=document.createElement('button');
      trigger.type='button';trigger.className='toolbtn';
      trigger.innerHTML=ICON_LANG;
      trigger.setAttribute('aria-haspopup','true');
      trigger.setAttribute('aria-expanded','false');
      if(navLabel){trigger.setAttribute('aria-label',navLabel);trigger.setAttribute('title',navLabel)}
      nav.id=nav.id||'site-language-menu';
      trigger.setAttribute('aria-controls',nav.id);
      nav.hidden=true;
      Array.prototype.slice.call(nav.querySelectorAll('a')).forEach(function(link){
        var code=link.getAttribute('hreflang')||link.textContent.trim();
        link.textContent=LOCALE_NAMES[code]||code;
      });
      nav.parentNode.insertBefore(menu,nav);
      menu.appendChild(trigger);menu.appendChild(nav);
      group.appendChild(menu);
      function closeMenu(){nav.hidden=true;trigger.setAttribute('aria-expanded','false')}
      trigger.addEventListener('click',function(event){
        event.preventDefault();event.stopPropagation();
        var open=nav.hidden;
        nav.hidden=!open;trigger.setAttribute('aria-expanded',open?'true':'false');
        if(open){var first=nav.querySelector('a');if(first)first.focus()}
      });
      document.addEventListener('click',function(event){
        if(nav.hidden)return;
        if(menu.contains(event.target))return;
        closeMenu();
      });
      document.addEventListener('keydown',function(event){
        if(event.key!=='Escape'||nav.hidden)return;
        closeMenu();trigger.focus();
      });
    }
    if(theme){theme.classList.add('toolbtn');group.appendChild(theme)}
    tools.setAttribute('data-toolbar','on');
    document.documentElement.setAttribute('data-sitebar','on');
  }
  buildToolbar();

  // --------------------------------------------------- truncated answer labels on narrow
  // The butterfly's answer column is ellipsised below 720px; a tap must still be able to
  // read out the whole answer, so borrow the page's own tooltip channel.
  var labelCells=Array.prototype.slice.call(document.querySelectorAll('.axis3:not(.rates) .cat'));
  function labelTips(){
    labelCells.forEach(function(cell){
      var text=(cell.textContent||'').trim();
      var clipped=!!text&&cell.scrollWidth-cell.clientWidth>1;
      if(clipped===(cell.getAttribute('data-tip')===text))return;
      if(clipped){cell.setAttribute('data-tip',text);cell.setAttribute('tabindex','0')}
      else{cell.removeAttribute('data-tip');cell.removeAttribute('tabindex')}
    });
  }
  if(labelCells.length){
    labelTips();
    var labelTimer=null;
    var relabel=function(){
      if(labelTimer)window.clearTimeout(labelTimer);
      labelTimer=window.setTimeout(labelTips,150);
    };
    window.addEventListener('resize',relabel);
    // A collapsed <details> measures nothing, so the rows inside the appendix and inside
    // "Details" are only measurable once someone opens them.  ``toggle`` does not bubble.
    document.addEventListener('toggle',relabel,true);
  }

  function announce(value){
    if(!status)return;
    status.textContent=value||'';
    if(statusTimer)window.clearTimeout(statusTimer);
    statusTimer=window.setTimeout(function(){status.textContent=''},2400);
  }
  function absolute(value){try{return new URL(value,window.location.href).href}catch(e){return window.location.href}}
  function legacyCopy(value){
    var area=document.createElement('textarea');
    area.value=value;area.setAttribute('readonly','');area.style.position='fixed';area.style.opacity='0';
    document.body.appendChild(area);area.select();
    var copied=false;try{copied=document.execCommand('copy')}catch(e){copied=false}
    area.remove();return copied?Promise.resolve():Promise.reject(new Error('copy failed'));
  }
  function copy(value){
    if(navigator.clipboard&&navigator.clipboard.writeText)return navigator.clipboard.writeText(value);
    return legacyCopy(value);
  }
  document.addEventListener('click',function(event){
    var button=event.target.closest&&event.target.closest('[data-share-angle]');
    if(!button)return;
    event.preventDefault();
    var url=absolute(button.getAttribute('data-share-url'));
    var landing=absolute(button.getAttribute('data-share-landing')||url);
    var angle=button.closest('.angle');
    var question=angle&&angle.querySelector('h2 span:last-child');
    var data={title:document.title,text:question?question.textContent:'',url:landing};
    var task=navigator.share?navigator.share(data):copy(url).then(function(){announce(strings.share_copied)});
    Promise.resolve(task).catch(function(error){
      if(error&&error.name==='AbortError')return;
      copy(url).then(function(){announce(strings.share_copied)},function(){announce(strings.share_failed)});
    });
  });

  var tabs=Array.prototype.slice.call(document.querySelectorAll('[data-kindtab]'));
  function syncStoryTabs(){
    var selected=tabs.filter(function(item){return item.getAttribute('aria-selected')==='true'});
    var active=selected.length?selected[0]:tabs[0];
    tabs.forEach(function(item){item.tabIndex=item===active?0:-1});
  }
  // Selection also moves without a click (a featured [data-angle] badge, a share deep
  // link), so the roving tabindex follows aria-selected instead of click events.
  var storyTabObserver=new MutationObserver(syncStoryTabs);
  tabs.forEach(function(tab,index){
    storyTabObserver.observe(tab,{attributes:true,attributeFilter:['aria-selected','class']});
    tab.addEventListener('keydown',function(event){
      var next=null;
      if(event.key==='ArrowRight'||event.key==='ArrowDown')next=(index+1)%tabs.length;
      if(event.key==='ArrowLeft'||event.key==='ArrowUp')next=(index+tabs.length-1)%tabs.length;
      if(event.key==='Home')next=0;if(event.key==='End')next=tabs.length-1;
      if(next===null)return;
      event.preventDefault();tabs[next].click();tabs[next].focus();
    });
  });
  if(tabs.length)syncStoryTabs();

  Array.prototype.slice.call(document.querySelectorAll('.tabs')).forEach(function(tablist,listIndex){
    tablist.setAttribute('role','tablist');
    var scope=tablist.closest('.modal-card')||document;
    var sideTabs=Array.prototype.slice.call(tablist.querySelectorAll('[data-tab]'));
    sideTabs.forEach(function(tab,index){
      var group=tab.getAttribute('data-tab');var panel=scope.querySelector('[data-panel="'+group+'"]');
      var tabId='m2-side-tab-'+listIndex+'-'+index;var panelId='m2-side-panel-'+listIndex+'-'+index;
      tab.id=tabId;tab.setAttribute('role','tab');tab.setAttribute('aria-controls',panelId);
      if(panel){panel.id=panelId;panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby',tabId)}
      function sync(){
        sideTabs.forEach(function(item){var on=item.classList.contains('on');item.tabIndex=on?0:-1;item.setAttribute('aria-selected',on?'true':'false')});
      }
      new MutationObserver(sync).observe(tab,{attributes:true,attributeFilter:['class']});
      tab.addEventListener('keydown',function(event){
        var next=null;if(event.key==='ArrowRight'||event.key==='ArrowDown')next=(index+1)%sideTabs.length;
        if(event.key==='ArrowLeft'||event.key==='ArrowUp')next=(index+sideTabs.length-1)%sideTabs.length;
        if(event.key==='Home')next=0;if(event.key==='End')next=sideTabs.length-1;
        if(next===null)return;event.preventDefault();sideTabs[next].click();sideTabs[next].focus();
      });
      sync();
    });
  });

  var floatTip=document.getElementById('floattip');var tappedTip=null;
  // A control whose click *does* something — opens a modal, switches a tab, follows a
  // link — must not also print its tooltip when clicked: the bubble lands on top of
  // whatever the click just opened, which is exactly where the reader is now looking.
  // On those, the note belongs to hover — and to a long press,
  // which is what hover is on a touch screen.  A badge, whose only click behaviour is to
  // pin its own note, keeps the tap.
  var ACTION_TIP='a[href],button,summary,input,select,textarea,[data-open],[data-media],'+
    '[data-cluster],[data-sid],[data-article],[data-tab],[data-angle],[data-kindtab],'+
    '[data-tr-toggle],[data-apx-toggle],[data-share-angle],[data-clear]';
  function actionTip(node){return !!(node&&node.matches&&node.matches(ACTION_TIP))}
  function hideTappedTip(){if(tappedTip&&floatTip){floatTip.hidden=true}tappedTip=null}
  function showTipFor(tipped){
    if(!floatTip)return;
    tappedTip=tipped;floatTip.textContent=tipped.getAttribute('data-tip')||'';floatTip.hidden=false;
    var box=tipped.getBoundingClientRect();var left=Math.min(box.left,window.innerWidth-floatTip.offsetWidth-12);
    var top=Math.min(box.bottom+8,window.innerHeight-floatTip.offsetHeight-12);
    floatTip.style.left=Math.max(8,left)+'px';floatTip.style.top=Math.max(8,top)+'px';
  }
  var pressTimer=null,pressFired=false;
  document.addEventListener('touchstart',function(event){
    var tipped=event.target.closest&&event.target.closest('[data-tip]:not(.fnref)');
    if(!tipped)return;
    pressFired=false;
    pressTimer=window.setTimeout(function(){pressFired=true;showTipFor(tipped)},450);
  },{passive:true});
  ['touchmove','touchcancel'].forEach(function(name){
    document.addEventListener(name,function(){
      if(pressTimer)window.clearTimeout(pressTimer);pressTimer=null;
    },{passive:true});
  });
  document.addEventListener('touchend',function(){
    if(pressTimer)window.clearTimeout(pressTimer);pressTimer=null;
    // A long press that never produced a click (a context menu took it) must not eat the
    // reader's next tap.
    if(pressFired)window.setTimeout(function(){pressFired=false},600);
  },{passive:true});
  // The press showed the note; the click it turns into is not a command.
  document.addEventListener('click',function(event){
    if(!pressFired)return;
    pressFired=false;event.preventDefault();event.stopPropagation();
  },true);
  document.addEventListener('click',function(event){
    var tipped=event.target.closest&&event.target.closest('[data-tip]:not(.fnref)');
    // A tap anywhere else — or on a control that did something — dismisses a tapped
    // tooltip: mobile readers have no Escape key and no hover-out.
    if(!tipped||actionTip(tipped)){hideTappedTip();return}
    window.setTimeout(function(){
      if(!floatTip)return;
      if(tappedTip===tipped){hideTappedTip();return}
      showTipFor(tipped);
    },0);
  });

  function enhanceTimeline(){
    var dataNode=document.getElementById('article-index');var articleData={};
    try{articleData=JSON.parse(dataNode&&dataNode.textContent||'{}')}catch(e){articleData={}}
    Array.prototype.slice.call(document.querySelectorAll('.tl-canvas .dot-hit')).forEach(function(dot){
      var id=dot.getAttribute('data-article');var article=articleData[id]||{};
      // The visual/hit radius stays as laid out: dots sit 13-16px apart, so inflating
      // every hit circle to 44px makes neighbours occlude each other and most taps
      // open the wrong article.  Large touch targets come from the nearest-dot tap
      // delegation below instead.
      dot.setAttribute('tabindex','0');dot.setAttribute('role','button');
      dot.setAttribute('aria-label',[article.source,article.date,article.title].filter(Boolean).join(' · ')||id);
      if(dot.getAttribute('data-m2-keyboard'))return;dot.setAttribute('data-m2-keyboard','true');
      dot.addEventListener('keydown',function(event){
        if(event.key==='Enter'||event.key===' '){event.preventDefault();dot.dispatchEvent(new MouseEvent('click',{bubbles:true}))}
      });
    });
  }
  var timelineBox=document.getElementById('tl-canvas');
  if(timelineBox){new MutationObserver(enhanceTimeline).observe(timelineBox,{childList:true,subtree:true});enhanceTimeline()}
  if(timelineBox&&!timelineBox.getAttribute('data-m2-nearest')){
    timelineBox.setAttribute('data-m2-nearest','true');
    timelineBox.addEventListener('click',function(event){
      if(event.target.closest&&event.target.closest('[data-article]'))return;
      var svg=timelineBox.querySelector('svg');if(!svg||!svg.viewBox||!svg.viewBox.baseVal)return;
      var rect=svg.getBoundingClientRect();var view=svg.viewBox.baseVal;
      if(!rect.width||!rect.height||!view.width||!view.height)return;
      var best=null;var bestDist=Infinity;
      Array.prototype.slice.call(svg.querySelectorAll('.dot-hit')).forEach(function(dot){
        var cx=rect.left+parseFloat(dot.getAttribute('cx'))*rect.width/view.width;
        var cy=rect.top+parseFloat(dot.getAttribute('cy'))*rect.height/view.height;
        var dx=event.clientX-cx;var dy=event.clientY-cy;var dist=dx*dx+dy*dy;
        if(dist<bestDist){bestDist=dist;best=dot}
      });
      if(best&&bestDist<=22*22){best.dispatchEvent(new MouseEvent('click',{bubbles:true}))}
    });
  }

  function focusable(scope){
    return Array.prototype.slice.call(scope.querySelectorAll(
      'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'
    )).filter(function(node){return !node.hidden&&node.getClientRects().length});
  }
  // A modal that lives inside <main> is unreachable the moment it opens: opening one
  // makes <main> inert, and inertness is inherited — a descendant cannot opt back out.
  // The concept cloud's "what is this?" panel is rendered beside its own section, so it
  // could be opened and never closed.  Re-home every such panel before anything reads
  // them; element identity survives the move, so every handler bound above still holds.
  var mainRegion=document.querySelector('main');
  if(mainRegion){
    Array.prototype.slice.call(mainRegion.querySelectorAll('.modal')).forEach(function(modal){
      document.body.appendChild(modal);
    });
  }
  var modalNodes=Array.prototype.slice.call(document.querySelectorAll('.modal'));
  modalNodes.forEach(function(modal,index){
    var card=modal.querySelector('[role="dialog"]');var heading=card&&card.querySelector('h4,h3');
    if(card&&heading&&!card.hasAttribute('aria-labelledby')&&!card.hasAttribute('aria-label')){
      if(!heading.id)heading.id='m2-dialog-title-'+index;
      card.setAttribute('aria-labelledby',heading.id);
    }
  });
  // Which open modal is on top.  DOM order is not opening order: the shared record
  // panels (sentence, outlet, cluster) are emitted before the question modals, and
  // re-homing `main`'s modals to the end of `body` moves them further apart still.  So a
  // sentence card opened *from* an annotation table came last in time and first in the
  // document, was judged not-top, and was made `inert` — visible, above everything, and
  // impossible to click or close except with Escape.  The page script already stamps
  // each layer with a stacking level as it opens it; read that, and fall back to
  // document order only for a modal that has none.
  function openModals(){
    var open=Array.prototype.slice.call(document.querySelectorAll('.modal:not([hidden])'));
    return open.map(function(modal,index){
      return {modal:modal,level:parseInt(modal.style.zIndex,10)||0,index:index};
    }).sort(function(a,b){
      return a.level===b.level?a.index-b.index:a.level-b.level;
    }).map(function(entry){return entry.modal});
  }
  function syncModalA11y(){
    var open=openModals();
    var top=open.length?open[open.length-1]:null;
    var main=document.querySelector('main');if(main)main.inert=open.length>0;
    modalNodes.forEach(function(modal){
      modal.inert=!modal.hidden&&modal!==top;
      modal.setAttribute('aria-hidden',modal.hidden?'true':'false');
    });
    // The lock belongs to the document's state, not to any one handler's bookkeeping.
    document.body.style.overflow=open.length?'hidden':'';
    document.body.classList.toggle('modal-open',open.length>0);
  }
  var modalObserver=new MutationObserver(syncModalA11y);
  modalNodes.forEach(function(modal){modalObserver.observe(modal,{attributes:true,attributeFilter:['hidden','style']})});
  syncModalA11y();
  document.addEventListener('keydown',function(event){
    if(event.key==='Escape')tappedTip=null;
    if(event.key!=='Tab')return;
    var stackTop=openModals();var open=stackTop.length?stackTop[stackTop.length-1]:null;
    if(!open)return;
    var nodes=focusable(open);if(!nodes.length){event.preventDefault();return}
    var first=nodes[0],last=nodes[nodes.length-1];
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus()}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}
  });

  function revealHash(){
    if(location.hash.indexOf('#angle-')!==0)return;
    var target=document.getElementById(location.hash.slice(1));if(!target)return;
    var panel=target.closest('[data-kindpanel]');
    if(panel&&panel.hidden){
      var tab=document.querySelector('[data-kindtab="'+panel.getAttribute('data-kindpanel')+'"]');
      if(tab)tab.click();
      // On hashchange the browser has already given up scrolling to a target that was
      // inside a hidden panel; scroll once it is revealed (cold loads retry on their
      // own after load).
      window.requestAnimationFrame(function(){target.scrollIntoView()});
    }
  }
  window.addEventListener('hashchange',revealHash);revealHash();
})();
"""

JS = _JS_TEMPLATE.replace("__LOCALE_NAMES_JSON__", _LOCALE_NAMES_JS)
