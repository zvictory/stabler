import assert from "node:assert/strict";
import { createPinia, setActivePinia } from "pinia";

globalThis.window = { __STABLER__: {} };
globalThis.localStorage = {
	getItem() {
		return null;
	},
	setItem() {},
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

console.log("tender dashboard company gate behavior: OK");
