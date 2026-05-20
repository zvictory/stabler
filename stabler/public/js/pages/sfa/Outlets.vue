<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { t } from "../../composables/i18n.js";
import EmptyState from "../../components/EmptyState.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const loading = ref(false);
const error = ref("");
const rows = ref([]);
const search = ref("");

const currency = computed(
	() => session.companyMeta(activeCompany.value)?.default_currency || "UZS"
);
const lang = computed(() => user.value?.language || "en");

const CHANNELS = ["Modern Trade", "Traditional Trade", "HoReCa", "Pharmacy", "Other"];
const OUTLET_CLASSES = ["A", "B", "C", "D"];

function blankOutlet() {
	return {
		outlet_code: "",
		outlet_name: "",
		company: activeCompany.value || "",
		customer: "",
		is_active: 1,
		channel: "",
		outlet_class: "",
		assigned_field_user: "",
		credit_limit: 0,
		address: "",
		gps_lat: null,
		gps_lng: null,
	};
}

const drawerOpen = ref(false);
const drawerMode = ref("create");
const form = ref(blankOutlet());
const submitting = ref(false);
const submitError = ref("");

function openCreate() {
	form.value = blankOutlet();
	drawerMode.value = "create";
	submitError.value = "";
	drawerOpen.value = true;
}

function openEdit(row) {
	form.value = JSON.parse(JSON.stringify(row));
	drawerMode.value = "edit";
	submitError.value = "";
	drawerOpen.value = true;
}

function closeDrawer() {
	if (submitting.value) return;
	drawerOpen.value = false;
	submitError.value = "";
}

async function submitDrawer() {
	submitError.value = "";
	const f = form.value;
	if (!f.outlet_code?.trim()) {
		submitError.value = t("Outlet code is required.");
		return;
	}
	if (!f.outlet_name?.trim()) {
		submitError.value = t("Outlet name is required.");
		return;
	}
	if (!f.company) {
		submitError.value = t("Company is required.");
		return;
	}
	const payload = {
		outlet_code: f.outlet_code.trim(),
		outlet_name: f.outlet_name.trim(),
		company: f.company,
		customer: f.customer || null,
		is_active: f.is_active ? 1 : 0,
		channel: f.channel || null,
		outlet_class: f.outlet_class || null,
		assigned_field_user: f.assigned_field_user || null,
		credit_limit: f.credit_limit || 0,
		address: f.address || null,
		gps_lat: f.gps_lat === "" ? null : f.gps_lat,
		gps_lng: f.gps_lng === "" ? null : f.gps_lng,
	};
	submitting.value = true;
	try {
		if (drawerMode.value === "create") {
			await call("stabler.api.sfa.create_outlet", { payload });
		} else {
			await call("stabler.api.sfa.update_outlet", { name: f.name, payload });
		}
		drawerOpen.value = false;
		await load();
	} catch (err) {
		submitError.value = err?.message || t("Something went wrong");
	} finally {
		submitting.value = false;
	}
}

async function load() {
	if (!activeCompany.value) {
		rows.value = [];
		return;
	}
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.sfa.list_outlets", {
			company: activeCompany.value,
			search: search.value || undefined,
		});
	} catch (e) {
		error.value = e?.message || t("Something went wrong");
		rows.value = [];
	} finally {
		loading.value = false;
	}
}

onMounted(load);
watch(activeCompany, () => {
	form.value.company = activeCompany.value || "";
	load();
});

let searchTimer = null;
watch(search, () => {
	if (searchTimer) clearTimeout(searchTimer);
	searchTimer = setTimeout(load, 250);
});
</script>

