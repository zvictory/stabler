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
watch(activeCompany, load);

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
			<div class="ms-auto" style="min-width: 240px">
				<input
					v-model="search"
					type="search"
					class="form-control form-control-sm"
					:placeholder="t('Search outlets…')"
				/>
			</div>
		</div>

		<div v-if="loading" class="card-body text-secondary">{{ t("Loading…") }}</div>
		<div v-else-if="error" class="card-body text-danger">{{ error }}</div>
		<EmptyState
			v-else-if="!rows.length"
			icon="ti-building-store"
			:title="t('No outlets yet')"
			:description="t('Create outlets to start planning routes and visits.')"
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table">
				<thead>
					<tr>
						<th>{{ t("Outlet Code") }}</th>
						<th>{{ t("Outlet Name") }}</th>
						<th>{{ t("Channel") }}</th>
						<th>{{ t("Outlet Class") }}</th>
						<th>{{ t("Assigned Field User") }}</th>
						<th class="text-end">{{ t("Credit Limit") }}</th>
						<th>{{ t("Status") }}</th>
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
					</tr>
				</tbody>
			</table>
		</div>
	</div>
</template>
