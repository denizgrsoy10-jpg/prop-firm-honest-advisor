from dataclasses import dataclass, field
from enum import Enum
from datetime import date
from typing import Optional

class DrawdownType(Enum):
    STATIC="static"; TRAILING_EOD="trailing_eod"; TRAILING_INTRADAY="trailing_intraday"
class DailyLossBasis(Enum):
    NONE="none"; BALANCE_SOD="balance_start_of_day"; PREV_CLOSE_MAX="prev_close_balance_or_equity_max"
class DailyLossEffect(Enum):
    BREACH="breach"; PAUSE="pause"; NONE="none"
class ConsistencyType(Enum):
    NONE="none"; BEST_DAY_PCT="best_day_pct_of_profit"

@dataclass
class PhaseRule:
    name:str; profit_target_pct:Optional[float]; min_trading_days:int=0
    min_profitable_days:int=0; profitable_day_threshold_pct:float=0.0
@dataclass
class RuleSet:
    firm:str; product:str; asset_class:str; phases:list
    max_drawdown_pct:float; drawdown_type:DrawdownType
    daily_loss_pct:Optional[float]; daily_loss_basis:DailyLossBasis; daily_loss_effect:DailyLossEffect
    consistency_type:ConsistencyType=ConsistencyType.NONE; consistency_pct:Optional[float]=None
    consistency_applies_eval:bool=False; consistency_applies_funded:bool=True
    time_limit_days:Optional[int]=None; inactivity_expiry_days:Optional[int]=None
    news_trading_allowed:bool=True; weekend_holding_allowed:bool=True
    profit_split_start:float=0.80; us_allowed:bool=True
    last_verified:Optional[date]=None; source_url:str=""; notes:str=""
    needs_verification:list=field(default_factory=list)

@dataclass
class DayRecord:
    day:int; pnl:float; eod_equity:float

@dataclass
class EvalResult:
    firm:str; product:str; target_met:bool; breached:bool; breach_reasons:list
    days_met:bool; consistency_ok:bool; final_profit_pct:float
    distance_to_breach_pct:float; payout_eligible:bool; warnings:list

MODEL_LIMITS = [
    "Daily loss is checked on end-of-day equity; intraday lows are not fully modeled.",
    "Trailing drawdown lock mechanics (FTMO 1-step, Apex safety net) are simplified.",
    "Multi-phase challenges use a single equity curve per phase.",
    "News/weekend/restricted-strategy rules are flagged but not auto-enforced.",
]

V=date(2026,6,4)
RULESETS=[
 RuleSet("FTMO","2-Step Challenge","cfd_forex",
   [PhaseRule("Challenge",0.10,min_trading_days=4),PhaseRule("Verification",0.05,min_trading_days=4)],
   0.10,DrawdownType.STATIC,0.05,DailyLossBasis.BALANCE_SOD,DailyLossEffect.BREACH,
   last_verified=V,source_url="https://ftmo.com/en/trading-objectives/",
   notes="Static 10% floor = forgiving; profit becomes permanent buffer.",
   needs_verification=["us_allowed (FTMO US access changes periodically)"]),
 RuleSet("FTMO","1-Step Challenge","cfd_forex",[PhaseRule("Challenge",0.10,min_trading_days=4)],
   0.10,DrawdownType.TRAILING_INTRADAY,0.03,DailyLossBasis.BALANCE_SOD,DailyLossEffect.BREACH,
   consistency_type=ConsistencyType.BEST_DAY_PCT,consistency_pct=None,profit_split_start=0.90,
   last_verified=V,source_url="https://ftmo.com/en/trading-objectives/",
   notes="Launched Feb 2026. Tighter 3% daily loss, trailing floor, Best Day rule.",
   needs_verification=["Best Day exact percentage","trailing lock threshold"]),
 RuleSet("FundedNext","Stellar 2-Step (CFD)","cfd_forex",
   [PhaseRule("Challenge",0.10,min_trading_days=5),PhaseRule("Verification",0.06,min_trading_days=5)],
   0.10,DrawdownType.STATIC,0.05,DailyLossBasis.BALANCE_SOD,DailyLossEffect.BREACH,
   last_verified=V,source_url="https://fundednext.com/",
   notes="CFD and Futures sides have separate rules. 40% consistency only on Futures.",
   needs_verification=["Phase 2 target (5% or 6%)","min trading days with add-on"]),
 RuleSet("The5ers","New High Stakes (2-Step)","cfd_forex",
   [PhaseRule("Phase 1",0.10,min_profitable_days=3,profitable_day_threshold_pct=0.005),
    PhaseRule("Phase 2",0.05,min_profitable_days=3,profitable_day_threshold_pct=0.005)],
   0.10,DrawdownType.STATIC,0.05,DailyLossBasis.PREV_CLOSE_MAX,DailyLossEffect.BREACH,
   inactivity_expiry_days=30,news_trading_allowed=False,us_allowed=False,
   last_verified=V,source_url="https://help.the5ers.com/",
   notes="New 10%/5%; Classic 8%/5%. US restricted. Restricted strategies (HFT, news, arb).",
   needs_verification=["Classic vs New product name"]),
 RuleSet("E8 Markets","E8 One (1-Step, preset)","cfd_forex",[PhaseRule("Challenge",0.08,min_trading_days=0)],
   0.08,DrawdownType.TRAILING_INTRADAY,0.05,DailyLossBasis.BALANCE_SOD,DailyLossEffect.BREACH,
   consistency_type=ConsistencyType.BEST_DAY_PCT,consistency_pct=0.40,inactivity_expiry_days=60,
   last_verified=V,source_url="https://help.e8markets.com/",
   notes="E8 One is highly customizable (DD 4-14%, daily 3-9.2%, target 6-21%). Values here are a representative preset.",
   needs_verification=["User's actual checkout parameters","preset defaults"]),
 RuleSet("Apex","EOD 50K Evaluation (Futures)","futures",[PhaseRule("Evaluation",0.06,min_trading_days=0)],
   0.05,DrawdownType.TRAILING_EOD,None,DailyLossBasis.NONE,DailyLossEffect.NONE,
   consistency_type=ConsistencyType.BEST_DAY_PCT,consistency_pct=0.50,time_limit_days=30,profit_split_start=1.00,
   last_verified=V,source_url="https://help.apextraderfunding.com/",
   notes="Apex 4.0 (Mar 2026) removed 7-day min. EOD trailing is default. ~95% of evals reportedly fail on trailing DD.",
   needs_verification=["Consistency 30% or 50% (SOURCES CONFLICT)","50K exact target/threshold"]),
]

