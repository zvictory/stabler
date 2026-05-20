const boot = window.__STABLER__ || {};

function encodeForm(args) {
	const params = new URLSearchParams();
	for (const [key, value] of Object.entries(args || {})) {
		if (value === undefined || value === null) continue;
		if (typeof value === "object") {
			params.append(key, JSON.stringify(value));
		} else {
			params.append(key, String(value));
		}
	}
	return params.toString();
}

/**
 * Call a whitelisted Frappe method.
 * `name` is the dotted path (e.g. "stabler.api.dashboard.summary").
 * Frappe wraps the return value in {message: ...}; we unwrap to the payload.
 */
export async function call(name, args = {}) {
	const res = await fetch(`/api/method/${name}`, {
		method: "POST",
		credentials: "same-origin",
		headers: {
			Accept: "application/json",
			"Content-Type": "application/x-www-form-urlencoded",
			"X-Frappe-CSRF-Token": boot.csrfToken || "",
		},
		body: encodeForm(args),
	});

	if (res.status === 403) {
		window.dispatchEvent(new CustomEvent("stabler:forbidden", { detail: res }));
	}

	let data = null;
	try {
		data = await res.json();
	} catch {
		/* non-JSON error body */
	}

	if (!res.ok) {
		const err = new Error(
			(data && (data.exception || data._error_message || data.message)) ||
				`Request failed: ${res.status}`
		);
		err.status = res.status;
		err.response = data;
		throw err;
	}

	return data && Object.prototype.hasOwnProperty.call(data, "message") ? data.message : data;
}

/**
 * Call a whitelisted method that writes a binary file to frappe.response
 * (e.g. export_query) and trigger a browser download.
 * Returns the filename used for the download.
 */
export async function download(name, args = {}, fallbackFilename = "download") {
	const res = await fetch(`/api/method/${name}`, {
		method: "POST",
		credentials: "same-origin",
		headers: {
			"Content-Type": "application/x-www-form-urlencoded",
			"X-Frappe-CSRF-Token": boot.csrfToken || "",
		},
		body: encodeForm(args),
	});

	if (res.status === 403) {
		window.dispatchEvent(new CustomEvent("stabler:forbidden", { detail: res }));
	}

	if (!res.ok) {
		let msg = `Request failed: ${res.status}`;
		try {
			const data = await res.json();
			msg = data?.exception || data?._error_message || data?.message || msg;
		} catch {
			/* non-JSON */
		}
		const err = new Error(msg);
		err.status = res.status;
		throw err;
	}

	const disposition = res.headers.get("Content-Disposition") || "";
	const match = disposition.match(/filename\*?=(?:UTF-8'')?["']?([^"';]+)["']?/i);
	const filename = match ? decodeURIComponent(match[1]) : fallbackFilename;

	const blob = await res.blob();
	const url = URL.createObjectURL(blob);
	const a = document.createElement("a");
	a.href = url;
	a.download = filename;
	document.body.appendChild(a);
	a.click();
	a.remove();
	setTimeout(() => URL.revokeObjectURL(url), 1000);
	return filename;
}
