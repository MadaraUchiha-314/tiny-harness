/**
 * The web renderer (R20.2, R20.3): an A2A client of the server through the official SDK
 * and nothing else, on shadcn's chat components. The conversation on the left, the task
 * pane on the right, the composer below. A `?fixture=prototype` query renders the
 * prototype's events without a server (visual tests); `?server=` names the harness and
 * `?task=` attaches to an existing task. After a stream ends in a non-terminal state the
 * renderer keeps a subscription open, so a reply from another surface shows up here.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { JSX } from "react";
import type React from "react";
import { PlugZapIcon, XIcon } from "lucide-react";
import { A2UI_MEDIA_TYPE, HarnessClient, dataPart, stateName, textPart, userMessage, type JsonObject, type StreamResponse } from "./a2a";
import { apply, emptyView, type View } from "./model";
import { prototypeEvents } from "./fixtures/prototype";
import { Composer } from "./components/Composer";
import { Stream } from "./components/Stream";
import { TaskPane } from "./components/TaskPane";
import type { ActionPayload } from "./components/A2uiCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export interface AppConfig {
  baseUrl: string;
  participant: string;
  agent: string;
  taskId?: string;
  fixture?: StreamResponse[];
}

const SERVER_KEY = "tiny-harness.server";
const TERMINAL = new Set(["COMPLETED", "FAILED", "CANCELED", "REJECTED"]);

function rememberedServer(): string | null {
  try {
    return window.localStorage.getItem(SERVER_KEY);
  } catch {
    return null;
  }
}

/**
 * The harness to talk to: the `?server=` query parameter, else the URL remembered in this
 * browser, else the page's own origin (the harness serving the renderer under `/ui`). A
 * renderer hosted elsewhere (GitHub Pages) needs the first or the second.
 */
export function configFromLocation(): AppConfig {
  const params = new URLSearchParams(window.location.search);
  const base = params.get("server") ?? rememberedServer() ?? window.location.origin;
  const config: AppConfig = {
    baseUrl: base.replace(/\/$/, ""),
    participant: params.get("participant") ?? "you",
    agent: params.get("agent") ?? "tiny-harness",
  };
  const task = params.get("task");
  if (task) config.taskId = task;
  if (params.get("fixture") === "prototype") config.fixture = prototypeEvents();
  return config;
}

const pillVariant = (state: string): "default" | "secondary" | "outline" => {
  if (state === "INPUT_REQUIRED" || state === "AUTH_REQUIRED") return "outline";
  if (TERMINAL.has(state)) return "default";
  return "secondary";
};

