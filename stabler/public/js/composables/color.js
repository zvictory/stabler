/**
 * Colour arithmetic for values a user stored.
 *
 * The contract board's stage colour is a plain `Data` field (Stabler SO Stage),
 * so it can hold a six-digit hex, a shorthand, an eight-digit one with an alpha,
 * a CSS colour name, or nothing at all. The board used to build its badge by
 * string concatenation — `colorOf(s) + '22'` — which produces a valid colour for
 * exactly one of those shapes and silently produces nonsense for the rest.
 *
 * It also printed the count in the stage's own colour on a 13 % tint of that
 * same colour. Measured 2026-09-02: NOT ONE of the seven seeded stage colours
 * clears WCAG AA (4.5:1) that way — the best is `#4263eb` at 4.18, and `#adb5bd`
 * is 1.91. So `stageTone` darkens until it passes rather than choosing between
 * the colour and a fixed ink: scaling all three channels by one factor keeps the
 * ratios between them exact, so the hue survives and orange stays orange.
 *
 * Here rather than in the component for the reason money.js already states about
 * money rules: a rule about how to render user data is not one screen's private
 * business. Nothing else uses it yet.
 */

/** The fallback for a value that is not a colour. Also the *New* stage's own
 *  colour — see prompt 18's S3, which wants that collision fixed separately. */
const NEUTRAL = [108, 117, 125]; // #6c757d
const TINT_ALPHA = 0.13;
const BORDER_ALPHA = 0.33;
/** WCAG AA for normal text. A badge count is small text, so 4.5 and not 3. */
const MIN_CONTRAST = 4.5;
/** One step of darkening. Small enough that a colour is never over-darkened by
 *  much, large enough that the worst case (white) converges in single digits. */
const STEP = 0.9;
const MAX_STEPS = 20;

/** `[r, g, b]` from `#rgb`, `#rrggbb` or `#rrggbbaa`, else `null`. */
export function parseColor(value) {
	const hex = String(value ?? "").trim();
	if (!/^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(hex)) return null;
	const body = hex.slice(1);
	const pairs =
		body.length === 3 ? [...body].map((c) => c + c) : [body.slice(0, 2), body.slice(2, 4), body.slice(4, 6)];
	return pairs.map((p) => parseInt(p, 16));
}

/** WCAG relative luminance of an `[r, g, b]` triple. */
export function relativeLuminance([r, g, b]) {
	const lin = (c) => {
		const v = c / 255;
		return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
	};
	return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

/** WCAG contrast ratio between two `[r, g, b]` triples, 1 … 21. */
export function contrastRatio(a, b) {
	const la = relativeLuminance(a);
	const lb = relativeLuminance(b);
	const [hi, lo] = la > lb ? [la, lb] : [lb, la];
	return (hi + 0.05) / (lo + 0.05);
}

/** `rgb` composited at `alpha` over the card, which is white in this app. */
export function tintOver(rgb, alpha) {
	return rgb.map((c) => c * alpha + 255 * (1 - alpha));
}

const css = (rgb, alpha) => {
	const [r, g, b] = rgb.map(Math.round);
	return alpha === undefined ? `rgb(${r}, ${g}, ${b})` : `rgba(${r}, ${g}, ${b}, ${alpha})`;
};

/**
 * The four colours a stage column needs, safe for any stored value.
 *
 * `line` is the card's top border, `tint` the count badge's background,
 * `border` its outline, and `text` the count itself — darkened only as far as
 * it has to be to stay readable on `tint`.
 */
export function stageTone(value) {
	const rgb = parseColor(value) || NEUTRAL;
	const background = tintOver(rgb, TINT_ALPHA);
	let text = rgb;
	for (let i = 0; i < MAX_STEPS && contrastRatio(text, background) < MIN_CONTRAST; i++) {
		text = text.map((c) => c * STEP);
	}
	return {
		line: css(rgb),
		tint: css(rgb, TINT_ALPHA),
		border: css(rgb, BORDER_ALPHA),
		text: css(text),
	};
}
