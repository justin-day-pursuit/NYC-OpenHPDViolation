#!/usr/bin/env python3
"""
Run a live Open HPD Violations analysis without opening Jupyter.

What it does:
  1) Calls the NYC Open Data SODA API (fresh source — NOT local SQLite)
  2) Prints borough / class / status / monthly counts
  3) Saves chart PNGs under notebooks/output/

How to run (non-technical):
  cd notebooks
  source .venv/bin/activate          # after pip install -r requirements.txt
  python run_live_analysis.py

Optional filter example (Bronx only):
  python run_live_analysis.py --where "boro='BRONX'"
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt

from soda_live import fetch_live_overview, load_socrata_settings


def _bar_chart(df, title: str, out_path: Path, *, horizontal: bool = False) -> None:
    """Save a simple bar chart PNG from a name/value DataFrame."""
    if df is None or df.empty:
        print(f"  skip chart (no data): {title}")
        return

    fig, ax = plt.subplots(figsize=(9, 4.5))
    if horizontal:
        ax.barh(df["name"], df["value"], color="#0b5fff")
        ax.invert_yaxis()
        ax.set_xlabel("Violations")
    else:
        ax.bar(df["name"], df["value"], color="#0b5fff")
        ax.set_ylabel("Violations")
        ax.tick_params(axis="x", rotation=30)
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    print(f"  wrote {out_path}")


def _line_chart(df, title: str, out_path: Path) -> None:
    """Save a monthly trend line chart."""
    if df is None or df.empty:
        print(f"  skip chart (no data): {title}")
        return

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(df["name"], df["value"], color="#0b5fff", linewidth=2)
    ax.set_title(title)
    ax.set_ylabel("Inspections")
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    print(f"  wrote {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Live SODA analysis for Open HPD Violations (no local cache)."
    )
    parser.add_argument(
        "--where",
        default="",
        help="Optional SoQL WHERE clause, e.g. boro='BRONX' or class='C'",
    )
    args = parser.parse_args()
    where = args.where.strip() or None

    cfg = load_socrata_settings()
    print("Live SODA analysis (source API — not local SQLite)")
    print(f"  env file : {cfg['env_path']}")
    print(f"  dataset  : {cfg['dataset_id']} @ {cfg['domain']}")
    print(f"  app token: {'yes' if cfg['has_app_token'] else 'NO — add SOCRATA_APP_TOKEN to .env'}")
    if where:
        print(f"  where    : {where}")

    # This can take 1–3 minutes — COUNT/GROUP BY on ~3M remote rows is slow
    print("\nFetching live aggregates (please wait)…")
    overview = fetch_live_overview(where=where)

    print(f"\nLive matching rows: {overview['row_count']:,}")
    print("\nBy borough:")
    print(overview["by_boro"].to_string(index=False))
    print("\nBy class:")
    print(overview["by_class"].to_string(index=False))
    print("\nTop statuses:")
    print(overview["by_currentstatus"].head(10).to_string(index=False))
    print("\nRecent months:")
    print(overview["by_month"].tail(6).to_string(index=False))

    out_dir = Path(__file__).resolve().parent / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("\nSaving charts…")
    _bar_chart(overview["by_boro"], "Open violations by borough (live SODA)", out_dir / "by_boro.png")
    _bar_chart(overview["by_class"], "Open violations by class (live SODA)", out_dir / "by_class.png")
    _bar_chart(
        overview["by_currentstatus"],
        "Top current statuses (live SODA)",
        out_dir / "by_status.png",
        horizontal=True,
    )
    _line_chart(
        overview["by_month"],
        "Inspections by month (live SODA)",
        out_dir / "by_month.png",
    )
    print("\nDone. Charts are in notebooks/output/")


if __name__ == "__main__":
    main()
