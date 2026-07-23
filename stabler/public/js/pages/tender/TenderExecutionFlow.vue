<script setup>
import { computed } from "vue";
import { t } from "../../composables/i18n.js";

const props = defineProps({
	acquisition: { type: Object, default: () => ({}) },
	execution: { type: Object, default: () => ({}) },
});

const invoiceCount = computed(() => {
	const status = props.execution.invoice_status || {};
	return Object.values(status.purchase_invoices || {}).reduce((total, count) => total + (Number(count) || 0), 0)
		+ Object.values(status.sales_invoices || {}).reduce((total, count) => total + (Number(count) || 0), 0);
});
const stages = computed(() => [
	{ label: t("Won"), count: props.acquisition.won || 0 },
	{ label: t("SO"), count: props.execution.sales_orders || 0 },
	{ label: t("PO"), count: props.execution.purchase_orders || 0 },
	{ label: t("PR"), count: props.execution.received || 0 },
	{ label: `${t("PI")}/${t("SI")}`, count: invoiceCount.value },
	{ label: t("DN"), count: props.execution.delivered || 0 },
]);
</script>

<template>
	<ol class="tender-execution-flow" :aria-label="t('Tender execution flow')">
		<li v-for="(stage, index) in stages" :key="stage.label" class="execution-stage">
			<div class="execution-count font-monospace">{{ stage.count }}</div>
			<div class="fw-semibold">{{ stage.label }}</div>
			<span v-if="index < stages.length - 1" class="execution-arrow" aria-hidden="true">→</span>
		</li>
	</ol>
</template>

<style scoped>
.tender-execution-flow { display: flex; list-style: none; margin: 0; padding: 0; }
.execution-stage { align-items: center; display: flex; flex: 1; flex-direction: column; min-width: 0; position: relative; text-align: center; }
.execution-count { align-items: center; background: var(--tblr-primary-lt, #e9f2ff); border-radius: 50%; color: var(--tblr-primary, #206bc4); display: flex; font-size: 1.15rem; font-weight: 700; height: 2.75rem; justify-content: center; width: 2.75rem; }
.execution-arrow { color: var(--tblr-secondary, #6c7a87); font-size: 1.25rem; position: absolute; right: -0.35rem; top: 0.6rem; }
@media (max-width: 767.98px) { .tender-execution-flow { flex-direction: column; gap: 0.6rem; } .execution-stage { align-items: center; flex-direction: row; gap: 0.75rem; text-align: left; } .execution-arrow { bottom: -1rem; left: 1.05rem; right: auto; top: auto; transform: rotate(90deg); } }
</style>
