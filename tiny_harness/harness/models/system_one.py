"""The System One model entity (R18.2): typed questions about a state, calibrated answers.

The shapes mirror TypeSafe AI's System One API (Jev) field for field, so the later Jev
adapter is a mapping with no interface change: a ``noul`` question answers with a
probability, a ``choice`` with the chosen option, its confidence and the probabilities of
every option, a ``score`` with a probability-weighted rubric level. The core loop does
not call a System One model in this work item; the interface, the deterministic fake and
the timeout contract ship so a later integration can fall back to the LLM on timeout.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Mapping
from datetime import timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from tiny_harness.harness.entities import Entity, EntityKind, EntityRef


class NoulQuestion(BaseModel, frozen=True):
    kind: Literal["noul"] = "noul"
    instructions: str


class ChoiceQuestion(BaseModel, frozen=True):
    kind: Literal["choice"] = "choice"
    instructions: str
    options: Mapping[str, str]


class ScoreQuestion(BaseModel, frozen=True):
    kind: Literal["score"] = "score"
    instructions: str
    levels: tuple[str, ...]


type Question = Annotated[
    NoulQuestion | ChoiceQuestion | ScoreQuestion, Field(discriminator="kind")
]


class NoulAnswer(BaseModel, frozen=True):
    kind: Literal["noul"] = "noul"
    probability: float = Field(ge=0.0, le=1.0)


class ChoiceAnswer(BaseModel, frozen=True):
    kind: Literal["choice"] = "choice"
    choice: str
    confidence: float = Field(ge=0.0, le=1.0)
    probabilities: Mapping[str, float]


class ScoreAnswer(BaseModel, frozen=True):
    kind: Literal["score"] = "score"
    score: float
    confidence: float = Field(ge=0.0, le=1.0)
    probabilities: Mapping[int, float]


type Answer = Annotated[NoulAnswer | ChoiceAnswer | ScoreAnswer, Field(discriminator="kind")]


class SystemOne(Entity):
    """Answers every question in one pass, within ``timeout``."""

    kind = EntityKind.SYSTEM_ONE

    @abstractmethod
    async def decide(
        self, state: str, questions: Mapping[str, Question], *, timeout: timedelta
    ) -> Mapping[str, Answer]: ...


class FakeSystemOne(SystemOne):
    """Deterministic answers for tests: a noul says yes with probability 0.5 unless scripted,
    a choice picks the first option, a score the middle level."""

    def __init__(self, scripted: Mapping[str, Answer] | None = None) -> None:
        super().__init__(EntityRef(kind=EntityKind.SYSTEM_ONE, id="fake", version=None))
        self._scripted = dict(scripted or {})
        self.calls: list[tuple[str, Mapping[str, Question]]] = []

    async def decide(
        self, state: str, questions: Mapping[str, Question], *, timeout: timedelta
    ) -> Mapping[str, Answer]:
        self.calls.append((state, questions))
        answers: dict[str, Answer] = {}
        for key, question in questions.items():
            if key in self._scripted:
                answers[key] = self._scripted[key]
            elif isinstance(question, NoulQuestion):
                answers[key] = NoulAnswer(probability=0.5)
            elif isinstance(question, ChoiceQuestion):
                options = list(question.options)
                share = 1.0 / len(options) if options else 0.0
                answers[key] = ChoiceAnswer(
                    choice=options[0] if options else "",
                    confidence=share,
                    probabilities={o: share for o in options},
                )
            else:
                levels = len(question.levels)
                middle = levels // 2
                answers[key] = ScoreAnswer(
                    score=float(middle),
                    confidence=1.0 / levels if levels else 0.0,
                    probabilities={i: (1.0 if i == middle else 0.0) for i in range(levels)},
                )
        return answers


__all__ = [
    "Answer",
    "ChoiceAnswer",
    "ChoiceQuestion",
    "FakeSystemOne",
    "NoulAnswer",
    "NoulQuestion",
    "Question",
    "ScoreAnswer",
    "ScoreQuestion",
    "SystemOne",
]
