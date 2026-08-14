/**
 * useListSelection — row multi-select for the Imports list pages.
 *
 * The score-card strip recalculates from the SELECTED rows when there is a
 * selection, and from the whole filtered page when there is not. Both figures
 * stay available so KpiCard can show "of X on all N rows".
 *
 *   const { selected, isSelected, toggle, toggleAll, allSelected, clear, scope }
 *     = useListSelection(rows, (r) => r.name);
 *
 *   const shown = computed(() => aggregate(scope.value));   // cards read this
 *   const global = computed(() => aggregate(rows.value));   // comparison line
 *
 * Keying is by document name, never by array index: a reload reorders rows and
 * an index-keyed selection would silently point at different documents.
 */
import { computed, ref, watch } from "vue";

export function useListSelection(rows, keyOf = (r) => r.name) {
	const selected = ref([]);

	// Rows that left the page (filter change, page change) drop out of the
	// selection — the cards must never total a row the user cannot see.
	watch(rows, (list) => {
		if (!selected.value.length) return;
		const present = new Set((list || []).map(keyOf));
		const kept = selected.value.filter((k) => present.has(k));
		if (kept.length !== selected.value.length) selected.value = kept;
	});

	const isSelected = (row) => selected.value.includes(keyOf(row));

	function toggle(row) {
		const k = keyOf(row);
		selected.value = selected.value.includes(k)
			? selected.value.filter((x) => x !== k)
			: [...selected.value, k];
	}

	const allSelected = computed(
		() => (rows.value || []).length > 0 && selected.value.length >= (rows.value || []).length
	);

	function toggleAll() {
		selected.value = allSelected.value ? [] : (rows.value || []).map(keyOf);
	}

	function clear() {
		selected.value = [];
	}

	const hasSelection = computed(() => selected.value.length > 0);

	// What the cards and the footer totals sum over.
	const scope = computed(() =>
		hasSelection.value ? (rows.value || []).filter(isSelected) : rows.value || []
	);

	return { selected, isSelected, toggle, toggleAll, allSelected, clear, hasSelection, scope };
}
