<script setup>
import { computed } from "vue";
import { useRouter } from "vue-router";
import { t } from "../../composables/i18n.js";

const props = defineProps({
	acquisition: { type: Object, default: () => ({}) },
	execution: { type: Object, default: () => ({}) },
	period: { type: Object, default: () => ({}) },
});

const router = useRouter();
const stages = computed(() => [
	{ label: t("Won"), count: props.acquisition.won || 0, route: "tender-portfolio", query: { status: "won" } },
	{ label: t("SO"), count: props.execution.sales_orders || 0, route: "sales-orders" },
	{ label: t("PO"), count: props.execution.purchase_orders || 0, route: "purchasing-orders" },
	{ label: t("PR"), count: props.execution.purchase_receipts || 0, route: "purchasing-receipts" },
	{ label: t("PI"), count: props.execution.purchase_invoices || 0, route: "purchasing-invoices" },
	{ label: t("SI"), count: props.execution.sales_invoices || 0, route: "sales-invoices" },
	{ label: t("DN"), count: props.execution.delivery_notes || 0, route: "sales-delivery-notes" },
]);

function openStage(stage) {
	router.push({
		name: stage.route,
		query: {
			from_date: props.period.from_date,
			to_date: props.period.to_date,
			tender_only: "1",
			...stage.query,
		},
	});
}
</script>

<template>
	<ol class="tender-execution-flow" :aria-label="t('Tender execution flow')">
		<li v-for="(stage, index) in stages" :key="stage.label" class="execution-stage">
			<button type="button" class="execution-count font-monospace" :aria-label="`${stage.label}: ${stage.count}`" @click="openStage(stage)">
				{{ stage.count }}
			</button>
			<div class="fw-semibold">{{ stage.label }}</div>
			<span v-if="index < stages.length - 1" class="execution-arrow" aria-hidden="true">→</span>
		</li>
	</ol>
</template>

<style scoped>
.tender-execution-flow { display: flex; list-style: none; margin: 0; padding: 0; }
.execution-stage { align-items: center; display: flex; flex: 1; flex-direction: column; min-width: 0; position: relative; text-align: center; }
.execution-count { align-items: center; background: var(--tblr-primary-lt, #e9f2ff); border: 1px solid transparent; border-radius: 50%; color: var(--tblr-primary, #206bc4); cursor: pointer; display: flex; font-size: 1.15rem; font-weight: 700; height: 2.75rem; justify-content: center; transition: transform 120ms ease, border-color 120ms ease; width: 2.75rem; }
.execution-count:hover { border-color: currentColor; transform: translateY(-1px); }
.execution-count:focus-visible { box-shadow: 0 0 0 3px rgba(var(--tblr-primary-rgb), 0.2); outline: 2px solid var(--tblr-primary); outline-offset: 2px; }
.execution-arrow { color: var(--tblr-secondary, #6c7a87); font-size: 1.25rem; position: absolute; right: -0.35rem; top: 0.6rem; }
@media (max-width: 767.98px) { .tender-execution-flow { flex-direction: column; gap: 0.6rem; } .execution-stage { align-items: center; flex-direction: row; gap: 0.75rem; text-align: left; } .execution-arrow { bottom: -1rem; left: 1.05rem; right: auto; top: auto; transform: rotate(90deg); } }
</style>
