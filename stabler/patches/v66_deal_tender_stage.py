"""Tender aşaması ve o aşamaya giriş anı — CRM Deal üzerinde.

İKİ AYRI EKSİK, TEK YAMA.

1. `custom_tender_stage` hiçbir yamada YARATILMIYORDU. `api/tender.py`
   içindeki `move_deal_stage` onu `frappe.db.has_column(...)` ile koruyup
   yazıyor; sütun olmadığı için koşul hep False dönüyor ve yazma sessizce
   atlanıyor. Tender CRM'de bir kartı sürüklemek iyimser güncelleme + başarı
   bildirimi gösteriyor, ama aşama HİÇBİR yere kaydedilmiyor: sayfa yenilenince
   kart `_funnel.classify` ile türetilen kulvarına geri düşüyor.

   Türetilmiş aşama kendi başına doğru ve bu yama onu değiştirmiyor —
   `crm_board` sütun boşken yine `classify`'a düşüyor. Değişen tek şey:
   kullanıcı elle taşıdığında bunun kalıcı olması.

2. `custom_tender_stage_entered_at`: aşamaya ne zaman girildiği. BPM süreç
   akışı ekranı "bu anlaşma bu aşamada kaç gündür bekliyor" sorusuna cevap
   vermek zorunda ve bugün bu veri hiçbir yerde yok.

   CRM Deal'de zaten bir `stage_entered_at` var (v60) — ama o `status`
   ekseninin damgası, `api/crm.py` onu statü değişiminde yazıyor. Tender
   aşaması ayrı bir eksen (`custom_tender_stage`) ve aynı alanı iki eksenden
   yazmak ikisini de okunmaz yapardı: bir alanın hangi hareketi kaydettiği
   belirsizse, üzerine kurulan hiçbir süre güvenilir değildir. O yüzden ayrı
   alan.

Idempotent: her alan kendi Custom Field varlık kontrolüyle korunuyor.
Pre-sync güvenli: CRM Deal yoksa hiçbir şey yapılmıyor.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

# _funnel.ORDER + "lost". Sıra iş sırası; Select bunu olduğu gibi gösteriyor
# ki Desk'te elle düzenleyen biri de aynı sözlüğü görsün.
STAGES = ("seen", "go", "sourcing", "priced", "submitted", "won", "lost")


def execute():
	if not frappe.db.exists("DocType", "CRM Deal"):
		return

	fields = []

	if not frappe.db.exists("Custom Field", {"dt": "CRM Deal", "fieldname": "custom_tender_stage"}):
		fields.append(
			{
				"fieldname": "custom_tender_stage",
				"label": "Tender Stage",
				"fieldtype": "Select",
				# Boş seçenek ilk sırada ve kasıtlı: boş = "elle taşınmadı,
				# aşama olgulardan türetilsin". Varsayılan bir aşama koymak
				# her anlaşmayı elle taşınmış gibi gösterirdi.
				"options": "\n" + "\n".join(STAGES),
				"insert_after": "custom_tender_intake"
				if frappe.db.has_column("CRM Deal", "custom_tender_intake")
				else "status",
				"read_only": 1,
				"description": (
					"Set when a user drags the deal between lanes in the Stabler Tender CRM. "
					"Blank means the stage is derived from the deal's own facts "
					"(stabler.api._funnel.classify)."
				),
			}
		)

	if not frappe.db.exists(
		"Custom Field", {"dt": "CRM Deal", "fieldname": "custom_tender_stage_entered_at"}
	):
		fields.append(
			{
				"fieldname": "custom_tender_stage_entered_at",
				"label": "Tender Stage Entered At",
				"fieldtype": "Datetime",
				"insert_after": "custom_tender_stage",
				"read_only": 1,
				"description": (
					"When the deal entered its current tender stage. Written only when the "
					"stage actually changes, so re-saving a deal does not reset the clock. "
					"Distinct from stage_entered_at, which tracks the CRM status axis."
				),
			}
		)

	if fields:
		create_custom_fields({"CRM Deal": fields}, ignore_validate=True)
