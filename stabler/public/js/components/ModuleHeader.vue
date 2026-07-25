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
			<div class="stbl-module-header-row d-flex align-items-center justify-content-between flex-nowrap">
				<h2 class="page-title stbl-module-title me-3 flex-shrink-0">
					<i class="ti" :class="icon"></i>{{ title }}
				</h2>
				<ul v-if="tabs.length" class="nav nav-bordered stbl-module-tabs flex-nowrap overflow-x-auto align-items-center text-nowrap">
					<template v-for="tab in tabs" :key="tab.name || tab.label">
						<!-- Dropdown Tab -->
						<li v-if="tab.children && tab.children.length" class="nav-item dropdown">
							<a
								class="nav-link dropdown-toggle py-2 px-2.5 font-monospace small cursor-pointer"
								:class="{ active: tab.children.some(c => c.name === activeTab) }"
								data-bs-toggle="dropdown"
								role="button"
								aria-expanded="false"
							>
								<i v-if="tab.icon" class="ti me-1" :class="tab.icon"></i>{{ tab.label }}
							</a>
							<div class="dropdown-menu dropdown-menu-end shadow-sm">
								<router-link
									v-for="child in tab.children"
									:key="child.name"
									:to="child.path"
									class="dropdown-item d-flex align-items-center py-2"
									:class="{ active: activeTab === child.name }"
								>
									<i v-if="child.icon" class="ti me-2" :class="child.icon"></i>{{ child.label }}
								</router-link>
							</div>
						</li>
						<!-- Regular Tab -->
						<li v-else class="nav-item">
							<router-link :to="tab.path" class="nav-link py-2 px-2.5 small" :class="{ active: activeTab === tab.name }">
								<i v-if="tab.icon" class="ti me-1" :class="tab.icon"></i>{{ tab.label }}
							</router-link>
						</li>
					</template>
				</ul>
			</div>
		</div>
	</div>
</template>
