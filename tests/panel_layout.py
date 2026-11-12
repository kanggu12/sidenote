"""Words cut or standing out of their box, things on top of each other, and rows and columns a little off, measured on all the panel shows.

A look at some screenshots does not find a value two pixels off its column, and the older suites look at the parts they were written for,
so a label running into the tile beside it passed every one of them. This one reads the page as a browser laid it out, in every state of
every surface, at every size, and says what it found:

  cut       words a box with overflow hidden does not show all of. Allowed only where the whole of them is in a tooltip
  spill     words standing out of the box they are drawn in, or out of the window
  overlap   words over words, or over a key or a picture, where both are seen
  covered   words something else lies on, on their own layer; a band or a menu's words under the page
  rows      things on one line of a row that do not share a baseline or a middle, by a little: one to four pixels is a mistake, more is a choice
  columns   what should stand on one edge and does not: in a card, between the cards, in a list, in a table
  boxes     words not in the middle of the key, pill or tab they are on
  mixed     boxes of one kind in one group with their words aligned differently

The states are drawn through the page's own code, from what a server sends. The audit plants defects of each kind in a page and checks it
finds them (group "the audit itself"), because an audit that finds nothing looks like a panel with nothing wrong. Besides the audit: the panel's
parts, check by check, and motion: nothing loops at rest, what comes in comes to rest where it would have stood without moving.

ONLY="the audit,motion" picks groups; LAYOUT_SIZES=1920x1080,390x844 fewer sizes; AUDIT_REPORT=path writes every finding as JSON for reading through.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import panel_harness as h  # noqa: E402
from panel_harness import Page, Stand, row  # noqa: E402

T = h.Tally()
check = T.check
support = h.support
FOUND: list[dict] = []

# ---------------------------------------------------------------- the audit, run in the page
AUDIT = r"""
(opts) => {
  const out = [], W = innerWidth, H = innerHeight, ROUND = (v) => Math.round(v * 10) / 10;
  const note = (kind, el, detail, words = '') => out.push({ kind, where: name(el), detail, words: (words || '').trim().slice(0, 48) });
  function name(e) {
    if (!e || !e.tagName) return '';
    const bit = (x) => x.tagName.toLowerCase() + (x.id ? '#' + x.id : '') + (typeof x.className === 'string' && x.className ? '.' + x.className.trim().split(/\s+/).slice(0, 2).join('.') : '');
    const up = e.parentElement && e.parentElement !== document.body ? bit(e.parentElement) + ' > ' : '';
    return up + bit(e);
  }
  const shown = (e) => {
    for (let x = e; x && x !== document.documentElement; x = x.parentElement) {
      const c = getComputedStyle(x);
      if (c.display === 'none' || c.visibility === 'hidden' || +c.opacity < .05) return false;
      if (x.classList.contains('sr-only')) return false;
      if (x.parentElement?.tagName === 'DETAILS' && !x.parentElement.open && x.tagName !== 'SUMMARY') return false;   // a closed <details> keeps boxes for what it holds
      // Kept for a screen reader, in whichever way: a box of a pixel, or a clip of nothing
      if (c.position === 'absolute' && (c.clip === 'rect(0px, 0px, 0px, 0px)' || c.clipPath === 'inset(50%)' || (parseFloat(c.width) <= 1 && parseFloat(c.height) <= 1))) return false;
    }
    return e.getClientRects().length > 0;
  };
  const skip = (e) => e.closest('script, style, option, select, noscript, .katex-mathml, svg, #thumb');
  const paints = (c) => {
    const clear = (v) => v === 'transparent' || /rgba\([^)]*,\s*0\)$/.test(v);
    return !clear(c.backgroundColor) || c.backgroundImage !== 'none' || ['Top', 'Right', 'Bottom', 'Left'].some((s) => parseFloat(c['border' + s + 'Width']) > 0 && !clear(c['border' + s + 'Color']) && c['border' + s + 'Style'] !== 'none');
  };
  const canvas = document.createElement('canvas').getContext('2d');
  const ascent = (c) => { canvas.font = `${c.fontStyle} ${c.fontWeight} ${c.fontSize} ${c.fontFamily}`; return canvas.measureText('가').fontBoundingBoxAscent; };
  // The baseline as laid out: a box of nothing on the line stands on it. A flex or grid box would lay it out beside the words, so the font's own ascent is used there

  // What passes under a bar or a floating box is not laid over it: only things on one layer can be in each other's way
  const LAYERS = 'header.bar, #toast, .alerts, .composer, .menu, .overlay, .combo-list, .jump, .h-day, .doc-tip';
  const layerOf = (e) => e.closest(LAYERS) || document.body;
  // The part of a box that can be seen: cut by all that clips it on the way up
  const seenPart = (e, r) => {
    let l = r.left, t = r.top, ri = r.right, b = r.bottom;
    for (let a = e; a && a !== document.documentElement; a = a.parentElement) {
      const c = getComputedStyle(a);
      if (c.overflowX !== 'visible' || c.overflowY !== 'visible') {
        const o = a.getBoundingClientRect();
        if (c.overflowX !== 'visible') { l = Math.max(l, o.left); ri = Math.min(ri, o.right); }
        if (c.overflowY !== 'visible') { t = Math.max(t, o.top); b = Math.min(b, o.bottom); }
      }
    }
    return { left: l, top: t, right: ri, bottom: b, width: ri - l, height: b - t };
  };
  // ---- every run of words on the page, line by line
  const runs = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, { acceptNode: (n) => (n.nodeValue.trim() ? 1 : 2) });
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const e = n.parentElement;
    if (skip(e) || !shown(e)) continue;
    const range = document.createRange();
    range.selectNodeContents(n);
    let rects = [...range.getClientRects()].filter((r) => r.width > .5 && r.height > .5);
    if (!rects.length) continue;
    const c = getComputedStyle(e), size = parseFloat(c.fontSize);
    // Spaces hang past the end of a wrapped line of code and are not seen: each line goes as far as its last letter
    if (c.whiteSpace === 'pre-wrap' && n.nodeValue.length < 4000 && /\s\s|\s$/.test(n.nodeValue)) {
      const ends = new Map();
      for (let i = 0; i < n.length; i++) {
        if (!n.nodeValue[i].trim()) continue;
        const one = document.createRange(); one.setStart(n, i); one.setEnd(n, i + 1);
        const box = one.getBoundingClientRect();
        if (box.width) ends.set(Math.round(box.top), Math.max(ends.get(Math.round(box.top)) || 0, box.right));
      }
      rects = rects.map((r) => { const end = ends.get(Math.round(r.top)); return end ? new DOMRect(r.left, r.top, Math.max(0, end - r.left), r.height) : r; }).filter((r) => r.width > .5);
      if (!rects.length) continue;
    }
    runs.push({ node: n, e, rects, c, size, slack: Math.max(1, ...rects.map((r) => (r.height - size) / 2 + 1)), text: n.nodeValue, baseline: rects[0].top + ascent(c) });
  }

  // ---- cut and spill
  for (const run of runs) {
    let cut = null, spill = null;
    for (const r of run.rects) {
      const part = seenPart(run.e, r);
      if (part.width > 0 && (part.right > W + 1 || part.left < -1)) { spill = spill || `out of the window by ${ROUND(Math.max(part.right - W, -part.left))}`; }
      let edged = false;
      for (let a = run.e; a && a !== document.documentElement; a = a.parentElement) {
        const c = getComputedStyle(a), box = a.getBoundingClientRect();
        const ox = c.overflowX, oy = c.overflowY;
        const clipX = ox === 'hidden' || ox === 'clip', clipY = oy === 'hidden' || oy === 'clip';
        if (clipX || clipY) {
          const extraX = ox === 'clip' ? parseFloat(c.overflowClipMargin) || 0 : 0;
          const left = box.left + a.clientLeft - extraX, right = box.left + a.clientLeft + a.clientWidth + extraX, top = box.top + a.clientTop - run.slack, bottom = box.top + a.clientTop + a.clientHeight + run.slack;
          if (clipX && (r.right > right + 1 || r.left < left - 1)) cut = cut || { by: a, side: r.right > right + 1 ? `right ${ROUND(r.right - right)}` : `left ${ROUND(left - r.left)}` };
          if (clipY && (r.bottom > bottom || r.top < top)) cut = cut || { by: a, side: r.bottom > bottom ? `bottom ${ROUND(r.bottom - bottom)}` : `top ${ROUND(top - r.top)}` };
        }
        // Scrolled away is not cut: it can be scrolled to. And words past the edge of what scrolls cannot stand out of the box outside it
        if (ox === 'auto' || ox === 'scroll' || oy === 'auto' || oy === 'scroll' || clipX || clipY) break;
        if (!edged && c.display !== 'inline' && paints(c)) {
          edged = true;
          if (r.right > box.right + .5 || r.left < box.left - .5 || r.bottom > box.bottom + run.slack || r.top < box.top - run.slack) {
            const d = r.right > box.right + .5 ? `right ${ROUND(r.right - box.right)}` : r.left < box.left - .5 ? `left ${ROUND(box.left - r.left)}` : r.bottom > box.bottom + run.slack ? `bottom ${ROUND(r.bottom - box.bottom)}` : `top ${ROUND(box.top - r.top)}`;
            spill = spill || `out of ${name(a)}: ${d}`;
          }
        }
      }
    }
    if (cut) {
      const whole = run.text.trim(), tip = (run.e.closest('[title]')?.getAttribute('title') || '').replace(/\s+/g, ' ');
      const told = tip.includes(whole.replace(/\s+/g, ' ').slice(0, 30));
      note(told ? 'cut-told' : 'cut', run.e, `by ${name(cut.by)}: ${cut.side}`, whole);
    }
    if (spill) note('spill', run.e, spill, run.text);
  }
  // What is typed or waiting in a box: not a text node, so measured apart
  for (const e of document.querySelectorAll('input:not([type=checkbox]):not([type=radio]):not([type=range]), textarea')) {
    if (!shown(e)) continue;
    const c = getComputedStyle(e);
    canvas.font = `${c.fontStyle} ${c.fontWeight} ${c.fontSize} ${c.fontFamily}`;
    const said = e.value || e.placeholder || '';
    const room = e.clientWidth - parseFloat(c.paddingLeft) - parseFloat(c.paddingRight);
    if (said && !e.value && canvas.measureText(said).width > room + 1) note('cut', e, `its hint is ${ROUND(canvas.measureText(said).width)} wide in ${ROUND(room)}`, said);
  }
  // A box of one size holding a thing bigger than itself, not through words: a picture, a mark, a key
  for (const e of document.querySelectorAll('.rail .card *, .bar-in *, .composer *, .settings *, .menu *')) {
    if (skip(e) || !shown(e)) continue;
    if (!e.matches('button, input, textarea.words, .pill, .switch, img, .stat, .steps3, .meter, .bars, .gpu-viz, dd, dt, .h-tab')) continue;
    const r = e.getBoundingClientRect();
    if (!r.width) continue;
    const card = e.closest('.card, .bar-in, .composer, .menu, .settings');
    if (!card) continue;
    const b = card.getBoundingClientRect();
    if (r.right > b.right + .5 || r.left < b.left - .5) note('spill', e, `out of its ${name(card)} by ${ROUND(Math.max(r.right - b.right, b.left - r.left))}`, e.textContent);
  }

  // ---- overlap: both must be what is seen at the place they meet
  const top = (x, y) => document.elementsFromPoint(x, y);
  const lines = runs.flatMap((run, i) => run.rects.map((r) => ({ r: seenPart(run.e, r), run, i, layer: layerOf(run.e) }))).filter((l) => l.r.width > 1 && l.r.height > 1);
  lines.sort((a, b) => a.r.top - b.r.top);
  for (let i = 0; i < lines.length; i++) {
    const a = lines[i];
    for (let j = i + 1; j < lines.length; j++) {
      const b = lines[j];
      if (b.r.top >= a.r.bottom - 1.5) break;
      if (a.i === b.i || a.layer !== b.layer || (a.run.e.closest('.katex') && a.run.e.closest('.katex') === b.run.e.closest('.katex'))) continue;
      const w = Math.min(a.r.right, b.r.right) - Math.max(a.r.left, b.r.left), v = Math.min(a.r.bottom, b.r.bottom) - Math.max(a.r.top, b.r.top);
      const overlapMin = Math.min(a.run.size, b.run.size) * .35;
      if (w <= 1.5 || v <= overlapMin) continue;
      const x = (Math.min(a.r.right, b.r.right) + Math.max(a.r.left, b.r.left)) / 2, y = (Math.min(a.r.bottom, b.r.bottom) + Math.max(a.r.top, b.r.top)) / 2;
      const at = top(x, y);
      const has = (e) => at.some((p) => p === e || p.contains(e) || e.contains(p));
      if (!has(a.run.e) || !has(b.run.e)) continue;
      const first = at[0];
      if (first && !(first === a.run.e || first === b.run.e || first.contains(a.run.e) || first.contains(b.run.e) || a.run.e.contains(first) || b.run.e.contains(first))) continue;
      note('overlap', a.run.e, `over ${name(b.run.e)} "${b.run.text.trim().slice(0, 24)}" by ${ROUND(w)}x${ROUND(v)}`, a.run.text);
    }
  }
  const things = [...document.querySelectorAll('button, input, textarea.words, .pill, .switch, img, .steps3, .combo-btn, svg, .bars, .meter')].filter((e) => !e.closest('.katex, .md svg, figure.viz-chart') && shown(e) && e.getBoundingClientRect().width > 1);
  for (const t of things) {
    const b = seenPart(t, t.getBoundingClientRect()), layer = layerOf(t);
    if (b.width < 1 || b.height < 1 || b.right < 0 || b.bottom < 0 || b.left > W || b.top > H) continue;
    for (const l of lines) {
      if (t === l.run.e || t.contains(l.run.e) || l.run.e.contains(t) || l.layer !== layer) continue;
      const w = Math.min(b.right, l.r.right) - Math.max(b.left, l.r.left), v = Math.min(b.bottom, l.r.bottom) - Math.max(b.top, l.r.top);
      if (w <= 1.5 || v <= l.run.size * .35) continue;
      const x = (Math.min(b.right, l.r.right) + Math.max(b.left, l.r.left)) / 2, y = (Math.min(b.bottom, l.r.bottom) + Math.max(b.top, l.r.top)) / 2;
      if (x < 0 || y < 0 || x > W || y > H) continue;
      const at = top(x, y);
      const seen = (e) => at.some((p) => p === e || e.contains(p) || p.contains(e));
      if (!seen(l.run.e) || !seen(t)) continue;
      if (at[0] && !(at[0] === t || t.contains(at[0]) || at[0].contains(t) || at[0] === l.run.e || l.run.e.contains(at[0]) || at[0].contains(l.run.e))) continue;
      note('overlap', t, `over words "${l.run.text.trim().slice(0, 24)}" (${name(l.run.e)}) by ${ROUND(w)}x${ROUND(v)}`);
    }
  }

  // ---- covered: words something else lies on, on their own layer, or a floating thing's words under the page
  const RANK = (l) => (l === document.body ? 0 : l.matches('.h-day') ? 0 : l.matches('header.bar, .composer, .alerts, .jump') ? 1 : 2);
  for (const l of lines) {
    if (l.run.e.closest('.katex') || l.r.width < 3) continue;
    const x = (l.r.left + l.r.right) / 2, y = (l.r.top + l.r.bottom) / 2;
    if (x < 0 || y < 0 || x >= W || y >= H) continue;
    const f = top(x, y)[0];
    if (!f || f === l.run.e || f.contains(l.run.e) || l.run.e.contains(f)) continue;
    if (f.matches('.veil, .overlay') || getComputedStyle(l.run.e).pointerEvents === 'none') continue;   // a sheet's backdrop lies over all on purpose; what takes no pointer is not what the point can find
    const other = layerOf(f);
    if (other === l.layer ? !f.closest('button, a, input, summary') || !l.run.e.closest('button, a, summary') : RANK(other) < RANK(l.layer)) {
      if (other === l.layer || RANK(other) < RANK(l.layer)) note('covered', l.run.e, `under ${name(f)}`, l.run.text);
    }
  }

  // ---- words in the middle of what they are on
  for (const e of document.querySelectorAll('button:not(.h), .pill, .h-tab, .v-pin, .tag, .badge, .signal, .combo-btn, .ct-n')) {
    if (skip(e) || !shown(e)) continue;
    const c = getComputedStyle(e), b = e.getBoundingClientRect();
    if (!paints(c) || b.height > 60 || b.height < 12) continue;
    const rects = [];
    for (const n of e.childNodes) {
      const range = document.createRange();
      range.selectNodeContents(n);
      if (n.nodeType === 3 && !n.nodeValue.trim()) continue;
      if (n.nodeType === 1 && (n.matches('svg') || !shown(n))) continue;
      rects.push(...[...range.getClientRects()].filter((r) => r.width > .5));
    }
    if (!rects.length) continue;
    const t = Math.min(...rects.map((r) => r.top)), bo = Math.max(...rects.map((r) => r.bottom));
    if (bo - t > b.height + 1) continue;
    const off = (t + bo) / 2 - (b.top + b.bottom) / 2;
    if (Math.abs(off) > 1.25) note('boxes', e, `its words stand ${ROUND(off)} from the middle (${ROUND(b.height)} high)`, e.textContent);
    const l = Math.min(...rects.map((r) => r.left)), ri = Math.max(...rects.map((r) => r.right));
    if (l - b.left < 2.5 || b.right - ri < 2.5) note('boxes', e, `its words have ${ROUND(l - b.left)} and ${ROUND(b.right - ri)} beside them`, e.textContent);
  }

  // ---- rows: what stands on one line shares its baseline, and what stands in a row of keys its middle
  const rowOf = [...document.querySelectorAll(opts.rows)].filter(shown);
  // Each run's baseline measured once, and all of them at one layout: one probe put in and taken out per pair of runs made a page of
  // long answers take minutes, a layout each time
  const inRows = new Set();
  for (const holder of rowOf) for (const run of runs) if (holder.contains(run.e) && !run.e.closest('.katex')) inRows.add(run);
  const placed = [];
  for (const run of inRows) {
    const probe = document.createElement('span'), parent = run.node.parentNode;
    probe.style.cssText = 'display:inline-block;width:0;height:0;padding:0;margin:0;border:0';
    // In a flex or grid box the words are an item of their own: a span round them takes its place, with the box of nothing on their line
    const round = /flex|grid/.test(run.c.display) ? document.createElement('span') : null;
    if (round) { parent.insertBefore(round, run.node); round.append(probe, run.node); } else parent.insertBefore(probe, run.node);
    placed.push([run, probe, round, parent]);
  }
  for (const [run, probe] of placed) run.base = probe.getBoundingClientRect().bottom;
  for (const [run, probe, round, parent] of placed) { if (round) { parent.insertBefore(run.node, round); round.remove(); } else probe.remove(); }
  for (const holder of rowOf) {
    const inside = runs.filter((run) => holder.contains(run.e) && !run.e.closest('.katex'));   // a formula sets its own parts above and below its line
    for (let i = 0; i < inside.length; i++) for (let j = i + 1; j < inside.length; j++) {
      const a = inside[i], b = inside[j], ra = a.rects[0], rb = b.rects[0];
      if (a.e === b.e) continue;
      const v = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
      if (v < Math.min(ra.height, rb.height) * .5) continue;
      const d = Math.abs(a.base - b.base);
      if (d > .75 && d <= 5) note('rows', a.e, `baseline ${ROUND(d)} from ${name(b.e)} "${b.text.trim().slice(0, 20)}"`, a.text);
    }
    const keys = [...holder.querySelectorAll('button, .pill, .switch, input, .combo-btn, .steps3')].filter((e) => shown(e));
    for (let i = 1; i < keys.length; i++) {
      const a = keys[i - 1].getBoundingClientRect(), b = keys[i].getBoundingClientRect();
      if (Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) < 4) continue;
      const d = Math.abs((a.top + a.bottom) / 2 - (b.top + b.bottom) / 2);
      if (d > .75 && d <= 5) note('rows', keys[i], `middle ${ROUND(d)} from ${name(keys[i - 1])}`);
    }
  }

  // ---- columns: edges that should be one, and are nearly
  for (const group of opts.columns) {
    const [sel, edge, label, each] = group;
    // "@media (...) selector": only where the window is such (on a phone the margin's words stand over the writing, left-aligned)
    const media = each && /^@media (\([^)]*\)) (.*)$/.exec(each);
    if (media && !matchMedia(media[1]).matches) continue;
    const roots = each ? [...document.querySelectorAll(media ? media[2] : each)].filter(shown) : [document];
    for (const root of roots) {
      const items = [...root.querySelectorAll(sel)].filter((e) => !skip(e) && shown(e));
      const where = items.map((e) => {
        let r = e.getBoundingClientRect();
        if (edge.startsWith('text') && !e.matches('button')) {
          const range = document.createRange(); range.selectNodeContents(e);
          const rs = [...range.getClientRects()].filter((x) => x.width > .5);
          if (rs.length) r = edge.endsWith('right') ? { left: rs[0].left, right: Math.max(...rs.map((x) => x.right)) } : rs[0];
        }
        return { e, x: edge.endsWith('right') ? r.right : r.left };
      });
      for (let i = 0; i < where.length; i++) for (let j = i + 1; j < where.length; j++) {
        const d = Math.abs(where[i].x - where[j].x);
        if (d > (group[4] || .75) && d <= (group[5] || 6)) { note('columns', where[j].e, `${label}: ${ROUND(where[i].x)} against ${ROUND(where[j].x)} (${name(where[i].e)})`, where[j].e.textContent); }
      }
    }
  }

  // ---- gaps: one kind of thing at one distance from the next, in one group
  for (const [sel, each, label, most] of opts.gaps) {
    for (const root of [...document.querySelectorAll(each)].filter(shown)) {
      const laidOut = (e) => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden';   // not shown(): a card still fading in has its place all the same
      const items = [...root.querySelectorAll(sel)].filter(laidOut).map((e) => ({ e, r: e.getBoundingClientRect() })).sort((a, b) => a.r.top - b.r.top);
      const between = [];
      // Each against the nearest one above it in its own column (one it overlaps sideways): in two columns side by side the
      // one just before it by its top can be the other column's, and their distance is no gap of either (the rail at 2560)
      for (let i = 1; i < items.length; i++) {
        let j = i - 1;
        while (j >= 0 && !(items[i].r.left < items[j].r.right && items[i].r.right > items[j].r.left)) j--;
        if (j >= 0 && items[i].r.top >= items[j].r.bottom - 1) between.push({ d: items[i].r.top - items[j].r.bottom, e: items[i].e });
      }
      if (between.length < 2) continue;
      const ds = between.map((b) => b.d), low = Math.min(...ds), high = Math.max(...ds);
      if (high - low > (most || 1)) note('gaps', between[ds.indexOf(high)].e, `${label}: ${ds.map(ROUND).join(', ')}`);
    }
  }
  // ---- what a box leaves around what it holds: the same on the left as on the right
  for (const e of [...document.querySelectorAll('.rail .card')].filter(shown)) {
    const b = e.getBoundingClientRect(), c = getComputedStyle(e);
    if (Math.abs(parseFloat(c.paddingLeft) - parseFloat(c.paddingRight)) > .5) note('gaps', e, `a card's sides: ${c.paddingLeft} and ${c.paddingRight}`);
    const inside = [...e.children].filter(shown).map((x) => x.getBoundingClientRect()).filter((r) => r.height > 0);
    if (!inside.length) continue;
    const up = Math.min(...inside.map((r) => r.top)) - b.top, down = b.bottom - Math.max(...inside.map((r) => r.bottom));
    if (Math.abs(up - down) > 3) note('gaps', e, `a card's top and foot: ${ROUND(up)} and ${ROUND(down)} (${e.id || e.getAttribute('aria-label') || e.querySelector('h2')?.textContent.trim().slice(0, 10) || ''})`);
  }
  // ---- mixed: one kind of box in one group, its words aligned differently
  for (const sel of opts.mixed) {
    const items = [...document.querySelectorAll(sel)].filter(shown);
    const ways = new Set(items.map((e) => { const a = getComputedStyle(e).textAlign; return a === 'start' ? 'left' : a; }));
    if (ways.size > 1) note('mixed', items[0], `${sel}: ${[...ways].join(', ')}`);
  }
  // The window does not scroll sideways, whatever is in it
  const side = document.documentElement.scrollWidth - document.documentElement.clientWidth;
  if (side > 0) note('spill', document.documentElement, `the page scrolls sideways by ${side}`);
  return out;
}
"""

# The rows to read: each is a line of one kind of thing
ROWS = ".src-top, .fact, .k, .usage-sub, .bars-key, .agent-who, .agent-scale, .h, .h-day, .card > h2, .hist-tools, .bar-in, .composer, .tools, .codebar, .meta, .set-row, .settings header, .row:not(:has(.md)), .run, .v-flow, .ct-head, .alert:not(.confirm)"
# The columns: [what, which edge, what it is, per what (none: the whole page), least, most]
COLUMNS = [
    [".rail .card", "left", "the cards' left edge"], [".rail .card", "right", "the cards' right edge"],
    [".src-name, .card > h2, .fact.wide dt, .fact:first-child dt, .usage .stat:first-child, .agent-who, .agent-scale > .t > span, .bars-key, .usage-sub, .usage-err, .usage-none, .hist-tools, .h-tab, .gpu-viz", "left", "what starts a card's line", ".rail .card"],
    [".switch, .src-top .btn, .shot-tools .btn, #hist-export, #hear-kept, .gpu-viz, .usage-sub, .bars, .h-day, .usage-top, .agent-who", "right", "the keys and blocks on a card's right", ".rail .card"],
    [".heard-line time", "left", "the times of what was heard", "#heard"], [".heard-line > span", "left", "the words of what was heard", "#heard"],
    [".fact:not(.wide):first-child dd, .fact.wide dd, .agent-scale > .steps3, .stat:nth-child(2), .quota .q-bar", "text-left", "a fact's first value column", ".rail .card.engine", .75, 60],
    [".fact:nth-child(odd):not(.wide) dd", "text-left", "the values in the screen and sound rows", ".rail .card:not(.engine)", .75, 60],
    # The second half of every card, the screen's and the sound's second detail with the tiles' third figure (the groups' own scope has no box of its
    # own in one column, and side by side the two groups' halves stand far beyond the 30 px this compares); the pills stand beside
    # their names, so they have no column of their own
    [".stat:nth-child(3), .gpu-viz > div:nth-child(2) .k:first-child > span, .card.conn .fact:nth-child(even):not(.wide) dt", "text-left", "the second half of the cards", ".rail", .75, 30],
    [".agent-scale > .t > b", "left", "the scales' words", ".rail .card.engine", .75, 30],
    [".row > .mg", "text-right", "the margin's labels", "@media (min-width: 821px) .entry", .75, 12],
    [".row > .ct", "left", "the writing's edge", ".entry", .75, 12],
    [".v-terms > li", "left", "the cards' left edges in a column", ".md", .75, 3],
    [".codebar .lang, figure .viz-title", "text-left", "the captions' column", ".md[data-body]", .75, 6],
    [".h .ht", "left", "the rows' words", "#history"],
    ["h2 .n, .h-n, #hist-export", "text-right", "the contents' right edge", ".card.history", .75, 40],
    # the rows' times stand first, on one left edge
    [".h time", "text-left", "the rows' times", ".card.history", .75, 12],
    [".md > p, .md > ul, .md > h2, .md > h3, .md > .qa > p, .md > .tablewrap, .md > pre", "left", "an answer's blocks", ".entry", .75, 4],
    [".set-t", "left", "the settings' names", "#settings"],
    [".set-seg, .set-row .seg", "right", "the settings' keys", "#settings"],
]
MIXED = [".rail .stat", ".rail .fact dd", ".rail .h .ht"]
# [what, per what, what it is, how far apart they may differ]
GAPS = [[".rail .card", ".rail", "the cards' gaps", 1], [".agent-scale", "#card-agent", "the agent's scales", 1], [".entry", "#thread", "the answers", 1]]
OPTS = {"rows": ROWS, "columns": COLUMNS, "mixed": MIXED, "gaps": GAPS}


def audit(p, state, size, keep=("cut", "cut-told", "spill", "overlap", "covered", "rows", "columns", "boxes", "mixed", "gaps")) -> list:
    """Every finding on this page as it stands, each with what it was looking at."""
    got = p.js(AUDIT, OPTS)
    seen, res = set(), []
    for g in got:
        key = (g["kind"], g["where"], g["detail"])
        if key in seen:
            continue
        seen.add(key)
        if g["kind"] in keep:
            res.append({**g, "state": state, "size": size})
    return res


# ---------------------------------------------------------------- the states, drawn as a server would
EMAIL_LONG = "a.very.long.name.of.a.reader.that.goes.on.and.on@some-long-company-domain.example.com"
MODEL_LONG = "sidenote-gemma4-with-a-very-long-model-name-26b-instruct-q4_k_m"
ASK_LONG = "두 수열이 주어졌을 때 합이 가장 큰 연속 부분 배열의 시작과 끝을 찾고 그 합을 구하는 프로그램을 작성하고 시간 복잡도를 설명하시오 " * 2


def eng(**parts) -> dict:
    e = json.loads(json.dumps(h.ENGINES))
    for side, more in parts.items():
        e[side].update(more)
    return e


def status(p, e):
    p.send({"type": "status", "text": "connected", "paused": False, "lang": "auto", "audio": True, "voice": True, "can_ask": True, "run_enabled": True, "runner": True, "engines": e})


def capture(p, **more):
    now = p.js("() => Date.now() / 1000")
    p.send({**h.CAPTURE, "now": now, "last_frame": now - 2, "last_audio": now - 3, **more})


HUGE = {"type": "usage", "answers": 1, "engines": {
    "local": {"answers": 1234, "errors": 321, "last_error": 1793500000, "tokens_in": 987654321, "tokens_out": 123456789, "cost_usd": 0, "elapsed_p50": 512.5, "first_token_avg": 123.4, "tps_avg": 1234.5,
              "recent": [{"ts": 1793500000 + i * 60, "elapsed": 4.0 + i * 3, "first_token": 1.0 + i, "tps": 90.0 + i} for i in range(40)]},
    "agent": {"answers": 1234, "errors": 321, "last_error": 1793500000, "tokens_in": 98123456, "tokens_out": 12345678, "cost_usd": 12345.6789, "elapsed_p50": 512.5, "first_token_avg": 123.4, "tps_avg": 1234.5,
              "recent": [{"ts": 1793500000 + i * 60, "elapsed": 30.0 + i * 3, "first_token": 18.0 + i, "tps": 70.0 + i} for i in range(40)]}}}
NONE = {"type": "usage", "answers": 0, "engines": {"local": {"answers": 0}, "agent": {"answers": 0}}}


def many(n=30):
    # two of today's starred, so every state audits the star key on a head and the star on a row of the contents
    return [row(200 + i, ["mcq", "algorithm", "essay", "work", "code", "sql"][i % 6], f"이것은 꽤 길게 쓴 문제의 물음입니다 {i} " * 2, "답", "풀이", ago=86400 * (i // 7) + 1800 - i * 40, thumb=h.thumb(960, 540), region=[.2, .2, .6, .8],
                starred=i in (2, 5)) for i in range(n)]


def st_full(p):
    pass


def st_off(p):
    capture(p, clients=0)


def st_screen_off(p):
    capture(p, screen_on=False, caps={**h.CAPTURE["caps"]})


def st_audio_off(p):
    capture(p, audio_on=False)


def st_no_device(p):
    capture(p, caps={**h.CAPTURE["caps"], "no_audio": True, "audio": False})


def st_three_monitors(p):
    capture(p, caps={**h.CAPTURE["caps"], "monitor": 3, "monitors": [[3840, 2160], [1440, 2560], [7680, 4320]]})


def st_skipping(p):   # a window of Skip windows on screen: the screen card's caution, with its note
    capture(p, caps={**h.CAPTURE["caps"], "skipping": True})


def st_skip_limit(p):   # the windows cannot be read here: the same caution, with a longer note
    capture(p, caps={**h.CAPTURE["caps"], "skip_limit": "none"})


def st_local_loaded(p):
    status(p, eng(local={"loaded": {"model": "sidenote-gemma4:26b", "vram_gb": 16.2, "params": "26B", "quant": "Q4_K_M", "ctx": 32768}}))


def st_local_rest(p):
    status(p, eng(local={"loaded": None}))


def st_local_loading(p):
    status(p, eng(local={"loaded": None, "loading": True}))


def st_local_busy(p):
    status(p, eng(local={"busy": {"model": "sidenote-gemma4:4b-small", "until": p.js("() => Date.now() / 1000") + 300}}))


def st_local_missing(p):
    status(p, eng(local={"ok": False, "missing": True, "loaded": None}))


def st_local_down(p):
    status(p, eng(local={"ok": False, "why": "connection refused", "loaded": None}))


def st_local_long(p):
    status(p, eng(local={"model": MODEL_LONG, "loaded": {"model": MODEL_LONG, "vram_gb": 16.2, "params": "26B", "quant": "Q4_K_M", "ctx": 32768}}))


def st_agent_off(p):
    status(p, eng(agent={"mode": "off", "effective": "off"}))


def st_agent_login(p):
    status(p, eng(agent={"ok": False}))


def st_agent_expired(p):
    status(p, eng(agent={"ok": False, "rejected": True}))


def st_agent_gone(p):
    status(p, eng(agent={"present": False}))


def st_agent_limit(p):
    status(p, eng(agent={"limit_until": p.js("() => Date.now() / 1000") + 7200}))


def st_agent_brake(p):
    status(p, eng(agent={"brake": "시간당 전송 상한에 닿아 자동 전송을 잠시 멈췄습니다"}))


def st_agent_forced(p):
    status(p, eng(local={"on": False, "ok": True, "loaded": None}))


def st_agent_long(p):
    e = eng(agent={"model": "claude-opus-5-5-with-a-very-long-model-name-20270101", "account": {"email": EMAIL_LONG, "plan": "enterprise"}, "product": "Claude Code Enterprise Edition", "thinking": "adaptive-extended", "effort": "xhigh", "max_tokens": 1280000})
    status(p, e)


def st_agent_codex(p):
    status(p, eng(agent={"method": "chatgpt", "plan": "plus", "label": "Codex", "short": "Codex", "product": "Codex", "model": "gpt-5-codex", "effort": "high", "effort_own": False, "thinking": "", "max_tokens": 0, "account": {"email": "reader@example.com", "plan": "plus"}}))


def st_huge(p):
    p.send(HUGE)


def st_nothing_today(p):
    p.send(NONE)


def st_no_gpu(p):
    p.send({"type": "gpu", "none": True})


def st_gpu_full(p):
    for u in (100, 100, 3, 100):
        p.send({"type": "gpu", "used": 23028, "total": 23028, "util": u, "temp": 104, "power": 450})


def st_hearing(p):
    p.send({"type": "transcript", "text": "지금 들리는 말이 아주 길게 이어지는 경우입니다 " * 8, "lang": "ko", "final": False})


def st_heard_notes(p):
    # A sentence not taken with its line under it, the key to what is kept beside the card's state
    msg = support.settings_message()
    msg["values"]["speech_keep"] = True
    p.send(msg)
    p.send({"type": "transcript", "text": "노드를 먼저 비운 다음에 커널을 올렸습니다. GTID가 뭐?", "lang": "ko", "final": False})
    p.send({"type": "utterance", "text": "노드를 먼저 비운 다음에 커널을 올렸습니다.", "lang": "ko", "why": "none"})
    p.send({"type": "utterance", "text": "GTID가 뭐?", "lang": "ko", "why": "short"})


def st_toast(p):
    p.js("() => toast('아주 긴 안내 문구가 한 번에 나오는 경우입니다, 어디까지 보이는지 봅니다. ' + 'x'.repeat(60))")


def st_alert(p):
    p.send({"type": "error", "text": "서버와 통신 중 오류가 났습니다. " * 4})


def st_disconnected(p):
    p.drop()


def st_update(p):
    # a newer release found by the server: one line in the band, its link and its close key; the version in the menu
    p.send({"type": "status", "version": "0.1.0", "update": {"version": "0.1.2", "url": "https://github.com/kanggu12/sidenote/releases/tag/v0.1.2"}})


RAIL_STATES = {f.__name__[3:]: f for f in (st_full, st_heard_notes, st_off, st_screen_off, st_audio_off, st_no_device, st_three_monitors, st_skipping, st_skip_limit, st_local_loaded, st_local_rest, st_local_loading, st_local_busy, st_local_missing,
                                           st_local_down, st_local_long, st_agent_off, st_agent_login, st_agent_expired, st_agent_gone, st_agent_limit, st_agent_brake, st_agent_forced, st_agent_long,
                                           st_agent_codex, st_huge, st_nothing_today, st_no_gpu, st_gpu_full, st_hearing, st_toast, st_alert, st_disconnected, st_update)}
SIZES = [(1920, 1080), (1920, 1300), (2560, 1440), (1440, 900), (1366, 768), (1280, 720), (1100, 800), (1001, 700), (1000, 800), (768, 1024), (390, 844)]
if os.environ.get("LAYOUT_SIZES"):
    SIZES = [tuple(int(v) for v in x.split("x")) for x in os.environ["LAYOUT_SIZES"].split(",")]

# Answers of all the shapes an answer takes: what is long, what is wide, what has no place to break
LONGWORD = "supercalifragilistic" * 12
URL = "https://example.com/" + "a-very-long-path/" * 12 + "index.html?query=" + "x" * 80
ANSWERS = {
    "mcq": ("mcq", "다음 중 HTTP 메서드의 멱등성에 대한 설명으로 옳은 것은?", "3번", "- **1번** (오답): GET은 멱등하지 않습니다\n- **2번** (오답): POST는 멱등합니다\n- **3번** (정답): PUT은 멱등합니다\n- **4번** (오답): DELETE는 멱등하지 않습니다\n"),
    "algorithm": ("algorithm", "합이 가장 큰 연속 부분 배열", "카데인 알고리즘, 시간 O(N), 공간 O(1)", "## 접근\n\n1. **초기화**: 합을 0으로 둡니다\n2. **순회**: 원소를 더합니다\n3. **갱신**: 최댓값을 갱신합니다\n\n## 코드\n\n```python\ndef f(a):\n    best = cur = a[0]\n    for x in a[1:]:\n        cur = max(x, cur + x)\n        best = max(best, cur)\n    return best\n```\n\n시간 O(N), 공간 O(1)\n"),
    "table": ("work", "", "표로 비교합니다", "| 항목 | 빠름 | 느림 | 비고 |\n|---|---|---|---|\n| 지연 | 1 ms | 90 ms | 아주 긴 설명이 들어가는 칸입니다 아주 긴 설명이 들어가는 칸입니다 |\n| 비용 | 3 | 7 | 짧음 |\n| 안정 | 맞음 | 틀림 | " + LONGWORD[:80] + " |\n"),
    "wide_table": ("work", "", "넓은 표", "|" + "|".join(f" 칸 이름 {i} " for i in range(16)) + "|\n|" + "---|" * 16 + "\n|" + "|".join(f" 아주 긴 값 {i} " for i in range(16)) + "|\n"),
    "numbers": ("work", "", "수치 표", "| 번호 | 지연 | 값 |\n|---|---|---|\n| 1 | 10 ms | -1 |\n| 2 | 20 ms | 2 |\n| 3 | 40 ms | 3 |\n| 4 | 80 ms | 4 |\n"),
    "long_key": ("essay", ASK_LONG, ASK_LONG, "풀이"),
    "longword": ("essay", LONGWORD, LONGWORD, LONGWORD + "\n\n`" + LONGWORD + "`\n\n" + URL + "\n"),
    "url_key": ("work", URL, URL, "- " + URL + "\n"),
    "code_wide": ("code", "", "넓은 코드", "```python\n" + "x = '" + "y" * 400 + "'\n```\n\n`" + "z" * 200 + "`\n"),
    "flow": ("work", "", "연쇄", "SYN → SYN-ACK → ACK의 순서로 맺습니다.\n\n명시적 Deny → 아주 길게 쓴 Allow 이름입니다 아주 길게 쓴 Allow 이름입니다 → 기본 Deny\n\n" + " → ".join(f"단계이름{i}" for i in range(7)) + "\n"),
    "flow_key": ("work", "", "커넥션 풀 → 슬로우 쿼리 → 락", "풀이"),
    "tiles": ("essay", "", "1) 첫째 답 2) 둘째 답 3) 아주 길게 쓴 셋째 답입니다 아주 길게 쓴 셋째 답입니다 4) 넷째", "## (1) 물음\n\n글\n\n## (2) 물음\n\n글\n\n## (3) 물음\n\n글\n\n## (4) 물음\n\n글\n"),
    "map": ("essay", "", "부분이 많은 답", "\n\n".join(f"## {'아주 긴 제목 ' * (i % 3 + 1)}{i}\n\n글입니다." for i in range(9)) + "\n"),
    "terms": ("work", "", "이름과 설명", "- **이주 긴 이름 하나입니다 아주 긴 이름 하나입니다**: 설명\n- **짧음**: 아주 긴 설명이 이어집니다 " + "아주 긴 설명이 이어집니다 " * 6 + "\n- **" + LONGWORD[:40] + "**: " + LONGWORD[:60] + "\n"),
    "bigo": ("algorithm", "", "시간 O((N+M) log N log log N), 공간 O(N^2)", "시간 O((N+M) log N log log N), 공간 O(N^2)\n\n## 풀이\n\n글\n"),
    "bigo_same": ("algorithm", "", "시간 O(N), 공간 O(N)", "시간 O(N), 공간 O(N)\n"),
    "math": ("work", "", "수식", "$$\\sum_{i=1}^{N} \\frac{a_i^2 + b_i^2}{c_i} + \\sum_{i=1}^{N} \\frac{a_i^2 + b_i^2}{c_i} + \\sum_{i=1}^{N} \\frac{a_i^2 + b_i^2}{c_i} + \\sum_{i=1}^{N} \\frac{a_i^2 + b_i^2}{c_i} + \\sum_{i=1}^{N} \\frac{a_i^2 + b_i^2}{c_i}$$\n\n인라인 $x^2 + y^2 = z^2$ 입니다.\n"),
    "nested": ("work", "", "겹친 목록", "1. **겉**\n   - 안쪽 항목\n   - **안쪽 이름**: 설명\n     - 더 안쪽\n2. **겉 둘**\n   1. 안쪽 번호\n   2. 안쪽 번호\n\n> 인용한 말이 아주 길게 이어집니다 " + "아주 길게 " * 30 + "\n\n주의: 함정이 있습니다\n"),
    "plain_long": ("essay", "", "긴 글", "\n\n".join("문단입니다. " * 60 for _ in range(4))),
    "empty_body": ("essay", "", "답만 있습니다", ""),
    "no_key": ("essay", "물음만 있습니다", "", "풀이만 있습니다"),
    "token": ("work", "", "토큰", "- **세션 비밀값**: `crypto.randomBytes(32)` 로 만듭니다\n- **짧은 이름**: `abc`\n"),
    "tall_math": ("work", "", "수식", "$$\\sum_{i=1}^{N} \\frac{a_i^{2}}{\\sqrt{b_i^{2} + c_i^{2}}} = \\int_0^{1} x^{2}\\,dx$$\n"),
    "english": ("work", "What is the maximum subarray sum", "Kadane's algorithm in O(N)", "## Approach\n\n1. **Scan**: keep a running sum\n2. **Update**: keep the best\n\nA long sentence in English that goes on and on, and wraps at the width of the page as any other paragraph does here.\n"),
}


def answer_rows(items):
    return [row(600 + i, kind, asked, key, body, ago=3000 - i * 30, thumb=h.thumb(1600, 900), region=[.1, .1, .8, .9], region_shown=True) for i, (kind, asked, key, body) in enumerate(items)]


# What Practice, the keyboard shortcuts and Export to Anki put on the page: the menu with Practice on, an answer Practice keeps back
# with a hint of three out (a long question over it) and one being written under it, the keys' sheet, and Export's menu
STUDY_CARD = """() => {
  setPractice(true);
  const now = Date.now() / 1000, text = 'TYPE: algorithm\\nANSWER: 사전 한 번 훑기\\nASKED: ' + '두 수의 합이 목표값이 되는 두 원소의 인덱스를 구하는 문제 '.repeat(3) + '\\n\\n## 핵심\\n\\n첫 부분입니다.\\n\\n## 코드\\n\\n둘째 부분\\n\\n## 복잡도\\n\\n셋째 부분';
  handle({ type: 'analysis_start', id: 9901, ts: now, thumb: null, transcript: '', pages: 0, trigger: 'screen', roi: null });
  handle({ type: 'delta', id: 9901, text });
  handle({ type: 'analysis_done', id: 9901, text, usage: {}, cost_usd: null, model: 'sidenote-gemma4:26b', engine: 'local', sent: [], stages: {}, elapsed: 2, region: null });
  handle({ type: 'analysis_start', id: 9902, ts: now, thumb: null, transcript: '', pages: 0, trigger: 'screen', roi: null });
  handle({ type: 'delta', id: 9902, text: 'TYPE: work\\nANSWER: 쓰는 중인 답\\nASKED: 쓰는 중인 물음\\n\\n풀이' });
  showHint(items.get(9901));
  stick = false; entryEl(9901).scrollIntoView({ block: 'start' });
}"""
STUDY_OPEN = [
    ("practice_menu", "() => { setPractice(true); document.getElementById('more').click(); }"),
    ("practice_card", STUDY_CARD),
    ("keys_sheet", "() => openKeys()"),
    ("export_menu", "() => { const k = document.getElementById('hist-export'); k.scrollIntoView({ block: 'nearest' }); k.click(); }"),
    ("heard_sheet", "() => openHeard()"),
    ("setup_guide", "() => openSetup(0)"),
]
# What the sheet of what was heard reads: the stand-in server's /heard while the audit opens it
HEARD_KEPT = {"days": [{"day": "2026-11-04", "n": 40, "first": 1793800000, "last": 1793803000}, {"day": "2026-11-03", "n": 2, "first": 1793700000, "last": 1793700100}], "day": "2026-11-04",
              "lines": [{"ts": 1793800000 + i * 75, "secs": 3.0, "lang": "ko", "text": t} for i, t in enumerate(
                  ["So we drained the node first and waited for the pods to move to the other two workers.", "커널을 올리고 다시 부팅한 다음에 노드를 돌려놓았습니다.", "GTID가 뭔가요?", "네", "x" * 90] * 8)]}
# A fault of one kind in each of those, in their order: the audit has to find it there (group_overlays)
STUDY_PLANTS = [
    ("cut", "#practice-seg button { width: 6px !important; flex: none !important; overflow: hidden !important; white-space: nowrap !important; padding: 0 !important; }"),
    ("overlap", ".row.practice .hint-n { margin-left: -150px !important; }"),
    ("cut", "#keys .set { overflow: hidden !important; } #keys kbd.cmd { margin-right: -60px !important; }"),
    # its words are in its tooltips, so the cut is one the audit says is told
    ("cut-told", "#export-menu { width: 64px !important; min-width: 0 !important; } #export-menu .item { overflow: hidden !important; white-space: nowrap !important; }"),
    ("cut", "#heard .heard-line { grid-template-columns: 8px minmax(0, 1fr) !important; } #heard .heard-line time { overflow: hidden !important; }"),
    ("cut", "#setup .setup-step .name { max-width: 8px !important; }"),
]


# ---------------------------------------------------------------- the groups
def record(found):
    FOUND.extend(found)
    return found


def report(what, found):
    """One check for each kind, its findings as its detail."""
    by = {}
    for g in found:
        by.setdefault(g["kind"], []).append(g)
    for kind in ("cut", "spill", "overlap", "covered", "rows", "columns", "boxes", "mixed", "gaps"):
        got = by.get(kind, [])
        check(f"{what}: {kind}", not got, [f'{g["state"]} {g["size"]} {g["where"]}: {g["detail"]} [{g["words"]}]' for g in got[:6]])


def group_rail(br, s):
    if not T.group("the column, in every state, at every size"):
        return
    found = []
    for (w, hh) in SIZES:
        for name, fn in RAIL_STATES.items():
            # Every state at the one size most windows have, the hard ones on a phone, the fullest at every other size
            if not ((w, hh) == (1920, 1080) or ((w, hh) == (390, 844) and name in ("full", "agent_long", "huge", "local_long", "agent_brake", "off", "skipping", "update")) or name == "full"):
                continue
            p = Page(br, s, many(), w=w, h=hh, settle=250)
            fn(p)
            p.wait(180)
            found += audit(p, name, f"{w}x{hh}")
            if p.errors:
                check(f"{name} {w}x{hh}: the page threw nothing", False, p.errors[:2])
            p.close()
    record(found)
    report("the column", found)


def group_answers(br, s):
    if not T.group("answers of every shape"):
        return
    found = []
    # One answer to a page: every word of a long thread measured at each answer took this suite past its 900 s, for what is on the screen anyway
    for (w, hh, theme) in ((1920, 1080, "dark"), (1001, 800, "dark"), (390, 844, "dark")):
        for nm, shape in ANSWERS.items():
            if w != 1920 and nm not in ("algorithm", "table", "wide_table", "long_key", "longword", "url_key", "code_wide", "flow", "tiles", "map", "terms", "math"):
                continue     # the shapes that a narrow column can break
            p = Page(br, s, answer_rows([shape]), w=w, h=hh, theme=theme, settle=300)
            size = p.js("() => { const e = document.querySelector('#thread > .entry'); if (!e) return null; e.scrollIntoView({ block: 'start' }); stick = false; return e.getBoundingClientRect().height; }")
            if size is None:
                check(f"{nm}: it is on the page", False)
                p.close()
                continue
            for step in range(3):       # down an answer longer than the window, as far as it is read
                p.wait(60)
                found += [{**g, "state": nm, "size": f"{w}x{hh} {theme}"} for g in p.js(AUDIT, OPTS)]
                if size < hh * (step + 1) * .8:
                    break
                p.js("(y) => window.scrollBy(0, y)", hh * .8)
            if p.errors:
                check(f"{nm} {w}x{hh}: the page threw nothing", False, p.errors[:2])
            p.close()
    uniq, seen = [], set()
    for g in found:
        key = (g["kind"], g["where"], g["detail"], g["size"])
        if key not in seen:
            seen.add(key)
            uniq.append(g)
    record(uniq)
    report("the answers", uniq)


def group_overlays(br, s):
    if not T.group("what opens over the page"):
        return
    found = []
    s.heard = HEARD_KEPT
    for (w, hh) in ((1920, 1080), (390, 844)):
        for name, act in (
            # with the version the server says at its foot (app.js, renderVersion)
            ("menu", "() => { handle({ type: 'status', version: '0.1.0' }); document.getElementById('more').click(); }"),
            ("settings", "() => { document.getElementById('more').click(); document.getElementById('open-settings').click(); }"),
            ("day_combo", "() => document.querySelectorAll('.hist-tools .combo-btn')[0]?.click()"),
            ("kind_combo", "() => document.querySelectorAll('.hist-tools .combo-btn')[1]?.click()"),
            ("search_long", "() => { const q = document.getElementById('hist-q'); q.value = '이것은 아주 길게 쓴 찾는 말입니다 어디까지 보일까요'; q.dispatchEvent(new Event('input', { bubbles: true })); }"),
            ("search_none", "() => { const q = document.getElementById('hist-q'); q.value = '없는말없는말'; q.dispatchEvent(new Event('input', { bubbles: true })); }"),
            ("ask_long", "() => { const a = document.getElementById('ask'); a.value = '아주 긴 추가 질문 '.repeat(30); a.dispatchEvent(new Event('input', { bubbles: true })); }"),
            *STUDY_OPEN,
        ):
            p = Page(br, s, many(), w=w, h=hh, settle=300)
            p.js(act)
            p.wait(300)
            found += audit(p, name, f"{w}x{hh}")
            if p.errors:
                check(f"{name} {w}x{hh}: the page threw nothing", False, p.errors[:2])
            p.close()
    # Practice's card, the keys' sheet and Export's menu at the narrowest and the widest windows too, in both themes
    for (w, hh, theme) in ((360, 740, "dark"), (360, 740, "light"), (1280, 720, "light"), (2560, 1440, "dark"), (2560, 1440, "light")):
        for name, act in STUDY_OPEN:
            p = Page(br, s, many(), w=w, h=hh, theme=theme, settle=300)
            p.js(act)
            p.wait(300)
            found += audit(p, name, f"{w}x{hh} {theme}")
            if p.errors:
                check(f"{name} {w}x{hh} {theme}: the page threw nothing", False, p.errors[:2])
            p.close()
    # ...and the audit sees them: a fault planted in each is found there
    for (name, act), (kind, css) in zip(STUDY_OPEN, STUDY_PLANTS):
        p = Page(br, s, many(), w=1920, h=1080, settle=300)
        p.js(act)
        p.wait(300)
        before = {(g["where"], g["detail"]) for g in p.js(AUDIT, OPTS) if g["kind"] == kind}
        p.js("(css) => { const st = document.createElement('style'); st.textContent = css; document.head.append(st); }", css)
        p.wait(200)
        after = [g for g in p.js(AUDIT, OPTS) if g["kind"] == kind and (g["where"], g["detail"]) not in before]
        check(f"the audit finds a fault planted in {name} ({kind})", bool(after), after[:2])
    # The settings sheet as the server fills it, on the Screen section with its box of words (Skip windows), from the narrowest
    # window up: the state above opens the sheet before any settings have come
    words = support.settings_message()
    for (w, hh) in ((2560, 1440), (1920, 1080), (1366, 768), (768, 1024), (390, 844), (360, 740)):
        p = Page(br, s, many(), w=w, h=hh, settle=300)
        p.send(words)
        p.js("() => { openSettings(); document.querySelector(\".set-tab[data-sec='screen']\").click(); }")
        p.wait(300)
        found += audit(p, "settings_words", f"{w}x{hh}")
        # and the Speech section, with its own box of words and the speech model
        p.js("() => document.querySelector(\".set-tab[data-sec='speech']\").click()")
        p.wait(300)
        found += audit(p, "settings_speech", f"{w}x{hh}")
        if p.errors:
            check(f"settings_words {w}x{hh}: the page threw nothing", False, p.errors[:2])
        p.close()
    # The setup guide as the server fills it, each of its four steps, from the widest window to the narrowest (app.js, renderSetup)
    for (w, hh) in ((2560, 1440), (1920, 1080), (1366, 768), (768, 1024), (390, 844), (360, 740)):
        p = Page(br, s, many(), w=w, h=hh, settle=300)
        p.send(words)
        p.js("() => openSetup(0)")
        p.wait(300)
        for i, step in enumerate(("solve", "screen", "sound", "try")):
            p.js(f"() => setupGo({i})")
            p.wait(250)
            found += audit(p, f"setup_{step}", f"{w}x{hh}")
        if p.errors:
            check(f"setup {w}x{hh}: the page threw nothing", False, p.errors[:2])
        p.close()
    s.heard = {"days": [], "day": "", "lines": []}
    # An empty panel, and the first screen
    for (w, hh) in ((1920, 1080), (1366, 768), (390, 844)):
        p = Page(br, s, [], w=w, h=hh, settle=500)
        found += audit(p, "empty", f"{w}x{hh}")
        p.close()
    record(found)
    report("what opens over the page", found)


def group_named(br, s):
    """Tables, captions, a run's result, term cards and the column's foot, each as a check that failed before its fix."""
    if not T.group("tables, captions, runs and cards"):
        return
    table = "| 버섯 | p | odd | even |\n|---|---|---|---|\n| 시작 | – | -∞ | 0 |\n| 0 | 7 | 7 | 0 |\n| 1 | 2 | 7 | 5 |\n| 2 | 1 | 7 | 6 |\n| 7 | 6 | **17** | 11 |\n"
    terms = lambda n: "\n".join(f"- **이름 {i}**: 설명입니다" for i in range(n)) + "\n"  # noqa: E731
    p = Page(br, s, [], w=1920, h=1080, settle=300)
    p.answer(801, "algorithm", "물음", "답", f"## 예제 검증 (P = 7 2 1)\n\n{table}\n## 코드 (Python)\n\n```python\nprint(1)\n```\n")
    p.wait(250)
    got = p.js("""() => { const e = entryEl(801), wrap = e.querySelector('.tablewrap'), t = wrap.querySelector('table'), r = (x) => x.getBoundingClientRect(), cols = [...t.rows[2].cells].map((c) => getComputedStyle(c).textAlign);
        return { wrap: r(wrap).width, table: r(t).width, bars: e.querySelectorAll('td.v-bar').length, cols, tab: wrap.querySelector('.lang').textContent, code: e.querySelector('pre .lang').textContent, odd: getComputedStyle(t.rows[1].cells[2]).textAlign }; }""")
    check("a table fills its frame: no strip that reads as a column with no name", abs(got["wrap"] - got["table"]) <= 2.5, got)
    check("plain numbers of a table worked by hand get no bars", got["bars"] == 0, got)
    check("a column with a dash and infinity in it is a column of numbers, set like the others", got["cols"][1:] == ["right", "right", "right"] and got["odd"] == "right", got)
    check("a caption numbers its table and says what it is, from the heading over it", got["tab"] == "표 1. 예제 검증 (P = 7 2 1)", got["tab"])
    check("nor the kind of thing twice", got["code"].replace(" ", "") == "코드1.Python", got["code"])
    # The runs of the code as a judge's result: the verdict, then what went in and came out
    checked = {"type": "check", "id": 801, "lang": "python", "probe": True, "passed": 1, "total": 1, "rows": [{"input": "3\n10 20 30\n", "got": "30\n", "ok": True}]}
    p.send(checked)
    p.wait(200)
    run = p.js("""() => { const b = entryEl(801).querySelector('.vcheck'); if (!b) return null; return { v: b.querySelector('.vc-verdict')?.textContent, keys: [...b.querySelectorAll('.vc-case:not([hidden]) .vc-k')].map((x) => x.textContent), boxes: [...b.querySelectorAll('.vc-case:not([hidden]) pre')].map((x) => x.textContent) }; }""")
    check("the verdict, then what went in and what came out, each in a box", run and run["v"] == "오류 없음" and run["keys"] == ["입력", "출력"] and run["boxes"] == ["3\n10 20 30", "30"], run)
    for n in range(2, 10):
        p.answer(810 + n, "work", "", "답", terms(n))
        p.wait(120)
        cards = p.js("""(id) => { const list = entryEl(id).querySelector('.v-terms'), w = list.getBoundingClientRect(), rows = {}; for (const c of list.children) { const r = c.getBoundingClientRect(); (rows[Math.round(r.top)] ??= []).push(r); }
            return Object.values(rows).map((x) => Math.round(Math.max(...x.map((r) => r.right)) - w.left) >= Math.round(w.width) - 1 && Math.round(Math.min(...x.map((r) => r.left)) - w.left) === 0); }""", 810 + n)
        check(f"{n} cards fill every row they stand in", all(cards), cards)
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()
    # On a narrow window every card takes its row: two, four or five of them stood two to a row there, about 150 px each at
    # 390, their code broken inside a path and their words a few to a line, as the rules that place them by count outranked
    # the narrow window's. So in a thread narrowed by the column beside it (1001 and 1100 px), where two were 220 to 290 px
    for (w, hh) in ((390, 844), (700, 900), (1001, 800), (1100, 800)):
        p = Page(br, s, [], w=w, h=hh, settle=300)
        for n in range(2, 8):
            p.answer(830 + n, "work", "", "답", terms(n))
            p.wait(120)
            rows = p.js("""(id) => { const list = entryEl(id).querySelector('.v-terms'), w = list.getBoundingClientRect().width;
                return [...list.children].map((c) => Math.round(c.getBoundingClientRect().width / w * 100)); }""", 830 + n)
            check(f"{n} cards at {w} px, one to a row", all(x >= 99 for x in rows), rows)
        p.close()
    # ...and between that and the widest windows, two to a row with no card alone beside an empty half
    p = Page(br, s, [], w=1200, h=800, settle=300)
    for n in range(2, 8):
        p.answer(850 + n, "work", "", "답", terms(n))
        p.wait(120)
        cards = p.js("""(id) => { const list = entryEl(id).querySelector('.v-terms'), w = list.getBoundingClientRect(), rows = {}; for (const c of list.children) { const r = c.getBoundingClientRect(); (rows[Math.round(r.top)] ??= []).push(r); }
            return Object.values(rows).map((x) => Math.round(Math.max(...x.map((r) => r.right)) - w.left) >= Math.round(w.width) - 1 && Math.round(Math.min(...x.map((r) => r.left)) - w.left) === 0); }""", 850 + n)
        check(f"{n} cards at 1200 px fill every row they stand in", all(cards), cards)
    p.close()
    # Opened with answers kept, the page stands at the end it follows (stageEnd), the newest answer's keys clear of the question
    # box: the answers come before the server's word that questions can be asked, and the keys that came with that word stood
    # half under the box
    for (w, hh) in ((1920, 1080), (1366, 768)):
        p = Page(br, s, many(), w=w, h=hh, status=False, settle=700)
        p.open_messages()
        p.wait(700)
        at = p.js("""() => { const box = document.getElementById('askform').getBoundingClientRect(), keys = [...document.querySelectorAll('#thread .row.asks .btn')];
            const k = keys.length ? keys[keys.length - 1].getBoundingClientRect() : null;
            return { short: Math.round(stageEnd() - innerHeight - scrollY), keys: k && Math.round(k.bottom), box: Math.round(box.top) }; }""")
        check(f"opened at {w}x{hh}: at the end, the last keys clear of the question box", at["keys"] is not None
              and at["short"] <= 1 and at["keys"] <= at["box"], at)
        p.close()
    # The column's foot level with the question box's while it follows the scroll, the list having more than it shows: on a window
    # it fits in (2560 x 1400); on a 1040 one it is taller than the window and drifts, its foot in the window at the thread's end
    p = Page(br, s, many(30), w=2560, h=1400, settle=500)
    feet = p.js("() => [document.querySelector('.rail').getBoundingClientRect().bottom, document.getElementById('askform').getBoundingClientRect().bottom, document.querySelector('.rail').className]")
    check("following, the column's foot is level with the question box's", abs(feet[0] - feet[1]) <= 1.5 and "stick" in feet[2], feet)
    p.close()
    # The contents are of the same glass as the others
    p = Page(br, s, many(), w=1920, h=1080, settle=400)
    glass = p.js("""() => [...document.querySelectorAll('.rail .card')].filter((c) => c.offsetParent).map((c) => { const k = getComputedStyle(c); return k.backgroundColor + '|' + k.backdropFilter; })""")
    check("every card of the column, the contents with them, is one material", len(set(glass)) == 1, glass)
    p.close()


def group_found(br, s):
    """An answer's tiles, term cards, commands, diagrams, captions and runs, and the column's states, each as a check."""
    if not T.group("tiles, cards, captions, diagrams, runs and the column"):
        return
    p = Page(br, s, [], w=1920, h=1080, settle=300)
    # A tile's key line underlined line by line
    p.answer(1701, "essay", "", "1) 아주 길게 쓴 첫째 답입니다, 아주 길게 쓴 첫째 답입니다, 아주 길게 쓴 첫째 답입니다, 2) 둘째 답입니다", "## (1) 물음\n\n글\n\n## (2) 물음\n\n글\n")
    p.wait(250)
    hl = p.js("""() => [...entryEl(1701).querySelectorAll('.ans-list .hl')].map((h) => [h.getClientRects().length, getComputedStyle(h).display, h.textContent.slice(-1)])""")
    check("a tile's highlighter is on its lines, not under a block", all(x[1] == "inline" for x in hl), hl)
    check("a tile's words end where they end, with no comma left over", all(x[2] not in ",;" for x in hl), hl)
    # Every term card keeps its name: forEach's index once went in as a length, and 128 of 128 real cards lost theirs with every check green
    p.answer(1720, "work", "", "답", "- **이름 하나**: 설명\n- **이름 둘**: 설명\n- **장점**: 설명\n- **단점**: 설명\n- **아주 길게 쓴 이름입니다 아주 길게 쓴 이름**: 설명\n")
    p.wait(200)
    named = p.js("() => [...entryEl(1720).querySelectorAll('.v-terms > li')].map((li) => [li.querySelector(':scope > .v-t')?.textContent.trim() || '', li.querySelector(':scope > .v-t')?.dataset.tone || ''])")
    check("every card has its name, however late in the list and however long", len(named) == 5 and all(n[0] for n in named) and named[2][1] == "good" and named[3][1] == "bad", named)
    # The margin's word on the baseline of the first line beside it, whatever comes first
    for nm, body in (("a paragraph", "문단입니다."), ("a heading", "## 제목\n\n글"), ("a list", "- 하나\n- 둘"), ("steps", "1. **첫째**: 설명\n2. **둘째**: 설명"), ("cards", "- **이름**: 설명\n- **둘째**: 설명"), ("a quote", "> 인용")):
        p.answer(1730 + len(nm), "work", "", "답", body)
        p.wait(150)
        off = p.js("""(id) => { const row = entryEl(id).querySelector('.row:has(> .ct > .md[data-body])'), mg = row.querySelector('.mg'), first = (() => { const w = document.createTreeWalker(row.querySelector('.md'), NodeFilter.SHOW_TEXT, { acceptNode: (n) => (n.nodeValue.trim() ? 1 : 2) }); return w.nextNode(); })(), base = (n) => { const e = document.createElement('span'); e.style.cssText = 'display:inline-block;width:0;height:0'; n.parentNode.insertBefore(e, n); const a = e.getBoundingClientRect().bottom; e.remove(); return a; }; const lab = [...mg.childNodes].find((n) => n.nodeType === 3 && n.nodeValue.trim()) || mg.firstChild.firstChild; return Math.abs(base(lab) - base(first)); }""", 1730 + len(nm))
        check(f"the margin's word stands on the first line's baseline over {nm}", off <= 1.5, off)
    # Two like headings are drawn alike, a formula right under one or not
    p.answer(1725, "work", "", "답", "**1. 주어진 값:**\n\n- 하나\n- 둘\n\n**2. 계산:**\n$$x = 1$$\n$$y = 2$$\n")
    p.wait(250)
    like = p.js("() => [...entryEl(1725).querySelectorAll('.md p > strong')].map((b) => [b.textContent, getComputedStyle(b).backgroundImage !== 'none', b.parentElement.className])")
    check("two like headings are drawn alike, with a formula right under one", len(like) == 2 and like[0][1] == like[1][1] and like[0][2] == like[1][2], like)
    check("...and the formula is still there", p.js("() => entryEl(1725).querySelectorAll('.katex-display').length") == 2, p.js("() => entryEl(1725).querySelectorAll('.katex-display').length"))
    # Commands and steps
    p.answer(1721, "work", "", "답", "## 확인 방법\n\n1. **로그 확인**: 먼저 봅니다\n\n   ```bash\n   tail -f app.log\n   ```\n\n2. **상태 확인**: 다음에 봅니다\n\n   ```bash\n   systemctl status app\n   ```\n")
    p.wait(250)
    steps = p.js("() => [...entryEl(1721).querySelectorAll('pre .lang')].map((l) => l.textContent.trim())")
    check("a command inside a step goes by the step", steps == ["명령어 1. 로그 확인", "명령어 2. 상태 확인"], steps)
    p.answer(1722, "work", "", "답", "```bash\nawk '{print $1}' a.log\n```\n")
    p.wait(200)
    alone = p.js("() => entryEl(1722).querySelector('pre .lang').textContent.trim()")
    check("a command with nothing said of it is named by its number and its program", alone == "명령어 1. awk", alone)
    # ...the program, not what wraps it or a comment over it: these said "명령어 1. sudo" and "명령어 2. #"
    p.answer(1723, "work", "", "답", "```bash\nsudo lsof | grep deleted\n```\n\n```bash\n# 확인한 PID로 비우기\n$ sudo -E truncate -s 0 /proc/1/fd/3\n```\n\n```bash\nLANG=C env FOO=1 sort a.txt\n```\n")
    p.wait(200)
    named = p.js("() => [...entryEl(1723).querySelectorAll('pre .lang')].map((l) => l.textContent.trim())")
    check("...past sudo, env, a VAR=value and a comment line", named == ["명령어 1. lsof", "명령어 2. truncate", "명령어 3. sort"], named)
    # A program's name (codeTopic): its wrapper's docstring, or the comment right under or over it; never a comment further in about a step,
    # nor an include or a shebang read as a comment (seven of these were once named wrong)
    topics = p.js("(cases) => cases.map(([text]) => codeTopic(text))", [["class Solution:\n    def twoSum(self, nums, target):\n        seen = {}\n        # edge case: empty input\n        return []", "twoSum 함수"], ["#include <bits/stdc++.h>\nusing namespace std;\nint main() {\n    int n; cin >> n;\n    // read the grid\n    return 0;\n}", ""], ["#include <iostream>\nint main() {\n    std::cout << 1;\n}", ""], ["#include <vector>\nusing namespace std;\n// 겹치는 회의 최대 개수\nint solution(vector<int> a) {\n    return 0;\n}", "겹치는 회의 최대 개수"], ["#!/usr/bin/env python3\nimport sys\ndef main():\n    data = sys.stdin.read()\nmain()", ""], ["class Solution {\n    public int[] twoSum(int[] nums, int target) {\n        // brute force\n        return null;\n    }\n}", "twoSum 함수"], ["import sys\n\n\ndef solution(a):\n    \"\"\"배열의 최대 부분합\"\"\"\n    return 0", "배열의 최대 부분합"], ["def solution(times):\n    \"\"\"회의실 최대 동시 사용 수\"\"\"\n    def time_to_minutes(t):\n        return 1\n    return 0", "회의실 최대 동시 사용 수"], ["def solution(times):\n    # 겹치는 회의의 최대 수\n    def time_to_minutes(t):\n        return 1", "겹치는 회의의 최대 수"], ["# 회의실 배정\nn = int(input())\nprint(n)", "회의실 배정"]])
    want = ["twoSum 함수", "", "", "겹치는 회의 최대 개수", "", "twoSum 함수", "배열의 최대 부분합", "회의실 최대 동시 사용 수", "겹치는 회의의 최대 수", "회의실 배정"]
    check("a program is named by what its wrapper says, not by a step inside it, an include or a shebang", topics == want, [(g, w) for g, w in zip(topics, want) if g != w])
    # Diagrams
    conf = p.js("() => mermaidConfig().themeVariables")
    check("an ER table's rows, a pie's slices and a mind map's branches have their colours", all(conf.get(k) for k in ("attributeBackgroundColorOdd", "attributeBackgroundColorEven", "pie1", "pie2", "cScale0")) and conf["pie1"] != conf["pie2"], {k: conf.get(k) for k in ("attributeBackgroundColorOdd", "pie1", "pie2")})
    # Not the setting but what it draws: the rows' words were light on light in the dark theme, in a picture the word checks cannot read
    if (h.PANEL / "vendor" / "mermaid.min.js").exists():
        p.answer(1724, "work", "", "답", "```mermaid\nerDiagram\n  CUSTOMER {\n    bigint id PK\n    varchar email UK\n    varchar phone\n    int age\n    date joined\n  }\n```\n")
        p.page.wait_for_function("() => entryEl(1724)?.querySelector('figure.viz-diagram-fig img')?.complete", timeout=9000)
        p.wait(300)
        box = p.js("() => { entryEl(1724).querySelector('figure.viz-diagram-fig').scrollIntoView({ block: 'center' }); const r = entryEl(1724).querySelector('figure.viz-diagram-fig img').getBoundingClientRect(); return [Math.floor(r.left), Math.floor(r.top), Math.ceil(r.right), Math.ceil(r.bottom)]; }")
        p.wait(200)
        box = p.js("() => { const r = entryEl(1724).querySelector('figure.viz-diagram-fig img').getBoundingClientRect(); return [Math.floor(r.left), Math.floor(r.top), Math.ceil(r.right), Math.ceil(r.bottom)]; }")
        mean = h.pixels(br, p.page.screenshot(), [box])[0]
        check("dark theme: an ER table's rows are dark under its light words", sum(mean) / 3 < 90, mean)
    plain = p.js("""() => unquoteDiagram('sequenceDiagram\\n  participant C as "클라이언트"\\n  C->>S: "요청"\\n')""")
    check("a sequence's names and messages lose the prompt's quotes", '"' not in plain and "클라이언트" in plain and "요청" in plain, plain)
    keep = p.js("""() => unquoteDiagram('flowchart LR\\n  A["가"] --> B["나"]\\n')""")
    check("a flowchart keeps them, as it needs them", keep.count('"') == 4, keep)
    # Code in bold words does not break the underline
    p.answer(1723, "work", "", "답", "**`SYN` 패킷**을 보냅니다.\n")
    p.wait(150)
    under = p.js("() => getComputedStyle(entryEl(1723).querySelector('.md strong code')).backgroundColor")
    check("code in bold words has no ground of its own over the underline", under == "rgba(0, 0, 0, 0)", under)
    # Empty columns, verdicts and chains
    p.answer(1702, "work", "", "표", "| 항목 | 빠름 | 느림 | 비고 |  |\n|---|---|---|---|---|\n| 지연 | 1 ms | 9 ms | 짧음 |  |\n| 안정 | 맞음 | 틀림 | 그런대로 |  |\n")
    p.wait(200)
    tb = p.js("""() => { const t = entryEl(1702).querySelector('table'); return { cols: t.rows[0].cells.length, plain: [...t.tHead.rows[0].cells].filter((c) => c.classList.contains('v-plain')).map((c) => c.textContent), right: t.querySelectorAll('tr.v-right').length }; }""")
    check("a column with nothing in it is not drawn", tb["cols"] == 4, tb)
    check("what is not compared has no colour of its own", tb["plain"] == ["비고"], tb)
    check("one right cell does not make a comparison's row an answer", tb["right"] == 0, tb)
    for text in ("요청을 받습니다 → 처리합니다 → 응답을 돌려줍니다.", "로드밸런서 → 워커 순서로 보냅니다. → 끝", '인증" → DB → 결과'):
        check(f"a sentence holding arrows is no chain: {text[:20]}", p.js("(t) => vChain(t)", text) is None)
    for expr, at in (("log^2 N", 1), ("log^{2} n", 1), ("N log^2 N", 3), ("N^2 log N", 4)):
        check(f"where O({expr}) stands", p.js("(t) => vBigOClass(t)", expr) == at, p.js("(t) => vBigOClass(t)", expr))
    # Numbered steps with a long name, or a list under the name, are one kind of step
    p.answer(1703, "work", "", "답", "1. **" + ("아주 길게 쓴 단계의 이름입니다 " * 4).strip() + "**: 설명\n2. **겉 하나**\n   - 안쪽 항목\n3. **셋째**: 설명\n")
    p.wait(200)
    leads = p.js("() => [...entryEl(1703).querySelectorAll('.md > ol > li')].map((li) => !!li.querySelector(':scope > .v-t'))")
    check("every numbered step has its name set alike", all(leads), leads)
    # Captions
    p.answer(1704, "work", "", "답", "## 첫째\n\n글입니다.\n\n| 가 | 나 |\n|---|---|\n| 1 | 2 |\n\n## 둘째\n\n| 가 | 나 |\n|---|---|\n| 1 | 2 |\n\n## 셋째 $x^2$\n\n글입니다.\n\n| 가 | 나 |\n|---|---|\n| 1 | 2 |\n")
    p.wait(250)
    caps = p.js("() => [...entryEl(1704).querySelectorAll('.tablebar .lang')].map((l) => l.textContent.trim())")
    check("a heading names the table under it, with writing between them or none", caps[0] == "표 1. 첫째" and caps[1] == "표 2. 둘째", caps)
    check("a formula in a heading comes once", caps[2].count("x") == 1, caps)
    p.answer(1706, "work", "", "답", "## 시간 복잡도 O(N log N)\n\n글입니다.\n\n| 가 |\n|---|\n| 1 |\n\n## 접근 시간 (단위: ns)\n\n글입니다.\n\n| 가 |\n|---|\n| 1 |\n\n## 넓이 $x^2+y^2$\n\n글입니다.\n\n| 가 |\n|---|\n| 1 |\n\n| 나 |\n|---|\n| 2 |\n")
    p.wait(250)
    said = p.js("() => [...entryEl(1706).querySelectorAll('.tablebar .lang')].map((l) => [l.textContent.trim(), Math.round(l.getBoundingClientRect().width)])")
    check("a caption keeps what is in its heading's brackets and a formula's marks", said[0][0] == "표 1. 시간 복잡도 O(N log N)" and said[1][0] == "표 2. 접근 시간 (단위: ns)" and "x²+y²" in said[2][0], said)
    check("a narrow table's caption can be read", all(x[1] >= 60 for x in said), said)
    long_cap = "아주 길게 쓴 제목입니다 " * 12
    p.answer(1705, "work", "", "답", f"## {long_cap}\n\n글입니다.\n\n| 가 |\n|---|\n| 1 |\n")
    p.wait(250)
    wid = p.js("""() => { const w = entryEl(1705).querySelector('.tablewrap'), key = w.querySelector('.copy').getBoundingClientRect(), md = w.closest('.md').getBoundingClientRect(); return { key: key.width, wrap: w.getBoundingClientRect().width, table: w.querySelector('table').getBoundingClientRect().width, body: md.width }; }""")
    check("a long caption does not squeeze the copy key", wid["key"] >= 26, wid)
    # A table takes the answer's width, and fills its frame
    check("a table takes the answer's width and fills its frame", abs(wid["wrap"] - wid["body"]) <= 1.5 and abs(wid["wrap"] - wid["table"]) <= 2.5, wid)
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()
    # The runs at every width: a column too narrow for three parts stacks them, words whole
    runs = [{"input": "3\n10 20 30\n", "expected": "30\n", "got": "Traceback (most recent call last):\n" + "  frame\n" * 40 + "ValueError: invalid literal\n", "ok": False}, {"input": "", "expected": "1\n", "got": "1\n", "ok": True}, {"input": "add(1)", "expected": "null", "got": None, "ok": True}]
    for w, hh in ((1920, 1080), (1366, 768), (1100, 800), (1001, 800), (1000, 800), (390, 844)):
        p = Page(br, s, [], w=w, h=hh, settle=300)
        p.answer(1710, "code", "", "답", "풀이")
        p.send({"type": "check", "id": 1710, "lang": "python", "passed": 2, "total": 3, "how": "stdin", "rows": runs})
        p.wait(250)
        got = p.js("""() => { const b = entryEl(1710).querySelector('.vcheck'); b.scrollIntoView({ block: 'center' }); const box = b.getBoundingClientRect(), col = [...entryEl(1710).querySelectorAll(':scope > .row > .ct')].find((c) => c.getBoundingClientRect().width > 0).getBoundingClientRect(), bad = b.querySelector('.vc-case.bad .vc-io.got pre'), r = document.createRange(); r.selectNodeContents(bad); const last = [...r.getClientRects()].pop(), pb = bad.getBoundingClientRect();
            return { inside: box.right <= col.right + 1, none: b.querySelectorAll('pre.none').length, end: Math.abs(last.bottom - pb.bottom) <= 14, tabs: [...b.querySelectorAll('.vc-tab')].map((x) => x.className.replace('vc-tab ', '')) }; }""")
        check(f"{w}: the check stays in its column", got["inside"], got)
        check(f"{w}: what is empty says so", got["none"] == 2, got)
        check(f"{w}: a failed run shows the end of its output first", got["end"], got)
        check(f"{w}: each run has its verdict on its tab", got["tabs"] == ["bad", "ok", "ok"], got)
        p.wait(120)
        record_in = audit(p, "runs", f"{w}x{hh}", keep=("cut", "spill", "overlap", "rows", "boxes"))
        here = [g for g in record_in if "vcheck" in g["where"] or "vc-" in g["where"]]
        record(here)
        check(f"{w}: the runs have nothing cut, out of line or on top of each other", not here, [f'{g["kind"]} {g["where"]}: {g["detail"]}' for g in here[:4]])
        p.close()
    # A failed example with no rows is the same card
    p = Page(br, s, [], w=1920, h=1080, settle=300)
    p.answer(1711, "code", "", "답", "풀이")
    p.send({"type": "check", "id": 1711, "lang": "python", "passed": 0, "total": 1, "how": "stdin", "fails": [{"input": "1", "expected": "2", "got": "3"}]})
    p.wait(200)
    check("a failed example with no rows is a run of the same check", p.js("() => entryEl(1711).querySelectorAll('.vcheck .vc-case.bad').length") == 1 and p.js("() => entryEl(1711).querySelectorAll('pre.check-fail').length") == 0)
    p.close()
    # The column
    p = Page(br, s, many(14), w=1920, h=1040, settle=500)
    status(p, eng(local={"loaded": {"model": "sidenote-gemma4:26b", "vram_gb": 16.2, "params": "26B", "quant": "Q4_K_M", "ctx": 32768}}))
    p.page.set_viewport_size({"width": 1920, "height": 900})
    p.wait(350)
    line = p.js("() => document.querySelector('#st-local .fact.wide dd:has(.lit), #st-local dd:has(.lit)')?.textContent.replace(/\\s+/g, ' ').trim()")
    gauge = p.js("() => Math.round(document.getElementById('gpu-viz').getBoundingClientRect().height)")
    # Nothing folds on a short window now (everything shows, the same at every resolution): the state and the model's details, the gauges under them
    check("on a short window the GPU's line is the state and the model's details, its gauges under it", bool(line) and line.startswith("바로 풂") and "Q4_K_M" in line and gauge > 40, [line, gauge])
    p.close()
    p = Page(br, s, many(14), w=1920, h=1040, settle=500)
    status(p, eng(local={"ok": False, "missing": True, "loaded": None}))
    p.wait(150)
    rest = p.js("() => document.getElementById('pill-local').closest('.src').hasAttribute('data-rest')")
    check("a model missing is a fault, not a model at rest", not rest)
    status(p, eng(agent={"brake": "시간당 상한에 닿았습니다"}))
    p.wait(150)
    keep = p.js("() => ({ who: !!document.querySelector('#card-agent .agent-who'), scales: document.querySelectorAll('#card-agent .agent-scale').length })")
    check("the agent's card keeps its shape when a brake holds", keep["who"] and keep["scales"] == 2, keep)
    p.close()
    # The screen's switch turned off is red, not grey; the agent switched off is at rest, grey, its switch too (the agent's
    # was made red once)
    for theme, red_want, grey_want in (("dark", "#4d2528", "#36373c"), ("light", "#f3c9c9", "#d8d9de")):
        p = Page(br, s, many(4), w=1920, h=1200, theme=theme, settle=400)
        status(p, eng(agent={"mode": "off", "effective": "off"}))
        capture(p, screen_on=False)
        p.wait(150)
        got = p.js("""() => ['sw-screen', 'sw-agent'].map((id) => { const c = getComputedStyle(document.getElementById(id)); return c.backgroundColor + ' ' + c.backgroundImage; })""")
        rgb = lambda h: f"rgb({int(h[1:3], 16)}, {int(h[3:5], 16)}, {int(h[5:7], 16)})"   # noqa: E731
        check(f"{theme}: the screen's switch off is red, the agent's switched off is grey", rgb(red_want) in got[0] and rgb(grey_want) in got[1], got)
        p.close()
    # Pressing something else while the search has words in it
    p = Page(br, s, many(14), w=1920, h=1040, settle=500)
    p.js("() => { window.__clicks = 0; document.getElementById('hist-export').addEventListener('click', () => { window.__clicks++; }, true); }")
    p.page.locator("#hist-q").click()
    p.page.keyboard.type("없는말찾기")
    p.wait(350)
    box = p.page.locator("#hist-export").bounding_box()
    p.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    p.page.mouse.down()
    p.wait(90)
    p.page.mouse.up()
    p.wait(250)
    check("a key pressed while the search box has the focus takes its click", p.js("() => window.__clicks") == 1, p.js("() => window.__clicks"))
    p.close()
    # A filter's list opened from a search stands by its key, and a search cleared does not move the page
    p = Page(br, s, many(40), w=1920, h=1040, settle=500)
    p.page.locator("#hist-q").click()
    p.page.keyboard.type("없는말찾기")
    p.wait(300)
    p.page.locator(".hist-tools .combo-btn").first.click()
    p.wait(300)
    place = p.js("""() => { const k = document.querySelector('.hist-tools .combo-btn').getBoundingClientRect(), l = document.querySelector('.combo-list:not([hidden])')?.getBoundingClientRect(); return l ? { key: [Math.round(k.top), Math.round(k.bottom)], list: [Math.round(l.top), Math.round(l.bottom)] } : null; }""")
    check("a filter's list opened from a search does not cover its key", place and (place["list"][0] >= place["key"][1] - 1 or place["list"][1] <= place["key"][0] + 1), place)
    p.page.keyboard.press("Escape")
    p.page.locator("#hist-q").click()
    at = p.js("() => Math.round(document.getElementById('hist-q').getBoundingClientRect().top)")
    p.page.keyboard.press("Control+a")
    p.page.keyboard.press("Delete")
    p.wait(350)
    after = p.js("() => Math.round(document.getElementById('hist-q').getBoundingClientRect().top)")
    check("a search cleared leaves its box where it stood in the window", abs(after - at) <= 1, [at, after])
    p.close()
    # Nothing folds now (everything shows, the same at every resolution): a long caption of the picture stays at 1280 x 720, inside its card
    p = Page(br, s, many(14), w=1280, h=720, settle=500)
    p.js("() => { const c = document.getElementById('shot-cap'); c.textContent = '이 답의 화면에 대한 설명이 길게 이어지는 경우입니다, 이 답의 화면에 대한 설명이 길게 이어지는 경우입니다'; window.dispatchEvent(new Event('resize')); }")
    p.wait(250)
    cap = p.js("() => { const c = document.getElementById('shot-cap'), k = c.closest('.card').getBoundingClientRect(), r = c.getBoundingClientRect(); return [getComputedStyle(c).display, Math.round(r.right - k.right), c.scrollWidth <= c.clientWidth + 1]; }")
    check("a long caption of the picture stays at 1280 x 720, inside its card", cap[0] != "none" and cap[1] <= 0 and cap[2], cap)
    p.close()
    # Pills readable in the column's own caution and fault
    for theme in ("dark", "light"):
        for state, want in ((st_agent_limit, "warn"), (st_agent_login, "bad")):
            p = Page(br, s, many(3), w=1920, h=1300, theme=theme, settle=300)
            state(p)
            p.wait(150)
            png = p.page.screenshot()
            got = p.js("""() => { const e = document.getElementById('pill-agent'), r = e.getBoundingClientRect(), c = getComputedStyle(e).color.match(/[\\d.]+/g).map(Number); return { box: [Math.floor(r.left), Math.floor(r.top), Math.ceil(r.right), Math.ceil(r.bottom)], colour: c, st: e.dataset.state }; }""")
            bg = h.background_of(br, png, got["box"])
            ratio = h.contrast(got["colour"], bg)
            check(f"{theme}: the {want} pill reads at 4.5:1 or better", ratio >= 4.5 and got["st"] == want, f"{ratio:.2f} {got}")
            p.close()
    # A check beginning under an answer being read: the page stays where it is
    p = Page(br, s, [], w=1920, h=1040, settle=300, reduced=False)
    p.answer(1740, "work", "", "답", "\n\n".join(f"## 절 {i}\n\n" + "문단입니다. " * 60 for i in range(8)))
    p.wait(300)
    for offset in (-500, -350, -100):
        p.js("(o) => { const e = entryEl(1740); stopFollowing(); autoUntil = 0; window.scrollTo(0, Math.max(0, scrollY + e.getBoundingClientRect().bottom - innerHeight + o)); }", offset)
        p.wait(150)
        at = p.js("() => { const h = [...entryEl(1740).querySelectorAll('.qa')].find((x) => x.getBoundingClientRect().top > 100); return h ? [h.textContent.slice(0, 8), h.getBoundingClientRect().top] : null; }")
        p.send({"type": "check", "id": 1740, "running": True})
        p.wait(200)
        now = p.js("(t) => { const h = [...entryEl(1740).querySelectorAll('.qa')].find((x) => x.textContent.startsWith(t)); return h ? h.getBoundingClientRect().top : null; }", at[0])
        check(f"a check beginning under the answer being read does not move the page ({offset})", now is not None and abs(now - at[1]) <= 2, (at, now))
        p.send({"type": "check", "id": 1740, "none": True})
        p.js("() => { const it = items.get(1740); it.check = null; renderEntry(it); }")
        p.wait(120)
    p.close()
    # A fresh answer's pictures start in the frame they are drawn: nothing shows whole, goes and comes back
    p = Page(br, s, [], w=1920, h=1040, settle=300, reduced=False)
    text = p.answer(1741, "work", "", "답", "- **이름**: 설명\n- **둘째**: 설명\n", final=False)
    p.wait(200)
    began = p.js("""(text) => { window.__sock.onmessage({ data: JSON.stringify({ type: 'analysis_done', id: 1741, text, usage: {}, cost_usd: null, model: 'm', engine: 'local', sent: [], stages: { local: true, agent: false }, elapsed: 1, region: null }) }); const c = entryEl(1741).querySelector('.v-terms'); return c && c.classList.contains('v-in'); }""", text)
    check("a fresh answer's cards begin to come in with their drawing, in one frame", began is True, began)
    p.close()
    # Words heard with a search standing, and a column that holds still when no words come
    p = Page(br, s, many(14), w=1920, h=1040, settle=500)
    p.page.locator("#hist-q").click()
    p.page.keyboard.type("문제")
    p.wait(200)
    p.page.locator("#hist-q").blur()
    p.send({"type": "transcript", "text": "지금 들리는 말입니다.", "lang": "ko", "final": False})
    p.wait(250)
    check("words heard bring their card back, with a search standing too", p.js("() => getComputedStyle(document.getElementById('hear')).display") != "none")
    p.close()
    p = Page(br, s, many(14), w=1920, h=1040, settle=500)
    before = p.js("() => document.querySelector('.rail').className + '|' + document.getElementById('history').style.maxHeight")
    p.js("() => { capture.last_audio = serverNow() - 30; renderHear(); }")
    p.wait(350)
    after = p.js("() => document.querySelector('.rail').className + '|' + document.getElementById('history').style.maxHeight")
    check("the microphone going quiet does not rearrange the column", before == after, (before, after))
    p.close()
    # Words in the hearing card on whole lines, and its marks still when nothing is coming
    p = Page(br, s, many(4), w=1920, h=1500, settle=400, reduced=False)
    p.send({"type": "transcript", "text": "지금 들리는 말이 아주 길게 이어지는 경우입니다. " * 12, "lang": "ko", "final": False})
    p.wait(250)
    lines = p.js("""() => { const b = document.getElementById('hear-text'), st = getComputedStyle(b); return { lh: parseFloat(st.lineHeight), box: b.clientHeight, end: Math.round(b.scrollHeight - b.clientHeight - b.scrollTop) }; }""")
    check("the words heard stand on whole lines, the latest in view", abs(lines["box"] / lines["lh"] - round(lines["box"] / lines["lh"])) < .12 and lines["end"] <= 1, lines)
    p.close()


def group_asked(br, s):
    """The layout as it is meant to be, each a check, so that no later change takes it away again: the question box once went full width,
    the contents' times to the right, the search squeezed onto one line with the filters, the agent's card cramped, the picture glued to its
    title and the term cards' colour gone, each undone by a later change that every check had let through."""
    if not T.group("the layout kept: the question box, the contents, the agent's card, tables and runs"):
        return
    p = Page(br, s, many(30), w=1920, h=1300, settle=500)
    capture(p, clients=0)
    p.wait(250)
    # Scrolled into the thread, the question box floats narrower than the thread's column and centred on it (it once went
    # the column's full width); the bands it was measured against stand in the bar now, scrolled too
    p.js("() => { stick = false; window.scrollTo(0, document.documentElement.scrollHeight / 3); }")
    p.wait(400)
    w = p.js("""() => { const f = document.getElementById('askform').getBoundingClientRect(), c = document.getElementById('stage').getBoundingClientRect();
        return { floating: document.getElementById('askform').classList.contains('floating'), ask: Math.round(f.width), column: Math.round(c.width),
                 off: Math.round(Math.abs((f.left + f.right) / 2 - (c.left + c.right) / 2)) }; }""")
    check("floating, the question box is narrower than the thread's column and centred on it",
          w["floating"] and 16 <= w["column"] - w["ask"] <= 120 and w["off"] <= 2, w)
    # The band that says the capture program is off has no key to copy a command
    check("the band that says the capture program is off has no copy key", p.js("() => [...document.querySelectorAll('#alerts .alert')].filter((a) => a.textContent.includes('캡처 프로그램')).every((a) => !a.querySelector('[data-copy]'))"))
    # In the contents a row's time stands on the left
    rows = p.js("() => [...document.querySelectorAll('#history .h')].slice(0, 3).map((h) => [h.querySelector('time').getBoundingClientRect().left, h.querySelector('.ht').getBoundingClientRect().left])")
    check("in the contents a row's time comes first, left of what was asked", rows and all(a < b for a, b in rows), rows)
    lefts = p.js("() => [...new Set([...document.querySelectorAll('#history .h time')].slice(0, 6).map((t) => Math.round(t.getBoundingClientRect().left)))]")
    check("...on one column", len(lefts) == 1, lefts)
    # The search on a row of its own, the filters under it
    tools = p.js("() => { const q = document.getElementById('hist-q').getBoundingClientRect(), f = document.querySelector('.hist-tools .combo-btn').getBoundingClientRect(), box = document.getElementById('hist-tools').getBoundingClientRect(); return { qw: Math.round(q.width), boxw: Math.round(box.width), below: f.top >= q.bottom - 1 }; }")
    check("the search has a row of its own, the filters under it", tools["below"] and tools["qw"] >= tools["boxw"] - 2, tools)
    # The agent's card not squeezed, and its profile in its own form
    prof = p.js("() => { const w = document.querySelector('#card-agent .agent-who'), a = w.querySelector('.ava'), c = getComputedStyle(a); return { ava: a.getBoundingClientRect().width, round: c.borderRadius, mail: w.querySelector('.mail').getBoundingClientRect().left > a.getBoundingClientRect().right, plan: w.querySelector('.how').getBoundingClientRect().top > w.querySelector('.mail').getBoundingClientRect().top }; }")
    check("the agent's profile: its initial in a round mark, the address beside it, the plan under the address", prof["ava"] >= 28 and prof["round"].startswith("50%") and prof["mail"] and prof["plan"], prof)
    pitch = p.js("() => { const r = [...document.querySelectorAll('#card-agent :is(.quota .q-bar, .agent-scale, .agent-viz + .facts)')].filter((e) => e.offsetParent).map((f) => f.getBoundingClientRect()); return r.slice(1).map((x, i) => Math.round(x.top - r[i].top)); }")
    check("...and its rows not squeezed: the meters, the scales and the model's row 20 px or more apart", pitch and all(d >= 20 for d in pitch), pitch)
    # Room between the title, the crop key and the picture
    gap = p.js("() => { const card = document.getElementById('shot').closest('.card'), h = card.querySelector('h2').getBoundingClientRect(), k = document.querySelector('.shot-tools').getBoundingClientRect(), s = document.getElementById('shot').getBoundingClientRect(); return [Math.round(s.top - h.bottom), Math.round(s.top - k.bottom)]; }")
    check("the picture stands clear of its title and the crop key", gap[0] >= 10 and gap[1] >= 8, gap)
    p.close()
    # No bookmark ribbon in the thread
    p = Page(br, s, many(4), w=1920, h=1040, settle=400)
    check("no ribbon in the thread", p.js("() => [...document.querySelectorAll('#thread .entry')].every((e) => getComputedStyle(e, '::before').content === 'none' || getComputedStyle(e, '::before').display === 'none')"))
    # A table drawn as a table: a ground of its own, not see-through, and a numbered caption on every one
    p.answer(1801, "work", "", "답", "## 예제 검증 (P = 7 2 1)\n\n| 가 | 나 |\n|---|---|\n| 1 | 2 |\n\n| 다 | 라 |\n|---|---|\n| 3 | 4 |\n")
    p.wait(250)
    tb = p.js("() => [...entryEl(1801).querySelectorAll('.tablewrap')].map((w) => [w.querySelector('.tablebar .lang')?.textContent.trim(), getComputedStyle(w).backgroundColor])")
    check("a table has a ground of its own", all(b not in ("rgba(0, 0, 0, 0)", "transparent") for _, b in tb), tb)
    check("...and a caption that says what it is, under a heading right over it or with none", tb[0][0] == "표 1. 예제 검증 (P = 7 2 1)" and tb[1][0].startswith("표 2. ") and len(tb[1][0]) > 5, tb)
    # The yellow highlighter and the term cards' colours stay
    p.answer(1802, "work", "", "답", "- **이름**: 설명입니다\n- **둘째**: 설명입니다\n\n**강조한 말**이 있는 문장입니다.\n")
    p.wait(250)
    col = p.js("() => { const li = entryEl(1802).querySelector('.v-terms > li'), t = li.querySelector('.v-t'), b = [...entryEl(1802).querySelectorAll('.md p strong')].pop(); return [getComputedStyle(li).backgroundColor, getComputedStyle(t).backgroundColor, getComputedStyle(b).backgroundImage]; }")
    check("term cards keep their card and their named chip", col[0] not in ("rgba(0, 0, 0, 0)",) and col[1] not in ("rgba(0, 0, 0, 0)",), col)
    check("...and stressed words their yellow", "gradient" in col[2], col[2])
    # The runs of the code drawn as a judge's
    # result, not a table: the verdict large, a tab for each run with the failed one in view, and the boxes of what went in, came out and was expected
    p.answer(1803, "code", "", "답", "풀이")
    p.send({"type": "check", "id": 1803, "lang": "python", "passed": 1, "total": 2, "how": "stdin", "rows": [{"input": "1\n", "expected": "1\n", "got": "1\n", "ok": True}, {"input": "2\n", "expected": "4\n", "got": "3\n", "ok": False}]})
    p.wait(250)
    same = p.js("""() => { const b = entryEl(1803).querySelector('.vcheck'); if (!b) return null; return { verdict: b.querySelector('.vc-verdict').textContent, count: b.querySelector('.vc-count').textContent, tabs: [...b.querySelectorAll('.vc-tab')].map((t) => [t.classList.contains('bad') ? 'bad' : 'ok', t.getAttribute('aria-selected')]), keys: [...b.querySelectorAll('.vc-case:not([hidden]) .vc-k')].map((k) => k.textContent), table: !!b.querySelector('table') }; }""")
    check("the runs of the code are a judge's result, not a table", same and same["verdict"] == "실패" and same["count"] == "1/2" and same["tabs"] == [["ok", "false"], ["bad", "true"]] and same["keys"] == ["입력", "출력", "기대 출력"] and not same["table"], same)
    p.js("() => entryEl(1803).querySelector('.vc-tab.ok').click()")
    shown = p.js("() => [...entryEl(1803).querySelectorAll('.vc-case')].map((c) => c.hidden)")
    check("...and a tab brings its run into view", shown == [False, True], shown)
    # A line saying what part of the screen went to the agent tells nothing worth reading
    p.send({"type": "analysis_start", "id": 1804, "ts": p.js("() => Date.now() / 1000"), "thumb": None, "transcript": "", "pages": 0, "trigger": "screen", "roi": None},
           {"type": "delta", "id": 1804, "text": "TYPE: work\nANSWER: 답\n\n풀이"},
           {"type": "analysis_done", "id": 1804, "text": "TYPE: work\nANSWER: 답\n\n풀이", "usage": {"input_tokens": 10, "output_tokens": 5}, "cost_usd": 0.01, "model": "m", "engine": "agent",
            "sent": [{"to": "agent", "what": "문제 부분 화면 1344x1600"}, {"to": "search", "what": "two sum hash map"}], "stages": {"local": True, "agent": True}, "elapsed": 3.0, "region": None})
    p.wait(250)
    # Moved into the details it still read "에이전트에 보냄 문제 부분 화면 1344×1600", word for word: what went to the agent is gone
    # from under the answer. The search words stay in the details: the agent's line was the one that told nothing
    sent = p.js("() => { const e = entryEl(1804); return { row: [...e.querySelectorAll('.row > .mg')].some((m) => m.textContent.includes('보낸 것')), agent: /1344|문제 부분 화면/.test(e.textContent), details: e.querySelector('.meta .meta-rest')?.textContent || '' }; }")
    check("what was sent to the agent is not written under the answer, not in a row and not in the details", not sent["row"] and not sent["agent"] and "토큰" in sent["details"], sent)
    check("...while the search words sent for it stay in its details", "웹 검색에 보냄" in sent["details"] and "two sum hash map" in sent["details"], sent)
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()
    # The agent's card, the contents' day tabs, one column at 1920 x 1040, and motion
    p = Page(br, s, many(30), w=1920, h=1040, settle=600)
    q = json.loads(json.dumps(h.ENGINES))
    q["agent"]["quota"] = {"session": {"used": 37.0, "resets": p.js("() => Date.now() / 1000") + 7980}, "week": {"used": 4.0, "resets": p.js("() => Date.now() / 1000") + 590000}, "models": [], "at": 1}
    q["agent"]["account"] = {"email": "reader@example.com", "plan": "Max 20x"}
    p.send({"type": "status", "engines": q})
    p.wait(1200)
    a = p.js("""() => { const c = document.getElementById('card-agent'), who = c.querySelector('.agent-who'), w = getComputedStyle(who), facts = [...c.querySelectorAll('#st-agent .agent-viz + .facts .fact')];
        const bars = [...c.querySelectorAll('.quota .q-bar')].map((b) => Math.round(b.getBoundingClientRect().width)), snug = document.querySelector('.rail').classList.contains('snug'),
            x0 = c.querySelector('.src').getBoundingClientRect().left, starts = [...c.querySelectorAll('.quota .q-bar')].map((b) => Math.round(b.getBoundingClientRect().left - x0)),
            cols = [...c.querySelectorAll('.usage-top .stat')].map((t) => Math.round(t.getBoundingClientRect().left - x0));
        return { box: w.backgroundColor !== 'rgba(0, 0, 0, 0)' && parseFloat(w.borderTopWidth) > 0 && parseFloat(w.paddingTop) >= 4, text: c.innerText,
                 facts: facts.map((f) => [f.querySelector('dt').textContent, Math.round(f.getBoundingClientRect().top)]), bars,
                 used: [...c.querySelectorAll('.quota .q-v b')].map((b) => b.textContent), fills: [...c.querySelectorAll('.quota .q-bar > i')].map((i) => i.style.width), snug, starts, cols }; }""")
    # The agent's profile in a box of its own
    check("the agent's profile stands in a box of its own", a["box"], a)
    # No thinking or output limit on the agent's card, which shows the plan's usage instead
    check("no thinking and no output limit on the agent's card", "thinking" not in a["text"] and "최대 출력" not in a["text"], a["text"][:200])
    # ...as the share used, not the share left, as Claude Code's own /usage says it
    check("...and the plan's usage: the session's and the week's meters, as shares used", a["used"] == ["37%", "4%"] and a["fills"] == ["37%", "4%"] and "사용" in a["text"] and "남음" not in a["text"], a)
    # stacked, the meters are one length; folded onto one row, each starts where the card's values start, the second at the tiles' fourth column
    check("...the meters on the card's columns", len(a["bars"]) == 2 and ((abs(a["starts"][0] - a["cols"][1]) <= 1 and abs(a["starts"][1] - a["cols"][3]) <= 1) if a["snug"] else abs(a["bars"][0] - a["bars"][1]) <= 1), a)
    # A day of the contents wears its index-tab shape
    tab = p.js("() => { const t = document.querySelector('#history .h-tab'), c = getComputedStyle(t); return [c.backgroundColor, c.borderTopWidth, c.borderTopLeftRadius, c.borderBottomLeftRadius]; }")
    check("a day of the contents is an index tab: a ground, a border and its top corners rounded", tab[0] not in ("rgba(0, 0, 0, 0)",) and float(tab[1].rstrip("px")) >= 1 and tab[2] != "0px" and tab[3] == "0px", tab)
    # The model and its effort on one row, in two columns
    check("the model and its effort on one row", [f[0] for f in a["facts"]] == ["모델", "생각 깊이"] and abs(a["facts"][0][1] - a["facts"][1][1]) <= 2, a["facts"])
    # The connected badge right beside its title
    gaps = p.js("() => [...document.querySelectorAll('.rail .src-top')].filter((t) => t.offsetParent).map((t) => Math.round(t.querySelector('.pill').getBoundingClientRect().left - t.querySelector('.src-name').getBoundingClientRect().right))")
    check("every source's state stands right beside its name", gaps and all(0 <= g <= 12 for g in gaps), gaps)
    # The live usage bars stay, and the right column is one column unless the window is very wide:
    # at 1920 x 1040 one column, the answers' bars, the capture's details, the contents' filters, the plan's meters and the profile all there
    seen = p.js("""() => { const on = (s) => [...document.querySelectorAll(s)].some((e) => e.offsetParent && e.getBoundingClientRect().height > 0);
        const g = [...document.querySelectorAll('.rail-col')].map((c) => getComputedStyle(c).display);
        return { one: g.every((d) => d === 'contents'), bars: on('#usage-local .bars') && on('#usage-agent .bars'), src: on('#st-screen .facts'), filters: on('.hist-tools .combo-btn'),
                 meters: on('.quota .q-bar'), who: on('.agent-who'), cls: document.querySelector('.rail').className }; }""")
    check("1920 x 1040: one column, with the answers' bars, the capture's details, the filters, the plan's meters and the profile", seen["one"] and seen["bars"] and seen["src"] and seen["filters"] and seen["meters"] and seen["who"], seen)
    # Motion is on by default though the system asks for less, and the menu turns it off
    calm_os = p.js("() => { localStorage.removeItem('sidenote-motion'); return [matchMedia('(prefers-reduced-motion: reduce)').matches, motionNow()]; }")
    check("motion is on by default, the system's wish for less notwithstanding", calm_os == [True, "on"], calm_os)
    check("the menu has a choice of motion", p.js("() => [...document.querySelectorAll('#motion-seg button')].map((b) => b.dataset.motion).join()") == "on,system,off")
    p.close()
    # ...and only a very wide window has the two groups side by side, with nothing taken away and the contents' rows
    p = Page(br, s, many(30), w=2560, h=1400, settle=600)
    wide = p.js("""() => { const g = [...document.querySelectorAll('.rail-col')].map((c) => c.getBoundingClientRect()), on = (s) => [...document.querySelectorAll(s)].some((e) => e.offsetParent && e.getBoundingClientRect().height > 0);
        return { side: g.length === 2 && g[1].left >= g[0].right, gauges: on('#gpu-viz'), scales: on('.agent-scale'), rows: [...document.querySelectorAll('#history .h')].filter((x) => { const r = x.getBoundingClientRect(), l = document.getElementById('history').getBoundingClientRect(); return r.top >= l.top - 1 && r.bottom <= l.bottom + 1; }).length }; }""")
    check("2560 x 1400: the controls and the screen side by side, the gauges and scales there, the contents with ten rows or more", wide["side"] and wide["gauges"] and wide["scales"] and wide["rows"] >= 10, wide)
    p.close()
    p = Page(br, s, many(3), w=1920, h=1040, settle=500, reduced=False)
    check("with no choice made, motion is on", p.js("() => document.documentElement.dataset.motion") == "on")
    p.js("() => document.querySelector('#motion-seg [data-motion=off]').click()")
    check("...and off once off is picked", p.js("() => [document.documentElement.dataset.motion, localStorage.getItem('sidenote-motion')]") == ["off", "off"])
    p.close()
    # The local model's card shows its figures too: with no answer in the last day, the last ones it gave
    p = Page(br, s, many(3), w=1920, h=1300, settle=400)
    usage = json.loads(json.dumps(h.USAGE))
    usage["engines"]["local"].update(window="recent")
    p.send(usage)
    p.wait(150)
    label = p.js("() => document.querySelector('#usage-local .stat .k')?.textContent")
    check("with none in the last day an engine shows its last answers' figures, said as such", label == "최근 답", label)
    p.close()


