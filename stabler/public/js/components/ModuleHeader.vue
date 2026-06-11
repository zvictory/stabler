<script setup>
const props = defineProps({
	title: { type: String, required: true },
	icon: { type: String, required: true },
	tabs: { type: Array, default: () => [] },
	activeTab: { type: [String, null], default: "" },
});
</script>

<template>
	<div class="stbl-module-header d-print-none">
		<div class="container-xl">
			<div class="stbl-module-header-row">
				<h2 class="page-title stbl-module-title">
					<i class="ti" :class="icon"></i>{{ title }}
				</h2>
				<ul v-if="tabs.length" class="nav nav-bordered stbl-module-tabs">
					<li v-for="tab in tabs" :key="tab.name" class="nav-item">
						<router-link :to="tab.path" class="nav-link" :class="{ active: activeTab === tab.name }">
							<i class="ti me-1" :class="tab.icon"></i>{{ tab.label }}
						</router-link>
					</li>
				</ul>
			</div>
		</div>
	</div>
</template>
