"""The page's behaviour: modals, tabs, theme, and the client-rendered timeline.

Two things moved into JavaScript this round and one thing did not.

* **The timeline is drawn here, not on the server.**  Granularity, tick density, dot size
  and lane height all depend on how wide the reader's window actually is; a server-side
  flex layout can only guess, and the guess is what clipped the tick labels and made the
  two lanes different heights.  The renderer now ships the dates and this draws them.
* **Theme and original/translation remain page state**, but their controls do not occupy a
  top bar: theme floats in the upper-right and translation follows translated quotes. The
  preferences live in ``localStorage`` so a reviewer's choice survives a reload. Every access is wrapped:
  a private window that refuses storage must still render the page.

What did *not* move: every number, every label and every panel of prose is still built on
the server from the pinned artifacts.  Nothing below computes a statistic.
"""

from __future__ import annotations

JS = r"""
(function () {
  document.documentElement.classList.add('js');
  var STORE = 'newsab.prefs';

  function readPrefs() {
    try { return JSON.parse(localStorage.getItem(STORE) || '{}') || {}; }
    catch (e) { return {}; }
  }
  function writePref(key, value) {
    try {
      var all = readPrefs();
      all[key] = value;
      localStorage.setItem(STORE, JSON.stringify(all));
    } catch (e) { /* storage refused: the page still works, the choice just resets */ }
  }

  function payload(id) {
    var node = document.getElementById(id);
    if (!node) { return {}; }
    try { return JSON.parse(node.textContent); } catch (e) { return {}; }
  }

  // The stored theme/translation choice applies before anything else: island fetches
  // must never leave the page flashing the wrong theme (externalized islands make
  // startup async).
  var prefs = readPrefs();
  if (prefs.theme === 'dark' || prefs.theme === 'light') {
    document.documentElement.setAttribute('data-theme', prefs.theme);
  }
  if (prefs.tr === 'translated') { document.body.setAttribute('data-tr', 'translated'); }

  // ------------------------------------------------- data islands + language overlay
  // The four heavy islands may be externalized as content-hash-named JSON assets the
  // node references via ``data-src``.  The base data is language-neutral; the
  // inline ``lang-overlay`` island carries the per-language lookup maps, and hydration
  // below rebuilds exactly the structures the rest of this script always consumed.  An
  // inline island (no ``data-src``) is already hydrated and passes straight through.
  var overlay = payload('lang-overlay');

  function hydrateTopics(list) {
    var topics = overlay.topics || {};
    for (var i = 0; i < (list || []).length; i++) {
      var entry = list[i];
      entry.localized = topics[entry.pivot_en] || entry.pivot_en || entry.source_phrase || '';
    }
  }

  function hydrateRecord(card) {
    var sources = overlay.sources || {};
    card.source = sources[card.source_id] || card.source_id || '';
    if (card.topics) { hydrateTopics(card.topics); }
    return card;
  }

  function uniqueValues(values) {
    var seen = {}, out = [];
    for (var i = 0; i < values.length; i++) {
      var text = String(values[i] == null ? '' : values[i]).trim();
      if (!text || seen[text]) { continue; }
      seen[text] = true;
      out.push(text);
    }
    return out;
  }

  function hydrateSearchDoc(doc) {
    var sources = overlay.sources || {};
    var groupsMap = overlay.groups || {};
    var origins = overlay.origins || {};
    var questionsMap = overlay.questions || {};
    var categoriesMap = overlay.categories || {};
    var topicsMap = overlay.topics || {};
    var source = sources[doc.source_id] || '';
    var group = groupsMap[doc.group_id] || {};
    var originLabel = origins[doc.origin_code] || doc.origin_code || '';
    var phraseValues = [], phraseLabels = [];
    (doc.topics || []).forEach(function (topic) {
      var localized = topicsMap[topic.pivot_en] || '';
      phraseLabels.push(localized || topic.pivot_en || topic.source_phrase || '');
      phraseValues.push(topic.source_phrase, localized, topic.pivot_en);
    });
    var answerValues = [];
    (doc.answers || []).forEach(function (row) {
      if (row.category) { answerValues.push(categoriesMap[row.category] || row.category); }
      (row.texts || []).forEach(function (text) { answerValues.push(text); });
    });
    return {
      article: doc.article,
      title: doc.title || '',
      source: source,
      date: doc.date || '',
      group: group.short || group.label || doc.group_id || '',
      origin: originLabel,
      cluster: doc.cluster || '',
      phrases: uniqueValues(phraseValues),
      phrase_labels: uniqueValues(phraseLabels),
      questions: uniqueValues((doc.question_ids || []).map(function (qid) {
        return questionsMap[qid] || qid;
      })),
      answers: uniqueValues(answerValues),
      meta: uniqueValues([source, doc.date, doc.fetched, group.short, group.label,
        group.definition, originLabel, doc.wire_source, doc.cluster])
    };
  }

  function hydrateIsland(id, data) {
    var translations = overlay.translations || {};
    if (id === 'sentence-index') {
      for (var sid in data) {
        if (!Object.prototype.hasOwnProperty.call(data, sid)) { continue; }
        hydrateRecord(data[sid]);
        if (translations[sid]) { data[sid].translation = translations[sid]; }
      }
      return data;
    }
    if (id === 'article-index') {
      for (var aid in data) {
        if (Object.prototype.hasOwnProperty.call(data, aid)) { hydrateRecord(data[aid]); }
      }
      return data;
    }
    if (id === 'report-search-index') {
      return Array.isArray(data) ? data.map(hydrateSearchDoc) : [];
    }
    return data;
  }

  function loadIsland(id, done) {
    var empty = id === 'report-search-index' ? [] : {};
    var node = document.getElementById(id);
    if (!node) { done(empty); return; }
    var srcUrl = node.getAttribute('data-src');
    if (!srcUrl) { done(payload(id)); return; }
    fetch(srcUrl).then(function (response) {
      if (!response.ok) { throw new Error(String(response.status)); }
      return response.json();
    }).then(function (data) {
      return hydrateIsland(id, data);
    }).catch(function () {
      return empty;
    }).then(function (data) {
      // Later readers (the M2 layer re-parses ``article-index`` from the DOM) get the
      // hydrated bytes from the same node they always read.
      try { node.textContent = JSON.stringify(data); } catch (e) { /* display only */ }
      done(data);
    });
  }

  var index = {};
  var articles = {};
  var clusters = {};
  var reportSearch = [];
  var media = payload('media-index');
  var strings = payload('modal-strings');
  var src = document.getElementById('srcmodal');
  var mediaModal = document.getElementById('mediamodal');
  var clusterModal = document.getElementById('clustermodal');
  var stack = [];
  var topicsMode = 'source';
  var backToTop = document.getElementById('backtotop');

  var EXTERNAL_ISLANDS = ['sentence-index', 'article-index', 'cluster-index', 'report-search-index'];
  var loadedIslands = {};
  var pendingIslands = EXTERNAL_ISLANDS.length;
  EXTERNAL_ISLANDS.forEach(function (id) {
    loadIsland(id, function (data) {
      loadedIslands[id] = data;
      if (--pendingIslands) { return; }
      index = loadedIslands['sentence-index'] || {};
      articles = loadedIslands['article-index'] || {};
      clusters = loadedIslands['cluster-index'] || {};
      reportSearch = loadedIslands['report-search-index'] || [];
      init();
      document.documentElement.setAttribute('data-islands', 'ready');
    });
  });

  function init() {

  function reducedMotion() {
    return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  }

  function syncBackToTop() {
    if (!backToTop) { return; }
    var shown = window.scrollY > Math.max(320, window.innerHeight / 2) &&
      !document.body.classList.contains('modal-open');
    backToTop.classList.toggle('shown', shown);
    backToTop.tabIndex = shown ? 0 : -1;
    backToTop.setAttribute('aria-hidden', shown ? 'false' : 'true');
  }

  syncBackToTop();
  window.addEventListener('scroll', syncBackToTop, { passive: true });

  // ---------------------------------------------------------------- theme + language
  // The stored preference itself was applied before the islands loaded; here the
  // controls are synced to it.
  syncSwitches();

  function resolvedDark() {
    var set = document.documentElement.getAttribute('data-theme');
    if (set) { return set === 'dark'; }
    return !!(window.matchMedia && window.matchMedia('(prefers-color-scheme:dark)').matches);
  }

  function syncSwitches() {
    var translated = document.body.getAttribute('data-tr') === 'translated';
    var quoteToggles = document.querySelectorAll('[data-tr-toggle]');
    for (var i = 0; i < quoteToggles.length; i++) {
      quoteToggles[i].textContent = translated ? strings.tr_original : strings.tr_translated;
    }
    var theme = document.getElementById('themebtn');
    if (theme) {
      var use = theme.querySelector('use');
      if (use) { use.setAttribute('href', resolvedDark() ? '#i-sun' : '#i-moon'); }
    }
  }

  // -------------------------------------------------------------------------- modals
  function row(dl, term, value, attrs) {
    if (!value) { return; }
    var dt = document.createElement('dt'); dt.textContent = term;
    var dd = document.createElement('dd');
    if (attrs && attrs.node) { dd.appendChild(attrs.node); } else { dd.textContent = value; }
    dl.appendChild(dt); dl.appendChild(dd);
  }

  function clusterButton(clusterId, count) {
    var articleLabel = count === 1 ? strings.article : strings.articles;
    var label = clusterId + ' · ' + articleLabel.replace('{n}', count);
    if (!clusters[clusterId]) { return document.createTextNode(label); }
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'clusterid';
    btn.setAttribute('data-cluster', clusterId);
    btn.title = strings.cluster_tip;
    btn.textContent = label;
    return btn;
  }

  function topicChips(list) {
    if (!list || !list.length) { return null; }
    var wrap = document.createElement('span');
    wrap.className = 'chips';
    for (var i = 0; i < list.length; i++) {
      var chip = document.createElement('span');
      chip.className = 'chip';
      chip.setAttribute('data-pivot', list[i].pivot_en || '');
      chip.setAttribute('data-source', list[i].source_phrase || '');
      chip.setAttribute('data-localized', list[i].localized || list[i].pivot_en || '');
      chip.textContent = topicsMode === 'source'
        ? (list[i].source_phrase || list[i].localized || list[i].pivot_en || '')
        : (list[i].localized || list[i].pivot_en || list[i].source_phrase || '');
      wrap.appendChild(chip);
    }
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'qbtn topics-tr';
    btn.title = strings.topics_tip;
    btn.setAttribute('aria-label', strings.topics_tip);
    renderTopicsToggle(btn);
    wrap.appendChild(btn);
    return wrap;
  }

  function renderTopicsToggle(btn) {
    btn.innerHTML = '';
    var source = document.createElement('span');
    source.textContent = strings.topics_source;
    source.className = topicsMode === 'source' ? 'on' : '';
    var concept = document.createElement('span');
    concept.textContent = strings.topics_concept;
    concept.className = topicsMode === 'localized' ? 'on' : '';
    btn.appendChild(source); btn.appendChild(concept);
    btn.setAttribute('aria-pressed', topicsMode === 'localized' ? 'true' : 'false');
  }

  function fillSource(card) {
    var meta = src.querySelector('.modal-meta');
    meta.innerHTML = '';
    if (card.source_id && media[card.source_id]) {
      var link = document.createElement('button');
      link.type = 'button';
      link.className = 'media';
      link.setAttribute('data-media', card.source_id);
      link.title = strings.media_tip;
      link.textContent = card.source;
      meta.appendChild(link);
    } else {
      meta.appendChild(document.createTextNode(card.source));
    }
    meta.appendChild(document.createTextNode(
      ' · ' + card.date + ' · ' + (strings.origin[card.origin] || card.origin)));
    src.querySelector('h4').textContent = card.title;
    var quote = src.querySelector('.modal-quote');
    var tr = src.querySelector('.modal-tr');
    if (card.text) {
      quote.textContent = card.text; quote.hidden = false;
    } else {
      quote.textContent = ''; quote.hidden = true;
    }
    if (card.translation) { tr.textContent = card.translation; tr.hidden = false; }
    else { tr.textContent = ''; tr.hidden = true; }
    var dl = src.querySelector('.modal-dl');
    dl.innerHTML = '';
    if (card.paragraph) {
      row(dl, strings.position,
          strings.para.replace('{p}', card.paragraph).replace('{s}', card.sentence));
    }
    row(dl, strings.cluster, '1',
        { node: clusterButton(card.cluster, card.cluster_articles) });
    row(dl, strings.origin_label, (strings.origin[card.origin] || card.origin) +
        (card.wire_source ? ' (' + card.wire_source + ')' : ''));
    row(dl, strings.fetched, card.fetched);
    // The article record carries collection-stage concepts.  The sentence/original
    // record stays focused on the quoted text and its provenance.
    var chips = card.text ? null : topicChips(card.topics);
    if (chips) { row(dl, strings.topics, '1', { node: chips }); }
    var out = src.querySelector('.modal-out');
    out.href = card.url;
    out.textContent = strings.out;
  }

  function fillMedia(entry) {
    mediaModal.querySelector('h4').textContent = entry.name;
    var dl = mediaModal.querySelector('.modal-dl');
    dl.innerHTML = '';
    row(dl, strings.media_country, entry.country);
    row(dl, strings.media_lang, entry.lang);
    row(dl, strings.media_category, entry.category);
    row(dl, strings.media_beat, entry.beat_scope);
    var notes = mediaModal.querySelector('.modal-lede');
    notes.textContent = entry.notes || '';
    notes.hidden = !entry.notes;
    var out = mediaModal.querySelector('.modal-out');
    out.href = entry.url;
    out.textContent = strings.media_site;
  }

  // A cluster of one is not a list of one: it is that report, so open it directly.
  function openCluster(clusterId, trigger) {
    var entry = clusters[clusterId];
    if (!entry) { return; }
    var ids = entry.articles || [];
    if (ids.length === 1 && articles[ids[0]]) {
      fillSource(articles[ids[0]]);
      show(src, trigger);
      return;
    }
    var body = clusterModal.querySelector('tbody');
    body.innerHTML = '';
    var ordered = ids.slice().sort(function (x, y) {
      var ax = articles[x] || {}, ay = articles[y] || {};
      // Original reporting first: a wire item and its twelve reprints are one report,
      // and the reader is entitled to see which one of them did the reporting.
      var ox = ax.origin === 'original' ? 0 : 1, oy = ay.origin === 'original' ? 0 : 1;
      if (ox !== oy) { return ox - oy; }
      if ((ax.date || '') !== (ay.date || '')) { return (ax.date || '') < (ay.date || '') ? -1 : 1; }
      return x < y ? -1 : 1;
    });
    for (var i = 0; i < ordered.length; i++) {
      var art = articles[ordered[i]];
      if (!art) { continue; }
      var tr = document.createElement('tr');
      var tdOutlet = document.createElement('td');
      if (art.source_id && media[art.source_id]) {
        var mb = document.createElement('button');
        mb.type = 'button'; mb.className = 'media';
        mb.setAttribute('data-media', art.source_id);
        mb.textContent = art.source;
        tdOutlet.appendChild(mb);
      } else {
        tdOutlet.textContent = art.source;
      }
      var tdDate = document.createElement('td');
      tdDate.className = 'date';
      tdDate.textContent = art.date || '';
      var tdTitle = document.createElement('td');
      var tb = document.createElement('button');
      tb.type = 'button'; tb.className = 'title';
      tb.setAttribute('data-article', ordered[i]);
      tb.textContent = art.title || ordered[i];
      tdTitle.appendChild(tb);
      if (art.origin === 'original') {
        var tag = document.createElement('span');
        tag.className = 'orig';
        tag.textContent = strings.origin_original;
        tdTitle.appendChild(tag);
      }
      tr.appendChild(tdOutlet); tr.appendChild(tdDate); tr.appendChild(tdTitle);
      body.appendChild(tr);
    }
    clusterModal.querySelector('h4').textContent =
      strings.cluster_title + ' · ' + clusterId;
    show(clusterModal, trigger);
  }

  // The scroll lock is derived from the document, never from the stack's bookkeeping.
  // Anything that closes a modal by another route — or an opener clicked twice — used to
  // leave the page unscrollable with nothing on screen to explain it.
  function syncScrollLock() {
    var open = document.querySelectorAll('.modal:not([hidden])').length > 0;
    document.body.classList.toggle('modal-open', open);
    document.body.style.overflow = open ? 'hidden' : '';
    syncBackToTop();
  }

  function show(modal, trigger) {
    if (!modal) { return; }
    // Opening what is already open raises it instead of stacking a second entry: two
    // entries for one modal meant one close left the stack — and the scroll lock — on.
    for (var i = 0; i < stack.length; i++) {
      if (stack[i].modal === modal) { stack.splice(i, 1); break; }
    }
    // A record can open another record (annotation → cluster → article → outlet).
    // Give each newly opened layer a higher stacking level than the one it came from.
    modal.style.zIndex = String(50 + stack.length * 10);
    stack.push({ modal: modal, trigger: trigger || null });
    modal.hidden = false;
    syncScrollLock();
    var x = modal.querySelector('.modal-x');
    if (x) { x.focus(); }
  }

  function closeTop() {
    var top = stack.pop();
    if (!top) { return; }
    top.modal.hidden = true;
    top.modal.style.zIndex = '';
    syncScrollLock();
    if (top.trigger && top.trigger.focus) { top.trigger.focus(); }
  }

  // ------------------------------------------------------------------ the storyline tabs
  function selectStoryTab(kind, scroll) {
    var buttons = document.querySelectorAll('[data-kindtab]');
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].classList.toggle('on', buttons[i].getAttribute('data-kindtab') === kind);
      buttons[i].setAttribute('aria-selected',
        buttons[i].getAttribute('data-kindtab') === kind ? 'true' : 'false');
    }
    var panels = document.querySelectorAll('[data-kindpanel]');
    for (var j = 0; j < panels.length; j++) {
      panels[j].hidden = panels[j].getAttribute('data-kindpanel') !== kind;
    }
    if (scroll) { window.scrollTo({ top: scroll, behavior: 'instant' }); }
  }

  function gotoAngle(questionId) {
    var target = document.getElementById('angle-' + questionId);
    if (!target) { return; }
    var panel = target.closest('[data-kindpanel]');
    if (panel && panel.hidden) { selectStoryTab(panel.getAttribute('data-kindpanel')); }
    target.scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth', block: 'start' });
  }

  function selectModalTab(scope, groupId) {
    var buttons = scope.querySelectorAll('[data-tab]');
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].classList.toggle('on', buttons[i].getAttribute('data-tab') === groupId);
    }
    var panels = scope.querySelectorAll('.tabpanel');
    for (var j = 0; j < panels.length; j++) {
      panels[j].hidden = panels[j].getAttribute('data-panel') !== groupId;
    }
    var heading = scope.querySelector('[data-evidence-heading]');
    var selected = scope.querySelector('[data-tab="' + groupId + '"]');
    if (heading && selected) {
      heading.textContent = (heading.getAttribute('data-template') || '{answer}')
        .replace('{answer}', selected.getAttribute('data-answer') || '');
    }
  }

  function syncAppendixToggle() {
    var button = document.querySelector('[data-apx-toggle]');
    if (!button) { return; }
    var rows = document.querySelectorAll('.appendix details.qrow');
    var allOpen = rows.length > 0;
    for (var i = 0; i < rows.length; i++) {
      if (!rows[i].open) { allOpen = false; break; }
    }
    var label = button.getAttribute(allOpen ? 'data-collapse-label' : 'data-expand-label');
    var use = button.querySelector('use');
    if (use) { use.setAttribute('href', allOpen ? '#i-collapse-all' : '#i-expand-all'); }
    button.setAttribute('aria-label', label || '');
    button.title = label || '';
  }

  syncAppendixToggle();
  document.addEventListener('toggle', function (event) {
    if (event.target.matches && event.target.matches('.appendix details.qrow')) {
      syncAppendixToggle();
    }
  }, true);

  document.addEventListener('click', function (event) {
    var tipped = event.target.closest('[data-tip]');
    if (tipped && tipped.classList.contains('fnref')) {
      event.preventDefault();
      togglePinnedTip(tipped);
      return;
    }
    if (tipped) { suppressTip(tipped); }
    else if (tipPinned) { hideTip(); }

    var trBtn = event.target.closest('[data-tr-toggle]');
    if (trBtn) {
      event.preventDefault();
      var mode = document.body.getAttribute('data-tr') === 'translated' ? 'original' : 'translated';
      document.body.setAttribute('data-tr', mode);
      writePref('tr', mode);
      syncSwitches();
      return;
    }

    if (event.target.closest('#themebtn')) {
      event.preventDefault();
      var next = resolvedDark() ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      writePref('theme', next);
      syncSwitches();
      drawTimeline();
      return;
    }

    var topicsBtn = event.target.closest('.topics-tr');
    if (topicsBtn) {
      event.preventDefault();
      topicsMode = topicsMode === 'source' ? 'localized' : 'source';
      var chips = document.querySelectorAll('.chip[data-pivot]');
      for (var c = 0; c < chips.length; c++) {
        var pivot = chips[c].getAttribute('data-pivot');
        var source = chips[c].getAttribute('data-source');
        var localized = chips[c].getAttribute('data-localized');
        chips[c].textContent = topicsMode === 'source'
          ? (source || localized || pivot) : (localized || pivot || source);
      }
      var topicToggles = document.querySelectorAll('.topics-tr');
      for (var tt = 0; tt < topicToggles.length; tt++) {
        renderTopicsToggle(topicToggles[tt]);
      }
      return;
    }

    var storyTab = event.target.closest('[data-kindtab]');
    if (storyTab) {
      event.preventDefault();
      selectStoryTab(storyTab.getAttribute('data-kindtab'));
      storyTab.blur();
      hideTip();
      return;
    }

    var jump = event.target.closest('[data-angle]');
    if (jump) {
      event.preventDefault();
      gotoAngle(jump.getAttribute('data-angle'));
      return;
    }

    var apx = event.target.closest('[data-apx-toggle]');
    if (apx) {
      event.preventDefault();
      var rows = document.querySelectorAll('.appendix details.qrow');
      var open = false;
      for (var ar = 0; ar < rows.length; ar++) {
        if (!rows[ar].open) { open = true; break; }
      }
      for (var r = 0; r < rows.length; r++) { rows[r].open = open; }
      syncAppendixToggle();
      return;
    }

    var tab = event.target.closest('[data-tab]');
    if (tab) {
      event.preventDefault();
      var scope = tab.closest('.modal-card') || document;
      selectModalTab(scope, tab.getAttribute('data-tab'));
      return;
    }

    var outlet = event.target.closest('[data-media]');
    if (outlet && mediaModal) {
      event.preventDefault();
      var entry = media[outlet.getAttribute('data-media')];
      if (entry) { fillMedia(entry); show(mediaModal, outlet); }
      return;
    }

    var clusterBtn = event.target.closest('[data-cluster]');
    if (clusterBtn && clusterModal) {
      event.preventDefault();
      openCluster(clusterBtn.getAttribute('data-cluster'), clusterBtn);
      return;
    }

    var quote = event.target.closest('[data-sid]');
    if (quote && src) {
      event.preventDefault();
      var card = index[quote.getAttribute('data-sid')];
      if (card) { fillSource(card); show(src, quote); }
      return;
    }

    var dot = event.target.closest('[data-article]');
    if (dot && src) {
      event.preventDefault();
      var article = articles[dot.getAttribute('data-article')];
      if (article) { fillSource(article); show(src, dot); }
      return;
    }

    var opener = event.target.closest('[data-open]');
    if (opener) {
      event.preventDefault();
      var opened = document.getElementById(opener.getAttribute('data-open'));
      var initialTab = opener.getAttribute('data-open-tab');
      if (opened && initialTab) { selectModalTab(opened, initialTab); }
      show(opened, opener);
      return;
    }

    if (event.target.closest('[data-close]')) { closeTop(); }
  });

  // ------------------------------------------------------------- the floating panel
  var tip = document.getElementById('floattip');
  var tipAnchor = null;
  var tipSuppressed = null;
  var tipPinned = null;

  function hideTip() {
    if (tip) { tip.hidden = true; }
    tipAnchor = null;
    tipPinned = null;
  }

  function suppressTip(target) {
    tipSuppressed = target;
    hideTip();
  }

  function showDataTip(target, x, y) {
    if (!tip || !target || target === tipSuppressed) { return; }
    if (tipPinned && target !== tipPinned) { return; }
    var value = target.getAttribute('data-tip');
    if (!value) { return; }
    tip.textContent = value;
    tip.hidden = false;
    tipAnchor = target;
    tipMove(x, y);
  }

  function togglePinnedTip(target) {
    if (tipPinned === target && tip && !tip.hidden) {
      hideTip();
      return;
    }
    tipSuppressed = null;
    tipPinned = target;
    var box = target.getBoundingClientRect();
    showDataTip(target, box.left + box.width / 2, box.bottom);
  }

  function tipMove(x, y) {
    if (!tip) { return; }
    var left = x + 14;
    if (left + tip.offsetWidth + 12 > window.innerWidth) { left = x - tip.offsetWidth - 14; }
    var top = y + 16;
    if (top + tip.offsetHeight + 12 > window.innerHeight) { top = y - tip.offsetHeight - 14; }
    tip.style.left = Math.max(8, Math.min(left, window.innerWidth - tip.offsetWidth - 12)) + 'px';
    tip.style.top = Math.max(8, Math.min(top, window.innerHeight - tip.offsetHeight - 12)) + 'px';
  }

  document.addEventListener('pointerover', function (event) {
    var target = event.target.closest && event.target.closest('[data-tip]');
    if (target) { showDataTip(target, event.clientX, event.clientY); }
  });
  document.addEventListener('pointermove', function (event) {
    if (tipAnchor && !tipPinned && tipAnchor !== tipSuppressed) {
      tipMove(event.clientX, event.clientY);
    }
  });
  document.addEventListener('pointerout', function (event) {
    var target = event.target.closest && event.target.closest('[data-tip]');
    if (target && (!event.relatedTarget || !target.contains(event.relatedTarget))) {
      if (tipSuppressed === target) { tipSuppressed = null; }
      if (tipAnchor === target && tipPinned !== target) { hideTip(); }
    }
  });
  document.addEventListener('focusin', function (event) {
    var target = event.target.closest && event.target.closest('[data-tip]');
    if (!target) { return; }
    var box = target.getBoundingClientRect();
    showDataTip(target, box.left + box.width / 2, box.bottom);
  });
  document.addEventListener('focusout', function (event) {
    if (tipAnchor && tipAnchor === event.target && tipPinned !== event.target) { hideTip(); }
  });

  // ------------------------------------------------------------------ the timeline
  var tl = payload('timeline-data');
  var tlBox = document.getElementById('tl-canvas');
  var tlLegend = document.getElementById('tl-legend');
  var SVGNS = 'http://www.w3.org/2000/svg';
  var tlState = null;

  function el(name, attrs) {
    var node = document.createElementNS(SVGNS, name);
    for (var key in attrs) {
      if (Object.prototype.hasOwnProperty.call(attrs, key)) {
        node.setAttribute(key, attrs[key]);
      }
    }
    return node;
  }

  function addDays(iso, days) {
    var parts = iso.split('-');
    var base = Date.UTC(+parts[0], +parts[1] - 1, +parts[2]);
    var moved = new Date(base + days * 86400000);
    var m = moved.getUTCMonth() + 1, d = moved.getUTCDate();
    return moved.getUTCFullYear() + '-' + (m < 10 ? '0' : '') + m + '-' + (d < 10 ? '0' : '') + d;
  }

  var MIN_COL = 12;
  var ROWS_TARGET = 6;
  var LANE_MIN = 48;
  var LANE_MAX = 118;

  function timelineUnits(span) {
    var values = [1];
    for (var day = 3; day <= Math.max(3, span + 2); day += 2) { values.push(day); }
    return values;
  }

  // One candidate layout: how the points fall into buckets at this bucket width, and how
  // big the dots and how tall the lanes have to be to hold the busiest bucket.
  function tlLayout(W, width) {
    var slots = Math.floor(tl.span / width) + 1;
    var colW = W / slots;
    var buckets = {};
    var maxCount = 1;
    for (var i = 0; i < tl.points.length; i++) {
      var p = tl.points[i];
      var key = Math.floor(p.d / width) + ':' + p.g;
      (buckets[key] = buckets[key] || []).push(p);
      if (buckets[key].length > maxCount) { maxCount = buckets[key].length; }
    }
    var dot = 10, gap = 4, cols = 1, rows = maxCount;
    var candidates = [12, 11, 10, 9];
    for (var c = 0; c < candidates.length; c++) {
      var size = candidates[c];
      var g = 4;
      var maxCols = Math.min(2, Math.max(1, Math.floor((colW + g) / (size + g))));
      var useCols = Math.min(maxCols, Math.max(1, Math.ceil(maxCount / ROWS_TARGET)));
      dot = size; gap = g; cols = useCols; rows = Math.ceil(maxCount / useCols);
      if (rows <= ROWS_TARGET) { break; }
    }
    return {
      width: width, slots: slots, colW: colW, buckets: buckets, maxCount: maxCount,
      dot: dot, gap: gap, cols: cols, rows: rows,
      laneH: Math.max(LANE_MIN, Math.max((dot + gap) * rows, dot + gap) + 6)
    };
  }

  function drawTimeline() {
    if (!tlBox || !tl.points) { return; }
    var W = tlBox.clientWidth;
    if (W < 60) { return; }

    // Granularity is chosen from the width in two steps: only bucket widths whose columns
    // still fit are candidates, and among those the finest one that keeps the lanes flat
    // wins.  A narrow window therefore coarsens the buckets rather than growing a tall
    // stack of dots — a wider column is what lets a busy bucket spread sideways.
    var options = [], units = timelineUnits(tl.span);
    for (var u = 0; u < units.length; u++) {
      if ((Math.floor(tl.span / units[u]) + 1) * MIN_COL <= W) {
        options.push(tlLayout(W, units[u]));
      }
    }
    if (!options.length) { options.push(tlLayout(W, units[units.length - 1])); }
    var plan = null;
    for (var o = 0; o < options.length; o++) {
      if (options[o].laneH <= LANE_MAX) { plan = options[o]; break; }
      if (!plan || options[o].laneH < plan.laneH) { plan = options[o]; }
    }
    var width = plan.width, slots = plan.slots, colW = plan.colW;
    var buckets = plan.buckets, dot = plan.dot, gap = plan.gap, cols = plan.cols;
    var step = dot + gap;
    // Both lanes are exactly as tall as the busiest one of them: the axis stays in the
    // middle of the picture whatever the two sides' volumes are.
    var laneH = plan.laneH;
    var topPad = 22, tickH = 18;
    var height = topPad + laneH * 2 + tickH;

    var svg = el('svg', {
      viewBox: '0 0 ' + W + ' ' + height, height: height,
      preserveAspectRatio: 'none', role: 'img'
    });
    svg.setAttribute('aria-label', tl.strings.title);

    var hover = el('g', {});
    svg.appendChild(hover);
    svg.appendChild(el('line', { x1: 0, y1: topPad + laneH, x2: W, y2: topPad + laneH, 'class': 'axis' }));

    for (var key2 in buckets) {
      if (!Object.prototype.hasOwnProperty.call(buckets, key2)) { continue; }
      var bits = key2.split(':');
      var slotIndex = +bits[0], side = +bits[1];
      var list = buckets[key2].slice().sort(function (x, y) {
        return x.d - y.d || (x.a < y.a ? -1 : 1);
      });
      var centre = (slotIndex + 0.5) * colW;
      var perRow = Math.min(cols, list.length);
      for (var k = 0; k < list.length; k++) {
        var rowIndex = Math.floor(k / perRow);
        var inRow = Math.min(perRow, list.length - rowIndex * perRow);
        var colIndex = k - rowIndex * perRow;
        var cx = centre + (colIndex - (inRow - 1) / 2) * step;
        var cy = side === 0
          ? topPad + laneH - (rowIndex + 0.5) * step
          : topPad + laneH + (rowIndex + 0.5) * step;
        var hit = el('circle', {
          cx: cx.toFixed(2), cy: cy.toFixed(2), r: 9,
          'class': 'dot-hit', fill: 'transparent'
        });
        hit.setAttribute('data-article', list[k].a);
        svg.appendChild(hit);
        var circle = el('circle', {
          cx: cx.toFixed(2), cy: cy.toFixed(2), r: (dot / 2).toFixed(2),
          'class': 'dot', fill: side === 0 ? 'var(--a)' : 'var(--b)', 'pointer-events': 'none'
        });
        circle.setAttribute('data-article', list[k].a);
        svg.appendChild(circle);
      }
    }

    var labelEvery = Math.max(1, Math.ceil(slots / Math.max(1, Math.floor(W / 62))));
    for (var s = 0; s < slots; s += labelEvery) {
      var day = addDays(tl.first, s * width);
      var text = el('text', {
        x: Math.min(Math.max((s + 0.5) * colW, 2), W - 2).toFixed(1),
        y: topPad + laneH * 2 + 13, 'class': 'tick',
        'text-anchor': s === 0 ? 'start' : (s + labelEvery >= slots ? 'end' : 'middle')
      });
      text.textContent = width >= 30 ? day.slice(0, 7) : day.slice(5);
      svg.appendChild(text);
    }

    tlBox.innerHTML = '';
    tlBox.appendChild(svg);
    tlState = { W: W, colW: colW, slots: slots, width: width, laneH: laneH,
      topPad: topPad, svg: svg, hover: hover };
    if (tlLegend) {
      tlLegend.style.paddingTop = topPad + 'px';
      var upSlot = tlLegend.querySelector('.slot.up');
      var downSlot = tlLegend.querySelector('.slot.down');
      if (upSlot) { upSlot.style.height = laneH + 'px'; }
      if (downSlot) { downSlot.style.height = laneH + 'px'; }
    }
  }

  function timelineHover(event) {
    if (!tlState) { return; }
    var box = tlState.svg.getBoundingClientRect();
    var x = (event.clientX - box.left) / box.width * tlState.W;
    var slot = Math.max(0, Math.min(tlState.slots - 1, Math.floor(x / tlState.colW)));
    tlState.hover.innerHTML = '';
    var label;
    tlState.hover.appendChild(el('rect', {
      x: (slot * tlState.colW).toFixed(1), y: tlState.topPad,
      width: tlState.colW.toFixed(1), height: tlState.laneH * 2, 'class': 'band'
    }));
    if (tlState.width === 1) {
      label = addDays(tl.first, slot);
    } else {
      var from = addDays(tl.first, slot * tlState.width);
      var to = addDays(tl.first, Math.min(slot * tlState.width + tlState.width - 1, tl.span));
      label = from + ' – ' + to;
    }
    var text = el('text', {
      x: Math.min(Math.max(x, 2), tlState.W - 2).toFixed(1), y: 10, 'class': 'cursorlab',
      'text-anchor': x > tlState.W - 70 ? 'end' : (x < 70 ? 'start' : 'middle')
    });
    text.textContent = label;
    tlState.hover.appendChild(text);
  }

  if (tlBox) {
    drawTimeline();
    var pending = null;
    window.addEventListener('resize', function () {
      if (pending) { clearTimeout(pending); }
      pending = setTimeout(drawTimeline, 120);
    });
    tlBox.addEventListener('mousemove', function (event) {
      timelineHover(event);
      var circle = event.target.closest ? event.target.closest('[data-article]') : null;
      if (circle && tip) {
        var card = articles[circle.getAttribute('data-article')];
        if (card) {
          tip.textContent = card.source + ' · ' + card.date + ' · ' + card.title;
          tip.hidden = false;
          tipMove(event.clientX, event.clientY);
        }
      } else if (tip) {
        tip.hidden = true;
      }
    });
    tlBox.addEventListener('mouseleave', function () {
      if (tlState) { tlState.hover.innerHTML = ''; }
      if (tip) { tip.hidden = true; }
    });
  }

  // ------------------------------------------------------------------ report search
  // Search only the metadata, concepts and annotations already exposed by this page.
  // The server-side payload never includes article body text.
  var searchInput = document.getElementById('report-search-input');
  var searchResults = document.getElementById('report-search-results');
  var searchStatus = document.getElementById('report-search-status');
  var searchCount = document.getElementById('report-search-count');
  var searchTimer = null;
  var SEARCH_LIMIT = 30;

  function searchFold(value) {
    var text = String(value || '');
    try { text = text.normalize('NFKC'); } catch (e) { /* older browser */ }
    return text.toLocaleLowerCase().replace(/\s+/g, ' ').trim();
  }

  function searchCompact(value) {
    return searchFold(value).replace(/[\s\-_/.,，。:：;；'"“”‘’()\[\]{}]+/g, '');
  }

  function searchJoin(values) {
    return searchFold((values || []).join(' '));
  }

  function searchContains(field, term) {
    if (field.indexOf(term) !== -1) { return true; }
    var compactTerm = searchCompact(term);
    return !!compactTerm && searchCompact(field).indexOf(compactTerm) !== -1;
  }

  var preparedSearch = Array.isArray(reportSearch) ? reportSearch.map(function (doc) {
    var title = searchFold(doc.title);
    var phrases = searchJoin(doc.phrases);
    var answers = searchJoin(doc.answers);
    var questions = searchJoin(doc.questions);
    var meta = searchJoin((doc.meta || []).concat([
      doc.source, doc.date, doc.group, doc.origin, doc.cluster
    ]));
    return {
      raw: doc, title: title, phrases: phrases, answers: answers,
      questions: questions, meta: meta,
      all: [title, phrases, answers, questions, meta].join(' ')
    };
  }) : [];

  function searchScore(doc, query, terms) {
    var score = 0;
    for (var i = 0; i < terms.length; i++) {
      var term = terms[i], best = 0;
      if (searchContains(doc.title, term)) { best = 42; }
      if (searchContains(doc.phrases, term)) { best = Math.max(best, 32); }
      if (searchContains(doc.answers, term)) { best = Math.max(best, 28); }
      if (searchContains(doc.questions, term)) { best = Math.max(best, 24); }
      if (searchContains(doc.meta, term)) { best = Math.max(best, 14); }
      if (!best || !searchContains(doc.all, term)) { return -1; }
      score += best;
    }
    if (doc.title === query) { score += 120; }
    else if (searchContains(doc.title, query)) { score += 55; }
    if (searchContains(doc.phrases, query)) { score += 38; }
    if (searchContains(doc.answers, query)) { score += 30; }
    if (searchContains(doc.questions, query)) { score += 24; }
    return score;
  }

  function matchingValues(values, terms) {
    var found = [];
    for (var i = 0; i < (values || []).length; i++) {
      var value = values[i];
      var folded = searchFold(value);
      for (var j = 0; j < terms.length; j++) {
        if (searchContains(folded, terms[j])) { found.push(value); break; }
      }
      if (found.length === 2) { break; }
    }
    return found;
  }

  function appendSearchHighlighted(parent, value, terms) {
    var text = String(value || '');
    var folded = searchFold(text);
    var ranges = [];
    // NFKC can change string length. In that rare case, keep the original text intact
    // rather than applying a highlight to the wrong character offsets.
    if (folded.length === text.length) {
      for (var i = 0; i < terms.length; i++) {
        var term = terms[i], offset = 0, at;
        if (!term) { continue; }
        while ((at = folded.indexOf(term, offset)) !== -1) {
          ranges.push([at, at + term.length]);
          offset = at + Math.max(term.length, 1);
        }
      }
    }
    if (!ranges.length) {
      parent.appendChild(document.createTextNode(text));
      return;
    }
    ranges.sort(function (left, right) {
      return left[0] === right[0] ? right[1] - left[1] : left[0] - right[0];
    });
    var merged = [];
    for (var j = 0; j < ranges.length; j++) {
      var last = merged.length ? merged[merged.length - 1] : null;
      if (last && ranges[j][0] <= last[1]) { last[1] = Math.max(last[1], ranges[j][1]); }
      else { merged.push(ranges[j].slice()); }
    }
    var cursor = 0;
    for (var k = 0; k < merged.length; k++) {
      if (merged[k][0] > cursor) {
        parent.appendChild(document.createTextNode(text.slice(cursor, merged[k][0])));
      }
      var strong = document.createElement('strong');
      strong.className = 'sr-match';
      strong.textContent = text.slice(merged[k][0], merged[k][1]);
      parent.appendChild(strong);
      cursor = merged[k][1];
    }
    if (cursor < text.length) { parent.appendChild(document.createTextNode(text.slice(cursor))); }
  }

  function addSearchHits(parent, label, values, terms) {
    if (!values.length) { return; }
    var group = document.createElement('span');
    group.className = 'sr-hitgroup';
    var name = document.createElement('b');
    name.textContent = label;
    group.appendChild(name);
    for (var i = 0; i < values.length; i++) {
      var hit = document.createElement('span');
      hit.className = 'sr-hit';
      appendSearchHighlighted(hit, values[i], terms);
      group.appendChild(hit);
    }
    parent.appendChild(group);
  }

  function renderSearchResult(doc, terms) {
    var li = document.createElement('li');
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'search-result';
    button.setAttribute('data-article', doc.article);
    button.setAttribute('aria-label', strings.search_open + ': ' + doc.title);

    var title = document.createElement('span');
    title.className = 'sr-title';
    appendSearchHighlighted(title, doc.title, terms);
    var meta = document.createElement('span');
    meta.className = 'sr-meta';
    appendSearchHighlighted(meta, [doc.source, doc.date]
      .filter(function (value) { return !!value; }).join(' · '), terms);
    var hits = document.createElement('span');
    hits.className = 'sr-hits';
    addSearchHits(hits, strings.search_phrases,
      matchingValues(doc.phrase_labels || doc.phrases, terms), terms);
    addSearchHits(hits, strings.search_answers,
      matchingValues((doc.answers || []).concat(doc.questions || []), terms), terms);
    var arrow = document.createElement('span');
    arrow.className = 'sr-arrow';
    arrow.setAttribute('aria-hidden', 'true');
    arrow.textContent = '›';

    button.appendChild(title);
    button.appendChild(meta);
    if (hits.childNodes.length) { button.appendChild(hits); }
    button.appendChild(arrow);
    li.appendChild(button);
    return li;
  }

  function runReportSearch() {
    if (!searchInput || !searchResults || !searchStatus) { return; }
    var query = searchFold(searchInput.value);
    searchResults.innerHTML = '';
    if (!query) {
      searchResults.hidden = true;
      searchCount.textContent = '';
      searchStatus.textContent = searchStatus.getAttribute('data-idle') || '';
      return;
    }
    var terms = query.split(' ').filter(function (term) { return !!term; });
    var matches = [];
    for (var i = 0; i < preparedSearch.length; i++) {
      var score = searchScore(preparedSearch[i], query, terms);
      if (score >= 0) { matches.push({ score: score, doc: preparedSearch[i].raw }); }
    }
    matches.sort(function (left, right) {
      if (left.score !== right.score) { return right.score - left.score; }
      if (left.doc.date !== right.doc.date) { return left.doc.date < right.doc.date ? 1 : -1; }
      return left.doc.title.localeCompare(right.doc.title);
    });

    var total = matches.length;
    var shown = Math.min(total, SEARCH_LIMIT);
    searchCount.textContent = strings.search_count.replace('{n}', total);
    if (!total) {
      searchResults.hidden = true;
      searchStatus.textContent = strings.search_none;
      return;
    }
    for (var j = 0; j < shown; j++) {
      searchResults.appendChild(renderSearchResult(matches[j].doc, terms));
    }
    searchResults.hidden = false;
    searchStatus.textContent = total > shown
      ? strings.search_more.replace('{shown}', shown).replace('{total}', total) : '';
  }

  var searchClear = document.getElementById('report-search-clear');

  function syncSearchClear() {
    if (searchClear) { searchClear.hidden = !(searchInput && searchInput.value); }
  }

  if (searchInput && searchResults && searchStatus) {
    searchInput.addEventListener('input', function () {
      syncSearchClear();
      if (searchTimer) { clearTimeout(searchTimer); }
      var base = parseInt(searchInput.getAttribute('data-search-delay'), 10) || 80;
      var extra = preparedSearch.length > 150 ? 35 : 0;
      if (searchInput.value.trim().length < 3) { extra += 25; }
      searchTimer = setTimeout(runReportSearch, base + extra);
    });
    if (searchClear) {
      searchClear.addEventListener('click', function () {
        searchInput.value = '';
        syncSearchClear();
        if (searchTimer) { clearTimeout(searchTimer); }
        runReportSearch();
        searchInput.focus();
      });
    }
    syncSearchClear();
    searchInput.addEventListener('search', function () {
      if (searchTimer) { clearTimeout(searchTimer); }
      runReportSearch();
    });
    searchInput.addEventListener('keydown', function (event) {
      if (event.key !== 'ArrowDown' || searchResults.hidden) { return; }
      var first = searchResults.querySelector('.search-result');
      if (first) { event.preventDefault(); first.focus(); }
    });
  }

  // ------------------------------------------------------------------ concept cloud
  // One concept lights up on both sides at once — the point of the section is where the
  // same word sits in each ranking — and the panel shows numbers only.
  var cloud = document.querySelector('.cc-grid');
  var cc = payload('concept-cloud-data');
  var ccPinned = null;

  function ccMark(key) {
    if (!cloud) { return; }
    cloud.classList.toggle('hot', !!key);
    var pills = cloud.querySelectorAll('.pill');
    for (var i = 0; i < pills.length; i++) {
      pills[i].classList.toggle('on', pills[i].getAttribute('data-k') === key);
    }
  }

  function ccFill(key) {
    tip.innerHTML = '';
    for (var i = 0; i < cc.order.length; i++) {
      var side = cc.sides[cc.order[i]];
      var entry = side.concepts[key];
      var trow = document.createElement('div');
      trow.className = 'trow';
      var who = document.createElement('span');
      who.textContent = side.short;
      var data = document.createElement('span');
      data.className = 'ccdata';
      var note = document.createElement('span');
      note.className = 'dim';
      var measure = document.createElement('span');
      measure.className = 'ccmeasure';
      if (entry) {
        note.textContent = entry.note || '';
        var n = document.createElement('b');
        n.textContent = entry.count;
        var pct = document.createElement('b');
        pct.textContent = entry.pct;
        measure.appendChild(n);
        measure.appendChild(document.createTextNode(' / ' + side.total + ' · '));
        measure.appendChild(pct);
      } else {
        var absent = document.createElement('span');
        absent.className = 'dim';
        absent.textContent = cc.strings.absent;
        measure.appendChild(absent);
      }
      data.appendChild(note);
      data.appendChild(measure);
      trow.appendChild(who);
      trow.appendChild(data);
      tip.appendChild(trow);
    }
  }

  function ccShow(key, x, y) {
    ccMark(key);
    ccFill(key);
    tip.hidden = false;
    tipMove(x, y);
  }

  function ccRest() {
    if (ccPinned) { ccMark(ccPinned); return; }
    ccMark(null);
    tip.hidden = true;
  }

  if (cloud && tip && cc.order) {
    cloud.addEventListener('mouseover', function (event) {
      var pill = event.target.closest('.pill');
      if (pill) { ccShow(pill.getAttribute('data-k'), event.clientX, event.clientY); }
      else { ccRest(); }
    });
    cloud.addEventListener('mousemove', function (event) {
      if (!tip.hidden && event.target.closest('.pill')) { tipMove(event.clientX, event.clientY); }
    });
    cloud.addEventListener('mouseleave', ccRest);
    cloud.addEventListener('focusin', function (event) {
      var pill = event.target.closest('.pill');
      if (!pill) { return; }
      var box = pill.getBoundingClientRect();
      ccShow(pill.getAttribute('data-k'), box.left, box.bottom);
    });
    cloud.addEventListener('focusout', ccRest);
    cloud.addEventListener('click', function (event) {
      var pill = event.target.closest('.pill');
      if (!pill) { return; }
      var key = pill.getAttribute('data-k');
      ccPinned = ccPinned === key ? null : key;
      if (ccPinned) {
        var box = pill.getBoundingClientRect();
        ccShow(key, box.left, box.bottom);
      } else {
        ccMark(null);
        tip.hidden = true;
      }
    });
  }

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
      hideTip();
      if (cloud) { ccPinned = null; ccRest(); }
      if (stack.length) { closeTop(); }
    }
  });
  }
})();
"""
