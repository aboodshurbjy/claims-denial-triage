"""Command line: generate synthetic data, build the database, validate the rules, serve the API."""

from __future__ import annotations

import argparse
import json
import sys

from . import config, pipeline, validation
from .generator import generate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="triage", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    gen = commands.add_parser("generate", help="write synthetic source files")
    gen.add_argument("--seed", type=int, default=42)
    gen.add_argument("--if-missing", action="store_true", help="skip when source files already exist")

    commands.add_parser("build", help="run the SQL pipeline and its assertions")

    commands.add_parser("validate", help="score the rules against the generator's answer key")

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

    if args.command == "validate":
        manifest_path = config.DATA_DIR / "manifest.json"
        seed = json.loads(manifest_path.read_text()).get("seed") if manifest_path.exists() else None
        result = validation.validate(seed=seed)
        print(validation.format_validation(result))
        return 0 if result.ok else 1

    import uvicorn
    uvicorn.run("triage.api:app", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