def evaluate_against_ruleset(records, initial, rs):
    phase=rs.phases[0]; breaches=[]; warnings=[]
    if rs.drawdown_type==DrawdownType.STATIC:
        floors=[initial*(1-rs.max_drawdown_pct)]*len(records)
    else:
        floors=[]; peak=initial
        for r in records:
            peak=max(peak,r.eod_equity); floors.append(peak-initial*rs.max_drawdown_pct)
    min_cushion=float("inf"); prev_eq=initial
    for i,r in enumerate(records):
        cushion=(r.eod_equity-floors[i])/initial; min_cushion=min(min_cushion,cushion)
        if r.eod_equity<floors[i]:
            breaches.append("Day "+str(r.day)+": max drawdown floor breached.")
        if rs.daily_loss_basis!=DailyLossBasis.NONE and rs.daily_loss_pct:
            limit=prev_eq-initial*rs.daily_loss_pct
            if r.eod_equity<limit:
                if rs.daily_loss_effect==DailyLossEffect.BREACH:
                    breaches.append("Day "+str(r.day)+": daily loss limit breached.")
                elif rs.daily_loss_effect==DailyLossEffect.PAUSE:
                    warnings.append("Day "+str(r.day)+": daily pause triggered (not a breach).")
        prev_eq=r.eod_equity
    final_profit=(records[-1].eod_equity-initial)/initial if records else 0.0
    target_met=phase.profit_target_pct is None or final_profit>=phase.profit_target_pct
    days_met=len(records)>=phase.min_trading_days
    if phase.min_profitable_days:
        prof_days=sum(1 for r in records if r.pnl>=initial*phase.profitable_day_threshold_pct)
        days_met=days_met and prof_days>=phase.min_profitable_days
    consistency_ok=True
    if rs.consistency_type==ConsistencyType.BEST_DAY_PCT and final_profit>0:
        total_profit=records[-1].eod_equity-initial
        best_day=max((r.pnl for r in records),default=0)
        pct=rs.consistency_pct or 0
        if pct and total_profit>0 and best_day>pct*total_profit:
            consistency_ok=False
            scope="eval+funded" if rs.consistency_applies_eval else "funded only"
            warnings.append("Consistency exceeded (best day >"+str(int(pct*100))+"% of total profit; "+scope+").")
    breached=len(breaches)>0
    payout_eligible=target_met and not breached and days_met and (consistency_ok or not rs.consistency_applies_funded)
    return EvalResult(firm=rs.firm,product=rs.product,target_met=target_met,breached=breached,
        breach_reasons=breaches,days_met=days_met,consistency_ok=consistency_ok,
        final_profit_pct=final_profit,distance_to_breach_pct=min_cushion if min_cushion!=float("inf") else 0.0,
        payout_eligible=payout_eligible,warnings=warnings)

def compare_firms(records, initial, rulesets=None):
    if rulesets is None: rulesets=RULESETS
    results=[evaluate_against_ruleset(records,initial,rs) for rs in rulesets]
    return sorted(results,key=lambda r:(not r.payout_eligible,-r.distance_to_breach_pct))
