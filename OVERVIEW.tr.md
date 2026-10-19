# OSOS — Sayacınız internete çıkmadan, sahadaki her sayaç cebinizde

> **Uzaktan sayaç okuma, MQTT üzerinden. Bir ESP8266, bir telefon, bir broker. Gerisi yok.**

```
DKM-440 ──ethernet──▶ LAN ◀──wifi── ESP8266 ──MQTT/TLS──▶ broker ──▶ telefon
```

Sahadaki bir enerji analizörü (DATAKOM DKM-440) normalde sahanın içinde
hapsolur. OSOS onu **tek, kontrollü, kimlik doğrulamalı bir çıkış noktasından**
dışarı açar: ölçümleri JSON olarak yayınlar, telefondan isimlendirir, gruplar,
uyutur, yük röleleri açıp kapatır. Sayaç hiçbir zaman internete doğrudan
bağlanmaz.

Bu depo, **IKOM Bilişim'e teslim edilen** (2026-08-06) çalışan sistemin
tamamıdır: firmware, Android uygulaması, simülatör, sinir ağı, dokümantasyon ve
sunum. Ayrıntılı teknik el kitabı için bkz. [`README.md`](README.md).

---

## Neden OSOS?

| Sorun | OSOS'un cevabı |
|---|---|
| Sayaç LAN'da, müşteri ise uzakta | Tek bir WAN köprüsü: ESP8266, TLS 1.3 ile broker'a çıkar |
| Her sayaç için ayrı kurulum | Bir modem **8 analizöre kadar** okur; protokol sınırsız, simülatörde modem başına 25 analizör gösterildi |
| Yeniden adlandırma = veri kaybı | **İsimler topic parçası değil.** Adı değiştirmek geçmişi kırmaz, Modbus adresini bozmaz |
| "Komut gitti, peki röle açıldı mı?" | **Durum gözlemlenir, istenmez.** Uygulama bir yükü yalnızca modem "açık" dediğinde açık gösterir |
| Cevapsız komut = belirsizlik | **Sessizlik cevap değildir.** Her komut `ok:true/false` + sebep ile döner |
| Pil/ağ tasarrufu ama bağlantı kopmasın | Uyku = uzun rapor aralığı, `deepSleep` değil. Uyandırma komutu **~2 sn**'de onaylanır |

---

## Öne çıkanlar

### 1. Donanıma dokunmadan 5 dakikada deneyin
Sayaç da, gateway de, broker hesabı da gerekmez. Protokolün eksiksiz bir
simülatörü var; uygulama da onunla geliştirildi.

```bash
pip install paho-mqtt
cd source/tools
python fake_fleet.py --modems 3 --analyzers 8     # 24 sanal sayaç
python meter_cmd.py --modem gw-01 ping
python meter_cmd.py --modem gw-01 load --ch 3 --on
```

`app/osos-hmi-0.3.1.apk` dosyasını Android 8+ bir telefona kurun, broker'ı
ayarlayın — Monitor sekmesi dolmaya başlar.

### 2. Filo mantığıyla çalışan telefon uygulaması
Kotlin + Jetpack Compose, **7 ana ekran**: filo ağacı, canlı izleme, alarmlar,
komutlar, çizim, konsol, ayarlar.

- Sayaçlara **isim ve klasör** verin; bilgi telefonda değil **broker'da** yaşar —
  uygulamayı silip kursanız da geri gelir
- **Master sleep**: tüm filoyu uyutun. Alarmlar uykuda da değerlendirilir, yalnızca
  *bildirim* susar; uyanınca kaçırılanların özeti gelir
- Aynı anda yalnızca baktığınız sayacın telemetrisine abone olur — 24 sayaç x 5 sn
  = saniyede 5 mesaj yerine yalnızca ilgilendiğiniz akış
- **41 birim test**, cihaz gerektirmez

### 3. Elle çizin, komuta dönüşsün
Sıfırdan C'de yazılmış bir **sinir ağı** (MLP 784-128-10, gradient check ile
kanıtlanmış), telefonda çizilen sembolleri komuta çevirir. Güvenlik tasarımı
bilinçli: **`load` bağlanabilir eylem listesinde yok — hiçbir çizim bir röleyi
çalıştıramaz.** Olasılıksal girdi, endüstriyel aktüatörün önüne asla doğrudan
konmadı.

### 4. Tek bir topic dili, üç uygulama
Topic gramerini Python (`osos_proto.py`), Android (`TopicRouter.kt`) ve firmware
(`commands.h`) **aynı kuraldan** üretir. Birbirinden sapamazlar. Her mesaj
`"v": 2` taşır; eski v1 gateway hâlâ filo ağacında `v1` etiketiyle görünür —
yani bir firmware güncellemesi kötü giderse sistem ölmez, v1'e düşer.

### 5. Belgelenmemiş bir sayacı çözmek için tekrarlanabilir yöntem
DKM-440'ın register haritası hazır gelmedi; **tarayıp, kaydedip, bilinen
değerlere en küçük kareler ile uydurarak** türetildi
(`source/modbus-mapping/METHOD.md`). Haritadan çok bu yöntem değerli: başka bir
Modbus TCP cihazı, haritası bilindiğinde yaklaşık **bir günde** aynı gateway'in
arkasına eklenir. Topic yapısı, uygulama ve filo mantığı satıcıdan bağımsızdır;
yalnızca `meter_map.h` sayaca özgüdür.

