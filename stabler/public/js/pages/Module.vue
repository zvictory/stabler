<script setup>
import EmptyState from "../components/EmptyState.vue";

defineProps({
	slug: { type: String, required: true },
	title: { type: String, required: true },
	icon: { type: String, default: "ti-folder" },
});
</script>

<template>
	<div class="page-header d-print-none">
		<div class="container-xl">
			<div class="row g-2 align-items-center">
				<div class="col">
					<div class="page-pretitle">Module</div>
					<h2 class="page-title">
						<i class="ti me-2" :class="icon"></i>
						{{ title }}
					</h2>
				</div>
			</div>
		</div>
	</div>

	<div class="page-body">
		<div class="container-xl">
			<EmptyState
				icon="ti-clock-hour-4"
				accentIcon="ti-sparkles"
				tone="purple"
				:title="`${title} is coming soon`"
				:subtitle="`This module is part of the next release. The Dashboard already aggregates ${slug} data.`"
			>
				<template #actions>
					<router-link to="/dashboard" class="btn btn-primary">
						<i class="ti ti-arrow-left me-1"></i>Back to dashboard
					</router-link>
				</template>
			</EmptyState>
		</div>
	</div>
</template>
