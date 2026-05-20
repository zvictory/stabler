<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import EmptyState from "../../components/EmptyState.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);

const loading = ref(false);
const error = ref("");
const rows = ref([]);
const schemeType = ref("");

const typeLabel = (s) => {
	if (s === "PercentOff") return t("Percent off");
	if (s === "BuyXGetY") return t("Buy X get Y");
	if (s === "Threshold") return t("Threshold");
	return s || "—";
};

async function load() {
	if (!activeCompany.value) {
		rows.value = [];
		return;
	}
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.sfa.list_promo_schemes", {
			company: activeCompany.value,
			scheme_type: schemeType.value || undefined,
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
watch(schemeType, load);
</script>

<template>
	<div class="card">
		<div class="card-header d-flex flex-wrap gap-2 align-items-center">
			<h3 class="card-title mb-0">{{ t("Promo Schemes") }}</h3>
			<div class="ms-auto">
				<select
					v-model="schemeType"
					class="form-select form-select-sm"
					:aria-label="t('Scheme Type')"
				>
					<option value="">{{ t("All types") }}</option>
					<option value="PercentOff">{{ t("Percent off") }}</option>
					<option value="BuyXGetY">{{ t("Buy X get Y") }}</option>
					<option value="Threshold">{{ t("Threshold") }}</option>
				</select>
			</div>
		</div>

		<div v-if="loading" class="card-body text-secondary">{{ t("Loading…") }}</div>
		<div v-else-if="error" class="card-body text-danger">{{ error }}</div>
		<EmptyState
			v-else-if="!rows.length"
			icon="ti-discount-2"
			:title="t('No promo schemes yet')"
			:description="t('Define promotions that field users can apply during visits.')"
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table">
				<thead>
					<tr>
						<th>{{ t("Scheme Code") }}</th>
						<th>{{ t("Scheme Name") }}</th>
						<th>{{ t("Scheme Type") }}</th>
						<th>{{ t("Valid From") }}</th>
						<th>{{ t("Valid To") }}</th>
						<th>{{ t("Status") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.name">
						<td>{{ r.scheme_code }}</td>
						<td>{{ r.scheme_name }}</td>
						<td>{{ typeLabel(r.scheme_type) }}</td>
						<td>{{ r.valid_from || "—" }}</td>
						<td>{{ r.valid_to || "—" }}</td>
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
