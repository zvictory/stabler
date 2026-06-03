<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { t } from "../../composables/i18n.js";
import EmptyState from "../../components/EmptyState.vue";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";
import {
	listEquipment,
	createEquipment,
} from "../../api/marketing_equipment.js";

const session = useSession();
const { activeCompany } = storeToRefs(session);

const loading = ref(false);
const error = ref("");
const rows = ref([]);
const search = ref("");

const showDrawer = ref(false);
const saving = ref(false);
const saveError = ref("");
const form = ref(defaultForm());

function defaultForm() {
	return {
		asset_tag: "",
		category: "Cooler",
		outlet: "",
		brand: "",
		model: "",
		serial_no: "",
		install_date: "",
		warranty_until: "",
		status: "InService",
	};
}

const categoryOptions = computed(() => [
	{ value: "Cooler", label: t("Cooler") },
	{ value: "Freezer", label: t("Freezer") },
	{ value: "Rack", label: t("Rack") },
	{ value: "POSM", label: t("POSM") },
]);

const statusOptions = computed(() => [
	{ value: "InService", label: t("InService") },
	{ value: "Repair", label: t("Repair") },
	{ value: "Retired", label: t("Retired") },
]);

const categoryBadge = (c) => {
	switch (c) {
		case "Cooler":
			return "bg-blue-lt";
		case "Freezer":
			return "bg-cyan-lt";
		case "Rack":
			return "bg-secondary-lt";
		case "POSM":
			return "bg-warning-lt";
		default:
			return "bg-secondary-lt";
	}
};

const statusBadge = (s) => {
	switch (s) {
		case "InService":
			return "bg-success-lt";
		case "Repair":
			return "bg-warning-lt";
		case "Retired":
			return "bg-secondary-lt";
		default:
			return "bg-secondary-lt";
	}
};

const utilColor = (pct) => {
	const v = Number(pct ?? 0);
	if (v >= 75) return "bg-success";
	if (v >= 50) return "bg-warning";
	return "bg-danger";
};

async function load() {
	loading.value = true;
	error.value = "";
	try {
		rows.value = await listEquipment({
			filters: search.value ? { search: search.value } : undefined,
		});
	} catch (e) {
		error.value = e?.message || t("Something went wrong");
		rows.value = [];
	} finally {
		loading.value = false;
	}
}

onMounted(load);
watch(activeCompany, load);

let searchTimer = null;
watch(search, () => {
	if (searchTimer) clearTimeout(searchTimer);
	searchTimer = setTimeout(load, 250);
});

function openCreate() {
	form.value = defaultForm();
	saveError.value = "";
	showDrawer.value = true;
}

function closeDrawer() {
	if (saving.value) return;
	showDrawer.value = false;
}

async function submitCreate() {
	saveError.value = "";
	if (!form.value.asset_tag || !form.value.category) {
		saveError.value = t("Asset Tag and Category are required.");
		return;
	}
	saving.value = true;
	try {
		const payload = { ...form.value };
		Object.keys(payload).forEach((k) => {
			if (payload[k] === "") delete payload[k];
		});
		await createEquipment(payload);
		showDrawer.value = false;
		await load();
	} catch (e) {
		saveError.value = e?.message || t("Failed to create equipment.");
	} finally {
		saving.value = false;
	}
}
</script>

