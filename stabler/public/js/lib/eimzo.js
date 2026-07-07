// Thin wrapper around the E-IMZO desktop app's CAPIWS websocket bridge
// (wss://127.0.0.1:64646/service/cryptapi). E-IMZO runs locally on the user's
// machine and holds their personal ЭЦП (PFX) key; the private key never
// leaves the browser/E-IMZO process — this module only relays JSON commands
// over the socket and returns whatever E-IMZO signs (PKCS#7), so the Didox
// submit flow can forward an already-signed envelope to the server.

import { t } from "../composables/i18n.js";

const CAPIWS_URL = "wss://127.0.0.1:64646/service/cryptapi";

function send(plugin, name, args) {
	return new Promise((resolve, reject) => {
		let ws;
		try {
			ws = new WebSocket(CAPIWS_URL);
		} catch {
			reject(new Error(t("E-IMZO is not running. Start the E-IMZO desktop app and try again.")));
			return;
		}
		const timer = setTimeout(() => {
			ws.close();
			reject(new Error(t("E-IMZO did not respond (timeout). Check that the app is running.")));
		}, 15000);
		ws.onopen = () => ws.send(JSON.stringify({ plugin, name, arguments: args }));
		ws.onmessage = (event) => {
			clearTimeout(timer);
			ws.close();
			let data;
			try {
				data = JSON.parse(event.data);
			} catch {
				reject(new Error(t("E-IMZO returned an invalid response")));
				return;
			}
			if (data.success === false) {
				reject(new Error(data.reason || t("E-IMZO error")));
				return;
			}
			resolve(data);
		};
		ws.onerror = () => {
			clearTimeout(timer);
			reject(new Error(t("E-IMZO is not running. Start the E-IMZO desktop app and try again.")));
		};
	});
}

/** True if the local E-IMZO app answers on its CAPIWS port. */
export async function isAvailable() {
	try {
		await send("", "version", []);
		return true;
	} catch {
		return false;
	}
}

/**
 * List certificates (keys) available in E-IMZO, most recent first.
 * @returns {Promise<Array<{id: string, cn: string, tin: string, validFrom: string, validTo: string}>>}
 */
export async function listKeys() {
	const data = await send("pfx", "list_all_certificates", []);
	const items = data.certificates || [];
	return items.map((c, index) => ({
		id: String(index),
		cn: c.CN || c.name || "",
		tin: c.TIN || c.tin || "",
		validFrom: c.validFrom || "",
		validTo: c.validTo || "",
		disk: c.disk,
		path: c.path,
		name: c.name,
		alias: c.alias,
	}));
}

/** Load (unlock) a key by its listKeys() entry; returns an opaque keyId for createPkcs7. */
export async function loadKey(keyEntry) {
	const data = await send("pfx", "load_key", [keyEntry.disk, keyEntry.path, keyEntry.name, keyEntry.alias]);
	return data.keyId;
}

/**
 * Sign base64-encoded data with an already-loaded key.
 * @param {string} keyId - value returned by loadKey()
 * @param {string} dataBase64 - the document payload to sign, base64-encoded
 * @returns {Promise<string>} attached PKCS#7 signature (base64)
 */
export async function createPkcs7(keyId, dataBase64) {
	const data = await send("pkcs7", "create_pkcs7", [dataBase64, keyId, true]);
	return data.pkcs7 || data.pkcs7_64;
}
