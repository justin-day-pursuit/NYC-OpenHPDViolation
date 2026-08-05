"""
Hazard persistence + problem-type clustering (extends the Analysis journey).

What this script does (plain English):
  1) Compares how OLD currently open violations are by class (A/B/C/I),
     citywide and inside the top 200 buildings.
  2) Groups open-violation text (novdescription) into problem themes
     (pests, heat, lead, leaks, …) and compares theme rates in the top 200
     buildings versus the whole open inventory.
  3) Updates frontend/public/analysis/building_concentration.json
     (adds hazard_persistence + problem_type_clustering sections).

Prerequisites:
  - Run run_building_concentration.py at least once first (needs top-200 list).
  - SOCRATA_APP_TOKEN in the project-root .env file.

How a non-technical maintainer re-runs this:
  cd notebooks
  source .venv/bin/activate
  python run_hazard_theme_analysis.py
  # usually 2–5 minutes, then reload the website

IMPORTANT: Open HPD Violations only; counts use distinct violationid.
"""

from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from soda_live import _soda_get, load_socrata_settings, make_client  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "frontend" / "public" / "analysis" / "building_concentration.json"
MIN_YEAR = 1980
NOW = datetime.now(timezone.utc)

# Theme rules: first match wins for “primary” theme assignment.
# Citywide rates use SODA LIKE counts (a row can match several themes).
THEME_RULES: list[tuple[str, str, str]] = [
    ("lead_paint_hazard", r"lead-based paint|lead based paint|lead content|lead hazard|§ 27-2056", "Lead-paint hazard"),
    ("heat_hot_water", r"\bheat\b|hot water|boiler|heating system|no heat", "Heat / hot water"),
    ("pests", r"roach|mice|mouse|vermin|infestation|\bpest|insect|bedbug|bed bug|\brats?\b", "Pests / infestation"),
    ("mold_moisture", r"\bmold\b|mildew|moisture|\bdamp\b", "Mold / moisture"),
    ("water_leak_plumbing", r"\bleak|water damage|flood|plumbing|\bpipe\b", "Water leak / plumbing"),
    ("smoke_co_detector", r"smoke detect|carbon monoxide|co detect", "Smoke / CO detector"),
    ("fire_egress_doors", r"egress|fire escape|self-closing|self closing", "Fire egress / doors"),
    ("paint_surfaces", r"paint with light colored|peeling paint|§ 27-2013|adm code paint", "Paint / surfaces (non-lead)"),
    ("registration_vacate", r"registration statement|vacated by the department|cannot be reoccupied", "Registration / vacate"),
    ("garbage_housekeeping", r"garbage|refuse|housekeep|debris|filth|rubbish", "Garbage / housekeeping"),
]

THEME_LABELS = {k: lab for k, _, lab in THEME_RULES}
THEME_LABELS["other_unmatched"] = "Other / unmatched"

# LIKE token sets for citywide counts (tighter than a single fuzzy word)
CITY_LIKE_TOKENS: dict[str, list[str]] = {
    "lead_paint_hazard": ["%LEAD%"],
    "heat_hot_water": ["%HEAT%", "%HOT WATER%", "%BOILER%"],
    "pests": [
        "%ROACH%",
        "%MICE%",
        "%MOUSE%",
        "%VERMIN%",
        "%INFESTATION%",
        "%BEDBUG%",
        "%BED BUG%",
        "% RATS %",
        "%RAT INFEST%",
    ],
    "mold_moisture": ["%MOLD%", "%MILDEW%"],
    "water_leak_plumbing": ["%LEAK%", "%PLUMBING%", "%WATER DAMAGE%"],
    "smoke_co_detector": ["%SMOKE DETECT%", "%CARBON MONOXIDE%"],
    "fire_egress_doors": ["%EGRESS%", "%FIRE ESCAPE%", "%SELF-CLOSING%", "%SELF CLOSING%"],
    "paint_surfaces": ["%27-2013%", "%LIGHT COLORED PAINT%", "%PEELING PAINT%"],
    "registration_vacate": ["%REGISTRATION STATEMENT%", "%VACATED BY THE DEPARTMENT%"],
    "garbage_housekeeping": ["%GARBAGE%", "%REFUSE%", "%HOUSEKEEP%", "%RUBBISH%"],
}


def theme_hits(text: str) -> list[str]:
    t = (text or "").lower()
    hits = [key for key, pat, _ in THEME_RULES if re.search(pat, t)]
    return hits or ["other_unmatched"]


def primary_theme(text: str) -> str:
    hits = set(theme_hits(text))
    for key, _, _ in THEME_RULES:
        if key in hits:
            return key
    return "other_unmatched"


