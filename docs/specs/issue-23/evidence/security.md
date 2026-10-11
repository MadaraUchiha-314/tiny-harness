---
type: evidence
workItem: issue-23
row: T8
---

# Security and abuse-case tests (T8)

All 27 security tests pass at `34dccbc`; `tests/security/test_push_token.py` is rewritten
for issue-23's abuse cases.

```text
$ uv run pytest tests/security -v
tests/security/test_push_token.py::test_push_credentials_are_stored_as_supplied PASSED
tests/security/test_push_token.py::test_push_credentials_are_masked_when_printed PASSED
tests/security/test_push_token.py::test_a_row_stored_encrypted_by_an_earlier_version_is_legacy PASSED
tests/security/test_push_token.py::test_a_new_sqlite_store_is_readable_by_its_owner_only PASSED
tests/security/test_push_token.py::test_an_existing_sqlite_store_keeps_its_mode PASSED
27 passed in 2.88s
```

| Abuse case (requirements.md) | Test | Outcome |
|---|---|---|
| 1 — another local user reads a new store | `test_a_new_sqlite_store_is_readable_by_its_owner_only` (mode `0600`); `test_an_existing_sqlite_store_keeps_its_mode` (out-of-scope boundary held) | pass |
| 2 — credential in logs or prints | `test_push_credentials_are_masked_when_printed` (`repr`, `str`, `model_dump()`); the legacy-drop warning carries ids only (integration scenario 7) | pass |
| 3 — the ignored key's value echoed | `test_an_exported_push_key_is_warned_about_without_its_value` (unit); manual T11 (`key_in_log=0`) | pass |
| 4 — ciphertext sent to a webhook | `test_a_row_stored_encrypted_by_an_earlier_version_is_legacy`; integration scenario 7 (nothing posted) | pass |

**Red before green:** the new file failed three of five tests on the old code
(`3 failed, 2 passed`): no `token` field, no `legacy`, and a new store file at
`644`.
