import type { JSX } from "react";
import type { Item } from "../model";
import { A2uiCard, type ActionPayload } from "./A2uiCard";

export function Stream(props: { items: Item[]; onAction: (action: ActionPayload) => void }): JSX.Element {
  return (
    <div className="stream" id="stream" role="log" aria-live="polite" aria-label="Event stream">
      {props.items.map((item) => {
        switch (item.kind) {
          case "text":
            return (
              <div key={item.key} className={`ev ${item.role}`}>
                <div className="who">{item.role === "user" ? "You" : "Agent · message"}</div>
                {item.text}
              </div>
            );
          case "status":
            return (
              <div key={item.key} className="ev agent">
                <div className="who">Agent · status</div>
                <div className="status">
                  <span className="dot" /> task → {item.state}
                </div>
              </div>
            );
          case "tool":
            return (
              <div key={item.key} className="ev agent">
                <div className="who">Agent · tool call</div>
                <div className="tool">{item.text}</div>
              </div>
            );
          case "help":
            return (
              <div key={item.key} className="ev agent help" data-testid="help">
                <div className="who">Agent · help requested</div>
                {item.text}
              </div>
            );
          case "a2ui":
            return <A2uiCard key={item.key} messages={item.messages} onAction={props.onAction} />;
          case "placeholder":
            return (
              <div key={item.key} className="ev agent placeholder" data-testid="placeholder">
                Unrenderable part: <code>{item.mediaType}</code> (kept, not dropped)
              </div>
            );
        }
      })}
    </div>
  );
}