---

## Şu an ne durumda?

Dürüst tablo — hiçbir rakam yuvarlanmadı; ölçülmeyen şey yazılmadı.

| | Durum |
|---|---|
| **Android uygulaması** `v0.3.1` | ✅ APK hazır, 41 test geçiyor |
| **ESP8266 gateway, Modbus TCP** | ✅ Donanımda kanıtlandı: 22/22 register, 15 ardışık döngü, kısmi okuma yok |
| **TLS 1.3** (sabitlenmiş DigiCert Global Root G2) | ✅ Doğrulanmış el sıkışma |
| **Simülatör + komut CLI** | ✅ Her komut ve her ret yolu denendi |
| **Uyku → uyanma, uykuda sessiz alarm, uyanış özeti** | ✅ Emülatörde simüle filo ile kanıtlandı |
| **Firmware v0.4** (filo zamanlayıcı, uyku, 4 röle kanalı, komut hattı) | 🟡 Derleniyor, **donanımda hiç çalışmadı** — ilk iş: flash + doğrulama |
| **ESP32 / RS-485 build** | 🟡 Referans amaçlı; kanıtlanmadı |
| **Broker rol ayrımı (kullanıcı başına ACL)** | 🔴 Tasarlandı, uygulanmadı |
| **Store-and-forward** | 🔴 `buffered` hep `false` — bağlantı kopunca kare kaybolur |
| **Tarihçe (historian)** | 🔴 RAM'de 720 kare = izleme, kayıt değil |
| **Uyku akım ölçümü, şebeke doğruluğu (DMM), gece soak testi** | ⚪ Yapılmadı, bu yüzden hiçbir rakam yok |

---

## Yol haritası: bir demodan bir ürüne

Sıralama bilinçli; bir sonraki adım bir öncekine bağlı.

1. **Firmware v0.4'ü sahada çalıştır** — komut gidiş-dönüşü, sayaç başına okuma,
   uyku/uyanma, röle anahtarlama
2. **Broker ACL'i uygula** — modem başına kullanıcı + bir `headend`. Bugün tüm
   cihazlar tek kimliği paylaşıyor; telefon artık yalnızca dinlemiyor, *komut da
   yayınlıyor*. İlk müşteri sahasından önce ucuz, sonra pahalı
3. **Store-and-forward** — LittleFS destekli kuyruk. Faturalama veya uyum için
   kullanılmadan önceki **kapı** bu; başka hiçbir özellik bunun önüne geçmez
4. **Historian** — kalıcı depolama
5. **IKOM Data Manager entegrasyonu** — `osos/m/+/labels`, `osos/tree` ve
   `osos/m/+/a/+/telemetry` konularına abone olan bir köprü, telefona ve
   gateway'e dokunmadan tüm filoyu *tanımlı, isimli, gruplanmış* olarak alır

---

## Depoda neler var?

| Klasör | İçerik |
|---|---|
| `app/` | `osos-hmi-0.3.1.apk` — kur ve çalıştır |
| `source/android/` | Kotlin / Compose uygulaması + testleri |
| `source/firmware-esp8266/` | **Çalışan gateway** (Arduino, Modbus TCP) |
| `source/firmware-esp32-rs485/` | Önceki ESP-IDF / RS-485 sürümü, referans |
| `source/tools/` | Protokol modülü, filo simülatörü, komut CLI |
| `source/browser-hmi/` | Aynı HMI, web sayfası olarak — kurulum yok |
| `source/neural-net-c/` | Sıfırdan C sinir ağı + MNIST |
| `source/modbus-mapping/` | Register haritasının nasıl çıkarıldığı |
| `reference/` | SRS belgeleri ve tezgâh fotoğrafları |
| `presentation/` | Teslim sunumu ve onu üreten Python |

Depoda **hiçbir kimlik bilgisi yoktur**. `config.h`, `broker.env`, `config.js`
gibi dosyalar isimle dışlanmıştır; her birinin yanında bir `.example` şablonu
bulunur.

---

## Hızlı başlangıç

```bash
# Uygulama (JDK 17 gerekir)
cd source/android && ./gradlew assembleDebug && ./gradlew testDebugUnitTest

# Gateway
cp source/firmware-esp8266/osos_gw8266/config.h.example source/firmware-esp8266/osos_gw8266/config.h
arduino-cli compile -b esp8266:esp8266:nodemcuv2 source/firmware-esp8266/osos_gw8266

# Sinir ağı ve matematiğin kanıtı
cd source/neural-net-c && make && ./gradcheck && ./mnist
```

Gerçek donanım, TLS ve broker güvenliği için: [`README.md`](README.md) bölüm 4 ve 5.

---

## Tek cümlede

**Çalışan bir okuma zinciri, sahada kanıtlanmış bir gateway, kullanıma hazır bir
telefon uygulaması ve neyin eksik olduğunu saklamayan bir yol haritası.**
Üretime giden yol belli: firmware'i çalıştır, broker'ı kilitle, veriyi kaybetme.

MIT lisansı — bkz. [`LICENSE`](LICENSE).
