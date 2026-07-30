import { describe, expect, it } from "vitest";

import { buildItemGroupTree, flattenItemGroupTree, itemGroupOptions } from "../composables/itemGroupTree.js";

const ROWS = [
	{ name: "All Item Groups", parent_item_group: "", is_group: 1, lft: 1, rgt: 12, item_count: 0 },
	{ name: "Furniture", parent_item_group: "All Item Groups", is_group: 1, lft: 2, rgt: 7, item_count: 0 },
	{ name: "Chairs", parent_item_group: "Furniture", is_group: 0, lft: 3, rgt: 4, item_count: 3 },
	{ name: "Tables", parent_item_group: "Furniture", is_group: 0, lft: 5, rgt: 6, item_count: 4 },
	{ name: "Services", parent_item_group: "All Item Groups", is_group: 0, lft: 8, rgt: 9, item_count: 2 },
];

describe("buildItemGroupTree", () => {
	it("builds a single-root tree from lft-ordered rows with correct depth", () => {
		const tree = buildItemGroupTree(ROWS);

		expect(tree).toHaveLength(1);
		const root = tree[0];
		expect(root.name).toBe("All Item Groups");
		expect(root.depth).toBe(0);

		const furniture = root.children.find((n) => n.name === "Furniture");
		expect(furniture.depth).toBe(1);
		expect(furniture.children.map((n) => n.name)).toEqual(["Chairs", "Tables"]);
		expect(furniture.children.every((n) => n.depth === 2)).toBe(true);
	});

	it("buckets a row whose parent is missing from the payload as a top-level node instead of dropping it", () => {
		const rows = [...ROWS, { name: "Orphaned", parent_item_group: "Deleted Group", is_group: 0, lft: 10, rgt: 11, item_count: 1 }];
		const tree = buildItemGroupTree(rows);

		// "Deleted Group" isn't in this payload, so Orphaned can't be nested under
		// it — it lands in the root bucket alongside the true root rather than
		// vanishing.
		expect(tree).toHaveLength(2);
		expect(tree.map((n) => n.name)).toContain("Orphaned");
	});

	it("rolls up totalItemCount from descendants, not just the node's own item_count", () => {
		const tree = buildItemGroupTree(ROWS);
		const root = tree[0];
		const furniture = root.children.find((n) => n.name === "Furniture");

		// Furniture carries 0 items directly; Chairs (3) + Tables (4) = 7.
		expect(furniture.item_count).toBe(0);
		expect(furniture.totalItemCount).toBe(7);
		// Root rolls up everything under it: 7 (Furniture) + 2 (Services) = 9.
		expect(root.totalItemCount).toBe(9);
	});
});

describe("flattenItemGroupTree", () => {
	it("shows only expanded branches when there is no search term", () => {
		const tree = buildItemGroupTree(ROWS);
		const collapsed = flattenItemGroupTree(tree, new Set());
		expect(collapsed.map((n) => n.name)).toEqual(["All Item Groups"]);

		const expanded = new Set(["All Item Groups", "Furniture"]);
		const opened = flattenItemGroupTree(tree, expanded);
		expect(opened.map((n) => n.name)).toEqual(["All Item Groups", "Furniture", "Chairs", "Tables", "Services"]);
	});

	it("force-opens the ancestors of a deep match and hides non-matching siblings", () => {
		const tree = buildItemGroupTree(ROWS);
		// Nothing is expanded, but searching for "Chairs" must still surface it —
		// through its ancestor chain — while Tables and Services stay hidden.
		const result = flattenItemGroupTree(tree, new Set(), "chair");

		expect(result.map((n) => n.name)).toEqual(["All Item Groups", "Furniture", "Chairs"]);
	});
});

describe("itemGroupOptions", () => {
	it("excludes a node and its entire subtree, mirroring the move-loop guard", () => {
		const options = itemGroupOptions(ROWS, { excludeSubtreeOf: "Furniture" });
		const names = options.map((o) => o.value);

		expect(names).not.toContain("Furniture");
		expect(names).not.toContain("Chairs");
		expect(names).not.toContain("Tables");
		expect(names).toContain("All Item Groups");
		expect(names).toContain("Services");
	});

	it("keeps only groups when groupsOnly is set", () => {
		const options = itemGroupOptions(ROWS, { groupsOnly: true });
		expect(options.map((o) => o.value)).toEqual(["All Item Groups", "Furniture"]);
	});
});
