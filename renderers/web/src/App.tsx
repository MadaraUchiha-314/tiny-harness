/**
 * The web renderer (R20.2, R20.3): an A2A client of the server and nothing else. The
 * event stream on the left, the task pane on the right, the composer below. A `?fixture=
 * prototype` query renders the prototype's events without a server (visual tests).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { JSX } from "react";
import type React from "react";
import { A2UI_MEDIA_TYPE, HarnessClient, dataPart, textPart, userMessage, type JsonObject, type StreamResponse } from "./a2a";
import { apply, emptyView, type View } from "./model";
import { prototypeEvents } from "./fixtures/prototype";
import { Composer } from "./components/Composer";
import { Stream } from "./components/Stream";
import { TaskPane } from "./components/TaskPane";
import type { ActionPayload } from "./components/A2uiCard";

export interface AppConfig {
  baseUrl: string;
  participant: string;
  agent: string;
  fixture?: StreamResponse[];
}

const SERVER_KEY = "tiny-harness.server";

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
  if (params.get("fixture") === "prototype") config.fixture = prototypeEvents();
  return config;
}

const pillClass = (state: string): string => {
  if (state === "INPUT_REQUIRED" || state === "AUTH_REQUIRED") return "pill state-input";
  if (["COMPLETED", "FAILED", "CANCELED", "REJECTED"].includes(state)) return "pill state-done";
  return "pill state-working";
};

export function App(props: { config: AppConfig }): JSX.Element {
  const { config } = props;
  const [view, setView] = useState<View>(() => emptyView());
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);
  const client = useRef(new HarnessClient(config.baseUrl, config.participant));
  const contextId = useRef(crypto.randomUUID());

  const fold = useCallback((event: StreamResponse) => {
    const index = seq.current++;
    setView((current) => apply(current, event, index));
  }, []);

  useEffect(() => {
    if (config.fixture) config.fixture.forEach(fold);
  }, [config.fixture, fold]);

  const consume = useCallback(
    async (events: AsyncGenerator<StreamResponse>) => {
      setBusy(true);
      try {
        for await (const event of events) fold(event);
      } catch (error) {
        setView((current) => ({
          ...current,
          items: [
            ...current.items,
            { kind: "placeholder", mediaType: `error: ${String(error)}`, key: `err${seq.current++}` },
          ],
        }));
      } finally {
        setBusy(false);
      }
    },
    [fold],
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
    <div className="app">
      <header>
        <h1>tiny-harness</h1>
        <span className="mono">agent card · {config.agent} · A2A 1.0 ·</span>
        <form className="harness" onSubmit={connect}>
          <label htmlFor="harnessUrl" className="visually-hidden">
            Harness URL
          </label>
          <input
            id="harnessUrl"
            className="mono"
            type="url"
            value={server}
            onChange={(e) => setServer(e.target.value)}
            placeholder="https://harness.example.com"
            title="The harness this renderer talks to (its agent card is at /.well-known/agent-card.json)"
          />
          <button className="choice" type="submit" disabled={server.trim() === config.baseUrl}>
            Connect
          </button>
        </form>
        <span className="spacer" />
        <span className="mono">task {shortId}</span>
        <span className={pillClass(view.state)} id="taskState" data-testid="state">
          {view.state}
        </span>
        <button className="choice" type="button" onClick={cancel} disabled={!view.taskId}>
          Cancel task
        </button>
      </header>
      <main>
        <section className="conv" aria-label="Conversation">
          <Stream items={view.items} onAction={onAction} />
          <Composer onSend={send} disabled={busy} />
        </section>
        <TaskPane ext={view.ext} trace={view.trace} />
      </main>
    </div>
  );
}
