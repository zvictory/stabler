<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { formatDateTime } from "../../composables/date.js";
import EmptyState from "../../components/EmptyState.vue";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);

const loading = ref(false);
const error = ref("");
const rows = ref([]);
const postingDate = ref("");
const status = ref("");

const VAN_STATUSES = ["Loaded", "Dispatched", "Returned", "Reconciled"];

const statusFilterOptions = computed(() => [
	{ value: "", label: t("All statuses") },
	...VAN_STATUSES.map((s) => ({ value: s, label: t(s) })),
]);

const statusOptions = computed(() => VAN_STATUSES.map((s) => ({ value: s, label: t(s) })));

const statusBadge = (s) => {
	if (s === "Reconciled") return "bg-success-lt";
	if (s === "Dispatched") return "bg-info-lt";
	if (s === "Returned") return "bg-warning-lt";
	return "bg-secondary-lt";
};

const drawerOpen = ref(false);
const drawerMode = ref("create");
const submitting = ref(false);
const submitError = ref("");

function blankVanStock() {
	return {
		name: "",
		field_user: "",
		company: activeCompany.value || "",
		posting_date: "",
		status: "Loaded",
		warehouse: "",
		items: [],
	};
}

const form = ref(blankVanStock());

function openCreate() {
	form.value = blankVanStock();
	drawerMode.value = "create";
	submitError.value = "";
	drawerOpen.value = true;
}

function openEdit(row) {
	loadDetail(row.name);
}

async function loadDetail(name) {
	submitError.value = "";
	drawerMode.value = "edit";
	drawerOpen.value = true;
	submitting.value = true;
	try {
		const doc = await call("stabler.api.sfa.get_van_stock", { name });
		form.value = {
			name: doc.name,
			field_user: doc.field_user || "",
			company: doc.company || activeCompany.value || "",
			posting_date: doc.posting_date || "",
			status: doc.status || "Loaded",
			warehouse: doc.warehouse || "",
			items: (doc.items || []).map((it) => ({
				item: it.item || "",
				qty: it.qty ?? 0,
				uom: it.uom || "",
			})),
		};
	} catch (e) {
		submitError.value = e?.message || t("Failed to load van stock.");
	} finally {
		submitting.value = false;
	}
}

function closeDrawer() {
	if (submitting.value) return;
	drawerOpen.value = false;
}

function addItem() {
	form.value.items.push({ item: "", qty: 0, uom: "" });
}

function removeItem(idx) {
	form.value.items.splice(idx, 1);
}

