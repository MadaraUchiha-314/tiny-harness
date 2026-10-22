/**
 * The composer. Text that starts with `/` (and has no argument yet) opens a listbox of the
 * matching commands, following the WAI-ARIA combobox pattern (R6.7): Up and Down move the
 * selection, Tab or Enter accepts it, Escape closes the list. The harness resolves the
 * command, so whatever is sent is the text as typed (R6.4) — except a surface command this
 * renderer implements: `/attach` opens the file picker and sends nothing (issue-38 R1.2).
 *
 * Issue-38: files come from the paperclip's picker, a drop on the form or a pasted image,
 * are checked against the card (type, size) and wait as chips until sent with the text
 * (`onSend(text, files)`). When the send is refused the chips and the text come back.
 */
import { useEffect, useRef, useState, type ClipboardEvent, type DragEvent, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import type { JSX } from "react";
import { AudioLinesIcon, PaperclipIcon, SendHorizontalIcon, XIcon } from "lucide-react";
import type { CommandSpec } from "../a2a";
import { ACCEPTED, baseType, checkFile, clock, humanSize, mediaKind, type MediaKind, type MediaParams } from "../media";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

/** A file waiting to be sent. */
export interface Attachment {
  id: string;
  blob: Blob;
  name: string;
  mediaType: string;
  size: number;
  kind: MediaKind;
  durationMs?: number;
  voice?: boolean;
}

/** The result of a send: false when the harness refused it (the chips come back). */
export type SendResult = void | Promise<boolean>;

const ATTACH = "attach";
let attachmentSeq = 0;

export function attachmentOf(blob: Blob, name: string, extra?: { durationMs?: number; voice?: boolean }): Attachment | null {
  const kind = mediaKind(blob.type);
  if (kind === null) return null;
  attachmentSeq += 1;
  return { id: `att-${attachmentSeq}`, blob, name, mediaType: baseType(blob.type), size: blob.size, kind, ...extra };
}

function Thumbnail(props: { blob: Blob }): JSX.Element {
  const [src, setSrc] = useState<string | null>(null);
  const [broken, setBroken] = useState(false);
  useEffect(() => {
    if (typeof URL.createObjectURL !== "function") return;
    const url = URL.createObjectURL(props.blob);
    setSrc(url);
    return () => URL.revokeObjectURL(url);
  }, [props.blob]);
  return src === null || broken ? (
    <span className="h-6 w-8 rounded bg-muted" aria-hidden="true" />
  ) : (
    <img src={src} alt="" onError={() => setBroken(true)} className="h-6 w-8 rounded object-cover" />
  );
}

function chipText(a: Attachment): string {
  const label = a.voice ? "voice" : a.name;
  return a.durationMs !== undefined ? `${label} · ${clock(a.durationMs)}` : `${label} · ${humanSize(a.size)}`;
}

export function Composer(props: {
  onSend: (text: string, files: Attachment[]) => SendResult;
  disabled: boolean;
  commands?: CommandSpec[];
  /** The card's media extension; without it there is no paperclip. */
  media?: MediaParams | null;
  /** A file refused before it was attached (the card's type or size). */
  onError?: (text: string) => void;
  /** Controls beside Send: the speaker toggle and the mic (issue-38 R3, R4). */
  voice?: ReactNode;
  /** Above the row: the recording bar while the mic records. */
  status?: ReactNode;
}): JSX.Element {
  const [text, setText] = useState("");
  const [selected, setSelected] = useState(0);
  const [dismissed, setDismissed] = useState(false);
  const [files, setFiles] = useState<Attachment[]>([]);
  const [dropping, setDropping] = useState(false);
  const box = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const media = props.media ?? null;
  const canAttach = media !== null && media.input.some((t) => ACCEPTED.has(baseType(t)));
  const attachCommand = (props.commands ?? []).some((c) => c.name === ATTACH && c.runsOn === "surface");

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

  const add = (list: ArrayLike<File> | null | undefined) => {
    if (!list || media === null) return;
    const added: Attachment[] = [];
    for (const file of Array.from(list)) {
      const refused = checkFile(file, media);
      const attachment = refused === null ? attachmentOf(file, file.name) : null;
      if (attachment === null) {
        props.onError?.(`Not attached: ${refused ?? `${file.name} is not a file this agent accepts`}.`);
        continue;
      }
      added.push(attachment);
    }
    if (added.length > 0) setFiles((current) => [...current, ...added]);
  };
  const openPicker = () => picker.current?.click();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = text.trim();
    if (canAttach && attachCommand && /^\/attach(\s|$)/.test(trimmed)) {
      change("");
      openPicker();
      return;
    }
    if (!trimmed && files.length === 0) return;
    const sent = files;
    const result = props.onSend(trimmed, sent);
    change("");
    setFiles([]);
    if (result instanceof Promise) {
      void result.then((ok) => {
        if (ok) return;
        setFiles((current) => [...sent, ...current]);
        setText((current) => current || trimmed);
      });
    }
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

  const hasFiles = (e: DragEvent<HTMLFormElement>) => Array.from(e.dataTransfer?.types ?? []).includes("Files");
  const dragOver = (e: DragEvent<HTMLFormElement>) => {
    if (!canAttach || !hasFiles(e)) return;
    e.preventDefault();
    setDropping(true);
  };
  const drop = (e: DragEvent<HTMLFormElement>) => {
    setDropping(false);
    if (!canAttach || !hasFiles(e)) return;
    e.preventDefault();
    add(e.dataTransfer.files);
  };
  const paste = (e: ClipboardEvent<HTMLTextAreaElement>) => {
    if (!canAttach) return;
    const images = Array.from(e.clipboardData?.files ?? []).filter((f) => mediaKind(f.type) === "image");
    if (images.length === 0) return;
    e.preventDefault();
    add(images);
  };

  return (
    <form
      id="composer"
      onSubmit={submit}
      onDragOver={dragOver}
      onDragLeave={() => setDropping(false)}
      onDrop={drop}
      autoComplete="off"
      {...(dropping ? { "data-drop": "true" } : {})}
      className={cn(
        "relative flex flex-col gap-2 border-t bg-background px-4 py-3",
        dropping && "outline-2 -outline-offset-[6px] outline-primary outline-dashed",
      )}
    >
      {files.length > 0 ? (
        <ul aria-label="Attachments" className="m-0 flex list-none flex-wrap gap-1.5 p-0">
          {files.map((a) => (
            <li
              key={a.id}
              className="inline-flex max-w-full items-center gap-2 rounded-lg border bg-muted/40 py-0.5 pr-0.5 pl-1 text-sm"
            >
              {a.kind === "image" ? <Thumbnail blob={a.blob} /> : <AudioLinesIcon className="size-4 text-muted-foreground" aria-hidden="true" />}
              <span className="min-w-0 truncate">{chipText(a)}</span>
              <Button
                type="button"
                variant="ghost"
                size="icon-xs"
                aria-label={`Remove ${a.name}`}
                onClick={() => setFiles((current) => current.filter((f) => f.id !== a.id))}
              >
                <XIcon />
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
      {props.status}
      <div className="flex items-end gap-2">
        {canAttach && media !== null ? (
          <>
            <Button type="button" variant="outline" size="icon" aria-label="Attach image or audio" title="Attach image or audio (or drop, or paste)" onClick={openPicker}>
              <PaperclipIcon />
            </Button>
            <input
              ref={picker}
              type="file"
              multiple
              accept={media.input.join(",")}
              tabIndex={-1}
              aria-hidden="true"
              className="sr-only"
              onChange={(e) => {
                add(e.target.files);
                e.target.value = "";
              }}
            />
          </>
        ) : null}
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
          placeholder={canAttach ? "Message, / for commands, or drop a file" : "Message, or / for commands"}
          className="min-h-10 max-h-40 min-w-0 flex-1 resize-none"
          value={text}
          onChange={(e) => change(e.target.value)}
          onKeyDown={keyDown}
          onPaste={paste}
        />
        {props.voice}
        <Button type="submit" disabled={props.disabled} aria-label="Send">
          <SendHorizontalIcon />
          Send
        </Button>
      </div>
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
    </form>
  );
}