def group_motion(br, s):
    """Nothing moves at rest; what is drawn comes in once and ends where it would have stood anyway."""
    if not T.group("motion"):
        return
    rows = many(6)
    p = Page(br, s, rows, w=1920, h=1200, settle=1200, reduced=False)
    p.wait(2600)
    loops = p.js("""() => document.getAnimations().filter((a) => a.effect.getComputedTiming().iterations === Infinity).map((a) => (a.animationName || '') + ' ' + (a.effect.target?.id || a.effect.target?.className || ''))""")
    check("at rest nothing loops: no blinking key, dot or switch", not loops, loops)
    idle = p.js("""() => document.getAnimations().filter((a) => a.playState === 'running').length""")
    check("at rest nothing runs at all", idle == 0, idle)
    p.close()
    p = Page(br, s, rows, w=1920, h=1200, settle=0, reduced=False, status=False)
    p.js("""() => { window.__fell = 0; document.addEventListener('animationstart', (e) => { if (e.animationName === 'ribbon-drop') window.__fell++; }, true); }""")
    p.open_messages()
    p.wait(1500)
    check("the ribbon does not fall as the page opens", p.js("() => window.__fell") == 0, p.js("() => window.__fell"))
    start = p.js("() => document.getElementById('pause').querySelector('svg').outerHTML")
    p.js("() => setPaused(true)")
    p.wait(40)
    turning = p.js("""() => document.getAnimations().filter((a) => a.animationName === 'key-swap').length""")
    check("the pause key's mark turns when its state changes", turning >= 1 and p.js("() => document.getElementById('pause').querySelector('svg').outerHTML") != start, turning)
    p.js("() => setPaused(false)")
    p.wait(450)
    body = "1. **첫째**: 설명\n2. **둘째**: 설명\n\n- **이름**: 설명\n- **둘째 이름**: 설명\n\n| 항목 | 값 |\n|---|---|\n| 가 | 10 ms |\n| 나 | 20 ms |\n| 다 | 40 ms |\n\n시간 O(N), 공간 O(1)\n"
    p.answer(901, "algorithm", "물음", "시간 O(N), 공간 O(1)", body)
    p.wait(350)
    moving = p.js("""() => [...new Set(document.getAnimations().filter((a) => a.playState === 'running').map((a) => a.animationName))]""")
    check("an answer finished and seen draws itself in", any(m in moving for m in ("card-in", "step-pop", "rail-grow", "hl-sweep")), moving)
    p.wait(2600)
    still = p.js("""() => document.getAnimations().filter((a) => a.playState === 'running').map((a) => a.animationName)""")
    check("and comes to rest", not still, still)
    where = """(id) => [...entryEl(id).querySelectorAll('.v-terms > li, .md > ol > li, .v-bigo, .tablewrap, .v-pin')].map((e) => { const r = e.getBoundingClientRect(), o = entryEl(id).getBoundingClientRect(); return [Math.round(r.left - o.left), Math.round(r.top - o.top), Math.round(r.width), Math.round(r.height), getComputedStyle(e).opacity]; })"""
    moved = p.js(where, 901)
    # From here on, what plays is counted
    p.js("""() => { window.__played = {}; document.addEventListener('animationstart', (e) => { window.__played[e.animationName] = (window.__played[e.animationName] || 0) + 1; }, true); }""")
    played = lambda: p.js("() => { const c = window.__played; window.__played = {}; return c; }")  # noqa: E731
    IN = ("card-in", "fade-in", "mark-up", "step-pop", "rail-grow", "link-in")
    p.send({"type": "check", "id": 901, "lang": "python", "probe": True, "passed": 1, "total": 1, "rows": [{"input": "1", "got": "2", "ok": True}]})
    p.wait(120)
    check_again = played()
    check("an answer's check coming in does not play its pictures over", not any(check_again.get(k) for k in ("mark-up", "step-pop", "rail-grow", "link-in")) and check_again.get("card-in", 0) <= 1, check_again)
    p.wait(2300)
    played()
    p.js("() => { renderEntry(items.get(901)); }")
    p.wait(200)
    drawn_again = played()
    check("an answer drawn again does not play anything over", not any(drawn_again.get(k) for k in IN), drawn_again)
    # Usage: only the new answer's bar stands up, and none for a figure that is not a bar
    usage = json.loads(json.dumps(h.USAGE))
    usage["engines"]["local"]["tokens_in"] += 7
    p.send(usage)
    p.wait(120)
    check("a figure changing plays no bars", not played().get("bar-up"))
    usage["engines"]["local"]["recent"] = usage["engines"]["local"]["recent"][1:] + [{"ts": 1793509999, "elapsed": 9.0, "first_token": 1.0, "tps": 90.0}]
    usage["engines"]["local"]["answers"] += 1
    p.send(usage)
    p.wait(120)
    new_bar = played()
    check("a new answer's bar stands up, and only that one", new_bar.get("bar-up") == 1, new_bar)
    # The ribbon falls on a change of answer alone, not on a list drawn again
    p.page.locator("#hist-q").click()
    p.page.keyboard.type("물")
    p.wait(200)
    p.page.keyboard.press("Backspace")
    p.wait(200)
    p.page.locator("#hist-q").blur()
    p.wait(150)
    check("typing in the search does not make the ribbon fall", not played().get("ribbon-drop"))
    p.page.locator('#history .h[aria-current="false"]').first.click()
    try:
        p.page.wait_for_function("() => window.__played['ribbon-drop'] >= 1", timeout=6000)   # the view changes when the page's smooth scroll has arrived: slower on CI
    except Exception:
        pass
    fell = played()
    check("going to another answer does", fell.get("ribbon-drop", 0) >= 1, fell)
    p.close()
    # An old answer is simply there; a table taller than the window does not fade in as it is scrolled to
    p = Page(br, s, rows, w=1920, h=1000, settle=600, reduced=False)
    p.js("""() => { window.__played = {}; document.addEventListener('animationstart', (e) => { window.__played[e.animationName] = (window.__played[e.animationName] || 0) + 1; }, true); }""")
    p.js("() => { window.scrollTo(0, 0); stick = false; }")
    p.wait(500)
    old_ones = p.js("() => window.__played")
    check("an old answer scrolled to is simply there", not any(old_ones.get(k) for k in IN), old_ones)
    wide = "| 번호 | 값 |\n|---|---|\n" + "\n".join(f"| {i} | {i * 3} ms |" for i in range(200)) + "\n"
    p.answer(902, "work", "", "답", wide)
    p.wait(150)
    p.js("() => { window.__played = {}; entryEl(902).querySelector('.tablewrap').scrollIntoView({ block: 'center' }); }")
    p.wait(300)
    tall = p.js("() => window.__played")
    check("a table taller than the window does not fade in as it is scrolled to", not tall.get("fade-in"), tall)
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()
    p = Page(br, s, rows, w=1920, h=1200, settle=0, reduced=True, status=False)
    p.open_messages()
    p.wait(60)
    opening = p.js("""() => document.getAnimations().filter((a) => a.playState === 'running').map((a) => a.animationName)""")
    check("asked for less motion, the page opens without its cards coming in", not opening, opening)
    p.wait(500)
    p.answer(901, "algorithm", "물음", "시간 O(N), 공간 O(1)", body)
    p.wait(120)
    none = p.js("""() => document.getAnimations().filter((a) => a.playState === 'running').map((a) => a.animationName)""")
    check("asked for less motion, it stands there at once", not none, none)
    p.send({"type": "transcript", "text": "지금 들리는 말입니다.", "lang": "ko", "final": False})
    p.wait(60)
    words = p.js("""() => document.getAnimations().filter((a) => a.playState === 'running').map((a) => a.animationName)""")
    check("...and words heard do not make anything bob", not words, words)
    check("what came in stands where it would have stood without moving", p.js(where, 901) == moved, (moved[:3], p.js(where, 901)[:3]))
    p.close()


