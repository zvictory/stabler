"""Bir anlaşmanın hareket kaydı — değişmez, ve artık iki eksenli.

İKİ EKSEN, TEK LOG, AYRI SÜTUNLAR

`status` ekseni CRM Deal Status hattı; `tender_stage` ekseni kullanıcının
Tender CRM panosunda kartı sürüklediği kulvar. İkisi de "bu anlaşma nereden
nereye gitti" sorusuna cevap veriyor, o yüzden tek log — bir anlaşmanın
zaman çizelgesini iki tablodan birleştirmek zorunda kalmak istemiyoruz.

Ama aynı SÜTUNLARI paylaşamıyorlar. `from_stage`/`to_stage` birer Link ve
hedefleri CRM Deal Status: bir statü yeniden adlandırıldığında Frappe geçmişi
de peşinden güncelliyor, yani eski kayıtlar öksüz kalmıyor. Tender aşamaları
ise kodda sabit (`_funnel.STAGES`) — tabloda satırları yok. Onları Link'e
yazmak kırık bağlantı üretir; sütunu Data'ya çevirmek ise statü tarafının
yeniden adlandırma zincirini kırardı. O yüzden tender ekseni kendi iki Data
sütununu kullanıyor.

Doğrulama da eksene göre: Link'in bedavaya verdiği "bu değer gerçekten var mı"
güvencesinin tender tarafındaki karşılığı `_funnel.STAGES` üyeliği, ve o
kontrol şema yerine burada yaşıyor.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

STATUS = "status"
TENDER_STAGE = "tender_stage"


class CRMStageEvent(Document):
	def validate(self):
		axis = (self.axis or STATUS).strip()
		if axis not in (STATUS, TENDER_STAGE):
			frappe.throw(_("Unknown stage axis: {0}").format(axis))
		self.axis = axis

		if axis == TENDER_STAGE:
			self._validate_tender_axis()
		else:
			self._validate_status_axis()

	def _validate_tender_axis(self) -> None:
		from stabler.api._funnel import STAGES

		if not self.to_tender_stage:
			frappe.throw(_("A tender stage event needs a destination stage."))
		for field in ("from_tender_stage", "to_tender_stage"):
			value = self.get(field)
			# Boş `from` ilk hareket demek ve geçerli — anlaşma bir yerden
			# gelmemiş olabilir.
			if value and value not in STAGES:
				frappe.throw(_("Unknown tender stage: {0}").format(value))
		# Statü sütunları bu eksende dolu kalırsa okuyan taraf hangisinin
		# geçerli olduğunu bilemez.
		self.from_stage = None
		self.to_stage = None

	def _validate_status_axis(self) -> None:
		if not self.to_stage:
			frappe.throw(_("A status event needs a destination status."))
		self.from_tender_stage = None
		self.to_tender_stage = None

	def before_save(self):
		if not self.is_new():
			frappe.throw(_("CRM Stage Event records are immutable."))

	def on_trash(self):
		frappe.throw(_("CRM Stage Event records are immutable."))
