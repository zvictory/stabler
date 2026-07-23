<script setup>
import { computed } from "vue";
import { t } from "../../composables/i18n.js";

const props = defineProps({
	points: { type: Array, default: () => [] },
});

const titleId = "tender-trend-title";
const descriptionId = "tender-trend-description";
const chartPoints = computed(() => props.points.map((point, index) => ({ ...point, index })));
const maxCount = computed(() => Math.max(1, ...chartPoints.value.flatMap((point) => [Number(point.submitted) || 0, Number(point.won) || 0])));
const xFor = (index) => chartPoints.value.length < 2 ? 320 : 48 + (index * 544) / (chartPoints.value.length - 1);
const yFor = (value) => 184 - ((Number(value) || 0) / maxCount.value) * 140;
const linePath = computed(() => chartPoints.value.map((point, index) => `${index ? "L" : "M"}${xFor(index)} ${yFor(point.won)}`).join(" "));
const areaPath = computed(() => {
	if (!chartPoints.value.length) return "";
	const firstX = xFor(0);
	const lastX = xFor(chartPoints.value.length - 1);
	return `M${firstX} 184 ${chartPoints.value.map((point, index) => `L${xFor(index)} ${yFor(point.won)}`).join(" ")} L${lastX} 184 Z`;
});
const accessibleSummary = computed(() => chartPoints.value.map((point) => `${point.month}: ${point.submitted || 0} ${t("Submitted")}, ${point.won || 0} ${t("Won")}`).join(". ") || t("No tender activity for this period."));
</script>

<template>
	<div class="tender-trend-chart">
		<svg role="img" :aria-labelledby="`${titleId} ${descriptionId}`" viewBox="0 0 640 220">
			<title :id="titleId">{{ t("Three-month tender conversion") }}</title>
			<desc :id="descriptionId">{{ accessibleSummary }}</desc>
			<line x1="48" y1="184" x2="592" y2="184" class="trend-axis" />
			<path class="trend-area" :d="areaPath" />
			<path class="trend-line" :d="linePath" />
			<g v-for="point in chartPoints" :key="point.month">
				<circle :cx="xFor(point.index)" :cy="yFor(point.won)" r="4" class="trend-point" />
				<text :x="xFor(point.index)" y="208" text-anchor="middle" class="trend-label">{{ point.month }}</text>
			</g>
		</svg>
		<div class="small text-secondary d-flex gap-3" aria-hidden="true">
			<span><i class="trend-legend trend-legend--won"></i>{{ t("Won") }}</span>
			<span>{{ t("Submitted") }}: {{ points.reduce((total, point) => total + (Number(point.submitted) || 0), 0) }}</span>
		</div>
		<table class="visually-hidden">
			<thead><tr><th>{{ t("Month") }}</th><th>{{ t("Submitted") }}</th><th>{{ t("Won") }}</th><th>{{ t("Won value") }}</th></tr></thead>
			<tbody>
				<tr v-for="point in points" :key="point.month">
					<th>{{ point.month }}</th><td>{{ point.submitted }}</td><td>{{ point.won }}</td><td>{{ point.won_value }}</td>
				</tr>
			</tbody>
		</table>
	</div>
</template>

<style scoped>
.tender-trend-chart svg { display: block; height: auto; max-width: 100%; overflow: visible; }
.trend-axis { stroke: var(--tblr-border-color, #e6e7e9); }
.trend-area { animation: trend-enter 280ms ease-out both; fill: rgba(32, 107, 196, 0.14); }
.trend-line { animation: trend-enter 280ms ease-out both; fill: none; stroke: var(--tblr-primary, #206bc4); stroke-linecap: round; stroke-linejoin: round; stroke-width: 3; }
.trend-point { fill: var(--tblr-primary, #206bc4); }
.trend-label { fill: var(--tblr-secondary, #6c7a87); font-size: 12px; }
.trend-legend { background: var(--tblr-primary, #206bc4); border-radius: 50%; display: inline-block; height: 0.6rem; margin-right: 0.35rem; width: 0.6rem; }
@keyframes trend-enter { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
@media (prefers-reduced-motion: reduce) { .trend-area, .trend-line { animation: none; } }
</style>
