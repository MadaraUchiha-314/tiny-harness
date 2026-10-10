import { useState, type FormEvent } from "react";
import type { JSX } from "react";

export function Composer(props: { onSend: (text: string) => void; disabled: boolean }): JSX.Element {
  const [text, setText] = useState("");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = text.trim();
    if (!trimmed) return;
    props.onSend(trimmed);
    setText("");
  };
  return (
    <form className="composer" id="composer" onSubmit={submit}>
      <label htmlFor="reply" className="visually-hidden">
        Message
      </label>
      <textarea
        id="reply"
        rows={2}
        placeholder="Message the task…"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submit(e);
          }
        }}
      />
      <button className="btn" type="submit" disabled={props.disabled}>
        Send
      </button>
    </form>
  );
}
