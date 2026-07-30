import { afterEach, describe, expect, it, vi } from "vitest";
import { login, logout } from "../api/auth.js";

afterEach(() => {
	vi.unstubAllGlobals();
});

describe("auth API", () => {
	it("posts credentials and the remember flag to stabler_login", async () => {
		// The stock /api/method/login cannot vary the sid cookie lifetime, so
		// "Remember me" only works if every login goes through stabler_login
		// carrying the flag.
		const fetch = vi.fn().mockResolvedValue({
			ok: true,
			json: async () => ({ message: { message: "Logged In" } }),
		});
		vi.stubGlobal("fetch", fetch);

		await login("user@example.com", "secret", false);

		expect(fetch).toHaveBeenCalledWith(
			"/api/method/stabler.api.organization.stabler_login",
			expect.objectContaining({
				method: "POST",
				credentials: "same-origin",
			})
		);
		expect(fetch.mock.calls[0][1].body.toString()).toBe("usr=user%40example.com&pwd=secret&remember=0");
	});

	it("defaults remember to a long-lived session", async () => {
		const fetch = vi.fn().mockResolvedValue({
			ok: true,
			json: async () => ({ message: { message: "Logged In" } }),
		});
		vi.stubGlobal("fetch", fetch);

		await login("user@example.com", "secret");

		expect(fetch.mock.calls[0][1].body.toString()).toBe("usr=user%40example.com&pwd=secret&remember=1");
	});

	it("rejects when the server does not confirm the login", async () => {
		const fetch = vi.fn().mockResolvedValue({
			ok: false,
			status: 401,
			json: async () => ({
				_server_messages: JSON.stringify([JSON.stringify({ message: "Invalid login credentials" })]),
			}),
		});
		vi.stubGlobal("fetch", fetch);

		await expect(login("user@example.com", "wrong")).rejects.toThrow("Invalid login credentials");
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
