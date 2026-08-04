"""
Management command: download the Open HPD Violations SODA table.

Run from the backend/ folder (with the venv active):

  python manage.py fetch_soda_violations

Flow (in this exact order):
  1) Ask the API what the rate / page limits are
  2) Count how many entries exist (COUNT(*))
  3) Download every page with limit + offset (sodapy + pandas)
  4) Save into backend/data/soda_violations.sqlite3

Optional quicker sample:

  python manage.py fetch_soda_violations --max-rows 5000
"""

from django.core.management.base import BaseCommand

from violations.data_store import refresh_from_socrata
from violations.socrata_client import discover_api_limits, get_record_count


class Command(BaseCommand):
    help = "Fetch the SODA Open HPD Violations table into the local SQLite cache."

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-rows",
            type=int,
            default=None,
            help=(
                "Optional cap for a quicker sample download. "
                "Omit this flag to download the entire remote table."
            ),
        )

    def handle(self, *args, **options):
        max_rows = options.get("max_rows")

        # ---- 1) Rate / page limits ------------------------------------------
        self.stdout.write("Step 1/3 — Asking the API for rate / page limits...")
        limits = discover_api_limits()
        self.stdout.write(
            self.style.NOTICE(
                f"  page limit (rows per request): {limits['page_limit']:,}"
            )
        )
        self.stdout.write(
            self.style.NOTICE(
                f"  requests / hour ({limits['requests_per_hour_source']}): "
                f"{limits['requests_per_hour']:,}"
            )
        )
        self.stdout.write(
            self.style.NOTICE(
                f"  app token present: {limits['has_app_token']}"
            )
        )
        if limits.get("rate_limit_headers"):
            self.stdout.write(
                f"  rate-limit headers: {limits['rate_limit_headers']}"
            )

        # ---- 2) Entry count -------------------------------------------------
        self.stdout.write("Step 2/3 — Counting entries (COUNT(*))...")
        total = get_record_count()
        self.stdout.write(self.style.NOTICE(f"  remote entries: {total:,}"))
        if max_rows:
            self.stdout.write(
                self.style.NOTICE(f"  this run will stop after {max_rows:,} rows")
            )

        # ---- 3) Full download via limit + offset ----------------------------
        def progress(fetched, expected):
            pct = (fetched / expected * 100) if expected else 0
            self.stdout.write(
                f"  downloaded {fetched:,} / {expected:,} ({pct:5.1f}%)",
                ending="\r",
            )
            self.stdout.flush()

        self.stdout.write(
            "Step 3/3 — Downloading with limit + offset (sodapy + pandas)..."
        )
        summary = refresh_from_socrata(
            progress_callback=progress,
            max_rows=max_rows,
        )
        self.stdout.write("")  # finish the progress line
        self.stdout.write(
            self.style.SUCCESS(
                f"Saved {summary['rows_saved']:,} rows to {summary['sqlite_path']}"
            )
        )
        self.stdout.write(
            f"Remote total: {summary.get('remote_total', total):,} · "
            f"page limit used: {summary.get('page_limit_used', limits['page_limit']):,}"
        )
        self.stdout.write(f"Columns: {', '.join(summary['columns'])}")