async function submitDrawer() {
	submitError.value = "";
	const f = form.value;
	if (!f.field_user?.trim()) return (submitError.value = t("Field User is required."));
	if (!f.company?.trim()) return (submitError.value = t("Company is required."));
	if (!f.posting_date) return (submitError.value = t("Posting Date is required."));
	if (!f.status) return (submitError.value = t("Status is required."));
	for (let i = 0; i < f.items.length; i++) {
		if (!f.items[i].item?.trim()) {
			return (submitError.value = t("Item #{0}: item is required.").replace("{0}", String(i + 1)));
		}
		const qty = Number(f.items[i].qty);
		if (!Number.isFinite(qty) || qty <= 0) {
			return (submitError.value = t("Item #{0}: qty must be greater than 0.").replace("{0}", String(i + 1)));
		}
	}
	submitting.value = true;
	try {
		const payload = {
			field_user: f.field_user.trim(),
			company: f.company.trim(),
			posting_date: f.posting_date,
			status: f.status,
			warehouse: f.warehouse || null,
			items: f.items.map((it) => ({
				item: it.item.trim(),
				qty: Number(it.qty) || 0,
				uom: it.uom || null,
			})),
		};
		if (drawerMode.value === "create") {
			await call("stabler.api.sfa.create_van_stock", payload);
		} else {
			await call("stabler.api.sfa.update_van_stock", { name: f.name, payload });
		}
		drawerOpen.value = false;
		await load();
	} catch (e) {
		submitError.value = e?.message || t("Failed to save van stock.");
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
		rows.value = await call("stabler.api.sfa.list_van_stock", {
			company: activeCompany.value,
			posting_date: postingDate.value || undefined,
			status: status.value || undefined,
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
watch([postingDate, status], load);
</script>

<template>
	<div class="card">
		<div class="card-header d-flex flex-wrap gap-2 align-items-center">
			<h3 class="card-title mb-0">{{ t("Van Stock") }}</h3>
			<div class="ms-auto d-flex gap-2">
				<DateInput v-model="postingDate" size="sm" :aria-label="t('Posting date')" />
				<Select
					v-model="status"
					size="sm"
					:options="statusFilterOptions"
					:aria-label="t('Status')"
				/>
				<button type="button" class="btn btn-sm btn-success" @click="openCreate">
					<i class="ti ti-plus me-1"></i>{{ t("New Van Stock") }}
				</button>
			</div>
		</div>

		<div v-if="loading" class="card-body text-secondary">{{ t("Loading…") }}</div>
		<div v-else-if="error" class="card-body text-danger">{{ error }}</div>
		<EmptyState
			v-else-if="!rows.length"
			icon="ti-truck-loading"
			:title="t('No van stock yet')"
			:description="t('Van stock tracks what each field user has loaded for the day.')"
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>{{ t("Reference") }}</th>
						<th>{{ t("Field User") }}</th>
						<th>{{ t("Posting Date") }}</th>
						<th>{{ t("Warehouse") }}</th>
						<th>{{ t("Status") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr
						v-for="r in rows"
						:key="r.name"
						style="cursor: pointer"
						@click="openEdit(r)"
					>
						<td>{{ r.name }}</td>
						<td>{{ r.field_user }}</td>
						<td>{{ formatDateTime(r.posting_date) || "—" }}</td>
						<td>{{ r.warehouse || "—" }}</td>
						<td><span class="badge" :class="statusBadge(r.status)">{{ t(r.status) }}</span></td>
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
							{{ drawerMode === "create" ? t("New Van Stock") : t("Edit Van Stock") }}
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
									{{ t("Field User") }} <span class="text-danger">*</span>
								</label>
								<input v-model="form.field_user" type="text" class="form-control" autofocus />
							</div>
							<div class="col-md-6">
								<label class="form-label">
									{{ t("Company") }} <span class="text-danger">*</span>
								</label>
								<input v-model="form.company" type="text" class="form-control" />
							</div>
							<div class="col-md-6">
								<label class="form-label">
									{{ t("Posting Date") }} <span class="text-danger">*</span>
								</label>
								<DateInput v-model="form.posting_date" />
							</div>
							<div class="col-md-6">
								<label class="form-label">
									{{ t("Status") }} <span class="text-danger">*</span>
								</label>
								<Select v-model="form.status" :options="statusOptions" />
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Warehouse") }}</label>
								<input v-model="form.warehouse" type="text" class="form-control" />
							</div>
						</div>

						<hr class="my-3" />
						<div class="d-flex align-items-center mb-2">
							<h6 class="m-0">{{ t("Items") }}</h6>
							<button
								type="button"
								class="btn btn-sm btn-outline-primary ms-auto"
								@click="addItem"
							>
								<i class="ti ti-plus me-1"></i>{{ t("Add row") }}
							</button>
						</div>
						<div v-if="!form.items.length" class="text-secondary small mb-2">
							{{ t("No items yet.") }}
						</div>
						<div v-else class="table-responsive">
							<table class="table table-sm table-vcenter">
								<thead>
									<tr>
										<th style="width: 24px">#</th>
										<th>{{ t("Item") }}</th>
										<th style="width: 120px">{{ t("Qty") }}</th>
										<th style="width: 140px">{{ t("UOM") }}</th>
										<th style="width: 40px"></th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="(it, idx) in form.items" :key="idx">
										<td class="text-secondary">{{ idx + 1 }}</td>
										<td>
											<input
												v-model="it.item"
												type="text"
												class="form-control form-control-sm"
											/>
										</td>
										<td>
											<input
												v-model.number="it.qty"
												type="number"
												inputMode="decimal"
												class="form-control form-control-sm text-end"
												min="0"
												step="any"
											/>
										</td>
										<td>
											<input
												v-model="it.uom"
												type="text"
												class="form-control form-control-sm"
											/>
										</td>
										<td>
											<button
												type="button"
												class="btn btn-sm btn-link link-danger p-0"
												:aria-label="t('Remove row')"
												@click="removeItem(idx)"
											>
												<i class="ti ti-x"></i>
											</button>
										</td>
									</tr>
								</tbody>
							</table>
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
							:disabled="
								submitting ||
								!form.field_user?.trim() ||
								!form.company?.trim() ||
								!form.posting_date ||
								!form.status
							"
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
