/**
 * The composer. Text that starts with `/` (and has no argument yet) opens a listbox of the
 * matching commands, following the WAI-ARIA combobox pattern (R6.7): Up and Down move the
 * selection, Tab or Enter accepts it, Escape closes the list. The harness resolves the
 * command, so whatever is sent is the text as typed (R6.4).
 */
import { useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import type { JSX } from "react";
import { SendHorizontalIcon } from "lucide-react";
import type { CommandSpec } from "../a2a";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

export function Composer(props: {
  onSend: (text: string) => void;
  disabled: boolean;
  commands?: CommandSpec[];
}): JSX.Element {
  const [text, setText] = useState("");
  const [selected, setSelected] = useState(0);
  const [dismissed, setDismissed] = useState(false);
  const box = useRef<HTMLTextAreaElement>(null);

  const query = /^\/(\S*)$/.exec(text)?.[1];
  const matches =
    query === undefined || dismissed ? [] : (props.commands ?? []).filter((c) => c.name.startsWith(query));
  const expanded = matches.length > 0;
  const active = expanded ? matches[Math.min(selected, matches.length - 1)] : undefined;

  const change = (value: string) => {
    setText(value);
    setSelected(0);
    setDismissed(false);
  };
  const accept = (command: CommandSpec) => {
    change(`/${command.name} `);
    box.current?.focus();
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = text.trim();
    if (!trimmed) return;
    props.onSend(trimmed);
    change("");
  };
  const keyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (expanded && active) {
      const index = matches.indexOf(active);
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const step = e.key === "ArrowDown" ? 1 : -1;
        setSelected((index + step + matches.length) % matches.length);
        return;
      }
      if (e.key === "Tab" || e.key === "Enter") {
        e.preventDefault();
        accept(active);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setDismissed(true);
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit(e);
    }
  };

  return (
    <form id="composer" onSubmit={submit} autoComplete="off" className="relative flex items-end gap-2 border-t bg-background px-4 py-3">
      <label htmlFor="reply" className="sr-only">
        Message or /command
      </label>
      <Textarea
        ref={box}
        id="reply"
        rows={2}
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={expanded}
        aria-controls="cmds"
        {...(active ? { "aria-activedescendant": `cmd-${active.name}` } : {})}
        placeholder="Message, or / for commands"
        className="min-h-10 max-h-40 resize-none"
        value={text}
        onChange={(e) => change(e.target.value)}
        onKeyDown={keyDown}
      />
      <ul
        id="cmds"
        role="listbox"
        aria-label="Commands"
        hidden={!expanded}
        className="absolute inset-x-4 bottom-[calc(100%-0.25rem)] z-10 m-0 flex list-none flex-col gap-0.5 rounded-lg border bg-popover p-1 text-popover-foreground shadow-lg"
      >
        {matches.map((command) => {
          // Muted text loses AA contrast on the selection's background; it keeps the ink there.
          const quiet = command === active ? undefined : "text-muted-foreground";
          return (
            <li
              key={command.name}
              id={`cmd-${command.name}`}
              role="option"
              aria-selected={command === active}
              onMouseDown={(e) => {
                e.preventDefault();
                accept(command);
              }}
              className={cn(
                "grid cursor-pointer grid-cols-1 gap-x-3 rounded-md px-2 py-1.5 text-sm sm:grid-cols-[minmax(10rem,auto)_1fr]",
                command === active && "bg-accent text-accent-foreground",
              )}
            >
              <span className="font-mono">
                {`/${command.name}`}
                {command.argument_hint ? <span className={quiet}>{` ${command.argument_hint}`}</span> : null}
              </span>
              <span className={quiet}>{command.description}</span>
            </li>
          );
        })}
      </ul>
      <Button type="submit" disabled={props.disabled} aria-label="Send">
        <SendHorizontalIcon />
        Send
      </Button>
    </form>
  );
}
