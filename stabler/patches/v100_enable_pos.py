"""POS'u kendi bayrağına taşı; kimsenin davranışını değiştirmeden.

POS ekranı bugüne kadar `module: "sales"` üzerinden görünüyordu. `sales`
varsayılan-açık dört çekirdek modülden biri olduğu için POS'u tek bir kiracıda
kapatmanın yolu yoktu — kapatılamayan bir ekran, kiracı ayarı değil kod
sabitidir. Bu patch yeni `enable_pos` sütununu, yerini aldığı kuralın birebir
çevirisiyle dolduruyor: POS sales'in açık olduğu her yerde açık kalır.

`enable_pos = enable_sales` yazması kasıtlı. Sabit bir 1 yazsaydı `sales`'i
kapatmış bir kiracıda POS'u ilk kez açardı; sabit bir 0 yazsaydı POS kullanan
altı kiracıdan onu alırdı. Kopyalanan şey bir değer değil, bir kural.

[post_model_sync] altına kayıtlı (patches.txt:41'den sonra), yani DDL sync
sütunu oluşturmuş oluyor. has_column guard'ı yine de duruyor: bir gün biri
girdiyi yukarı taşırsa migrate'i düşürmesin (ev tarzı — bkz. v62).

Yeniden koşmaya güvenli: tek geçiş, yalnız `IS NULL` satırlar. Bir NULL asla
"izin verildi" diye okunmaz; bir 0 ya da 1 birinin cevabıdır — deploy sonrası
POS'u yönetici ekranından kapatan operatörünki de dâhil. Replay teorik değil:
bir site backup'tan geri yüklendiğinde ya da patch'ler elle koşturulduğunda
oluyor, ve tam da kimsenin izlemediği anda (bkz. test_module_flag_patch_replay).
"""

import frappe


def execute():
	if not frappe.db.has_column("Stabler Company Modules", "enable_pos"):
		return  # Sütun henüz yok — DocType DDL sync koşmamış.

	frappe.db.sql(
		"UPDATE `tabStabler Company Modules` SET enable_pos = enable_sales WHERE enable_pos IS NULL"
	)
	frappe.db.commit()
