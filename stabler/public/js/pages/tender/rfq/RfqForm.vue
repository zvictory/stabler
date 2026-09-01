<script setup>
// New RFQ — the request side of the sourcing conversation, as a full page
// instead of the old workspace modal. The item lines arrive pre-filled from
// the tender intake: a lot that reached sourcing was already specified line
// by line, and this form's job is to ask suppliers for exactly that list.
import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../../stores/session.js";
import { call } from "../../../api/client.js";
import { formatMoney } from "../../../composables/money.js";
import { t } from "../../../composables/i18n.js";
import { useToast } from "../../../composables/useToast.js";
import { buildTenderQuery } from "../../../composables/useTenderContext.js";
import DateInput from "../../../components/DateInput.vue";
import EmptyState from "../../../components/EmptyState.vue";
import MoneyInput from "../../../components/MoneyInput.vue";
import SkeletonRows from "../../../components/SkeletonRows.vue";
import Typeahead from "../../../components/Typeahead.vue";
import TenderPage from "../TenderPage.vue";
import { reachOf } from "../../../composables/sourcingReach.js";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const route = useRoute();
const router = useRouter();
const toast = useToast();

const deal = ref(route.query.deal ? String(route.query.deal) : "");
const dealLabel = ref("");
const currency = ref("");

const defaultsLoading = ref(false);
const suppliers = ref([]);
// Country by supplier, kept beside `suppliers` rather than inside it: the create
// call posts `suppliers` verbatim as a list of names, and widening it to objects
// would change the payload to teach the badge a fact only the badge needs.
const supplierCountry = ref({});
// Sent by `get_deal_rfq_defaults`, never typed here — see the note on that
// endpoint. Zeroed until it arrives so the badge stays quiet rather than
// announcing a policy it has not been told.
const policy = ref({ min_suppliers: 0, min_countries: 0 });
const items = ref([]);
const scheduleDate = ref("");
const saving = ref(false);

const blankLine = () => ({ item_code: "", itemLabel: "", qty: 1, uom: "", rate: 0 });

async function searchDeals(q) {
	const r = await call("stabler.api.crm.list_deals", {
		company: activeCompany.value,
		search: q,
		deal_type: "Tender",
		page_length: 20,
	});
	return (r?.deals || []).map((d) => ({
		name: d.name,
		label: d.organization || d.lead_name || d.name,
	}));
}

async function searchSuppliers(q) {
	const rows = await call("stabler.api.purchasing.list_suppliers", {
		company: activeCompany.value,
		search: q,
		limit: 20,
	});
	return (rows || []).map((r) => ({
		name: r.name,
		label: r.supplier_name || r.name,
		country: r.country || "",
	}));
}

async function searchItems(q) {
	const rows = await call("stabler.api.inventory.list_items", { search: q, limit: 20 });
	return (rows || []).map((r) => ({ name: r.name, label: r.item_name || r.name }));
}

function pickDeal(o) {
	deal.value = o.name;
	dealLabel.value = o.label;
	router.replace({ query: buildTenderQuery(route.query, { deal: o.name }) });
	loadDefaults();
}

function pickSupplier(o) {
	if (!o) return;
	// Remembered even for a vendor already on the list: the picker is the only
	// place the country is ever seen, and a re-pick is the cheapest chance to
	// learn one that was blank the first time round.
	supplierCountry.value[o.name] = o.country || "";
	if (!suppliers.value.includes(o.name)) suppliers.value.push(o.name);
}

function pickItem(line, o) {
	line.item_code = o.name;
	line.itemLabel = o.label;
	if (!line.uom && o.uom) line.uom = o.uom;
}

// The tender lines, exactly as captured at intake. Rates are the buyer's
// target — shown muted next to what is being asked, never sent to suppliers.
async function loadDefaults() {
	if (!deal.value || !activeCompany.value) return;
	defaultsLoading.value = true;
	try {
		const res = await call("stabler.api.sourcing.get_deal_rfq_defaults", {
			deal: deal.value,
			company: activeCompany.value,
		});
		dealLabel.value = res?.deal_label || deal.value;
		currency.value = res?.currency || "";
		policy.value = {
			min_suppliers: Number(res?.policy?.min_suppliers) || 0,
			min_countries: Number(res?.policy?.min_countries) || 0,
		};
		const lines = (res?.items || []).map((i) => ({
			item_code: i.item_code || "",
			itemLabel: i.item_name || i.item_code || "",
			qty: Number(i.qty) || 1,
			uom: i.uom || "",
			rate: Number(i.rate) || 0,
		}));
		items.value = lines.length ? lines : [blankLine()];
	} catch (err) {
		toast.error(err?.message || t("Could not load the tender's items."));
		items.value = [blankLine()];
	} finally {
		defaultsLoading.value = false;
	}
}

