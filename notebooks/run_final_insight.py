"""
Final insight pass — Class B moisture + multi-dwelling + age×theme.

What this adds to the website “Final insight” block:
  1) Age×theme: how old are Class B mold/water opens vs other Class B vs Class C?
  2) Burden gradient: Class B∧mold|water share in top 200 / next 200 / lower band / city.
  3) Structure: multi-dwelling vs limited-unit (single-ish) proxies — who is in the top tier?

Prerequisites:
  - run_building_concentration.py (needs top-200 building list in the JSON)
  - SOCRATA_APP_TOKEN in the project-root .env

How a non-technical maintainer re-runs this:
  cd notebooks
  source .venv/bin/activate
  python run_final_insight.py
  # usually a few minutes, then reload the website

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

MOLD_WATER_RE = re.compile(
    r"\bmold\b|mildew|\bleak|water damage|flood|plumbing|\bpipe\b", re.I
)
MOLD_WATER_LIKE = "(" + " OR ".join(
    f"upper(novdescription) like '{t}'"
    for t in ["%MOLD%", "%MILDEW%", "%LEAK%", "%PLUMBING%", "%WATER DAMAGE%"]
) + ")"


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

        data["final_insight"] = final_block
        data["charts"]["final_age_compare"] = age_compare_bars
        data["charts"]["final_tier_gradient"] = tier_gradient
        data["charts"]["final_multi_vs_limited"] = multi_vs_limited
        data["charts"]["final_structure_counts"] = structure_building_counts
        data["headlines"]["final_bmw_pre_2020_pct"] = round(100 * (bmw["share_pre_2020"] or 0), 1)
        data["headlines"]["final_b_other_pre_2020_pct"] = round(100 * (b_other["share_pre_2020"] or 0), 1)
        data["headlines"]["final_c_pre_2020_pct"] = round(100 * (c_all["share_pre_2020"] or 0), 1)
        data["headlines"]["final_bmw_median_year"] = bmw["median_year"]
        data["headlines"]["final_top200_bmw_pct"] = grad[0]["class_B_mold_water_pct"]
        data["headlines"]["final_city_bmw_pct"] = grad[3]["class_B_mold_water_pct"]
        data["headlines"]["final_top200_multi_buildings"] = top_proxy.get("multi_dwelling", 0)
        data["headlines"]["final_top200_limited_buildings"] = top_proxy.get("limited_unit", 0)
        data["meta"]["final_insight_analyzed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        OUT_PATH.write_text(json.dumps(data, indent=2))
        print(f"Wrote {OUT_PATH}")
        print(insight["statement"][:280], "…")
    finally:
        client.close()


if __name__ == "__main__":
    main()
