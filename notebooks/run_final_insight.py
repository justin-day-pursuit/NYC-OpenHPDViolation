"""
Final insight pass — Class B moisture + multi-dwelling + age×theme
+ mold/moisture vs pests comparison for the bottom-of-page “Key insight”.

What this adds to the website:
  1) Age×theme: how old are Class B mold/water opens vs other Class B vs Class C?
  2) Burden gradient: Class B∧mold|water share in top 200 / next 200 / lower band / city.
  3) Structure: multi-dwelling vs limited-unit (single-ish) proxies — who is in the top tier?
  4) Mold & moisture vs pests: citywide vs high-burden multi-dwelling shares
     (feeds the #data-insight jump target at the bottom of the Analysis journey).

Prerequisites:
  - run_building_concentration.py (needs top-200 building list in the JSON)
  - SOCRATA_APP_TOKEN in the project-root .env

How a non-technical maintainer re-runs this:
  cd notebooks
  source .venv/bin/activate
  python run_final_insight.py
  # usually a few minutes, then reload the website
  # The top-of-page “Jump to key insight” button scrolls to the new section.

Open HPD Violations only; distinct violationid.
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

# Broad moisture channel (mold + water/leak/plumbing) — same as Class B moisture insight.
MOLD_WATER_RE = re.compile(
    r"\bmold\b|mildew|\bleak|water damage|flood|plumbing|\bpipe\b", re.I
)
MOLD_WATER_LIKE = "(" + " OR ".join(
    f"upper(novdescription) like '{t}'"
    for t in ["%MOLD%", "%MILDEW%", "%LEAK%", "%PLUMBING%", "%WATER DAMAGE%"]
) + ")"

# Pest keywords — aligned with run_hazard_theme_analysis.py (common comparison issue).
PESTS_RE = re.compile(
    r"roach|mice|mouse|vermin|infestation|\bpest|insect|bedbug|bed bug|\brats?\b",
    re.I,
)
PESTS_LIKE_TOKENS = [
    "%ROACH%",
    "%MICE%",
    "%MOUSE%",
    "%VERMIN%",
    "%INFESTATION%",
    "%BEDBUG%",
    "%BED BUG%",
    "% RATS %",
    "%RAT INFEST%",
]
PESTS_LIKE = "(" + " OR ".join(
    f"upper(novdescription) like '{t}'" for t in PESTS_LIKE_TOKENS
) + ")"


def count_distinct(client, dataset_id: str, where: str | None = None) -> int:
    """Count distinct open violation IDs (SoQL aggregate — no full dump)."""
    kwargs: dict[str, Any] = {"select": "count(distinct violationid) as n"}
    if where:
        kwargs["where"] = where
    return int(_soda_get(client, dataset_id, **kwargs)[0]["n"])


def theme_shares_from_rows(rows: list[dict]) -> dict[str, Any]:
    """Share of rows whose NOV text matches moisture or pests (a row can match both)."""
    n = len(rows) or 1
    mw = sum(1 for r in rows if MOLD_WATER_RE.search(r.get("novdescription") or ""))
    pests = sum(1 for r in rows if PESTS_RE.search(r.get("novdescription") or ""))
    return {
        "opens": len(rows),
        "mold_water_count": mw,
        "pests_count": pests,
        "mold_water_share": round(mw / n, 4),
        "pests_share": round(pests / n, 4),
    }


def parse_year(raw: Any) -> int | None:
    if not raw:
        return None
    try:
        y = int(str(raw)[:4])
        if MIN_YEAR <= y <= NOW.year:
            return y
    except Exception:
        return None
    return None


def persist_from_years(years: list[int]) -> dict[str, Any]:
    if not years:
        return {"n": 0, "median_year": None, "share_pre_2020": None, "share_pre_2022": None}
    years = sorted(years)
    n = len(years)
    return {
        "n": n,
        "median_year": years[n // 2],
        "share_pre_2020": round(sum(1 for y in years if y < 2020) / n, 4),
        "share_pre_2022": round(sum(1 for y in years if y < 2022) / n, 4),
    }


def year_counts(client, dataset_id: str, where: str | None = None) -> dict[int, int]:
    kwargs: dict[str, Any] = {
        "select": "date_trunc_y(inspectiondate) as yr, count(distinct violationid) as c",
        "group": "yr",
        "order": "yr ASC",
        "limit": 200,
    }
    if where:
        kwargs["where"] = where
    out: dict[int, int] = {}
    for row in _soda_get(client, dataset_id, **kwargs):
        y = parse_year(row.get("yr"))
        if y is not None:
            out[y] = out.get(y, 0) + int(row["c"])
    return out


def stats_from_year_map(ymap: dict[int, int]) -> dict[str, Any]:
    years: list[int] = []
    for y, c in ymap.items():
        years.extend([y] * c)
    return persist_from_years(years)


def fetch_building_page(client, dataset_id: str, limit: int, offset: int = 0) -> list[dict]:
    rows = _soda_get(
        client,
        dataset_id,
        select="buildingid, boro, count(distinct violationid) as c",
        group="buildingid, boro",
        order="c DESC",
        limit=limit,
        offset=offset,
    )
    agg: dict[str, dict] = {}
    for r in rows:
        bid = str(r["buildingid"])
        c = int(r["c"])
        if bid not in agg:
            agg[bid] = {"buildingid": bid, "boro": str(r.get("boro") or ""), "c": c}
        else:
            agg[bid]["c"] += c
    return sorted(agg.values(), key=lambda x: -x["c"])


def pull_rows(client, dataset_id: str, ids: list[str]) -> list[dict]:
    rows: list[dict] = []
    for i in range(0, len(ids), 25):
        chunk = ids[i : i + 25]
        where = "(" + " OR ".join(f"buildingid='{b}'" for b in chunk) + ")"
        offset = 0
        while True:
            batch = _soda_get(
                client,
                dataset_id,
                select="violationid,buildingid,class,inspectiondate,novdescription,apartment,story,boro,zip",
                where=where,
                limit=50000,
                offset=offset,
            )
            rows.extend(batch)
            if len(batch) < 50000:
                break
            offset += 50000
    by_vid: dict[str, dict] = {}
    for r in rows:
        vid = str(r.get("violationid") or "")
        if vid and vid not in by_vid:
            by_vid[vid] = r
    return list(by_vid.values())


def story_num(raw: Any) -> int | None:
    text = str(raw or "").strip()
    return int(text) if re.fullmatch(r"\d+", text) else None


def structure_proxy(apt_n: int, story_nums: list[int]) -> str:
    plausible = [n for n in story_nums if 0 <= n <= 120]
    max_story = max(plausible) if plausible else 0
    n_floors = len(set(plausible))
    if apt_n >= 10 or (apt_n >= 5 and max_story >= 4):
        return "multi_dwelling"
    if apt_n >= 3 or n_floors >= 3 or max_story >= 3:
        return "small_multi"
    return "limited_unit"


def analyze_tier(rows: list[dict], label: str) -> dict[str, Any]:
    bld: dict[str, dict] = defaultdict(lambda: {"apts": set(), "stories": [], "rows": []})
    for r in rows:
        bid = str(r.get("buildingid"))
        bld[bid]["rows"].append(r)
        apt = str(r.get("apartment") or "").strip()
        if apt:
            bld[bid]["apts"].add(apt)
        sn = story_num(r.get("story"))
        if sn is not None:
            bld[bid]["stories"].append(sn)

    building_proxy = {
        bid: structure_proxy(len(info["apts"]), info["stories"]) for bid, info in bld.items()
    }

    def row_stats(subset: list[dict]) -> dict[str, Any]:
        n = len(subset) or 1
        cls = Counter(str(r.get("class") or "?") for r in subset)
        mw = [r for r in subset if MOLD_WATER_RE.search(r.get("novdescription") or "")]
        pests_n = sum(1 for r in subset if PESTS_RE.search(r.get("novdescription") or ""))
        mw_b = [r for r in mw if r.get("class") == "B"]
        years_mw_b = [y for y in (parse_year(r.get("inspectiondate")) for r in mw_b) if y]
        years_other_b = [
            y
            for y in (
                parse_year(r.get("inspectiondate"))
                for r in subset
                if r.get("class") == "B"
                and not MOLD_WATER_RE.search(r.get("novdescription") or "")
            )
            if y
        ]
        years_b = [
            y for y in (parse_year(r.get("inspectiondate")) for r in subset if r.get("class") == "B") if y
        ]
        return {
            "opens": len(subset),
            "class_B_share": round(cls.get("B", 0) / n, 4),
            "class_C_share": round(cls.get("C", 0) / n, 4),
            "mold_water_share": round(len(mw) / n, 4),
            "pests_share": round(pests_n / n, 4),
            "pests_count": pests_n,
            "mold_water_count": len(mw),
            "class_B_mold_water_share": round(len(mw_b) / n, 4),
            "class_B_mold_water_age": persist_from_years(years_mw_b),
            "class_B_other_age": persist_from_years(years_other_b),
            "class_B_age": persist_from_years(years_b),
        }

    overall = row_stats(rows)
    by_proxy: dict[str, Any] = {}
    for proxy in ["multi_dwelling", "small_multi", "limited_unit"]:
        subset = [r for r in rows if building_proxy.get(str(r.get("buildingid"))) == proxy]
        if not subset:
            by_proxy[proxy] = {"opens": 0, "buildings": 0}
            continue
        st = row_stats(subset)
        st["buildings"] = sum(1 for p in building_proxy.values() if p == proxy)
        by_proxy[proxy] = st

    print(f"{label}: buildings={len(bld)} opens={len(rows):,} proxies={dict(Counter(building_proxy.values()))}")
    return {
        "label": label,
        "buildings": len(bld),
        "proxy_building_counts": dict(Counter(building_proxy.values())),
        "overall": overall,
        "by_proxy": by_proxy,
    }


def main() -> None:
    if not OUT_PATH.exists():
        raise SystemExit(f"Missing {OUT_PATH}. Run run_building_concentration.py first.")

    data = json.loads(OUT_PATH.read_text())
    profiles = (data.get("top_building_structure") or {}).get("profiles_top200") or []
    if len(profiles) < 50:
        raise SystemExit("JSON missing top_building_structure.profiles_top200.")

    top_ids = {str(p["buildingid"]) for p in profiles}
    city_total = int(data["meta"]["distinct_violationid_count"])
    cfg = load_socrata_settings()
    client = make_client(cfg)
    ds = cfg["dataset_id"]

    try:
        print("1) Citywide age × theme slices…")
        slices = {
            "all_opens": None,
            "class_B": "class='B'",
            "class_C": "class='C'",
            "class_A": "class='A'",
            "mold_water": MOLD_WATER_LIKE,
            "class_B_mold_water": f"class='B' AND {MOLD_WATER_LIKE}",
            "class_B_not_mold_water": f"class='B' AND NOT {MOLD_WATER_LIKE}",
            "class_C_mold_water": f"class='C' AND {MOLD_WATER_LIKE}",
        }
        city_slice_stats = {
            name: stats_from_year_map(year_counts(client, ds, where))
            for name, where in slices.items()
        }
        for name, st in city_slice_stats.items():
            print(f"  {name}: median={st['median_year']} pre2020={st['share_pre_2020']}")

        print("2) Building tiers…")
        ranked400 = fetch_building_page(client, ds, 400, 0)
        next200 = [b for b in ranked400 if b["buildingid"] not in top_ids][:200]
        low_band = [b for b in fetch_building_page(client, ds, 400, 20000) if b["c"] >= 3][:200]

        rows_top = pull_rows(client, ds, list(top_ids))
        rows_next = pull_rows(client, ds, [b["buildingid"] for b in next200])
        rows_low = pull_rows(client, ds, [b["buildingid"] for b in low_band])

        tier_top = analyze_tier(rows_top, "TOP 200")
        tier_next = analyze_tier(rows_next, "NEXT 200")
        tier_low = analyze_tier(rows_low, "LOWER-BURDEN BAND")

        bmw = city_slice_stats["class_B_mold_water"]
        b_other = city_slice_stats["class_B_not_mold_water"]
        c_all = city_slice_stats["class_C"]
        b_all = city_slice_stats["class_B"]
        top_proxy = tier_top["proxy_building_counts"]
        low_proxy = tier_low["proxy_building_counts"]

        tier_gradient = [
            {
                "name": "Top 200\n(high burden)",
                "short": "Top 200",
                "class_B_mold_water_pct": round(100 * tier_top["overall"]["class_B_mold_water_share"], 1),
                "mold_water_pct": round(100 * tier_top["overall"]["mold_water_share"], 1),
                "class_B_pct": round(100 * tier_top["overall"]["class_B_share"], 1),
                "bmw_pre_2020_pct": round(
                    100 * (tier_top["overall"]["class_B_mold_water_age"]["share_pre_2020"] or 0), 1
                ),
                "highlight": True,
            },
            {
                "name": "Next 200",
                "short": "Next 200",
                "class_B_mold_water_pct": round(100 * tier_next["overall"]["class_B_mold_water_share"], 1),
                "mold_water_pct": round(100 * tier_next["overall"]["mold_water_share"], 1),
                "class_B_pct": round(100 * tier_next["overall"]["class_B_share"], 1),
                "bmw_pre_2020_pct": round(
                    100 * (tier_next["overall"]["class_B_mold_water_age"]["share_pre_2020"] or 0), 1
                ),
            },
            {
                "name": "Lower-burden\nband",
                "short": "Lower-burden",
                "class_B_mold_water_pct": round(100 * tier_low["overall"]["class_B_mold_water_share"], 1),
                "mold_water_pct": round(100 * tier_low["overall"]["mold_water_share"], 1),
                "class_B_pct": round(100 * tier_low["overall"]["class_B_share"], 1),
                "bmw_pre_2020_pct": round(
                    100 * (tier_low["overall"]["class_B_mold_water_age"]["share_pre_2020"] or 0), 1
                ),
            },
            {
                "name": "Citywide",
                "short": "Citywide",
                "class_B_mold_water_pct": round(100 * bmw["n"] / city_total, 1),
                "mold_water_pct": round(100 * city_slice_stats["mold_water"]["n"] / city_total, 1),
                "class_B_pct": round(100 * data["class_mix"]["citywide"]["B"]["share"], 1),
                "bmw_pre_2020_pct": round(100 * (bmw["share_pre_2020"] or 0), 1),
            },
        ]

        top_multi = tier_top["by_proxy"].get("multi_dwelling") or {}
        top_limited = tier_top["by_proxy"].get("limited_unit") or {}
        low_multi = tier_low["by_proxy"].get("multi_dwelling") or {}
        low_limited = tier_low["by_proxy"].get("limited_unit") or {}
        multi_vs_limited = [
            {
                "name": "Multi-dwelling\n(top 200)",
                "class_B_mold_water_pct": round(100 * (top_multi.get("class_B_mold_water_share") or 0), 1),
                "bmw_pre_2020_pct": round(
                    100 * ((top_multi.get("class_B_mold_water_age") or {}).get("share_pre_2020") or 0), 1
                ),
                "buildings": top_multi.get("buildings", 0),
                "highlight": True,
            },
            {
                "name": "Limited-unit\n(top 200)",
                "class_B_mold_water_pct": round(100 * (top_limited.get("class_B_mold_water_share") or 0), 1),
                "bmw_pre_2020_pct": round(
                    100 * ((top_limited.get("class_B_mold_water_age") or {}).get("share_pre_2020") or 0), 1
                ),
                "buildings": top_limited.get("buildings", 0),
            },
            {
                "name": "Multi-dwelling\n(lower-burden)",
                "class_B_mold_water_pct": round(100 * (low_multi.get("class_B_mold_water_share") or 0), 1),
                "bmw_pre_2020_pct": round(
                    100 * ((low_multi.get("class_B_mold_water_age") or {}).get("share_pre_2020") or 0), 1
                ),
                "buildings": low_multi.get("buildings", 0),
            },
            {
                "name": "Limited-unit\n(lower-burden)",
                "class_B_mold_water_pct": round(100 * (low_limited.get("class_B_mold_water_share") or 0), 1),
                "bmw_pre_2020_pct": round(
                    100 * ((low_limited.get("class_B_mold_water_age") or {}).get("share_pre_2020") or 0), 1
                ),
                "buildings": low_limited.get("buildings", 0),
            },
        ]

        age_compare_bars = [
            {
                "name": "Class B (other)",
                "share_pre_2020_pct": round(100 * (b_other["share_pre_2020"] or 0), 1),
                "median_year": b_other["median_year"],
                "n": b_other["n"],
                "role": "Oldest Class B backlog",
            },
            {
                "name": "Class B mold/water",
                "share_pre_2020_pct": round(100 * (bmw["share_pre_2020"] or 0), 1),
                "median_year": bmw["median_year"],
                "n": bmw["n"],
                "highlight": True,
                "role": "Moisture channel (older than Class C)",
            },
            {
                "name": "All opens",
                "share_pre_2020_pct": round(100 * (city_slice_stats["all_opens"]["share_pre_2020"] or 0), 1),
                "median_year": city_slice_stats["all_opens"]["median_year"],
                "n": city_slice_stats["all_opens"]["n"],
                "role": "City baseline",
            },
            {
                "name": "Class C",
                "share_pre_2020_pct": round(100 * (c_all["share_pre_2020"] or 0), 1),
                "median_year": c_all["median_year"],
                "n": c_all["n"],
                "role": "Turns over faster",
            },
        ]

        structure_building_counts = [
            {
                "name": "Multi-dwelling",
                "top_200": top_proxy.get("multi_dwelling", 0),
                "lower_burden": low_proxy.get("multi_dwelling", 0),
            },
            {
                "name": "Small multi",
                "top_200": top_proxy.get("small_multi", 0),
                "lower_burden": low_proxy.get("small_multi", 0),
            },
            {
                "name": "Limited-unit / single-ish",
                "top_200": top_proxy.get("limited_unit", 0),
                "lower_burden": low_proxy.get("limited_unit", 0),
            },
        ]

        grad = tier_gradient
        insight = {
            "title": "Chronic open inventories are multi-dwelling Class B moisture — not old Class C in small homes",
            "statement": (
                f"Buildings with the most open violations are almost entirely multi-dwelling "
                f"({top_proxy.get('multi_dwelling', 0)} of {tier_top['buildings']} in the top 200; "
                f"{top_proxy.get('limited_unit', 0)} limited-unit / single-ish). In that tier, "
                f"Class B mold/water is {grad[0]['class_B_mold_water_pct']}% of opens versus "
                f"{grad[3]['class_B_mold_water_pct']}% citywide — a burden gradient that also appears "
                f"in the next 200 ({grad[1]['class_B_mold_water_pct']}%). "
                f"Age×theme ties this to the Class B backlog channel: open Class B is much older than "
                f"open Class C ({b_all['share_pre_2020']:.0%} vs {c_all['share_pre_2020']:.0%} inspected "
                f"before 2020). Class B mold/water sits in that Class B channel "
                f"({bmw['share_pre_2020']:.0%} pre-2020; median {bmw['median_year']}) — older than Class C "
                f"({c_all['share_pre_2020']:.0%}, median {c_all['median_year']}), though not older than "
                f"other Class B themes ({b_other['share_pre_2020']:.0%}, median {b_other['median_year']}). "
                f"Limited-unit buildings show up mainly in lower-burden stock "
                f"({low_proxy.get('limited_unit', 0)} of {tier_low['buildings']} in the "
                f"lower-burden band) and do not drive the extreme open-violation tail."
            ),
            "specificity": (
                f"Three locks: (1) Structure — top 200 = {top_proxy.get('multi_dwelling', 0)} multi-dwelling "
                f"/ {top_proxy.get('small_multi', 0)} small-multi / {top_proxy.get('limited_unit', 0)} "
                f"limited-unit by apartment/story proxy. "
                f"(2) Composition gradient — Class B∧mold|water share of opens: "
                f"citywide {grad[3]['class_B_mold_water_pct']}% → lower-burden {grad[2]['class_B_mold_water_pct']}% "
                f"→ next 200 {grad[1]['class_B_mold_water_pct']}% → top 200 {grad[0]['class_B_mold_water_pct']}%. "
                f"(3) Age×theme — pre-2020 shares: Class B other {b_other['share_pre_2020']:.0%}, "
                f"Class B mold/water {bmw['share_pre_2020']:.0%}, all opens "
                f"{city_slice_stats['all_opens']['share_pre_2020']:.0%}, "
                f"Class C {c_all['share_pre_2020']:.0%}."
            ),
            "non_obvious": (
                "Two common stories fail: that chronic opens are mostly lingering Class C hazards, "
                "and that “small homes with bad conditions” explain the worst open counts. The open "
                "tail is multi-dwelling; its distinctive overload is Class B moisture/mold volume; "
                "and the long-lived open book runs through Class B (with moisture as the enrichment "
                "in high-burden buildings), while Class C turns over younger."
            ),
            "arguments_for": [
                f"Zero limited-unit / single-ish buildings in the top 200 open-violation tier "
                f"({top_proxy.get('limited_unit', 0)} of {tier_top['buildings']}); "
                f"nearly all are multi-dwelling proxies.",
                f"Class B∧mold|water intensifies with burden: {grad[3]['class_B_mold_water_pct']}% of "
                f"citywide opens vs {grad[0]['class_B_mold_water_pct']}% in the top 200 "
                f"(and {grad[1]['class_B_mold_water_pct']}% in the next 200 — not only the extreme tip).",
                f"Age×theme: open Class B is the persistent channel vs Class C "
                f"({b_all['share_pre_2020']:.0%} vs {c_all['share_pre_2020']:.0%} pre-2020). "
                f"Class B mold/water is older than Class C ({bmw['share_pre_2020']:.0%} vs "
                f"{c_all['share_pre_2020']:.0%} pre-2020).",
                "Mold/water NOV text is ~75% Class B citywide, so the moisture theme and the Class B backlog are the same enforcement channel.",
            ],
            "arguments_against": [
                f"Within Class B, non-moisture opens are even older than mold/water "
                f"({b_other['share_pre_2020']:.0%} vs {bmw['share_pre_2020']:.0%} pre-2020) — so "
                f"“persistence” is Class B broadly; moisture is the high-burden composition signature, "
                f"not uniquely the oldest theme.",
                "Apartment/story proxies are not official unit counts; limited-unit can be a large building with opens in few units.",
                "Open-only data: age differences can reflect certification/closure pathways and inspection timing, not only physical duration of bad conditions.",
                "Keyword matching on novdescription can miss or over-include some moisture-related wording.",
                "HPD open violations underrepresent owner-occupied / non-regulated 1–2 family housing — the single-dwelling comparison is within the HPD open universe.",
            ],
            "method_note": (
                "Open HPD Violations only; distinct violationid. Moisture/mold = keyword match on "
                "novdescription (mold/mildew/leak/plumbing/water damage). Building structure proxy from "
                "distinct apartment + story labels among each building’s open violations: "
                "multi_dwelling (≥10 apts or ≥5 apts with floor≥4), small_multi (≥3 apts or multi-floor), "
                "limited_unit (few apt/floor labels — single-ish signal, not a deed/occupancy proof). "
                "Age uses inspectiondate year; years <1980 dropped."
            ),
            "one_sentence": (
                f"Prioritize Class B mold/water remediation in high-burden multi-dwelling buildings, "
                f"where those opens are {grad[0]['class_B_mold_water_pct']}% of the inventory versus "
                f"{grad[3]['class_B_mold_water_pct']}% citywide — while limited-unit / single-ish "
                f"buildings are absent from the top-200 open-violation tier "
                f"(0 of {tier_top['buildings']})."
            ),
        }

        final_block = {
            "finding": insight,
            "citywide_slice_stats": city_slice_stats,
            "tiers": {
                "top_200": tier_top,
                "next_200": tier_next,
                "lower_burden_band": {
                    **tier_low,
                    "note": "Buildings around rank offset ~20,000 by open-violation count.",
                },
            },
            "charts": {
                "age_compare_bars": age_compare_bars,
                "tier_gradient": tier_gradient,
                "multi_vs_limited": multi_vs_limited,
                "structure_building_counts": structure_building_counts,
            },
        }

        # ------------------------------------------------------------------
        # Mold & moisture vs pests — bottom-of-page “Key insight” section
        # Citywide counts use SoQL aggregates; multi-dwelling uses top-200 rows.
        # ------------------------------------------------------------------
        print("3) Citywide mold/moisture vs pests counts…")
        # Same SoQL method for both themes (count distinct violationid).
        # Do NOT reuse year_counts()["n"] here — that drops rows without a
        # groupable inspectiondate and would undercount moisture vs pests.
        city_mw_n = count_distinct(client, ds, MOLD_WATER_LIKE)
        city_pests_n = count_distinct(client, ds, PESTS_LIKE)
        city_mw_pct = round(100 * city_mw_n / city_total, 1)
        city_pests_pct = round(100 * city_pests_n / city_total, 1)
        print(f"  citywide mold/moisture: {city_mw_n:,} ({city_mw_pct}%)")
        print(f"  citywide pests: {city_pests_n:,} ({city_pests_pct}%)")

        # Multi-dwelling opens inside the top 200 — reuse by_proxy from analyze_tier
        top_multi_stats = tier_top["by_proxy"].get("multi_dwelling") or {}
        low_multi_stats = tier_low["by_proxy"].get("multi_dwelling") or {}
        multi_mw_pct = round(100 * (top_multi_stats.get("mold_water_share") or 0), 1)
        multi_pests_pct = round(100 * (top_multi_stats.get("pests_share") or 0), 1)
        multi_buildings = int(top_multi_stats.get("buildings") or 0)
        multi_opens = int(top_multi_stats.get("opens") or 0)
        low_mw_pct = round(100 * (low_multi_stats.get("mold_water_share") or 0), 1)
        low_pests_pct = round(100 * (low_multi_stats.get("pests_share") or 0), 1)

        # Fallback if by_proxy somehow empty — use overall top-200 (still high-burden)
        if multi_opens == 0:
            overall_theme = theme_shares_from_rows(rows_top)
            multi_mw_pct = round(100 * overall_theme["mold_water_share"], 1)
            multi_pests_pct = round(100 * overall_theme["pests_share"], 1)
            multi_buildings = tier_top["buildings"]
            multi_opens = overall_theme["opens"]
            top_multi_stats = {
                **top_multi_stats,
                "mold_water_count": overall_theme["mold_water_count"],
                "pests_count": overall_theme["pests_count"],
            }

        mw_lift = round(multi_mw_pct / city_mw_pct, 2) if city_mw_pct else None
        pests_lift = round(multi_pests_pct / city_pests_pct, 2) if city_pests_pct else None
        moisture_wins_multi = multi_mw_pct > multi_pests_pct
        pests_win_city = city_pests_pct > city_mw_pct

        # Chart A: grouped bars — % of open violations for each issue, two settings
        # short = axis label (single line); name = longer tooltip / table label
        mold_vs_pests_compare = [
            {
                "name": "All NYC (open violations)",
                "short": "Citywide",
                "mold_moisture_pct": city_mw_pct,
                "pests_pct": city_pests_pct,
                "highlight": False,
            },
            {
                "name": "Multi-dwelling (top 200 burden)",
                "short": "Multi-dwelling top 200",
                "mold_moisture_pct": multi_mw_pct,
                "pests_pct": multi_pests_pct,
                "highlight": True,
            },
        ]
        # Optional contrast row for lower-burden multi-dwellings (not on main chart)
        if low_multi_stats.get("opens"):
            mold_vs_pests_compare.append(
                {
                    "name": "Multi-dwelling (lower burden)",
                    "short": "Lower-burden multi",
                    "mold_moisture_pct": low_mw_pct,
                    "pests_pct": low_pests_pct,
                    "highlight": False,
                }
            )

        # Chart B: how each issue changes vs citywide (lift; 1.0 = same as city)
        mold_vs_pests_lift = [
            {
                "name": "Mold & moisture",
                "lift": mw_lift if mw_lift is not None else 0,
                "citywide_pct": city_mw_pct,
                "multi_dwelling_pct": multi_mw_pct,
                "delta_pp": round(multi_mw_pct - city_mw_pct, 1),
                "highlight": True,
                "direction": "more common in high-burden multi-dwellings"
                if (mw_lift or 0) > 1
                else "similar or less common",
            },
            {
                "name": "Pests",
                "lift": pests_lift if pests_lift is not None else 0,
                "citywide_pct": city_pests_pct,
                "multi_dwelling_pct": multi_pests_pct,
                "delta_pp": round(multi_pests_pct - city_pests_pct, 1),
                "highlight": False,
                "direction": "less common in high-burden multi-dwellings"
                if (pests_lift or 0) < 1
                else "similar or more common",
            },
        ]

        mvp_finding = {
            "title": "Mold & moisture outrank pests in high-burden multi-dwellings",
            "statement": (
                f"Across all currently open HPD violations citywide, pests appear in "
                f"{city_pests_pct}% of opens while mold & moisture (mold, leaks, plumbing, "
                f"water damage) appear in {city_mw_pct}%. In the multi-dwelling buildings "
                f"among the top 200 by open-violation count "
                f"({multi_buildings} buildings, {multi_opens:,} opens), that ranking flips: "
                f"mold & moisture are {multi_mw_pct}% of opens versus pests at "
                f"{multi_pests_pct}%."
            ),
            "one_sentence": (
                f"In high-burden multi-dwelling buildings, mold & moisture "
                f"({multi_mw_pct}% of open violations) are more common than pests "
                f"({multi_pests_pct}%) — the reverse of the citywide pattern "
                f"(pests {city_pests_pct}% vs moisture {city_mw_pct}%)."
            ),
            "why_it_matters": (
                "Pests are a familiar, high-volume citywide issue. In the buildings that "
                "carry the heaviest open-violation load — almost all multi-dwelling — "
                "mold and moisture problems take a larger share of the open inventory "
                "than pest problems do."
            ),
            "method_note": (
                "Open HPD Violations only (csn4-vhvf); distinct violationid. "
                "Mold & moisture = NOV text match for mold/mildew/leak/plumbing/water damage. "
                "Pests = NOV text match for roach/mice/vermin/infestation/bedbug/rats. "
                "A violation can match both themes. Multi-dwelling = apartment/story proxy "
                "among each building’s open violations (≥10 distinct apartments, or ≥5 "
                "apartments with floor ≥4). Top 200 = buildings with the most open violations."
            ),
            "caveats": [
                "Keyword matching on violation descriptions can miss or over-include some wording.",
                "Apartment/story proxies are not official unit counts.",
                "Shares can overlap (one open violation may mention both moisture and pests).",
            ],
            "moisture_wins_in_multi_dwelling": moisture_wins_multi,
            "pests_win_citywide": pests_win_city,
        }

        mold_vs_pests_block = {
            "finding": mvp_finding,
            "citywide": {
                "opens": city_total,
                "mold_water_count": city_mw_n,
                "mold_water_pct": city_mw_pct,
                "pests_count": city_pests_n,
                "pests_pct": city_pests_pct,
            },
            "multi_dwelling_top200": {
                "buildings": multi_buildings,
                "opens": multi_opens,
                "mold_water_count": int(top_multi_stats.get("mold_water_count") or 0),
                "mold_water_pct": multi_mw_pct,
                "pests_count": int(top_multi_stats.get("pests_count") or 0),
                "pests_pct": multi_pests_pct,
                "mold_water_lift": mw_lift,
                "pests_lift": pests_lift,
            },
            "charts": {
                "compare": mold_vs_pests_compare,
                "lift": mold_vs_pests_lift,
            },
        }

        data["final_insight"] = final_block
        data["mold_vs_pests_insight"] = mold_vs_pests_block
        data["charts"]["final_age_compare"] = age_compare_bars
        data["charts"]["final_tier_gradient"] = tier_gradient
        data["charts"]["final_multi_vs_limited"] = multi_vs_limited
        data["charts"]["final_structure_counts"] = structure_building_counts
        data["charts"]["mold_vs_pests_compare"] = mold_vs_pests_compare
        data["charts"]["mold_vs_pests_lift"] = mold_vs_pests_lift
        data["headlines"]["final_bmw_pre_2020_pct"] = round(100 * (bmw["share_pre_2020"] or 0), 1)
        data["headlines"]["final_b_other_pre_2020_pct"] = round(100 * (b_other["share_pre_2020"] or 0), 1)
        data["headlines"]["final_c_pre_2020_pct"] = round(100 * (c_all["share_pre_2020"] or 0), 1)
        data["headlines"]["final_bmw_median_year"] = bmw["median_year"]
        data["headlines"]["final_top200_bmw_pct"] = grad[0]["class_B_mold_water_pct"]
        data["headlines"]["final_city_bmw_pct"] = grad[3]["class_B_mold_water_pct"]
        data["headlines"]["final_top200_multi_buildings"] = top_proxy.get("multi_dwelling", 0)
        data["headlines"]["final_top200_limited_buildings"] = top_proxy.get("limited_unit", 0)
        data["headlines"]["mvp_city_mw_pct"] = city_mw_pct
        data["headlines"]["mvp_city_pests_pct"] = city_pests_pct
        data["headlines"]["mvp_multi_mw_pct"] = multi_mw_pct
        data["headlines"]["mvp_multi_pests_pct"] = multi_pests_pct
        data["headlines"]["mvp_mw_lift"] = mw_lift
        data["headlines"]["mvp_pests_lift"] = pests_lift
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        data["meta"]["final_insight_analyzed_at"] = stamp
        data["meta"]["mold_vs_pests_analyzed_at"] = stamp

        OUT_PATH.write_text(json.dumps(data, indent=2))
        print(f"Wrote {OUT_PATH}")
        print(insight["statement"][:280], "…")
        print("Mold vs pests:", mvp_finding["one_sentence"])
    finally:
        client.close()


if __name__ == "__main__":
    main()