function addLine() {
	items.value.push(blankLine());
}

function removeLine(idx) {
	items.value.splice(idx, 1);
	if (!items.value.length) addLine();
}

// What THIS invitation reaches, counted before it is saved. Rounds already sent
// for the lot are counted on the server and shown on the sourcing workspace; the
// two are reported apart on purpose, because "asked" and "answered" are separate
// facts and one standing in for the other is what hid the gap in the first place.
const reach = computed(() =>
	reachOf(
		suppliers.value.map((name) => ({ name, supplier: name, country: supplierCountry.value[name] || "" })),
		policy.value.min_suppliers,
		policy.value.min_countries,
	),
);

const validLines = computed(() => items.value.filter((l) => l.item_code && Number(l.qty) > 0));
const canCreate = computed(
	() => Boolean(deal.value) && suppliers.value.length > 0 && validLines.value.length > 0 && !saving.value,
);

const totalTarget = computed(() =>
	validLines.value.reduce((s, l) => s + (Number(l.qty) || 0) * (Number(l.rate) || 0), 0),
);

function fmtRate(v) {
	return formatMoney(v, currency.value, user.value.language);
}

async function create() {
	if (!canCreate.value) return;
	saving.value = true;
	try {
		const res = await call("stabler.api.sourcing.create_rfq", {
			deal: deal.value,
			suppliers: JSON.stringify(suppliers.value),
			items: JSON.stringify(
				validLines.value.map((l) => ({
					item_code: l.item_code,
					qty: Number(l.qty),
					...(l.uom ? { uom: l.uom } : {}),
				})),
			),
			schedule_date: scheduleDate.value || null,
			company: activeCompany.value,
		});
		toast.success(t("Request for quotation created as draft."));
		router.push({ name: "tender-rfq-detail", params: { name: res.name }, query: { ...route.query } });
	} catch (err) {
		toast.error(err?.message || t("Could not create RFQ."));
	} finally {
		saving.value = false;
	}
}

// Direct-URL smoke rule: opening /tender/rfq/new?deal=… prefilled is the
// primary path here, not a corner case — branch on the query, not on flags.
onMounted(() => {
	if (deal.value) {
		loadDefaults();
	} else {
		items.value = [blankLine()];
	}
});
</script>

