<script setup>
import { computed } from "vue";
import { formatMoney, formatCompactMoney } from "../../composables/money.js";
import { t } from "../../composables/i18n.js";

const props = defineProps({
	kpi: { type: Object, default: () => ({}) },
	currency: { type: String, default: "" },
	language: { type: String, default: "en" },
});
const emit = defineEmits(["select"]);

const items = computed(() => [
	{ key: "count", label: t("Active tenders"), value: props.kpi.count || 0, tone: "" },
	{
		key: "value",
		label: t("Portfolio value"),
		value: formatCompactMoney(props.kpi.total_value || 0, props.currency, props.language),
		exact: formatMoney(props.kpi.total_value || 0, props.currency, props.language),
		tone: "",
	},
	{
		key: "margin",
		label: t("Avg margin"),
		value: `${props.kpi.avg_margin || 0}%`,
		tone: "text-green",
	},
	{
		key: "risk",
		label: t("At risk"),
		value: props.kpi.at_risk || 0,
		tone: props.kpi.at_risk ? "text-red" : "",
	},
	{ key: "win", label: t("Win rate"), value: `${props.kpi.win_rate || 0}%`, tone: "text-green" },
	{
		key: "remaining",
		label: t("Net remaining"),
		value: formatCompactMoney(props.kpi.total_ostatok || 0, props.currency, props.language),
		exact: formatMoney(props.kpi.total_ostatok || 0, props.currency, props.language),
		tone: "",
	},
]);
</script>

<template>
	<ul class="executive-kpis" :aria-label="t('Tender operations')">
		<li v-for="item in items" :key="item.key" class="card card-sm executive-kpi">
			<button type="button" class="card-body executive-kpi-action" @click="emit('select', item.key)">
				<div class="text-secondary small">{{ item.label }}</div>
				<div
					class="h2 mb-0 font-monospace"
					:class="item.tone"
					:title="item.exact"
					:aria-label="item.exact ? `${item.label}: ${item.exact}` : undefined"
				>
					{{ item.value }}
				</div>
			</button>
		</li>
	</ul>
</template>

<style scoped>
.executive-kpis {
	display: grid;
	grid-template-columns: repeat(6, minmax(0, 1fr));
	gap: 0.5rem;
	margin: 0 0 1rem;
	padding: 0;
	list-style: none;
}

.executive-kpi {
	min-width: 0;
}
.executive-kpi-action { background: transparent; border: 0; color: inherit; text-align: start; width: 100%; }
.executive-kpi-action:hover { background: var(--tblr-bg-surface-secondary); }

@media (max-width: 1199px) {
	.executive-kpis {
		grid-template-columns: repeat(3, minmax(0, 1fr));
	}
}

@media (max-width: 575px) {
	.executive-kpis {
		grid-template-columns: repeat(2, minmax(0, 1fr));
	}
}
</style>
