# UAT Test Senaryosu: HMA Proforma Faturası ve Akıllı Parçalı Avans Ödeme Sistemi

Bu kullanıcı kabul testi (UAT) senaryosu, **HMA AGRO INDUSTRIES LIMITED** tedarikçisinden gelen bir Proforma Faturanın (PI) sisteme girilmesini, 33 konteynerlik test kalemlerinin tanımlanmasını ve yeni tasarlanan **Record Advance Payment** modalı üzerinden %30'luk avansın oransal olarak banka ve kasa hesaplarına bölünerek kaydedilmesini adım adım test etmek için hazırlanmıştır.

---

## 🛠 1. Ön Koşullar (Prerequisites)

Test işlemine başlamadan önce aşağıdaki verilerin sistemde tanımlı olduğunu doğrulayın:
1. **Tedarikçi**: `HMA AGRO INDUSTRIES LIMITED` sistemde kayıtlı olmalıdır.
2. **Kategori ve Ürünler**: `Test Category` adında bir ürün kategorisi bulunmalı ve bu kategoriye bağlı en az bir ürün tanımlı olmalıdır.
3. **Kasa & Banka Hesapları**: Aktif şirkete bağlı en az bir adet **USD Banka Hesabı** ve en az bir adet **USD Nakit Kasa Hesabı** tanımlı ve aktif olmalıdır.

---

## 📝 2. Test Adımları (Step-by-Step Test Steps)

### Adım 1: Proforma Faturası (PI) Oluşturma
1. Stabler SPA arayüzünden **Imports > Proformas** sayfasına gidin.
2. Sağ üstteki **"+ New Proforma"** butonuna tıklayın.
3. Başlık (Header) alanlarını aşağıdaki gibi doldurun:
   - **Supplier**: `HMA AGRO INDUSTRIES LIMITED`
   - **Total Containers**: `33`
   - **Currency**: `USD`
   - **Prepayment Base**: `Agreed total`
   - **Advance % (Prepayment Pct)**: `30`
4. Sayfadaki **"Fill from Category"** butonuna tıklayarak açılan yardımcı modalı doldurun:
   - **Category**: `Test Category`
   - **Containers**: `33`
   - **Agreed Price**: `5.00`
   - **Docs Price**: `4.50`
   - **Box Weight**: `20` (kg)
5. **"Apply"** butonuna tıklayarak kalemlerin otomatik oluşturulmasını sağlayın.
6. Faturayı kaydetmek için **"Save"** butonuna tıklayın.

---

### Adım 2: Matematiksel Kontroller ve Doğrulama
Fatura detay alanlarında ve sağlanan özet panelinde aşağıdaki hesaplamaların doğruluğunu inceleyin:
- **Agreed Total (Toplam Anlaşılan Tutar)**: 
  $$\text{Toplam Kg} \times \$5.00$$
- **Docs Total (Resmi Evrak Toplamı)**: 
  $$\text{Toplam Kg} \times \$4.50$$
- **Cash Difference (Nakit Farkı)**: 
  $$\text{Agreed Total} - \text{Docs Total} \quad (\text{Toplam Kg} \times \$0.50)$$
- **Expected Advance (Beklenen Avans - %30)**:
  $$\text{Agreed Total} \times 0.30$$

---

### Adım 3: Yeni Parçalı Avans Ödeme Modalı Testi
1. Proforma faturası kaydedildikten sonra üst menüdeki **"Record Advance"** butonuna tıklayın.
2. Açılan **"Record Advance Payment"** modalında yeni arayüz bileşenlerini doğrulayın:
   - **Matrah Kartı (Top Card)**: `Total Agreed PI`, `Official Docs Total` ve `Cash Difference` tutarlarının Adım 2'deki hesaplamalarla birebir eşleştiğini görün.
   - **Yüzde Seçimi (% Pills)**: Hızlı yüzde haplarından **`30%`** seçeneğini seçin.
   - **Strateji Seçimi (Strategy Presets)**: **`Split Bank + Cash`** (Oransal Böl) kartına tıklayın.
3. **Akıllı Paylaştırma Doğrulaması**:
   Strateji kartı tıklandığında aşağıdaki alt kutuların otomatik doldurulduğunu kontrol edin:
   - **Official Bank Amount (Banka Avans Tutarı)**:
     $$\text{Docs Total} \times 0.30$$
   - **Cash Safe Amount (Kasa Avans Tutarı)**:
     $$\text{Cash Difference} \times 0.30$$
4. **Ödeme Hesaplarının Seçimi (Paid From Dropdowns)**:
   - **Paid From (Bank Account)** açılır menüsünden ödemenin yapılacağı ilgili banka hesabını seçin (örneğin: default veya USD banka hesabı).
   - **Paid From (Cash Account)** açılır menüsünden ödemenin yapılacağı nakit kasa hesabını seçin.
5. **Tarih & Referans**:
   - **Payment Date**: Günün tarihini seçin.
   - **Payment Reference / Memo**: `ADV-HMA-33-SPLIT` yazın.
6. En alttaki yeşil şeritte **Total Advance to Record** tutarının toplam avans miktarı ile tam uyumlu olduğunu görün.
7. **"Create Draft Payment Entries"** butonuna tıklayın.

---

### Adım 4: Taslak Payment Entry Belgelerinin Doğrulanması
1. Kayıt işlemi bittiğinde modal otomatik kapanacak ve Proforma üzerinde bildirim görünecektir.
2. Sistemde oluşturulan taslak belgeleri kontrol etmek için finans/ödeme ekranına gidin:
   - **Banka Ödemesi**: Seçilen Banka Hesabından, `HMA AGRO INDUSTRIES LIMITED` tedarikçisine, Adım 3'teki **Banka Avans Tutarı** kadar **DRAFT (Taslak)** durumunda bir `Payment Entry` oluşturulduğunu ve `custom_payment_stream` alanının `Bank` olduğunu doğrulayın.
   - **Kasa Ödemesi**: Seçilen Kasa Hesabından, `HMA AGRO INDUSTRIES LIMITED` tedarikçisine, Adım 3'teki **Kasa Avans Tutarı** kadar **DRAFT (Taslak)** durumunda ikinci bir `Payment Entry` oluşturulduğunu ve `custom_payment_stream` alanının `Cash` olduğunu doğrulayın.

---

## 🎯 3. Kabul Kriterleri (Acceptance Criteria)

| # | Kontrol Noktası | Beklenen Durum | Sonuç |
|---|---|---|---|
| 1 | Fill from Category | 33 konteyner ve Agreed 5.00 / Docs 4.50 fiyatları ile PI başarıyla kaydedilmeli. | |
| 2 | Top Context Card | Toplam tutarlar, evrak tutarı ve nakit farkı hatasız listelenmeli. | |
| 3 | Strategy Preset (%30 Split) | Banka ve kasa kutuları oransal formüle göre otomatik hesaplanmalı. | |
| 4 | Source Accounts | Banka ve Kasa dropdownları şirketin aktif hesaplarını listelemeli ve seçime izin vermeli. | |
| 5 | Draft Entries Creation | Biri banka ödemesi, diğeri nakit ödemesi olmak üzere 2 adet taslak Payment Entry başarıyla açılmalı. | |
