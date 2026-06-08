<script setup>
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../stores/session.js";
import { call } from "../api/client.js";
import { formatMoney } from "../composables/money.js";
import { t } from "../composables/i18n.js";
import Select from "../components/Select.vue";

const session = useSession();
const router = useRouter();
const { activeCompany, user } = storeToRefs(session);

const searchInput = ref(null);
const profiles = ref([]);
const selectedProfile = ref("");
const profile = ref(null);
const paymentMode = ref("");
const profileLoading = ref(false);
const profileError = ref("");

const search = ref("");
const selectedCategory = ref("all");
const searchLoading = ref(false);
const searchError = ref("");
const itemResults = ref([]);
const cart = ref([]);
const checkoutRunning = ref(false);
const checkoutError = ref("");
const lastInvoice = ref(null);

const currency = computed(() => profile.value?.currency || session.currency);
const language = computed(() => user.value?.language || "en");
const cashierName = computed(() => user.value?.full_name || user.value?.email || t("Cashier"));
const profileOptions = computed(() =>
	profiles.value.map((p) => ({
		value: p.name,
		label: `${p.name}${p.warehouse ? ` · ${p.warehouse}` : ""}`,
	}))
);
const paymentOptions = computed(() =>
	(profile.value?.payments || []).map((p) => ({
		value: p.mode_of_payment,
		label: p.mode_of_payment,
	}))
);
const cartTotal = computed(() =>
	cart.value.reduce((sum, item) => sum + Number(item.qty || 0) * Number(item.rate || 0), 0)
);
const cartUnits = computed(() => cart.value.reduce((sum, item) => sum + Number(item.qty || 0), 0));
const canCheckout = computed(
	() =>
		!!profile.value &&
		!!paymentMode.value &&
		cart.value.length > 0 &&
		cart.value.every((item) => Number(item.qty || 0) > 0 && Number(item.qty || 0) <= Number(item.available_qty || 0)) &&
		!checkoutRunning.value
);
const categoryChips = computed(() => {
	const seen = new Map([["all", { key: "all", label: t("All"), tone: "neutral" }]]);
	for (const item of itemResults.value) {
		const category = categoryForItem(item);
		if (!seen.has(category.key)) seen.set(category.key, category);
	}
	return [...seen.values()];
});
const filteredItems = computed(() => {
	if (selectedCategory.value === "all") return itemResults.value;
	return itemResults.value.filter((item) => categoryForItem(item).key === selectedCategory.value);
});
const cashTenderOptions = computed(() => {
	const total = Number(cartTotal.value || 0);
	if (!total) return [];
	const denominations = [10000, 20000, 50000, 100000, 200000];
	const rounded = denominations.filter((amount) => amount >= total).slice(0, 3);
	return [
		{ key: "exact", label: t("Exact"), amount: total },
		...rounded.map((amount) => ({ key: `cash-${amount}`, label: formatMoney(amount, currency.value, language.value), amount })),
	];
});

function categoryForItem(item) {
	const text = `${item.item_name || ""} ${item.item_code || ""}`.toLowerCase();
	if (text.includes("choco") || text.includes("chocolate")) return { key: "chocolate", label: t("Chocolate"), tone: "cocoa" };
	if (text.includes("klub") || text.includes("straw")) return { key: "berry", label: t("Berry"), tone: "berry" };
	if (text.includes("pista") || text.includes("pistachio")) return { key: "pistachio", label: t("Pistachio"), tone: "pistachio" };
	if (text.includes("premium") || text.includes("oila")) return { key: "premium", label: t("Premium"), tone: "premium" };
	return { key: "classic", label: t("Classic"), tone: "classic" };
}

function itemCardClass(item) {
	const category = categoryForItem(item);
	return [`pos-item-card`, `pos-item-card--${category.tone}`, { "is-empty": Number(item.available_qty || 0) <= 0 }];
}

function focusSearch() {
	nextTick(() => searchInput.value?.focus());
}

