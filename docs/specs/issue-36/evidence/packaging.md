# T7 — packaging

2026-10-13, branch `loop/issue-36`, Python 3.14, local Temporal dev server (`start_local`).

## `uv run pytest tests/integration/test_package.py -v`

```text
tests/integration/test_package.py::test_built_wheel_installs_and_exposes_the_version PASSED [ 50%]
tests/integration/test_package.py::test_the_fastapi_helper_needs_its_extra PASSED [100%]
exit=0
```

`test_the_fastapi_helper_needs_its_extra` installs the built wheel without extras:
`import tiny_harness.fastapi` fails naming `tiny_harness[fastapi]`. With the extra
installed, the import succeeds (R3.4).
