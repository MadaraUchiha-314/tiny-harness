/**
 * A link to another task of the same harness (R9.4): a real `?task=<id>` link, so it can
 * open in a new tab, that a plain click follows in place by attaching to the task.
 */
import type { JSX, MouseEvent, ReactNode } from "react";
import { cn } from "@/lib/utils";

/** This page's URL with `task` set; the server, participant and fixture parameters stay. */
export function taskHref(taskId: string, search: string = window.location.search): string {
  const params = new URLSearchParams(search);
  params.set("task", taskId);
  return `?${params.toString()}`;
}

export function TaskLink(props: {
  taskId: string;
  onOpen: (taskId: string) => void;
  children: ReactNode;
  className?: string;
  "data-testid"?: string;
}): JSX.Element {
  const click = (e: MouseEvent<HTMLAnchorElement>) => {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    props.onOpen(props.taskId);
  };
  return (
    <a
      href={taskHref(props.taskId)}
      onClick={click}
      data-testid={props["data-testid"]}
      className={cn(
        "rounded-sm text-primary underline underline-offset-2 hover:text-primary/80 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none",
        props.className,
      )}
    >
      {props.children}
    </a>
  );
}