async function loadProfiles() {
	if (!activeCompany.value) return;
	profileLoading.value = true;
	profileError.value = "";
	profiles.value = [];
	profile.value = null;
	selectedProfile.value = "";
	paymentMode.value = "";
	try {
		profiles.value = await call("stabler.api.pos.list_pos_profiles", {
			company: activeCompany.value,
		});
		if (profiles.value.length === 1) {
			selectedProfile.value = profiles.value[0].name;
			await loadProfile();
		}
	} catch (err) {
		profileError.value = err?.message || t("Failed to load POS profiles.");
	} finally {
		profileLoading.value = false;
		focusSearch();
	}
}

async function loadProfile() {
	if (!activeCompany.value || !selectedProfile.value) {
		profile.value = null;
		paymentMode.value = "";
		return;
	}
	profileLoading.value = true;
	profileError.value = "";
	checkoutError.value = "";
	lastInvoice.value = null;
	try {
		profile.value = await call("stabler.api.pos.pos_bootstrap", {
			company: activeCompany.value,
			pos_profile: selectedProfile.value,
		});
		paymentMode.value = profile.value.default_payment_mode || profile.value.payments?.[0]?.mode_of_payment || "";
		cart.value = [];
		itemResults.value = [];
		search.value = "";
		selectedCategory.value = "all";
		await searchItems();
	} catch (err) {
		profile.value = null;
		paymentMode.value = "";
		profileError.value = err?.message || t("Failed to load POS profile.");
	} finally {
		profileLoading.value = false;
		focusSearch();
	}
}

let searchTimer = null;
function scheduleSearch() {
	clearTimeout(searchTimer);
	searchTimer = setTimeout(searchItems, 180);
}

async function searchItems() {
	if (!profile.value || !activeCompany.value) return;
	searchLoading.value = true;
	searchError.value = "";
	try {
		itemResults.value = await call("stabler.api.pos.search_pos_items", {
			company: activeCompany.value,
			pos_profile: profile.value.name,
			search: search.value,
			limit: 48,
		});
	} catch (err) {
		searchError.value = err?.message || t("Failed to search items.");
		itemResults.value = [];
	} finally {
		searchLoading.value = false;
	}
}

function addItem(item) {
	if (Number(item.available_qty || 0) <= 0) return;
	const existing = cart.value.find((row) => row.item_code === item.item_code);
	if (existing) {
		existing.qty = Math.min(Number(existing.available_qty || 0), Number(existing.qty || 0) + 1);
		return;
	}
	cart.value.push({
		item_code: item.item_code,
		item_name: item.item_name,
		stock_uom: item.stock_uom,
		available_qty: Number(item.available_qty || 0),
		rate: Number(item.rate || 0),
		qty: 1,
	});
}

function removeItem(itemCode) {
	cart.value = cart.value.filter((item) => item.item_code !== itemCode);
}

function setQty(item, value) {
	const qty = Number(value || 0);
	item.qty = Math.max(0, Math.min(qty, Number(item.available_qty || 0)));
	if (item.qty === 0) removeItem(item.item_code);
}

function incrementQty(item) {
	setQty(item, Number(item.qty || 0) + 1);
}

function decrementQty(item) {
	setQty(item, Number(item.qty || 0) - 1);
}

async function checkout() {
	if (!canCheckout.value) return;
	checkoutRunning.value = true;
	checkoutError.value = "";
	lastInvoice.value = null;
	try {
		const invoice = await call("stabler.api.pos.create_pos_invoice", {
			company: activeCompany.value,
			pos_profile: profile.value.name,
			items: cart.value.map((item) => ({ item_code: item.item_code, qty: item.qty })),
			payment_mode: paymentMode.value,
		});
		lastInvoice.value = invoice;
		cart.value = [];
		await searchItems();
	} catch (err) {
		checkoutError.value = err?.message || t("Checkout failed.");
	} finally {
		checkoutRunning.value = false;
		focusSearch();
	}
}

