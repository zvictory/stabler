<script setup>
import { computed, onMounted, ref } from "vue";
import { adminApi } from "../../api/admin.js";
import { t } from "../../composables/i18n.js";
import EmptyState from "../../components/EmptyState.vue";

const loading = ref(false);
const error = ref("");
const roles = ref([]);

const detailOpen = ref(false);
const detailLoading = ref(false);
const detail = ref(null);
const drawerError = ref("");

async function load() {
	loading.value = true;
	error.value = "";
	try {
		roles.value = await adminApi.listRoles(1);
	} catch (err) {
		error.value = err?.message || "Failed to load roles.";
	} finally {
		loading.value = false;
	}
}

async function openDetail(name) {
	detailOpen.value = true;
	detailLoading.value = true;
	detail.value = null;
	drawerError.value = "";
	try {
		detail.value = await adminApi.getRole(name);
	} catch (err) {
		drawerError.value = err?.message || "Failed to load role.";
	} finally {
		detailLoading.value = false;
	}
}

function closeDetail() {
	detailOpen.value = false;
	detail.value = null;
}

const moduleNames = computed(() =>
	detail.value ? Object.keys(detail.value.permissions_by_module || {}).sort() : [],
);

onMounted(load);
</script>

<template>
	<div class="card">
		<div class="card-header">
			<div class="card-title">{{ t("Roles") }}</div>
			<div class="ms-auto">
				<button type="button" class="btn btn-sm btn-outline-primary" @click="load">
					<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
				</button>
			</div>
		</div>

		<div v-if="loading" class="card-body text-center py-5">
			<div class="spinner-border text-primary"></div>
		</div>
		<div v-else-if="error" class="card-body">
			<div class="alert alert-danger m-0">{{ error }}</div>
		</div>
		<EmptyState
			v-else-if="!roles.length"
			icon="ti-shield-lock"
			title="No roles found"
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>{{ t("Role") }}</th>
						<th class="w-1">{{ t("Desk access") }}</th>
						<th class="w-1 text-end">{{ t("Permissions") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in roles" :key="r.name" style="cursor: pointer" @click="openDetail(r.name)">
						<td class="fw-semibold">{{ r.name }}</td>
						<td>
							<span v-if="r.desk_access" class="badge bg-blue-lt">{{ t("Yes") }}</span>
							<span v-else class="badge bg-secondary-lt">{{ t("No") }}</span>
						</td>
						<td class="text-end font-monospace">{{ r.permission_count }}</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<!-- Detail drawer -->
	<div v-if="detailOpen" class="offcanvas-backdrop fade show" @click="closeDetail"></div>
	<div
		v-if="detailOpen"
		class="offcanvas offcanvas-end show"
		tabindex="-1"
		style="visibility: visible; width: 720px"
	>
		<div class="offcanvas-header">
			<h5 class="offcanvas-title">
				<i class="ti ti-shield-lock me-1"></i>{{ detail?.name || t("Role") }}
			</h5>
			<button type="button" class="btn-close" @click="closeDetail"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="detailLoading" class="text-center py-5">
				<div class="spinner-border text-primary"></div>
			</div>
			<div v-else-if="drawerError" class="alert alert-danger">{{ drawerError }}</div>
			<div v-else-if="detail">
				<div class="alert alert-info py-2 px-3 mb-3 small">
					<i class="ti ti-info-circle me-1"></i>
					{{ t("Read-only view. Edit permissions in Frappe's Role Permission Manager.") }}
				</div>

				<div v-for="mod in moduleNames" :key="mod" class="mb-4">
					<h6 class="text-uppercase text-secondary small mb-2">{{ mod }}</h6>
					<div class="table-responsive">
						<table class="table table-sm table-vcenter">
							<thead>
								<tr>
									<th>{{ t("DocType") }}</th>
									<th class="w-1 text-center">{{ t("Read") }}</th>
									<th class="w-1 text-center">{{ t("Write") }}</th>
									<th class="w-1 text-center">{{ t("Create") }}</th>
									<th class="w-1 text-center">{{ t("Delete") }}</th>
									<th class="w-1 text-center">{{ t("Submit") }}</th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="(p, i) in detail.permissions_by_module[mod]" :key="i">
									<td>{{ p.parent }}</td>
									<td class="text-center">
										<i v-if="p.read" class="ti ti-check text-success"></i>
									</td>
									<td class="text-center">
										<i v-if="p.write" class="ti ti-check text-success"></i>
									</td>
									<td class="text-center">
										<i v-if="p.create" class="ti ti-check text-success"></i>
									</td>
									<td class="text-center">
										<i v-if="p.delete" class="ti ti-check text-success"></i>
									</td>
									<td class="text-center">
										<i v-if="p.submit" class="ti ti-check text-success"></i>
									</td>
								</tr>
							</tbody>
						</table>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