def persistence_stats(year_class_map: dict[int, Counter]) -> dict[str, Any]:
    total: Counter = Counter()
    before = {2015: Counter(), 2020: Counter(), 2022: Counter(), 2024: Counter()}
    years_sorted = sorted(year_class_map)
    for y in years_sorted:
        for cls, c in year_class_map[y].items():
            total[cls] += c
            for cut in before:
                if y < cut:
                    before[cut][cls] += c
    med_year: dict[str, int | None] = {}
    for cls in ["A", "B", "C", "I"]:
        t = total[cls]
        if not t:
            med_year[cls] = None
            continue
        cum = 0
        med_year[cls] = years_sorted[-1]
        for y in years_sorted:
            cum += year_class_map[y][cls]
            if cum >= t / 2:
                med_year[cls] = y
                break
    return {
        "totals": dict(total),
        "median_inspection_year": med_year,
        "share_before": {
            str(cut): {
                cls: round(ctr[cls] / total[cls], 4) if total[cls] else None
                for cls in ["A", "B", "C", "I"]
            }
            for cut, ctr in before.items()
        },
    }


def pull_top200_rows(client, dataset_id: str, building_ids: list[str]) -> list[dict]:
    """Download open rows for top buildings (deduped later by violationid)."""
    rows: list[dict] = []
    chunk = 25
    for i in range(0, len(building_ids), chunk):
        ids = building_ids[i : i + chunk]
        where = "(" + " OR ".join(f"buildingid='{b}'" for b in ids) + ")"
        offset = 0
        while True:
            batch = _soda_get(
                client,
                dataset_id,
                select="violationid,buildingid,class,inspectiondate,novdescription",
                where=where,
                limit=50000,
                offset=offset,
            )
            rows.extend(batch)
            if len(batch) < 50000:
                break
            offset += 50000
        if i % 50 == 0:
            print(f"  pulled buildings {i}/{len(building_ids)} rows={len(rows)}")
    # distinct violationid
    by_vid: dict[str, dict] = {}
    for r in rows:
        vid = str(r.get("violationid") or "")
        if vid and vid not in by_vid:
            by_vid[vid] = r
    return list(by_vid.values())


