"""The A2UI basic catalog on Textual widgets (R20.6): every component of the catalog has
a widget; Video and AudioPlayer render the placeholder of R20.4. Data bindings resolve
against the surface's data model, which input widgets update, and a Button's
``action.event`` becomes an ``Action`` with its context resolved.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import cast

from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import (
    Button,
    Checkbox,
    Collapsible,
    Input,
    RadioButton,
    RadioSet,
    Rule,
    SelectionList,
    Static,
)

from tiny_harness.interaction.a2ui import (
    Action,
    CreateSurface,
    ServerMessage,
    UpdateComponents,
    UpdateDataModel,
)
from tiny_harness.jsontypes import JsonObject, JsonValue

PLACEHOLDER_COMPONENTS = frozenset({"Video", "AudioPlayer"})
ActionSink = Callable[[Action], None]


def _text(value: JsonValue, data: Mapping[str, JsonValue]) -> str:
    """A ``DynamicString``: a literal, a data-model path, or a function call (shown as is)."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        path = value.get("path")
        if isinstance(path, str):
            bound = data.get(path.lstrip("/"))
            return "" if bound is None else str(bound)
        call = value.get("call")
        if isinstance(call, str):
            return f"<{call}>"
    return "" if value is None else str(value)


class SurfaceState:
    """One surface: its components by id and its data model."""

    def __init__(self, surface_id: str, catalog_id: str) -> None:
        self.surface_id = surface_id
        self.catalog_id = catalog_id
        self.components: dict[str, JsonObject] = {}
        self.data: dict[str, JsonValue] = {}

    def set(self, path: str, value: JsonValue) -> None:
        self.data[path.lstrip("/")] = value

    def resolve_context(self, context: JsonObject) -> JsonObject:
        resolved: JsonObject = {}
        for key, value in context.items():
            if isinstance(value, dict) and isinstance(value.get("path"), str):
                resolved[key] = self.data.get(str(value["path"]).lstrip("/"))
            else:
                resolved[key] = value
        return resolved


class Surfaces:
    """Client-side registry of the surfaces the agent created (mirrors the server's)."""

    def __init__(self) -> None:
        self.by_id: dict[str, SurfaceState] = {}

    def apply(self, message: ServerMessage) -> SurfaceState | None:
        if isinstance(message, CreateSurface):
            surface = SurfaceState(message.surface_id, message.catalog_id)
            self.by_id[message.surface_id] = surface
            return surface
        if isinstance(message, UpdateComponents):
            surface = self.by_id.setdefault(
                message.surface_id, SurfaceState(message.surface_id, "")
            )
            for component in message.components:
                identifier = component.get("id")
                if isinstance(identifier, str):
                    surface.components[identifier] = component
            return surface
        if isinstance(message, UpdateDataModel):
            surface = self.by_id.get(message.surface_id)
            if surface is not None and message.path:
                surface.set(message.path, message.value)
            return surface
        self.by_id.pop(message.surface_id, None)
        return None


