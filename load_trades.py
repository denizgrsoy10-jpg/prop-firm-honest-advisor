"""
load_trades.py - Islem CSV'sini okur, gunluk equity egrisine cevirir,
firm_rules motoruna baglar. Titiz veri-kalitesi kontrolu icerir.

Kullanim:
    python3 load_trades.py                 # ornek CSV uretir ve test eder
    python3 load_trades.py kendi_dosyam.csv --initial 100000
"""

import csv
import sys
from datetime import datetime, timedelta

from firm_rules import DayRecord, compare_firms, MODEL_LIMITS, RULESETS


# ----------------------------------------------------------------------------
# 1) KOLON TESPITI - farkli broker export formatlari (MT4/MT5/cTrader/generic)
# ----------------------------------------------------------------------------

# Oncelik sirasi onemli: en spesifik isim once gelir.
DATE_HINTS = ["close time", "closing time", "close_time", "closetime",
              "exit time", "time", "date"]
PROFIT_HINTS = ["net profit", "net usd", "net", "profit", "p/l", "pnl",
                "realized p/l", "result", "gain", "profit/loss"]


def detect_columns(header):
    """Header listesinden (tarih_idx, kar_idx) bulur. Bulamazsa None doner."""
    low = [h.strip().lower() for h in header]

    def find(hints):
        for hint in hints:
            for i, h in enumerate(low):
                if hint == h:          # tam eslesme oncelikli
                    return i
        for hint in hints:
            for i, h in enumerate(low):
                if hint in h:          # sonra icerik eslesmesi
                    return i
        return None

    return find(DATE_HINTS), find(PROFIT_HINTS)


# ----------------------------------------------------------------------------
# 2) GUVENLI PARSE - tarih ve sayi (cok format, dunya capinda broker cesitliligi)
# ----------------------------------------------------------------------------

DATE_FORMATS = [
    "%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M", "%Y.%m.%d",      # MT5
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",      # ISO
    "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y",      # Avrupa
    "%m/%d/%Y %H:%M:%S", "%m/%d/%Y",                        # ABD
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y",                        # UK
]


def parse_date(s):
    s = s.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_float(s):
    """Para birimi, binlik ayraci, parantez-negatif, virgul-ondalik destekler."""
    if s is None:
        return None
    s = s.strip()
    if s == "":
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):   # (123.45) = -123.45
        neg = True
        s = s[1:-1]
    for sym in ["$", "EUR", "USD", "TL", "TRY", "GBP", "\u20ac", "\u00a3", " "]:
        s = s.replace(sym, "")
    if "-" in s:
        neg = True
        s = s.replace("-", "")
    s = s.replace("+", "")
    # binlik/ondalik ayrac heuristigi
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):     # son virgul -> ondalik (Avrupa)
            s = s.replace(".", "").replace(",", ".")
        else:                                # son nokta -> ondalik (ABD)
            s = s.replace(",", "")
    elif "," in s:
        # tek virgul: 2 hane sonrasi varsa ondalik, degilse binlik
        if len(s.split(",")[-1]) in (1, 2):
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    try:
        val = float(s)
        return -val if neg else val
    except ValueError:
        return None


# ----------------------------------------------------------------------------
# 3) CSV YUKLEYICI - islem listesi + parse raporu
# ----------------------------------------------------------------------------

def load_trades_csv(path):
    trades = []          # (date, profit) listesi
    issues = []          # veri-kalitesi notlari
    skipped = 0

    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        # ayraci otomatik bul (virgul, noktali virgul, tab)
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(f, dialect)
        rows = list(reader)

    if not rows:
        issues.append("HATA: CSV bos.")
        return trades, issues

    header = rows[0]
    date_idx, profit_idx = detect_columns(header)
    if date_idx is None or profit_idx is None:
        issues.append("HATA: Tarih ve/veya kar kolonu bulunamadi. "
                      "Header: " + str(header))
        issues.append("       Beklenen kolon adlari: tarih icin 'Close Time'/'Date', "
                      "kar icin 'Profit'/'Net'/'P/L'.")
        return trades, issues

    issues.append("Tespit edilen kolonlar -> tarih: '" + header[date_idx]
                  + "', kar: '" + header[profit_idx] + "'")

    for n, row in enumerate(rows[1:], start=2):
        if len(row) <= max(date_idx, profit_idx):
            skipped += 1
            continue
        d = parse_date(row[date_idx])
        p = parse_float(row[profit_idx])
        if d is None or p is None:
            skipped += 1
            continue
        trades.append((d, p))

    if skipped:
        issues.append("UYARI: " + str(skipped) + " satir okunamadi (tarih/kar parse edilemedi)."
                      " Bunlar atlandi.")
    return trades, issues


# ----------------------------------------------------------------------------
# 4) ISLEMLER -> GUNLUK EQUITY EGRISI
# ----------------------------------------------------------------------------

def trades_to_daily(trades, initial):
    """Gun gun kar topla, kumulatif equity egrisi kur. DayRecord listesi doner."""
    daily = {}
    for d, p in trades:
        daily[d] = daily.get(d, 0.0) + p
    days_sorted = sorted(daily.keys())
    recs = []
    eq = initial
    for i, d in enumerate(days_sorted, start=1):
        eq += daily[d]
        recs.append(DayRecord(day=i, pnl=daily[d], eod_equity=eq))
    return recs, days_sorted


# ----------------------------------------------------------------------------
# 5) VERI KALITESI RAPORU - durustlugun temeli
# ----------------------------------------------------------------------------

