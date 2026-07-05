import { useSession } from "../stores/session.js";

/**
 * Activation telemetry — fire-and-forget from the front-end.
 *
 * Every send is non-blocking: `fetch(..., { keepalive: true })` is issued and its
 * promise is never awaited, and all errors are swallowed. So telemetry latency or
 * a network failure can NEVER block, delay, or break the user experience.
 *
 * The backend (api/telemetry.py) stamps the authoritative versioned schema and
 * anonymises the company; the front-end only forwards the event name + PII-free
 * props.
 */

// Keep in sync with SCHEMA_VERSION in api/telemetry.py (backend stamps the real "v").
export const TELEMETRY_SCHEMA_VERSION = 1;

// Activation funnel event names — must match api/telemetry.py FUNNEL_EVENTS.
export const FUNNEL = Object.freeze({
	SIGNUP: "signup",
	WIZARD_DONE: "wizard_done",
	FIRST_ITEM: "first_item",
	FIRST_SALE: "first_sale",
	FIRST_PAYMENT: "first_payment",
});

const CTA_EVENT = "empty_state_cta";
const ENDPOINT = "/api/method/stabler.api.telemetry.track";

function csrfToken() {
	return (window.__STABLER__ || {}).csrfToken || "";
}

/**
 * Fire-and-forget POST. Never awaited by callers, never throws, swallows every
 * error (payload, network, unload). `keepalive` lets it survive navigation; the
 * body is tiny, well under the 64KB keepalive cap.
 */
function send(event, company, props) {
	try {
		if (!event || !company) return;
		const body = new URLSearchParams();
		body.append("event", event);
		body.append("company", company);
		body.append("props", JSON.stringify(props || {}));
		fetch(ENDPOINT, {
			method: "POST",
			credentials: "same-origin",
			keepalive: true,
			headers: {
				"Content-Type": "application/x-www-form-urlencoded",
				"X-Frappe-CSRF-Token": csrfToken(),
			},
			body: body.toString(),
		}).catch(() => {}); // network / server error → ignored, UX unaffected
	} catch (_) {
		// never throw
	}
}

export function useTelemetry() {
	const session = useSession();

	/** Emit an event every time (e.g. CTA clicks handled via trackCta). */
	function track(event, props = {}) {
		send(event, session.activeCompany, props);
	}

	/**
	 * Funnel "first_*" milestones must fire ONCE per company. Guarded in
	 * localStorage so repeated item/sale/payment creation doesn't re-emit. If
	 * storage is unavailable (private mode) the event still fires, just undeduped.
	 */
	function trackOnce(event, props = {}) {
		const company = session.activeCompany;
		if (!company || !event) return;
		const key = `stabler.telemetry.${company}.${event}`;
		try {
			if (localStorage.getItem(key)) return;
			localStorage.setItem(key, "1");
		} catch (_) {
			/* storage blocked — fall through and emit */
		}
		send(event, company, props);
	}

	/** Empty-state CTA click. `cta` identifies which CTA (e.g. "add_first_item"). */
	function trackCta(cta, props = {}) {
		send(CTA_EVENT, session.activeCompany, { cta, ...props });
	}

	return { track, trackOnce, trackCta, FUNNEL };
}
