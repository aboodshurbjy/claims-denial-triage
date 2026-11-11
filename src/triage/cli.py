"""Command line: generate synthetic data, build the database, serve the API."""

from __future__ import annotations

import argparse
import json
import sys

from . import config, pipeline
from .generator import generate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="triage", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    gen = commands.add_parser("generate", help="write synthetic source files")
    gen.add_argument("--seed", type=int, default=42)
    gen.add_argument("--if-missing", action="store_true", help="skip when source files already exist")

    commands.add_parser("build", help="run the SQL pipeline and its assertions")

    serve = commands.add_parser("serve", help="start the API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)

    if args.command == "generate":
        if args.if_missing and (config.RAW_DIR / "claims_export.csv").exists():
            print(f"source files already present in {config.RAW_DIR}")
            return 0
        print(json.dumps(generate(config.DATA_DIR, args.seed), indent=2))
        return 0

    if args.command == "build":
        try:
            results = pipeline.build()
        except pipeline.AssertionFailure as failure:
            print(pipeline.format_results(failure.results))
            print(f"\n{failure}", file=sys.stderr)
            return 1
        print(pipeline.format_results(results))
        print(f"\nbuilt {config.DB_PATH}")
        return 0

    import uvicorn
    uvicorn.run("triage.api:app", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
