<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { call } from "../api/client.js";
import { useSession } from "../stores/session.js";

const router = useRouter();
const session = useSession();

const open = ref(false);
const query = ref("");
const results = ref({ customers: [], suppliers: [], items: [], invoices: [] });
const loading = ref(false);
const highlightedIndex = ref(0);
const inputRef = ref(null);

let debounceTimer = null;
let searchToken = 0;

const QUICK_ACTIONS = [
	{ label: "Dashboard", icon: "ti-layout-dashboard", route: { name: "dashboard" } },
	{ label: "Chart of Accounts", icon: "ti-list-tree", route: { name: "money-accounts" } },
	{ label: "Journal Entries", icon: "ti-book", route: { name: "money-journals" } },
	{ label: "Payments", icon: "ti-cash", route: { name: "money-payments" } },
	{ label: "Reports", icon: "ti-report", route: { name: "money-reports" } },
	{ label: "Customers", icon: "ti-users", route: { name: "sales-customers" } },
	{ label: "Sales Invoices", icon: "ti-file-invoice", route: { name: "sales-invoices" } },
	{ label: "AR Aging", icon: "ti-clock-dollar", route: { name: "sales-aging" } },
	{ label: "Suppliers", icon: "ti-truck", route: { name: "purchasing-suppliers" } },
	{ label: "Purchase Invoices", icon: "ti-receipt", route: { name: "purchasing-invoices" } },
	{ label: "AP Aging", icon: "ti-clock-dollar", route: { name: "purchasing-aging" } },
	{ label: "Items", icon: "ti-package", route: { name: "inventory-items" } },
	{ label: "Warehouses", icon: "ti-building-warehouse", route: { name: "inventory-warehouses" } },
	{ label: "Stock Ledger", icon: "ti-list", route: { name: "inventory-ledger" } },
	{ label: "Low Stock Alerts", icon: "ti-alert-triangle", route: { name: "inventory-alerts" } },
];

const quickActionMatches = computed(() => {
	const q = query.value.trim().toLowerCase();
	if (!q) return QUICK_ACTIONS.slice(0, 6);
	return QUICK_ACTIONS.filter((a) => a.label.toLowerCase().includes(q)).slice(0, 6);
});

const flatItems = computed(() => {
	const items = [];
	for (const action of quickActionMatches.value) {
		items.push({ kind: "action", label: action.label, icon: action.icon, action });
	}
	for (const c of results.value.customers) {
		items.push({
			kind: "customer",
			label: c.title || c.name,
			subtitle: c.subtitle,
			icon: "ti-user",
			route: { name: "sales-customers", query: { focus: c.name } },
		});
	}
	for (const s of results.value.suppliers) {
		items.push({
			kind: "supplier",
			label: s.title || s.name,
			subtitle: s.subtitle,
			icon: "ti-truck",
			route: { name: "purchasing-suppliers", query: { focus: s.name } },
		});
	}
	for (const it of results.value.items) {
		items.push({
			kind: "item",
			label: it.title || it.name,
			subtitle: it.subtitle,
			icon: "ti-package",
			route: { name: "inventory-items", query: { focus: it.name } },
		});
	}
	for (const inv of results.value.invoices) {
		const isSales = inv.doctype === "Sales Invoice";
		items.push({
			kind: isSales ? "sales-invoice" : "purchase-invoice",
			label: inv.name,
			subtitle: inv.subtitle ? `${inv.subtitle} · ${inv.status || ""}` : inv.status || "",
			icon: isSales ? "ti-file-invoice" : "ti-receipt",
			route: {
				name: isSales ? "sales-invoices" : "purchasing-invoices",
				query: { focus: inv.name },
			},
		});
	}
	return items;
});

const groupedView = computed(() => {
	const groups = {
		Actions: [],
		Customers: [],
		Suppliers: [],
		Items: [],
		Invoices: [],
	};
	flatItems.value.forEach((item, idx) => {
		const entry = { ...item, index: idx };
		if (item.kind === "action") groups.Actions.push(entry);
		else if (item.kind === "customer") groups.Customers.push(entry);
		else if (item.kind === "supplier") groups.Suppliers.push(entry);
		else if (item.kind === "item") groups.Items.push(entry);
		else groups.Invoices.push(entry);
	});
	return Object.entries(groups).filter(([, list]) => list.length > 0);
});

function show() {
	open.value = true;
	query.value = "";
	results.value = { customers: [], suppliers: [], items: [], invoices: [] };
	highlightedIndex.value = 0;
	nextTick(() => inputRef.value?.focus());
}

function hide() {
	open.value = false;
	if (debounceTimer) {
		clearTimeout(debounceTimer);
		debounceTimer = null;
	}
}

function activate(item) {
	if (!item) return;
	if (item.kind === "action") {
		router.push(item.action.route);
	} else if (item.route) {
		router.push(item.route);
	}
	hide();
}

