import { ref } from "vue";
import { useRouter } from "vue-router";
import { call } from "../api/client.js";
import { t } from "./i18n.js";

// One source of truth for "open the source voucher behind a ledger/report row".
// Journal & Payment entries open in-place in a VoucherDrawer (detail loaded here);
// everything else routes to its module page with ?open=<name>. Pass `routes` to
// extend/override the document → path map for a specific ledger.
//
//   const drill = useVoucherDrill();
//   drill.canOpen(entry)        // is this voucher clickable?
//   drill.openVoucher(entry)    // open drawer or route
//   <VoucherDrawer :open="drill.open" :loading="drill.loading"
//                  :detail="drill.detail" :currency="cur" @close="drill.close" />
const DRAWER_TYPES = new Set(["Journal Entry", "Payment Entry"]);
const DEFAULT_ROUTES = {
	"Sales Invoice": "/sales/invoices",
	"Purchase Invoice": "/purchasing/invoices",
	"Stock Entry": "/inventory/entries",
	"Purchase Receipt": "/purchasing/receipts",
};

export function useVoucherDrill(options = {}) {
	const router = useRouter();
	const routes = { ...DEFAULT_ROUTES, ...(options.routes || {}) };

	const open = ref(false);
	const loading = ref(false);
	const detail = ref(null);

	function canOpen(entry) {
		const vt = entry?.voucher_type;
		return DRAWER_TYPES.has(vt) || !!routes[vt];
	}

	async function openVoucher(entry) {
		const vt = entry?.voucher_type;
		const no = entry?.voucher_no;
		if (!vt || !no) return;
		if (DRAWER_TYPES.has(vt)) {
			open.value = true;
			loading.value = true;
			detail.value = null;
			const method =
				vt === "Journal Entry"
					? "stabler.api.money.journal_entry_detail"
					: "stabler.api.money.payment_entry_detail";
			try {
				detail.value = await call(method, { name: no });
			} catch (err) {
				detail.value = { error: err?.message || t("Failed to load.") };
			} finally {
				loading.value = false;
			}
			return;
		}
		const path = routes[vt];
		if (path) router.push({ path, query: { open: no } });
	}

	function close() {
		open.value = false;
		detail.value = null;
	}

	return { open, loading, detail, canOpen, openVoucher, close };
}
