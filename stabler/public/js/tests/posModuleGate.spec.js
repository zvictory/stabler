// POS'un kapatılabilirliği, gerçek session store'u üzerinden.
//
// Bu dosyanın varlık sebebi kaynak sözleşmesi testlerinin (test_pos_module_flag.py)
// kanıtlayamadığı tek şey: bağların doğru yere gitmesi değil, sonucun doğru
// çıkması. `pos` anahtarı 2026-08-27'ye kadar yoktu; POS `sales` üzerinden
// görünüyordu ve `sales`, satış akışının tamamının astığı çengel olduğu için
// POS kullanmayan kiracıda kapatılamıyordu. Buradaki iddia tam olarak o:
// **POS kapanırken sales ayakta kalabilmeli.** İkisi tek bayrağa geri
// düşerse bu spec düşer, kaynak testleri düşmez.
import { beforeEach, describe, expect, it } from "vitest";
import { createPinia, setActivePinia } from "pinia";

// session.js aktif şirketi MODÜL YÜKLENİRKEN localStorage'dan okuyor
// (stores/session.js:10), yani stub import'tan önce durmak zorunda —
// beforeEach çok geç kalır. setup.js yalnız `window`u kuruyor.
globalThis.localStorage = {
	getItem: () => null,
	setItem: () => {},
};

const { useSession } = await import("../stores/session.js");

function sessionWith(modules, { admin = false } = {}) {
	setActivePinia(createPinia());
	const session = useSession();
	session.user = { id: admin ? "Administrator" : "kassir@mikas.uz" };
	session.roles = admin ? ["System Manager"] : ["Sales User"];
	session.allowedModules = [];
	session.modules = modules;
	return session;
}

describe("POS gate", () => {
	beforeEach(() => {
		setActivePinia(createPinia());
	});

	it("kapatılan POS, açık kalan sales'i yanında götürmez", () => {
		const session = sessionWith({ sales: true, pos: false });
		expect(session.canAccessModule("pos")).toBe(false);
		expect(session.canAccessModule("sales")).toBe(true);
	});

	it("şirket POS'u kapattıysa yönetici de göremez", () => {
		// canAccessModule'de şirket bayrağı isAdmin bypass'ından ÖNCE bakılıyor.
		// Kiracı kararı bir yetki değil bir kapsam: kiracıda olmayan ekran
		// kimsede yoktur, aksi hâlde "kapattım" yarım bir cümle olur.
		const session = sessionWith({ sales: true, pos: false }, { admin: true });
		expect(session.canAccessModule("pos")).toBe(false);
	});

	it("POS açıkken satış rolündeki kullanıcı erişir", () => {
		const session = sessionWith({ sales: true, pos: true });
		expect(session.canAccessModule("pos")).toBe(true);
	});

	it("kullanıcı bazlı override POS'u tek tek verebilir", () => {
		const session = sessionWith({ sales: true, pos: true });
		session.allowedModules = ["dashboard", "sales"];
		expect(session.canAccessModule("pos")).toBe(false);
		session.allowedModules = ["dashboard", "pos"];
		expect(session.canAccessModule("pos")).toBe(true);
	});
});
