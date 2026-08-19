"""Var olan hareket kayıtlarını `status` ekseniyle işaretle.

`CRM Stage Event`e `axis` alanı eklendi ve zorunlu. Alan doctype senkronunda
oluşuyor, ama var olan satırlar NULL kalıyor — oysa hepsi statü hattına ait:
bu yamadan önce o logu yazan tek yer `api/crm.py`ydi.

NULL bırakmak, "ekseni bilinmeyen" bir yığın kayıt demek olurdu ve süreç akışı
ekranı ekseni filtrelediğinde geçmişin tamamı sessizce kaybolurdu — hata değil,
boş bir zaman çizelgesi. Boş bir çizelge "hiç hareket olmamış" diye okunur.

Bu yama patches.txt'te [post_model_sync] altında kayıtlı (72. satır), yani
doctype DDL senkronundan SONRA çalışıyor — sütun bu noktada zaten var. Kontrol
yine de tutuluyor (ev stili: bir `if`e mal olur, bu satır ileride taşınırsa da
güvenli kalır), sütun eksik olabileceği için değil.
"""

import frappe


def execute():
	if not frappe.db.table_exists("CRM Stage Event"):
		return
	if not frappe.db.has_column("CRM Stage Event", "axis"):
		return  # Sütun DDL senkronunda oluşacak; bu satırlar zaten yalnız statü.

	frappe.db.sql("UPDATE `tabCRM Stage Event` SET axis = 'status' WHERE axis IS NULL OR axis = ''")
	frappe.db.commit()
