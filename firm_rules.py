from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from datetime import date
from typing import Optional


class DrawdownType(Enum):
    STATIC = "static"
    TRAILING_EOD = "trailing_eod"
    TRAILING_INTRADAY = "trailing_intraday"


class DailyLossBasis(Enum):
    NONE = "none"
    BALANCE_SOD = "balance_start_of_day"
    PREV_CLOSE_MAX = "prev_close_balance_or_equity_max"


class DailyLossEffect(Enum):
    BREACH = "breach"
    PAUSE = "pause"
    NONE = "none"


class ConsistencyType(Enum):
    NONE = "none"
    BEST_DAY_PCT = "best_day_pct_of_profit"


@dataclass
class PhaseRule:
    name: str
    profit_target_pct: Optional[float]
    min_trading_days: int = 0
    min_profitable_days: int = 0
    profitable_day_threshold_pct: float = 0.0


@dataclass
class RuleSet:
    firm: str
    product: str
    asset_class: str
    phases: list
    max_drawdown_pct: float
    drawdown_type: DrawdownType
    daily_loss_pct: Optional[float]
    daily_loss_basis: DailyLossBasis
    daily_loss_effect: DailyLossEffect
    consistency_type: ConsistencyType = ConsistencyType.NONE
    consistency_pct: Optional[float] = None
    consistency_applies_eval: bool = False
    consistency_applies_funded: bool = True
    time_limit_days: Optional[int] = None
    inactivity_expiry_days: Optional[int] = None
    news_trading_allowed: bool = True
    weekend_holding_allowed: bool = True
    profit_split_start: float = 0.80
    us_allowed: bool = True
    last_verified: Optional[date] = None
    source_url: str = ""
    notes: str = ""
    needs_verification: list = field(default_factory=list)


MODEL_LIMITS = [
    "Gunluk zarar gun-sonu equity uzerinden kontrol ediliyor; gun-ici dip modellenmiyor.",
    "Trailing drawdown'da kar hedefine ulasinca taban kilitlenir nuansi basitlestirildi.",
    "Cok fazli challenge'larda tek equity egrisi = tek faz varsayiliyor.",
    "Haber/hafta-sonu/yasak-strateji kurallari bayrak olarak tutuluyor, otomatik kontrol yok.",
]


V = date(2026, 6, 4)

