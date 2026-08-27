// The operator picker is needed in two places that are now two pages: the
// single-order assignment on the detail page, and the "these fifteen orders,
// these two people" bulk gesture on the list. Same endpoint, same option shape,
// same "— Remove operator —" first entry — so it is fetched and shaped once
// rather than kept in step by hand across two files.
import { computed, ref } from "vue";
import { call } from "../api/client.js";
import { t } from "./i18n.js";

export function useOperatorOptions() {
	const operatorList = ref([]);

	const operatorSelectOptions = computed(() => [
		{ value: "", label: `— ${t("Remove operator")} —` },
		...operatorList.value.map((u) => ({ value: u.name, label: u.full_name || u.name })),
	]);

	/** @returns {string} an error message, or "" — the caller owns where it shows. */
	async function loadOperators(company) {
		if (operatorList.value.length) return "";
		try {
			operatorList.value = await call("stabler.api.manufacturing.list_operators", { company });
			return "";
		} catch (err) {
			return err?.message || "Failed to load operators.";
		}
	}

	return { operatorList, operatorSelectOptions, loadOperators };
}
