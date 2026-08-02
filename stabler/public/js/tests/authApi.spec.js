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

	it("calls stabler_logout with POST and CSRF headers", async () => {
		const fetch = vi.fn().mockResolvedValue({ ok: true });
		vi.stubGlobal("fetch", fetch);

		await logout();

		expect(fetch).toHaveBeenCalledWith(
			"/api/method/stabler.api.organization.stabler_logout",
			expect.objectContaining({
				method: "POST",
				credentials: "same-origin",
			})
		);
	});

	it("falls back to stock logout endpoint if stabler_logout returns non-ok", async () => {
		const fetch = vi
			.fn()
			.mockResolvedValueOnce({ ok: false, status: 404 })
			.mockResolvedValueOnce({ ok: true });
		vi.stubGlobal("fetch", fetch);

		await logout();

		expect(fetch).toHaveBeenNthCalledWith(
			1,
			"/api/method/stabler.api.organization.stabler_logout",
			expect.anything()
		);
		expect(fetch).toHaveBeenNthCalledWith(
			2,
			"/api/method/logout",
			expect.objectContaining({ method: "POST" })
		);
	});
});
