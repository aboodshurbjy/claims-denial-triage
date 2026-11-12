# Design decisions

Moved here from the [README](../README.md).

## Rules as pure functions

Each rule is a function of `(claim, context, parameters)` that returns a status and a reason. `rules.py` imports only the standard library: no database, no web framework, no YAML parser, no clock. A test enforces that.

- A rule test builds a claim and a few facts in memory and asserts the result. There is no database to seed and nothing to mock, so I could give every boundary its own test (the last covered day, the 90th day, the unit that tips an auth over).
- The evaluation date is an input. The rules never read the clock, so I can reproduce a result months later when a denial is disputed.
- `POST /check`, the evaluation of the whole queue, and the test suite all call the same functions. There is no second copy of the logic in SQL or in the UI.
- A rule cannot return a status without a reason, so the trace a biller reads comes from the code path that made the decision.
- The rules know nothing about DuckDB or FastAPI, so either can be replaced without touching payer logic.

## Versioned ruleset

Payer policy changes. Filing limits move, codes start requiring authorization, unit caps are revised. So policy lives in a YAML file with an explicit `version` and `effective_date`, kept in git.

- The ruleset version is stamped on every trace and API response. If a claim passed last month and fails today, either the data changed or the version did, and both can be checked.
- Raising a threshold is a one-line diff in a file a billing lead can read, plus a changelog entry.
- Checking out an old version of the file reproduces what the system would have said under the old policy.
- The loader rejects unknown rule names, duplicates and missing fields at startup, so a bad edit fails at startup and no check is skipped quietly.

## Other choices

- DuckDB and plain SQL. The data is small and file-based. One embedded database reads CSV and JSON directly and needs no server, and plain `.sql` files are readable by anyone who knows SQL. The Excel roster is the one source read in Python, because spreadsheet cells are typed and must be flattened to text first.
- The raw layer is kept as delivered. Nothing is cleaned on the way in, so a surprising result can be traced back to the exact source row.
- Assertions are queries. Each file in `sql/tests/` selects the rows that violate an expectation. Error-level violations stop the build. Warn-level ones (for example, claims whose patient is not on the roster) are reported and left for the rules to surface.
- Unmatched claims are kept. A claim whose member could not be resolved is one of the most likely to be denied, so dropping it would hide it.
