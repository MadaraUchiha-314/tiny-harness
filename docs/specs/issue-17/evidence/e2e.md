# End-to-end: the demo in embedded mode

Work item: issue-17 · testing-plan row T4 · commit `cdd0785` · run 2026-10-10. `OPENAI_API_KEY` from the keyring (`secret-tool lookup service openai project tiny-harness`), `TEMPORAL_API_KEY` unset, model `gpt-6.1-sol`. The transcript lines are the A2A stream as the client saw it.

## The embedded demo, one serve process, no Temporal key

```sh
env -u TEMPORAL_API_KEY uv run pytest tests/e2e/test_demo_embedded.py -s -v --basetemp ~/.cache/tiny-harness-pytest/run 2>&1 | grep -E '^\[|PASSED|FAILED|passed|failed|skipped'
```

Exit status `0` in 73.8 s.

````text
[   9.3s] status_update  TASK_STATE_WORKING       
[  46.7s] artifact_update                          a2ui
[  50.6s] status_update  TASK_STATE_INPUT_REQUIRED I'm sorry the blender arrived cracked. For order #48213, would you like the $129 refund or a replacement? Please confirm when the damage was reported (the policy requires reporting within 14 days of October 6, 2026). For a refund, please provide a photo of the damage; for a replacement, confirm the shipping address, since your blender order lists 14 Harbour Lane and your other open order lists 3 Quay Street, Portsea.
[  51.0s] status_update  TASK_STATE_WORKING       
[  54.9s] status_update  TASK_STATE_INPUT_REQUIRED You've selected the $129 refund for order #48213. Before I can issue it, please provide a photo showing the cracked blender and confirm the date you reported the damage, so I can verify it was within 14 days of delivery on October 6, 2026.
[  55.3s] status_update  TASK_STATE_WORKING       
[  71.2s] status_update  TASK_STATE_COMPLETED     Your replacement blender for order #48213 is shipping to 14 Harbour Lane, Portsea, with tracking number **NB-48213-R1**. No refund was issued, and order #48377 was left unchanged.
PASSED
========================= 1 passed in 72.93s (0:01:12) =========================
````
