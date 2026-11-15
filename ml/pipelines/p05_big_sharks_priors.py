"""Stage 05 — derive holding priors from the Big Sharks dataset.

The PRD treats Big Sharks as a schema reference only. It can do more than
that. After mapping its company names onto NSE symbols it yields two
empirical distributions worth borrowing for the synthetic cohort:

  * which Indian stocks investors actually concentrate in, and
  * how concentrated real portfolios are (the distribution of HHI).

Sampling synthetic holdings from observed popularity rather than uniformly
makes the cohort look like real Indian portfolios instead of a random draw
from the NIFTY 50.

The obvious caveat, carried into the report: these are large and
institutional investors, not retail ones. Their *holding preferences* are a
defensible prior for which large-cap names are widely held. Their position
sizes are not, and are used only as a loose shape for the concentration
distribution.

Run:  python -m ml.pipelines.p05_big_sharks_priors
"""

from __future__ import annotations

import json
import re

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

from .common import (
    BIG_SHARKS_CSV,
    KAGGLE_NSE_DIR,
    PROCESSED_DIR,
    PipelineError,
    Stage,
    get_logger,
    load_universe,
    read_tabular,
    write_report,
)

log = get_logger("sharks")

# Corporate suffixes and filler words that carry no identifying information.
NOISE_WORDS = {
    "ltd", "limited", "the", "india", "indian", "co", "corp", "corporation",
    "company", "pvt", "private", "inc", "plc", "and", "of",
}

FUZZY_ACCEPT_SCORE = 88  # below this a match is more likely wrong than right


def normalise_company(name: str) -> str:
    """Reduce a company name to a comparable key."""
    text = str(name).lower().replace("_", " ").replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    tokens = [t for t in text.split() if t and t not in NOISE_WORDS]
    return "".join(tokens)


def build_symbol_map(sharks: pd.DataFrame, symbols: pd.DataFrame) -> tuple[dict, dict]:
    """Map Big Sharks company names onto NSE symbols.

    Exact normalised matching first, then fuzzy matching for the remainder
    with a score floor. Anything below the floor is left unmapped rather
    than guessed: a wrong mapping silently attributes one company's holdings
    to another.
    """
    lookup: dict[str, str] = {}
    for _, row in symbols.iterrows():
        key = normalise_company(row["Company Name"])
        lookup.setdefault(key, row["Scrip"])

    names = sorted(sharks["Stock"].dropna().unique())
    mapping: dict[str, str] = {}
    exact = fuzzy = 0
    unmatched: list[str] = []

    candidates = list(lookup)
    for name in names:
        key = normalise_company(name)
        if key in lookup:
            mapping[name] = lookup[key]
            exact += 1
            continue

        best = process.extractOne(key, candidates, scorer=fuzz.ratio)
        if best and best[1] >= FUZZY_ACCEPT_SCORE:
            mapping[name] = lookup[best[0]]
            fuzzy += 1
        else:
            unmatched.append(name)

    stats = {
        "total_names": len(names),
        "exact_matches": exact,
        "fuzzy_matches": fuzzy,
        "unmatched": len(unmatched),
        "match_rate": round((exact + fuzzy) / len(names), 4) if names else 0.0,
        "fuzzy_threshold": FUZZY_ACCEPT_SCORE,
        "unmatched_sample": unmatched[:20],
    }
    return mapping, stats