def group_audit(br, s):
    """The audit finds what is planted: each kind of defect, in a page otherwise as it is."""
    if not T.group("the audit itself"):
        return
    rows = many(6)
    plants = [
        ("cut", "a value cut with no tooltip", ".rail .fact dd { width: 30px !important; display: block !important; overflow: hidden !important; white-space: nowrap !important; } .rail .fact { display: block !important; }"),
        ("spill", "words out of a pill", ".rail .src-top .pill { width: 24px !important; overflow: visible !important; padding: 0 !important; white-space: nowrap !important; }"),
        ("overlap", "a label running into the tile beside it", ".rail .usage-top { overflow: visible !important; } .rail .usage .stat { overflow: visible !important; } .rail .usage .stat .k { white-space: nowrap !important; }", "() => { document.querySelector('#card-local .stat .k').textContent = '24시간 답 그리고 더 길게 쓴 이름입니다'; }"),
        # Each switch laid on the pill beside it, measured once the switches are out of the row: a place set in pixels from
        # the card's edge lands beside the pill as soon as the name before it grows
        ("covered", "words a box lies on", ".rail .card:first-child::after { content: ''; } #pill-screen { position: relative; } .rail .src-top .switch { position: absolute !important; z-index: 5; }",
         "() => { const keys = [...document.querySelectorAll('.rail .src-top .switch')]; document.body.offsetWidth; "
         "for (const k of keys) { const box = k.offsetParent.getBoundingClientRect(), pill = k.parentElement.querySelector('.pill').getBoundingClientRect(); "
         "k.style.setProperty('left', `${pill.left - box.left}px`, 'important'); k.style.setProperty('top', `${pill.top - box.top}px`, 'important'); "
         "k.style.setProperty('width', `${pill.width}px`, 'important'); } }"),
        ("rows", "a value a little lower than its label", ".rail.tight .fact dd, .rail .fact dd { position: relative; top: 2px; }"),
        ("columns", "one card's left edge two pixels off", ".rail .card:nth-child(2) { margin-left: 2px !important; }"),
        ("columns", "the second half a little off the tiles'", ".rail .fact:nth-child(even) dt { margin-left: 3px !important; }"),
        ("boxes", "words low in a key", "#gpu-load, #hist-export, .combo-btn, .btn { padding-top: 8px !important; padding-bottom: 0 !important; }"),
    ]
    for kind, what, css, *js in plants:
        p = Page(br, s, rows, w=1920, h=1300, settle=300)
        before = {(g["where"], g["detail"]) for g in p.js(AUDIT, OPTS) if g["kind"] == kind}
        p.js("(css) => { const st = document.createElement('style'); st.textContent = css; document.head.append(st); window.dispatchEvent(new Event('resize')); }", css)
        for step in js:
            p.js(step)
        p.wait(260)
        after = [g for g in p.js(AUDIT, OPTS) if g["kind"] == kind and (g["where"], g["detail"]) not in before]
        check(f"it finds {what} ({kind})", bool(after), after[:2])
        p.close()
    # The box of words in the settings sheet (Skip windows), which holds no words of the page's own for the rest to find
    for kind, what, css in (("spill", "a box of words wider than its sheet", ".set textarea.words { width: 160% !important; }"),
                            ("overlap", "a box of words over its row's name", ".set textarea.words { margin-top: -30px !important; }")):
        p = Page(br, s, rows, w=1920, h=1300, settle=300)
        p.send(support.settings_message())
        p.js("() => { openSettings(); document.querySelector(\".set-tab[data-sec='screen']\").click(); }")
        p.wait(250)
        before = {(g["where"], g["detail"]) for g in p.js(AUDIT, OPTS) if g["kind"] == kind}
        p.js("(css) => { const st = document.createElement('style'); st.textContent = css; document.head.append(st); }", css)
        p.wait(200)
        after = [g for g in p.js(AUDIT, OPTS) if g["kind"] == kind and (g["where"], g["detail"]) not in before and "words" in g["where"]]
        check(f"it finds {what} ({kind})", bool(after), after[:2])
        p.close()


