"""Add Transporter Management translations across en, ru, tr, uz, uzc CSV files."""

import csv
import os

TRANSLATIONS = {
	"en.csv": [
		("Nakliye Operasyon Masası", "Land Freight Operations Center"),
		("Total Freight Cost", "Total Freight Cost"),
		("Paid Cash (Kassa)", "Paid Cash (Kassa)"),
		("Paid Bank (Transfer)", "Paid Bank (Transfer)"),
		("Outstanding Balance", "Outstanding Balance"),
		("All Transporters", "All Transporters"),
		("Transporter Vendor", "Transporter Vendor"),
		("Container / Truck #", "Container / Truck #"),
		("Transport Cost", "Transport Cost"),
		("Paid Cash", "Paid Cash"),
		("Paid Bank", "Paid Bank"),
		("Balance Due", "Balance Due"),
		("Edit Transport & Payment Details", "Edit Transport & Payment Details"),
		("Agreed Transport Cost", "Agreed Transport Cost"),
		("Save Details", "Save Details"),
	],
	"ru.csv": [
		("Nakliye Operasyon Masası", "Операционный стол перевозчиков"),
		("Total Freight Cost", "Общая стоимость фрахта"),
		("Paid Cash (Kassa)", "Оплачено наличными (Касса)"),
		("Paid Bank (Transfer)", "Оплачено банком (Перевод)"),
		("Outstanding Balance", "Остаток задолженности"),
		("All Transporters", "Все перевозчики"),
		("Transporter Vendor", "Перевозчик"),
		("Container / Truck #", "Контейнер / Грузовик №"),
		("Transport Cost", "Стоимость перевозки"),
		("Paid Cash", "Оплата наличными"),
		("Paid Bank", "Оплата банком"),
		("Balance Due", "Остаток к оплате"),
		("Edit Transport & Payment Details", "Редактировать данные перевозки и оплаты"),
		("Agreed Transport Cost", "Согласованная стоимость перевозки"),
		("Save Details", "Сохранить данные"),
	],
	"tr.csv": [
		("Nakliye Operasyon Masası", "Nakliye Operasyon Masası"),
		("Total Freight Cost", "Toplam Navlun Maliyeti"),
		("Paid Cash (Kassa)", "Nakit Ödenen (Kasa)"),
		("Paid Bank (Transfer)", "Banka Ödenen (Havale)"),
		("Outstanding Balance", "Kalan Nakliyeci Borcu"),
		("All Transporters", "Tüm Nakliyeciler"),
		("Transporter Vendor", "Nakliyeci Firma"),
		("Container / Truck #", "Konteyner / Tır No"),
		("Transport Cost", "Navlun Bedeli"),
		("Paid Cash", "Nakit Ödenen"),
		("Paid Bank", "Banka Ödenen"),
		("Balance Due", "Kalan Bakiye"),
		("Edit Transport & Payment Details", "Nakliye ve Ödeme Detaylarını Düzenle"),
		("Agreed Transport Cost", "Anlaşılan Navlun Bedeli"),
		("Save Details", "Detayları Kaydet"),
	],
	"uz.csv": [
		("Nakliye Operasyon Masası", "Tashuvchilar Operatsion Markazi"),
		("Total Freight Cost", "Jami Fraxt Qiymati"),
		("Paid Cash (Kassa)", "Naqd To'langan (Kassa)"),
		("Paid Bank (Transfer)", "Bank To'langan (O'tkazma)"),
		("Outstanding Balance", "Qolgan Qarz Balansi"),
		("All Transporters", "Barcha Tashuvchilar"),
		("Transporter Vendor", "Tashuvchi Kompaniya"),
		("Container / Truck #", "Konteyner / Yuk mashinasi №"),
		("Transport Cost", "Tashish Narxi"),
		("Paid Cash", "Naqd To'langan"),
		("Paid Bank", "Bank To'langan"),
		("Balance Due", "To'lanishi Kerak"),
		("Edit Transport & Payment Details", "Tashish va To'lov Tafsilotlarini Tahrirlash"),
		("Agreed Transport Cost", "Kelishilgan Tashish Narxi"),
		("Save Details", "Tafsilotlarni Saqlash"),
	],
	"uzc.csv": [
		("Nakliye Operasyon Masası", "Ташувчилар Операцион Маркази"),
		("Total Freight Cost", "Жами Фрахт Қиймати"),
		("Paid Cash (Kassa)", "Нақд Тўланган (Касса)"),
		("Paid Bank (Transfer)", "Банк Тўланган (Ўтказма)"),
		("Outstanding Balance", "Қолган Қарз Баланси"),
		("All Transporters", "Барча Ташувчилар"),
		("Transporter Vendor", "Ташувчи Компания"),
		("Container / Truck #", "Контейнер / Юк машинаси №"),
		("Transport Cost", "Ташиш Нархи"),
		("Paid Cash", "Нақд Тўланган"),
		("Paid Bank", "Банк Тўланган"),
		("Balance Due", "Тўланиши Керак"),
		("Edit Transport & Payment Details", "Ташиш ва Тўлов Тафсилотларини Таҳрирлаш"),
		("Agreed Transport Cost", "Келишилган Ташиш Нархи"),
		("Save Details", "Тафсилотларни Сақлаш"),
	],
}


def main():
	base_dir = os.path.dirname(__file__)
	for filename, pairs in TRANSLATIONS.items():
		filepath = os.path.join(base_dir, filename)
		if not os.path.exists(filepath):
			continue

		existing = set()
		with open(filepath, "r", encoding="utf-8") as f:
			reader = csv.reader(f)
			for row in reader:
				if row:
					existing.add(row[0])

		new_rows = [pair for pair in pairs if pair[0] not in existing]
		if new_rows:
			with open(filepath, "a", encoding="utf-8", newline="") as f:
				writer = csv.writer(f)
				for src, tr in new_rows:
					writer.writerow([src, tr])
			print(f"Added {len(new_rows)} translations to {filename}")


if __name__ == "__main__":
	main()
