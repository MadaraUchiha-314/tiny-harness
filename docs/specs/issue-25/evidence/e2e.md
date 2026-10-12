# End-to-end

Issue #25, verification run on 2026-10-12 against `loop/issue-25` at `2393e75`.
Testing-plan rows: T4.

`TINY_HARNESS_OLLAMA_MODEL=qwen3:1.7b uv run pytest tests/e2e/test_demo_ollama.py -m e2e`

This is the demo with no network: embedded Temporal, plus Ollama on `127.0.0.1:11434`
behind `[openai] base_url`. Neither `OPENAI_API_KEY` nor `TEMPORAL_API_KEY` is set.

```text
1 passed in 558.77s (0:09:18)
```

Most of that time is the 1.7B model running on the CPU.

Observed state sequence:

```text
[   7.2s] task           TASK_STATE_SUBMITTED     b7cca180-34f8-4815-a21e-f2262ac9b86d
[   7.2s] status_update  TASK_STATE_WORKING       
[ 443.4s] status_update  TASK_STATE_INPUT_REQUIRED The plan has been successfully created with two steps to resolve the refund request. The next action is to execute these steps:  
1. **Check order status and resolve based on policy** (verify eligibility for refund/replacement).  
2. **Request damage photo for refund** (await customer approval).  

No further tool calls are needed. The resolution process is underway.
[ 443.8s] status_update  TASK_STATE_WORKING       
[ 552.4s] status_update  TASK_STATE_INPUT_REQUIRED I'll present resolution options to the customer:  
**A2UI Card:**  
- **Option 1:** Refund (requires damage photo)  
- **Option 2:** Replacement (no photo needed)  
Ask the customer to confirm their choice before proceeding.  

No further tool calls are needed. The resolution process is underway.
[ 552.8s] status_update  TASK_STATE_INPUT_REQUIRED Task b7cca180-34f8-4815-a21e-f2262ac9b86d · Refund order #48213: the customer says the blender arrived c
State: INPUT_REQUIRED · awaiting-next-message
Model: qwen3:1.7b (default)
Effort: provider default
Plan: 0/2 steps done
Sub-tasks: none
[ 554.8s] task           TASK_STATE_INPUT_REQUIRED b7cca180-34f8-4815-a21e-f2262ac9b86d
[ 555.4s] status_update  TASK_STATE_COMPLETED     completed by alice
```

1. The complaint's turn ends `INPUT_REQUIRED · awaiting-next-message`, and the task stays
   open (R3.1).
2. A second message continues the same task id, which parks again.
3. `/status` replies `Task <id> · …` / `State: INPUT_REQUIRED · awaiting-next-message`.
   The trace's `chat` span count does not change, so no model call was made (R6.2,
   R10).
4. The reporter's complete control ends the task `COMPLETED`, with `completed by alice`
   (R3.2).
5. The server log names the loopback endpoint and `api=chat_completions`, and no secret
   value appears in the trace or the log.

The OpenAI-backed e2e tests (`test_demo.py`, `test_demo_embedded.py`,
`test_crash_recovery.py`) need `OPENAI_API_KEY` and skip here. Their driver now
completes the parked task explicitly, so they still assert `COMPLETED`.
