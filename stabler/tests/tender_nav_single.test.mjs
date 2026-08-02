// Source contract: the tender module bar is drawn exactly ONCE on every tender
// screen, and it is drawn ABOVE that screen's own heading.
//
// Both halves are regressions we actually shipped (measured 2026-08-02, Mikas):
//   * `#/dashboard` rendered `<TenderNav>` and then embedded `<OperationsDesk>`,
//     which carries its own bar — two identical bars stacked on one screen.
//   * MyTenders / DeclarantQueue / LogistBoard put the bar UNDER their `<h2>`,
//     so the menu jumped down a row as you moved between tender screens.
//
// The count is transitive on purpose: a page that embeds another page component
// inherits that component's bar, which is exactly how the double layer got in.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const jsDir = resolve(here, "../public/js");

const read = (file) => readFileSync(file, "utf8");

// HTML comments are stripped first — this very fix left a comment quoting
// `<TenderNav overview />`, and a naive count would read it as a second bar.
function templateOf(file) {
	const src = read(file);
	const start = src.indexOf("<template>");
	if (start === -1) return "";
	return src.slice(start).replace(/<!--[\s\S]*?-->/g, "");
}

function vueImportsOf(file) {
	const out = new Map();
	const re = /import\s+(\w+)\s+from\s+["'](\.[^"']+\.vue)["']/g;
	const src = read(file);
	let m;
	while ((m = re.exec(src))) out.set(m[1], resolve(dirname(file), m[2]));
	return out;
}

function navCount(file, seen = new Set()) {
	if (seen.has(file)) return 0; // cycles can't add bars
	seen.add(file);
	const tpl = templateOf(file);
	let count = (tpl.match(/<TenderNav[\s/>]/g) || []).length;
	for (const [tag, path] of vueImportsOf(file)) {
		if (tag === "TenderNav") continue;
		const used = new RegExp(`<${tag}[\\s/>]`).test(tpl);
		if (used) count += navCount(path, seen);
	}
	return count;
}

// The routes the user actually walks: every `module: "tender"` route with a
// component, read out of the router so a new tender screen joins this test the
// day it gets a route — plus /dashboard, the tender Overview entry in the bar.
function tenderRouteComponents() {
	const routerFile = resolve(jsDir, "router.js");
	const src = read(routerFile);
	const imports = vueImportsOf(routerFile);
	const out = new Map();
	const re = /component:\s*(\w+)[^}]*module:\s*"tender"/g;
	let m;
	while ((m = re.exec(src))) {
		const path = imports.get(m[1]);
		if (path) out.set(m[1], path);
	}
	return out;
}

const targets = tenderRouteComponents();
targets.set("Dashboard", resolve(jsDir, "pages/Dashboard.vue"));

assert.ok(targets.size >= 10, `expected the tender routes to be found, got ${targets.size}`);

for (const [name, file] of targets) {
	assert.equal(
		navCount(file),
		1,
		`${name} must draw the tender bar exactly once — 0 means the menu disappears on that screen, 2 means the double layer is back`,
	);

	const tpl = templateOf(file);
	const nav = tpl.search(/<TenderNav[\s/>]/);
	const heading = tpl.search(/<h[12][\s>]/);
	if (nav !== -1 && heading !== -1) {
		assert.ok(
			nav < heading,
			`${name} must put the tender bar above its own heading (see /tender/desk) — otherwise the menu shifts rows between screens`,
		);
	}
}

// Second half of the contract: a tender ROUTE builds its shell from <TenderPage>,
// it does not hand-roll one. Ten screens each wrote their own wrapper and the ten
// drifted — four on the design layer, six on Bootstrap `container-xl py-3`, and two
// of the four in a centred 1240px box with zero top padding, which pulled the bar
// 16px above the content area (measured 2026-08-02: /tender/flow and /tender/crm
// nav top = -16, /tender/desk = 0). Same bar, different place, every screen.
//
// Dashboard is exempt: it is the tender Overview entry, not a /tender/* screen, and
// it draws its bar through the embedded OperationsDesk.
for (const [name, file] of tenderRouteComponents()) {
	const root = templateOf(file).replace("<template>", "").trimStart();
	assert.ok(
		root.startsWith("<TenderPage"),
		`${name} must build its shell from <TenderPage> so every /tender/* screen has the same bar, header and padding — found: ${root.slice(0, 60)}`,
	);
}

// Third half: what a page puts in `#actions` goes in bare, not inside its own row
// container. The shell's `.ds-actions` already IS the row (flex + gap + 16px top).
// Two screens shipped a wrapper that re-declared it — `.desk-actions` and
// `.flow-controls`, both `margin-top: 16px` — so their action row sat 16px lower
// than the other eight (measured 2026-08-02: desk/flow actions top 217, crm 201).
// The bar was identical and the row underneath it still was not.
for (const [name, file] of tenderRouteComponents()) {
	const slot = templateOf(file).match(/#actions>\s*([\s\S]*?)<\/template>/);
	if (!slot) continue;
	assert.ok(
		!slot[1].trimStart().startsWith("<div"),
		`${name} must pass its actions to <TenderPage> bare — a wrapper <div> re-declares the row the shell already draws and pushes it out of line with the other screens`,
	);
}

console.log(`ok — tender bar drawn once, above the heading, on ${targets.size} screens`);
