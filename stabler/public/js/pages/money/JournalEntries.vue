<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, todayIso, daysAgoIso } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { getDocstatusLabel, getStatusBadgeClass } from "../../composables/status.js";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import JournalEntryDrawer from "../../components/JournalEntryDrawer.vue";
import { useEscapeBack } from "../../composables/useEscapeBack.js";

const session = useSession();
const route = useRoute();
const { activeCompany, user } = storeToRefs(session);

const statusFilter = ref("");
const statusOptions = computed(() => [
	{ value: "", label: t("Draft + submitted") },
	{ value: "Draft", label: t("Draft") },
	{ value: "Submitted", label: t("Submitted") },
	{ value: "Cancelled", label: t("Cancelled") },
]);

const today = todayIso();
const monthAgo = daysAgoIso(30);

const fromDate = ref(monthAgo);
const toDate = ref(today);
const limit = ref(50);

const loading = ref(false);
const error = ref("");
const rows = ref([]);

// The entry's view/edit surface, in a drawer. `null` means closed; otherwise
// `{ mode: 'view' | 'edit', name }` is what JournalEntryDrawer was opened
// with — everything past that point (switching from viewing to editing,
// amending, saving) is the drawer's own business, not this page's. See
// JournalEntryDrawer.vue's file header for why the split sits there.
const drawer = ref(null);
// So the page's Escape handler can defer to the drawer's own draft guard —
// see useEscapeBack below. The drawer's dirty state (`form`, `pristine`)
// lives inside the component now, out of this page's reach, so asking "is it
// safe to close" has to go through the instance itself.
const drawerRef = ref(null);

// ESC → back (general app rule). There were two listeners here, and neither
// knew about the other: the generic one navigated away and the page-local one
// navigated again, so a draft in the edit pane was discarded — twice over —
// without a word. One listener, and the drawer gets first refusal.
useEscapeBack(() => {
	if (!drawer.value) return false;
	// The drawer decides whether it is safe to close (dirty-draft confirm,
	// same as its own Cancel button and backdrop click) and emits `close`
	// itself once it is. Escape does not get a shortcut around that.
	drawerRef.value?.requestClose();
	return true;
	// `ownsDrawer` is not optional here: the drawer below is hand-rolled, so the
	// composable would otherwise treat it as an overlay that closes itself and
	// never call this handler at all.
}, "/money", { ownsDrawer: () => !!drawer.value });

const currencyCode = computed(() => (session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency || "USD");
const currency = currencyCode;

// ── List + selection ─────────────────────────────────────────────────────────
async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.money.list_journal_entries", {
			company: activeCompany.value, from_date: fromDate.value, to_date: toDate.value,
			status: statusFilter.value || undefined, limit: limit.value,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load journal entries.");
	} finally {
		loading.value = false;
	}
}

function select(name) {
	drawer.value = { mode: "view", name };
}
function openCreate() {
	drawer.value = { mode: "edit", name: null };
}

onMounted(async () => {
	await load();
	const openName = route.query?.open;
	if (openName) select(String(openName));
});
watch(activeCompany, () => {
	drawer.value = null; // another company's ledger, not this one's
	load();
});
watch(statusFilter, load);
</script>

<template>
	<!-- Toolbar -->
	<div class="d-flex flex-wrap align-items-end gap-2 mb-3">
		<div><label class="form-label small mb-1">{{ t("From") }}</label><DateInput v-model="fromDate" size="sm" /></div>
		<div><label class="form-label small mb-1">{{ t("To") }}</label><DateInput v-model="toDate" size="sm" /></div>
		<div style="min-width: 160px"><label class="form-label small mb-1">{{ t("Status") }}</label><Select v-model="statusFilter" :options="statusOptions" size="sm" /></div>
		<button type="button" class="btn btn-sm btn-outline-secondary" @click="load"><i class="ti ti-refresh me-1"></i>{{ t("Apply") }}</button>
		<button type="button" class="btn btn-sm btn-primary ms-auto" :disabled="!activeCompany" @click="openCreate">
			<i class="ti ti-plus me-1"></i>{{ t("New journal") }}
		</button>
	</div>

	<div v-if="error" class="alert alert-danger">{{ error }}</div>

	<div class="card">
		<div class="row g-0">
			<!-- The list, full width. Both view and edit happen in
			     JournalEntryDrawer now, floating over the page instead of
			     sharing it with a 7/8-col detail pane. -->
			<div class="col-12">
				<table class="table table-sm table-hover mb-0">
					<thead><tr>
						<th>{{ t("Entry") }}</th>
						<!-- The figure is total_debit_base — the COMPANY's currency, not the
						     entry's. Unlabelled, a multi-currency entry's so'm total read as
						     the USD figure the user had just typed. The detail table has
						     said "Total (UZS)" over the same number all along. -->
						<th class="text-end">{{ t("Total") }} ({{ currency }})</th>
					</tr></thead>
					<SkeletonRows v-if="loading" :rows="12" :cols="2" />
					<tbody v-else>
						<tr v-if="!rows.length"><td colspan="2" class="text-secondary text-center py-4">{{ t("No journal entries in this range") }}</td></tr>
						<tr
							v-for="r in rows"
							:key="r.name"
							class="cursor-pointer"
							:class="{ 'table-active': drawer?.mode === 'view' && drawer?.name === r.name }"
							@click="select(r.name)"
						>
							<td>
								<div class="d-flex align-items-center gap-1">
									<span class="fw-semibold font-monospace small text-truncate">{{ r.name }}</span>
									<i v-if="r.multi_currency" class="ti ti-arrows-exchange text-azure" :title="t('Multi-currency')" style="font-size:.85rem"></i>
								</div>
								<div v-if="r.user_remark" class="small text-truncate" style="max-width: 220px">{{ r.user_remark }}</div>
								<div class="small text-secondary">{{ formatDate(r.posting_date) }} ·
									<span class="badge" :class="getStatusBadgeClass('Journal Entry', r.docstatus)">{{ getDocstatusLabel(r.docstatus) }}</span>
								</div>
							</td>
							<td class="text-end font-monospace align-middle">{{ formatMoney(r.total_debit_base, r.base_currency || currency, user.language) }}</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>
	</div>

	<JournalEntryDrawer
		v-if="drawer"
		ref="drawerRef"
		:key="`${drawer.mode}:${drawer.name || ''}`"
		:mode="drawer.mode"
		:name="drawer.name"
		@close="drawer = null"
		@saved="load"
	/>
</template>
