---
type: evidence
phase: needs-review
workItem: issue-38
---

# Self-review: multi-modal input and output, with a voice mode

> The `self-review` node's proof. Policy (`the-loop critic policy`): `selfReviewCount: 2`,
> stop on no new findings, escalate on a repeated finding. Each round was a fresh-context,
> read-only review of the code diff (`tiny_harness`, `renderers/web/src`,
> `examples/multimodal`, `tests`) against `requirements.md` and `design.md`.

## Review cycles

| Round | Reviewer | Outcome | Findings → disposition | Link |
|-------|----------|---------|------------------------|------|
| 1 | `claude/opus-5.5` | 7 new findings (2 major, 5 minor), no blocker | 1.1 TUI de-dup of `image:`/`speech:` artifacts → fixed `c93f7d6` · 1.2 overlapping `PcmPlayer` plays, Escape could not stop → `165e12f` · 1.3 web mic left live when the recorder failed → `08890bd` · 1.4 TUI `Recorder.start` leak on a PortAudio error → `66f887d` · 1.5 `sniff` trusted WAV byte rate and MP4 deltas → `455b74f` · 1.6 async media streams not closed on early exit → `80f7825` · 1.7 route gave 500 for a file removed after lookup → `3314ab1` | [findings](https://github.com/MadaraUchiha-314/tiny-harness/pull/39#issuecomment-6350909471), [replies](https://github.com/MadaraUchiha-314/tiny-harness/pull/39#issuecomment-6350910046) |
| 2 | `claude/opus-5.5` | 9 new findings (1 high, 2 medium, 6 low); two complete round-1 fixes 3 and 6, not repeats | 2.1 no per-request media byte budget → `8c01d6c`, `67ee452` · 2.2 large text parts under the media body cap → `3b33ad4` · 2.3 web player kept scheduled audio after a broken stream → `f3d0317` · 2.4 purge deleted media before terminating → `29f9d66` · 2.5 web re-downloaded sent files, refused blobs not revoked → `d78e416` · 2.6 sweep race and stale temp files → `5f7ab4f` · 2.7 meter `AudioContext` leak on a failed start → `a60dad5` · 2.8 interrupted transcription lost the transcript → `d657ced` · 2.9 speech writer file left open on a retryable failure → `f5b9e3f` | [findings](https://github.com/MadaraUchiha-314/tiny-harness/pull/39#issuecomment-6351379543), [replies](https://github.com/MadaraUchiha-314/tiny-harness/pull/39#issuecomment-6351379964) |

The cap of two rounds was reached; it did not converge to zero. Every fix was written test
first, and the red reason is in each commit body. After round 2: 1 272 Python
unit/contract/security/UI tests, 33 media integration tests, 104 web unit tests and 28
strict visual tests pass, and pre-commit passes.
