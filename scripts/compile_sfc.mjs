// Compile every Vue single-file component.
//
// `make compile` runs `python -m compileall`, so until 2026-08-27 nothing in the
// push gate ever compiled a .vue file: an unbalanced tag or a template that
// referenced a binding nobody defined passed lint, passed the source-scraping
// specs, and shipped. This closes that door.
//
// Two checks per file:
//   1. the SFC parses and its template compiles;
//   2. every identifier the template uses resolves to a <script setup> binding.
//      Vue silently falls back to `_ctx.foo` for unknown names, so a rename that
//      misses one call site is invisible at build time and blank at runtime.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { parse, compileScript, compileTemplate } from "@vue/compiler-sfc";

const ROOT = "stabler/public/js";

function* vueFiles(dir) {
	for (const entry of readdirSync(dir)) {
		const path = join(dir, entry);
		if (statSync(path).isDirectory()) yield* vueFiles(path);
		else if (entry.endsWith(".vue")) yield path;
	}
}

let failed = 0;
let checked = 0;

for (const file of vueFiles(ROOT)) {
	checked += 1;
	const source = readFileSync(file, "utf8");
	const { descriptor, errors } = parse(source, { filename: file });
	if (errors.length) {
		console.error(`${file}: ${errors.map((e) => e.message).join("; ")}`);
		failed += 1;
		continue;
	}
	if (!descriptor.template) continue;

	const template = compileTemplate({
		source: descriptor.template.content,
		filename: file,
		id: file,
	});
	if (template.errors.length) {
		console.error(`${file}: ${template.errors.map(String).join("; ")}`);
		failed += 1;
		continue;
	}

	if (!descriptor.scriptSetup) continue;
	let compiled;
	try {
		compiled = compileScript(descriptor, { id: file, inlineTemplate: true });
	} catch (err) {
		console.error(`${file}: ${err.message}`);
		failed += 1;
		continue;
	}
	// `_ctx.$slots` / `$attrs` and friends are Vue's own instance properties, not
	// missing bindings.
	const unresolved = [
		...new Set(compiled.content.match(/_ctx\.[A-Za-z_][A-Za-z0-9_$]*/g) || []),
	].map((s) => s.slice(5));
	if (unresolved.length) {
		console.error(`${file}: template uses undefined binding(s): ${unresolved.join(", ")}`);
		failed += 1;
	}
}

console.log(`sfc: ${checked} component(s) compiled, ${failed} failed.`);
process.exit(failed ? 1 : 0);
