<script setup>
import { onMounted, onBeforeUnmount, ref, watch } from "vue";
import ApexCharts from "apexcharts";

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

onMounted(() => {
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
	if (chart) {
		chart.destroy();
		chart = null;
	}
});
</script>

<template>
	<div ref="el"></div>
</template>
