"""
Building concentration analysis for Open HPD Violations (live SODA).

What this script does (plain English):
  1) Asks NYC Open Data how many open violations exist, counting each
     violationid only once (duplicates / escalations entered twice = 1).
  2) Counts open violations per building (buildingid).
  3) Tests whether a small share of buildings holds most open violations.
  4) Digs into class and status mix for the heaviest buildings.
  5) Writes a JSON file the website reads for the "Analysis journey" section.

How a non-technical maintainer re-runs this:
  1) Put SOCRATA_APP_TOKEN in the project-root .env file.
  2) From the notebooks/ folder:
       source .venv/bin/activate
       python run_building_concentration.py
  3) Wait — full refresh can take 10–20 minutes (remote aggregates).
  4) Refresh the website. The new numbers load from:
       frontend/public/analysis/building_concentration.json

IMPORTANT:
  This uses ONLY the Open HPD Violations dataset (currently open rows).
  It does not include closed / historical violations.
"""

from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# Allow "from soda_live import ..." when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent))

from soda_live import (  # noqa: E402
    _soda_get,
    get_live_count,
    load_socrata_settings,
    make_client,
)

# Output path the React app loads (public URL: /analysis/building_concentration.json)
ROOT_DIR = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT_DIR / "frontend" / "public" / "analysis" / "building_concentration.json"

# Page size when downloading every building's count (SODA max is often 50_000)
PAGE_SIZE = 50_000

# Status string as it appears in NYC Open Data (note the odd spacing)
NO_ACCESS_STATUS = "FIRST NO ACCESS TO RE- INSPECT VIOLATION"


def fetch_building_counts(client, dataset_id: str) -> pd.DataFrame:
    """
    Download one row per building with its open-violation count.

    Uses count(distinct violationid) so duplicate / escalation rows
    for the same violationid are not double-counted.

    Groups by buildingid AND boro (a few buildings appear under more than
    one boro label in the feed; we collapse those later).
    """
    frames: list[pd.DataFrame] = []
    offset = 0
    while True:
        t0 = time.time()
        rows = _soda_get(
            client,
            dataset_id,
            select="buildingid, boro, count(distinct violationid) as c",
            group="buildingid, boro",
            order="c DESC",
            limit=PAGE_SIZE,
            offset=offset,
        )
        print(f"  building page offset={offset} rows={len(rows)} ({time.time() - t0:.0f}s)")
        if not rows:
            break
        frames.append(pd.DataFrame.from_records(rows))
        if len(rows) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    if not frames:
        return pd.DataFrame(columns=["buildingid", "boro", "c"])

    df = pd.concat(frames, ignore_index=True)
    df["c"] = pd.to_numeric(df["c"], errors="coerce").fillna(0).astype(int)
    df["buildingid"] = df["buildingid"].astype(str)
    df["boro"] = df["boro"].astype(str)

    # Collapse rare multi-boro buildingids: keep the boro with the most rows,
    # sum violation counts so we do not invent extras.
    if df["buildingid"].duplicated().any():
        boro_pick = (
            df.sort_values("c", ascending=False)
            .drop_duplicates("buildingid")[["buildingid", "boro"]]
        )
        sums = df.groupby("buildingid", as_index=False)["c"].sum()
        df = sums.merge(boro_pick, on="buildingid", how="left")

    return df.sort_values("c", ascending=False).reset_index(drop=True)


