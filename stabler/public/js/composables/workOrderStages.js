// What a "stage" is on this shop floor.
//
// The obvious answer would be an ERPNext routing operation, and the detail page
// would show one card per Work Order Operation. Measured on the only tenant that
// runs work orders: 4 211 orders, 560 BOMs, and zero rows in Work Order
// Operation, zero in BOM Operation, zero Workstations. Operation cards would be
// an empty grid on every order in the system.
//
// What these orders do carry is two people doing two different jobs — pouring
// and packing — with the bill of materials split between them by role, and a
// deviation bucket per role. That is the decomposition the floor actually has,
// so that is what the cards show.

/** Assignment order, which is also the order the work happens in. */
export const STAGE_ROLES = ["Production", "Packaging"];

const fullyMoved = (i) => (Number(i.transferred_qty) || 0) >= (Number(i.required_qty) || 0);

function buildStage(role, operator, items, deviation, itemsHidden = false) {
	return {
		role,
		operator: operator || "",
		items,
		// The server filtered this role's lines out of the payload rather than
		// the order not having any. Without the distinction an empty list reads
		// as a mis-set BOM, which is a different and much louder claim.
		itemsHidden,
		// Line counts, never summed quantities: these rows are litres, kilograms
		// and pieces at once, and one total across them is wrong without looking
		// wrong. Same rule the deviation footer follows.
		lines: items.length,
		transferredLines: items.filter(fullyMoved).length,
		consumedLines: items.filter((i) => (Number(i.consumed_qty) || 0) > 0).length,
		deviation: deviation || null,
	};
}

/**
 * @param {object} detail a `work_order_detail` payload
 * @returns {Array} one card per stage the order actually has
 */
export function workOrderStages(detail) {
	const items = detail?.required_items || [];
	// `work_order_detail` gives an operator only the lines their own role writes
	// off, but hands over both operator names unfiltered. So from here the other
	// role looks like somebody assigned to a stage with no work on it — the exact
	// mis-set-BOM shape the card warns about — on every order they open.
	const scopedTo = detail?.items_scoped_to_role || "";
	const deviation = new Map((detail?.role_deviation || []).map((b) => [b.role || "", b]));
	const operators = {
		Production: detail?.operator || "",
		Packaging: detail?.packaging_operator || "",
	};

	const stages = [];
	for (const role of STAGE_ROLES) {
		const own = items.filter((i) => i.operator_role === role);
		// An empty card on every order trains people to ignore the cards. One
		// that has an operator but no work, though, is a mis-set BOM role and is
		// invisible anywhere else.
		if (!own.length && !operators[role]) continue;
		stages.push(
			buildStage(role, operators[role], own, deviation.get(role), Boolean(scopedTo) && role !== scopedTo),
		);
	}

	// The items nobody owns are the ones that need saying out loud. Folding them
	// into a stage would name the wrong person for them; dropping them makes a
	// half-described order look complete.
	const undecided = items.filter((i) => !i.operator_role);
	if (undecided.length) stages.push(buildStage("", "", undecided, deviation.get("")));

	return stages;
}
