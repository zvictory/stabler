"""Kiracı başına tender aşama süreleri.

`Stabler Company Modules` ile aynı şekil: Stabler Settings altında şirket
başına tek satır. Sütunlar `_tender_sla.DEFAULT_STAGE_SLA_DAYS` anahtarlarını
birebir izliyor — `won` ve `lost` kasıtlı olarak yok, çünkü sonuçlanmış bir
anlaşma beklemiyor ve ona eşik vermek her kazanılan işi gecikmiş gösterirdi.
"""

from frappe.model.document import Document


class StablerTenderStageSLA(Document):
	pass