<template>
	<div class="card">
		<div class="card-header d-flex flex-wrap gap-2 align-items-center">
			<h3 class="card-title mb-0">{{ t("Outlets") }}</h3>
			<div class="ms-auto d-flex gap-2 align-items-center">
				<input
					v-model="search"
					type="search"
					class="form-control form-control-sm"
					:placeholder="t('Search outlets…')"
					style="min-width: 240px"
				/>
				<button type="button" class="btn btn-sm btn-success" @click="openCreate">
					<i class="ti ti-plus me-1"></i>{{ t("New outlet") }}
				</button>
			</div>
		</div>

		<div v-if="loading" class="card-body text-secondary">{{ t("Loading…") }}</div>
		<div v-else-if="error" class="card-body text-danger">{{ error }}</div>
		<EmptyState
			v-else-if="!rows.length"
			icon="ti-building-store"
			:title="t('No outlets yet')"
			:description="t('Create outlets to start planning routes and visits.')"
		>
			<template #actions>
				<button type="button" class="btn btn-primary" @click="openCreate">
					<i class="ti ti-plus me-1"></i>{{ t("New outlet") }}
				</button>
			</template>
		</EmptyState>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>{{ t("Outlet Code") }}</th>
						<th>{{ t("Outlet Name") }}</th>
						<th>{{ t("Channel") }}</th>
						<th>{{ t("Outlet Class") }}</th>
						<th>{{ t("Assigned Field User") }}</th>
						<th class="text-end">{{ t("Credit Limit") }}</th>
						<th>{{ t("Status") }}</th>
						<th class="text-end"></th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.name">
						<td>{{ r.outlet_code }}</td>
						<td>{{ r.outlet_name }}</td>
						<td>{{ r.channel || "—" }}</td>
						<td>{{ r.outlet_class || "—" }}</td>
						<td>{{ r.assigned_field_user || "—" }}</td>
						<td class="text-end">{{ formatMoney(r.credit_limit, currency, lang) }}</td>
						<td>
							<span
								class="badge"
								:class="r.is_active ? 'bg-success-lt' : 'bg-secondary-lt'"
							>
								{{ r.is_active ? t("Active") : t("Inactive") }}
							</span>
						</td>
						<td class="text-end">
							<button
								type="button"
								class="btn btn-sm btn-link"
								@click="openEdit(r)"
							>
								<i class="ti ti-edit me-1"></i>{{ t("Edit") }}
							</button>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<template v-if="drawerOpen">
		<div class="modal-backdrop fade show" @click="closeDrawer"></div>
		<div class="modal fade show d-block" tabindex="-1" role="dialog">
			<div class="modal-dialog modal-dialog-centered modal-lg" role="document">
				<div class="modal-content">
					<div class="modal-header">
						<h5 class="modal-title">
							{{ drawerMode === "create" ? t("New outlet") : t("Edit outlet") }}
						</h5>
						<button
							type="button"
							class="btn-close"
							:aria-label="t('Close')"
							@click="closeDrawer"
						></button>
					</div>
					<div class="modal-body">
						<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>
						<div class="row g-3">
							<div class="col-md-6">
								<label class="form-label">
									{{ t("Outlet Code") }} <span class="text-danger">*</span>
								</label>
								<input
									v-model="form.outlet_code"
									type="text"
									class="form-control"
									:disabled="drawerMode === 'edit'"
									autofocus
								/>
							</div>
							<div class="col-md-6">
								<label class="form-label">
									{{ t("Outlet Name") }} <span class="text-danger">*</span>
								</label>
								<input v-model="form.outlet_name" type="text" class="form-control" />
							</div>
							<div class="col-md-6">
								<label class="form-label">
									{{ t("Company") }} <span class="text-danger">*</span>
								</label>
								<input
									v-model="form.company"
									type="text"
									class="form-control"
									:disabled="drawerMode === 'edit'"
								/>
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Customer") }}</label>
								<input v-model="form.customer" type="text" class="form-control" />
								<div class="form-hint small">
									{{ t("Link to an existing Customer for receivables.") }}
								</div>
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Channel") }}</label>
								<select v-model="form.channel" class="form-select">
									<option value="">{{ t("— none —") }}</option>
									<option v-for="c in CHANNELS" :key="c" :value="c">{{ t(c) }}</option>
								</select>
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Outlet Class") }}</label>
								<select v-model="form.outlet_class" class="form-select">
									<option value="">{{ t("— none —") }}</option>
									<option v-for="oc in OUTLET_CLASSES" :key="oc" :value="oc">
										{{ oc }}
									</option>
								</select>
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Assigned Field User") }}</label>
								<input
									v-model="form.assigned_field_user"
									type="text"
									class="form-control"
									:placeholder="t('user@example.com')"
								/>
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Credit Limit") }}</label>
								<input
									v-model.number="form.credit_limit"
									type="number"
									step="0.01"
									inputMode="decimal"
									class="form-control"
								/>
							</div>
							<div class="col-12">
								<label class="form-label">{{ t("Address") }}</label>
								<textarea
									v-model="form.address"
									class="form-control"
									rows="2"
								></textarea>
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("GPS Latitude") }}</label>
								<input
									v-model.number="form.gps_lat"
									type="number"
									step="0.000001"
									inputMode="decimal"
									class="form-control"
								/>
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("GPS Longitude") }}</label>
								<input
									v-model.number="form.gps_lng"
									type="number"
									step="0.000001"
									inputMode="decimal"
									class="form-control"
								/>
							</div>
							<div class="col-12">
								<label class="form-check">
									<input
										v-model="form.is_active"
										type="checkbox"
										class="form-check-input"
										:true-value="1"
										:false-value="0"
									/>
									<span class="form-check-label">{{ t("Active") }}</span>
								</label>
							</div>
						</div>
					</div>
					<div class="modal-footer">
						<button
							type="button"
							class="btn btn-link link-secondary"
							:disabled="submitting"
							@click="closeDrawer"
						>
							{{ t("Cancel") }}
						</button>
						<button
							type="button"
							class="btn btn-primary ms-auto"
							:disabled="submitting || !form.outlet_code?.trim() || !form.outlet_name?.trim() || !form.company"
							@click="submitDrawer"
						>
							<span v-if="submitting" class="spinner-border spinner-border-sm me-2"></span>
							<i v-else class="ti ti-device-floppy me-1"></i>
							{{ t("Save") }}
						</button>
					</div>
				</div>
			</div>
		</div>
	</template>
</template>