def ink_mid(browser, png: bytes, x0: float, x1: float):
    """The middle of the rows with ink between columns x0 and x1 of a screenshot, against its colour at (4, 4), its edge rows left out:
    where the eye puts a mark or a word. Read by a page of its own, as pixels() is (the panel suites' interpreter may have no image library)."""
    import base64
    ctx = browser.new_context()
    pg = ctx.new_page()
    out = pg.evaluate("""async ([src, x0, x1]) => {
        const bits = await createImageBitmap(await (await fetch(src)).blob());
        const c = new OffscreenCanvas(bits.width, bits.height), g = c.getContext('2d');
        g.drawImage(bits, 0, 0);
        const d = g.getImageData(0, 0, bits.width, bits.height).data, at = (x, y) => (y * bits.width + x) * 4, bg = d.slice(at(4, 4), at(4, 4) + 3);
        const rows = [];
        // the box's own edge (a band's 1 px border) runs under every column: three rows at the top and the foot are left out
        for (let y = 3; y < bits.height - 3; y++) for (let x = Math.round(x0); x < Math.round(x1); x++) {
          const i = at(x, y);
          if (Math.abs(d[i] - bg[0]) + Math.abs(d[i + 1] - bg[1]) + Math.abs(d[i + 2] - bg[2]) > 60) { rows.push(y); break; }
        }
        return rows.length ? (rows[0] + rows[rows.length - 1]) / 2 : null;
    }""", ["data:image/png;base64," + base64.b64encode(png).decode(), x0, x1])
    ctx.close()
    return out


