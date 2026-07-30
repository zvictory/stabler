function credentialsBody(usr, pwd, remember) {
	const body = new URLSearchParams();
	body.append("usr", usr);
	body.append("pwd", pwd);
	body.append("remember", remember ? "1" : "0");
	return body;
}

function extractServerMessage(payload) {
	let msg = typeof payload.message === "string" ? payload.message : "Invalid username or password.";
	if (payload._server_messages) {
		try {
			const parsed = JSON.parse(payload._server_messages);
			if (Array.isArray(parsed) && parsed.length > 0) {
				const item = typeof parsed[0] === "string" ? JSON.parse(parsed[0]) : parsed[0];
				msg = item.message || msg;
			}
		} catch (_) {
			// ignore JSON parsing errors for server messages
		}
	}
	return msg;
}

export async function login(usr, pwd, remember = true) {
	const response = await fetch("/api/method/stabler.api.organization.stabler_login", {
		method: "POST",
		credentials: "same-origin",
		headers: {
			Accept: "application/json",
			"Content-Type": "application/x-www-form-urlencoded",
		},
		body: credentialsBody(usr, pwd, remember),
	});
	const payload = await response.json().catch(() => ({}));
	if (!response.ok || payload.message?.message !== "Logged In") {
		const msg = extractServerMessage(payload);
		const error = new Error(msg);
		error.response = payload;
		throw error;
	}
	return payload.message;
}

export async function logout() {
	const response = await fetch("/api/method/logout", {
		method: "GET",
		credentials: "same-origin",
		headers: { Accept: "application/json" },
	});
	if (!response.ok) throw new Error("Sign out failed");
}
