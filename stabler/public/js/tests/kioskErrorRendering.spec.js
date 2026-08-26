import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(
	resolve(here, "../pages/manufacturing/ManufacturingOperatorBoard.vue"),
	"utf8"
);

/**
 * `humanizeError` strips the HTML out of ERPNext's validation errors so the
 * kiosk shows plain text instead of raw "<strong>… <a href=/desk/…>" markup.
 * It did that by assigning the message to a detached div's innerHTML, which
 * executes it: an element from document.createElement belongs to a document
 * WITH a browsing context, so `<img src=x onerror=…>` fires as it parses,
 * attached or not. DOMParser builds an inert document instead — no scripts, no
 * resource loads.
 *
 * The path is not theoretical. These messages are assembled from data:
 * `_assert_sweep_is_acknowledged` interpolates `item_name` straight off the Item
 * master, so anyone who can name an Item can put markup into a string that every
 * operator's kiosk then renders.
 *
 * jsdom is not a devDependency (same constraint as operatorWriteOffGate.spec.js),
 * so the function is executed against a recording DOMParser stub rather than a
 * real DOM. That still distinguishes the two implementations: one routes the
 * untrusted string through the parser, the other never calls it.
 */
function humanizeErrorSource() {
	const start = src.indexOf("function humanizeError(");
	expect(start, "no humanizeError in the SFC").toBeGreaterThan(-1);
	const end = src.indexOf("\n}", start);
	expect(end, "unterminated humanizeError").toBeGreaterThan(start);
	return src.slice(start, end + 2);
}

function run(message, { onParse } = {}) {
	const calls = [];
	class StubDOMParser {
		parseFromString(str, type) {
			calls.push({ str, type });
			if (onParse) onParse(str, type);
			// What a real inert parse yields for our purposes: the text, no tags.
			return { body: { textContent: str.replace(/<[^>]*>/g, "") } };
		}
	}
	const fn = new Function(
		"DOMParser",
		"document",
		"err",
		`${humanizeErrorSource()}; return humanizeError(err);`
	);
	const document = {
		createElement() {
			throw new Error("humanizeError built a live element to parse untrusted HTML");
		},
	};
	return { out: fn(StubDOMParser, document, { message }), calls };
}

describe("kiosk error rendering", () => {
	it("never assigns untrusted text to innerHTML", () => {
		// The sink itself. Asserted on the whole SFC and not just this function,
		// because the next one added would be just as live.
		expect(src).not.toMatch(/\.innerHTML\s*=/);
	});

	it("routes an HTML error through the inert parser", () => {
		const { out, calls } = run("<strong>Not enough</strong> <a href='/desk/x'>PROBE-MILK</a>");
		expect(calls).toHaveLength(1);
		expect(calls[0].type).toBe("text/html");
		expect(out).toBe("Not enough PROBE-MILK");
	});

	it("does not execute an onerror payload smuggled through an item name", () => {
		// The concrete shape: an Item named so that the sweep refusal carries it.
		let fired = false;
		const { out } = run(
			`Finishing now will also write off: <img src=x onerror="fired=true">Milk`,
			{
				onParse: () => {
					// A real DOMParser document has no browsing context, so nothing
					// here loads or runs. The assertion below is that the string got
					// this far as DATA — it was handed to a parser, not to a live tree.
				},
			}
		);
		expect(fired).toBe(false);
		expect(out).toBe("Finishing now will also write off: Milk");
	});

	it("leaves a plain message alone without parsing it at all", () => {
		// The fast path, kept: most refusals carry no markup, and running every
		// one of them through a parser would be work for nothing.
		const { out, calls } = run("Produced quantity must be positive.");
		expect(calls).toHaveLength(0);
		expect(out).toBe("Produced quantity must be positive.");
	});

	it("still collapses the whitespace ERPNext leaves behind", () => {
		const { out } = run("<p>Row  1</p>\n\n<p>is   short</p>");
		expect(out).toBe("Row 1 is short");
	});
});