function openInvoice() {
	if (lastInvoice.value?.name) router.push(`/sales/invoices/${lastInvoice.value.name}`);
}

watch(activeCompany, loadProfiles);
watch(selectedProfile, loadProfile);

onMounted(loadProfiles);
</script>

<template>
	<div class="page-header d-print-none">
		<div class="container-fluid">
			<div class="row g-2 align-items-center">
				<div class="col">
					<div class="page-pretitle">{{ t("Retail") }}</div>
					<h2 class="page-title d-flex align-items-center gap-2">
						<i class="ti ti-building-store"></i>{{ t("POS") }}
					</h2>
				</div>
				<div class="col-auto text-secondary small">
					{{ profile?.warehouse || t("Select POS Profile") }}
				</div>
			</div>
		</div>
	</div>

	<div class="page-body pt-3">
		<div class="container-fluid">
			<div class="ice-pos-shell">
		<aside class="ice-pos-control card" aria-label="Cashier controls">
			<section class="ice-pos-shift">
				<div class="ice-pos-kicker">{{ t("Shift") }}</div>
				<div class="ice-pos-shift-status">
					<span class="ice-pos-status-dot"></span>
					<span>{{ t("Open") }}</span>
				</div>
				<div class="ice-pos-cashier">{{ cashierName }}</div>
			</section>

			<section class="ice-pos-control-group">
				<div class="ice-pos-kicker">{{ t("Profile") }}</div>
				<Select
					v-model="selectedProfile"
					:options="profileOptions"
					:disabled="profileLoading"
					:placeholder="t('POS Profile')"
				/>
				<div v-if="profile" class="ice-pos-meta">
					<div>{{ profile.customer }}</div>
					<div>{{ profile.warehouse }}</div>
				</div>
			</section>

			<section class="ice-pos-control-group">
				<div class="ice-pos-kicker">{{ t("Actions") }}</div>
				<button type="button" class="ice-pos-key btn btn-outline-secondary" @click="focusSearch">
					<i class="ti ti-barcode"></i>
					<span>{{ t("Scan") }}</span>
				</button>
				<button type="button" class="ice-pos-key btn btn-outline-secondary" :disabled="!cart.length" @click="cart = []">
					<i class="ti ti-receipt-off"></i>
					<span>{{ t("Void Cart") }}</span>
				</button>
				<button type="button" class="ice-pos-key btn btn-outline-secondary" @click="searchItems">
					<i class="ti ti-refresh"></i>
					<span>{{ t("Refresh") }}</span>
				</button>
			</section>

			<section class="ice-pos-control-group mt-auto">
				<div class="ice-pos-kicker">{{ t("Lock") }}</div>
				<button type="button" class="ice-pos-lock btn btn-light">
					<i class="ti ti-lock"></i>
					<span>{{ t("Cashier Lock") }}</span>
				</button>
			</section>
		</aside>

		<main class="ice-pos-products card">
			<header class="ice-pos-searchbar">
				<div class="ice-pos-search-wrap">
					<i class="ti ti-search"></i>
					<input
						ref="searchInput"
						v-model="search"
						type="search"
						:placeholder="t('Scan barcode or search packaged ice cream')"
						:disabled="!profile"
						autofocus
						@input="scheduleSearch"
						@focus="searchItems"
					/>
				</div>
				<div class="ice-pos-search-state">
					<span v-if="searchLoading">{{ t("Loading") }}</span>
					<span v-else>{{ filteredItems.length }} {{ t("items") }}</span>
				</div>
			</header>

			<div v-if="profileError" class="alert alert-danger mb-3">{{ profileError }}</div>
			<div v-if="searchError" class="alert alert-danger mb-3">{{ searchError }}</div>

			<nav class="ice-pos-categories" aria-label="Product categories">
				<button
					v-for="category in categoryChips"
					:key="category.key"
					type="button"
					class="ice-pos-chip btn"
					:class="[`ice-pos-chip--${category.tone}`, { active: selectedCategory === category.key }]"
					@click="selectedCategory = category.key"
				>
					{{ category.label }}
				</button>
			</nav>

			<section class="ice-pos-grid" aria-label="Product grid">
				<button
					v-for="item in filteredItems"
					:key="item.item_code"
					type="button"
					:class="itemCardClass(item)"
					:disabled="Number(item.available_qty || 0) <= 0"
					@click="addItem(item)"
				>
					<span class="ice-pos-card-marker"></span>
					<span class="ice-pos-card-stock">{{ item.available_qty }} {{ item.stock_uom }}</span>
					<span class="ice-pos-card-name">{{ item.item_name || item.item_code }}</span>
					<span class="ice-pos-card-code">{{ item.item_code }}</span>
					<span class="ice-pos-card-price">{{ formatMoney(item.rate, currency, language) }}</span>
				</button>

				<div v-if="profile && !filteredItems.length && !searchLoading" class="ice-pos-empty">
					<i class="ti ti-package-off"></i>
					<strong>{{ t("No stocked items found") }}</strong>
					<span>{{ t("Only items with available stock in this POS warehouse appear here.") }}</span>
				</div>

				<div v-if="!profile && !profileLoading" class="ice-pos-empty">
					<i class="ti ti-building-store"></i>
					<strong>{{ t("Select a POS Profile") }}</strong>
					<span>{{ t("Choose the retail shop warehouse before selling.") }}</span>
				</div>
			</section>
		</main>

		<aside class="ice-pos-ledger card" aria-label="Sale ledger">
			<header class="ice-pos-ledger-head">
				<div>
					<div class="ice-pos-kicker">{{ t("Current Sale") }}</div>
					<h2>{{ cartUnits }} {{ t("units") }}</h2>
				</div>
				<span class="ice-pos-ledger-count">{{ cart.length }}</span>
			</header>

			<section class="ice-pos-lines">
				<div v-if="!cart.length" class="ice-pos-ledger-empty">
					{{ t("Scan or tap products to build the sale.") }}
				</div>

				<article v-for="item in cart" :key="item.item_code" class="ice-pos-line">
					<div class="ice-pos-line-main">
						<strong>{{ item.item_name || item.item_code }}</strong>
						<span>{{ formatMoney(item.rate, currency, language) }} · {{ item.available_qty }} {{ item.stock_uom }}</span>
					</div>
					<div class="ice-pos-qty">
						<button type="button" @click="decrementQty(item)" aria-label="Decrease quantity">
							<i class="ti ti-minus"></i>
						</button>
						<input
							type="number"
							min="1"
							:max="item.available_qty"
							step="1"
							:value="item.qty"
							@input="setQty(item, $event.target.value)"
						/>
						<button type="button" @click="incrementQty(item)" aria-label="Increase quantity">
							<i class="ti ti-plus"></i>
						</button>
					</div>
					<button type="button" class="ice-pos-line-remove" @click="removeItem(item.item_code)">
						<i class="ti ti-trash"></i>
					</button>
				</article>
			</section>

			<footer class="ice-pos-summary">
				<label class="ice-pos-payment-mode">
					<span>{{ t("Payment Mode") }}</span>
					<Select
						v-model="paymentMode"
						:options="paymentOptions"
						:disabled="!profile || checkoutRunning"
						:placeholder="t('Select payment')"
					/>
				</label>

				<div class="ice-pos-total-row">
					<span>{{ t("Total") }}</span>
					<strong>{{ formatMoney(cartTotal, currency, language) }}</strong>
				</div>

				<div v-if="checkoutError" class="alert alert-danger mb-2">{{ checkoutError }}</div>
				<div v-if="lastInvoice" class="alert alert-success mb-2">
					<button type="button" class="btn btn-link p-0 text-success" @click="openInvoice">
						{{ t("Sale completed") }} · {{ lastInvoice.name }}
					</button>
				</div>

				<div class="ice-pos-tenders">
					<button
						v-for="tender in cashTenderOptions"
						:key="tender.key"
						type="button"
						class="ice-pos-tender"
						:disabled="!canCheckout"
						@click="checkout"
					>
						<span>{{ tender.label }}</span>
						<strong v-if="tender.amount > cartTotal">
							{{ t("Change") }} {{ formatMoney(tender.amount - cartTotal, currency, language) }}
						</strong>
					</button>
					<button type="button" class="ice-pos-tender ice-pos-tender--primary" :disabled="!canCheckout" @click="checkout">
						<i v-if="!checkoutRunning" class="ti ti-cash"></i>
						<span v-else class="spinner-border spinner-border-sm"></span>
						{{ t("Take Payment") }}
					</button>
				</div>
			</footer>
		</aside>
			</div>
		</div>
	</div>
