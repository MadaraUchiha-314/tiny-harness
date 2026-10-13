"""A scripted model shared by a parent task and its child on the same harness.

Both tasks call the one model, in an order the test cannot fix, so each request is
answered from the script of the task it belongs to: the child's when its input carries
the child's goal and not the parent's first message."""

from __future__ import annotations

from collections.abc import Sequence

from tiny_harness.harness.models import FakeLLM, LLMRequest, LLMResponse, scripted
from tiny_harness.harness.models.llm import MessageItem


def texts(request: LLMRequest) -> str:
    return "\n".join(i.text for i in request.input if isinstance(i, MessageItem))


class RoutedLLM(FakeLLM):
    def __init__(
        self,
        *,
        parent: Sequence[LLMResponse],
        child: Sequence[LLMResponse],
        child_goal: str,
        parent_message: str,
    ) -> None:
        super().__init__([])
        self.parent, self.child = list(parent), list(child)
        self.child_goal, self.parent_message = child_goal, parent_message

    def is_child(self, request: LLMRequest) -> bool:
        seen = texts(request)
        return self.child_goal in seen and self.parent_message not in seen

    async def invoke(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        script = self.child if self.is_child(request) else self.parent
        return script.pop(0) if script else scripted("Nothing more to add.")


__all__ = ["RoutedLLM", "texts"]