<template>
	<TenderPage :label="t('Tender')" :title="t('New request for quotation')">
		<div class="card mb-3">
			<div class="card-body">
				<div class="row g-3">
					<div class="col-md-6">
						<label class="form-label fw-semibold">{{ t("Tender lot") }} <span class="text-danger" aria-hidden="true">*</span><span class="visually-hidden"> {{ t("Required") }}</span></label>
						<Typeahead
							:model-value="deal"
							:display="dealLabel || deal"
							:search="searchDeals"
							:placeholder="t('Search a tender deal… ⌘K')"
							@pick="pickDeal"
							@clear="
								deal = '';
								dealLabel = '';
								items = [blankLine()];
							"
						>
							<template #option="{ item }">{{ item.label }}</template>
						</Typeahead>
					</div>
					<div class="col-md-3">
						<label class="form-label fw-semibold">{{ t("Required response date") }}</label>
						<DateInput v-model="scheduleDate" />
					</div>
					<div class="col-md-3" v-if="totalTarget">
						<label class="form-label fw-semibold">{{ t("Target total") }}</label>
						<div class="form-control-plaintext font-monospace">{{ fmtRate(totalTarget) }}</div>
					</div>
				</div>
			</div>
		</div>

		<div class="card mb-3">
			<div class="card-header py-2 fw-semibold">{{ t("Suppliers to ask") }} <span class="text-danger" aria-hidden="true">*</span><span class="visually-hidden"> {{ t("Required") }}</span></div>
			<div class="card-body">
				<div v-if="suppliers.length" class="d-flex flex-wrap gap-1 mb-2">
					<span v-for="(sup, idx) in suppliers" :key="sup" class="badge bg-primary-lt text-primary">
						{{ sup }}
						<button
							type="button"
							class="btn-close ms-1"
							style="font-size: 10px"
							@click="suppliers.splice(idx, 1)"
						></button>
					</span>
				</div>
				<Typeahead
					:search="searchSuppliers"
					:placeholder="t('Search and add suppliers… ⌘K')"
					@pick="pickSupplier"
				>
					<template #option="{ item }">{{ item.label }}</template>
				</Typeahead>
				<div v-if="policy.min_suppliers" class="small mt-2">
					<div class="text-secondary">
						{{
							t("Asking {count} vendor(s) from {countries} country(ies).", {
								count: reach.suppliers,
								countries: reach.countries,
							})
						}}
						{{
							t("The policy wants {min} quotations from {countries} countries.", {
								min: policy.min_suppliers,
								countries: policy.min_countries,
							})
						}}
					</div>
					<div v-if="suppliers.length && !reach.meets_countries" class="text-warning mt-1">
						<i class="ti ti-alert-triangle me-1"></i>
						{{
							t(
								"This invitation reaches {countries} country(ies). On its own it cannot satisfy the {min}-country rule — a quotation attached from elsewhere still can.",
								{ countries: reach.countries, min: policy.min_countries },
							)
						}}
					</div>
					<div v-if="reach.unknown_country" class="text-warning mt-1">
						<i class="ti ti-map-pin-off me-1"></i>
						{{
							t(
								"{count} of the vendors has no country on file, so it counts toward no country. Fixing the supplier record is quicker now than after the answers arrive.",
								{ count: reach.unknown_country },
							)
						}}
					</div>
				</div>
			</div>
		</div>

		<div class="card mb-3">
			<div class="card-header py-2 d-flex justify-content-between align-items-center">
				<span class="fw-semibold">{{ t("Requested items") }} <span class="text-danger" aria-hidden="true">*</span><span class="visually-hidden"> {{ t("Required") }}</span></span>
				<button type="button" class="btn btn-outline-secondary btn-sm" @click="addLine">
					<i class="ti ti-plus me-1"></i>{{ t("Add line") }}
				</button>
			</div>
			<div class="table-responsive">
				<table class="table table-vcenter card-table">
					<thead>
						<tr>
							<th>{{ t("Item") }}</th>
							<th style="width: 130px" class="text-end">{{ t("Qty") }}</th>
							<th style="width: 110px">{{ t("UOM") }}</th>
							<th style="width: 140px" class="text-end">{{ t("Target rate") }}</th>
							<th style="width: 44px"></th>
						</tr>
					</thead>
					<tbody>
						<SkeletonRows v-if="defaultsLoading" :cols="5" :rows="3" />
						<tr v-for="(line, idx) in items" :key="idx">
							<td>
								<Typeahead
									:model-value="line.item_code"
									:display="line.itemLabel"
									:search="searchItems"
									:placeholder="t('Search item… ⌘K')"
									@pick="(o) => pickItem(line, o)"
									@clear="
										line.item_code = '';
										line.itemLabel = '';
									"
								>
									<template #option="{ item }">{{ item.label }}</template>
								</Typeahead>
							</td>
							<td>
								<MoneyInput v-model="line.qty" hide-currency :min="1" />
							</td>
							<td>
								<input v-model="line.uom" type="text" class="form-control" />
							</td>
							<td class="text-end font-monospace text-secondary">
								{{ line.rate ? fmtRate(line.rate) : "—" }}
							</td>
							<td class="text-center">
								<button
									type="button"
									class="btn btn-ghost-danger btn-icon btn-sm"
									@click="removeLine(idx)"
								>
									<i class="ti ti-trash"></i>
								</button>
							</td>
						</tr>
					</tbody>
					<tbody v-if="!defaultsLoading && !items.length">
						<tr>
							<td colspan="5">
								<EmptyState
									icon="ti-package"
									:title="t('Pick a tender lot to load its items, or add lines by hand.')"
								/>
							</td>
						</tr>
					</tbody>
				</table>
			</div>
			<div class="card-footer d-flex gap-2 flex-wrap align-items-center">
				<button
					type="button"
					class="btn btn-outline-secondary"
					:disabled="saving"
					@click="router.back()"
				>
					{{ t("Cancel") }}
				</button>
				<button
					type="button"
					class="btn btn-primary"
					:disabled="!canCreate"
					:aria-busy="saving"
					@click="create"
				>
					{{ saving ? t("Creating…") : t("Create draft RFQ") }}
				</button>
				<span class="text-secondary small ms-auto">
					{{ t("Stabler creates the draft; sharing it with suppliers stays your act.") }}
				</span>
			</div>
		</div>
	</TenderPage>
</template>
