import csv, sys
from datetime import datetime, timedelta
from firm_rules import DayRecord, compare_firms, MODEL_LIMITS, RULESETS

DATE_HINTS=["close time","closing time","close_time","closetime","exit time","time","date"]
PROFIT_HINTS=["net profit","net usd","net","profit","p/l","pnl","realized p/l","result","gain","profit/loss"]

def detect_columns(header):
    low=[h.strip().lower() for h in header]
    def find(hints):
        for hint in hints:
            for i,h in enumerate(low):
                if hint==h: return i
        for hint in hints:
            for i,h in enumerate(low):
                if hint in h: return i
        return None
    return find(DATE_HINTS),find(PROFIT_HINTS)

DATE_FORMATS=["%Y.%m.%d %H:%M:%S","%Y.%m.%d %H:%M","%Y.%m.%d","%Y-%m-%d %H:%M:%S","%Y-%m-%d %H:%M",
    "%Y-%m-%d","%d.%m.%Y %H:%M:%S","%d.%m.%Y %H:%M","%d.%m.%Y","%m/%d/%Y %H:%M:%S","%m/%d/%Y",
    "%d/%m/%Y %H:%M:%S","%d/%m/%Y"]

def parse_date(s):
    s=s.strip()
    for fmt in DATE_FORMATS:
        try: return datetime.strptime(s,fmt).date()
        except ValueError: pass
    return None

def parse_float(s):
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
    except ValueError: return None

def load_trades_csv(path):
    trades=[]; issues=[]; skipped=0
    with open(path,"r",encoding="utf-8-sig",newline="") as f:
        sample=f.read(4096); f.seek(0)
        try: dialect=csv.Sniffer().sniff(sample,delimiters=",;\t")
        except csv.Error: dialect=csv.excel
        rows=list(csv.reader(f,dialect))
    if not rows:
        issues.append("ERROR: CSV is empty."); return trades,issues
    header=rows[0]; date_idx,profit_idx=detect_columns(header)
    if date_idx is None or profit_idx is None:
        issues.append("ERROR: Could not find date and/or profit columns. Header: "+str(header))
        issues.append("       Expected column names: 'Close Time'/'Date' for date, 'Profit'/'Net'/'P/L' for profit.")
        return trades,issues
    issues.append("Detected columns -> date: '"+header[date_idx]+"', profit: '"+header[profit_idx]+"'")
    for n,row in enumerate(rows[1:],start=2):
        if len(row)<=max(date_idx,profit_idx): skipped+=1; continue
        d=parse_date(row[date_idx]); p=parse_float(row[profit_idx])
        if d is None or p is None: skipped+=1; continue
        trades.append((d,p))
    if skipped:
        issues.append("WARNING: "+str(skipped)+" rows could not be parsed (date/profit). Skipped.")
    return trades,issues

def trades_to_daily(trades, initial):
    daily={}
    for d,p in trades: daily[d]=daily.get(d,0.0)+p
    days_sorted=sorted(daily.keys()); recs=[]; eq=initial
    for i,d in enumerate(days_sorted,start=1):
        eq+=daily[d]; recs.append(DayRecord(day=i,pnl=daily[d],eod_equity=eq))
    return recs,days_sorted

def data_quality_report(trades, days_sorted, initial):
    notes=[]
    if not trades: notes.append("ERROR: No valid trades."); return notes
    n_trades=len(trades); n_days=len(days_sorted)
    notes.append("Trades: "+str(n_trades)+" | Trading days: "+str(n_days)
                 +" | Date range: "+str(days_sorted[0])+" -> "+str(days_sorted[-1]))
    max_min_days=max((ph.min_trading_days for rs in RULESETS for ph in rs.phases),default=0)
    if n_days<max_min_days:
        notes.append("WARNING: Only "+str(n_days)+" trading days; some firms require min "+str(max_min_days)+". Results may be unreliable.")
    gaps=[]
    for a,b in zip(days_sorted,days_sorted[1:]):
        delta=(b-a).days
        if delta>4: gaps.append(str(a)+" -> "+str(b)+" ("+str(delta)+" days)")
    if gaps:
        notes.append("WARNING: Large calendar gaps (possible missing data): "+"; ".join(gaps[:5])+(" ..." if len(gaps)>5 else ""))
    daily={}
    for d,p in trades: daily[d]=daily.get(d,0.0)+p
    best=max(daily.values())
    if best>initial*0.10:
        notes.append("WARNING: One day gained "+str(round(best/initial*100,1))+"% of initial balance. May trigger consistency rules (or data error).")
    profits=[p for _,p in trades]
    if all(p==0 for p in profits):
        notes.append("WARNING: All profit values are 0. Wrong column may have been read.")
    if n_trades<20:
        notes.append("NOTE: "+str(n_trades)+" trades is low; statistical confidence is limited. This matters even more at the Monte Carlo stage.")
    return notes

def write_sample_csv(path):
    from datetime import datetime as dt
    base=dt(2026,5,4)
    plan=[[1200,800,1200],[600,900],[1500,1100],[-2000,-1800],[700,1200],[900,900],[1300,-400,600],[800,700]]
    rows=[["Close Time","Symbol","Profit"]]; day=0; added=0
    while added<len(plan):
        d=base+timedelta(days=day)
        if d.weekday()<5:
            for pnl in plan[added]:
                rows.append([d.strftime("%Y.%m.%d")+" 15:30:00","EURUSD",str(pnl)])
            added+=1
        day+=1
    with open(path,"w",encoding="utf-8",newline="") as f: csv.writer(f).writerows(rows)

def main():
    args=sys.argv[1:]; initial=100000.0
    if "--initial" in args:
        idx=args.index("--initial"); initial=float(args[idx+1]); args=args[:idx]+args[idx+2:]
    if args: path=args[0]; print("Reading CSV: "+path)
    else:
        path="sample_trades.csv"; write_sample_csv(path)
        print("No CSV provided -> sample created: "+path)
    trades,issues=load_trades_csv(path)
    for it in issues: print("  "+it)
    if not trades: print("No valid trades found, stopping."); return
    recs,days_sorted=trades_to_daily(trades,initial)
    print("\nDATA QUALITY:")
    for note in data_quality_report(trades,days_sorted,initial): print("  "+note)
    print("\nStart: "+str(int(initial))+"  End: "+str(int(recs[-1].eod_equity))
          +"  ("+str(round((recs[-1].eod_equity-initial)/initial*100,1))+"%)")
    print("\n"+"FIRM / PRODUCT".ljust(42)+"PASS?".ljust(8)+"PAYOUT?".ljust(8)+"CUSHION")
    print("-"*72)
    for r in compare_firms(recs,initial):
        p="YES" if (r.target_met and not r.breached and r.days_met) else "NO"
        o="YES" if r.payout_eligible else "NO"
        print((r.firm+" "+r.product).ljust(42)+p.ljust(8)+o.ljust(8)+str(round(r.distance_to_breach_pct*100,1))+"%")
        for b in r.breach_reasons: print("    x "+b)
        for w in r.warnings: print("    ! "+w)

if __name__=="__main__": main()