RULESETS = [
    RuleSet(
        firm="FTMO", product="2-Step Challenge", asset_class="cfd_forex",
        phases=[
            PhaseRule("Challenge", 0.10, min_trading_days=4),
            PhaseRule("Verification", 0.05, min_trading_days=4),
        ],
        max_drawdown_pct=0.10, drawdown_type=DrawdownType.STATIC,
        daily_loss_pct=0.05, daily_loss_basis=DailyLossBasis.BALANCE_SOD,
        daily_loss_effect=DailyLossEffect.BREACH,
        consistency_type=ConsistencyType.NONE,
        time_limit_days=None, profit_split_start=0.80,
        last_verified=V, source_url="https://ftmo.com/en/trading-objectives/",
        notes="Statik %10 taban = affedici.",
        needs_verification=["us_allowed"],
    ),
    RuleSet(
        firm="FTMO", product="1-Step Challenge", asset_class="cfd_forex",
        phases=[PhaseRule("Challenge", 0.10, min_trading_days=4)],
        max_drawdown_pct=0.10, drawdown_type=DrawdownType.TRAILING_INTRADAY,
        daily_loss_pct=0.03, daily_loss_basis=DailyLossBasis.BALANCE_SOD,
        daily_loss_effect=DailyLossEffect.BREACH,
        consistency_type=ConsistencyType.BEST_DAY_PCT, consistency_pct=None,
        consistency_applies_eval=False, consistency_applies_funded=True,
        time_limit_days=None, profit_split_start=0.90,
        last_verified=V, source_url="https://ftmo.com/en/trading-objectives/",
        notes="Subat 2026'da cikti. Gunluk zarar %3, trailing taban.",
        needs_verification=["Best Day yuzdesi", "trailing kilit esigi"],
    ),
    RuleSet(
        firm="FundedNext", product="Stellar 2-Step (CFD)", asset_class="cfd_forex",
        phases=[
            PhaseRule("Challenge", 0.10, min_trading_days=5),
            PhaseRule("Verification", 0.06, min_trading_days=5),
        ],
        max_drawdown_pct=0.10, drawdown_type=DrawdownType.STATIC,
        daily_loss_pct=0.05, daily_loss_basis=DailyLossBasis.BALANCE_SOD,
        daily_loss_effect=DailyLossEffect.BREACH,
        consistency_type=ConsistencyType.NONE,
        time_limit_days=None, profit_split_start=0.80,
        last_verified=V, source_url="https://fundednext.com/",
        notes="CFD ve Futures tarafi ayri. Consistency %40 yalniz Futures'ta.",
        needs_verification=["Faz-2 hedefi (%5 mi %6 mi)", "min trading days"],
    ),
    RuleSet(
        firm="The5ers", product="New High Stakes (2-Step)", asset_class="cfd_forex",
        phases=[
            PhaseRule("Phase 1", 0.10, min_profitable_days=3, profitable_day_threshold_pct=0.005),
            PhaseRule("Phase 2", 0.05, min_profitable_days=3, profitable_day_threshold_pct=0.005),
        ],
        max_drawdown_pct=0.10, drawdown_type=DrawdownType.STATIC,
        daily_loss_pct=0.05, daily_loss_basis=DailyLossBasis.PREV_CLOSE_MAX,
        daily_loss_effect=DailyLossEffect.BREACH,
        consistency_type=ConsistencyType.NONE,
        time_limit_days=None, inactivity_expiry_days=30,
        news_trading_allowed=False, profit_split_start=0.80, us_allowed=False,
        last_verified=V, source_url="https://help.the5ers.com/",
        notes="New %10/%5, Classic %8/%5. ABD yasak.",
        needs_verification=["Classic vs New"],
    ),
    RuleSet(
        firm="E8 Markets", product="E8 One (1-Step, preset)", asset_class="cfd_forex",
        phases=[PhaseRule("Challenge", 0.08, min_trading_days=0)],
        max_drawdown_pct=0.08, drawdown_type=DrawdownType.TRAILING_INTRADAY,
        daily_loss_pct=0.05, daily_loss_basis=DailyLossBasis.BALANCE_SOD,
        daily_loss_effect=DailyLossEffect.BREACH,
        consistency_type=ConsistencyType.BEST_DAY_PCT, consistency_pct=0.40,
        consistency_applies_eval=False, consistency_applies_funded=True,
        time_limit_days=None, inactivity_expiry_days=60, profit_split_start=0.80,
        last_verified=V, source_url="https://help.e8markets.com/",
        notes="E8 One cok ozellestirilebilir. Buradaki degerler temsili preset.",
        needs_verification=["Checkout parametreleri", "preset degerler"],
    ),
    RuleSet(
        firm="Apex", product="EOD 50K Evaluation (Futures)", asset_class="futures",
        phases=[PhaseRule("Evaluation", 0.06, min_trading_days=0)],
        max_drawdown_pct=0.05, drawdown_type=DrawdownType.TRAILING_EOD,
        daily_loss_pct=None, daily_loss_basis=DailyLossBasis.NONE,
        daily_loss_effect=DailyLossEffect.NONE,
        consistency_type=ConsistencyType.BEST_DAY_PCT, consistency_pct=0.50,
        consistency_applies_eval=False, consistency_applies_funded=True,
        time_limit_days=30, profit_split_start=1.00,
        last_verified=V, source_url="https://help.apextraderfunding.com/",
        notes="Apex 4.0 (Mart 2026) 7-gun minimumu kaldirdi. EOD trailing varsayilan.",
        needs_verification=["Consistency %30 mu %50 mi (KAYNAKLAR CELISIYOR)", "50K hedef/esik"],
    ),
]


@dataclass
class DayRecord:
    day: int
    pnl: float
    eod_equity: float


@dataclass
class EvalResult:
    firm: str
    product: str
    target_met: bool
    breached: bool
    breach_reasons: list
    days_met: bool
    consistency_ok: bool
    final_profit_pct: float
    distance_to_breach_pct: float
    payout_eligible: bool
    warnings: list


