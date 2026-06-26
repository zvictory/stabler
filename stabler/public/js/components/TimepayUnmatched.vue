<script setup>
import { ref, onMounted } from "vue";
import { call } from "../api/client.js";
import { t } from "../composables/i18n.js";
import { useToast } from "../composables/useToast.js";
import Typeahead from "./Typeahead.vue";

const props = defineProps({ company: { type: String, required: true } });
const emit = defineEmits(["close", "resolved"]);
const toast = useToast();

const loading = ref(true);
const users = ref([]); // {device_user_id, fio, events, last_seen, suggestions, _pick, _pickLabel, _saving}

async function load() {
	loading.value = true;
	try {
		const r = await call("stabler.api.timepay_match.unmatched_timepay_users", { limit: 100 });
		users.value = (r?.users || []).map((u) => ({
			...u,
			_pick: u.suggestions?.[0]?.employee || "",
			_pickLabel: u.suggestions?.[0]?.employee_name || "",
			_saving: false,
		}));
	} catch (err) {
		toast.error(err?.message || t("Could not load unmatched users."));
	} finally {
		loading.value = false;
	}
}
onMounted(load);

async function searchEmp(q) {
	const r = await call("stabler.api.hr.list_employees", { company: props.company, search: q, limit: 20 });
	const rows = Array.isArray(r) ? r : r?.rows || r?.employees || [];
	return rows.map((e) => ({ name: e.name, label: e.employee_name || e.name }));
}

function setPick(u, employee, label) {
	u._pick = employee;
	u._pickLabel = label;
}

async function linkUser(u) {
	if (!u._pick) {
		toast.error(t("Pick an employee first."));
		return;
	}
	u._saving = true;
	try {
		const r = await call("stabler.api.timepay_match.link_timepay_user", {
			device_user_id: u.device_user_id,
			employee: u._pick,
		});
		toast.success(t("Linked. {0} parked punches re-queued.").replace("{0}", r?.requeued ?? 0));
		users.value = users.value.filter((x) => x.device_user_id !== u.device_user_id);
		emit("resolved");
	} catch (err) {
		toast.error(err?.message || t("Link failed."));
	} finally {
		u._saving = false;
	}
}
</script>

<template>
	<div class="modal-backdrop fade show" @click="emit('close')"></div>
	<div class="modal fade show d-block" tabindex="-1">
		<div class="modal-dialog modal-lg modal-dialog-scrollable">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title"><i class="ti ti-user-question me-2"></i>{{ t("Unmatched TimePay users") }}</h5>
					<button type="button" class="btn-close" @click="emit('close')"></button>
				</div>
				<div class="modal-body">
					<p class="text-secondary small">
						{{ t("These device users have no employee link. Confirm a match to re-queue their punches.") }}
					</p>
					<div v-if="loading" class="text-center py-4"><span class="spinner-border text-primary"></span></div>
					<div v-else-if="!users.length" class="text-center py-4 text-secondary">
						<i class="ti ti-checks ti-lg text-success d-block mb-2"></i>{{ t("No unmatched users. All punches are mapped.") }}
					</div>
					<div v-else class="vstack gap-3">
						<div v-for="u in users" :key="u.device_user_id" class="card card-sm">
							<div class="card-body">
								<div class="d-flex align-items-start gap-2 mb-2">
									<div>
										<div class="fw-bold">{{ u.fio || t("(no name)") }}</div>
										<div class="small text-secondary">
											ID {{ u.device_user_id }} · {{ u.events }} {{ t("punches") }}
										</div>
									</div>
								</div>
								<div v-if="u.suggestions.length" class="mb-2 d-flex flex-wrap gap-1">
									<button
										v-for="s in u.suggestions"
										:key="s.employee"
										type="button"
										class="btn btn-sm"
										:class="u._pick === s.employee ? 'btn-primary' : 'btn-outline-secondary'"
										@click="setPick(u, s.employee, s.employee_name)"
									>
										{{ s.employee_name }}
										<span class="badge ms-1" :class="s.score >= 0.7 ? 'bg-green-lt' : 'bg-secondary-lt'">
											{{ Math.round(s.score * 100) }}%
										</span>
									</button>
								</div>
								<div class="d-flex gap-2 align-items-center">
									<div style="flex: 1 1 auto; min-width: 0">
										<Typeahead
											:model-value="u._pick"
											:display="u._pickLabel"
											:search="searchEmp"
											size="sm"
											:placeholder="t('Search employee…')"
											@pick="(o) => setPick(u, o.name, o.label)"
											@clear="setPick(u, '', '')"
										>
											<template #option="{ item }">{{ item.label }}</template>
										</Typeahead>
									</div>
									<button
										type="button"
										class="btn btn-sm btn-primary"
										:disabled="!u._pick || u._saving"
										@click="linkUser(u)"
									>
										<span v-if="u._saving" class="spinner-border spinner-border-sm me-1"></span>
										<i v-else class="ti ti-link me-1"></i>{{ t("Link") }}
									</button>
								</div>
							</div>
						</div>
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-link link-secondary" @click="emit('close')">{{ t("Close") }}</button>
				</div>
			</div>
		</div>
	</div>
</template>