def group_controls(br, s):
    """The menu, keys and bands, an answer's head and its failure, the plan's meters, the question box and the dropdowns, each as a check
    that failed before its fix."""
    if not T.group("the menu, keys, bands, an answer's head, the meters and the question box"):
        return
    import time as _t
    p = Page(br, s, many(6), w=1920, h=1040, settle=400)
    # The menu's headings on its items' columns: mark at their marks, words at their words (they stood 6 and 8 px apart)
    p.js("() => document.getElementById('more').click()")
    p.wait(250)
    cols = p.js("""() => { const m = document.getElementById('menu').getBoundingClientRect();
        const txt = (el) => { const t = [...el.childNodes].find((n) => n.nodeType === 3 && n.textContent.trim()); const r = document.createRange(); r.selectNodeContents(t); return Math.round(r.getBoundingClientRect().left - m.left); };
        const mark = (el) => Math.round(el.getBoundingClientRect().left - m.left + parseFloat(getComputedStyle(el).paddingLeft));
        return { h3: [...document.querySelectorAll('#menu h3')].map((x) => [mark(x), txt(x)]), items: [...document.querySelectorAll('#menu .item')].filter((x) => x.offsetParent).map((x) => [mark(x), txt(x)]) }; }""")
    both = cols["h3"] + cols["items"]
    check("the menu's headings stand on its items' columns, marks and words", len({x[0] for x in both}) == 1 and len({x[1] for x in both}) == 1, cols)
    p.js("() => document.getElementById('more').click()")
    # Colours a later change once undid: the GPU key's green words, the highlighter on the words meant to stand out
    status(p, eng(local={"loaded": None}))
    p.wait(250)
    look = p.js("""() => ({ key: getComputedStyle(document.getElementById('gpu-load')).color, mark: getComputedStyle(document.querySelector('.rail .facts mark.key')).backgroundImage })""")
    check("the GPU key's words are green", look["key"] == "rgb(95, 224, 168)", look)
    check("'문제가 오면 자동으로 올림' wears the highlighter", "gradient" in look["mark"], look)
    # A limit band does not ask to turn on a model that is on
    now = p.js("() => Date.now() / 1000")
    status(p, eng(local={"ok": False, "on": True}, agent={"limit_until": now + 3 * 3600}))
    p.wait(250)
    lim = p.js("() => [...document.querySelectorAll('#alerts .alert')].map((a) => a.textContent).join(' | ')")
    check("a limit band does not ask to turn on a model that is on", "사용 한도" in lim and "켜면" not in lim, lim)
    # Its tone is the agent card's (orange; red with nothing to answer meanwhile), and no band beside it says every engine is
    # off: the limit band was green, and with the local model off a red "every engine is off" stood beside it
    tones = "() => [...document.querySelectorAll('#alerts .alert')].map((a) => [a.className, a.textContent.trim().slice(0, 24)])"
    status(p, eng(agent={"limit_until": now + 3 * 3600}))
    p.wait(250)
    ready = p.js(tones)
    status(p, eng(local={"on": False, "ok": True}, agent={"limit_until": now + 3 * 3600}) | {"ready": False})
    p.wait(250)
    alone = p.js(tones)
    # The local model's card in trouble says what to do: the pill and the model's row say what is wrong, and its note said it again
    notes = []
    for state in (st_local_missing, st_local_down):
        state(p)
        p.wait(200)
        notes.append(p.js("() => document.getElementById('st-local').textContent.replace(/\\s+/g, ' ').trim()"))
    check("the local model's card in trouble says what to do, not what is wrong a second time",
          notes[0].endswith("서버 터미널에서 모델 받기 ./sidenote llm pull, 그다음 ./sidenote up") and notes[1].endswith("서버 터미널에서 ./sidenote doctor")
          and "없음." not in notes[0] and "응답 없음." not in notes[1], notes)
    check("a limit band in the agent card's tone, red when nothing answers meanwhile, and no 'every engine is off' beside it",
          any("warn" in c and "사용 한도" in x for c, x in ready) and any("bad" in c and "사용 한도" in x for c, x in alone)
          and not any("모두 꺼짐" in x for _, x in alone), [ready, alone])
    status(p, eng())
    # The capture program is started on the PC whose screen it reads: the capture PC is the server's client
    capture(p, clients=0)
    p.wait(250)
    cap = p.js("() => document.getElementById('st-screen').textContent")
    check("a capture program that is off is started on the capture PC, not the server's terminal", "캡처 PC에서" in cap and "서버 터미널" not in cap, cap)
    capture(p)
    # An answer's head: the problem text's copy key has its own mark; a failed answer's date stands where every date does; its command is a chip
    p.answer(1801, "essay", "", "답", "풀이")
    p.wait(150)
    p.send({"type": "problem_text", "id": 1801, "text": "문제 글"})
    p.send({"type": "analysis_start", "id": 1802, "ts": now, "thumb": None, "transcript": "", "pages": 0, "trigger": "screen", "roi": None})
    p.send({"type": "error", "id": 1802, "text": "RuntimeError: boom", "hint": ""})
    p.wait(300)
    marks = p.js("() => { const e = entryEl(1801), a = e.querySelector('[data-copy-item] svg'), b = e.querySelector('[data-copy-ptext] svg'); return a && b ? [a.innerHTML, b.innerHTML] : null; }")
    check("the problem text's copy key has a mark of its own", bool(marks) and marks[0] != marks[1], marks)
    dates = p.js("""() => [entryEl(1801), entryEl(1802)].map((e) => { const t = e.querySelector('.row.head .mg time').getBoundingClientRect(), h2 = e.querySelector('.errbox h2');
        return [Math.round(t.left), h2 ? Math.round(h2.getBoundingClientRect().top - t.bottom) : null]; })""")
    check("a failed answer's date stands where every answer's does, over what went wrong", abs(dates[0][0] - dates[1][0]) <= 1 and dates[1][1] is not None and dates[1][1] >= 0, dates)
    box = p.js("() => { const b = entryEl(1802).querySelector('.errbox'); return [!!b.querySelector('code.cmd'), !!b.querySelector('[data-copy]'), b.querySelector('p').textContent]; }")
    check("the failure box gives its command as a chip with a copy key", box[0] and box[1], box)
    check("the key stands last in its clause, with no particle after it to stand apart from the chip", "한 번 더: 다시 분석" in box[2], box[2])
    p.send({"type": "status", "text": "connected", "paused": True, "lang": "auto", "audio": True, "voice": True, "can_ask": True, "run_enabled": True, "runner": True, "engines": eng()})
    p.wait(200)
    band = p.js("() => document.getElementById('alerts').textContent")
    check("...and on the pause band", "지금 화면만 풀려면 다시 분석" in band, band)
    status(p, eng())
    # The agent's review: named on one line in the margin, and no colon standing alone in its line
    p.send({"type": "verify", "id": 1801, "verdict": "fix", "text": "TYPE: essay\nANSWER: 다른 답\n\n이유", "sent": []})
    p.wait(250)
    vr = p.js("""() => { const row = [...entryEl(1801).querySelectorAll('.row')].find((r) => r.querySelector('.cap.check')); if (!row) return null;
        const mg = row.querySelector('.mg'), cap = row.querySelector('.cap.check');
        return [mg.textContent.trim(), Math.round(mg.getBoundingClientRect().height), [...cap.childNodes].filter((n) => n.nodeType === 3 && n.textContent.trim()).map((n) => n.textContent.trim())]; }""")
    check("the agent's review is named on one line in the margin", bool(vr) and vr[1] <= 26, vr)
    check("...and its line has no colon standing alone between its parts", bool(vr) and not vr[2], vr)
    # The working line: one way of saying it, parts set apart by dots, no brackets in a row
    p.send({"type": "analysis_start", "id": 1803, "ts": now, "thumb": None, "transcript": "들은 문제", "pages": 0, "trigger": "voice", "roi": None})
    p.send({"type": "stage", "id": 1803, "stage": "think", "detail": "생각 1,200자"})
    p.wait(1300)
    foot = p.js("() => [...document.querySelectorAll('[data-pending]')].map((x) => x.textContent).filter(Boolean).join(' | ')")
    check("the working line sets its parts apart one way, with no brackets in a row", bool(foot) and ") (" not in foot and "·" in foot, foot)
    # The plan's meters: a window past its reset is not running, and a reading grown old is drawn faint
    status(p, eng(agent={"quota": {"session": {"used": 95.0, "resets": now - 60}, "week": {"used": 40.0, "resets": now + 86400}, "models": [], "at": now - 900}}))
    p.wait(300)
    q = p.js("""() => [...document.querySelectorAll('#st-agent .quota')].map((x) => [x.dataset.k, x.querySelector('.q-v').textContent, x.classList.contains('old')])""")
    check("a session past its reset stands as not started, not at its old share a minute from resetting", any(k == "session" and "시작 전" in v and "95%" not in v for k, v, _ in q), q)
    check("...and a reading fifteen minutes old is drawn faint", bool(q) and all(o for _, _, o in q), q)
    p.close()
    # The band's mark level with its words in the bar (its ink sat 2 px under theirs)
    b = Page(br, s, many(6), w=2560, h=1200, settle=400)
    status(b, eng(local={"ok": False}))
    b.js("() => { stick = false; window.scrollTo(0, 0); }")
    b.wait(250)
    b.js("() => { window.scrollTo(0, 0); placeBands(); }")
    b.wait(250)
    at = b.js("""() => { const a = document.querySelector('#alerts .alert'); if (!a || !document.documentElement.classList.contains('bands-in-bar')) return null;
        const r = a.getBoundingClientRect(), s = a.querySelector('svg').getBoundingClientRect(), w = a.querySelector('.msg b').getBoundingClientRect();
        return { clip: [r.left, r.top, r.width, r.height], mark: [s.left - r.left, s.right - r.left], words: [w.left - r.left, w.left - r.left + 30] }; }""")
    lv = None
    if at:
        png = b.page.screenshot(clip={"x": at["clip"][0], "y": at["clip"][1], "width": at["clip"][2], "height": at["clip"][3]})
        mark, words = ink_mid(br, png, *at["mark"]), ink_mid(br, png, *at["words"])
        lv = None if mark is None or words is None else [mark, words]
    check("a band in the bar has its mark level with its words, by their ink", lv is not None and abs(lv[0] - lv[1]) <= 1, lv)
    b.close()
    # A notice in the bar, over none of the bands at the thread's head: under the bar it lay on the last of them (8 px into
    # it), then over the thread's cards under them
    n = Page(br, s, many(6), w=900, h=900, settle=400)
    status(n, eng(local={"ok": False}))
    n.js("() => { stick = false; window.scrollTo(0, 0); }")
    n.wait(200)
    n.js("() => { placeBands(); toast('알림 하나', null, 'warn'); }")
    n.wait(450)
    tb = n.js("""() => { const t = document.getElementById('toast').getBoundingClientRect(), b = document.querySelector('header.bar').getBoundingClientRect(),
        a = document.getElementById('alerts').getBoundingClientRect();
        return [document.documentElement.classList.contains('bands-in-bar'), t.top >= b.top && t.bottom <= b.bottom, a.height > 0,
                Math.max(0, Math.min(t.bottom, a.bottom) - Math.max(t.top, a.top))]; }""")
    check("a notice stands in the bar, over none of the bands at the thread's head", not tb[0] and tb[1] and tb[2] and tb[3] == 0, tb)
    n.close()
    # Folded to one line, the profile gives its plan whole: "Claude Code Max ..." was cut at 1366x768
    n = Page(br, s, many(6), w=1366, h=768, settle=400)
    prof = n.js("""() => { const how = document.querySelector('#st-agent .agent-who .how'); if (!how) return null; const snug = document.querySelector('.rail').classList.contains('snug');
        return { snug, cut: how.scrollWidth > how.clientWidth + 1, prod: how.querySelector('.prod') ? getComputedStyle(how.querySelector('.prod')).display : null }; }""")
    check("the profile folded to one line gives its plan whole", bool(prof) and (not prof["snug"] or (prof["prod"] == "none" and not prof["cut"])), prof)
    n.close()
    # With the server away: the key shows what pressing it does while watching (the two bars), the cards say when they will know, the arrow names no mode
    w = Page(br, s, [], w=1366, h=768, settle=300, status=False)
    w.js("() => { wsState = 'down'; renderAll(); }")
    w.wait(250)
    down = w.js("""() => ({ icon: document.getElementById('pause-icon').innerHTML.includes('rect'), local: document.getElementById('st-local').textContent.trim(),
        edge: [...document.querySelectorAll('#welcome text.edge')].map((t) => t.textContent.trim()) })""")
    check("with the server away the key shows the pause mark, the cards say when they will know, and the arrow names no mode",
          down["icon"] and "서버 연결 후 확인" in down["local"] and all(not e for e in down["edge"]), down)
    w.close()
    # A day chosen, the kinds offered are that day's ("0/22 맞는 답 없음" for a kind the day had none of)
    r = Page(br, s, [row(300, "mcq", ago=60), row(301, "essay", ago=86400 * 2)], w=1920, h=1040, settle=400)
    kinds = r.js("() => { histDay = dayOf(items.get(301).ts); renderIndex(); return [...document.getElementById('hist-kind').options].map((o) => o.value).filter(Boolean); }")
    check("a day chosen, the kinds offered are that day's", kinds == ["essay"], kinds)
    # The question box grows with a long question and its start stays in sight; Enter sends, Shift+Enter starts a line, an IME's Enter is its own
    r.js("() => { const a = document.getElementById('ask'); a.value = '아주 긴 추가 질문 '.repeat(30); a.dispatchEvent(new Event('input', { bubbles: true })); }")
    r.wait(150)
    grow = r.js("() => { const a = document.getElementById('ask'); return [a.tagName, Math.round(a.getBoundingClientRect().height), a.scrollTop]; }")
    check("a long question grows the box, its start in sight", grow[0] == "TEXTAREA" and 60 <= grow[1] <= 141 and grow[2] == 0, grow)
    r.js("() => { const a = document.getElementById('ask'); a.value = ''; a.dispatchEvent(new Event('input', { bubbles: true })); window.__sent = []; }")
    r.page.locator("#ask").click()
    r.page.keyboard.type("첫 줄")
    r.page.keyboard.press("Shift+Enter")
    r.page.keyboard.type("둘째 줄")
    r.js("() => document.getElementById('ask').dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', isComposing: true, bubbles: true, cancelable: true }))")
    sent_mid = r.js("() => (window.__sent || []).filter((m) => m.type === 'ask').length")
    r.page.keyboard.press("Enter")
    r.wait(150)
    asks = r.js("() => (window.__sent || []).filter((m) => m.type === 'ask').map((m) => m.text)")
    check("Shift+Enter starts a line, an Enter while composing is the IME's, Enter sends", sent_mid == 0 and asks == ["첫 줄\n둘째 줄"], [sent_mid, asks])
    check("...and the box goes back to one line", r.js("() => Math.round(document.getElementById('ask').getBoundingClientRect().height)") <= 42)
    r.close()
    # A dropdown's list ends on its key's edge (its width was read while it opened, drawn smaller, and it stood 4 px off)
    c = Page(br, s, many(4), w=1920, h=1040, settle=400, reduced=False)
    c.page.locator(".hist-tools .combo-btn").nth(1).click()
    c.wait(500)
    edge = c.js("() => { const o = comboOpen; if (!o) return null; return [Math.round(o.btn.getBoundingClientRect().right), Math.round(o.list.getBoundingClientRect().right)]; }")
    check("a dropdown's list ends on its key's edge", bool(edge) and abs(edge[0] - edge[1]) <= 1, edge)
    c.close()


