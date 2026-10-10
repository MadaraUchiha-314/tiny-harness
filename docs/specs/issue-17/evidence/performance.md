# Performance: embedded startup

Work item: issue-17 · testing-plan row T7 · commit `cdd0785` · run 2026-10-10 on Linux (Python 3.14, temporalio 1.34.0, Temporal CLI 1.9.1).

## Five cached starts of the embedded dev server

```sh
env -u TEMPORAL_API_KEY uv run pytest tests/integration/embedded -k startup_time -s -q --basetemp ~/.cache/tiny-harness-pytest/run 2>&1 | grep -E 'embedded startup|passed|failed'
```

Exit status `0` in 4.8 s.

````text
embedded startup (s): [0.11, 0.11, 0.11, 0.11, 0.11] median=0.11 max=0.11 budget=10
1 passed, 14 deselected in 0.72s
````

## The dev server binary

```sh
ls ~/.cache/temporalio/ && ~/.cache/temporalio/temporal-sdk-python-1.34.0 --version
```

Exit status `0` in 0.1 s.

````text
temporal-sdk-python-1.34.0
temporal-test-server-sdk-python-1.34.0
temporal version 1.9.1 (Server 1.32.0, UI 2.54.1)
````
