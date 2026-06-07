<script setup>
// PeriodSelect — period-preset dropdown for date-range filters.
//
// v-model: preset key string (one of the keys understood by presetRange()).
// Emits "change" with { from, to } ISO strings whenever the preset changes.
// "custom" key is a no-op sentinel: callers should render DateInput fields
// alongside this component and show them when modelValue === "custom".
//
// Reused by AccountLedger and Reports; keep dependency surface minimal.
import { computed } from "vue";
import Select from "./Select.vue";
import { presetRange } from "../composables/date.js";
import { t } from "../composables/i18n.js";

const props = defineProps({
	modelValue: { type: String, default: "custom" },
	size: { type: String, default: "md" },
	// Show the "All (no bounds)" option. Useful for ledger; may not make sense
	// for P&L reports that require a bounded fiscal period.
	showAll: { type: Boolean, default: true },
});

const emit = defineEmits(["update:modelValue", "change"]);

const PRESETS = computed(() => {
	const list = [
		{ value: "today", label: t("Today") },
		{ value: "mtd", label: t("Month to date") },
		{ value: "this_month", label: t("This month") },
		{ value: "last_month", label: t("Last month") },
		{ value: "ytd", label: t("Year to date") },
		{ value: "this_year", label: t("This year") },
		{ value: "last_year", label: t("Last year") },
	];
	if (props.showAll) list.push({ value: "all", label: t("All time") });
	list.push({ value: "custom", label: t("Custom") });
	return list;
});

function onSelect(key) {
	emit("update:modelValue", key);
	emit("change", presetRange(key));
}
</script>

<template>
	<Select
		:model-value="modelValue"
		:options="PRESETS"
		value-key="value"
		label-key="label"
		:size="size"
		style="min-width: 140px"
		@update:model-value="onSelect"
	/>
</template>
