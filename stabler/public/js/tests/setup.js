// composables/i18n.js captures `window.__STABLER__` at MODULE LOAD:
//
//     const boot = window.__STABLER__ || {};
//     const messages = boot.translations || {};
//
// so anything assigned after the first import of i18n.js (directly, or through
// status.js, which imports `t`) is invisible to it. A setup file is the only
// place that reliably runs BEFORE the spec files' imports -- hence this, rather
// than a beforeEach.
//
// Two consequences worth knowing before you edit this:
//   * the fixture below is the ONE translation table every spec sees; there is no
//     way to swap it per test without a dynamic import + module reset.
//   * `language: "ru"` makes tlang() return "ru" everywhere. That is deliberate:
//     an en-only fixture would let a hardcoded-English regression pass.
globalThis.window = {
	__STABLER__: {
		user: { language: "ru" },
		translations: {
			Draft: "Черновик",
			Submitted: "Проведён",
			Cancelled: "Отменён",
			"Hello {name}": "Привет, {name}",
			"{n} of {n}": "{n} из {n}",
		},
	},
};
