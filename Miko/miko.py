from __future__ import annotations

import argparse
from pathlib import Path

from miko_app.cli import MikoCli
from miko_app.config import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Miko v0.1 local AI companion")
    parser.add_argument("--session", help="Start or resume a named session")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent
    settings = load_settings(project_root / "config" / "settings.yaml", project_root)
    cli = MikoCli(settings=settings, initial_session=args.session)
    cli.run()


if __name__ == "__main__":
    main()
