/**
 * An identity for one operator intent, held across retries.
 *
 * The money forms keep the filled form on screen when a save fails — losing the
 * operator's typing would be worse — so the natural next move is to click Save
 * again. Nothing in the payload separates that from a genuine second expense:
 * two identical cash expenses on one day are legitimate, and `cheque_no` is
 * `Exp-<date>`, which every expense that day shares. What the server needs is a
 * value that says "this is the same click", and only the client knows that.
 *
 * So the key is bound to the INTENT, not the request: generated on the first
 * attempt, repeated verbatim while that attempt keeps failing, and dropped once
 * it succeeds so the next save is a new intent. Backed by
 * `custom_idempotency_key` (unique) on Journal Entry and Payment Entry — see
 * `stabler/patches/v96_money_idempotency_key.py`.
 *
 * Contrast `RemittancePayout.vue:358`, which generates a NEW key per attempt on
 * purpose: there the key travels with a pickup code the operator retypes, so
 * reusing it after a refusal would send one key with two different codes, which
 * the server reads as a conflict rather than a retry. Here the payload is the
 * same on every attempt, which is exactly what makes reuse the right answer.
 */

export function createIntentKey(generate = () => crypto.randomUUID()) {
	let current = null;
	return {
		/** The key for the attempt about to be made — the same one after a failure. */
		begin() {
			if (!current) current = generate();
			return current;
		},
		/** This intent reached the ledger. The next save is a different intent. */
		settle() {
			current = null;
		},
		/** The key currently held, or null. For tests and for asserting state. */
		peek() {
			return current;
		},
	};
}
