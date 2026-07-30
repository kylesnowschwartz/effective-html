---
name: effective-html
description: Create elegant, self-contained HTML artifacts in the effective-HTML style. This skill should be used whenever the user wants something delivered as a single HTML file — a general artifact (report, explainer, comparison, slide deck, prototype), a full-screen architecture/system diagram (low-prose, high-quality interactive SVG), a scroll-driven explainer where scrolling advances a sticky chart or diagram, or a pragmatic plan page. Routes the request to the matching mode and follows the bundled reference examples for style, density, and tone.
---

# Effective HTML

One entry point for producing self-contained HTML artifacts in the effective-HTML style. This file is a router: pick the mode that matches the request, follow its notes, and apply the shared requirement below to every mode.

## Read first

Review the example files throughout [`references/html-effectiveness/`](references/html-effectiveness/). Match their alignment — style, density, and tone — as closely as the request allows. Every mode below assumes these examples are in mind.

## Mode routing

| The user wants… | Mode | Mode-specific guidance |
|---|---|---|
| A general artifact — report, explainer, comparison, slide deck, prototype, or anything else best delivered as one HTML file — with prose and visuals both sitting still on the page | **Artifact** | Build the HTML for whatever is being described, leaning on the references to match style, density, and tone. |
| A full-screen architecture or system diagram, light on prose, that makes the stack click fast | **Diagram** | Build a high-quality SVG and iterate on the diagram more than anything else. Keep prose minimal — simplify toward a full-screen diagram. Where it helps, make the diagram interactive and animate different sequences of system behavior. Also review [`references/architecture-example.html`](references/architecture-example.html) — a finished example (full-screen SVG stage, clickable nodes, flow chips that light up and animate request paths). Style the SVG through CSS classes that use the theme variables — never hard-coded hex inside the SVG — so the diagram follows the theme. **No floating card should trap diagram content behind it.** Two patterns, both in the example: a persistent inspection card (`#detail`) defaults to a collapsed pill and expands only on demand (clicking a node), with one control to collapse back; a transient caption (`#flowcap`) appears only while its flow is active and carries a dismiss control, since a flow can light the very node the caption sits over. Prefer these over draggable/resizable cards, which cede the composition and add touch/JS cost. **A diagram worth drawing usually outgrows the viewport, so support pan and zoom.** Wrap every SVG child in one `<g id="svg-content">` and drive its `transform`. Pan in SVG units 1:1 with the mouse delta — dividing the delta by the zoom scale is the tempting mistake, and it makes dragging feel sluggish exactly when the reader is zoomed in and needs it most. Zoom on the wheel about the cursor: translate so the SVG point under the pointer stays put. A drag must not fire the node it ends on, so track movement against a ~5px threshold and cancel the pending `click` with a one-shot capture-phase listener. Show the reader the affordance: `grab`/`grabbing` cursors, the current zoom level, and a reset-to-100% control. |
| A page where scrolling drives the explanation — each step brings a chart or diagram to a new state, rather than prose sitting beside a fixed visual | **Scroll explainer** | Sticky visual pane, steps scrolling beside it. Open with a short hero that says scrolling is the interface — a title, a sentence of setup, and a "scroll to begin" cue — and put a read-progress rail on the bottom edge of the top bar, since a reader who cannot see how much story is left will not commit to it. Make each step a fixed scroll slot (`min-height: 78vh` with its card flex-centered) rather than spacing cards with margins: every step then gets the same travel and the progress rail advances evenly. Drive step changes with an `IntersectionObserver` (`rootMargin` around `-45% 0px -45% 0px`), never a scroll handler — but observe the **card**, not the slot around it, or the band fires while the card is still off-screen. A continuous scroll fraction is the one thing a scroll handler does better: read `scrollTop / (scrollHeight - clientHeight)` inside `requestAnimationFrame` on a passive listener for the progress rail, or for any value that should count up as the reader scrolls rather than snap at a step. Keep **one state object and one `render(state)`**: the active step and every slider/toggle write to the same state, so the chart, the numbers, the legend, and the plain-English explanation can never disagree. Derive a rule's effect from the step index so the visual never shows a state the reader has not reached. Add sliders or toggles for any threshold or assumption that is a judgement call, and label the live value next to the control. Chart marks get their fill and stroke from theme variables — never hard-coded hex inside the SVG. Fix the y-scale so it does not jump between steps. **Build the chart once and then update it in place** — set attributes on nodes you kept references to, rather than rewriting the container's `innerHTML` on every render. Rewriting is easier to write and throws away every transition, so marks jump between steps instead of growing into the new state; with persistent nodes a CSS transition on the geometry (`y`, `height`, `transform`) does the animation for free. Give a step change a slow eased transition and a slider drag a short linear one, so the chart glides between steps but still tracks the thumb. Set `scroll-behavior: smooth` on `html`. Honour `prefers-reduced-motion` by returning that to `auto` and dropping the transitions, the translate and any looping animation — but not the active-step highlight; reveals become instant, nothing moves. Keep the step prose readable when JavaScript does not run: gate the dimmed state behind a `js` class on `<html>`, and use `<noscript>` to say plainly what the reader is missing. Stacking on a narrow viewport needs its own handling — a sticky pane taller than the screen lets the steps scroll over it, so bound the pane's height, raise it above the steps, and move the activation band down to where a step card is actually legible. For a longer story with several independent scrolly sections, factor activation into one `makeScrolly(selector, onActive)` helper and call it per section rather than writing an observer each time. Also review [`references/scroll-explainer-example.html`](references/scroll-explainer-example.html) — a finished example (hero with scroll cue, progress rail, sticky stacked-bar chart animated in place, five scroll steps, two sliders and a toggle, live readout, data table). |
| A plan page that stays pragmatic and close to what they gave you | **Plan** | Keep it pragmatic and simple. Keep the writing close to the user's input; clean up the grammar without turning it into something bigger. |

