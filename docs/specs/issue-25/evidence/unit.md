# Unit tests

Issue #25, verification run on 2026-10-12 against `loop/issue-25` at `2393e75`.
Testing-plan rows: T1.

## Python

`uv run pytest tests/unit`

```text
514 passed in 5.38s
rc=0 secs=7
```

## Web renderer

`cd renderers/web && bun run test` (vitest)

```text
 Test Files  3 passed (3)
      Tests  26 passed (26)
   Start at  00:13:15
   Duration  6.78s (environment 32%, tests 25%, import 20%, setup 13%, transform 9%, worker 1%)

rc=0 secs=9
```

Both suites pass. The Python suite includes the bounded-depth argument parser
(`tests/unit/models/test_json_args.py`). With it, the suite takes 6 s under
`ulimit -s unlimited`, which is how CI runners are set.
