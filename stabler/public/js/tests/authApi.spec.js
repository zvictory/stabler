import { afterEach, describe, expect, it, vi } from "vitest";
import { login, logout } from "../api/auth.js";

afterEach(() => {
	vi.unstubAllGlobals();
});

describe("auth API", () => {
	it("posts credentials to Frappe login with same-origin cookies", async () => {
		const fetch = vi.fn().mockResolvedValue({
			ok: true,
			json: async () => ({ message: "Logged In" }),
		});
		vi.stubGlobal("fetch", fetch);

		await login("user@example.com", "secret");

		expect(fetch).toHaveBeenCalledWith("/api/method/login", expect.objectContaining({
			method: "POST",
			credentials: "same-origin",
		}));
		expect(fetch.mock.calls[0][1].body.toString()).toBe("usr=user%40example.com&pwd=secret");
	});

	it("uses the documented GET logout endpoint", async () => {
		const fetch = vi.fn().mockResolvedValue({ ok: true });
		vi.stubGlobal("fetch", fetch);

		await logout();

		expect(fetch).toHaveBeenCalledWith("/api/method/logout", {
			method: "GET",
			credentials: "same-origin",
			headers: { Accept: "application/json" },
		});
	});

	it("rejects failed logout instead of pretending the session ended", async () => {
		vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500 }));
		await expect(logout()).rejects.toThrow("Sign out failed");
	});
});