def main() -> None:
    if not OUT_PATH.exists():
        raise SystemExit(
            f"Missing {OUT_PATH}. Run run_building_concentration.py first."
        )

    data = json.loads(OUT_PATH.read_text())
    profiles = (data.get("top_building_structure") or {}).get("profiles_top200") or []
    if len(profiles) < 50:
        raise SystemExit(
            "JSON is missing top_building_structure.profiles_top200. "
            "Re-run run_building_concentration.py first."
        )
    top_ids = [str(p["buildingid"]) for p in profiles]

    cfg = load_socrata_settings()
    client = make_client(cfg)
    ds = cfg["dataset_id"]
    city_total = int(data["meta"]["distinct_violationid_count"])

    try:
        print("1) Citywide year × class…")
        yc_rows = _soda_get(
            client,
            ds,
            select="date_trunc_y(inspectiondate) as yr, class, count(distinct violationid) as c",
            group="yr, class",
            order="yr ASC",
            limit=500,
        )
        city_year_class: dict[int, Counter] = defaultdict(Counter)
        for r in yc_rows:
            try:
                y = int(str(r["yr"])[:4])
            except Exception:
                continue
            if y < MIN_YEAR or y > NOW.year:
                continue
            city_year_class[y][str(r["class"])] += int(r["c"])
        city_persist = persistence_stats(city_year_class)

        print("2) Top-200 open rows…")
        rows_top = pull_top200_rows(client, ds, top_ids)
        print(f"   deduped rows={len(rows_top)}")

        top_year_class: dict[int, Counter] = defaultdict(Counter)
        for r in rows_top:
            raw = r.get("inspectiondate")
            if not raw:
                continue
            try:
                y = int(str(raw)[:4])
            except Exception:
                continue
            if y < MIN_YEAR or y > NOW.year:
                continue
            top_year_class[y][str(r.get("class") or "?")] += 1
        top_persist = persistence_stats(top_year_class)

        persist_compare = []
        for cls in ["A", "B", "C", "I"]:
            persist_compare.append(
                {
                    "name": f"Class {cls}",
                    "citywide_share_pre_2020_pct": round(
                        100 * (city_persist["share_before"]["2020"][cls] or 0), 1
                    ),
                    "top200_share_pre_2020_pct": round(
                        100 * (top_persist["share_before"]["2020"][cls] or 0), 1
                    ),
                    "citywide_median_year": city_persist["median_inspection_year"][cls],
                    "top200_median_year": top_persist["median_inspection_year"][cls],
                }
            )

        print("3) Citywide theme LIKE counts…")
        city_theme_counts: dict[str, int] = {}
        for key, tokens in CITY_LIKE_TOKENS.items():
            where = "(" + " OR ".join(f"upper(novdescription) like '{t}'" for t in tokens) + ")"
            n = int(
                _soda_get(client, ds, select="count(distinct violationid) as n", where=where)[0][
                    "n"
                ]
            )
            city_theme_counts[key] = n
            print(f"   {key}: {n:,}")

        print("4) Top-200 theme mix…")
        top_theme: Counter = Counter()
        top_primary: Counter = Counter()
        c_primary: Counter = Counter()
        for r in rows_top:
            hits = theme_hits(r.get("novdescription"))
            for h in hits:
                if h != "other_unmatched" or len(hits) == 1:
                    top_theme[h] += 1
            prim = primary_theme(r.get("novdescription"))
            top_primary[prim] += 1
            if r.get("class") == "C":
                c_primary[prim] += 1

        theme_lift_bars = []
        for key, _, label in THEME_RULES:
            city_n = city_theme_counts.get(key, 0)
            top_n = top_theme.get(key, 0)
            city_share = city_n / city_total if city_total else 0
            top_share = top_n / len(rows_top) if rows_top else 0
            theme_lift_bars.append(
                {
                    "name": label,
                    "key": key,
                    "citywide_share_pct": round(100 * city_share, 2),
                    "citywide_count": city_n,
                    "top200_share_pct": round(100 * top_share, 2),
                    "top200_count": top_n,
                    "lift": round(top_share / city_share, 2) if city_share else None,
                }
            )
        theme_lift_bars.sort(key=lambda b: -(b["lift"] or 0))

        primary_bars = [
            {
                "name": THEME_LABELS[k],
                "key": k,
                "share_pct": round(100 * v / len(rows_top), 1),
                "count": v,
            }
            for k, v in top_primary.most_common()
        ]
        c_tot = sum(c_primary.values()) or 1
        c_primary_bars = [
            {
                "name": THEME_LABELS[k],
                "key": k,
                "share_pct": round(100 * v / c_tot, 1),
                "count": v,
            }
            for k, v in c_primary.most_common(8)
        ]

        city_b = city_persist["share_before"]["2020"]["B"]
        city_c = city_persist["share_before"]["2020"]["C"]
        top_b = top_persist["share_before"]["2020"]["B"]
        top_c = top_persist["share_before"]["2020"]["C"]

        hazard_finding = {
            "title": "Class B is the lingering open backlog — Class C turns over faster",
            "claim": (
                f"Open Class B violations are substantially older than open Class C: "
                f"{city_b:.0%} of citywide open Class B was inspected before 2020, versus "
                f"{city_c:.0%} of Class C (median inspection years "
                f"{city_persist['median_inspection_year']['B']} vs "
                f"{city_persist['median_inspection_year']['C']}). "
                f"In the top 200 buildings, open inventory is newer overall — but Class B "
                f"still ages out more slowly than Class C ({top_b:.0%} vs {top_c:.0%} pre-2020). "
                f"The stuck open book is Class B persistence, not Class C “hazard permanence.”"
            ),
            "why_non_obvious": (
                "It is natural to assume the most serious hazards (Class C) are what linger. "
                "The age profile of currently open violations shows the opposite: immediately "
                "hazardous opens recycle faster, while Class B accumulates as long-lived backlog — "
                "citywide and inside the highest-burden buildings."
            ),
            "metrics": {
                "citywide_share_pre_2020": city_persist["share_before"]["2020"],
                "top200_share_pre_2020": top_persist["share_before"]["2020"],
                "citywide_median_inspection_year": city_persist["median_inspection_year"],
                "top200_median_inspection_year": top_persist["median_inspection_year"],
                "top200_rows_analyzed": len(rows_top),
            },
            "method_note": (
                "Age uses inspectiondate year for distinct open violationid rows. "
                f"Years before {MIN_YEAR} are dropped as date-quality outliers. "
                "“Pre-2020” means inspection year ≤ 2019."
            ),
        }

        lifts = [b for b in theme_lift_bars if b.get("lift") is not None]
        top_lifts = lifts[:3]
        theme_finding = {
            "title": (
                "Chronic buildings over-index on moisture/leak problems; "
                "their Class C opens are pest-heavy"
            ),
            "claim": (
                f"Relative to the citywide open inventory, the top 200 buildings are enriched for "
                f"{top_lifts[0]['name']} ({top_lifts[0]['lift']}×), "
                f"{top_lifts[1]['name']} ({top_lifts[1]['lift']}×), and "
                f"{top_lifts[2]['name']} ({top_lifts[2]['lift']}×). "
                f"Separately, among Class C (immediately hazardous) opens in those buildings, "
                f"{c_primary_bars[0]['name']} is the leading primary theme at "
                f"{c_primary_bars[0]['share_pct']}% — not a uniform mix of hazards."
            ),
            "why_non_obvious": (
                "High open counts could just be “more of the same” problem mix. Instead, chronic "
                "buildings skew toward moisture/leak/paint-type issues versus the city, while their "
                "most serious (Class C) open inventory is concentrated in pest cases — a specific "
                "remediation and access problem, not generic volume."
            ),
            "metrics": {
                "theme_lifts_top200_vs_city": [
                    {
                        "key": b["key"],
                        "name": b["name"],
                        "lift": b["lift"],
                        "citywide_share_pct": b["citywide_share_pct"],
                        "top200_share_pct": b["top200_share_pct"],
                    }
                    for b in lifts
                ],
                "top200_primary_theme_leader": primary_bars[0] if primary_bars else None,
                "top200_class_c_primary_leader": c_primary_bars[0] if c_primary_bars else None,
            },
            "method_note": (
                "Themes are keyword matches on novdescription. Citywide rates use SODA LIKE "
                "counts over distinct violationid (a violation can match multiple themes). "
                "Top-200 rates use the same keyword rules on deduped open rows for those "
                "buildings. Primary theme = first matching rule in a fixed priority order."
            ),
        }

        data["hazard_persistence"] = {
            "finding": hazard_finding,
            "citywide": city_persist,
            "top200": top_persist,
            "charts": {"pre_2020_compare": persist_compare},
        }
        data["problem_type_clustering"] = {
            "finding": theme_finding,
            "theme_labels": THEME_LABELS,
            "charts": {
                "theme_lift_bars": theme_lift_bars,
                "top200_primary_themes": primary_bars,
                "top200_class_c_primary_themes": c_primary_bars,
            },
        }
        data["charts"]["pre_2020_by_class"] = [
            {
                "name": r["name"],
                "citywide": r["citywide_share_pre_2020_pct"],
                "top_200_buildings": r["top200_share_pre_2020_pct"],
            }
            for r in persist_compare
        ]
        data["charts"]["median_inspection_year_by_class"] = [
            {
                "name": f"Class {cls}",
                "citywide_median_year": city_persist["median_inspection_year"][cls],
                "top200_median_year": top_persist["median_inspection_year"][cls],
            }
            for cls in ["A", "B", "C", "I"]
        ]
        data["charts"]["theme_lift_bars"] = [
            {
                "name": b["name"],
                "citywide": b["citywide_share_pct"],
                "top_200_buildings": b["top200_share_pct"],
                "lift": b["lift"],
            }
            for b in theme_lift_bars
        ]
        data["charts"]["top200_primary_themes"] = [
            {"name": b["name"], "share_pct": b["share_pct"], "count": b["count"]}
            for b in primary_bars[:8]
        ]
        data["charts"]["top200_class_c_primary_themes"] = [
            {"name": b["name"], "share_pct": b["share_pct"], "count": b["count"]}
            for b in c_primary_bars
        ]

        data["headlines"]["class_b_pre_2020_city_pct"] = round(100 * city_b, 1)
        data["headlines"]["class_c_pre_2020_city_pct"] = round(100 * city_c, 1)
        data["headlines"]["class_b_pre_2020_top200_pct"] = round(100 * top_b, 1)
        data["headlines"]["class_c_pre_2020_top200_pct"] = round(100 * top_c, 1)
        data["headlines"]["top_theme_lift_name"] = top_lifts[0]["name"]
        data["headlines"]["top_theme_lift"] = top_lifts[0]["lift"]
        data["headlines"]["top200_class_c_top_theme"] = c_primary_bars[0]["name"]
        data["headlines"]["top200_class_c_top_theme_pct"] = c_primary_bars[0]["share_pct"]
        data["meta"]["hazard_theme_analyzed_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        )

        OUT_PATH.write_text(json.dumps(data, indent=2))
        print(f"Wrote {OUT_PATH}")
        print("Hazard:", hazard_finding["claim"][:220], "…")
        print("Themes:", theme_finding["claim"][:220], "…")
    finally:
        client.close()


if __name__ == "__main__":
    main()
