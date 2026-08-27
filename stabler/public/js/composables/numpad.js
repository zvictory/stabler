// Quantity entry for a wall-mounted shop-floor terminal.
//
// The finish dialog asks for the two numbers that decide a shift's output, and
// it asked for them through `<input type="number">`: two 12-pixel spinner arrows
// on a wall, operated with gloves, on an Android kiosk where whether a soft
// keyboard appears at all is a coin toss. The numpad puts the digits on the
// screen the operator is already touching.
//
// The arithmetic lives here rather than in the component because it is where
// the entry can go wrong — a second decimal point, a backspace past the start,
// a leading zero — and none of that is visible in markup.

/** Digits and the first decimal point survive; everything else is dropped. */
export function sanitizeNumeric(text) {
	let seenDot = false;
	let out = "";
	for (const ch of String(text ?? "")) {
		if (ch >= "0" && ch <= "9") out += ch;
		else if (ch === "." && !seenDot) {
			seenDot = true;
			out += ch;
		}
	}
	return out;
}

/**
 * @param {string} current the digits typed so far
 * @param {string} key a digit, ".", "back" or "clear"
 * @returns {string} the new buffer — a string, because "1." is a legitimate
 *          half-typed quantity and no number can hold it.
 */
export function applyNumpadKey(current, key) {
	const buf = String(current ?? "");

	if (key === "clear") return "";
	// The most-tapped key on a kiosk. Past the start it is a no-op, never a
	// stray "-" and never a crash.
	if (key === "back") return buf.slice(0, -1);

	if (key === ".") {
		if (buf.includes(".")) return buf; // "1.2.5" is NaN, not a quantity.
		return buf === "" ? "0." : `${buf}.`; // A bare "." is NaN too.
	}

	if (key < "0" || key > "9") return buf;

	// "0450" on a wall display reads as a typo and gets cleared and retyped.
	// The zero only survives when it is the whole number or opens a decimal.
	if (buf === "0") return key;
	return buf + key;
}