watch(query, (val) => {
	if (debounceTimer) clearTimeout(debounceTimer);
	const q = (val || "").trim();
	if (!q) {
		results.value = { customers: [], suppliers: [], items: [], invoices: [] };
		highlightedIndex.value = 0;
		return;
	}
	debounceTimer = setTimeout(async () => {
		const token = ++searchToken;
		loading.value = true;
		try {
			const res = await call("stabler.api.search.palette_search", {
				query: q,
				company: session.activeCompany || "",
				limit_per_kind: 5,
			});
			if (token !== searchToken) return;
			results.value = res || { customers: [], suppliers: [], items: [], invoices: [] };
			highlightedIndex.value = 0;
		} catch {
			if (token === searchToken) {
				results.value = { customers: [], suppliers: [], items: [], invoices: [] };
			}
		} finally {
			if (token === searchToken) loading.value = false;
		}
	}, 200);
});

function onKeydown(e) {
	if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
		e.preventDefault();
		open.value ? hide() : show();
		return;
	}
	if (!open.value) return;
	if (e.key === "Escape") {
		e.preventDefault();
		hide();
	} else if (e.key === "ArrowDown") {
		e.preventDefault();
		const max = flatItems.value.length;
		if (max) highlightedIndex.value = (highlightedIndex.value + 1) % max;
	} else if (e.key === "ArrowUp") {
		e.preventDefault();
		const max = flatItems.value.length;
		if (max) highlightedIndex.value = (highlightedIndex.value - 1 + max) % max;
	} else if (e.key === "Enter") {
		e.preventDefault();
		activate(flatItems.value[highlightedIndex.value]);
	}
}

onMounted(() => window.addEventListener("keydown", onKeydown));
onBeforeUnmount(() => {
	window.removeEventListener("keydown", onKeydown);
	if (debounceTimer) clearTimeout(debounceTimer);
});

defineExpose({ show, hide });
</script>

<template>
	<teleport to="body">
		<div v-if="open" class="modal-backdrop fade show" @click="hide"></div>
		<div
			v-if="open"
			class="modal fade show d-block"
			tabindex="-1"
			role="dialog"
			aria-modal="true"
			@click.self="hide"
		>
			<div class="modal-dialog modal-dialog-centered modal-dialog-scrollable" role="document">
				<div class="modal-content">
					<div class="modal-header py-2">
						<i class="ti ti-search me-2 text-muted"></i>
						<input
							ref="inputRef"
							v-model="query"
							type="text"
							class="form-control form-control-flush border-0"
							placeholder="Search customers, suppliers, items, invoices…"
							autocomplete="off"
							spellcheck="false"
						/>
						<span class="text-muted small ms-2 d-none d-sm-inline">esc</span>
					</div>
					<div class="modal-body p-0" style="max-height: 60vh; overflow-y: auto;">
						<div v-if="loading" class="px-3 py-2 text-muted small">Searching…</div>
						<div v-if="!flatItems.length && !loading" class="px-3 py-4 text-center text-muted">
							<i class="ti ti-mood-empty fs-2 d-block mb-2"></i>
							<div v-if="query.trim()">No results for "{{ query }}"</div>
							<div v-else>Type to search, or pick a quick action</div>
						</div>
						<div v-for="[groupLabel, entries] in groupedView" :key="groupLabel">
							<div class="px-3 py-1 text-uppercase text-muted small bg-light border-bottom">
								{{ groupLabel }}
							</div>
							<button
								v-for="entry in entries"
								:key="`${entry.kind}-${entry.index}`"
								type="button"
								class="palette-item w-100 d-flex align-items-center px-3 py-2 border-0 bg-transparent text-start"
								:class="{ 'palette-item-active': entry.index === highlightedIndex }"
								@mouseenter="highlightedIndex = entry.index"
								@click="activate(entry)"
							>
								<i class="ti me-3 fs-3 text-muted" :class="entry.icon"></i>
								<div class="flex-fill text-truncate">
									<div class="text-truncate">{{ entry.label }}</div>
									<div v-if="entry.subtitle" class="text-muted small text-truncate">
										{{ entry.subtitle }}
									</div>
								</div>
								<i class="ti ti-corner-down-left text-muted ms-2" v-if="entry.index === highlightedIndex"></i>
							</button>
						</div>
					</div>
					<div class="modal-footer py-2 text-muted small justify-content-between">
						<div>
							<kbd>↑</kbd> <kbd>↓</kbd> navigate · <kbd>↵</kbd> open · <kbd>esc</kbd> close
						</div>
						<div><kbd>⌘</kbd> <kbd>K</kbd></div>
					</div>
				</div>
			</div>
		</div>
	</teleport>
</template>

<style scoped>
.palette-item {
	transition: background-color 0.1s ease;
}
.palette-item-active {
	background-color: var(--tblr-primary-lt, #e7f0fb);
}
.form-control-flush:focus {
	box-shadow: none;
	outline: none;
}
</style>
