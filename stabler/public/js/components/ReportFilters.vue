<script setup>
// Shared Report Center filter bar: company comes from the session; this owns the
// date range with quick presets and an Apply button, plus a slot for extra
// per-report filters (customer, item, …). Emits "apply" with
// {from_date, to_date, ...filterValues} — filterValues keyed by each entry in
// the optional `filters` descriptor (QuickBooks-style multi-select Customer/Item).
import { ref, reactive, watch } from "vue";
import { todayIso } from "../composables/date.js";
import { t } from "../composables/i18n.js";
import DateInput from "./DateInput.vue";
import MultiSelectPicker from "./MultiSelectPicker.vue";

const props = defineProps({
	from: { type: String, default: "" },
	to: { type: String, default: "" },
	// Declarative extra filters, e.g.
	// [{ key: "customers", kind: "multiselect", searchApi, extraParams, idKey, display, placeholder }]
	filters: { type: Array, default: () => [] },
	// Active company; merged into every filter's extraParams so descriptors in
	// router.js can stay static (they're fixed at module-load time, before the
	// user's company selection is known).
	company: { type: String, default: "" },
});
const emit = defineEmits(["apply"]);

const today = todayIso();
const fromDate = ref(props.from || `${today.slice(0, 4)}-01-01`);
const toDate = ref(props.to || today);

// One reactive array per descriptor, keyed by descriptor.key.
const filterValues = reactive({});
watch(
	() => props.filters,
	(descriptors) => {
		for (const d of descriptors || []) {
			if (!(d.key in filterValues)) filterValues[d.key] = [];
		}
	},
	{ immediate: true }
);

function preset(kind) {
	const d = new Date();
	// LOCAL calendar date (yyyy-mm-dd) — never toISOString(), which converts to UTC
	// and shifts the day back in UTC+N zones (e.g. UZT +5 turned 01.06 → 31.05).
	const iso = (x) => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}-${String(x.getDate()).padStart(2, "0")}`;
	if (kind === "this-month") {
		fromDate.value = iso(new Date(d.getFullYear(), d.getMonth(), 1));
		toDate.value = today;
	} else if (kind === "last-month") {
		fromDate.value = iso(new Date(d.getFullYear(), d.getMonth() - 1, 1));
		toDate.value = iso(new Date(d.getFullYear(), d.getMonth(), 0));
	} else if (kind === "ytd") {
		fromDate.value = `${today.slice(0, 4)}-01-01`;
		toDate.value = today;
	} else if (kind === "this-quarter") {
		const q = Math.floor(d.getMonth() / 3);
		fromDate.value = iso(new Date(d.getFullYear(), q * 3, 1));
		toDate.value = today;
	} else if (kind === "last-quarter") {
		const q = Math.floor(d.getMonth() / 3) - 1;
		fromDate.value = iso(new Date(d.getFullYear(), q * 3, 1));
		toDate.value = iso(new Date(d.getFullYear(), q * 3 + 3, 0));
	} else if (kind === "this-year") {
		fromDate.value = `${today.slice(0, 4)}-01-01`;
		toDate.value = `${today.slice(0, 4)}-12-31`;
	} else if (kind === "last-year") {
		const y = d.getFullYear() - 1;
		fromDate.value = `${y}-01-01`;
		toDate.value = `${y}-12-31`;
	}
	apply();
}

function apply() {
	emit("apply", { from_date: fromDate.value, to_date: toDate.value, ...filterValues });
}

defineExpose({ apply });
</script>

<template>
	<div class="d-flex align-items-end gap-2 flex-wrap mb-3">
		<div>
			<label class="form-label small mb-1">{{ t("From") }}</label>
			<DateInput v-model="fromDate" size="sm" />
		</div>
		<div>
			<label class="form-label small mb-1">{{ t("To") }}</label>
			<DateInput v-model="toDate" size="sm" />
		</div>
		<div class="btn-group btn-group-sm" role="group">
			<button type="button" class="btn btn-outline-secondary" @click="preset('this-month')">{{ t("This month") }}</button>
			<button type="button" class="btn btn-outline-secondary" @click="preset('last-month')">{{ t("Last month") }}</button>
			<button type="button" class="btn btn-outline-secondary" @click="preset('this-quarter')">{{ t("This quarter") }}</button>
			<button type="button" class="btn btn-outline-secondary" @click="preset('last-quarter')">{{ t("Last quarter") }}</button>
			<button type="button" class="btn btn-outline-secondary" @click="preset('ytd')">{{ t("YTD") }}</button>
			<button type="button" class="btn btn-outline-secondary" @click="preset('this-year')">{{ t("This year") }}</button>
			<button type="button" class="btn btn-outline-secondary" @click="preset('last-year')">{{ t("Last year") }}</button>
		</div>

		<div v-for="d in filters" :key="d.key" style="min-width: 12rem">
			<label class="form-label small mb-1">{{ d.label || d.key }}</label>
			<MultiSelectPicker
				v-model="filterValues[d.key]"
				:search-api="d.searchApi"
				:extra-params="{ ...(d.extraParams || {}), company }"
				:id-key="d.idKey || 'name'"
				:display="d.display"
				:placeholder="d.placeholder || ''"
				:title="d.label || d.key"
				size="sm"
			/>
		</div>

		<slot />

		<button type="button" class="btn btn-sm btn-primary ms-auto" @click="apply">
			<i class="ti ti-refresh me-1"></i>{{ t("Apply") }}
		</button>
	</div>
</template>
