import assert from "node:assert/strict";
import { createPinia, setActivePinia } from "pinia";

globalThis.window = { __STABLER__: {} };
globalThis.localStorage = {
	getItem() {
		return null;
	},
	setItem() {},
};

let tenderRequestCount = 0;
let deferredTenderResponse = null;
let resolveTenderResponse = null;

function response(message) {
	return {
		ok: true,
		status: 200,
		json: async () => ({ message }),
	};
}

globalThis.fetch = async (url) => {
	if (url.endsWith("stabler.api.organization.switch_company")) {
		return response({ modules: { tender: true } });
	}
	if (url.endsWith("stabler.api.tender.tender_views")) {
		tenderRequestCount += 1;
		if (deferredTenderResponse) return deferredTenderResponse;
		return response({ views: ["sourcing"] });
	}
	throw new Error(`Unexpected request: ${url}`);
};

const { useSession } = await import("../public/js/stores/session.js");

setActivePinia(createPinia());
const session = useSession();
session.roles = ["System Manager"];
session.allowedModules = ["dashboard", "tender"];
session.modules = { tender: false };

assert.equal(
	session.canAccessModule("tender"),
	false,
	"an admin must stay on the financial dashboard when the active company disables tender",
);

session.modules = { tender: true };
assert.equal(
	session.canAccessModule("tender"),
	true,
	"an admin may enter the tender dashboard when the active company enables tender",
);

session.activeCompany = "Alpha";
session.companies = [{ name: "Alpha" }, { name: "Beta" }];
session.tenderViews = ["director"];
session.tenderViewsLoaded = true;

await session.setCompany("Beta");

assert.equal(tenderRequestCount, 1, "switching company must reload tender views");
assert.deepEqual(
	session.tenderViews,
	["sourcing"],
	"the sidebar must receive the new company's tender views without a reload",
);

session.tenderViews = [];
session.tenderViewsLoaded = false;
deferredTenderResponse = new Promise((resolve) => {
	resolveTenderResponse = resolve;
});
const firstLoad = session.ensureTenderViews();
const secondLoad = session.ensureTenderViews();

assert.equal(
	tenderRequestCount,
	2,
	"concurrent tender view loads must share one request",
);

resolveTenderResponse(response({ views: ["logist"] }));
await Promise.all([firstLoad, secondLoad]);
assert.deepEqual(session.tenderViews, ["logist"]);

console.log("tender dashboard company gate behavior: OK");
