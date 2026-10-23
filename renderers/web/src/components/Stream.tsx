/**
 * The conversation on shadcn's chat components: `MessageScroller` keeps the newest turn in
 * view, each item is a `Message` with a `Bubble` (the user on the end side, the agent on
 * the start side), status changes and tool calls are `Marker`s, and an A2UI card is the
 * official renderer inside an outline bubble. A command's reply is a quiet, ruled line
 * under the command's name; a `/sub-task` reply links the new task (R9.4). Issue-38: an
 * image or audio file is a turn of its own (`MediaItem`), and a spoken reply's line sits
 * under the reply it speaks.
 */
import type { JSX, ReactNode } from "react";
import { BotIcon, CircleAlertIcon, CircleHelpIcon, TriangleAlertIcon, WrenchIcon } from "lucide-react";
import { Bubble, BubbleContent } from "@/components/ui/bubble";
import { Marker, MarkerContent, MarkerIcon } from "@/components/ui/marker";
import { Message, MessageContent, MessageHeader } from "@/components/ui/message";
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from "@/components/ui/message-scroller";
import { Spinner } from "@/components/ui/spinner";
import type { Item, SpeechItemData } from "../model";
import { MediaItem, type MediaLoad } from "./MediaItem";
import { A2uiCard, type ActionPayload } from "./A2uiCard";
import { TaskLink } from "./TaskLink";

const LIVE = new Set(["SUBMITTED", "WORKING"]);

interface RowProps {
  item: Item;
  onAction: (action: ActionPayload) => void;
  onOpen: (taskId: string) => void;
  load?: MediaLoad | undefined;
  speech?: ((item: SpeechItemData) => ReactNode) | undefined;
}

const noMedia: MediaLoad = () => Promise.reject(new Error("media is not available here"));

function Row(props: RowProps): JSX.Element {
  const { item } = props;
  switch (item.kind) {
    case "text":
      return item.role === "user" ? (
        <Message align="end">
          <MessageContent>
            <Bubble>
              <BubbleContent>{item.text}</BubbleContent>
            </Bubble>
          </MessageContent>
        </Message>
      ) : (
        <Message>
          <MessageContent>
            <MessageHeader>
              <BotIcon className="size-3.5" /> Agent
            </MessageHeader>
            <Bubble variant="secondary">
              <BubbleContent>{item.text}</BubbleContent>
            </Bubble>
          </MessageContent>
        </Message>
      );
    case "status":
      return (
        <Marker role="status" variant="separator" data-testid="status">
          <MarkerIcon>{LIVE.has(item.state) ? <Spinner /> : null}</MarkerIcon>
          <MarkerContent>
            task → {item.state}
            {item.subState ? ` · ${item.subState.replace(/-/g, " ")}` : ""}
          </MarkerContent>
        </Marker>
      );
    case "command":
      return (
        <div
          data-testid="command"
          className="max-w-[72ch] border-l-[3px] border-primary py-1 pl-3 font-mono text-sm whitespace-pre-wrap text-muted-foreground"
        >
          <div className="mb-0.5 font-sans text-xs tracking-wide uppercase">/{item.name}</div>
          {item.text}
          {item.taskRef ? (
            <div className="mt-1 font-sans">
              <TaskLink taskId={item.taskRef} onOpen={props.onOpen}>
                Open sub-task
              </TaskLink>
            </div>
          ) : null}
        </div>
      );
    case "error":
      return (
        <Marker variant="border" data-testid="error" className="text-destructive">
          <MarkerIcon>
            <CircleAlertIcon />
          </MarkerIcon>
          <MarkerContent>{item.text}</MarkerContent>
        </Marker>
      );
    case "tool":
      return (
        <Marker>
          <MarkerIcon>
            <WrenchIcon />
          </MarkerIcon>
          <MarkerContent className="font-mono text-xs">{item.text}</MarkerContent>
        </Marker>
      );
    case "help":
      return (
        <Message>
          <MessageContent>
            <MessageHeader className="text-amber-700 dark:text-amber-400">
              <CircleHelpIcon className="size-3.5" /> Agent · help requested
            </MessageHeader>
            <Bubble variant="tinted" data-testid="help">
              <BubbleContent>{item.text}</BubbleContent>
            </Bubble>
          </MessageContent>
        </Message>
      );
    case "a2ui":
      return (
        <Message>
          <MessageContent>
            <A2uiCard messages={item.messages} onAction={props.onAction} />
          </MessageContent>
        </Message>
      );
    case "media":
      return item.role === "user" ? (
        <Message align="end">
          <MessageContent>
            <Bubble variant="secondary" data-testid="media">
              <BubbleContent>
                <MediaItem item={item} load={props.load ?? noMedia} />
              </BubbleContent>
            </Bubble>
          </MessageContent>
        </Message>
      ) : (
        <Message>
          <MessageContent>
            <MessageHeader>
              <BotIcon className="size-3.5" /> Agent · {item.media}
            </MessageHeader>
            <Bubble variant="outline" data-testid="media">
              <BubbleContent>
                <MediaItem item={item} load={props.load ?? noMedia} />
              </BubbleContent>
            </Bubble>
          </MessageContent>
        </Message>
      );
    case "speech":
      return <div data-testid="speech">{props.speech ? props.speech(item) : null}</div>;
    case "placeholder":
      return (
        <Marker variant="border" data-testid="placeholder">
          <MarkerIcon>
            <TriangleAlertIcon />
          </MarkerIcon>
          <MarkerContent>
            Unrenderable part: <code className="font-mono text-xs">{item.mediaType}</code> (kept, not dropped)
          </MarkerContent>
        </Marker>
      );
  }
}

export function Stream(props: {
  items: Item[];
  onAction: (action: ActionPayload) => void;
  onOpen: (taskId: string) => void;
  load?: MediaLoad;
  speech?: (item: SpeechItemData) => ReactNode;
}): JSX.Element {
  return (
    <MessageScrollerProvider autoScroll defaultScrollPosition="end">
      <MessageScroller className="min-h-0 flex-1">
        <MessageScrollerViewport>
          <MessageScrollerContent
            id="stream"
            role="log"
            aria-live="polite"
            aria-label="Event stream"
            className="mx-auto flex w-full max-w-3xl flex-col gap-3 px-4 py-4"
          >
            {props.items.map((item) => (
              <MessageScrollerItem
                key={item.key}
                messageId={item.key}
                scrollAnchor={(item.kind === "text" || item.kind === "media") && item.role === "user"}
              >
                <Row item={item} onAction={props.onAction} onOpen={props.onOpen} load={props.load} speech={props.speech} />
              </MessageScrollerItem>
            ))}
          </MessageScrollerContent>
        </MessageScrollerViewport>
        <MessageScrollerButton />
      </MessageScroller>
    </MessageScrollerProvider>
  );
}
