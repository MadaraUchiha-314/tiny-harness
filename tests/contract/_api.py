"""Public-API snapshots: the contract tests of Requirement 23.

``snapshot(module)`` renders every public name of a module with its signature (or its
fields, for Pydantic models and enums) and compares it with the committed file under
``snapshots/``. Set ``UPDATE_API_SNAPSHOTS=1`` to rewrite a snapshot on purpose; a diff
without that is an incompatible change caught before it ships (T3).
"""

from __future__ import annotations

import enum
import inspect
import os
from pathlib import Path
from types import ModuleType

import pydantic

SNAPSHOTS = Path(__file__).parent / "snapshots"


def _render(name: str, obj: object) -> str:
    if inspect.isclass(obj) and issubclass(obj, enum.Enum):
        members = ", ".join(f"{m.name}={m.value!r}" for m in obj)
        return f"enum {name}: {members}"
    if inspect.isclass(obj) and issubclass(obj, pydantic.BaseModel):
        fields = ", ".join(
            f"{field}: {info.annotation!r}" + ("" if info.is_required() else " = ...")
            for field, info in obj.model_fields.items()
        )
        return f"model {name}({fields})"
    if inspect.isclass(obj):
        methods: list[str] = []
        for attr, value in sorted(vars(obj).items()):
            if attr.startswith("_") and attr != "__init__":
                continue
            if inspect.isfunction(value):
                methods.append(f"  def {attr}{inspect.signature(value)}")
            elif isinstance(value, property):
                methods.append(f"  property {attr}")
        bases = ", ".join(b.__name__ for b in obj.__bases__)
        return "\n".join([f"class {name}({bases})", *methods])
    if inspect.isfunction(obj):
        return f"def {name}{inspect.signature(obj)}"
    return f"{name} = {type(obj).__name__}"


def render_module(module: ModuleType) -> str:
    names = getattr(module, "__all__", None) or [n for n in vars(module) if not n.startswith("_")]
    lines = [f"# {module.__name__}"]
    for name in names:
        lines.append(_render(name, getattr(module, name)))
    return "\n".join(lines) + "\n"


def assert_snapshot(module: ModuleType) -> None:
    rendered = render_module(module)
    path = SNAPSHOTS / f"{module.__name__}.txt"
    if os.environ.get("UPDATE_API_SNAPSHOTS") == "1" or not path.exists():
        path.write_text(rendered)
    expected = path.read_text()
    assert rendered == expected, (
        f"public API of {module.__name__} changed; review the diff and, if intended, "
        "rerun with UPDATE_API_SNAPSHOTS=1"
    )