<template>
	<div class="card">
		<div class="card-header d-flex flex-wrap gap-2 align-items-center">
			<h3 class="card-title mb-0">{{ t("Equipment") }}</h3>
			<div class="ms-auto d-flex gap-2 align-items-center">
				<input
					v-model="search"
					type="search"
					class="form-control form-control-sm"
					style="min-width: 220px"
					:placeholder="t('Search asset tag…')"
				/>
				<button class="btn btn-primary btn-sm" @click="openCreate">
					{{ t("New Equipment") }}
				</button>
			</div>
		</div>

		<div v-if="loading" class="card-body text-secondary">{{ t("Loading…") }}</div>
		<div v-else-if="error" class="card-body text-danger">{{ error }}</div>
		<EmptyState
			v-else-if="!rows.length"
			icon="ti-fridge"
			:title="t('No equipment yet')"
			:description="t('Register coolers, freezers, racks, and POSM assets here.')"
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table">
				<thead>
					<tr>
						<th>{{ t("Asset Tag") }}</th>
						<th>{{ t("Category") }}</th>
						<th>{{ t("Outlet") }}</th>
						<th>{{ t("Status") }}</th>
						<th style="min-width: 180px">{{ t("Utilization %") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.name">
						<td>{{ r.asset_tag }}</td>
						<td>
							<span class="badge" :class="categoryBadge(r.category)">
								{{ t(r.category) }}
							</span>
						</td>
						<td>{{ r.outlet || "—" }}</td>
						<td>
							<span class="badge" :class="statusBadge(r.status)">
								{{ t(r.status) }}
							</span>
						</td>
						<td>
							<div class="d-flex align-items-center gap-2">
								<div class="progress flex-fill" style="height: 6px">
									<div
										class="progress-bar"
										:class="utilColor(r.utilization_pct)"
										role="progressbar"
										:style="{ width: `${Math.min(100, Number(r.utilization_pct ?? 0))}%` }"
									/>
								</div>
								<span class="text-secondary small" style="min-width: 48px">
									{{ Number(r.utilization_pct ?? 0).toFixed(0) }}%
								</span>
							</div>
						</td>
					</tr>
				</tbody>
			</table>
		</div>

		<!-- Off-canvas drawer: New Equipment -->
		<div
			v-if="showDrawer"
			class="offcanvas offcanvas-end show"
			style="visibility: visible; width: 480px"
			tabindex="-1"
		>
			<div class="offcanvas-header">
				<h2 class="offcanvas-title">{{ t("New Equipment") }}</h2>
				<button
					type="button"
					class="btn-close"
					:disabled="saving"
					@click="closeDrawer"
				/>
			</div>
			<div class="offcanvas-body">
				<div v-if="saveError" class="alert alert-danger">{{ saveError }}</div>

				<div class="mb-3">
					<label class="form-label required">{{ t("Asset Tag") }}</label>
					<input v-model="form.asset_tag" type="text" class="form-control" />
				</div>
				<div class="mb-3">
					<label class="form-label required">{{ t("Category") }}</label>
					<Select v-model="form.category" :options="categoryOptions" />
				</div>
				<div class="mb-3">
					<label class="form-label">{{ t("Outlet") }}</label>
					<input
						v-model="form.outlet"
						type="text"
						class="form-control"
						:placeholder="t('Outlet name (e.g. OUT-001)')"
					/>
				</div>
				<div class="row g-2">
					<div class="col-6 mb-3">
						<label class="form-label">{{ t("Brand") }}</label>
						<input v-model="form.brand" type="text" class="form-control" />
					</div>
					<div class="col-6 mb-3">
						<label class="form-label">{{ t("Model") }}</label>
						<input v-model="form.model" type="text" class="form-control" />
					</div>
				</div>
				<div class="mb-3">
					<label class="form-label">{{ t("Serial No") }}</label>
					<input v-model="form.serial_no" type="text" class="form-control" />
				</div>
				<div class="row g-2">
					<div class="col-6 mb-3">
						<label class="form-label">{{ t("Install Date") }}</label>
						<DateInput v-model="form.install_date" />
					</div>
					<div class="col-6 mb-3">
						<label class="form-label">{{ t("Warranty Until") }}</label>
						<DateInput v-model="form.warranty_until" />
					</div>
				</div>
				<div class="mb-3">
					<label class="form-label">{{ t("Status") }}</label>
					<Select v-model="form.status" :options="statusOptions" />
				</div>
			</div>
			<div class="offcanvas-footer p-3 border-top d-flex justify-content-end gap-2">
				<button
					type="button"
					class="btn btn-link"
					:disabled="saving"
					@click="closeDrawer"
				>
					{{ t("Cancel") }}
				</button>
				<button
					type="button"
					class="btn btn-primary"
					:disabled="saving"
					@click="submitCreate"
				>
					{{ saving ? t("Saving…") : t("Create") }}
				</button>
			</div>
		</div>
		<div
			v-if="showDrawer"
			class="offcanvas-backdrop fade show"
			@click="closeDrawer"
		/>
	</div>
</template>
