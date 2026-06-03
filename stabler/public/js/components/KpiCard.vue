<script setup>
defineProps({
	label: { type: String, required: true },
	value: { type: String, default: "—" },
	// Optional per-currency breakdown: pre-formatted strings, dominant first.
	// When provided, lines[0] is displayed as the primary (big) value and
	// lines.slice(1) are shown as smaller secondary rows below.
	lines: { type: Array, default: null },
	icon: { type: String, default: "ti-coin" },
	trend: { type: Number, default: null },
	hint: { type: String, default: "" },
	loading: { type: Boolean, default: false },
	tone: { type: String, default: "primary" },
});
</script>

<template>
	<div class="card card-sm">
		<div class="card-body">
			<div class="row align-items-center">
				<div class="col-auto">
					<span class="bg-{{ tone || 'primary' }} text-white avatar" :class="`bg-${tone}`">
						<i class="ti" :class="icon"></i>
					</span>
				</div>
				<div class="col">
					<div class="font-weight-medium text-secondary small">{{ label }}</div>
					<div class="h2 mb-0">
						<span v-if="loading" class="placeholder col-6">&nbsp;</span>
						<span v-else>{{ lines ? lines[0] : value }}</span>
					</div>
					<template v-if="!loading && lines && lines.length > 1">
						<div
							v-for="(line, i) in lines.slice(1)"
							:key="i"
							class="text-secondary small font-monospace"
						>
							{{ line }}
						</div>
					</template>
					<div v-if="hint || trend !== null" class="text-secondary small mt-1">
						<span v-if="trend !== null" :class="trend >= 0 ? 'text-success' : 'text-danger'">
							<i class="ti" :class="trend >= 0 ? 'ti-trending-up' : 'ti-trending-down'"></i>
							{{ Math.abs(trend).toFixed(1) }}%
						</span>
						<span v-if="hint" class="ms-1">{{ hint }}</span>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
