"""advisor.py - Turns the calculator into an ADVISOR.
Includes: intraday drawdown, multi-phase chaining, expected cost, verdict."""
import csv, random, sys
from datetime import datetime
from firm_rules import (RULESETS, DrawdownType, DailyLossBasis, DailyLossEffect, ConsistencyType)

DATE_FORMATS=["%Y.%m.%d %H:%M:%S","%Y.%m.%d %H:%M","%Y-%m-%d %H:%M:%S","%Y-%m-%d",
              "%d.%m.%Y %H:%M:%S","%m/%d/%Y %H:%M:%S","%d/%m/%Y %H:%M:%S"]

def parse_dt(s):
    s=s.strip()
    for f in DATE_FORMATS:
        try: return datetime.strptime(s,f)
        except ValueError: pass
    return None

def parse_num(s):
    if s is None: return None
    s=s.strip()
    if s=="": return None
    neg=False
    if s.startswith("(") and s.endswith(")"): neg=True; s=s[1:-1]
    for sym in ["$","EUR","USD","TL","TRY","GBP"," "]: s=s.replace(sym,"")
    if "-" in s: neg=True; s=s.replace("-","")
    s=s.replace("+","")
    if "," in s and "." in s:
        if s.rfind(",")>s.rfind("."): s=s.replace(".","").replace(",",".")
        else: s=s.replace(",","")
    elif "," in s:
        s=s.replace(",",".") if len(s.split(",")[-1]) in (1,2) else s.replace(",","")
    try:
        v=float(s); return -v if neg else v
    except: return None

def load_days(path):
    with open(path,encoding="utf-8-sig",newline="") as f:
        rows=list(csv.reader(f))
    header=[h.lower() for h in rows[0]]
    di=next((i for i,h in enumerate(header) if "time" in h or "date" in h),0)
    pi=next((i for i,h in enumerate(header) if "profit" in h or "net" in h or "p/l" in h),len(header)-1)
    trades=[]
    for r in rows[1:]:
        if len(r)<=max(di,pi): continue
        dt=parse_dt(r[di]); p=parse_num(r[pi])
        if dt and p is not None: trades.append((dt,p))
    trades.sort(key=lambda t:t[0])
    byday={}
    for dt,p in trades: byday.setdefault(dt.date(),[]).append((dt,p))
    days=[]
    for d in sorted(byday):
        seq=[p for _,p in sorted(byday[d])]
        run=0.0; mn=0.0
        for p in seq: run+=p; mn=min(mn,run)
        days.append((round(run,2),round(mn,2)))
    return days

def sim_phase(draw, n, initial, phase, rs):
    eq=initial; peak=initial; prev=initial; td=0; pd_=0; best=0.0
    for _ in range(n):
        net,intramin=draw(); td+=1; low_eq=eq+intramin
        if rs.drawdown_type==DrawdownType.STATIC: floor=initial*(1-rs.max_drawdown_pct)
        else: floor=peak-initial*rs.max_drawdown_pct
        if low_eq<floor: return ("fail_dd",td,eq,best)
        if rs.daily_loss_basis!=DailyLossBasis.NONE and rs.daily_loss_pct:
            lim=prev-initial*rs.daily_loss_pct
            if low_eq<lim and rs.daily_loss_effect==DailyLossEffect.BREACH:
                return ("fail_daily",td,eq,best)
        eq+=net
        if eq>peak: peak=eq
        prev=eq
        if net>best: best=net
        if net>=initial*phase.profitable_day_threshold_pct: pd_+=1
        if phase.profit_target_pct is None or (eq-initial)/initial>=phase.profit_target_pct:
            if td>=phase.min_trading_days and pd_>=phase.min_profitable_days:
                return ("pass",td,eq,best)
    return ("timeout",td,eq,best)

def sim_challenge(pool, initial, rs, horizon, rng):
    h=horizon if not rs.time_limit_days else min(horizon,rs.time_limit_days)
    draw=lambda: rng.choice(pool)
    total_days=0; best_overall=0.0; total_profit=0.0
    for ph in rs.phases:
        out,td,eq,best=sim_phase(draw,h,initial,ph,rs)
        total_days+=td; best_overall=max(best_overall,best); total_profit+=(eq-initial)
        if out!="pass": return (out,total_days,False,ph.name)
    payout=True
    if rs.consistency_type==ConsistencyType.BEST_DAY_PCT and rs.consistency_pct and total_profit>0:
        if best_overall>rs.consistency_pct*total_profit: payout=False
    payout=payout or not rs.consistency_applies_funded
    return ("pass",total_days,payout,None)

