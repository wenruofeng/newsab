"""The page's whole stylesheet: one token system, three theme states.

Editorial text uses serif faces; controls, badges, labels and other interface furniture
use sans-serif faces.  The distinction is deliberate: a reading surface is not an excuse
to make every affordance look like body copy.

Three theme states, in this order, and every colour is defined in the first one:

* bare ``:root`` — the complete light palette;
* ``@media (prefers-color-scheme:dark)`` guarded by ``:root:not([data-theme="light"])`` —
  the system default;
* ``:root[data-theme="dark"]`` — an explicit choice, which must win in both directions.

Fonts come from Google Fonts with a full local fallback stack.  A preview is a local
file a reviewer may open on a plane: offline it must be plain, never broken.
"""

from __future__ import annotations

#: One family per script the halo's nine locales actually need beyond Latin/Cyrillic
#: (which "IBM Plex Sans"/"Source Serif 4" already cover) and Chinese (already loaded
#: above as the SC families).  ko/ja/hi/ar each get a serif and a sans so ``--serif``/
#: ``--sans`` stay meaningful reading faces in every script, not a silent fallback to the
#: browser default.  ru needs no
#: new family — Cyrillic ships in "IBM Plex Sans" and "Source Serif 4" already.
FONT_LINK = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?'
    "family=Source+Serif+4:opsz,wght@8..60,400;8..60,600;8..60,700"
    "&family=Noto+Serif+SC:wght@400;500;600"
    "&family=Noto+Sans+SC:wght@400;500;600"
    "&family=Noto+Serif+KR:wght@400;500;600"
    "&family=Noto+Sans+KR:wght@400;500;600"
    "&family=Noto+Serif+JP:wght@400;500;600"
    "&family=Noto+Sans+JP:wght@400;500;600"
    "&family=Noto+Serif+Devanagari:wght@400;500;600"
    "&family=Noto+Sans+Devanagari:wght@400;500;600"
    "&family=Noto+Naskh+Arabic:wght@400;500;600"
    "&family=Noto+Sans+Arabic:wght@400;500;600"
    "&family=IBM+Plex+Sans:wght@400;500;600"
    "&family=IBM+Plex+Mono:wght@400;500"
    '&display=swap" rel="stylesheet">'
)