STAR_WIDTHS = (360, 390, 768, 1000, 1001, 1100, 1280, 1366, 1440, 1920, 2560)
# An answer's head with its star key, and a row of the contents with its star, as laid out
STAR_LOOK = """(id) => {
  const e = entryEl(id), tools = e.querySelector(':scope > .row.head .tools'), keys = [...tools.children].filter((b) => b.offsetParent);
  const box = (x) => { const r = x.getBoundingClientRect(); return { l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height }; };
  const key = tools.querySelector('[data-star]');
  if (!key) return { missing: true };   // said as a check that failed, not as an error that ends the suite
  // the answer's writing column: the first that has a box, as on a narrow window the head's own has none (its words and keys
  // stand in the head's row, index.html)
  const svg = key.querySelector('svg'), ct = [...e.querySelectorAll(':scope > .row > .ct')].find((c) => c.getBoundingClientRect().width > 0);
  const date = e.querySelector(':scope > .row.head time');
  const p = document.createElement('i'); p.style.color = 'var(--hl-yellow)'; document.body.append(p); const token = getComputedStyle(p).color; p.remove();
  // the answer's own inner edges: a head row laid out wider than the page carries its column out with it, so the column is no measure
  const page = e.getBoundingClientRect(), pad = getComputedStyle(e);
  // its place: just before Copy all and Delete, the last two keys, or before what of them an answer has, so it stays put whatever
  // keys come before it
  const names = keys.map((b) => Object.keys(b.dataset)[0]), after = names.slice(keys.indexOf(key) + 1).join(",");
  const placed = ["", "copyItem", "copyItem,delete", "delete"].includes(after);
  const out = { keys: keys.map(box), names, placed, fromEnd: tools.getBoundingClientRect().right - key.getBoundingClientRect().right, key: box(key), svg: box(svg), ct: box(ct), date: box(date), W: innerWidth,
                inner: { l: page.left + parseFloat(pad.paddingLeft), r: page.right - parseFloat(pad.paddingRight) },
                fill: getComputedStyle(svg).fill, token, pressed: key.getAttribute('aria-pressed') };
  const rowEl = document.querySelector(`#history .h[data-id="${id}"]`), star = rowEl?.querySelector('.h-star');
  if (star) {
    const ht = rowEl.querySelector('.ht'), words = document.createRange(), text = [...ht.childNodes].find((n) => n.nodeType === 3 && n.nodeValue.trim());
    words.selectNodeContents(text);
    const plain = [...document.querySelectorAll('#history .h')].find((x) => !x.querySelector('.h-star'));
    out.row = { star: box(star), row: box(rowEl), ht: box(ht), time: box(rowEl.querySelector('time')), words: box(words), plainH: plain ? plain.getBoundingClientRect().height : null,
                fill: getComputedStyle(star).fill };
  }
  return out;
}"""


