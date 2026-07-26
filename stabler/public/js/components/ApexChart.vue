<script setup>
import { onMounted, onBeforeUnmount, ref, watch } from "vue";
import { loadApexCharts } from "../composables/apexcharts.js";

const props = defineProps({
	options: { type: Object, required: true },
	series: { type: Array, required: true },
	type: { type: String, default: "line" },
	height: { type: [Number, String], default: 240 },
});

const el = ref(null);
let chart = null;

function buildConfig() {
	// Pull `chart` out of options FIRST so the rest-spread can't clobber our
	// merged chart config (toolbar suppression, height, etc).
	const { chart: chartOverrides = {}, ...rest } = props.options || {};
	return {
		...rest,
		chart: {
			type: props.type,
			height: props.height,
			fontFamily: "inherit",
			toolbar: { show: false },
			zoom: { enabled: false },
			animations: { enabled: true, speed: 250 },
			...chartOverrides,
		},
		series: props.series,
	};
}

// ApexCharts is loaded at runtime (see composables/apexcharts.js), so mount is
// async and `disposed` guards the two races that creates: the component being
// unmounted while the script is still in flight, and props changing before the
// chart exists. The latter needs no extra handling -- buildConfig() runs AFTER
// the await, so it always reads the current props.
let disposed = false;

onMounted(async () => {
	const ApexCharts = await loadApexCharts();
	if (disposed || !el.value) return;
	chart = new ApexCharts(el.value, buildConfig());
	chart.render();
});

watch(
	() => [props.series, props.options],
	() => {
		if (!chart) return;
		chart.updateOptions(buildConfig(), false, true);
	},
	{ deep: true }
);

onBeforeUnmount(() => {
	disposed = true;
	if (chart) {
		chart.destroy();
		chart = null;
	}
});
</script>

<template>
	<div ref="el"></div>
</template>
