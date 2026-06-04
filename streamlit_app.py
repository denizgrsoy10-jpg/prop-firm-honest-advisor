import os, tempfile, random
import streamlit as st

from firm_rules import RULESETS, compare_firms
from load_trades import load_trades_csv, trades_to_daily, data_quality_report
import advisor

st.set_page_config(page_title="Prop-Firma Durust Test", layout="wide")
st.title("Prop-Firma Durust Test Araci")
st.caption("Garanti satmiyoruz, gercek satiyoruz. Motor yalnizca yayinlanmis "
           "kurallara karsi test eder, asla tahmin etmez.")

with st.sidebar:
    st.header("Ayarlar")
    initial = st.number_input("Baslangic bakiyesi", min_value=1000.0, value=100000.0, step=1000.0)
    fee = st.number_input("Challenge ucreti (deneme basi)", min_value=0.0, value=550.0, step=10.0,
                          help="Beklenen maliyet = ucret x ortalama deneme sayisi.")
    horizon = st.slider("Sure penceresi (islem gunu)", 10, 120, 60,
                        help="Her fazi bu kadar gun icinde gecmeye calisiyor varsayilir.")
    sims = st.select_slider("Simulasyon sayisi", options=[1000, 2000, 5000, 10000], value=5000)
    seed = st.number_input("Seed", value=42, step=1)

uploaded = st.file_uploader("Islem gecmisi CSV'si yukle (Close Time + Profit)", type=["csv"])
if uploaded is None:
    st.info("Bir CSV yukle. Kolonlar otomatik tespit edilir; bozuk veri varsa uyarilir.")
    st.stop()

tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
tmp.write(uploaded.getvalue()); tmp.close()
path = tmp.name

trades, issues = load_trades_csv(path)
with st.expander("CSV okuma / kolon tespiti", expanded=False):
    for it in issues:
        st.write("- " + it)
if not trades:
    st.error("Gecerli islem bulunamadi. Kolon adlarini kontrol et (tarih + kar).")
    os.unlink(path); st.stop()

recs, days_sorted = trades_to_daily(trades, initial)

st.subheader("Veri kalitesi")
for note in data_quality_report(trades, days_sorted, initial):
    (st.error if note.startswith("HATA") else st.warning if note.startswith("UYARI") else st.write)(note)

final_eq = recs[-1].eod_equity
c1, c2, c3 = st.columns(3)
c1.metric("Baslangic", str(int(initial)))
c2.metric("Son equity", str(int(final_eq)))
c3.metric("Toplam getiri", str(round((final_eq - initial) / initial * 100, 1)) + "%")
st.line_chart([r.eod_equity for r in recs])

days = advisor.load_days(path)
os.unlink(path)
pool = days
avg = sum(d[0] for d in days) / len(days)
rng = random.Random(int(seed))
res = [advisor.run_firm(pool, initial, rs, sims, horizon, rng) for rs in RULESETS]
res.sort(key=lambda r: r["payout"], reverse=True)

st.subheader("Ozet oneri")
hl = advisor.headline(res, fee)
(st.success if "HICBIR" not in hl else st.error)(hl)

st.subheader("Gecme / odeme ihtimali (gun-ici + cok-faz dahil)")
st.caption("Gunluk ortalama: " + str(round(avg, 0))
           + ("  -> pozitif edge var." if avg > 0 else "  -> edge ~0/negatif, sansa kalir."))
mc_rows = []
for r in res:
    mc_rows.append({
        "Firma / Urun": r["firm"] + " " + r["product"],
        "Gecme": "%" + str(round(r["pass"] * 100, 1)),
        "Odeme": "%" + str(round(r["payout"] * 100, 1)),
        "Medyan gun": r["median"] if r["median"] is not None else "-",
        "En sik bitis": r["topfail"],
    })
st.dataframe(mc_rows, use_container_width=True, hide_index=True)

st.subheader("Danisman gorusu (her firma)")
for r in res:
    with st.expander(r["firm"] + " " + r["product"]
                     + "   (odeme %" + str(round(r["payout"] * 100, 1)) + ")"):
        st.write(advisor.verdict(r, fee, avg))

with st.expander("Durust notlar"):
    st.write("- Bootstrap her gunu bagimsiz varsayar; rejim degisimi tam yansimaz.")
    st.write("- Gun-ici dip, kapali islemlerin gun ici sirasindan hesaplanir; aciktaki "
             "(floating) pozisyon dipleri hala tam modellenmez.")
    st.write("- Cok-faz firmalarda her faz taze hesap olarak ayri simule edilir.")
    st.write("- Beklenen maliyet = ucret x (1 / gecme orani); kaba bir ortalamadir.")
    if len(pool) < 30:
        st.warning("Gun havuzu kucuk (" + str(len(pool)) + "); yuzdeler kaba.")

with st.expander("Kural guncelligi / teyit gereken alanlar"):
    for rs in RULESETS:
        st.write("**" + rs.firm + " " + rs.product + "** - dogrulama: "
                 + str(rs.last_verified) + " - " + rs.source_url)
        for nv in rs.needs_verification:
            st.write("   - teyit: " + nv)