def group_star(br, s):
    """The star key on an answer's head, and the star on a starred row of the contents, at every width from 360 to 2560 in both themes: the
    key is the size of the keys beside it, in their row and at their spacing, inside the page, its mark in its middle, filled with the
    highlighter once starred; the row's star stands inside its row before the words, on their middle, and makes the row no taller."""
    if not T.group("the star key, at every width"):
        return
    # the newest three stand open, the older two folded with Fold beside the star; 1951 and 1953 starred
    rows = [row(1950 + i, "essay", f"이것은 꽤 길게 쓴 문제의 물음입니다 {i} " * 2, "답", "풀이", ago=900 - i * 30, starred=i in (1, 3)) for i in range(5)]
    for theme in ("dark", "light"):
        bad = {k: [] for k in ("size", "row", "gap", "inside", "mark", "fill", "line", "rowstar", "place")}
        for w in STAR_WIDTHS:
            p = Page(br, s, rows, w=w, h=900, theme=theme, settle=350)
            ends = {}
            for i in (1951, 1953, 1954):   # folded and starred, open and starred, open and not
                m, at = p.js(STAR_LOOK, i), f"{w} #{i}"
                if m.get("missing"):
                    bad["size"].append([at, "no star key"])
                    continue
                k, ks = m["key"], m["keys"]
                ends[i] = round(m["fromEnd"], 1)
                # the same key as the others: a pressable square of their size, in its place in their row
                if not (m["placed"] and k["w"] >= 24 and k["h"] >= 24 and all(abs(x["w"] - k["w"]) <= .5 and abs(x["h"] - k["h"]) <= .5 for x in ks)):
                    bad["size"].append([at, [(round(x["w"], 1), round(x["h"], 1)) for x in ks]])
                if not all(abs(x["t"] - k["t"]) <= .5 for x in ks):
                    bad["row"].append([at, [round(x["t"], 1) for x in ks]])
                gaps = [round(b["l"] - a["r"], 1) for a, b in zip(ks, ks[1:])]
                # Delete, last, stands 4 px further off (index.html, [data-delete]); every other gap is the same
                apart = m["names"][-1:] == ["delete"] and len(gaps) >= 2
                even = gaps[:-1] if apart else gaps
                if even and max(even) - min(even) > .5:
                    bad["gap"].append([at, gaps])
                if apart and not 3.5 <= gaps[-1] - gaps[0] <= 4.5:
                    bad["gap"].append([at, "Delete not 4 px apart", gaps])
                # inside the answer's writing, the answer's page and the window, at every width
                if not (k["l"] >= m["ct"]["l"] - .5 and ks[-1]["r"] <= m["ct"]["r"] + .5 and k["l"] >= m["inner"]["l"] - .5
                        and ks[-1]["r"] <= m["inner"]["r"] + .5 and m["ct"]["r"] <= m["inner"]["r"] + .5 and ks[-1]["r"] <= m["W"]):
                    bad["inside"].append([at, round(k["l"], 1), round(ks[-1]["r"], 1), round(m["ct"]["r"], 1), round(m["inner"]["r"], 1)])
                # its mark in its middle
                if abs((m["svg"]["l"] + m["svg"]["r"]) / 2 - (k["l"] + k["r"]) / 2) > .5 or abs((m["svg"]["t"] + m["svg"]["b"]) / 2 - (k["t"] + k["b"]) / 2) > .5:
                    bad["mark"].append([at, m["svg"], k])
                starred = i != 1954
                if (m["fill"] == m["token"]) != starred or m["pressed"] != str(starred).lower():
                    bad["fill"].append([at, m["fill"], m["token"], m["pressed"]])
                # the keys on the line of the date, unless the window is too narrow for both, and then on a line of their own under it
                if not (abs((k["t"] + k["b"]) / 2 - (m["date"]["t"] + m["date"]["b"]) / 2) <= 1 or k["t"] >= m["date"]["b"]):
                    bad["line"].append([at, k, m["date"]])
                r = m.get("row")
                if starred and not r:
                    bad["rowstar"].append([at, "no star on its row"])
                elif r:
                    mid = lambda b: (b["t"] + b["b"]) / 2  # noqa: E731
                    ok = (r["star"]["l"] >= r["ht"]["l"] - .5 and r["star"]["r"] <= r["words"]["l"] + .5 and r["star"]["l"] >= r["time"]["r"]
                          and r["star"]["t"] >= r["row"]["t"] and r["star"]["b"] <= r["row"]["b"] and abs(mid(r["star"]) - mid(r["words"])) <= 1
                          and r["plainH"] is not None and abs(r["row"]["h"] - r["plainH"]) <= .5 and r["fill"] == m["token"])
                    if not ok:
                        bad["rowstar"].append([at, r])
            # a folded answer has Show the solution among its keys, an open one Fold: the star stands where it stood
            if ends and max(ends.values()) - min(ends.values()) > .5:
                bad["place"].append([w, ends])
            if p.errors:
                check(f"{theme} {w}: the page threw nothing", False, p.errors[:2])
            p.close()
        check(f"{theme}: the star key is the keys' size, just before Copy all and Delete, pressable", not bad["size"], bad["size"][:3])
        check(f"{theme}: ...at the same place on a folded answer as on an open one, whatever keys come before it", not bad["place"], bad["place"][:3])
        check(f"{theme}: ...in their row", not bad["row"], bad["row"][:3])
        check(f"{theme}: ...at their spacing, Delete a little apart", not bad["gap"], bad["gap"][:3])
        check(f"{theme}: ...inside the answer and the window, from 360 to 2560", not bad["inside"], bad["inside"][:3])
        check(f"{theme}: ...its star in its middle", not bad["mark"], bad["mark"][:2])
        check(f"{theme}: ...filled with the highlighter when starred, an outline when not", not bad["fill"], bad["fill"][:3])
        check(f"{theme}: ...on the date's line, or a line of their own under it", not bad["line"], bad["line"][:2])
        check(f"{theme}: a starred row's star stands before its words, inside the row, on the words' middle, the row no taller", not bad["rowstar"], bad["rowstar"][:2])