def run_firm(pool,initial,rs,sims,horizon,rng):
    c={"pass":0,"fail_dd":0,"fail_daily":0,"timeout":0}; payouts=0; pdays=[]
    for _ in range(sims):
        out,days,payout,ph=sim_challenge(pool,initial,rs,horizon,rng)
        c[out]+=1
        if out=="pass":
            pdays.append(days)
            if payout: payouts+=1
    n=sims; pr=c["pass"]/n; payr=payouts/n
    md=sorted(pdays)[len(pdays)//2] if pdays else None
    fails={k:v for k,v in c.items() if k!="pass"}
    top=max(fails,key=fails.get) if any(fails.values()) else None
    lbl={"fail_dd":"drawdown","fail_daily":"daily loss","timeout":"time/target not reached"}.get(top,"-")
    return {"firm":rs.firm,"product":rs.product,"pass":pr,"payout":payr,"median":md,"topfail":lbl,"rs":rs}

def verdict(r, fee, avg_day):
    pr=r["pass"]; payr=r["payout"]; tf=r["topfail"]
    att=(1/pr) if pr>0 else None
    cost=(fee*att) if att else None
    parts=[]
    if pr<0.02:
        parts.append("You practically cannot pass this firm.")
    elif tf.startswith("time"):
        parts.append("Risk is not your problem - REACHING THE TARGET is. Your edge points the right way but is too weak for this bar.")
        parts.append("Action: switch to a lower-target product (e.g. E8 at 8%), extend your time window, or strengthen your edge.")
    elif tf=="drawdown":
        parts.append("Risk management is eliminating you. Reduce position size or choose a firm with a wider drawdown allowance.")
    elif tf=="daily loss":
        parts.append("The daily loss limit is hitting you. Split your daily risk - avoid losing too much in a single day.")
    if payr<pr-0.03:
        parts.append("WARNING: Even if you pass, ~"+str(round((pr-payr)*100))+"% get denied at payout due to consistency rules. Spread your profit across days.")
    if att:
        parts.append("Expected: ~"+str(round(att,1))+" attempts"+(" (~$"+str(int(cost))+" cost)" if cost else "")+", median "+str(r["median"])+" days.")
    return " ".join(parts)

def headline(res, fee):
    best=max(res,key=lambda r:r["payout"])
    if best["payout"]<0.02:
        return ("SUMMARY: This strategy currently cannot pass ANY firm. The issue is not firm selection - it is edge. Strengthen your strategy before paying for a challenge.")
    att=(1/best["pass"]) if best["pass"]>0 else None
    msg="SUMMARY: Best match is "+best["firm"]+" "+best["product"]+" (payout ~"+str(round(best["payout"]*100))+"%)"+"."
    if att: msg+=" Still expect ~"+str(round(att,1))+" attempts, ~$"+str(int(fee*att))+" total cost."
    spread=max(r["payout"] for r in res)-min(r["payout"] for r in res)
    if spread>0.10:
        msg+=" Firm selection matters: "+str(round(spread*100))+"% gap between best and worst."
    return msg

def main():
    path=sys.argv[1] if len(sys.argv)>1 else "realistic_trades.csv"
    initial=100000.0; sims=5000; horizon=60; fee=550.0
    days=load_days(path); pool=days; nets=[d[0] for d in days]
    avg=sum(nets)/len(nets); rng=random.Random(42)
    print("Days: "+str(len(days))+" | daily avg: "+str(round(avg,1))
          +" | avg intraday low: "+str(round(sum(d[1] for d in days)/len(days),1)))
    print("Sims: "+str(sims)+" | horizon: "+str(horizon)+" days | assumed fee: $"+str(int(fee)))
    res=[run_firm(pool,initial,rs,sims,horizon,rng) for rs in RULESETS]
    res.sort(key=lambda r:r["payout"],reverse=True)
    print("\n"+headline(res,fee)+"\n")
    print("FIRM / PRODUCT".ljust(40)+"PASS".ljust(8)+"PAYOUT".ljust(8)+"MED.DAYS".ljust(9)+"TOP FAIL")
    print("-"*82)
    for r in res:
        print((r["firm"]+" "+r["product"]).ljust(40)
              +(str(round(r["pass"]*100,1))+"%").ljust(8)
              +(str(round(r["payout"]*100,1))+"%").ljust(8)
              +(str(r["median"]) if r["median"] else "-").ljust(9)+r["topfail"])
    print("\nADVISOR VERDICT (per firm):")
    for r in res:
        print("  * "+r["firm"]+" "+r["product"]+":")
        print("      "+verdict(r,fee,avg))

if __name__=="__main__": main()
