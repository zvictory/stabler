"""İki bileşik index: `tabGL Entry` üzerindeki müşteri/tedarikçi bakiye taraması.

`stabler.api.sales.list_customers_with_balances` iki ağır sorgu koşuyor
(`gl_rows`, `drift_rows`) ve ikisi de aynı dört kolonla filtreliyor:
``company`` + ``party_type`` + ``is_cancelled`` + ``party``. ERPNext'in kendi
index'lerinden **hiçbiri `is_cancelled`'ı taşımıyor**, dolayısıyla plan
`party_type_party_index` üzerinden gereğinden fazla kayıt okuyup fazlasını
`WHERE` ile atıyordu.

ANJAN prod'unda ölçüldü (2026-08-07, sorgu önbelleği KAPALI, ısınmış havuz):

    index'siz   uç nokta 892–1082 ms   (gl_rows ~292 ms, drift_rows ~530 ms)
    iki index   uç nokta 709– 783 ms   (gl_rows ~270 ms, drift_rows ~310 ms)

Yani **~%29**. `ANALYZE SELECT` ile doğrulandı: `stabler_party_balance_idx`
okunan satırların **tamamını** eşliyor (r_rows 55 652 → 43 007, r_filtered
%77 → %100) — index'ten okunup atılan tek bir kayıt kalmıyor.

`stabler_party_voucher_idx` ise `drift_rows`'un iç sorgusunu **kapsayıcı**
hale getiriyor (`Using index`, 96 490 → 37 764 satır); asıl kazanç orada.

**Neden tam kapsayıcı bir index yok:** `gl_rows`'un okuduğu yük kolonları
altı adet `varchar(140)` içeriyor; utf8mb4'te yalnız o altısı 3 372 bayt
ediyor ve InnoDB'nin anahtar sınırı 3 072. Ölçüldü, denenmedi değil — bu
yüzden `gl_rows` kümelenmiş index'e inmeye devam ediyor ve kazancı
`drift_rows`'unkinden küçük.

Bedel: index alanı 159 → 185 MB (+%16, ANJAN'da ölçüldü).

Idempotent: index adı `information_schema.STATISTICS`'te varsa hiçbir şey
yapılmaz. `ALGORITHM=INPLACE, LOCK=NONE` ile çevrimiçi kurulur — kiracılar
kesinti görmez.
"""

import frappe

TABLE = "tabGL Entry"

INDEXES = {
	"stabler_party_balance_idx": ("company", "party_type", "is_cancelled", "party"),
	"stabler_party_voucher_idx": (
		"company",
		"party_type",
		"is_cancelled",
		"voucher_type",
		"voucher_no",
		"party",
	),
}


def _has_index(name: str) -> bool:
	return bool(
		frappe.db.sql(
			"""SELECT 1 FROM information_schema.STATISTICS
			   WHERE table_schema = DATABASE() AND table_name = %s AND index_name = %s
			   LIMIT 1""",
			(TABLE, name),
		)
	)


def execute():
	if not frappe.db.table_exists("GL Entry"):
		return

	logger = frappe.logger("stabler.performance")
	for name, columns in INDEXES.items():
		if _has_index(name):
			continue
		# Kolonlardan biri bu ERPNext sürümünde yoksa index'i hiç deneme —
		# yarım bir index sessizce yanlış plan üretmekten kötüdür.
		missing = [c for c in columns if not frappe.db.has_column("GL Entry", c)]
		if missing:
			logger.warning(f"v77: {name} atlandı, eksik kolon: {missing}")
			continue

		cols = ", ".join(f"`{c}`" for c in columns)
		frappe.db.sql_ddl(f"ALTER TABLE `{TABLE}` ADD INDEX `{name}` ({cols}), ALGORITHM=INPLACE, LOCK=NONE")
		logger.info(f"v77: {name} oluşturuldu ({cols})")