def group_recheck(br, s):
    """What later fixes took away, or never brought to a 1920x1040 window: the question box when it is off, the GPU's line, the pause
    key, and a thread shorter than the right column. Each failed before its fix."""
    if not T.group("the question box off, the GPU's line, the pause key, a short thread"):
        return
    p = Page(br, s, many(6), w=1920, h=1040, settle=400)
    # Off, the question box is a little more opaque, of frosted glass. The box became a textarea and the rules for its
    # off look, written for an input, matched nothing: off, it looked exactly like an open one
    look = """() => { const c = document.querySelector('.composer'), a = document.getElementById('ask'), cs = getComputedStyle(c);
        return { off: a.disabled, tag: a.tagName, edge: cs.backgroundImage, blur: cs.backdropFilter || cs.webkitBackdropFilter || '',
                 hint: getComputedStyle(a, '::placeholder').color }; }"""
    p.send({"type": "status", "text": "connected", "paused": False, "lang": "auto", "audio": True, "voice": True, "can_ask": False,
            "run_enabled": True, "runner": True, "engines": eng()})
    p.wait(250)
    off = p.js(look)
    status(p, eng())
    p.wait(250)
    on = p.js(look)
    check("the question box looks off when it is off: a fainter edge, the glass blur, a grey hint",
          off["off"] and not on["off"] and off["tag"] == "TEXTAREA" and off["edge"] != on["edge"] and "blur" in off["blur"] and off["hint"] != on["hint"], [off, on])
    # '문제가 오면 자동으로 올림' stands out in the yellow highlighter. On a 1920x1040 window the
    # column folded the GPU's gauge, and the figures put on the GPU's line in its place had taken these words' place too
    capture(p)
    status(p, eng(local={"loaded": None}))
    p.send({**h.GPU, "used": 1200, "util": 1})
    p.wait(400)
    g = p.js("""() => { const m = document.querySelector('.rail .gpu-says mark.key'), r = m && m.getBoundingClientRect(), v = document.getElementById('gpu-viz');
        return { says: m ? [Math.round(r.width), Math.round(r.height), m.textContent] : null, mark: m ? getComputedStyle(m).backgroundImage : '',
                 gauge: Math.round(v.getBoundingClientRect().height), cls: document.querySelector('.rail').className }; }""")
    check("on a 1920x1040 window an empty GPU says '문제가 오면 자동으로 올림' in the highlighter, its gauges there too",
          bool(g["says"]) and g["says"][0] > 0 and g["says"][1] > 0 and "올림" in g["says"][2] and "gradient" in g["mark"] and g["gauge"] > 40 and g["cls"] in ("rail stick", "rail drift"), g)
    # ...and a loaded one its gauges and the details of the model it holds, the same at every resolution
    status(p, eng(local={"loaded": {"model": "sidenote-gemma4:26b", "vram_gb": 16.2, "params": "25.2B", "quant": "Q4_K_M", "ctx": 16384}}))
    p.send(h.GPU)
    p.wait(400)
    up = p.js("() => [Math.round(document.getElementById('gpu-viz').getBoundingClientRect().height), document.getElementById('st-local').innerText]")
    check("...and a loaded one its gauges and the model's size, quantization and context", up[0] > 40 and all(w in up[1] for w in ("25.2B", "Q4_K_M", "16,384")), up)
    # The pause key's mark is what pressing it does, as its tooltip
    # says, the two bars while it watches and the triangle while paused; its colour stays the state's, green watching and orange paused
    key = """() => { const b = document.getElementById('pause'); return { mark: document.getElementById('pause-icon').innerHTML.includes('rect') ? 'bars' : 'triangle', title: b.title, colour: getComputedStyle(b).color }; }"""
    watching = p.js(key)
    p.send({"type": "status", "text": "connected", "paused": True, "lang": "auto", "audio": True, "voice": True, "can_ask": True, "run_enabled": True, "runner": True, "engines": eng()})
    p.wait(450)
    held = p.js(key)
    status(p, eng())
    p.wait(300)
    rgb = lambda c: [int(float(x)) for x in c[c.index("(") + 1:c.index(")")].split(",")[:3]]
    green, orange = rgb(watching["colour"]), rgb(held["colour"])
    check("the pause key shows what pressing it does: the bars while watching, in green; the triangle while paused, in orange",
          watching["mark"] == "bars" and "멈추기" in watching["title"] and held["mark"] == "triangle" and "계속" in held["title"]
          and green[1] > green[0] and orange[0] > orange[1] > orange[2], [watching, held])
    # A thread shorter than the right column, which makes the page longer than the thread (the page is as tall as the column): scrolled to the
    # page's end the question box stands at the window's foot, clear of a notice at the top (it had rested at the thread's end, in the
    # window's middle, and CI caught a notice over it); and following a new answer goes to the thread's end, not to the page's foot
    q = Page(br, s, [row(1901, "short", "문제", "답", "짧은 풀이")], w=1440, h=900, settle=400)
    q.js("() => { stick = false; window.scrollTo(0, document.scrollingElement.scrollHeight); }")
    q.wait(300)
    q.js("() => toast('지금 화면을 다시 분석합니다.')")
    q.wait(300)
    foot = q.js("""() => { const f = document.getElementById('askform').getBoundingClientRect(), t = document.getElementById('toast').getBoundingClientRect(),
        r = document.querySelector('.rail').getBoundingClientRect(), th = document.getElementById('thread').getBoundingClientRect();
        return { ask: [Math.round(f.top), Math.round(f.bottom)], win: innerHeight, overlap: Math.max(0, Math.min(f.bottom, t.bottom) - Math.max(f.top, t.top)), taller: r.height > th.height + 200 }; }""")
    check("a thread shorter than the right column: at the page's end the question box stands at the window's foot, clear of a notice",
          foot["taller"] and foot["win"] - 60 <= foot["ask"][1] <= foot["win"] and foot["overlap"] == 0, foot)
    q.js("() => { window.scrollTo(0, 0); stick = true; }")
    q.answer(1902, "short", "", "답", "짧은 풀이 둘")
    q.wait(500)
    end = q.js("() => { const e = entryEl(1902).getBoundingClientRect(); return [Math.round(e.top), Math.round(e.bottom), innerHeight, Math.round(scrollY)]; }")
    check("...and following a new answer keeps the thread's end in view, not the foot of the page", end[0] >= 0 and end[1] <= end[2], end)
    q.close()
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()


def group_release(br, s):
    """The notice of a newer release, audited at every width from a phone's to a wide screen's in both themes and in English and Korean
    (the English words are the longer), at the top of the page (in the bar where it fits) and scrolled (floating under the bar): what the
    audit finds on the band's own words, link and key."""
    if not T.group("the release notice in the band"):
        return
    found = []
    for locale in ("en-US", "ko-KR"):
        for theme in ("dark", "light"):
            for w, hh in ((360, 760), (390, 844), (414, 896), (768, 1024), (1000, 800), (1001, 700), (1366, 768), (1920, 1080), (2560, 1440)):
                p = Page(br, s, many(), w=w, h=hh, theme=theme, settle=250, locale=locale)
                st_update(p)
                for at in ("top", "scrolled"):
                    p.js("(y) => { stick = false; window.scrollTo(0, y); placeBands(); }", 0 if at == "top" else 900)
                    p.wait(220)
                    # the band's findings: its words, link and key, and anything over them (the rest of the page has its own states above)
                    found += [g for g in audit(p, f"release, {at}", f"{w}x{hh} {theme} {locale[:2]}") if "alert" in g["where"] or "msg" in g["where"]]
                shown = p.js("() => !!document.querySelector('#alerts [data-act=\"update-hide\"]')")
                if not shown or p.errors:
                    check(f"{locale[:2]} {theme} {w}x{hh}: the notice is drawn, and the page threw nothing", False, p.errors[:2])
                p.close()
    record(found)
    report("the release notice", found)


def group_column_kept(br, s):
    """The column, the welcome and the answers' heads, at the sizes and in the language each shows in: the Local
    model's pill cut to "On GP" by the English GPU key beside it; the welcome's engines still ticked with the server gone; a
    spoken problem's "heard by voice" taking two lines beside the keys and pushing them off the date's line on a phone; a
    choice's keys wrapping one alone on a narrow sheet; the capture card's second values 4 px apart in English."""
    if not T.group("the column, the welcome and a phone's heads"):
        return
    for state, loaded in (("on the GPU", h.ENGINES["local"]["loaded"]), ("idle", None)):
        p = Page(br, s, many(3), w=1366, h=768, settle=400, locale="en-US", query="?lang=en")
        p.send({"type": "status", "engines": {**h.ENGINES, "local": {**h.ENGINES["local"], "loaded": loaded}}})
        p.wait(250)
        got = p.js("() => { const pl = document.getElementById('pill-local'); return { text: pl.textContent, room: pl.clientWidth, need: pl.scrollWidth }; }")
        check(f"the Local model's pill whole beside its GPU key in English at 1366, {state}", got["need"] <= got["room"] + 1, got)
        p.close()
    p = Page(br, s, [], w=1440, h=900, settle=400)
    p.drop()
    p.wait(400)
    ticked = p.js("() => [...document.querySelectorAll('.welcome .steps li')].filter((li) => li.dataset.done === 'true').map((li) => li.querySelector('.t')?.textContent)")
    check("with the server gone the welcome ticks no engine as connected", not ticked, ticked)
    p.close()
    voice = dict(h.row(9, "algorithm", "", "해시맵으로 한 번 훑는다", "풀이", ago=10), trigger="voice", transcript="What is a hash map, and why is a lookup O(1)?")
    p = Page(br, s, many(3) + [voice], w=390, h=844, settle=500, locale="en-US", query="?lang=en")
    p.wait(300)
    got = p.js("""() => { const e = document.querySelector('.entry[data-id="9"]'), via = e?.querySelector('.headline > span:not(.tools)'), keys = e?.querySelector('.tools'), date = e?.querySelector('.row.head time');
      if (!via || !keys || !date) return null; const v = via.getBoundingClientRect(), k = keys.getBoundingClientRect(), d = date.getBoundingClientRect();
      return { keysOnDate: Math.abs((k.top + k.bottom) / 2 - (d.top + d.bottom) / 2) < 8, viaUnder: v.top >= k.bottom - 1, oneLine: v.height < parseFloat(getComputedStyle(via).lineHeight || 18) * 1.5 + 1 }; }""")
    check("on a phone a spoken problem's 'heard by voice' stands on a line of its own under its keys, the keys on the date's line",
          got == {"keysOnDate": True, "viaUnder": True, "oneLine": True}, got)
    p.close()
    p = Page(br, s, many(3), w=390, h=844, settle=400, locale="en-US", query="?lang=en")
    p.send(support.settings_message())
    p.js("() => { openSettings(); document.querySelector(\".set-tab[data-sec='agent']\").click(); }")
    p.wait(300)
    got = p.js("""() => [...document.querySelectorAll('#settings-body .set .seg')].map((g) => { const b = [...g.querySelectorAll('button')].map((x) => x.getBoundingClientRect());
      return { keys: b.length, widths: new Set(b.map((r) => Math.round(r.width))).size, columns: new Set(b.map((r) => Math.round(r.left))).size }; }).filter((g) => g.keys > 1)""")
    check("on a narrow sheet a choice's keys stand in even columns, none of another width alone on a row",
          bool(got) and all(g["widths"] == 1 and g["columns"] >= 2 for g in got), got)
    p.close()
    p = Page(br, s, many(3), w=1920, h=1080, settle=400, locale="en-US", query="?lang=en")
    p.wait(300)
    xs = p.js("() => [...document.querySelectorAll('.rail .card.conn:not(.engine) .fact:nth-child(even) dd')].map((d) => Math.round(d.getBoundingClientRect().left))")
    check("the capture card's second values at one place in English, where a wider name moved one 4 px", len(xs) >= 2 and len(set(xs)) == 1, xs)
    p.close()


# The top layers clear of every box's edge (the user: a notice at the top and the gear menu must not lie over other boxes'
# and panels' edges). Every visible box that straddles the layer's edge, part of it under the layer and part out, is an edge
# crossing it; a box round the layer (the bar round a notice in it) or wholly under it is none. What passes under the header
# (the bar, and the bands' strip stuck to its foot over the thread's column) is the page under the header, as under any bar:
# only the part of a box below the header counts, and a band past the strip's own scroll is cut by the strip
TOP_CROSS = r"""
(sel) => {
  const f = document.querySelector(sel); if (!f) return null;
  const vw = innerWidth, vh = innerHeight;
  const clip = (b) => ({ l: Math.max(0, b.left), t: Math.max(0, b.top), r: Math.min(vw, b.right), b: Math.min(vh, b.bottom) });
  const a = clip(f.getBoundingClientRect());
  const bar = document.querySelector('header.bar'), barR = bar.getBoundingClientRect();
  const al = document.getElementById('alerts'), alR = al.getBoundingClientRect();
  const stuck = al.children.length && !document.documentElement.classList.contains('bands-in-bar') && alR.top <= barR.bottom + 1 ? alR : null;
  const alpha = (c) => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return c === 'transparent' ? 0 : 1; const p = m[1].split(/[ ,/]+/).filter(Boolean); return p.length > 3 ? parseFloat(p[3]) : 1; };
  const name = (el) => el.id ? '#' + el.id : el.tagName.toLowerCase() + '.' + String(typeof el.className === 'string' ? el.className : '').trim().split(/\s+/).slice(0, 2).join('.');
  const out = [];
  for (const el of document.querySelectorAll('body *')) {
    if (f.contains(el) || el.contains(f)) continue;
    if (!el.checkVisibility({ opacityProperty: true, visibilityProperty: true })) continue;
    const cs = getComputedStyle(el);
    const line = ['Top', 'Right', 'Bottom', 'Left'].some((s) => parseFloat(cs['border' + s + 'Width']) > 0 && cs['border' + s + 'Style'] !== 'none' && alpha(cs['border' + s + 'Color']) > 0.03);
    if (!line && !(alpha(cs.backgroundColor) > 0.05) && cs.backgroundImage === 'none' && cs.boxShadow === 'none') continue;   // draws no edge
    const r0 = el.getBoundingClientRect();
    if (r0.width < 3 || r0.height < 3) continue;
    const b = clip(r0);
    if (!bar.contains(el) && !al.contains(el)) {
      b.t = Math.max(b.t, barR.bottom);
      if (stuck && b.l >= stuck.left - 1 && b.r <= stuck.right + 1) b.t = Math.max(b.t, stuck.bottom);
    } else if (al.contains(el) && el !== al) { b.t = Math.max(b.t, alR.top); b.b = Math.min(b.b, alR.bottom); }
    const ov = Math.min(a.r, b.r) - Math.max(a.l, b.l), oh = Math.min(a.b, b.b) - Math.max(a.t, b.t);
    if (ov <= 1 || oh <= 1) continue;                                   // apart, or edge on edge
    const inside = b.l >= a.l - 1 && b.r <= a.r + 1 && b.t >= a.t - 1 && b.b <= a.b + 1;
    const around = b.l <= a.l + 1 && b.r >= a.r - 1 && b.t <= a.t + 1 && b.b >= a.b - 1;
    if (!inside && !around) out.push(name(el) + ' [' + [b.l, b.t, b.r, b.b].map(Math.round).join(',') + ']');
  }
  return out;
}
"""


def group_top_layers(br, s):
    if not T.group("the notice, the bands and the gear menu over no box's edge"):
        return
    p = Page(br, s, many(30), w=1600, h=900, settle=400)
    crossed, cut, sheet, inbar = [], [], [], []
    for bands in ("none", "two"):
        status(p, eng() if bands == "none" else eng(local={"ok": False}, agent={"ok": False}))
        p.wait(300)
        for w in (1600, 1100, 900, 760, 480, 400):
            p.page.set_viewport_size({"width": w, "height": 900})
            for y in (0, 700):
                p.js("(y) => { stick = false; window.scrollTo(0, y); placeBands(); }", y)
                p.wait(250)
                at = f"{w} px, {bands} bands, scrolled {y}"
                # a short notice, and a long one with a key to press
                for long in (False, True):
                    p.js("() => toast('Deleted · in Recently deleted for 30 days', () => {}, 'done', '', 'Undo')" if long else "() => toast('Restored', null, 'done')")
                    p.wait(450)
                    crossed += [f"notice, {at}: {x}" for x in p.js(TOP_CROSS, "#toast")]
                    got = p.js("""() => { const t = document.getElementById('toast').getBoundingClientRect(), b = document.querySelector('header.bar').getBoundingClientRect(),
                        m = document.querySelector('#toast .msg'); return [t.top >= b.top && t.bottom <= b.bottom && t.left >= 0 && t.right <= innerWidth, m.scrollWidth > m.clientWidth + 1]; }""")
                    if not got[0]:
                        inbar.append(at)
                    if got[1] and w >= 480:
                        cut.append(at)
                    p.js("() => { clearTimeout(toast.timer); $('toast').classList.remove('show'); }")
                    p.wait(260)
                p.js("() => toggleMenu(true)")
                p.wait(350)
                crossed += [f"menu, {at}: {x}" for x in p.js(TOP_CROSS, "#menu")]
                m = p.js("""() => { const r = document.getElementById('menu').getBoundingClientRect(), b = document.querySelector('header.bar').getBoundingClientRect();
                    return Math.abs(r.top - b.bottom) <= 1 && Math.abs(r.bottom - innerHeight) <= 1; }""")
                if not m:
                    sheet.append(at)
                p.js("() => toggleMenu(false)")
                p.wait(200)
    check("a notice stands in the bar, at every width, scroll and band", not inbar, inbar[:4])
    check("...its words on one line at 480 px and wider", not cut, cut[:4])
    check("the gear menu is a sheet from the bar's foot to the window's", not sheet, sheet[:4])
    check("no box's edge crosses a notice or the gear menu: 6 widths, at the top and scrolled, with no band and with two",
          not crossed, crossed[:6])
    p.close()


def main() -> int:
    support.need_vendor(h.PANEL)
    s = Stand("layout")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        for group in (group_audit, group_asked, group_named, group_found, group_controls, group_top_layers, group_star, group_recheck, group_motion, group_rail, group_answers, group_overlays, group_release, group_column_kept):
            group(br, s)
        br.close()
    if os.environ.get("AUDIT_REPORT"):
        Path(os.environ["AUDIT_REPORT"]).write_text(json.dumps(FOUND, ensure_ascii=False, indent=0), encoding="utf-8")
    return T.end()


if __name__ == "__main__":
    sys.exit(main())
