<script setup>
// Shared Report Center filter bar: company comes from the session; this owns the
// date range with quick presets and an Apply button, plus a slot for extra
// per-report filters (customer, item, …). Emits "apply" with {from_date, to_date}.
import { ref } from "vue";
import { todayIso } from "../composables/date.js";
import { t } from "../composables/i18n.js";
import DateInput from "./DateInput.vue";

const props = defineProps({
	from: { type: String, default: "" },
	to: { type: String, default: "" },
});
const emit = defineEmits(["apply"]);

const today = todayIso();
const fromDate = ref(props.from || `${today.slice(0, 4)}-01-01`);
const toDate = ref(props.to || today);

function preset(kind) {
	const d = new Date();
	const iso = (x) => x.toISOString().slice(0, 10);
	if (kind === "this-month") {
		fromDate.value = iso(new Date(d.getFullYear(), d.getMonth(), 1));
		toDate.value = today;
	} else if (kind === "last-month") {
		fromDate.value = iso(new Date(d.getFullYear(), d.getMonth() - 1, 1));
		toDate.value = iso(new Date(d.getFullYear(), d.getMonth(), 0));
	} else if (kind === "ytd") {
		fromDate.value = `${today.slice(0, 4)}-01-01`;
		toDate.value = today;
	}
	apply();
}

function apply() {
	emit("apply", { from_date: fromDate.value, to_date: toDate.value });
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
			<button type="button" class="btn btn-outline-secondary" @click="preset('ytd')">{{ t("YTD") }}</button>
		</div>

		<slot />

		<button type="button" class="btn btn-sm btn-primary ms-auto" @click="apply">
			<i class="ti ti-refresh me-1"></i>{{ t("Apply") }}
		</button>
	</div>
</template>
