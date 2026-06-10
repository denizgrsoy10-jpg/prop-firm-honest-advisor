# Candor RealityCheck — Soft-Live Deploy Package

Bu klasör Netlify drag-drop deploy için hazır. Pazarlama launch'ı **değil** —
sadece dışarıdan açılan bir URL elde etmek için. Reklam yok, trafik yok.

## İçindekiler

```
candor-landing/
├── index.html              # Ana landing (legal gate + 2 mode kartı + tüm bölümler)
├── terms.html              # Terms of Use (DRAFT)
├── privacy.html            # Privacy Notice (DRAFT)
├── refund.html             # Refund Policy (DRAFT)
├── risk-disclaimer.html    # Risk Disclaimer (DRAFT)
├── _redirects              # Netlify temiz URL eşlemeleri
├── netlify.toml            # Security + cache + noindex header'lar
└── README.md               # bu dosya
```

## Deploy adımları (5 dakika)

### 1) Netlify hesabı

- https://app.netlify.com → "Sign up" → **GitHub ile** veya e-postayla
- Ücretsiz plan yeterli (bandwidth 100 GB/ay, sınırsız site)

### 2) Manuel deploy

- Sol menüden **Sites** → sağ üstte **Add new site** → **Deploy manually**
- Bu **klasörün tamamını** (içindeki dosyaları değil, klasörü olduğu gibi)
  açılan pencereye sürükle bırak
- 20-30 saniye → site canlı. URL: `random-name-12345.netlify.app`

### 3) Temiz isim ver

- Site sayfasında **Site settings** → **Change site name**
- Öneri: `candor-reality` veya `candor-realitycheck`
- Yeni URL: `candor-reality.netlify.app`

### 4) HTTPS otomatik

- Netlify Let's Encrypt sertifikasını dakikalar içinde verir.
- Site adresini her zaman `https://` ile paylaş.

## Test checklist (deploy sonrası, soft-live'a koymadan önce)

**Mobil + masaüstü için ayrı yap.** Chrome auto-translate **kapalı** olsun
(sağ tık → "Show original") — bu sayfanın gerçek dili İngilizce.

### Legal gate
- [ ] Site açılınca büyük logo + "Before you continue" modal görünüyor
- [ ] 3 checkbox yok ki "Enter Candor" disabled
- [ ] 3 checkbox işaretlenince buton aktifleşiyor
- [ ] Terms / Risk Disclaimer / Privacy linkleri **çalışıyor** (yeni sekme açılmasa da gelmesi yeter)
- [ ] "Enter Candor"a basınca modal kayboluyor + scroll açılıyor
- [ ] Sayfa yenilendiğinde modal **tekrar çıkmıyor** (localStorage)

### Hero + modes
- [ ] Hero başlığı: "Before you risk money, run a RealityCheck."
- [ ] Alt mesaj: "Funded or self-funded, Candor shows what can break your trading."
- [ ] "Run my free RealityCheck" → Streamlit app açılıyor, **Prop mode seçili**
- [ ] "See the two modes" → aşağı kayıyor, MODES bölümüne iniyor
- [ ] **MODE.01 Prop kartı** tıklayınca app `?mode=prop_firm` ile açılıyor
- [ ] **MODE.02 Own Account kartı** tıklayınca app `?mode=own_account` ile açılıyor
- [ ] App'te ilgili mode radio'su otomatik seçili geliyor

### Legal sayfalar
- [ ] `/terms` ya da `/terms.html` her ikisi de açılıyor
- [ ] `/privacy`, `/refund`, `/risk-disclaimer` aynı şekilde
- [ ] Her sayfada **gold "Draft · Pending legal review" bandı** üstte
- [ ] Geri dön linki çalışıyor
- [ ] Sayfa başlıkları doğru, footer disclaimer var

### Mobil
- [ ] Hero ortalanmış, mode kartları **alt alta** geliyor (grid 2'den 1'e dönüyor)
- [ ] Legal gate mobil ekrana sığıyor, scroll edilebilir
- [ ] Pricing kartları okunabilir
- [ ] Footer kırpılmıyor

### Görünmeyenler
- [ ] Tarayıcıda **DevTools → Console** boş veya 200 status (sadece bilgi mesajları)
- [ ] DevTools → Network → bir `404` yok
- [ ] Logo ve scanner görselleri yükleniyor (base64 gömülü, harici bağlantı yok)

## Önemli notlar

### Pazarlama yok
Bu URL **paylaşılır değil** henüz. Avukat onayı bitmeden,
LemonSqueezy bağlanmadan, Draft band'leri kalkmadan reklamı verme.
Sadece soft-live görmek için.

### Streamlit demo banner duruyor
App tarafındaki `⚠️ DEMO / TEST MODE` uyarısı **bilerek kalsın**.
LemonSqueezy gerçek ödeme bağlanmadan önce satış yapma — kullanıcılar
soft-live'da "demo" işareti görmeli.

### Avukat / mali müşavir kontrolü
- Terms, Privacy, Refund, Risk Disclaimer hâlâ **DRAFT**.
- `[placeholder]` italik alanlar (Limitation of Liability, Governing Law,
  KVKK aydınlatma final, retention süreleri vs.) avukat tarafından doldurulacak.
- Onay sonrası: Draft band'i kaldır, Effective Date doldur, Version 1.0 yap.

### İleride GitHub Pages'e taşımak istersen
Aynı dosyalar GitHub Pages'te de çalışır. Tek fark: `_redirects` ve
`netlify.toml` ignore edilir; clean URL'ler için ya repo'da
`terms/index.html` klasörleri oluşturursun ya da linkler `.html` uzantılı kalır
(şu an zaten `.html` uzantılı, çalışır).

### Mode deep-link
Landing'deki kart linkleri Streamlit app'inin URL'ine `?mode=...` parametresi
ekliyor. App tarafında `app.py`'da bu parametreyi `ss.mode`'a yazan kod var.
Eğer Streamlit URL'i değişirse landing'deki linkleri de güncellemen gerek
(hero CTA + iki mode kartı = 3 link).

### Logo değişimi
Logo PNG'ler `index.html` içine **base64 olarak gömülü**, harici asset yok.
Logo değişirse: GitHub repo'daki `candor-logo-primary-dark.png` dosyasını
güncelle, sonra ben landing'deki base64'ü yenilerim.

## Yardım

Sorun çıkarsa Netlify Deploy log'unu (Sites → site → Deploys → en üstteki
deploy → View summary) ve test checklist'inde patlayan adımı paylaş.