def main() -> None:
    if not BIG_SHARKS_CSV.exists():
        raise PipelineError(f"Big Sharks file not found at {BIG_SHARKS_CSV}")

    symbols_path = KAGGLE_NSE_DIR / "NSE Symbols.CSV"
    if not symbols_path.exists():
        raise PipelineError(f"NSE symbol master not found at {symbols_path}")

    report: dict = {}

    with Stage(log, "load Big Sharks holdings"):
        sharks = read_tabular(BIG_SHARKS_CSV)
        symbols = read_tabular(symbols_path)
        log.info("  %d holdings rows, %d investors, %d distinct stocks",
                 len(sharks), sharks["Investor"].nunique(), sharks["Stock"].nunique())
        log.info("  %d NSE symbols in the master list", len(symbols))

    with Stage(log, "map company names to NSE symbols"):
        mapping, stats = build_symbol_map(sharks, symbols)
        report["symbol_mapping"] = stats
        log.info("  exact %d, fuzzy %d, unmatched %d → %.1f%% mapped",
                 stats["exact_matches"], stats["fuzzy_matches"],
                 stats["unmatched"], 100 * stats["match_rate"])

    with Stage(log, "derive holding popularity"):
        sharks["symbol"] = sharks["Stock"].map(mapping)
        mapped = sharks.dropna(subset=["symbol"]).copy()

        universe = load_universe()
        investable = set(
            universe.loc[
                (universe.status == "active") & (universe.asset_class == "equity"), "symbol"
            ]
        )

        popularity = (
            mapped.groupby("symbol")["Investor"].nunique().rename("n_investors").reset_index()
        )
        popularity["in_mvp_universe"] = popularity["symbol"].isin(investable)

        in_universe = popularity[popularity.in_mvp_universe].copy()
        # Sampling weight. The +1 keeps a universe member that no big
        # investor happens to hold from being impossible to draw.
        in_universe["weight"] = in_universe["n_investors"] + 1
        in_universe["weight"] /= in_universe["weight"].sum()
        in_universe = in_universe.sort_values("weight", ascending=False)

        log.info("  %d of %d MVP equity symbols appear in Big Sharks",
                 len(in_universe), len(investable))
        log.info("  most widely held: %s",
                 ", ".join(in_universe.head(5)["symbol"].tolist()))

        # Universe members absent from Big Sharks still need a weight.
        missing = sorted(investable - set(in_universe["symbol"]))
        if missing:
            floor = float(in_universe["weight"].min()) if len(in_universe) else 1.0
            extra = pd.DataFrame({
                "symbol": missing, "n_investors": 0,
                "in_mvp_universe": True, "weight": floor,
            })
            in_universe = pd.concat([in_universe, extra], ignore_index=True)
            in_universe["weight"] /= in_universe["weight"].sum()
            log.info("  %d universe symbols unseen in Big Sharks given a floor weight",
                     len(missing))

    with Stage(log, "derive the concentration distribution"):
        # Each investor's portfolio concentration, as a shape to sample from.
        def hhi_of(group: pd.DataFrame) -> float:
            values = group["Holding_Value_in_Cr"].astype(float)
            values = values[values > 0]
            if values.empty:
                return float("nan")
            weights = values / values.sum()
            return float((weights ** 2).sum())

        per_investor = (
            mapped.groupby("Investor")[["Holding_Value_in_Cr"]]
            .apply(lambda g: pd.Series({
                "hhi": hhi_of(g), "n_holdings": int((g["Holding_Value_in_Cr"] > 0).sum()),
            }))
            .dropna()
        )

        report["concentration"] = {
            "investors": int(len(per_investor)),
            "hhi": {
                "p10": round(float(per_investor.hhi.quantile(0.10)), 4),
                "median": round(float(per_investor.hhi.median()), 4),
                "p90": round(float(per_investor.hhi.quantile(0.90)), 4),
            },
            "n_holdings": {
                "p10": int(per_investor.n_holdings.quantile(0.10)),
                "median": int(per_investor.n_holdings.median()),
                "p90": int(per_investor.n_holdings.quantile(0.90)),
            },
            "caveat": (
                "Derived from large and institutional investors, not retail "
                "ones. Used as a loose shape for the synthetic concentration "
                "distribution, never as a retail benchmark."
            ),
        }
        log.info("  investor HHI: p10 %.3f, median %.3f, p90 %.3f",
                 report["concentration"]["hhi"]["p10"],
                 report["concentration"]["hhi"]["median"],
                 report["concentration"]["hhi"]["p90"])
        log.info("  holdings per investor: median %d",
                 report["concentration"]["n_holdings"]["median"])

    with Stage(log, "write priors"):
        in_universe[["symbol", "n_investors", "weight"]].to_csv(
            PROCESSED_DIR / "holding_popularity.csv", index=False
        )
        (PROCESSED_DIR / "sharks_symbol_map.json").write_text(json.dumps(mapping, indent=2))
        per_investor.round(4).to_csv(PROCESSED_DIR / "sharks_concentration.csv")
        write_report("big_sharks_priors", report)
        log.info("  → data/processed/holding_popularity.csv")


if __name__ == "__main__":
    main()
