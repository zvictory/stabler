// Pure tree/flatten/options helpers for the Item Group (QuickBooks-style category)
// hierarchy. No API calls here — ItemGroups.vue and Items.vue call
// stabler.api.inventory.list_item_group_tree and feed the flat `rows` in.

const ROOT_KEY = "__ROOT__";

function groupByParent(rows) {
	// A row's parent_item_group can point at a name that isn't in this payload
	// (stale data, or a caller that filtered rows). Rather than drop the row —
	// which would silently hide a whole subtree — bucket it under the root so it
	// still renders, just not indented under the parent it claims.
	const names = new Set(rows.map((r) => r.name));
	const byParent = new Map();
	for (const row of rows) {
		const parent = row.parent_item_group;
		const key = parent && names.has(parent) ? parent : ROOT_KEY;
		if (!byParent.has(key)) byParent.set(key, []);
		byParent.get(key).push(row);
	}
	return byParent;
}

export function buildItemGroupTree(rows = []) {
	const byParent = groupByParent(rows);

	function build(parentKey, depth) {
		const list = byParent.get(parentKey) || [];
		return list.map((row) => {
			const children = row.is_group ? build(row.name, depth + 1) : [];
			const childTotal = children.reduce((sum, c) => sum + c.totalItemCount, 0);
			return {
				...row,
				depth,
				children,
				totalItemCount: (row.item_count || 0) + childTotal,
			};
		});
	}

	return build(ROOT_KEY, 0);
}

export function flattenItemGroupTree(nodes = [], expanded, term = "") {
	const out = [];
	const needle = term.trim().toLowerCase();
	const matchesTerm = (n) => (n.item_group_name || n.name || "").toLowerCase().includes(needle);

	function hasMatch(node) {
		if (matchesTerm(node)) return true;
		return (node.children || []).some(hasMatch);
	}

	function walk(node) {
		if (needle && !hasMatch(node)) return;
		out.push(node);
		const isExpanded = needle ? true : expanded?.has(node.name);
		if (isExpanded) {
			for (const child of node.children || []) walk(child);
		}
	}

	for (const root of nodes) walk(root);
	return out;
}

export function itemGroupOptions(rows = [], { excludeSubtreeOf, groupsOnly = false } = {}) {
	const excluded = excludeSubtreeOf ? rows.find((r) => r.name === excludeSubtreeOf) : null;
	const tree = buildItemGroupTree(rows);
	const out = [];

	function walk(node) {
		// A node can't become its own ancestor, so its whole subtree — not just
		// itself — is excluded from the parent picker. Mirrors the backend's
		// NestedSetRecursionError guard on move.
		const withinExcluded = excluded && node.lft >= excluded.lft && node.rgt <= excluded.rgt;
		if (!withinExcluded && (!groupsOnly || node.is_group)) {
			out.push({ value: node.name, label: node.item_group_name || node.name, depth: node.depth });
		}
		if (!withinExcluded) {
			for (const child of node.children) walk(child);
		}
	}

	for (const root of tree) walk(root);
	return out;
}
