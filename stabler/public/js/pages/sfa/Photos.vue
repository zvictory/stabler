<script setup>
import { onMounted, ref, watch } from "vue";
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
const category = ref("");

const categoryLabel = (c) => {
	if (c === "Shelf") return t("Shelf");
	if (c === "Storefront") return t("Storefront");
	if (c === "Promo") return t("Promo");
	if (c === "Other") return t("Other");
	return c || "—";
};

async function load() {
	if (!activeCompany.value) {
		rows.value = [];
		return;
	}
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.sfa.list_photo_reports", {
			company: activeCompany.value,
			category: category.value || undefined,
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
watch(category, load);
</script>

<template>
	<div class="card">
		<div class="card-header d-flex flex-wrap gap-2 align-items-center">
			<h3 class="card-title mb-0">{{ t("Photo Reports") }}</h3>
			<div class="ms-auto">
				<select v-model="category" class="form-select form-select-sm" :aria-label="t('Category')">
					<option value="">{{ t("All categories") }}</option>
					<option value="Shelf">{{ t("Shelf") }}</option>
					<option value="Storefront">{{ t("Storefront") }}</option>
					<option value="Promo">{{ t("Promo") }}</option>
					<option value="Other">{{ t("Other") }}</option>
				</select>
			</div>
		</div>

		<div v-if="loading" class="card-body text-secondary">{{ t("Loading…") }}</div>
		<div v-else-if="error" class="card-body text-danger">{{ error }}</div>
		<EmptyState
			v-else-if="!rows.length"
			icon="ti-camera"
			:title="t('No photo reports yet')"
			:description="t('Photos capture shelves, storefronts and promotions during visits.')"
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table">
				<thead>
					<tr>
						<th>{{ t("Reference") }}</th>
						<th>{{ t("Outlet") }}</th>
						<th>{{ t("Field User") }}</th>
						<th>{{ t("Category") }}</th>
						<th>{{ t("Captured At") }}</th>
						<th>{{ t("Photo") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.name">
						<td>{{ r.name }}</td>
						<td>{{ r.outlet }}</td>
						<td>{{ r.field_user || "—" }}</td>
						<td>{{ categoryLabel(r.category) }}</td>
						<td>{{ r.captured_at || "—" }}</td>
						<td>
							<a v-if="r.photo_url" :href="r.photo_url" target="_blank" rel="noopener">
								{{ t("Open") }}
							</a>
							<span v-else>—</span>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>
</template>
