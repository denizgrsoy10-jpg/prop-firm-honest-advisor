import os, tempfile, random
import streamlit as st
from firm_rules import RULESETS, compare_firms
from load_trades import load_trades_csv, trades_to_daily, data_quality_report
import advisor

st.set_page_config(page_title="Prop Firm Honest Advisor", layout="wide")
st.title("Prop Firm Honest Advisor")
st.caption("We don't sell guarantees - we sell truth. The engine only tests against published rules. No predictions, ever.")

with st.sidebar:
    st.header("Settings")
    initial=st.number_input("Starting balance",min_value=1000.0,value=100000.0,step=1000.0)
    fee=st.number_input("Challenge fee (per attempt)",min_value=0.0,value=550.0,step=10.0,
                        help="Expected cost = fee x average number of attempts.")
    horizon=st.slider("Time window (trading days)",10,120,60,
                      help="Assumes the trader tries to pass within this many days per phase.")
    sims=st.select_slider("Simulations",options=[1000,2000,5000,10000],value=5000)
    seed=st.number_input("Seed",value=42,step=1)

uploaded=st.file_uploader("Upload your trade history CSV (Close Time + Profit columns)",type=["csv"])
if uploaded is None:
    st.info("Upload a CSV. Columns are auto-detected; you will be warned about any data issues.")
    st.stop()

tmp=tempfile.NamedTemporaryFile(delete=False,suffix=".csv")
tmp.write(uploaded.getvalue()); tmp.close(); path=tmp.name

trades,issues=load_trades_csv(path)
with st.expander("CSV parsing / column detection",expanded=False):
    for it in issues: st.write("- "+it)
if not trades:
    st.error("No valid trades found. Check column names (date + profit)."); os.unlink(path); st.stop()

recs,days_sorted=trades_to_daily(trades,initial)

st.subheader("Data quality")
for note in data_quality_report(trades,days_sorted,initial):
    (st.error if note.startswith("ERROR") else st.warning if note.startswith("WARNING") else st.write)(note)

final_eq=recs[-1].eod_equity
c1,c2,c3=st.columns(3)
c1.metric("Starting balance",str(int(initial)))
c2.metric("Final equity",str(int(final_eq)))
c3.metric("Total return",str(round((final_eq-initial)/initial*100,1))+"%")
st.line_chart([r.eod_equity for r in recs])

days=advisor.load_days(path); os.unlink(path)
pool=days; avg=sum(d[0] for d in days)/len(days)
rng=random.Random(int(seed))
res=[advisor.run_firm(pool,initial,rs,sims,horizon,rng) for rs in RULESETS]
res.sort(key=lambda r:r["payout"],reverse=True)

st.subheader("Recommendation")
hl=advisor.headline(res,fee)
(st.success if "ANY" not in hl else st.error)(hl)

st.subheader("Pass / payout probability (intraday + multi-phase)")
st.caption("Daily average: "+str(round(avg,0))+("  -> positive edge detected." if avg>0 else "  -> edge ~0/negative, passing depends on luck."))
mc_rows=[]
for r in res:
    mc_rows.append({
        "Firm / Product":r["firm"]+" "+r["product"],
        "Pass":str(round(r["pass"]*100,1))+"%",
        "Payout":str(round(r["payout"]*100,1))+"%",
        "Median days":r["median"] if r["median"] is not None else "-",
        "Top fail reason":r["topfail"],
    })
st.dataframe(mc_rows,use_container_width=True,hide_index=True)

st.subheader("Advisor verdict (per firm)")
for r in res:
    with st.expander(r["firm"]+" "+r["product"]+"   (payout "+str(round(r["payout"]*100,1))+"%)"):
        st.write(advisor.verdict(r,fee,avg))

with st.expander("Honest notes"):
    st.write("- Bootstrap treats each day as independent; regime changes are not fully captured.")
    st.write("- Intraday lows are estimated from closed-trade timestamps; floating (unrealized) drawdowns are not fully modeled.")
    st.write("- Multi-phase firms simulate each phase as a fresh account.")
    st.write("- Expected cost = fee x (1 / pass rate); this is a rough average.")
    if len(pool)<30:
        st.warning("Day pool is small ("+str(len(pool))+"); probabilities are rough estimates.")

with st.expander("Rule freshness / fields needing verification"):
    for rs in RULESETS:
        st.write("**"+rs.firm+" "+rs.product+"** - verified: "+str(rs.last_verified)+" - "+rs.source_url)
        for nv in rs.needs_verification:
            st.write("   - verify: "+nv)