export function App(props: { config: AppConfig }): JSX.Element {
  const { config } = props;
  const [view, setView] = useState<View>(() => emptyView());
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);
  const folded = useRef(0); // server events folded for the current task (a replay skips them)
  const subscription = useRef<AbortController | null>(null);
  const client = useRef(new HarnessClient(config.baseUrl, config.participant));
  const contextId = useRef(crypto.randomUUID());

  const fold = useCallback((event: StreamResponse) => {
    const index = seq.current++;
    setView((current) => apply(current, event, index));
  }, []);

  const fail = useCallback((error: unknown) => {
    setView((current) => ({
      ...current,
      items: [
        ...current.items,
        { kind: "placeholder", mediaType: `error: ${String(error)}`, key: `err${seq.current++}` },
      ],
    }));
  }, []);

  const stopSubscription = useCallback(() => {
    subscription.current?.abort();
    subscription.current = null;
  }, []);

  const viewRef = useRef(view);
  useEffect(() => {
    viewRef.current = view;
  }, [view]);

  /**
   * Follow a task's event log: the replayed prefix is skipped, the rest folded live. A
   * subscription ends at every final event (INPUT_REQUIRED included, per the SDK), so
   * while the task is not finished it is opened again after a pause, which is how a
   * reply sent from another surface shows up here (R20.3).
   */
  const subscribe = useCallback(
    async (taskId: string) => {
      stopSubscription();
      const controller = new AbortController();
      subscription.current = controller;
      try {
        while (!controller.signal.aborted) {
          // A subscription starts with the task as it is now, then replays the log; the
          // events this page already folded are skipped, the snapshot with them.
          let skip = folded.current > 0 ? folded.current + 1 : 0;
          for await (const event of client.current.subscribe(taskId, controller.signal)) {
            if (controller.signal.aborted) break;
            if (skip > 0) {
              skip -= 1;
              continue;
            }
            folded.current += 1;
            fold(event);
          }
          if (controller.signal.aborted || TERMINAL.has(viewRef.current.state)) break;
          await new Promise((resolve) => setTimeout(resolve, 2000));
        }
      } catch (error) {
        if (!controller.signal.aborted) fail(error);
      } finally {
        if (subscription.current === controller) subscription.current = null;
      }
    },
    [fail, fold, stopSubscription],
  );

  useEffect(() => {
    if (config.fixture) config.fixture.forEach(fold);
    else if (config.taskId) void subscribe(config.taskId);
    return stopSubscription;
  }, [config.fixture, config.taskId, fold, stopSubscription, subscribe]);

  const consume = useCallback(
    async (events: AsyncGenerator<StreamResponse>) => {
      stopSubscription();
      setBusy(true);
      let taskId: string | null = null;
      let state = "";
      try {
        for await (const event of events) {
          folded.current += 1;
          fold(event);
          const payload = event.payload;
          if (payload?.$case === "task") {
            taskId = payload.value.id;
            state = stateName(payload.value.status?.state);
          } else if (payload?.$case === "statusUpdate") {
            taskId = payload.value.taskId;
            state = stateName(payload.value.status?.state);
          }
        }
      } catch (error) {
        fail(error);
      } finally {
        setBusy(false);
      }
      // Keep following the task while it is not finished: another surface may answer.
      if (taskId && !TERMINAL.has(state)) void subscribe(taskId);
    },
    [fail, fold, stopSubscription, subscribe],
  );

  const send = useCallback(
    (text: string) => {
      const options = {
        text,
        contextId: view.contextId ?? contextId.current,
        participant: config.participant,
        ...(view.taskId ? { taskId: view.taskId } : {}),
      };
      const message = userMessage(options);
      fold({ payload: { $case: "message", value: message } });
      if (config.fixture) return;
      void consume(client.current.sendMessage(message));
    },
    [config.fixture, config.participant, consume, fold, view.contextId, view.taskId],
  );

  const onAction = useCallback(
    (action: ActionPayload) => {
      const payload: JsonObject = {
        version: "v0.9.1",
        action: {
          name: action.name,
          surfaceId: action.surfaceId,
          sourceComponentId: action.sourceComponentId,
          timestamp: action.timestamp,
          context: action.context as JsonObject,
        },
      };
      const message = userMessage({
        parts: [dataPart(payload, A2UI_MEDIA_TYPE)],
        contextId: view.contextId ?? contextId.current,
        participant: config.participant,
        ...(view.taskId ? { taskId: view.taskId } : {}),
      });
      fold({
        payload: {
          $case: "message",
          value: { ...message, parts: [textPart(`${action.name} ${JSON.stringify(action.context)}`)] },
        },
      });
      if (config.fixture || !view.taskId) return;
      void consume(client.current.sendMessage(message));
    },
    [config.fixture, config.participant, consume, fold, view.contextId, view.taskId],
  );

  const cancel = useCallback(() => {
    if (!view.taskId || config.fixture) return;
    void client.current.cancel(view.taskId).then((task) => fold({ payload: { $case: "task", value: task } }));
  }, [config.fixture, fold, view.taskId]);

  const [server, setServer] = useState(config.baseUrl);
  const connect = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      const url = server.trim().replace(/\/$/, "");
      if (!url) return;
      try {
        window.localStorage.setItem(SERVER_KEY, url);
      } catch {
        // a private window or blocked storage: the query parameter still carries it
      }
      const params = new URLSearchParams(window.location.search);
      params.set("server", url);
      window.location.search = params.toString();
    },
    [server],
  );

  const shortId = view.taskId ? `${view.taskId.slice(0, 4)}…${view.taskId.slice(-4)}` : "no task";
  return (
    <div className="grid h-full grid-rows-[auto_1fr] bg-background text-foreground">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b px-4 py-2.5">
        <h1 className="text-base font-semibold tracking-tight">tiny-harness</h1>
        <span className="hidden font-mono text-xs text-muted-foreground sm:inline">
          {config.agent} · A2A 1.0
        </span>
        <form onSubmit={connect} className="flex min-w-0 items-center gap-1.5">
          <label htmlFor="harnessUrl" className="sr-only">
            Harness URL
          </label>
          <Input
            id="harnessUrl"
            type="url"
            value={server}
            onChange={(e) => setServer(e.target.value)}
            placeholder="https://harness.example.com"
            title="The harness this renderer talks to (its agent card is at /.well-known/agent-card.json)"
            className="h-8 w-64 font-mono text-xs"
          />
          <Button type="submit" variant="outline" size="sm" disabled={server.trim() === config.baseUrl}>
            <PlugZapIcon />
            Connect
          </Button>
        </form>
        <span className="flex-1" />
        <span className="font-mono text-xs text-muted-foreground">task {shortId}</span>
        <Badge
          variant={pillVariant(view.state)}
          id="taskState"
          data-testid="state"
          data-task={view.taskId ?? ""}
          className={cn("tracking-wide uppercase", view.state === "INPUT_REQUIRED" && "border-amber-500 text-amber-700 dark:text-amber-400")}
        >
          {view.state}
        </Badge>
        <Button type="button" variant="ghost" size="sm" onClick={cancel} disabled={!view.taskId}>
          <XIcon />
          Cancel task
        </Button>
      </header>
      <main className="grid min-h-0 grid-cols-1 md:grid-cols-[minmax(0,1fr)_minmax(280px,380px)]">
        <section className="flex min-h-0 min-w-0 flex-col" aria-label="Conversation">
          <Stream items={view.items} onAction={onAction} />
          <Composer onSend={send} disabled={busy} />
        </section>
        <TaskPane ext={view.ext} trace={view.trace} />
      </main>
    </div>
  );
}
