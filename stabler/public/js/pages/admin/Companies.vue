<script setup>
import { computed, onMounted, ref } from "vue";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { useConfirm } from "../../composables/useConfirm.js";
import EmptyState from "../../components/EmptyState.vue";

const loading = ref(false);
const error = ref("");
const companies = ref([]);

const drawerOpen = ref(false);
const drawerLoading = ref(false);
const drawerError = ref("");
const drawerSaving = ref(false);
const selected = ref(null);
const modules = ref({});
const allUsers = ref([]);
const allowedUsers = ref([]);
const clearingReservations = ref(false);
const clearResult = ref(null);

const { confirm } = useConfirm();

const moduleOptions = computed(() => [
	{ key: "money", label: t("Money") },
	{ key: "sales", label: t("Sales") },
	{ key: "purchasing", label: t("Purchasing") },
	{ key: "inventory", label: t("Inventory") },
	{ key: "manufacturing", label: t("Manufacturing") },
	{ key: "hr", label: t("People") },
	{ key: "stock_reservation", label: t("Stock Reservation") },
	{ key: "compliance", label: t("Compliance") },
	{ key: "field_sales", label: t("Field Sales") },
	{ key: "marketing", label: t("Trade Marketing") },
	{ key: "crm", label: t("CRM") },
	{ key: "service", label: t("Service") },
	{ key: "tender", label: t("Tender") },
	{ key: "imports", label: t("Imports") },
	{ key: "remittance", label: t("Remittance") },
	{ key: "installment", label: t("Installment") },
	// Bu ikisi eşlemede vardı ama yönetici ekranında yoktu — yani yalnız yama
	// ile set edilebiliyorlardı. Kiracı ayarı olup arayüzü olmayan bir bayrak,
	// pratikte kod sabitidir.
	{ key: "direct_invoicing", label: t("Direct Invoicing") },
	{ key: "dimensional_lines", label: t("Dimensional Sales Lines") },
	{ key: "sales_box_uom", label: t("Sales Box/Case UOM Preference") },
]);

async function load() {
	loading.value = true;
	error.value = "";
	try {
		companies.value = await call("stabler.api.organization.list_companies");
	} catch (err) {
		error.value = err?.message || "Failed to load companies.";
	} finally {
		loading.value = false;
	}
}

async function openDetail(company) {
	selected.value = company;
	drawerOpen.value = true;
	drawerLoading.value = true;
	drawerError.value = "";
	modules.value = {};
	allowedUsers.value = [];
	try {
		const [mods, users] = await Promise.all([
			call("stabler.api.organization.get_company_modules", { company: company.name }),
			call("stabler.api.admin.list_users", { limit: 500 }),
		]);
		modules.value = mods || {};
		allUsers.value = users || [];
		allowedUsers.value = (users || [])
			.filter((u) => (u.allowed_companies || []).includes(company.name))
			.map((u) => u.name);
	} catch (err) {
		drawerError.value = err?.message || "Failed to load company.";
	} finally {
		drawerLoading.value = false;
	}
}

function closeDetail() {
	if (drawerSaving.value) return;
	drawerOpen.value = false;
	selected.value = null;
	clearResult.value = null;
}

async function clearReservations() {
	if (!selected.value) return;
	const confirmed = await confirm({
		title: t("Cancel reservations?"),
		body: t("Cancel ALL open stock reservations for {0}? Reserved stock will be released.").replace(
			"{0}",
			selected.value.name,
		),
		danger: true,
	});
	if (!confirmed) return;
	clearingReservations.value = true;
	drawerError.value = "";
	clearResult.value = null;
	try {
		const result = await call("stabler.api.sales.clear_open_reservations", {
			company: selected.value.name,
		});
		clearResult.value = result;
		if (result.errors?.length) {
			drawerError.value = t("{0} reservation(s) failed to cancel. See results below.").replace(
				"{0}",
				result.errors.length,
			);
		}
	} catch (err) {
		drawerError.value = err?.message || t("Failed to clear reservations.");
	} finally {
		clearingReservations.value = false;
	}
}

async function saveModules() {
	if (!selected.value) return;
	drawerSaving.value = true;
	drawerError.value = "";
	try {
		await call("stabler.api.organization.update_company_modules", {
			company: selected.value.name,
			...modules.value,
		});
	} catch (err) {
		drawerError.value = err?.message || "Failed to save modules.";
	} finally {
		drawerSaving.value = false;
	}
}

function toggleUserAllowed(userName) {
	const i = allowedUsers.value.indexOf(userName);
	if (i >= 0) allowedUsers.value.splice(i, 1);
	else allowedUsers.value.push(userName);
}