class SurfaceView(Vertical):
    """A rendered surface: the component tree from ``root`` as Textual widgets."""

    DEFAULT_CSS = """
    SurfaceView { height: auto; border: round $accent; padding: 0 1; margin: 0 0 1 0; }
    SurfaceView .a2ui-placeholder { color: $warning; }
    SurfaceView Button { margin: 0 1 0 0; }
    """

    def __init__(self, surface: SurfaceState, *, on_action: ActionSink) -> None:
        super().__init__(id=f"surface-{surface.surface_id}")
        self.surface = surface
        self._on_action = on_action
        self._paths: dict[str, str] = {}  # widget id -> data-model path (not Textual's bindings)

    def compose(self):  # type: ignore[no-untyped-def]
        names = sorted({str(c.get("component", "?")) for c in self.surface.components.values()})
        yield Static(f"A2UI · {', '.join(names)}", classes="a2ui-title")
        if "root" in self.surface.components:
            yield self.build("root")

    def build(self, component_id: str) -> Widget:
        component = self.surface.components.get(component_id)
        if component is None:
            return Static(f"[missing component: {component_id}]", classes="a2ui-placeholder")
        kind = str(component.get("component", ""))
        data = self.surface.data
        if kind in PLACEHOLDER_COMPONENTS:
            return Static(f"[unrenderable component: {kind}]", classes="a2ui-placeholder")
        if kind == "Text":
            return Static(_text(component.get("text"), data), classes="a2ui-text")
        if kind in ("Row",):
            return Horizontal(*self._children(component), classes="a2ui-row")
        if kind in ("Column", "Card", "List"):
            return Vertical(*self._children(component), classes=f"a2ui-{kind.lower()}")
        if kind == "Divider":
            return Rule()
        if kind == "Image":
            return Static(f"[image: {_text(component.get('url'), data)}]")
        if kind == "Icon":
            return Static(f"[icon: {_text(component.get('name'), data)}]")
        if kind == "Button":
            child = component.get("child")
            label = "Button"
            if isinstance(child, str):
                target = self.surface.components.get(child, {})
                label = _text(target.get("text", child), data)
            return Button(label, id=f"a2ui-{component_id}")
        if kind == "CheckBox":
            value = component.get("value")
            self._bind(component_id, value)
            checked = (
                bool(data.get(str(value.get("path", "")).lstrip("/")))
                if isinstance(value, dict)
                else bool(value)
            )
            return Checkbox(_text(component.get("label"), data), checked, id=f"a2ui-{component_id}")
        if kind == "TextField":
            self._bind(component_id, component.get("value"))
            return Input(
                value=_text(component.get("value"), data),
                placeholder=_text(component.get("placeholder") or component.get("label"), data),
                id=f"a2ui-{component_id}",
            )
        if kind in ("Slider", "DateTimeInput"):
            self._bind(component_id, component.get("value"))
            return Input(
                value=_text(component.get("value"), data),
                placeholder=kind,
                id=f"a2ui-{component_id}",
            )
        if kind == "ChoicePicker":
            return self._choice_picker(component_id, component)
        if kind == "Tabs":
            tabs = component.get("tabs")
            sections: list[Widget] = []
            if isinstance(tabs, list):
                for index, tab in enumerate(cast(list[JsonValue], tabs)):
                    if isinstance(tab, dict):
                        child = tab.get("child")
                        title = _text(tab.get("title"), data) or f"tab {index + 1}"
                        inner = self.build(child) if isinstance(child, str) else Static("")
                        sections.append(Collapsible(inner, title=title, collapsed=index > 0))
            return Vertical(*sections, classes="a2ui-tabs")
        if kind == "Modal":
            content = component.get("content")
            inner = self.build(content) if isinstance(content, str) else Static("")
            return Collapsible(inner, title="modal", collapsed=True)
        return Static(f"[unrenderable component: {kind}]", classes="a2ui-placeholder")

    def _children(self, component: JsonObject) -> list[Widget]:
        children = component.get("children")
        if isinstance(children, list):
            return [self.build(c) for c in cast(list[JsonValue], children) if isinstance(c, str)]
        child = component.get("child")
        return [self.build(child)] if isinstance(child, str) else []

    def _bind(self, component_id: str, value: JsonValue) -> None:
        if isinstance(value, dict) and isinstance(value.get("path"), str):
            self._paths[f"a2ui-{component_id}"] = str(value["path"])

    def _choice_picker(self, component_id: str, component: JsonObject) -> Widget:
        self._bind(component_id, component.get("value"))
        options = component.get("options")
        pairs: list[tuple[str, str]] = []
        if isinstance(options, list):
            for option in cast(list[JsonValue], options):
                if isinstance(option, dict):
                    pairs.append(
                        (
                            _text(option.get("label"), self.surface.data),
                            str(option.get("value", "")),
                        )
                    )
        label = _text(component.get("label"), self.surface.data)
        if component.get("variant") == "multipleSelection":
            selection = SelectionList[str](
                *[(lbl, val) for lbl, val in pairs], id=f"a2ui-{component_id}"
            )
            selection.border_title = label
            return selection
        radios = RadioSet(
            *[RadioButton(lbl, name=val) for lbl, val in pairs], id=f"a2ui-{component_id}"
        )
        radios.border_title = label
        return radios

    # --- widget events -> data model and actions ----------------------------------------

    def _path(self, widget_id: str | None) -> str | None:
        return self._paths.get(widget_id or "")

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        path = self._path(event.radio_set.id)
        if path is not None:
            self.surface.set(path, [event.pressed.name or ""])

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        path = self._path(event.checkbox.id)
        if path is not None:
            self.surface.set(path, event.value)

    def on_input_changed(self, event: Input.Changed) -> None:
        path = self._path(event.input.id)
        if path is not None:
            self.surface.set(path, event.value)

    def on_selection_list_selected_changed(self, event: SelectionList.SelectedChanged[str]) -> None:
        path = self._path(event.selection_list.id)
        if path is not None:
            self.surface.set(path, list(event.selection_list.selected))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        widget_id = event.button.id or ""
        component_id = widget_id.removeprefix("a2ui-")
        component = self.surface.components.get(component_id, {})
        action = component.get("action")
        if not isinstance(action, dict):
            return
        spec = action.get("event")
        if not isinstance(spec, dict):
            return
        context = spec.get("context")
        resolved = (
            self.surface.resolve_context(cast(JsonObject, context))
            if isinstance(context, dict)
            else {}
        )
        self._on_action(
            Action(
                name=str(spec.get("name", "")),
                surfaceId=self.surface.surface_id,
                sourceComponentId=component_id,
                timestamp=datetime.now(UTC).isoformat(),
                context=resolved,
            )
        )
        event.stop()


__all__ = ["PLACEHOLDER_COMPONENTS", "ActionSink", "SurfaceState", "SurfaceView", "Surfaces"]
