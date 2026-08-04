#!/usr/bin/env python
"""
Django's command-line utility.

Common commands (run from the backend/ folder):
  python manage.py runserver          # start the API on http://127.0.0.1:8000
  python manage.py migrate            # create/update database tables
  python manage.py createsuperuser    # create an admin login
  python manage.py test               # run Django's built-in tests
"""

import os
import sys


def main():
    """Run administrative tasks."""
    # Tell Django which settings file to use
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Is it installed and is your virtual "
            "environment activated? Try: pip install -r requirements.txt"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
