# Verification output — issue-2

Captured 2026-10-08 from a fresh clone of branch `issue-2-repo-tooling` at commit
`81eb80c`. `<scratch>` is a temporary directory; home paths are shortened to `~`.

## Fresh clone: setup, hooks, tests, build, docs

```text
$ uv sync --locked
Using CPython 3.14.7 interpreter at: /usr/bin/python3.14
Creating virtual environment at: .venv
Resolved 34 packages in 0.81ms
   Building tiny-harness @ file:///tmp/claude-1000/-home-the-looper--the-loop-workspace--worktrees-github-com-MadaraUchiha-314-tiny-harness-github-MadaraUchiha-314-tiny-harness-2/47f7a8e0-9a2d-4e26-a741-4f44f3b165fa/scratchpad/fresh
      Built tiny-harness @ file:///tmp/claude-1000/-home-the-looper--the-loop-workspace--worktrees-github-com-MadaraUchiha-314-tiny-harness-github-MadaraUchiha-314-tiny-harness-2/47f7a8e0-9a2d-4e26-a741-4f44f3b165fa/scratchpad/fresh
Prepared 1 package in 3ms
warning: Failed to hardlink files; falling back to full copy. This may lead to degraded performance.
         If the cache and target directories are on different filesystems, hardlinking may not be supported.
         If this is intentional, set `export UV_LINK_MODE=copy` or use `--link-mode=copy` to suppress this warning.
Installed 34 packages in 278ms
exit=0

$ ls -d .venv && .venv/bin/python --version
.venv
Python 3.14.7

$ uv run pre-commit install
pre-commit installed at .git/hooks/pre-commit
pre-commit installed at .git/hooks/commit-msg

$ uv run pre-commit run --all-files
ruff (lint + autofix)....................................................Passed
ruff (format)............................................................Passed
pyright (type check).....................................................Passed
pytest (unit tests)......................................................Passed
markdownlint.............................................................Passed
exit=0

$ uv run pytest -v
tests/integration/test_package.py::test_built_wheel_installs_and_exposes_hello_world PASSED [  6%]
tests/unit/test_hello.py::test_hello_world_returns_greeting PASSED       [ 12%]
tests/unit/test_workflows.py::test_workflow_defaults_to_read_only_contents[ci.yml] PASSED [ 18%]
tests/unit/test_workflows.py::test_workflow_defaults_to_read_only_contents[release.yml] PASSED [ 25%]
tests/unit/test_workflows.py::test_no_workflow_uses_pull_request_target[ci.yml] PASSED [ 31%]
tests/unit/test_workflows.py::test_no_workflow_uses_pull_request_target[release.yml] PASSED [ 37%]
tests/unit/test_workflows.py::test_no_workflow_uses_pull_request_target[docs.yml] PASSED [ 43%]
tests/unit/test_workflows.py::test_ci_runs_on_pull_requests_and_can_be_called PASSED [ 50%]
tests/unit/test_workflows.py::test_ci_never_requests_write_or_oidc PASSED [ 56%]
tests/unit/test_workflows.py::test_ci_runs_the_precommit_hooks_integration_tests_and_docs_build PASSED [ 62%]
tests/unit/test_workflows.py::test_release_runs_ci_before_bumping_and_publishing PASSED [ 68%]
tests/unit/test_workflows.py::test_release_triggers_on_push_to_main PASSED [ 75%]
tests/unit/test_workflows.py::test_only_the_bump_job_can_write_contents PASSED [ 81%]
tests/unit/test_workflows.py::test_only_the_publish_job_gets_an_oidc_token_in_env_pypi PASSED [ 87%]
tests/unit/test_workflows.py::test_bump_skips_its_own_bump_commit PASSED [ 93%]
tests/unit/test_workflows.py::test_docs_deploys_from_main_with_pages_scopes_only PASSED [100%]
============================== 16 passed in 0.29s ==============================

$ uv run python -c "from tiny_harness import hello_world; print(hello_world())"
Hello, world!

$ uv build
Successfully built dist/tiny_harness-0.0.0.tar.gz
Successfully built dist/tiny_harness-0.0.0-py3-none-any.whl

$ (cd docs && bun install --frozen-lockfile && bun run docs:build)
127 packages installed [154.00ms]
build complete in 3.46s.
```

