<script setup>
import { computed } from "vue";
import { t } from "../../composables/i18n.js";

const props = defineProps({
	rows: { type: Array, default: () => [] },
	formatMoney: { type: Function, required: true },
});
defineEmits(["open-deal"]);

const progressFields = [
	{ key: "po_received_pct", label: "PO receipt" },
	{ key: "po_billed_pct", label: "PO billing" },
	{ key: "so_delivered_pct", label: "SO delivery" },
	{ key: "so_billed_pct", label: "SO billing" },
];
const displayRows = computed(() => props.rows || []);
const percent = (value) => Math.max(0, Math.min(100, Number(value) || 0));
</script>

<template>
	<div class="table-responsive tender-portfolio-preview">
		<table class="table table-vcenter card-table">
			<thead><tr><th>{{ t("Tender") }}</th><th>{{ t("Status") }}</th><th>{{ t("Progress") }}</th><th class="text-end">{{ t("Spread") }}</th><th>{{ t("Risk") }}</th></tr></thead>
			<tbody>
				<tr v-if="!displayRows.length"><td colspan="5" class="text-center text-secondary py-4">{{ t("No tender rows for this period.") }}</td></tr>
				<tr v-for="row in displayRows" :key="row.deal" tabindex="0" class="portfolio-row" @click="$emit('open-deal', row.deal)" @keydown.enter="$emit('open-deal', row.deal)" @keydown.space.prevent="$emit('open-deal', row.deal)">
					<td data-label="Tender"><div class="fw-semibold">{{ row.label || row.deal }}</div><div v-if="row.lot_no" class="small text-secondary">{{ t("Lot") }} {{ row.lot_no }}</div></td>
					<td data-label="Status"><span class="badge bg-azure-lt">{{ row.status || "—" }}</span></td>
					<td data-label="Progress"><div v-for="field in progressFields" :key="field.key" class="progress-line"><span>{{ t(field.label) }}</span><div class="progress flex-grow-1" :aria-label="t(field.label)" role="progressbar" :aria-valuenow="percent(row[field.key])" aria-valuemin="0" aria-valuemax="100"><div class="progress-bar" :style="{ width: `${percent(row[field.key])}%` }"></div></div><span class="font-monospace">{{ percent(row[field.key]) }}%</span></div></td>
					<td data-label="Spread" class="text-end font-monospace">{{ formatMoney(row.spread) }}</td>
					<td data-label="Risk"><span class="badge" :class="row.risk ? 'bg-red-lt text-red' : 'bg-green-lt text-green'">{{ row.risk || t("On track") }}</span></td>
				</tr>
			</tbody>
		</table>
	</div>
</template>

<style scoped>
.portfolio-row { cursor: pointer; }
.portfolio-row:focus-visible { outline: 2px solid var(--tblr-primary, #206bc4); outline-offset: -2px; }
.progress-line { align-items: center; display: grid; font-size: 0.75rem; gap: 0.4rem; grid-template-columns: 4.75rem minmax(4rem, 1fr) 3rem; margin-bottom: 0.25rem; min-width: 14rem; }
@media (max-width: 767.98px) { .tender-portfolio-preview table, .tender-portfolio-preview tbody, .tender-portfolio-preview tr, .tender-portfolio-preview td { display: block; width: 100%; } .tender-portfolio-preview thead { display: none; } .portfolio-row { border-bottom: 1px solid var(--tblr-border-color, #e6e7e9); padding: 0.75rem; } .portfolio-row td { padding: 0.25rem 0; text-align: left !important; } .portfolio-row td::before { color: var(--tblr-secondary, #6c7a87); content: attr(data-label); display: block; font-size: 0.75rem; } }
</style>