When a request spans modes, pick the dominant one and borrow from the others as needed.

## The house style

[`references/house-style-tokens.css`](references/house-style-tokens.css) **is the authority for every value.** Inline it verbatim as the first thing in the document's `<style>`, and do not retype, round, or re-derive anything in it. Reach a colour through a role token — the job it does — never through a pigment name and never as a literal. The reference files were migrated onto this block; where one of them disagrees with it, the block wins.

The rules below are the ones a visual scan of the examples cannot teach, because they are about what must be true rather than what things look like.

**Colour.**

- **Status hues and series hues never appear as marks in the same figure.** Measured, not advisory: the combined eight-colour set separates by ΔE 5.0 under colourblind simulation and 5.9 in normal vision, both hard failures. One figure is either showing categories or showing states.
- **Status colour always ships with an icon, an arrow, or a label.** Colour alone carries no meaning for a reader who cannot separate the hues, and the three status hues are re-steps of three of the five series hues.
- **Series hues are assigned in fixed order — `--s1` through `--s5` — and never cycled.** A sixth series folds into "Other", becomes small multiples, or gets a second encoding.
- **Text on a status tint is `--body`, never the status colour.** The tints are solved so body text clears AA on them; the role colour stays on the border and the icon.
- **No hex inside any SVG, in any mode.** Style marks through CSS classes that read theme variables, so the drawing follows the theme. `var()` resolves in SVG presentation attributes and tracks dark mode, so `fill="var(--s1)"` is also fine.
- **`@media print` re-declares every light role token, including under `html.dark`.** `prefers-color-scheme` is not suppressed for print, so without this block a reader in OS dark mode exports a near-black page.

**Type.**

- **Weights are exactly `400` and `700`.** No other value. Georgia, Menlo, Consolas, DejaVu and Liberation each ship two weights and Segoe UI has no 500 face, so `500` renders as `400` and `600` jumps to full bold. Get emphasis from family or size, not from an intermediate weight.
- **Never set figures in the serif face.** System Georgia's default figures are oldstyle and carry no `tnum` or `lnum` feature table, so a column of numbers drifts up to 39% in width and no CSS corrects it. Numbers that must align go in `--font-data` with `font-variant-numeric: tabular-nums`.
- **16px is the prose floor.** 13px is for glanced UI text, metadata, table cells and chart labels; 11px is for a single glanced token. Prose caps at `--w-measure`, which is narrower than the column so tables, charts and code can still use the full width.
- **The serif / sans / mono split is a determinism device, not a legibility one.** The serif-versus-sans legibility literature is a consistent null; family switching is what renders reliably across platforms where weight switching does not. Do not collapse the three stacks into one.

**Layout.**

- **Size badges, chips and table cells with padding and line-height, never a fixed `height`.** A fixed height is the likeliest way to break text-spacing conformance when a reader's own styles apply.
- **Long inline runs need three rules, not one:** `code, td, th { overflow-wrap: anywhere }`, `pre { white-space: pre-wrap; overflow-wrap: anywhere }`, and a `.scroll-x { overflow-x: auto }` wrapper around wide tables.
- **Card grids use `repeat(auto-fit, minmax(min(100%, var(--w-rail)), 1fr))`.** `auto-fill` leaves empty trailing tracks; a bare `minmax` overflows below the floor.
- **Every interactive target is at least 24×24 CSS px.** A labelled checkbox's target is the label, so wrap the input in one; a slider's target is the thumb, not the track.

### The breaking permission

The layout system is closed. Every width comes from the width set, every gap and pad from the spacing set, every radius from the radius set. You may leave the system in exactly four ways, and only these: `.overhang` (a figure extends into one margin — the widest thing a document may do), `.bleed` (a band cancels the page padding to span the shell's outer box, never the viewport), `.stage` (a viewport-sized interactive canvas), `.off-scale` (a single value outside the scale). Budget per document: at most two `.overhang`, two `.bleed`, one `.stage`, one `.off-scale`. Plan mode gets zero of all four. Every break carries an HTML comment on the line above naming which break it is and why this element needs it. If you cannot write that reason, you do not have a break, you have a mistake.

`.bleed` is already defined in the token block, and its definition is load-bearing: neither `width: 100vw` nor `width: 100%` works, because inside a split track both resolve to the wrong box and `100vw` ignores the scrollbar. Use it as shipped. The other three breaks are yours to write, since each one is specific to the element that needs it.

## Always (every mode)

Include dark mode: the token block's `:root` / `html.dark` blocks, a small theme toggle button, `localStorage` persistence, and an apply-before-paint script in `<head>` (default to `prefers-color-scheme`).

Ship one self-contained file: inline the CSS, the JavaScript, and any data or artwork. If an asset genuinely cannot be inlined, keep the hand-off to that asset plus the HTML — never a build step or a server.

When the user supplies data — slides, a spreadsheet, an export — every figure on the page comes from it. Do not invent values or round them into something tidier. If a number the design needs is missing, say so on the page instead of filling the gap.