## Negative checks: the git hooks block bad commits

Run in the same fresh clone after `uv run pre-commit install`. Each change was reset
after its attempt.

```text
$ echo x >> README.md && git commit -am "bad message"
ruff (lint + autofix)................................(no files to check)Skipped
ruff (format)........................................(no files to check)Skipped
pyright (type check).................................(no files to check)Skipped
pytest (unit tests)..................................(no files to check)Skipped
markdownlint.............................................................Passed
Conventional Commits (commitizen)........................................Failed
- hook id: commitizen
- exit code: 14

commit validation: failed!
please enter a commit message in the commitizen format.
commit "": "bad message
"pattern: (?s)(build|bump|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)(\(\S+\))?!?: ([^\n\r]+)((\n\n.*)|(\s*))?$

exit=1

$ git commit -am "docs: good message"
ruff (lint + autofix)................................(no files to check)Skipped
ruff (format)........................................(no files to check)Skipped
pyright (type check).................................(no files to check)Skipped
pytest (unit tests)..................................(no files to check)Skipped
markdownlint.............................................................Passed
Conventional Commits (commitizen)........................................Passed
[issue-2-repo-tooling b61b308] docs: good message
exit=0

$ printf "import os\n" > tiny_harness/bad.py && git add -A && git commit -m "feat: add unused import"
ruff (lint + autofix)....................................................Failed
- hook id: ruff-lint
- files were modified by this hook

Found 1 error (1 fixed, 0 remaining).

ruff (format)............................................................Passed
pyright (type check).....................................................Passed
pytest (unit tests)......................................................Passed
markdownlint.........................................(no files to check)Skipped
exit=1

$ sed -i "s/Hello, world!/Hi/" tiny_harness/hello.py && git commit -am "fix: break greeting"
ruff (lint + autofix)....................................................Passed
ruff (format)............................................................Passed
pyright (type check).....................................................Passed
pytest (unit tests)......................................................Failed
E       AssertionError: assert 'Hi' == 'Hello, world!'
tests/unit/test_hello.py:5: AssertionError
1 failed, 14 passed in 0.10s
exit=1

$ printf "def f(x):\n    return x.nope\n" > tiny_harness/untyped.py && git add -A && git commit -m "feat: untyped"
ruff (lint + autofix)....................................................Passed
ruff (format)............................................................Passed
pyright (type check).....................................................Failed
  <scratch>/fresh/tiny_harness/untyped.py:1:5 - error: Return type is unknown (reportUnknownParameterType)
  <scratch>/fresh/tiny_harness/untyped.py:1:7 - error: Type of parameter "x" is unknown (reportUnknownParameterType)
  <scratch>/fresh/tiny_harness/untyped.py:1:7 - error: Type annotation is missing for parameter "x" (reportMissingParameterType)
  <scratch>/fresh/tiny_harness/untyped.py:2:12 - error: Type of "nope" is unknown (reportUnknownMemberType)
  <scratch>/fresh/tiny_harness/untyped.py:2:12 - error: Return type is unknown (reportUnknownVariableType)
5 errors, 0 warnings, 0 informations
pytest (unit tests)......................................................Passed
exit=1
```

## Release version computation (dry run)

In a throwaway clone, with a local baseline tag `v0.0.0` on `main`'s tip (what
`release.yml` seeds on the first release):

```text
$ uv run cz bump --dry-run --yes
bump: version 0.0.0 → 0.1.0
tag to create: v0.1.0
increment detected: MINOR

$ uv run cz bump --yes && git show --stat HEAD
    bump: version 0.0.0 → 0.1.0

 pyproject.toml | 2 +-
 uv.lock        | 2 +-
 2 files changed, 2 insertions(+), 2 deletions(-)
```

## Pull request CI

```text
$ the-loop pr status github:MadaraUchiha-314/tiny-harness#5
  "headSha": "81eb80c776811229623b053ef2ab91b5321c76e6",
  "checks": { "conclusion": "success", "total": 3, "failing": [], "pending": [] }
```

The three checks are `ci.yml`'s jobs: lint/type check/unit tests/markdownlint,
integration tests, docs build.
