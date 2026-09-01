import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "fs";
import { dirname, join, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const components = resolve(here, "../components");

/**
 * A field's error state has to land on the control the user is typing in.
 *
 * The design layer styles it that way — `.stbl-ds .form-control[aria-invalid="true"]`
 * — and the frontend mandate makes both of these components compulsory: money only
 * through `MoneyInput`, dates only through `DateInput`. So an `aria-invalid` a caller
 * passes must reach the `<input>` carrying `.form-control`.
 *
 * It did not. Measured 2026-09-01: neither component declared `inheritAttrs`, and both
 * render a wrapper `<div class="input-group">` as their root — in `DateInput` always, in
 * `MoneyInput` on every branch that shows a currency. Vue's fallthrough put
 * `aria-invalid` on that wrapper, where the selector never matches. The rule was dead in
 * exactly the screens that carry money: the comparison table and the quotation form.
 *
 * The two components are fixed differently, and that is deliberate — the call sites
 * differ and were counted:
 *
 *   MoneyInput  135 uses, 5 pass an attribute, all of them `class` aimed at the control
 *               (`is-invalid`, `form-control-sm`, `ds-input so-rate`). Everything goes
 *               to the input. This also removes a real inconsistency: the same `class`
 *               used to land on the input or on the wrapper depending on the currency.
 *
 *   DateInput   202 uses, 28 pass `style`, every one of them a width sizing the GROUP
 *               (`width: 120px`). Moving those to the input would let the group grow
 *               past the width its caller asked for, so `class` and `style` stay on the
 *               wrapper and everything else — `aria-invalid`, `aria-describedby`,
 *               `data-*` — goes to the input.
 *
 * This spec reads source rather than mounting, because the repo has no DOM test
 * environment: `vitest.config.mjs` sets `environment: "node"` on purpose, and
 * `@vue/test-utils` is not a dependency. Whether that changes is Zafar's call
 * (Phase A, section 10.9) — until it does, the structural contract is what can be pinned.
 */
const CONTRACT = [
	{
		file: "MoneyInput.vue",
		// Both branches: the bare input and the one inside .input-group.
		inputsThatMustReceiveAttrs: 2,
		wrapperKeepsClassAndStyle: false,
	},
	{
		file: "DateInput.vue",
		inputsThatMustReceiveAttrs: 1,
		wrapperKeepsClassAndStyle: true,
	},
];

const read = (file) => readFileSync(join(components, file), "utf8");

/** `<input …>` elements, template only — the script block never contains one. */
const inputTags = (src) => src.slice(src.indexOf("<template>")).match(/<input\b[\s\S]*?\/>/g) ?? [];

describe("a field error reaches the control, not its wrapper", () => {
	for (const { file, inputsThatMustReceiveAttrs, wrapperKeepsClassAndStyle } of CONTRACT) {
		describe(file, () => {
			it("turns off automatic fallthrough, so attributes stop landing on the root div", () => {
				expect(read(file)).toMatch(/defineOptions\(\{\s*inheritAttrs:\s*false/);
			});

			it("binds the caller's attributes onto every <input> it renders", () => {
				const bound = inputTags(read(file)).filter((tag) => /v-bind=/.test(tag));
				expect(bound.length).toBe(inputsThatMustReceiveAttrs);
			});

			// Stated positively on purpose. Asserting the ABSENCE of the other
			// component's shape passes today, before anything is written — the
			// do-nothing criterion this repo has been bitten by twice already.
			it(
				wrapperKeepsClassAndStyle
					? "keeps class and style on the wrapper, because callers size the group"
					: "sends class through to the control like every other attribute",
				() => {
					const src = read(file);
					if (wrapperKeepsClassAndStyle) {
						expect(src).toMatch(/:style="\$attrs\.style"/);
						expect(src).toMatch(/:class="\[[^\]]*\$attrs\.class/);
					} else {
						expect(inputTags(src).every((tag) => /v-bind="\$attrs"/.test(tag))).toBe(true);
					}
				},
			);
		});
	}

	// The other half of the same contract. Once a class reaches the control, a class
	// that was shaping the GROUP starts shaping the control instead — and one call
	// site was doing exactly that. Measured in Chrome against Tabler 1.0.0-beta20
	// (the version `www/stabler.html:1` pins), NewDirectInvoiceModal.vue:340:
	//
	//   wrapper carries rounded-3  ->  input border-radius  0px / 2px   (flush)
	//   input   carries rounded-3  ->  input border-radius  8px / 8px   (seam)
	//
	// The group has no overflow clip, so `rounded-3` on the wrapper was painted over
	// by its children and did nothing. On the control it rounds the corner that meets
	// the currency badge and opens a visible gap. Rendering with the class removed is
	// pixel-identical to what shipped before, which is why removing it was the fix.
	it("is never handed a rounded-* utility, which would open a seam at the currency badge", () => {
		const offenders = [];
		const walk = (dir) => {
			for (const entry of readdirSync(dir, { withFileTypes: true })) {
				const full = join(dir, entry.name);
				if (entry.isDirectory()) {
					walk(full);
					continue;
				}
				if (!entry.name.endsWith(".vue")) continue;
				const src = readFileSync(full, "utf8");
				for (const tag of src.match(/<MoneyInput\b[\s\S]*?\/>/g) ?? []) {
					if (/:?class="[^"]*\brounded-/.test(tag)) offenders.push(entry.name);
				}
			}
		};
		walk(resolve(here, ".."));
		expect(offenders).toEqual([]);
	});

	it("never forwards style onto a control whose callers size the wrapper", () => {
		// The failure this guards: someone simplifies DateInput to a plain
		// `v-bind="$attrs"` and 28 call sites silently lose their width.
		const src = read("DateInput.vue");
		const inputs = inputTags(src);
		expect(inputs.length).toBeGreaterThan(0);
		for (const tag of inputs) {
			expect(tag).not.toMatch(/v-bind="\$attrs"/);
		}
	});
});