def data_quality_report(trades, days_sorted, initial):
    notes = []
    if not trades:
        notes.append("HATA: Hic gecerli islem yok.")
        return notes

    n_trades = len(trades)
    n_days = len(days_sorted)
    span_start, span_end = days_sorted[0], days_sorted[-1]
    notes.append("Islem sayisi: " + str(n_trades)
                 + " | Islem gunu: " + str(n_days)
                 + " | Tarih araligi: " + str(span_start) + " -> " + str(span_end))

    # 1) Yetersiz gun: en kati min_trading_days'e gore
    max_min_days = max((ph.min_trading_days for rs in RULESETS for ph in rs.phases),
                       default=0)
    if n_days < max_min_days:
        notes.append("UYARI: Sadece " + str(n_days) + " islem gunu var; bazi firmalar "
                     + "min " + str(max_min_days) + " gun istiyor. Sonuclar guvenilmez.")

    # 2) Takvim bosluklari (olasi eksik veri)
    gaps = []
    for a, b in zip(days_sorted, days_sorted[1:]):
        delta = (b - a).days
        if delta > 4:    # hafta sonu ~2-3 gun normaldir; 4+ supheli
            gaps.append(str(a) + " -> " + str(b) + " (" + str(delta) + " gun)")
    if gaps:
        notes.append("UYARI: Buyuk takvim boslugu (eksik veri olabilir): "
                     + "; ".join(gaps[:5]) + (" ..." if len(gaps) > 5 else ""))

    # 3) Tek gun asiri konsantrasyon (ya cok iyi veri ya bozuk)
    daily = {}
    for d, p in trades:
        daily[d] = daily.get(d, 0.0) + p
    best = max(daily.values())
    if best > initial * 0.10:
        notes.append("UYARI: Bir gun baslangic bakiyenin %"
                     + str(round(best / initial * 100, 1))
                     + "'ini kazanmis. Cogu consistency kuralini zorlar (ya da veri hatasi).")

    # 4) Hepsi sifir / tek deger suphesi
    profits = [p for _, p in trades]
    if all(p == 0 for p in profits):
        notes.append("UYARI: Tum kar degerleri 0. Yanlis kolon okunmus olabilir.")

    # 5) Cok az islem
    if n_trades < 20:
        notes.append("NOT: " + str(n_trades) + " islem az; istatistiksel guven dusuk. "
                     + "Monte Carlo asamasinda bu daha da onemli olacak.")

    return notes


# ----------------------------------------------------------------------------
# 6) ORNEK CSV URETICI - kullanicinin CSV'si yokken uctan uca test icin
# ----------------------------------------------------------------------------

def write_sample_csv(path):
    base = datetime(2026, 5, 4)   # bir Pazartesi
    # 8 islem gunu, gunde birkac islem; 4. gun sert dususlu
    plan = [
        [1200, 800, 1200],      # gun 1
        [600, 900],             # gun 2
        [1500, 1100],           # gun 3
        [-2000, -1800],         # gun 4 (kotu gun)
        [700, 1200],            # gun 5
        [900, 900],             # gun 6
        [1300, -400, 600],      # gun 7
        [800, 700],             # gun 8
    ]
    rows = [["Close Time", "Symbol", "Profit"]]
    day = 0
    added = 0
    while added < len(plan):
        d = base + timedelta(days=day)
        if d.weekday() < 5:     # sadece hafta ici
            for pnl in plan[added]:
                ts = d.strftime("%Y.%m.%d") + " 15:30:00"
                rows.append([ts, "EURUSD", str(pnl)])
            added += 1
        day += 1
    with open(path, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)


# ----------------------------------------------------------------------------
# 7) ANA AKIS
# ----------------------------------------------------------------------------

def main():
    args = sys.argv[1:]
    initial = 100000.0
    if "--initial" in args:
        idx = args.index("--initial")
        initial = float(args[idx + 1])
        args = args[:idx] + args[idx + 2:]

    if args:
        path = args[0]
        print("CSV okunuyor: " + path)
    else:
        path = "sample_trades.csv"
        write_sample_csv(path)
        print("CSV verilmedi -> ornek olusturuldu: " + path)
        print("Kendi verinle: python3 load_trades.py dosyan.csv --initial 100000")

    print("")
    trades, issues = load_trades_csv(path)
    for it in issues:
        print("  " + it)

    if not trades:
        print("Gecerli islem bulunamadi, durduruluyor.")
        return

    recs, days_sorted = trades_to_daily(trades, initial)

    print("")
    print("VERI KALITESI:")
    for note in data_quality_report(trades, days_sorted, initial):
        print("  " + note)

    print("")
    print("Baslangic: " + str(int(initial)) + "  Son: " + str(int(recs[-1].eod_equity))
          + "  (" + str(round((recs[-1].eod_equity - initial) / initial * 100, 1)) + "%)")
    print("")
    print("FIRMA / URUN".ljust(42) + "GECER?".ljust(8) + "ODEME?".ljust(8) + "TABANA PAY")
    print("-" * 72)
    for r in compare_firms(recs, initial):
        gec = "EVET" if (r.target_met and not r.breached and r.days_met) else "HAYIR"
        ode = "EVET" if r.payout_eligible else "HAYIR"
        print((r.firm + " " + r.product).ljust(42) + gec.ljust(8) + ode.ljust(8)
              + str(round(r.distance_to_breach_pct * 100, 1)) + "%")
        for b in r.breach_reasons:
            print("    x " + b)
        for w in r.warnings:
            print("    ! " + w)


if __name__ == "__main__":
    main()
