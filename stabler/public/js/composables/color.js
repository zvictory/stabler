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

/**
 * A stage with no colour is rendered as HAVING no colour, not as a different one.
 *
 * The fallback used to be the literal `#6c757d` — which is also the *New* stage's
 * own colour, so an uncoloured stage was a second *New* (prompt 18's S3). The
 * obvious repair, another grey, was measured on 2026-09-02 and does not work: the
 * badge is a 13 % tint over white, and `#8b95a5`, `#9099a6`, `#c7ccd4` and
 * `#adb5bd` all land within 1.11:1 of *New*'s badge — 1.00 being identical. So
 * there is no grey that reads as "unset" beside *New*; only no fill does.
 *
 * CSS-wide keywords rather than house tokens. The first version read
 * `var(--ds-ln2)` / `var(--ds-tx2)`, which resolve for the contract board —
 * TenderPage wraps it in `.stbl-ds`, where the tokens are defined — but not for
 * the CRM kanban, which renders under App.vue's plain `.page`. `inherit` and
 * `transparent` need no token and no ancestor, and they say the same thing: this
 * column has no colour, so its count is simply text.
 */
const UNCOLOURED = Object.freeze({
	line: "transparent",
	tint: "transparent",
	border: "transparent",
	text: "inherit",
});

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
		body.length === 3
			? [...body].map((c) => c + c)
			: [body.slice(0, 2), body.slice(2, 4), body.slice(4, 6)];
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
	const rgb = parseColor(value);
	if (!rgb) return UNCOLOURED;
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

/**
 * ── Handing a new stage a colour ─────────────────────────────────────────────
 *
 * `so_stage_save` has always accepted a `color`; the board never sent one, so
 * every stage a manager created came out uncoloured. Giving it one is the half of
 * S3 that actually removes the collision — the fallback above only decides what
 * the rows that predate this change look like.
 *
 * The colour is GENERATED, not chosen from a list, because a list cannot clear
 * the bar the board already sets for itself. Measured 2026-09-02: nine of the ten
 * colours in the CRM's kanban palette sit within 18° of a seeded stage's hue
 * (`cyan` 4° from *Invoicing*, `gray` 0° from *New*), while the seeded seven are
 * 40° apart at their own tightest. Putting each new stage in the middle of the
 * widest unused arc clears 55° on a default board, and keeps working after
 * stages are deleted or recoloured — which a fixed list stops doing on the first
 * edit.
 *
 * It degrades honestly rather than failing: as the wheel fills the best available
 * gap shrinks (55°, 46°, 30°, 28° …), because on a board of fifteen stages there
 * is no set of fifteen distinguishable hues to hand out.
 */

/** Saturation and lightness of a generated colour: the median of the five
 *  chromatic seeded stages, so a new stage sits in the band the app shipped. */
const GEN_SATURATION = 0.81;
const GEN_LIGHTNESS = 0.48;
/** Below this a colour reads as grey, so it occupies no hue and fences off none.
 *  *New* (7 %) and *Closed* (11 %) are both under it, by design. */
const MIN_CHROMA = 0.15;
/** With nothing chromatic on the board every hue is equally distinct, so the
 *  first choice is arbitrary; the app's own accent (`--ds-acc`, #206bc4) is the
 *  least arbitrary one available. */
const FIRST_HUE = 213;

/** Hue in degrees, or `null` when the colour is too grey to have one. */
function hueOf(rgb) {
	const [r, g, b] = rgb.map((v) => v / 255);
	const mx = Math.max(r, g, b);
	const mn = Math.min(r, g, b);
	const chroma = mx - mn;
	if (!chroma) return null;
	const lightness = (mx + mn) / 2;
	if (chroma / (1 - Math.abs(2 * lightness - 1)) < MIN_CHROMA) return null;
	const h =
		mx === r
			? (g - b) / chroma + (g < b ? 6 : 0)
			: mx === g
				? (b - r) / chroma + 2
				: (r - g) / chroma + 4;
	return (h * 60 + 360) % 360;
}

/** `[r, g, b]` for an HSL triple — the inverse of the reading above. */
function fromHsl(h, s, l) {
	const c = (1 - Math.abs(2 * l - 1)) * s;
	const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
	const m = l - c / 2;
	const seg = [
		[c, x, 0],
		[x, c, 0],
		[0, c, x],
		[0, x, c],
		[x, 0, c],
		[c, 0, x],
	][Math.floor(h / 60) % 6];
	return seg.map((v) => Math.round((v + m) * 255));
}

/**
 * A six-digit hex for a new stage, as far in hue from `inUse` as the wheel allows.
 *
 * Hex and not `hsl(...)`: `parseColor` reads nothing else, so a stage stored in
 * any other notation would come back uncoloured — the exact state this exists to
 * prevent.
 */
export function nextStageColor(inUse) {
	const hues = (Array.isArray(inUse) ? inUse : [])
		.map((v) => parseColor(v))
		.filter(Boolean)
		.map(hueOf)
		.filter((h) => h !== null)
		.sort((a, b) => a - b);

	let hue = FIRST_HUE;
	let widest = 0;
	for (let i = 0; i < hues.length; i++) {
		const from = hues[i];
		const to = i + 1 < hues.length ? hues[i + 1] : hues[0] + 360;
		if (to - from > widest) {
			widest = to - from;
			hue = (from + widest / 2) % 360;
		}
	}
	return `#${fromHsl(hue, GEN_SATURATION, GEN_LIGHTNESS)
		.map((v) => v.toString(16).padStart(2, "0"))
		.join("")}`;
}