CSS = """
:root{
  --serif:"Source Serif 4","Noto Serif SC",Georgia,"Songti SC",serif;
  --sans:"IBM Plex Sans","Noto Sans SC",system-ui,-apple-system,sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
  --paper:#FBFAF7; --panel:#FFFFFF; --ink:#14171A; --ink2:#41484E; --muted:#767D84;
  --rule:#E0DCD2; --accent:#8C2F1E;
  --a:#1D4E6B; --b:#8A5A16;
  --ok:#2F6B3B; --warn:#9A7211; --bad:#9A3A2E;
  --tip-bg:#1A1D20; --tip-ink:#F3F0EA;
  --a-soft:color-mix(in oklab, var(--a) 12%, var(--panel));
  --b-soft:color-mix(in oklab, var(--b) 14%, var(--panel));
  --a-line:color-mix(in oklab, var(--a) 32%, var(--panel));
  --b-line:color-mix(in oklab, var(--b) 34%, var(--panel));
  --sunk:color-mix(in oklab, var(--ink) 4%, var(--paper));
  /* Two surfaces the warm paper cannot supply, and the only two colours here that are
     stated as literals rather than mixed off it.  --answer-surface is the elevation an
     answer card sits at — one step above whatever module holds it, so the pair reads as
     cards wherever it is dropped, on a topic page or on the home grid.  --data-surface
     is the opposite step, one below, and it is achromatic on purpose: the bars drawn on
     it are a cool/warm pair, and any tint in the ground puts a thumb on one side. */
  --answer-surface:#FFFFFF;
  --data-surface:#F3F3F3;
  --page:62rem; --read:44rem;
}
/* Per-script reading faces.  ``:lang()`` matches on the ``<html
   lang>`` this page always carries, so a page's own declared language picks its own
   faces without a data attribute to keep in sync.  Higher specificity than the bare
   :root above by design — these override its Latin/SC defaults, never the other way. */
:root:lang(ko){
  --serif:"Noto Serif KR","Source Serif 4",Georgia,serif;
  --sans:"Noto Sans KR","IBM Plex Sans",system-ui,-apple-system,sans-serif;
}
:root:lang(ja){
  --serif:"Noto Serif JP","Source Serif 4",Georgia,serif;
  --sans:"Noto Sans JP","IBM Plex Sans",system-ui,-apple-system,sans-serif;
}
:root:lang(hi){
  --serif:"Noto Serif Devanagari","Source Serif 4",Georgia,serif;
  --sans:"Noto Sans Devanagari","IBM Plex Sans",system-ui,-apple-system,sans-serif;
}
:root:lang(ar){
  --serif:"Noto Naskh Arabic","Source Serif 4",Georgia,serif;
  --sans:"Noto Sans Arabic","IBM Plex Sans",system-ui,-apple-system,sans-serif;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --paper:#171B20; --panel:#1E242A; --ink:#E7E3DB; --ink2:#C4BFB6; --muted:#98A0A8;
    --rule:#363E46; --accent:#E08265;
    --a:#77AECD; --b:#D6A860;
    --ok:#6FAF7C; --warn:#D2A94A; --bad:#DE8272;
    --tip-bg:#E7E3DB; --tip-ink:#14171A;
    --a-soft:color-mix(in oklab, var(--a) 18%, var(--panel));
    --b-soft:color-mix(in oklab, var(--b) 18%, var(--panel));
    --a-line:color-mix(in oklab, var(--a) 40%, var(--panel));
    --b-line:color-mix(in oklab, var(--b) 40%, var(--panel));
    --sunk:color-mix(in oklab, var(--ink) 6%, var(--paper));
    --answer-surface:#262C33;
    --data-surface:#1C1C1C;
  }
}
:root[data-theme="dark"]{
  --paper:#171B20; --panel:#1E242A; --ink:#E7E3DB; --ink2:#C4BFB6; --muted:#98A0A8;
  --rule:#363E46; --accent:#E08265;
  --a:#77AECD; --b:#D6A860;
  --ok:#6FAF7C; --warn:#D2A94A; --bad:#DE8272;
  --tip-bg:#E7E3DB; --tip-ink:#14171A;
  --a-soft:color-mix(in oklab, var(--a) 18%, var(--panel));
  --b-soft:color-mix(in oklab, var(--b) 18%, var(--panel));
  --a-line:color-mix(in oklab, var(--a) 40%, var(--panel));
  --b-line:color-mix(in oklab, var(--b) 40%, var(--panel));
  --sunk:color-mix(in oklab, var(--ink) 6%, var(--paper));
  --answer-surface:#262C33;
  --data-surface:#1C1C1C;
}

*{box-sizing:border-box;margin:0;padding:0}
/* a tooltip that makes the scrollbar appear moves the element out from under the
   cursor, which hides the tooltip, which… — reserve the gutter and the loop cannot start */
html{scrollbar-gutter:stable;-webkit-text-size-adjust:100%;scroll-behavior:smooth}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
body{background:var(--paper);color:var(--ink);font-family:var(--serif);
     font-size:17px;line-height:1.65;-webkit-font-smoothing:antialiased}
a{color:var(--accent);text-decoration-thickness:1px;text-underline-offset:2px}
a:hover{color:var(--ink)}
summary::-webkit-details-marker{display:none}
::selection{background:var(--a-soft);color:var(--ink)}
strong{font-weight:600}

/* The only page-level control: theme floats without consuming the reading column. */
.theme-fab{position:fixed;z-index:45;top:1rem;right:1rem;width:2.75rem;height:2.75rem;
       display:flex;align-items:center;justify-content:center;border:1px solid var(--rule);
       border-radius:50%;background:var(--panel);color:var(--ink2);cursor:pointer;
       box-shadow:0 5px 18px rgba(0,0,0,.12)}
.theme-fab:hover{color:var(--ink);border-color:var(--ink2)}
.theme-fab svg{width:1.15rem;height:1.15rem;display:block}
.top-fab{position:fixed;z-index:44;
       right:max(1rem,calc(env(safe-area-inset-right) + .5rem));
       bottom:max(1rem,calc(env(safe-area-inset-bottom) + .5rem));
       width:2.75rem;height:2.75rem;display:flex;align-items:center;justify-content:center;
       border:1px solid var(--rule);border-radius:50%;background:var(--panel);color:var(--ink2);
       box-shadow:0 5px 18px rgba(0,0,0,.12);font:600 1.15rem/1 var(--sans);
       text-decoration:none;transition:opacity .14s ease,transform .14s ease}
.top-fab:hover{color:var(--ink);border-color:var(--ink2)}
.js .top-fab:not(.shown),body.modal-open .top-fab{opacity:0;transform:translateY(.5rem);
       pointer-events:none}
@media (prefers-reduced-motion:reduce){.top-fab{transition:none}}
.tbtn{font:500 11px/1 var(--sans);padding:.36rem .6rem;white-space:nowrap;
      border:1px solid var(--rule);border-radius:2px;background:none;color:var(--ink2);
      cursor:pointer}
.tbtn:hover{border-color:var(--ink2);color:var(--ink)}
main{width:min(var(--page),100%);margin:0 auto;
     padding:clamp(1.8rem,4vw,3.2rem) clamp(1rem,4vw,2.5rem) 4rem}

/* ------------------------------------------------------------------- title and intro */
.home-link{display:inline-flex;align-items:center;gap:.35rem;margin:0 0 1rem;
       font:500 12px/1.4 var(--sans);color:var(--muted);text-decoration:none}
.home-link:hover{color:var(--accent)}
header.head{max-width:none;margin:0 0 clamp(2rem,4vw,3rem);text-align:left}
h1{font:700 clamp(27px,3.6vw,42px)/1.2 var(--serif);letter-spacing:-.012em;
   text-wrap:pretty;margin-bottom:1.4rem}
/* The brief runs the page's full width, like every other block, and each fact carries a
   bullet: a centred 44rem column of unmarked lines read as one paragraph broken up by
   accident rather than as the list of separately-anchored facts it is. */
.intro{list-style:none;display:grid;gap:.6rem;max-width:none;margin-inline:0;
       text-align:left}
.intro li{display:grid;grid-template-columns:.55rem 1fr;gap:.55rem;padding:0}
.intro li::before{content:"";align-self:start;justify-self:center;width:.3rem;
       height:.3rem;margin-top:.62rem;border-radius:50%;background:var(--accent)}
.intro li .x{font:400 15.5px/1.65 var(--serif);color:var(--ink2);text-wrap:pretty}
/* One or two facts are a sentence, not a list. */
.intro.plain li{display:block;padding:0}
.intro.plain li::before{content:none}

/* ------------------------------------------------------------------- section shells */
.panel{background:var(--panel);border:1px solid var(--rule);border-radius:3px;
       padding:clamp(1rem,2.2vw,1.6rem);margin:0 0 clamp(2rem,4vw,3rem)}
.panel-head{display:flex;align-items:baseline;justify-content:space-between;gap:1rem;
       flex-wrap:wrap;margin-bottom:.15rem}
.panel-head h3{font:600 17px/1.4 var(--sans);letter-spacing:-.005em}
.section-title{display:inline-flex;align-items:center;gap:.48rem}
.section-title>svg{width:1.2em;height:1.2em;flex:none;color:var(--accent)}
.lede{font:400 12.5px/1.7 var(--sans);color:var(--muted);margin-bottom:1.2rem;
       max-width:var(--read)}
.helpbtn{display:inline-flex;align-items:center;justify-content:center;flex:none;
       width:1.75rem;height:1.75rem;border:1px solid var(--rule);border-radius:50%;
       background:var(--panel);color:var(--muted);cursor:pointer}
.helpbtn:hover{border-color:var(--ink2);color:var(--ink)}
.helpbtn svg{width:1.05rem;height:1.05rem;display:block}

/* --------------------------------------------------------------------------- badges */
.badge{display:inline-flex;align-items:center;gap:.35em;font:500 11px/1.55 var(--sans);
       letter-spacing:.02em;white-space:nowrap;padding:.12rem .45rem;border-radius:2px;
       border:1px solid var(--rule);color:var(--ink2);background:var(--panel);
       text-decoration:none}
.badge.rank{font-family:var(--mono);font-weight:600;font-size:10.5px;letter-spacing:.06em}
.badge.count{font-family:var(--mono);font-weight:500;font-size:10.5px;color:var(--muted);
       border-color:var(--rule);background:var(--sunk);padding:.12rem .45rem}
.badge.gtag{font-weight:600;font-size:10.5px;letter-spacing:.04em}
.badge.gtag.a{color:var(--a);background:var(--a-soft);border-color:var(--a-line)}
.badge.gtag.b{color:var(--b);background:var(--b-soft);border-color:var(--b-line)}
.badge.story{border-color:var(--accent);color:var(--accent);font-weight:600}
.badge.soft{border-style:dashed;color:var(--muted);background:none}
.badge.off{border-style:dashed;color:var(--muted);background:none;font-family:var(--mono);
       font-size:10px}
.dot-ok{width:.42rem;height:.42rem;border-radius:1px;background:var(--ok);flex:none}
.dot-warn{width:.42rem;height:.42rem;border-radius:1px;background:var(--warn);flex:none}
.dot-bad{width:.42rem;height:.42rem;border-radius:1px;background:var(--bad);flex:none}
button.badge{cursor:pointer}
button.badge:hover{border-color:var(--ink2);color:var(--ink)}
.badge.count:hover{color:var(--ink)}

/* JS moves tooltips into #floattip, so modal overflow and viewport edges cannot clip them. */
[data-tip]{cursor:help;position:relative}
button[data-tip],a[data-tip]{cursor:pointer}

/* --------------------------------------------------------------------- the timeline */
.tl-wrap{display:flex;align-items:flex-start;gap:.8rem}
.tl-legend{flex:none;display:flex;flex-direction:column}
.tl-legend span.slot{display:flex;align-items:center}
.tl-canvas{flex:1 1 auto;min-width:0}
.tl-canvas svg{display:block;width:100%;overflow:visible}
.tl-canvas .dot-hit{cursor:pointer}
.tl-canvas .dot-hit:hover + .dot{stroke:var(--accent);stroke-width:2}
.tl-canvas .tick{font:400 10px/1 var(--mono);fill:var(--muted)}
.tl-canvas .axis{stroke:var(--rule);stroke-width:1}
.tl-canvas .band{fill:var(--sunk)}
.tl-canvas .cursorlab{font:500 10px/1 var(--mono);fill:var(--muted)}
.timeline-head{justify-content:flex-start;align-items:center;gap:.75rem;margin-bottom:.15rem}
.timeline-head h3{font-size:clamp(20px,2.2vw,25px)}
.timeline-range{font:400 11px/1.5 var(--mono);color:var(--muted)}
.timeline-head .helpbtn{margin-left:auto}
.tl-foot{display:flex;flex-wrap:wrap;gap:.6rem;align-items:center;
       justify-content:center;margin-top:1.1rem;padding-top:.7rem;
       border-top:1px solid var(--rule)}
.tl-foot .sum{font:400 11.5px/1.6 var(--mono);color:var(--muted);text-align:center}

/* ------------------------------------------------------------------ storyline: tabs */
.storyline{position:relative;margin:0 0 clamp(2rem,4vw,3rem);
       padding:clamp(.9rem,2.4vw,1.5rem);border-radius:6px;
       background:var(--panel);
       box-shadow:inset 0 0 0 1px var(--rule)}
.story-head{align-items:center;margin-bottom:.15rem}
.story-head h2{font:600 clamp(20px,2.2vw,25px)/1.4 var(--sans);letter-spacing:-.005em}
.story-tabs{display:flex;justify-content:center;gap:.6rem;border-bottom:1px solid var(--rule);
       margin-bottom:clamp(1.4rem,3vw,2.2rem);flex-wrap:wrap}
.story-tabs button{font:600 clamp(17px,1.8vw,20px)/1.5 var(--sans);letter-spacing:.01em;
       background:none;border:none;border-bottom:2px solid transparent;
       padding:.55rem .9rem;cursor:pointer;color:var(--muted);white-space:nowrap;
       display:inline-flex;align-items:center;gap:.4rem;
       margin-bottom:-1px}
.story-tabs .kindicon{width:1.35rem;height:1.35rem;display:block;flex:none}
.story-tabs button .n{font-family:var(--mono);font-weight:500;font-size:.85em;
       margin-left:.3em;opacity:.8}
.story-tabs button:hover{color:var(--ink2)}
.story-tabs button.on{color:var(--ink);border-bottom-color:var(--accent)}
.story-tabs button.zero{color:color-mix(in oklab, var(--muted) 70%, var(--paper))}
.story-panel[hidden]{display:none}
.story-empty{max-width:var(--read);font:400 14.5px/1.75 var(--serif);color:var(--muted);
       border-left:2px solid var(--rule);padding:.4rem 0 .4rem 1rem;margin:1rem 0 2rem}

/* ---------------------------------------------------------------- storyline: angles */
.angle{margin:0 0 clamp(2.5rem,5vw,3.75rem);scroll-margin-top:4rem}
.angle:has(>details.qdata:not([open])){margin-bottom:clamp(1.35rem,2.7vw,2rem)}
.angle-top{display:flex;flex-wrap:wrap;gap:.3rem;align-items:center;margin-bottom:.55rem}
.angle-top .left{display:flex;flex-wrap:wrap;gap:.3rem;align-items:center}
.angle h2{font:600 clamp(21px,2.4vw,28px)/1.35 var(--serif);letter-spacing:-.008em;
       max-width:none;text-wrap:pretty;margin-bottom:1.1rem;display:grid;
       grid-template-columns:auto minmax(0,1fr);align-items:baseline;gap:.5rem}
.angle h2 .qm{font:600 clamp(19px,2.1vw,24px)/1 var(--sans);color:var(--accent);
       letter-spacing:0;
       flex:none}
.sig{flex:none;display:inline-flex;align-items:center;align-self:center;
       border:1px solid var(--rule);border-radius:2px;padding:.2rem;background:var(--panel);
       cursor:help}
.sig svg{width:1.05rem;height:1.05rem;display:block}
.sig.supported svg{color:var(--ok)}
.sig.weak svg{color:var(--warn)}

/* the two answer cards and the relation between them — the page's core visual */
.duo{display:grid;grid-template-columns:1fr auto 1fr;align-items:stretch;
       gap:0 .55rem;margin-bottom:1rem}
.acard{background:var(--answer-surface);border:1px solid var(--rule);border-top:3px solid var(--rule);
       border-radius:0 0 3px 3px;padding:.9rem 1rem 1.05rem;display:flex;
       flex-direction:column;align-items:center;justify-content:center;text-align:center;
       min-width:0;position:relative}
/* The card wears its side: the thicker top bar over a flat tint of the same colour, one
   step quieter than the badge's own --a-soft/--b-soft so both still read on it.  The
   tint sits on --answer-surface, not on the module below it, so the pair keeps the same
   lift whatever it is dropped on — the home grid's cards are the same three lines. */
.acard.a{border-top-color:var(--a);
       background:color-mix(in oklab,var(--a) 7%,var(--answer-surface))}
.acard.b{border-top-color:var(--b);
       background:color-mix(in oklab,var(--b) 8%,var(--answer-surface))}
.acard .ahead{display:flex;flex-wrap:wrap;gap:.3rem .45rem;align-items:center;justify-content:center;
       margin-bottom:.55rem}
.acard .acontrol{position:absolute;top:.72rem;right:.72rem;display:flex;gap:.3rem;
       align-items:center}
.acard .acontrol + .ahead{padding-left:2rem;padding-right:2rem}
.acard .acontrol .iconbtn{width:1.35rem;height:1.35rem;color:var(--muted)}
.acard .acontrol .iconbtn svg{width:.78rem;height:.78rem}
/* The answer is the sentence the reader came for; it was set smaller than the prose
   explaining it. */
.acard .alabel{font:600 clamp(17.5px,1.95vw,22px)/1.4 var(--serif);text-wrap:pretty;
       color:var(--ink)}
/* A side that said nothing is the same card without a side: the grey is mixed into the
   card's own surface, so it stays level with its neighbour instead of sinking back into
   the module. */
.acard.silent{background:color-mix(in oklab,var(--muted) 7%,var(--answer-surface));
       border-style:dashed;border-top-style:solid;
       border-top-color:color-mix(in oklab,var(--muted) 50%,var(--panel))}
.acard.silent .alabel{font:400 15.5px/1.6 var(--serif);color:var(--muted);
       font-style:italic}
.rel{display:flex;align-items:center;justify-content:center;flex:none;width:3.7rem;
       position:relative;min-height:3.1rem}
.rel .rel-leads{position:absolute;inset:50% 0 auto;transform:translateY(-50%);
       width:3.7rem;height:2.7rem;display:block;overflow:visible}
.rel .la{stroke:var(--a)}
.rel .lb{stroke:var(--b)}
.rel .muted{stroke:var(--muted)}
.relmark{position:relative;z-index:1;width:2.55rem;height:2.55rem;border-radius:50%;
       display:flex;align-items:center;justify-content:center;background:var(--panel);
       color:var(--ink2);border:1.6px solid var(--rule)}
.relmark.supported{border-color:var(--ok);box-shadow:0 0 0 3px color-mix(in oklab,var(--ok) 10%,transparent)}
.relmark.weak{border-color:color-mix(in oklab,var(--warn) 48%,var(--rule));
       border-style:dotted;border-width:1.4px;
       box-shadow:0 0 0 2px color-mix(in oklab,var(--warn) 4%,transparent)}
.relmark .kindicon{width:1.45rem;height:1.45rem;display:block}
.relmark .kindicon.flip{transform:scaleX(-1)}
/* Stacked, the relation remains upright and becomes a short connector between cards. */
@media (max-width:720px){
  .duo{grid-template-columns:1fr;gap:.35rem 0}
  .rel{width:auto;height:2.2rem}
  .rel .rel-leads{width:6rem;height:2.2rem;left:50%;right:auto;transform:translate(-50%,-50%)}
}

/* the writer's two columns, tight under the cards */
.comm{display:grid;grid-template-columns:1fr 3.7rem 1fr;gap:.9rem .55rem;
       margin:0 0 .2rem;max-width:none}
.comm:not(.joint) p:last-child{grid-column:3}
.comm.joint{grid-template-columns:1fr;max-width:none}
@media (max-width:720px){.comm{grid-template-columns:1fr}.comm:not(.joint) p:last-child{grid-column:1}}
.comm p{font:400 15px/1.7 var(--serif);color:var(--ink2);text-wrap:pretty;padding:0 1rem}
.comm p.silent{color:var(--muted);font-style:italic}
.comm .cmark{display:inline-block;width:.25rem;height:.9em;border-radius:1px;
       margin-right:.5em;vertical-align:-.05em}
.comm .cmark.a{background:var(--a)}
.comm .cmark.b{background:var(--b)}
.fnref{font:600 10px/1 var(--sans);color:var(--accent);background:none;border:none;
       vertical-align:super;margin-left:.15em;padding:.1em;cursor:pointer}
.fnref:hover{color:var(--ink);text-decoration:underline}
details.qdata{margin-top:1.8rem;border-top:1px solid var(--rule)}
details.qdata>summary{cursor:pointer;font:600 14px/1.5 var(--sans);color:var(--accent);
       letter-spacing:.01em;padding:0 0 0 .7rem;list-style:none;width:max-content;
       margin:-.78rem 0 .78rem auto;background:var(--panel)}
details.qdata>summary::before{content:"▸ ";font-family:var(--sans);font-size:1.35em;vertical-align:-.08em}
details.qdata[open]>summary::before{content:"▾ "}

/* ------------------------------------------------------------ the question data card
   Sunk out of the module that holds it, on the one achromatic surface in the palette:
   every row in here is a cool bar against a warm one, and the ground they share has to
   be neither. */
.qblock{padding:1.15rem 1.2rem 1.4rem;border:1px solid var(--rule);border-radius:3px;
       background:var(--data-surface)}
.appendix .qblock{margin:.2rem 0 1rem}
.angle .qblock{padding-top:1rem}
.qhead{display:flex;flex-wrap:wrap;gap:.3rem;align-items:center;margin-bottom:.65rem}
.qhead .grow{flex:1 1 auto}
.qtext{font:600 clamp(15px,1.4vw,18px)/1.5 var(--serif);color:var(--ink);
       margin-bottom:1rem;max-width:none;text-wrap:pretty}
.qtext .qm{font:600 17px/1 var(--sans);color:var(--accent);margin-right:.45rem}
.iconbtn{display:inline-flex;align-items:center;justify-content:center;flex:none;
       width:1.6rem;height:1.6rem;border:1px solid var(--rule);border-radius:2px;
       background:none;color:var(--ink2);cursor:pointer}
.iconbtn:hover{border-color:var(--ink2);color:var(--ink)}
.iconbtn svg{width:.95rem;height:.95rem;display:block}
.axis3{display:grid;grid-template-columns:minmax(0,1fr) minmax(6.5rem,13rem) minmax(0,1fr);
       gap:.45rem;align-items:center;padding:.22rem 0}
.axis3.rates{margin-bottom:.85rem}
.axis3 .cat{text-align:center;font:400 13px/1.45 var(--sans);color:var(--ink);
       overflow-wrap:anywhere;padding:0 .15rem}
.axis3.top .cat{font-weight:600}
.bf-left{display:flex;align-items:center;justify-content:flex-end;gap:.4rem;min-width:0}
.bf-right{display:flex;align-items:center;gap:.4rem;min-width:0}
.bar{height:.8rem;border-radius:1px;opacity:.55}
.bar.lead{opacity:1}
.bar.a{background:var(--a)}
.bar.b{background:var(--b)}
/* The silent side of a gap, drawn the way its answer card is: grey, because a bar in the
   side's own colour reads as that side's distribution and one cluster is not one. */
.bar.quiet,.bar.quiet.lead{background:var(--muted);opacity:.45}
.bn{font:500 10px/1 var(--mono);color:var(--muted);white-space:nowrap;flex:none}
@media (max-width:720px){
  .axis3{grid-template-columns:minmax(0,1fr) 6.5rem minmax(0,1fr)}
  .axis3 .cat{font-size:12px}
}

/* ------------------------------------------------------------------- concept cloud */
.cloudbox{position:relative;margin-top:clamp(3.5rem,7vw,5rem)}
.cc-grid{display:grid;grid-template-columns:1fr 1fr;gap:0}
.cloud-head{align-items:center;margin-bottom:.15rem}
.cloud-head h3{font-size:clamp(20px,2.2vw,25px)}
.cc-side{min-width:0}
.cc-side.b{border-left:1px solid var(--rule);padding-left:1.1rem}
.cc-side.a{padding-right:1.1rem}
.cc-h{display:flex;align-items:center;gap:.5rem;flex-wrap:wrap;padding-bottom:.55rem;
       border-bottom:1px solid var(--rule);margin-bottom:.7rem}
.cc-side.a .cc-h{justify-content:flex-end}
.cc-h small{font:400 11px/1.5 var(--mono);color:var(--muted)}
.cc-body{display:flex;flex-wrap:wrap;align-items:baseline;gap:.35rem .55rem}
.cc-side.a .cc-body{justify-content:flex-end}
.pill{font-family:var(--serif);line-height:1.3;border-radius:3px;
       padding:.14em .42em .18em;cursor:default;display:inline-flex;align-items:baseline;
       gap:.4em;max-width:100%;transition:opacity .12s ease,box-shadow .12s ease}
.pill .lbl{min-width:0;overflow-wrap:anywhere}
.pill .pct{flex:none;font:500 10px/1.6 var(--mono);opacity:.7;white-space:nowrap}
.pill.a{color:var(--a);background:var(--a-soft)}
.pill.b{color:var(--b);background:var(--b-soft)}
.cc-grid.hot .pill{opacity:.28}
.cc-grid.hot .pill.on{opacity:1;box-shadow:0 0 0 1px currentColor}
.pill:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.cc-foot{font:400 11.5px/1.7 var(--sans);color:var(--muted);margin-top:1.3rem;
       padding-top:.7rem;border-top:1px dotted var(--rule)}
@media (max-width:640px){
  .cc-side.a{padding-right:.4rem}.cc-side.b{padding-left:.4rem}
}

/* the floating panel both the cloud and the timeline hover use */
#floattip{position:fixed;z-index:80;max-width:24rem;background:var(--tip-bg);
       color:var(--tip-ink);font:400 12px/1.6 var(--sans);padding:.5rem .7rem;
       border-radius:3px;pointer-events:none;box-shadow:0 6px 20px rgba(0,0,0,.28)}
#floattip[hidden]{display:none}
#floattip .trow{display:grid;grid-template-columns:auto minmax(11rem,1fr);gap:1em;
       align-items:baseline;white-space:nowrap}
#floattip .ccdata{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:.65rem;
       align-items:baseline;text-align:right}
#floattip .ccmeasure{font-family:var(--mono);min-width:7.6rem;text-align:right}
#floattip .dim{opacity:.65}

/* -------------------------------------------------------------------- the appendix */
.appendix{margin-top:clamp(2.5rem,5vw,4rem);padding:clamp(.9rem,2.4vw,1.5rem);
       border:1px solid color-mix(in oklab,var(--ink) 10%,var(--rule));border-radius:6px;
       background:var(--panel)}
.appendix h2{font:600 clamp(20px,2.2vw,25px)/1.35 var(--sans);letter-spacing:-.005em}
.appendix .apx-head{display:flex;align-items:center;justify-content:space-between;
       gap:1rem;flex-wrap:wrap;margin-bottom:1.4rem}
.apx-toggle{width:1.85rem;height:1.85rem;border-radius:2px}
.qrow{border-top:1px solid var(--rule)}
.qrow>summary{cursor:pointer;list-style:none;display:flex;flex-wrap:nowrap;gap:.45rem .65rem;
       align-items:center;padding:.75rem 0}
.qrow>summary::-webkit-details-marker{display:none}
.qrow>summary:hover{color:var(--accent)}
.qrow>summary .qsum{font:600 clamp(16px,1.65vw,19px)/1.5 var(--serif);flex:1 1 16rem;min-width:0;
       text-wrap:pretty}
.qrow>summary .qsum .qm,.modal-meta .qm{font:600 .92em/1 var(--sans);color:var(--accent)}
.qrow>summary .chev{display:inline-flex;align-items:center;justify-content:center;
       color:var(--accent);flex:none;transition:transform .12s ease}
.qrow>summary .chev svg{width:1rem;height:1rem;display:block}
.qrow[open]>summary .chev{transform:rotate(90deg)}
.qrow[open]>summary{border-bottom:1px dotted var(--rule)}

/* ------------------------------------------------------------- annotation tables */
.tabs{display:flex;gap:.4rem;margin:.2rem 0 .8rem;flex-wrap:wrap}
.tabs button{font:500 11.5px/1.4 var(--sans);background:none;border:1px solid var(--rule);
       border-radius:2px;padding:.3rem .7rem;cursor:pointer;color:var(--ink2)}
.tabs button.on{background:var(--ink);border-color:var(--ink);color:var(--paper)}
.tabpanel[hidden]{display:none}
table.ann{width:100%;border-collapse:collapse;font:400 12px/1.6 var(--sans);
       margin:.3rem 0 1rem;table-layout:fixed}
table.ann th,table.ann td{border-bottom:1px solid var(--rule);padding:.4rem .45rem;
       vertical-align:top;text-align:left}
table.ann th{color:var(--muted);font-weight:600;white-space:nowrap}
table.ann td.meta{color:var(--muted);overflow-wrap:anywhere}
table.ann td.cat{overflow-wrap:anywhere}
table.ann td.anchors{color:var(--muted)}
table.ann col.meta{width:9.5rem}table.ann col.cat{width:10rem}
table.ann col.anchors{width:7.5rem}
table.ann tr.unaddressed td{color:var(--muted);font-style:italic}
.ann-scroll{overflow-x:auto}
button.media{font:inherit;color:var(--accent);background:none;border:none;padding:0;
       cursor:pointer;text-align:left;text-decoration:underline;
       text-decoration-style:dotted;text-underline-offset:2px}
button.clusterid{font:500 10px/1.5 var(--mono);color:var(--ink2);background:none;
       border:1px solid var(--rule);border-radius:2px;padding:.05rem .3rem;cursor:pointer}
button.clusterid:hover{border-color:var(--ink2);color:var(--ink)}

/* ------------------------------------------------------------------------ quotes */
blockquote{margin:.9rem 0 0;padding-left:.9rem;border-left:1px solid var(--rule)}
blockquote .q,blockquote .tx{font:400 14px/1.75 var(--serif);color:var(--ink2)}
body[data-tr="translated"] .q.has-tr{display:none}
body:not([data-tr="translated"]) .tx{display:none}
.qbtn{display:inline-flex;align-items:center;justify-content:center;vertical-align:middle;
       border:1px solid var(--rule);border-radius:2px;background:none;cursor:pointer;
       color:var(--accent);padding:.15rem .32rem;margin-left:.25rem;
       font:600 10px/1 var(--sans)}
.qbtn:hover{border-color:var(--accent)}
.qbtn svg{width:.8rem;height:.8rem;fill:currentColor;display:block}
details.more{margin-top:.9rem}
details.more>summary{cursor:pointer;font:500 11.5px/1.4 var(--sans);color:var(--accent);
       letter-spacing:.02em;list-style:none}

/* -------------------------------------------------------------------- report search */
.report-search{margin-top:clamp(3.5rem,7vw,5rem);padding:clamp(1rem,2.2vw,1.6rem);
       border:1px solid var(--rule);border-radius:3px;background:var(--panel)}
.search-head{display:flex;align-items:center;justify-content:space-between;gap:1rem;
       flex-wrap:wrap;margin-bottom:.15rem}
.search-head h2{font:600 clamp(20px,2.2vw,25px)/1.35 var(--sans);letter-spacing:-.005em}
.search-count{font:400 11px/1.5 var(--mono);color:var(--muted)}
.search-field{position:relative;display:flex;align-items:center;border:1px solid var(--rule);
       border-radius:3px;background:var(--paper);transition:border-color .12s ease,box-shadow .12s ease}
.search-field:focus-within{border-color:var(--accent);
       box-shadow:0 0 0 3px color-mix(in oklab,var(--accent) 10%,transparent)}
.search-field>svg{position:absolute;left:.9rem;width:1.15rem;height:1.15rem;color:var(--muted);
       pointer-events:none}
.search-field input{width:100%;min-height:3rem;border:0;outline:0;background:transparent;
       color:var(--ink);padding:.7rem 2.7rem .7rem 2.75rem;font:400 15px/1.5 var(--sans)}
.search-field input::placeholder{color:var(--muted);opacity:.82}
/* The browser's own cancel control is a colour emoji on WebKit; the site draws its own,
   the same one the home page's search field uses. */
.search-field input::-webkit-search-cancel-button{-webkit-appearance:none;display:none}
.search-field .search-clear{display:flex;align-items:center;justify-content:center;
       flex:none;width:2rem;height:2rem;margin-right:.5rem;border:0;border-radius:50%;
       background:none;color:var(--muted);cursor:pointer}
.search-field .search-clear[hidden]{display:none}
.search-field .search-clear:hover{color:var(--accent)}
.search-field .search-clear svg{width:1rem;height:1rem}
.search-status{min-height:1.2rem;margin:.55rem 0 0;font:400 11.5px/1.6 var(--sans);color:var(--muted)}
.search-status:empty{display:none}
/* The list keeps its own scroll, but it is a panel in the page's flow, not a modal:
   ``overscroll-behavior:contain`` stopped the wheel from chaining to the page, so once
   the results filled the viewport the page would not scroll at all while the pointer was
   over them — which is what "the page stops scrolling after a search" was. */
.search-results{list-style:none;margin:.7rem 0 0;border-top:1px solid var(--rule);
       max-height:min(36rem,70vh);overflow-y:auto}
.search-results[hidden]{display:none}
.search-results li{border-bottom:1px solid var(--rule)}
.search-result{position:relative;width:100%;display:grid;grid-template-columns:minmax(0,1fr) auto;
       gap:.2rem 1rem;text-align:left;border:0;background:none;color:var(--ink);
       padding:.8rem 2.2rem .8rem .15rem;cursor:pointer}
.search-result:hover{background:var(--sunk)}
.search-result:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.sr-title{grid-column:1;font:600 15.5px/1.45 var(--serif);text-wrap:pretty}
.sr-meta{grid-column:2;grid-row:1;font:400 10.5px/1.7 var(--mono);color:var(--muted);
       white-space:nowrap;text-align:right}
.sr-match{font-weight:800;color:var(--ink)}
.sr-hits{grid-column:1/-1;display:flex;gap:.35rem .65rem;align-items:center;flex-wrap:wrap;
       margin-top:.2rem}
.sr-hitgroup{display:inline-flex;gap:.3rem;align-items:center;min-width:0;flex:0 1 auto;
       font:400 10.5px/1.5 var(--sans);color:var(--muted)}
/* The group's own name must never be what gives way: a squeezed CJK label wraps one
   character per line and stands the words on end. The hit chips ellipsise instead. */
.sr-hitgroup b{font-weight:600;color:var(--ink2);flex:none;white-space:nowrap}
.sr-hit{display:inline-block;max-width:20rem;min-width:0;flex:0 1 auto;overflow:hidden;
       text-overflow:ellipsis;
       white-space:nowrap;border:1px solid var(--rule);border-radius:2px;padding:.04rem .32rem;
       color:var(--ink2);background:var(--paper)}
.sr-arrow{position:absolute;right:.6rem;top:50%;transform:translateY(-50%);
       font:400 1.4rem/1 var(--sans);color:var(--muted)}
@media (max-width:640px){
  .search-result{display:block;padding-right:1.8rem}
  .sr-title,.sr-meta{display:block;text-align:left;white-space:normal}
  .sr-meta{margin-top:.12rem}
  .sr-hit{max-width:14rem}
}

/* ------------------------------------------------------------------------ footer */
footer{margin-top:clamp(2.5rem,5vw,4rem);border-top:1px solid var(--rule);
       padding-top:1.2rem;display:flex;flex-wrap:wrap;gap:.6rem 1rem;
       align-items:center;justify-content:space-between;
       font:400 12px/1.7 var(--sans);color:var(--muted)}
footer .flinks{display:flex;gap:.5rem;flex-wrap:wrap}

/* ------------------------------------------------------------------------ modals */
.modal[hidden]{display:none}
.modal{position:fixed;inset:0;z-index:50;display:flex;align-items:center;
       justify-content:center;padding:1rem}
#srcmodal,#mediamodal{z-index:70}
.modal-backdrop{position:absolute;inset:0;background:rgba(10,12,14,.55)}
.modal-card{position:relative;background:var(--panel);border:1px solid var(--rule);
       border-radius:3px;max-width:36rem;width:100%;max-height:86vh;overflow-y:auto;
       padding:1.4rem 1.5rem;box-shadow:0 16px 50px rgba(0,0,0,.3)}
.modal-card.wide{max-width:58rem}
.modal-x{position:absolute;top:.5rem;right:.6rem;border:none;background:none;
       font:400 20px/1 var(--sans);color:var(--muted);cursor:pointer}
.modal-x:hover{color:var(--ink)}
.modal-meta{font:400 12px/1.5 var(--sans);color:var(--muted);margin-bottom:.35rem}
.modal-card h4{font:600 1.05rem/1.4 var(--serif);margin-bottom:.7rem;padding-right:1.5rem}
.modal-card h4.qmodal{font:600 15px/1.5 var(--serif)}
.modal-card h5{font:600 12.5px/1.5 var(--sans);color:var(--ink2);margin:1rem 0 .35rem;
       letter-spacing:.02em}
.modal-quote{border-left:2px solid var(--accent);font-size:1rem;margin:.3rem 0 0}
.modal-tr{color:var(--muted);font:400 .9rem/1.7 var(--serif);margin:.4rem 0 0 .9rem}
.modal-dl{display:grid;grid-template-columns:auto 1fr;gap:.3rem .9rem;margin:.9rem 0;
       font:400 12.5px/1.6 var(--sans)}
.modal-dl dt{color:var(--muted)}
.modal-out{display:inline-block;margin-top:.4rem;font:500 12.5px/1.4 var(--sans);
       color:var(--paper);background:var(--accent);border-radius:2px;padding:.5rem .9rem;
       text-decoration:none}
.modal-out:hover{color:var(--paper);opacity:.9}
.modal-fine{font:400 11px/1.6 var(--sans);color:var(--muted);margin-top:.8rem}
.modal-lede{font:400 13px/1.75 var(--sans);color:var(--ink2);margin-bottom:.6rem}
.modal-list{font:400 13px/1.75 var(--sans);margin:.2rem 0 .9rem 1.1rem}
.modal-list li{margin-bottom:.25rem}
.modal-p{font:400 13.5px/1.8 var(--sans);color:var(--ink2);margin-bottom:.7rem}
.modal-p strong{color:var(--ink)}
.stat-list{margin:.9rem 0 0 1.1rem;font:400 13.5px/1.75 var(--sans);color:var(--ink2)}
.stat-list li{padding-left:.25rem;margin-bottom:.85rem}
.stat-list p{margin:0}.stat-list .stat-sub{color:var(--muted);margin-top:.2rem}
.stat-list strong{color:var(--ink)}
.modal-runs{font:400 11px/1.9 var(--mono);color:var(--muted);overflow-wrap:anywhere}
.prov-list{margin:.8rem 0 0;border-top:1px solid var(--rule)}
.prov-item{display:grid;grid-template-columns:minmax(7.5rem,.32fr) minmax(0,1fr);
       gap:.5rem 1rem;padding:.8rem 0;border-bottom:1px solid var(--rule)}
.prov-item dt{font:600 12px/1.5 var(--sans);color:var(--ink2)}
.prov-item dd{min-width:0}
.prov-run{display:block;font:500 11.5px/1.6 var(--mono);color:var(--ink);
       overflow-wrap:anywhere}
.prov-meta{display:flex;flex-wrap:wrap;gap:.2rem .8rem;margin-top:.15rem;
       font:400 11px/1.6 var(--mono);color:var(--muted)}
.prov-model{color:var(--ink2);font-weight:500}
.prov-note{display:block;margin-top:.2rem;font:400 11.5px/1.6 var(--sans);color:var(--ink2)}
.prov-person{display:block;font:500 12.5px/1.6 var(--sans);color:var(--ink)}
@media(max-width:520px){.prov-item{grid-template-columns:1fr;gap:.2rem}}
.chips{display:flex;flex-wrap:wrap;gap:.3rem;align-items:center;margin:.15rem 0 .3rem}
.chip{font:400 11.5px/1.5 var(--sans);border:1px solid var(--rule);border-radius:2px;
       padding:.1rem .4rem;color:var(--ink2);background:var(--paper)}
.topics-tr{padding:0;margin-left:.25rem;overflow:hidden;color:var(--muted);
       align-items:stretch}
.topics-tr span{display:flex;align-items:center;padding:.2rem .38rem}
.topics-tr span.on{background:var(--accent);color:var(--panel)}
table.clist{width:100%;border-collapse:collapse;font:400 12.5px/1.6 var(--sans);
       margin:.4rem 0 0}
table.clist td,table.clist th{border-bottom:1px solid var(--rule);padding:.45rem .4rem;
       vertical-align:top;text-align:left}
table.clist th{font:600 11px/1.5 var(--sans);color:var(--muted);white-space:nowrap}
table.clist td.date{font:400 11px/1.7 var(--mono);color:var(--muted);white-space:nowrap}
table.clist button.title{font:inherit;color:var(--accent);background:none;border:none;
       padding:0;cursor:pointer;text-align:left}
table.clist .orig{font:500 9.5px/1.5 var(--mono);color:var(--ok);border:1px solid var(--ok);
       border-radius:2px;padding:0 .25rem;margin-left:.35rem;white-space:nowrap}

/* --------------------------------------------------------------------------- RTL
   Under dir="rtl" (Arabic today,
   the halo's only RTL locale) prose, controls and furniture all mirror — that is what
   `dir` is for, and nothing below fights it.  What must NOT mirror is layout that
   carries a content meaning rather than a text-flow one: which side is "A" and which is
   "B" in the answer duo and the writer's two columns, which half of a rate bar belongs
   to which side, which column of the concept cloud holds which side's vocabulary, and
   the timeline's x-axis, which is chronological, not a script convention.  web_gate
   asserts this directly: the duo's DOM-order-0 card must stay physically left of
   DOM-order-1 on every locale (`_COLUMN_GEOMETRY` / `left["x"] < rel["x"] < right["x"]`
   in packages/publish/newsab_publish/web_gate.py).  Each subtree below is forced back to
   `ltr` for its own item placement, then the actual prose leaves inside it back to `rtl`
   so Arabic text still shapes and aligns as Arabic. */
[dir="rtl"] .duo,
[dir="rtl"] .comm:not(.joint),
[dir="rtl"] .axis3,
[dir="rtl"] .cc-grid,
[dir="rtl"] .tl-wrap{direction:ltr}
[dir="rtl"] .acard{direction:rtl}
[dir="rtl"] .comm p{direction:rtl;text-align:right}
[dir="rtl"] .axis3 .cat{direction:rtl}
[dir="rtl"] .pill{direction:rtl}

/* Furniture that *should* mirror under RTL but was pinned to a physical edge rather
   than a logical one when the site only ever shipped LTR locales. */
[dir="rtl"] .theme-fab{right:auto;left:1rem}
[dir="rtl"] .top-fab{right:auto;
       left:max(1rem,calc(env(safe-area-inset-left) + .5rem))}
[dir="rtl"] .modal-x{right:auto;left:.6rem}
[dir="rtl"] .timeline-head .helpbtn{margin-left:0;margin-right:auto}
[dir="rtl"] .intro{text-align:right}
[dir="rtl"] table.ann th,[dir="rtl"] table.ann td{text-align:right}
[dir="rtl"] .search-field>svg{left:auto;right:.9rem}
[dir="rtl"] .search-field input{padding:.7rem 2.75rem .7rem 2.7rem}
[dir="rtl"] .search-field .search-clear{margin-right:0;margin-left:.5rem}
[dir="rtl"] .sr-arrow{right:auto;left:.6rem}
[dir="rtl"] blockquote{padding-left:0;padding-right:.9rem;border-left:0;
       border-right:1px solid var(--rule)}
[dir="rtl"] .comm .cmark{margin-right:0;margin-left:.5em}
[dir="rtl"] details.qdata>summary{margin:-.78rem auto .78rem 0}
"""
