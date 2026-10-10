/**
 * The conversation on shadcn's chat components: `MessageScroller` keeps the newest turn in
 * view, each item is a `Message` with a `Bubble` (the user on the end side, the agent on
 * the start side), status changes and tool calls are `Marker`s, and an A2UI card is the
 * official renderer inside an outline bubble.
 */
import type { JSX } from "react";
import { BotIcon, CircleHelpIcon, TriangleAlertIcon, WrenchIcon } from "lucide-react";
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
import type { Item } from "../model";
import { A2uiCard, type ActionPayload } from "./A2uiCard";

const LIVE = new Set(["SUBMITTED", "WORKING"]);

function Row(props: { item: Item; onAction: (action: ActionPayload) => void }): JSX.Element {
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
          <MarkerContent>task → {item.state}</MarkerContent>
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

export function Stream(props: { items: Item[]; onAction: (action: ActionPayload) => void }): JSX.Element {
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
                scrollAnchor={item.kind === "text" && item.role === "user"}
              >
                <Row item={item} onAction={props.onAction} />
              </MessageScrollerItem>
            ))}
          </MessageScrollerContent>
        </MessageScrollerViewport>
        <MessageScrollerButton />
      </MessageScroller>
    </MessageScrollerProvider>
  );
}