</template>

<style scoped>
.ice-pos-shell {
	display: grid;
	grid-template-columns: 15% 50% 35%;
	min-height: calc(100dvh - 7rem);
	gap: 1rem;
}

.ice-pos-control,
.ice-pos-products,
.ice-pos-ledger {
	min-width: 0;
}

.ice-pos-control {
	display: flex;
	flex-direction: column;
	gap: 1rem;
	padding: 1rem;
	background: var(--tblr-card-bg, #ffffff);
	color: var(--tblr-body-color, #1f2937);
	border-color: var(--tblr-border-color, #dadfe5);
}

.ice-pos-kicker {
	color: var(--tblr-secondary, #667382);
	font-size: 0.68rem;
	font-weight: 700;
	letter-spacing: 0.08em;
	text-transform: uppercase;
}

.ice-pos-shift,
.ice-pos-control-group {
	display: grid;
	gap: 0.65rem;
}

.ice-pos-shift-status {
	display: flex;
	align-items: center;
	gap: 0.45rem;
	font-size: 1.05rem;
	font-weight: 700;
}

.ice-pos-status-dot {
	width: 0.75rem;
	height: 0.75rem;
	border-radius: 999px;
	background: var(--tblr-success, #2fb344);
	box-shadow: 0 0 0 0.35rem rgba(47, 179, 68, 0.12);
}

.ice-pos-cashier,
.ice-pos-meta {
	color: var(--tblr-secondary, #667382);
	font-size: 0.82rem;
	line-height: 1.35;
}

.ice-pos-key,
.ice-pos-lock {
	display: flex;
	min-height: 56px;
	width: 100%;
	align-items: center;
	gap: 0.65rem;
	justify-content: flex-start;
	font-weight: 700;
	padding: 0 0.75rem;
}

.ice-pos-key:disabled {
	opacity: 0.45;
}

.ice-pos-products {
	padding: 1rem;
	overflow: auto;
}

.ice-pos-searchbar {
	display: grid;
	grid-template-columns: minmax(0, 1fr) auto;
	gap: 0.75rem;
	align-items: center;
	margin-bottom: 0.85rem;
}

.ice-pos-search-wrap {
	display: flex;
	min-height: 64px;
	align-items: center;
	gap: 0.75rem;
	border: 1px solid var(--tblr-border-color, #dadfe5);
	border-radius: var(--tblr-border-radius, 4px);
	background: var(--tblr-bg-surface, #ffffff);
	padding: 0 1rem;
}

.ice-pos-search-wrap input {
	width: 100%;
	border: 0;
	outline: 0;
	font-size: 1.05rem;
	font-weight: 600;
}

.ice-pos-search-state {
	font-size: 0.8rem;
	font-weight: 700;
	color: var(--tblr-secondary, #667382);
	text-transform: uppercase;
}

.ice-pos-categories {
	display: flex;
	gap: 0.5rem;
	margin-bottom: 1rem;
	overflow-x: auto;
	padding-bottom: 0.25rem;
}

.ice-pos-chip {
	min-height: 48px;
	font-weight: 800;
	padding: 0 1rem;
	white-space: nowrap;
}

.ice-pos-chip.active {
	border-color: var(--tblr-primary, #206bc4);
	color: var(--tblr-primary, #206bc4);
	background: rgba(32, 107, 196, 0.06);
	box-shadow: inset 0 -3px 0 var(--tblr-primary, #206bc4);
}

.ice-pos-grid {
	display: grid;
	grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
	gap: 0.75rem;
}

.pos-item-card {
	position: relative;
	display: grid;
	min-height: 148px;
	align-content: space-between;
	text-align: left;
	border: 1px solid var(--tblr-border-color, #dadfe5);
	border-radius: var(--tblr-border-radius, 4px);
	background: var(--tblr-card-bg, #ffffff);
	color: var(--tblr-body-color, #1f2937);
	padding: 0.85rem;
	transition: transform 120ms ease, border-color 120ms ease;
}

.pos-item-card:hover:not(:disabled) {
	border-color: rgba(32, 107, 196, 0.45);
}

.pos-item-card:active {
	transform: scale(0.98);
}

.pos-item-card:disabled {
	cursor: not-allowed;
}

.pos-item-card.is-empty {
	opacity: 0.42;
	filter: grayscale(0.85);
}

.ice-pos-card-marker {
	position: absolute;
	inset: 0 auto 0 0;
	width: 7px;
	background: #94a3b8;
}

.pos-item-card--cocoa .ice-pos-card-marker {
	background: #7c3f2c;
}

.pos-item-card--berry .ice-pos-card-marker {
	background: #c02654;
}

.pos-item-card--pistachio .ice-pos-card-marker {
	background: #4d7c0f;
}

.pos-item-card--premium .ice-pos-card-marker {
	background: #a16207;
}

.pos-item-card--classic .ice-pos-card-marker {
	background: #0284c7;
}

.ice-pos-card-stock {
	justify-self: end;
	border: 1px solid rgba(32, 107, 196, 0.18);
	border-radius: 999px;
	background: rgba(32, 107, 196, 0.08);
	color: var(--tblr-primary, #206bc4);
	font-size: 0.75rem;
	font-weight: 900;
	padding: 0.2rem 0.45rem;
}

.ice-pos-card-name {
	display: -webkit-box;
	-webkit-box-orient: vertical;
	-webkit-line-clamp: 2;
	overflow: hidden;
	font-size: 0.98rem;
	font-weight: 850;
	line-height: 1.15;
}

.ice-pos-card-code,
.ice-pos-card-price {
	color: var(--tblr-secondary, #667382);
	font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
	font-size: 0.8rem;
}

.ice-pos-card-price {
	color: var(--tblr-body-color, #1f2937);
	font-size: 1rem;
	font-weight: 900;
}

.ice-pos-empty {
	display: grid;
	min-height: 220px;
	place-items: center;
	grid-column: 1 / -1;
	align-content: center;
	gap: 0.45rem;
	border: 1px dashed var(--tblr-border-color, #dadfe5);
	border-radius: var(--tblr-border-radius, 4px);
	background: var(--tblr-card-bg, #ffffff);
	color: var(--tblr-secondary, #667382);
	text-align: center;
}

.ice-pos-empty i {
	font-size: 2rem;
}

.ice-pos-ledger {
	display: grid;
	grid-template-rows: auto minmax(0, 1fr) auto;
	background: var(--tblr-card-bg, #ffffff);
}

.ice-pos-ledger-head {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 1rem;
	border-bottom: 1px solid var(--tblr-border-color, #dadfe5);
}

.ice-pos-ledger-head h2 {
	margin: 0.1rem 0 0;
	font-size: 1.35rem;
	font-weight: 900;
}

.ice-pos-ledger-count {
	display: grid;
	min-width: 48px;
	min-height: 48px;
	place-items: center;
	border: 1px solid rgba(32, 107, 196, 0.22);
	border-radius: var(--tblr-border-radius, 4px);
	background: rgba(32, 107, 196, 0.06);
	color: var(--tblr-primary, #206bc4);
	font-size: 1.1rem;
	font-weight: 900;
}

.ice-pos-lines {
	overflow: auto;
	padding: 0.75rem 1rem;
}

.ice-pos-ledger-empty {
	color: var(--tblr-secondary, #667382);
	font-weight: 700;
	padding: 1rem 0;
}

.ice-pos-line {
	display: grid;
	grid-template-columns: minmax(0, 1fr) auto auto;
	gap: 0.6rem;
	align-items: center;
	border-bottom: 1px solid var(--tblr-border-color, #e6e9ef);
	padding: 0.75rem 0;
}

.ice-pos-line-main {
	display: grid;
	gap: 0.15rem;
	min-width: 0;
}

.ice-pos-line-main strong {
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}

.ice-pos-line-main span {
	color: var(--tblr-secondary, #667382);
	font-size: 0.78rem;
}

.ice-pos-qty {
	display: grid;
	grid-template-columns: 48px 54px 48px;
	align-items: center;
	border: 1px solid var(--tblr-border-color, #dadfe5);
	border-radius: var(--tblr-border-radius, 4px);
	overflow: hidden;
}

.ice-pos-qty button,
.ice-pos-line-remove {
	min-width: 48px;
	min-height: 48px;
	border: 0;
	background: var(--tblr-bg-surface-secondary, #f6f8fb);
	color: var(--tblr-body-color, #1f2937);
	font-weight: 900;
}

.ice-pos-qty input {
	width: 54px;
	height: 48px;
	border: 0;
	border-left: 1px solid var(--tblr-border-color, #dadfe5);
	border-right: 1px solid var(--tblr-border-color, #dadfe5);
	text-align: center;
	font-weight: 900;
}

.ice-pos-line-remove {
	background: rgba(214, 57, 57, 0.08);
	color: var(--tblr-danger, #d63939);
}

.ice-pos-summary {
	position: sticky;
	bottom: 0;
	display: grid;
	gap: 0.75rem;
	border-top: 1px solid var(--tblr-border-color, #dadfe5);
	background: var(--tblr-card-bg, #ffffff);
	padding: 1rem;
}

.ice-pos-payment-mode {
	display: grid;
	gap: 0.35rem;
	font-weight: 800;
}

.ice-pos-total-row {
	display: flex;
	align-items: end;
	justify-content: space-between;
	gap: 1rem;
}

.ice-pos-total-row span {
	color: var(--tblr-secondary, #667382);
	font-weight: 800;
	text-transform: uppercase;
}

.ice-pos-total-row strong {
	color: var(--tblr-body-color, #1f2937);
	font-size: clamp(1.6rem, 3vw, 2.6rem);
	font-weight: 950;
	line-height: 1;
}

.ice-pos-tenders {
	display: grid;
	grid-template-columns: repeat(2, minmax(0, 1fr));
	gap: 0.5rem;
}

.ice-pos-tender {
	display: grid;
	min-height: 64px;
	align-content: center;
	border: 1px solid var(--tblr-border-color, #dadfe5);
	border-radius: var(--tblr-border-radius, 4px);
	background: var(--tblr-card-bg, #ffffff);
	color: var(--tblr-body-color, #1f2937);
	font-size: 0.95rem;
	font-weight: 900;
	text-align: left;
	padding: 0.55rem 0.75rem;
}

.ice-pos-tender strong {
	color: var(--tblr-secondary, #667382);
	font-size: 0.72rem;
}

.ice-pos-tender--primary {
	grid-column: 1 / -1;
	min-height: 76px;
	align-items: center;
	border-color: var(--tblr-primary, #206bc4);
	background: var(--tblr-primary, #206bc4);
	color: #ffffff;
	font-size: 1.15rem;
	text-align: center;
}

.ice-pos-tender:disabled {
	opacity: 0.45;
}

@media (max-width: 1100px) {
	.ice-pos-shell {
		grid-template-columns: 1fr;
	}

	.ice-pos-control,
	.ice-pos-ledger {
		min-height: auto;
	}
}
</style>
