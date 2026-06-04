"""advisor.py - Hesap makinesini DANISMANA cevirir.
Eklenenler: gun-ici drawdown, cok-faz zincirleme, beklenen deneme/maliyet, karar cumlesi."""
import csv, random, sys
from datetime import datetime
from firm_rules import (RULESETS, DrawdownType, DailyLossBasis, DailyLossEffect,
                        ConsistencyType)

DATE_FORMATS = ["%Y.%m.%d %H:%M:%S","%Y.%m.%d %H:%M","%Y-%m-%d %H:%M:%S","%Y-%m-%d",
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
    for dt,p in trades:
        byday.setdefault(dt.date(),[]).append((dt,p))
    days=[]
    for d in sorted(byday):
        seq=[p for _,p in sorted(byday[d])]
        run=0.0; mn=0.0
        for p in seq:
            run+=p; mn=min(mn,run)
        days.append((round(run,2), round(mn,2)))
    return days

def sim_phase(draw, n, initial, phase, rs):
    eq=initial; peak=initial; prev=initial; td=0; pd_=0; best=0.0
    for _ in range(n):
        net,intramin = draw()
        td+=1
        low_eq = eq + intramin
        if rs.drawdown_type==DrawdownType.STATIC:
            floor=initial*(1-rs.max_drawdown_pct)
        else:
            floor=peak-initial*rs.max_drawdown_pct
        if low_eq < floor:
            return ("fail_dd",td,eq,best)
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
        if out!="pass":
            return (out,total_days,False,ph.name)
    payout=True
    if rs.consistency_type==ConsistencyType.BEST_DAY_PCT and rs.consistency_pct and total_profit>0:
        if best_overall>rs.consistency_pct*total_profit: payout=False
    payout = payout or not rs.consistency_applies_funded
    return ("pass",total_days,payout,None)

def run_firm(pool,initial,rs,sims,horizon,rng):
    c={"pass":0,"fail_dd":0,"fail_daily":0,"timeout":0}; payouts=0; pdays=[]
    for _ in range(sims):
        out,days,payout,ph=sim_challenge(pool,initial,rs,horizon,rng)
        c[out]+=1
        if out=="pass":
            pdays.append(days)
            if payout: payouts+=1
    n=sims
    pr=c["pass"]/n; payr=payouts/n
    md=sorted(pdays)[len(pdays)//2] if pdays else None
    fails={k:v for k,v in c.items() if k!="pass"}
    top=max(fails,key=fails.get) if any(fails.values()) else None
    lbl={"fail_dd":"drawdown","fail_daily":"gunluk zarar","timeout":"zaman/hedefe yetisememe"}.get(top,"-")
    return {"firm":rs.firm,"product":rs.product,"pass":pr,"payout":payr,"median":md,"topfail":lbl,"rs":rs}

def verdict(r, fee, avg_day):
    pr=r["pass"]; payr=r["payout"]; tf=r["topfail"]
    att = (1/pr) if pr>0 else None
    cost = (fee*att) if att else None
    parts=[]
    if pr<0.02:
        parts.append("Bu firmada pratikte gecemezsin.")
    elif tf.startswith("zaman"):
        parts.append("Seni risk degil, HEDEFE yetisememe eliyor. Edge'in yonu dogru ama bu barin altinda zayif.")
        parts.append("Yapilacak: daha dusuk hedefli urune gec (orn. E8 %8) ya da sure pencereni uzat / edge'i guclendir.")
    elif tf=="drawdown":
        parts.append("Risk yonetimi seni eliyor. Pozisyonlarini kucult ya da daha genis drawdown'li firma sec.")
    elif tf=="gunluk zarar":
        parts.append("Gunluk zarar limiti seni vuruyor. Gunluk riskini parcala, tek gunde cok kaybetme.")
    if payr < pr-0.03:
        parts.append("DIKKAT: gecsen bile consistency yuzunden odemede ~%"+str(round((pr-payr)*100))+" elenirsin; kari gunlere yay.")
    if att:
        parts.append("Beklenen: ~"+str(round(att,1))+" deneme"+(" (~"+str(int(cost))+" maliyet)" if cost else "")+", medyan "+str(r["median"])+" gun.")
    return " ".join(parts)

def headline(res, fee):
    best=max(res,key=lambda r:r["payout"])
    if best["payout"]<0.02:
        return ("OZET: Bu strateji su an HICBIR firmada gecmiyor. Sorun firma secimi degil, "
                "edge. Para vermeden once stratejini guclendir.")
    att=(1/best["pass"]) if best["pass"]>0 else None
    msg="OZET: En mantikli secim "+best["firm"]+" "+best["product"]+" (odeme ~%"+str(round(best["payout"]*100))+")."
    if att: msg+=" Yine de ortalama ~"+str(round(att,1))+" deneme, ~"+str(int(fee*att))+" beklenen maliyet."
    spread=max(r["payout"] for r in res)-min(r["payout"] for r in res)
    if spread>0.10:
        msg+=" Firma secimi onemli: en iyi ile en kotu arasinda %"+str(round(spread*100))+" fark var."
    return msg

def main():
    path=sys.argv[1] if len(sys.argv)>1 else "realistic_trades.csv"
    initial=100000.0; sims=5000; horizon=60; fee=550.0
    days=load_days(path)
    pool=days
    nets=[d[0] for d in days]
    avg=sum(nets)/len(nets)
    rng=random.Random(42)
    print("Gun: "+str(len(days))+" | gunluk ortalama: "+str(round(avg,1))
          +" | gun-ici dip ortalamasi: "+str(round(sum(d[1] for d in days)/len(days),1)))
    print("Sim: "+str(sims)+" | sure: "+str(horizon)+" gun | varsayilan ucret: "+str(int(fee)))
    print("")
    res=[run_firm(pool,initial,rs,sims,horizon,rng) for rs in RULESETS]
    res.sort(key=lambda r:r["payout"],reverse=True)
    print(headline(res,fee))
    print("")
    print("FIRMA / URUN".ljust(40)+"GECME".ljust(8)+"ODEME".ljust(8)+"MED.GUN".ljust(9)+"EN SIK BITIS")
    print("-"*82)
    for r in res:
        print((r["firm"]+" "+r["product"]).ljust(40)
              +("%"+str(round(r["pass"]*100,1))).ljust(8)
              +("%"+str(round(r["payout"]*100,1))).ljust(8)
              +(str(r["median"]) if r["median"] else "-").ljust(9)+r["topfail"])
    print("")
    print("DANISMAN GORUSU (her firma):")
    for r in res:
        print("  * "+r["firm"]+" "+r["product"]+":")
        print("      "+verdict(r,fee,avg))

if __name__=="__main__":
    main()
