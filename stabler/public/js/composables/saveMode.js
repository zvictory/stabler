// The QuickBooks-style split save button remembers which way the operator likes
// to save, in localStorage, and puts that choice on the big primary button.
//
// Which means the set of things that may be remembered is a safety property,
// not a preference: whatever is in the store becomes the default action of the
// most-clicked button on the form. The Expense form offered a third item,
// "Save & clear", that reset the form and never called the API — so once it had
// been picked, the primary button read "Save & clear" and discarded the
// operator's typing, with no dialog and nothing to undo. That item is now a
// plainly labelled "Clear form" and is not a save mode at all, but the string
// is still sitting in the localStorage of everyone who ever chose it.
//
// Hence: the stored value is never trusted, only resolved.

// Every mode here saves. Anything that does not save does not belong on the
// split button, because the split button is what the primary click runs.
export const SAVE_MODES = ["close", "new"];

export function resolveSaveMode(stored) {
	return SAVE_MODES.includes(stored) ? stored : "close";
}
