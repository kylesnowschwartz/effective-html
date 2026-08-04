/* Measure every rendered text node against the surface it actually lands on.
 *
 * check-house-style.py resolves ancestry from selector text, so it sees
 * `.invert .eyebrow` and misses `.decision-context` — a rule that only ever
 * matches inside an inverted band but never names it. That gap is not fixable by
 * reading CSS: it needs the document tree. This walks the rendered tree instead,
 * so a tint painted inside an always-dark panel and a page text tier inside an
 * inverted band both show up as what they are.
 *
 * The static checker stays the fast gate. This is the ground truth.
 *
 * Usage — serve the references directory, then:
 *   python3 -m http.server 8931 -d skills/effective-html/references
 *   playwright-cli open
 *   playwright-cli run-code "$(cat tools/audit-rendered-contrast.js)"
 */
async page => {
  const FILES = ['architecture-example.html', 'scroll-explainer-example.html',
    ...['01-exploration-code-approaches', '02-exploration-visual-designs', '03-code-review-pr',
      '04-code-understanding', '05-design-system', '06-component-variants', '07-prototype-animation',
      '08-prototype-interaction', '09-slide-deck', '10-svg-illustrations', '11-status-report',
      '12-incident-report', '13-flowchart-diagram', '14-research-feature-explainer',
      '15-research-concept-explainer', '16-implementation-plan', '17-pr-writeup',
      '18-editor-triage-board', '19-editor-feature-flags', '20-editor-prompt-tuner', 'examples-index']
      .map(n => n + '.html')];
  const out = [];
  for (const file of FILES) {
    for (const theme of ['light', 'dark']) {
      await page.goto('http://localhost:8931/' + file);
      await page.evaluate(t => localStorage.setItem('theme', t), theme);
      await page.reload();
      await page.waitForTimeout(150);
      const hits = await page.evaluate(() => {
        const luminance = ([r, g, b]) => {
          const [x, y, z] = [r, g, b].map(v => v / 255)
            .map(v => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
          return 0.2126 * x + 0.7152 * y + 0.0722 * z;
        };
        const channels = s => { const m = s.match(/[\d.]+/g); return m ? m.slice(0, 3).map(Number) : null; };
        const opacity = s => { const m = s.match(/rgba?\([^)]*,\s*([\d.]+)\s*\)/); return m ? Number(m[1]) : 1; };
        const hex = c => '#' + c.map(v => Math.round(v).toString(16).padStart(2, '0')).join('');
        const ratio = (a, b) => {
          const [p, q] = [luminance(a), luminance(b)];
          return (Math.max(p, q) + 0.05) / (Math.min(p, q) + 0.05);
        };
        // A near-transparent wash reads as the surface below it, so keep walking. So
        // does an ancestor the text does not overlap at all: a 12px dot whose labels
        // are absolutely positioned above and below it paints neither of them.
        // Overlap rather than containment, because a long line inside a scrolling code
        // panel runs past the panel's right edge and is still on the panel.
        const overlaps = (host, box) => {
          const h = host.getBoundingClientRect();
          return box.left < h.right && box.right > h.left
            && box.top < h.bottom && box.bottom > h.top;
        };
        const surfaceOf = (el, box) => {
          for (let e = el; e; e = e.parentElement) {
            const bg = getComputedStyle(e).backgroundColor;
            if (opacity(bg) > 0.85 && (e === el || overlaps(e, box))) return [channels(bg), e];
          }
          return [[255, 255, 255], document.body];
        };
        const name = e => e.tagName.toLowerCase()
          + (String(e.className).trim() ? '.' + String(e.className).trim().split(/\s+/).join('.') : '');
        const found = [];
        for (const el of document.querySelectorAll('*')) {
          if (el.children.length || !(el.textContent || '').trim()) continue;
          const style = getComputedStyle(el);
          if (style.visibility === 'hidden' || Number(style.opacity) < 0.5) continue;
          const box = el.getBoundingClientRect();
          if (!box.width || !box.height) continue;
          if (opacity(style.color) < 0.85) continue;
          const ink = channels(style.color);
          if (!ink) continue;
          const px = parseFloat(style.fontSize);
          const floor = px >= 24 || (px >= 18.66 && Number(style.fontWeight) >= 700) ? 3 : 4.5;
          const [surface, host] = surfaceOf(el, box);
          const measured = ratio(ink, surface);
          if (measured >= floor) continue;
          found.push(`${name(el)} ${hex(ink)} on ${name(host)} ${hex(surface)} `
            + `${measured.toFixed(2)}:1 (floor ${floor})`);
        }
        return [...new Set(found)];
      });
      if (hits.length) out.push(`${file} [${theme}]\n  ` + hits.join('\n  '));
    }
  }
  return out.length ? out.join('\n') : 'clean: every rendered text node clears its floor';
}