def grouped_distinct_counts(
    client,
    dataset_id: str,
    column: str,
    *,
    where: str | None = None,
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    """GROUP BY one column, counting distinct violationid values."""
    kwargs: dict[str, Any] = {
        "select": f"{column}, count(distinct violationid) as c",
        "group": column,
        "order": "c DESC",
    }
    if where:
        kwargs["where"] = where
    if top_n:
        kwargs["limit"] = int(top_n)
    return _soda_get(client, dataset_id, **kwargs)


def counts_for_building_subset(
    client,
    dataset_id: str,
    building_ids: list[str],
    column: str,
    *,
    chunk_size: int = 50,
) -> Counter:
    """
    Class or status counts for a list of buildings.

    SODA URLs cannot hold thousands of IDs at once, so we query in chunks
    and add the counts together.
    """
    totals: Counter = Counter()
    for i in range(0, len(building_ids), chunk_size):
        chunk = building_ids[i : i + chunk_size]
        where = "(" + " OR ".join(f"buildingid='{bid}'" for bid in chunk) + ")"
        rows = grouped_distinct_counts(client, dataset_id, column, where=where)
        for row in rows:
            key = str(row.get(column) or "?")
            totals[key] += int(row["c"])
        if (i // chunk_size) % 10 == 0:
            print(f"    {column} chunks {i}/{len(building_ids)}")
    return totals


def concentration_metrics(df: pd.DataFrame) -> dict[str, Any]:
    """Pareto / Lorenz-style concentration stats from per-building counts."""
    counts = df["c"].to_numpy()
    n_buildings = len(counts)
    total_v = int(counts.sum())
    cum_v = np.cumsum(counts)
    cum_share = cum_v / total_v

    def share_at_top_frac(frac: float) -> dict[str, Any]:
        k = max(1, int(np.ceil(n_buildings * frac)))
        return {
            "top_building_fraction": frac,
            "top_building_count": k,
            "violation_share": float(cum_share[k - 1]),
            "violation_count": int(cum_v[k - 1]),
        }

    def buildings_for_violation_share(target: float) -> dict[str, Any]:
        idx = int(np.searchsorted(cum_share, target, side="left"))
        idx = min(idx, n_buildings - 1)
        return {
            "violation_share_target": target,
            "building_count": idx + 1,
            "building_fraction": float((idx + 1) / n_buildings),
            "violation_count": int(cum_v[idx]),
            "actual_violation_share": float(cum_share[idx]),
        }

    # Gini coefficient (0 = equal, 1 = one building has everything)
    i = np.arange(1, n_buildings + 1)
    asc = counts[::-1]  # ascending order required for this formula
    gini = float((2 * np.sum(i * asc)) / (n_buildings * total_v) - (n_buildings + 1) / n_buildings)

    # Lorenz curve sample (~200 points) for the chart
    lorenz_idx = np.unique(
        np.concatenate(
            [
                [0],
                np.linspace(0, n_buildings - 1, 201).astype(int),
                [n_buildings - 1],
            ]
        )
    )
    lorenz = [{"building_percentile": 0.0, "violation_percentile": 0.0}] + [
        {
            "building_percentile": float((idx + 1) / n_buildings * 100),
            "violation_percentile": float(cum_share[idx] * 100),
        }
        for idx in lorenz_idx
    ]

    # Violation-count buckets (how many buildings have 1, 2–5, … open violations)
    labels = ["1", "2–5", "6–20", "21–50", "51–100", "101+"]
    bucketed = pd.cut(
        df["c"],
        bins=[0, 1, 5, 20, 50, 100, np.inf],
        labels=labels,
        right=True,
    )
    bucket_summary = (
        df.assign(bucket=bucketed)
        .groupby("bucket", observed=False)
        .agg(buildings=("buildingid", "count"), violations=("c", "sum"))
        .reset_index()
    )
    bucket_summary["building_share"] = bucket_summary["buildings"] / n_buildings
    bucket_summary["violation_share"] = bucket_summary["violations"] / total_v

    tops = [share_at_top_frac(f) for f in (0.01, 0.05, 0.10, 0.20)]
    return {
        "n_buildings": n_buildings,
        "total_v": total_v,
        "gini": gini,
        "tops": tops,
        "milestones": [buildings_for_violation_share(t) for t in (0.50, 0.80)],
        "lorenz": lorenz,
        "buckets": [
            {
                "name": str(row["bucket"]),
                "buildings": int(row["buildings"]),
                "violations": int(row["violations"]),
                "building_share": float(row["building_share"]),
                "violation_share": float(row["violation_share"]),
            }
            for _, row in bucket_summary.iterrows()
        ],
        # Not disproved if top 10% of buildings hold > 50% of open violations
        "result": "not_disproved" if tops[2]["violation_share"] > 0.5 else "disproved",
    }


def borough_concentration(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Same top-share math, but one borough at a time."""
    rows_out: list[dict[str, Any]] = []
    for boro, group in df.groupby("boro"):
        group = group.sort_values("c", ascending=False)
        n = len(group)
        tv = int(group["c"].sum())
        if n == 0 or tv == 0:
            continue
        cv = np.cumsum(group["c"].to_numpy())

        def top_share(frac: float) -> float:
            k = max(1, int(np.ceil(n * frac)))
            return float(cv[k - 1] / tv)

        idx50 = int(np.searchsorted(cv / tv, 0.50, side="left"))
        rows_out.append(
            {
                "boro": str(boro),
                "buildings": n,
                "violations": tv,
                "mean_per_building": float(tv / n),
                "median_per_building": float(group["c"].median()),
                "top_1pct_violation_share": top_share(0.01),
                "top_5pct_violation_share": top_share(0.05),
                "top_10pct_violation_share": top_share(0.10),
                "building_frac_for_50pct_violations": float((idx50 + 1) / n),
                "max_building": int(group["c"].iloc[0]),
            }
        )
    rows_out.sort(key=lambda r: r["top_10pct_violation_share"], reverse=True)
    return rows_out


def class_share_map(raw: dict[str, int] | list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Turn class counts into {class: {count, share}}."""
    if isinstance(raw, list):
        data = {str(r["class"]): int(r["c"]) for r in raw}
    else:
        data = {str(k): int(v) for k, v in raw.items()}
    total = sum(data.values()) or 1
    return {
        key: {"count": val, "share": val / total}
        for key, val in sorted(data.items())
    }


def status_share(counts: dict[str, int], total: int, name: str) -> float:
    return (counts.get(name, 0) / total) if total else 0.0


def parse_story_number(raw: str) -> int | None:
    """Pull a plain floor number from the story field when possible."""
    text = (raw or "").strip()
    if re.fullmatch(r"\d+", text):
        return int(text)
    return None


def classify_structure_proxy(n_apartments: int, story_numbers: list[int]) -> str:
    """
    Rough building-type proxy from OPEN violation locations only.

    This dataset has no official unit count or building class, so we infer from
    distinct apartment / story values among currently open violations:
      multi_dwelling_complex   — many apartments and/or high floors touched
      multi_unit_or_multi_story — smaller apt spread but still multi-unit/floor
      limited_unit_signal      — few apt + few floor labels (NOT proof of 1–2 family)
    """
    plausible = [n for n in story_numbers if 0 <= n <= 120]
    max_story = max(plausible) if plausible else 0
    n_floors = len(set(plausible))

    if n_apartments >= 10 or (n_apartments >= 5 and max_story >= 4):
        return "multi_dwelling_complex"
    if n_apartments >= 3 or n_floors >= 3 or max_story >= 3:
        return "multi_unit_or_multi_story"
    return "limited_unit_signal"


def profile_top_buildings(
    client,
    dataset_id: str,
    building_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    For each top building, count distinct apartments/stories among open violations.

    Non-technical tip:
      “Distinct apartments with opens” means how many different apartment labels
      appear on currently open violations — not the building’s full unit count.
    """
    profiles: list[dict[str, Any]] = []
    for i, row in enumerate(building_rows):
        bid = str(row["buildingid"])
        where = f"buildingid='{bid}'"
        apts = _soda_get(
            client,
            dataset_id,
            select="apartment, count(distinct violationid) as c",
            group="apartment",
            where=where,
            order="c DESC",
            limit=1000,
        )
        stories = _soda_get(
            client,
            dataset_id,
            select="story, count(distinct violationid) as c",
            group="story",
            where=where,
            order="c DESC",
            limit=500,
        )
        addr = _soda_get(
            client,
            dataset_id,
            where=where,
            limit=1,
            select="buildingid, boro, housenumber, streetname, zip",
        )
        addr0 = addr[0] if addr else {}

        apt_labels = [
            str(r.get("apartment") or "").strip()
            for r in apts
            if str(r.get("apartment") or "").strip()
        ]
        story_labels = [
            str(r.get("story") or "").strip()
            for r in stories
            if str(r.get("story") or "").strip()
        ]
        blank_apt = sum(
            int(r["c"]) for r in apts if not str(r.get("apartment") or "").strip()
        )
        total = sum(int(r["c"]) for r in apts) or int(row.get("open_violations") or 0)
        story_nums = [
            n
            for n in (parse_story_number(s) for s in story_labels)
            if n is not None and 0 <= n <= 120
        ]
        n_apt = len(apt_labels)
        typ = classify_structure_proxy(n_apt, story_nums)

        profiles.append(
            {
                "buildingid": bid,
                "boro": str(addr0.get("boro") or row.get("boro") or ""),
                "housenumber": str(addr0.get("housenumber") or ""),
                "streetname": str(addr0.get("streetname") or ""),
                "zip": str(addr0.get("zip") or ""),
                "open_violations": int(row["open_violations"]),
                "distinct_apartments_with_opens": n_apt,
                "blank_apartment_violation_share": round(blank_apt / total, 4)
                if total
                else 0.0,
                "distinct_stories_with_opens": len(story_labels),
                "max_story_observed": max(story_nums) if story_nums else None,
                "sample_apartments": apt_labels[:8],
                "sample_stories": story_labels[:10],
                "structure_proxy": typ,
            }
        )
        if i % 25 == 0:
            print(f"    structure profile {i}/{len(building_rows)} ({bid} → {typ})")
    return profiles


def summarize_structure_profiles(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll top-building structure proxies into chart + talking-point summaries."""
    n = len(profiles) or 1
    type_counts = Counter(p["structure_proxy"] for p in profiles)

    def apt_bin(count: int) -> str:
        if count <= 2:
            return "1–2 apartments"
        if count <= 9:
            return "3–9 apartments"
        if count <= 49:
            return "10–49 apartments"
        if count <= 99:
            return "50–99 apartments"
        return "100+ apartments"

    apt_bins = Counter(apt_bin(p["distinct_apartments_with_opens"]) for p in profiles)
    type_labels = {
        "multi_dwelling_complex": "Multi-dwelling complex signal",
        "multi_unit_or_multi_story": "Multi-unit / multi-story signal",
        "limited_unit_signal": "Limited unit/story signal",
    }
    type_bars = [
        {
            "name": type_labels[key],
            "key": key,
            "buildings": type_counts.get(key, 0),
            "share_pct": round(100 * type_counts.get(key, 0) / n, 1),
        }
        for key in [
            "multi_dwelling_complex",
            "multi_unit_or_multi_story",
            "limited_unit_signal",
        ]
    ]
    apt_order = [
        "1–2 apartments",
        "3–9 apartments",
        "10–49 apartments",
        "50–99 apartments",
        "100+ apartments",
    ]
    apt_bars = [
        {
            "name": name,
            "buildings": apt_bins.get(name, 0),
            "share_pct": round(100 * apt_bins.get(name, 0) / n, 1),
        }
        for name in apt_order
    ]
    min_apts = min((p["distinct_apartments_with_opens"] for p in profiles), default=0)
    finding = {
        "title": "Top-burden buildings look like multi-dwelling / multi-story stock",
        "scope": f"Top {len(profiles)} buildings by distinct open violationid",
        "method_note": (
            "Open HPD Violations do not include official unit counts or building class. "
            "We proxy structure from distinct non-blank apartment and story values among "
            "each building’s currently open violations. This can understate true size "
            "(violations may touch only some units) and cannot prove a building is 1–2 family."
        ),
        "summary": (
            f"Among the top {len(profiles)} buildings, "
            f"{type_counts.get('multi_dwelling_complex', 0)} "
            f"({round(100 * type_counts.get('multi_dwelling_complex', 0) / n, 1)}%) show a "
            f"clear multi-dwelling complex signal. "
            f"{type_counts.get('limited_unit_signal', 0)} show a limited apartment/story "
            f"signal. Minimum distinct apartments with opens in this set: {min_apts}."
        ),
        "type_counts": dict(type_counts),
        "apt_bin_counts": dict(apt_bins),
        "max_story_at_least_3_buildings": sum(
            1 for p in profiles if (p.get("max_story_observed") or 0) >= 3
        ),
        "max_story_at_least_6_buildings": sum(
            1 for p in profiles if (p.get("max_story_observed") or 0) >= 6
        ),
        "min_distinct_apartments": min_apts,
        "buildings_with_le_2_apartments": sum(
            1 for p in profiles if p["distinct_apartments_with_opens"] <= 2
        ),
        "buildings_with_le_5_apartments": sum(
            1 for p in profiles if p["distinct_apartments_with_opens"] <= 5
        ),
    }
    return {
        "finding": finding,
        "profiles_top200": profiles,
        "charts": {
            "structure_type_bars": type_bars,
            "apartment_spread_bars": apt_bars,
        },
    }


def build_payload(
    *,
    dataset_id: str,
    raw_rows: int,
    distinct_vids: int,
    df: pd.DataFrame,
    metrics: dict[str, Any],
    boro_rows: list[dict[str, Any]],
    city_class: list[dict[str, Any]],
    top1_class: Counter,
    top200_class: Counter,
    city_status: list[dict[str, Any]],
    top200_status: Counter,
    top_buildings: list[dict[str, Any]],
    structure_block: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the JSON the website reads (charts + talking points)."""
    city_tot = metrics["total_v"]
    city_class_shares = {k: v["share"] for k, v in class_share_map(city_class).items()}
    top1_map = class_share_map(top1_class)
    top200_map = class_share_map(top200_class)
    top1_shares = {k: v["share"] for k, v in top1_map.items()}
    top200_tot = sum(v["count"] for v in top200_map.values())
    city_status_counts = {r["currentstatus"]: int(r["c"]) for r in city_status}
    top200_status_counts = dict(top200_status)

    city_no_access = status_share(city_status_counts, city_tot, NO_ACCESS_STATUS)
    top200_no_access = status_share(top200_status_counts, top200_tot, NO_ACCESS_STATUS)
    lift = (top200_no_access / city_no_access) if city_no_access else None

    insight = {
        "title": "Access barriers concentrate with building burden",
        "claim": (
            "Among the 200 buildings with the most open violations, the share of open "
            "violations stuck in “FIRST NO ACCESS TO RE-INSPECT” is about double the "
            "citywide rate — suggesting chronic open inventories are not only about "
            "issuance volume, but also about failed re-inspection access."
        ),
        "metrics": {
            "citywide_no_access_share": city_no_access,
            "top_200_no_access_share": top200_no_access,
            "lift": lift,
            "citywide_class_c_share": city_class_shares.get("C"),
            "top_1pct_class_c_share": top1_shares.get("C"),
            "citywide_class_i_share": city_class_shares.get("I"),
            "top_1pct_class_i_share": top1_shares.get("I"),
        },
        "why_non_obvious": (
            "Borough-level concentration is surprisingly similar (top 10% of buildings "
            "hold roughly half of open violations in every borough). The sharper "
            "difference shows up in status composition: high-burden buildings are "
            "enriched for no-access reinspection states, while informational Class I "
            "violations almost disappear from their open inventory."
        ),
    }

    class_compare = [
        {
            "name": f"Class {cls}",
            "citywide": round(city_class_shares.get(cls, 0) * 100, 1),
            "top_1pct_buildings": round(top1_shares.get(cls, 0) * 100, 1),
        }
        for cls in ["A", "B", "C", "I"]
    ]

    status_compare = []
    for name, short in [
        ("NOV SENT OUT", "NOV SENT OUT"),
        (NO_ACCESS_STATUS, "NO ACCESS TO RE-INSPECT"),
        ("NOT COMPLIED WITH", "NOT COMPLIED WITH"),
        ("VIOLATION WILL BE REINSPECTED", "VIOLATION WILL BE REINSPECTED"),
    ]:
        status_compare.append(
            {
                "name": short,
                "full_name": name,
                "citywide": round(status_share(city_status_counts, city_tot, name) * 100, 1),
                "top_200_buildings": round(
                    status_share(top200_status_counts, top200_tot, name) * 100, 1
                ),
            }
        )

    m50 = metrics["milestones"][0]
    structure = structure_block or {}
    structure_charts = structure.get("charts") or {}
    finding = structure.get("finding") or {}

    headlines = {
        "top_10pct_violation_share_pct": round(
            metrics["tops"][2]["violation_share"] * 100, 1
        ),
        "buildings_pct_for_half_violations": round(m50["building_fraction"] * 100, 1),
        "buildings_for_half_violations": m50["building_count"],
        "gini": round(metrics["gini"], 2),
        "tail_101plus_building_pct": round(metrics["buckets"][5]["building_share"] * 100, 1),
        "tail_101plus_violation_pct": round(
            metrics["buckets"][5]["violation_share"] * 100, 1
        ),
        "no_access_lift": round(lift, 2) if lift is not None else None,
    }
    if finding:
        type_counts = finding.get("type_counts") or {}
        n_profiles = len(structure.get("profiles_top200") or []) or 1
        headlines["top200_multi_dwelling_pct"] = round(
            100 * type_counts.get("multi_dwelling_complex", 0) / n_profiles, 1
        )
        headlines["top200_limited_unit_count"] = type_counts.get("limited_unit_signal", 0)
        headlines["top200_min_apartments"] = finding.get("min_distinct_apartments")

    return {
        "meta": {
            "dataset_id": dataset_id,
            "source": "live_socrata_soda_api",
            "scope": "Open HPD Violations only (currently open)",
            "dedupe_rule": (
                "Count distinct violationid only. If the same violationid appears more "
                "than once (including escalations entered twice as the same entry), "
                "it is counted once."
            ),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "unit_of_analysis": "buildingid",
            "raw_row_count": raw_rows,
            "distinct_violationid_count": distinct_vids,
            "duplicate_violationid_rows_removed": raw_rows - distinct_vids,
            "buildings_with_open_violations": metrics["n_buildings"],
            "total_open_violations_deduped": metrics["total_v"],
        },
        "hypothesis": {
            "statement": "Open violations are concentrated in a small fraction of buildings.",
            "decision_rule": (
                "Not disproved if top ~10% of buildings hold well over half of open violations."
            ),
            "result": metrics["result"],
            "gini": metrics["gini"],
            "top_shares": metrics["tops"],
            "buildings_needed_for_violation_milestones": metrics["milestones"],
        },
        "buckets": metrics["buckets"],
        "lorenz_curve": metrics["lorenz"],
        "by_boro_concentration": boro_rows,
        "class_mix": {
            "citywide": class_share_map(city_class),
            "top_1pct_buildings": top1_map,
            "top_200_buildings": top200_map,
        },
        "status_mix": {
            "citywide_top15": [
                {"name": r["currentstatus"], "value": int(r["c"])} for r in city_status
            ],
            "top_200_buildings_top10": [
                {"name": name, "value": int(val)}
                for name, val in top200_status.most_common(10)
            ],
        },
        "top_buildings": top_buildings,
        "top_building_structure": structure,
        "insight": insight,
        "charts": {
            "top_share_bars": [
                {
                    "name": f"Top {int(t['top_building_fraction'] * 100)}%",
                    "violation_share_pct": round(t["violation_share"] * 100, 1),
                    "buildings": t["top_building_count"],
                }
                for t in metrics["tops"]
            ],
            "bucket_bars": [
                {
                    "name": b["name"],
                    "building_share_pct": round(b["building_share"] * 100, 1),
                    "violation_share_pct": round(b["violation_share"] * 100, 1),
                }
                for b in metrics["buckets"]
            ],
            "class_compare": class_compare,
            "status_compare": status_compare,
            "boro_concentration": [
                {
                    "name": r["boro"],
                    "top_10pct_share_pct": round(r["top_10pct_violation_share"] * 100, 1),
                    "building_frac_for_50pct_pct": round(
                        r["building_frac_for_50pct_violations"] * 100, 1
                    ),
                }
                for r in boro_rows
            ],
            "structure_type_bars": structure_charts.get("structure_type_bars", []),
            "apartment_spread_bars": structure_charts.get("apartment_spread_bars", []),
        },
        "headlines": headlines,
    }


def main() -> None:
    cfg = load_socrata_settings()
    if not cfg["has_app_token"]:
        print(
            "WARNING: SOCRATA_APP_TOKEN is missing from the root .env. "
            "Queries may time out. Add a token and re-run."
        )

    client = make_client(cfg)
    ds = cfg["dataset_id"]
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    try:
        print("Step 0 — totals (distinct violationid)…")
        raw_rows = get_live_count(client, ds)
        distinct_vids = int(
            _soda_get(client, ds, select="count(distinct violationid) as n")[0]["n"]
        )
        print(
            f"  rows={raw_rows:,} distinct_violationid={distinct_vids:,} "
            f"dupes_removed={raw_rows - distinct_vids:,}"
        )

        print("Step 1 — download building-level counts…")
        df = fetch_building_counts(client, ds)
        print(f"  buildings={len(df):,} sum(c)={int(df['c'].sum()):,}")

        print("Step 2 — concentration metrics…")
        metrics = concentration_metrics(df)
        print(f"  result={metrics['result']} gini={metrics['gini']:.3f}")
        print(f"  top 10% share={metrics['tops'][2]['violation_share']:.1%}")

        print("Step 3a — borough heterogeneity…")
        boro_rows = borough_concentration(df)

        print("Step 3b — class mix (citywide vs top buildings)…")
        city_class = grouped_distinct_counts(client, ds, "class")
        k1 = max(1, int(np.ceil(len(df) * 0.01)))
        top1_class = counts_for_building_subset(
            client, ds, df.iloc[:k1]["buildingid"].tolist(), "class"
        )
        top200_class = counts_for_building_subset(
            client, ds, df.iloc[:200]["buildingid"].tolist(), "class"
        )

        print("Step 3c — status mix (citywide vs top 200)…")
        city_status = grouped_distinct_counts(client, ds, "currentstatus", top_n=15)
        top200_status = counts_for_building_subset(
            client, ds, df.iloc[:200]["buildingid"].tolist(), "currentstatus"
        )

        print("Step 3d — structure proxy for top 200 buildings (apartment/story)…")
        # Open violations have no official unit count; apartment + story are our proxy.
        top200_seed = [
            {
                "buildingid": str(row["buildingid"]),
                "boro": str(row.get("boro") or ""),
                "open_violations": int(row["c"]),
            }
            for _, row in df.head(200).iterrows()
        ]
        structure_profiles = profile_top_buildings(client, ds, top200_seed)
        structure_block = summarize_structure_profiles(structure_profiles)
        print("  structure types:", structure_block["finding"]["type_counts"])

        print("Step 3e — top 15 building table (with structure fields)…")
        # Reuse profiles so the website table matches the top-200 breakdown
        by_id = {p["buildingid"]: p for p in structure_profiles}
        top_buildings = []
        for _, row in df.head(15).iterrows():
            bid = str(row["buildingid"])
            profile = by_id.get(bid, {})
            top_buildings.append(
                {
                    "buildingid": bid,
                    "boro": str(profile.get("boro") or row.get("boro") or ""),
                    "housenumber": str(profile.get("housenumber") or ""),
                    "streetname": str(profile.get("streetname") or ""),
                    "zip": str(profile.get("zip") or ""),
                    "open_violations": int(row["c"]),
                    "distinct_apartments_with_opens": profile.get(
                        "distinct_apartments_with_opens"
                    ),
                    "distinct_stories_with_opens": profile.get(
                        "distinct_stories_with_opens"
                    ),
                    "max_story_observed": profile.get("max_story_observed"),
                    "blank_apartment_violation_share": profile.get(
                        "blank_apartment_violation_share"
                    ),
                    "structure_proxy": profile.get("structure_proxy"),
                    "sample_apartments": profile.get("sample_apartments", []),
                    "sample_stories": profile.get("sample_stories", []),
                }
            )

        payload = build_payload(
            dataset_id=ds,
            raw_rows=raw_rows,
            distinct_vids=distinct_vids,
            df=df,
            metrics=metrics,
            boro_rows=boro_rows,
            city_class=city_class,
            top1_class=top1_class,
            top200_class=top200_class,
            city_status=city_status,
            top200_status=top200_status,
            top_buildings=top_buildings,
            structure_block=structure_block,
        )
        OUT_PATH.write_text(json.dumps(payload, indent=2))
        print(f"Wrote {OUT_PATH}")
        print("Headlines:", json.dumps(payload["headlines"], indent=2))
    finally:
        client.close()


if __name__ == "__main__":
    main()