async function saveAllowedUsers() {
	if (!selected.value) return;
	drawerSaving.value = true;
	drawerError.value = "";
	try {
		// Iterate every user: include/exclude this company in their allowed list.
		for (const u of allUsers.value) {
			const current = new Set(u.allowed_companies || []);
			const shouldBeAllowed = allowedUsers.value.includes(u.name);
			const isAllowed = current.has(selected.value.name);
			if (shouldBeAllowed === isAllowed) continue;
			if (shouldBeAllowed) current.add(selected.value.name);
			else current.delete(selected.value.name);
			await call("stabler.api.organization.set_user_allowed_companies", {
				user: u.name,
				companies: Array.from(current),
			});
		}
	} catch (err) {
		drawerError.value = err?.message || "Failed to save users.";
	} finally {
		drawerSaving.value = false;
	}
}

onMounted(load);
</script>

<template>
	<div class="card">
		<div class="card-header">
			<div class="card-title">{{ t("Companies") }}</div>
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
			v-else-if="!companies.length"
			icon="ti-building"
			title="No companies"
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>{{ t("Name") }}</th>
						<th>{{ t("Abbr") }}</th>
						<th>{{ t("Currency") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="c in companies" :key="c.name" style="cursor: pointer" @click="openDetail(c)">
						<td class="fw-semibold">{{ c.name }}</td>
						<td>{{ c.abbr }}</td>
						<td>{{ c.default_currency }}</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<div v-if="drawerOpen" class="offcanvas-backdrop fade show" @click="closeDetail"></div>
	<div
		v-if="drawerOpen"
		class="offcanvas offcanvas-end show"
		tabindex="-1"
		style="visibility: visible; width: 600px"
	>
		<div class="offcanvas-header">
			<h5 class="offcanvas-title">
				<i class="ti ti-building me-1"></i>{{ selected?.name }}
			</h5>
			<button type="button" class="btn-close" @click="closeDetail"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="drawerLoading" class="text-center py-5">
				<div class="spinner-border text-primary"></div>
			</div>
			<div v-else>
				<div v-if="drawerError" class="alert alert-danger">{{ drawerError }}</div>

				<h6 class="text-uppercase text-secondary small mb-2">{{ t("Modules") }}</h6>
				<div class="border rounded p-2 mb-3">
					<label v-for="m in moduleOptions" :key="m.key" class="form-check form-switch">
						<input
							class="form-check-input"
							type="checkbox"
							:true-value="1"
							:false-value="0"
							v-model="modules[m.key]"
						/>
						<span class="form-check-label">{{ m.label }}</span>
					</label>
				</div>
				<div class="d-flex justify-content-end mb-4">
					<button class="btn btn-primary btn-sm" :disabled="drawerSaving" @click="saveModules">
						<i class="ti ti-check me-1"></i>{{ t("Save modules") }}
					</button>
				</div>

				<template v-if="modules.stock_reservation">
					<h6 class="text-uppercase text-secondary small mb-2">
						{{ t("Stock reservations") }}
					</h6>
					<div class="border rounded p-3 mb-4">
						<p class="text-secondary small mb-2">
							{{ t("Cancel all open (submitted, non-delivered) Stock Reservation Entries for this company. Reserved stock will be returned to available quantity.") }}
						</p>
						<div v-if="clearResult" class="mb-2 small">
							<span class="text-success fw-semibold">
								{{ t("Cleared {0} of {1}").replace("{0}", clearResult.cleared).replace("{1}", clearResult.total) }}
							</span>
							<span v-if="clearResult.errors?.length" class="text-danger ms-2">
								· {{ clearResult.errors.length }} {{ t("error(s)") }}
							</span>
						</div>
						<button
							class="btn btn-outline-danger btn-sm"
							:disabled="clearingReservations"
							@click="clearReservations"
						>
							<span v-if="clearingReservations" class="spinner-border spinner-border-sm me-1"></span>
							<i v-else class="ti ti-lock-open me-1"></i>
							{{ t("Clear open reservations") }}
						</button>
					</div>
				</template>

				<h6 class="text-uppercase text-secondary small mb-2">{{ t("Allowed users") }}</h6>
				<div class="border rounded p-2 mb-3" style="max-height: 260px; overflow: auto">
					<label v-for="u in allUsers" :key="u.name" class="form-check">
						<input
							class="form-check-input"
							type="checkbox"
							:checked="allowedUsers.includes(u.name)"
							@change="toggleUserAllowed(u.name)"
						/>
						<span class="form-check-label">
							{{ u.full_name || u.name }}
							<span class="text-secondary small">— {{ u.email }}</span>
						</span>
					</label>
				</div>
				<div class="d-flex justify-content-end">
					<button class="btn btn-primary btn-sm" :disabled="drawerSaving" @click="saveAllowedUsers">
						<i class="ti ti-check me-1"></i>{{ t("Save allowed users") }}
					</button>
				</div>
				<p class="text-secondary small mt-3 mb-0">
					{{ t("Empty allowed list = user can access every company.") }}
				</p>
			</div>
		</div>
	</div>
</template>