def evaluate_against_ruleset(records, initial, rs):
    phase = rs.phases[0]
    breaches = []
    warnings = []

    if rs.drawdown_type == DrawdownType.STATIC:
        floors = [initial * (1 - rs.max_drawdown_pct)] * len(records)
    else:
        floors = []
        peak = initial
        for r in records:
            peak = max(peak, r.eod_equity)
            floors.append(peak - initial * rs.max_drawdown_pct)

    min_cushion = float("inf")
    prev_eq = initial
    for i, r in enumerate(records):
        cushion = (r.eod_equity - floors[i]) / initial
        min_cushion = min(min_cushion, cushion)
        if r.eod_equity < floors[i]:
            breaches.append("Gun " + str(r.day) + ": max drawdown tabani asildi.")
        if rs.daily_loss_basis != DailyLossBasis.NONE and rs.daily_loss_pct:
            limit = prev_eq - initial * rs.daily_loss_pct
            if r.eod_equity < limit:
                if rs.daily_loss_effect == DailyLossEffect.BREACH:
                    breaches.append("Gun " + str(r.day) + ": gunluk zarar limiti asildi.")
                elif rs.daily_loss_effect == DailyLossEffect.PAUSE:
                    warnings.append("Gun " + str(r.day) + ": gunluk pause tetiklendi (ihlal degil).")
        prev_eq = r.eod_equity

    final_profit = (records[-1].eod_equity - initial) / initial if records else 0.0
    target_met = phase.profit_target_pct is None or final_profit >= phase.profit_target_pct

    days_met = len(records) >= phase.min_trading_days
    if phase.min_profitable_days:
        prof_days = sum(1 for r in records if r.pnl >= initial * phase.profitable_day_threshold_pct)
        days_met = days_met and prof_days >= phase.min_profitable_days

    consistency_ok = True
    if rs.consistency_type == ConsistencyType.BEST_DAY_PCT and final_profit > 0:
        total_profit = records[-1].eod_equity - initial
        best_day = max((r.pnl for r in records), default=0)
        pct = rs.consistency_pct or 0
        if pct and total_profit > 0 and best_day > pct * total_profit:
            consistency_ok = False
            scope = "eval+funded" if rs.consistency_applies_eval else "yalniz funded"
            warnings.append("Consistency asildi (en iyi gun > %" + str(int(pct*100)) + " toplam kar; " + scope + ").")

    breached = len(breaches) > 0
    payout_eligible = target_met and not breached and days_met and (consistency_ok or not rs.consistency_applies_funded)

    return EvalResult(
        firm=rs.firm, product=rs.product,
        target_met=target_met, breached=breached, breach_reasons=breaches,
        days_met=days_met, consistency_ok=consistency_ok,
        final_profit_pct=final_profit,
        distance_to_breach_pct=min_cushion if min_cushion != float("inf") else 0.0,
        payout_eligible=payout_eligible, warnings=warnings,
    )


def compare_firms(records, initial, rulesets=RULESETS):
    results = [evaluate_against_ruleset(records, initial, rs) for rs in rulesets]
    return sorted(results, key=lambda r: (not r.payout_eligible, -r.distance_to_breach_pct))


if __name__ == "__main__":
    initial = 100000.0
    daily_pnls = [3200, 1500, 2600, -3800, 1900, 1800]
    eq = initial
    recs = []
    for i, p in enumerate(daily_pnls, 1):
        eq += p
        recs.append(DayRecord(day=i, pnl=p, eod_equity=eq))

    print("Baslangic: " + str(int(initial)) + "  Son: " + str(int(eq)) + "  (" + str(round((eq-initial)/initial*100, 1)) + "%)")
    print("")
    print("FIRMA / URUN".ljust(42) + "GECER?".ljust(8) + "ODEME?".ljust(8) + "TABANA PAY")
    print("-" * 72)
    for r in compare_firms(recs, initial):
        gec = "EVET" if (r.target_met and not r.breached and r.days_met) else "HAYIR"
        ode = "EVET" if r.payout_eligible else "HAYIR"
        print((r.firm + " " + r.product).ljust(42) + gec.ljust(8) + ode.ljust(8) + str(round(r.distance_to_breach_pct*100, 1)) + "%")
        for b in r.breach_reasons:
            print("    x " + b)
        for w in r.warnings:
            print("    ! " + w)

    print("")
    print("=" * 72)
    print("MOTORUN MODELLEYEMEDIGI SEYLER:")
    for lim in MODEL_LIMITS:
        print("  - " + lim)
    print("")
    print("TEYIT GEREKTIREN ALANLAR:")
    for rs in RULESETS:
        if rs.needs_verification:
            print("  [" + rs.firm + " " + rs.product + "] dogrulama: " + str(rs.last_verified))
            for nv in rs.needs_verification:
                print("      - " + nv)
