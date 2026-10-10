import { useState, type FormEvent } from "react";
import type { JSX } from "react";
import { SendHorizontalIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

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
    <form id="composer" onSubmit={submit} className="flex items-end gap-2 border-t bg-background px-4 py-3">
      <label htmlFor="reply" className="sr-only">
        Message
      </label>
      <Textarea
        id="reply"
        rows={2}
        placeholder="Message the task…"
        className="min-h-10 max-h-40 resize-none"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submit(e);
          }
        }}
      />
      <Button type="submit" disabled={props.disabled} aria-label="Send">
        <SendHorizontalIcon />
        Send
      </Button>
    </form>
  );
}
