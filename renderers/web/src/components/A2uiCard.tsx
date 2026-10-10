/**
 * A2UI on the official renderer (R20.5, R20.6): `MessageProcessor` from web_core fed with
 * the `application/a2ui+json` parts, `A2uiSurface` from @a2ui/react drawing the bundled
 * basic catalog; a component's action comes back through the processor's action handler
 * and is sent as an A2A message carrying the A2UI part. Nothing is hand-written.
 */
import { useEffect, useMemo, useState } from "react";
import type { JSX } from "react";
import { MessageProcessor } from "@a2ui/web_core/v0_9";
import { basicCatalog } from "@a2ui/web_core/v0_9/basic_catalog";
import { A2uiSurface, type ReactCatalogComponent } from "@a2ui/react/v0_9";
import type { ActionPayload, Catalog } from "@a2ui/web_core/v0_9";
import type { JsonObject } from "../a2a";
import { Badge } from "@/components/ui/badge";
import { Bubble, BubbleContent } from "@/components/ui/bubble";

// The basic catalog is implemented as custom elements, which the React surface hosts;
// its schema-only static type does not say so, hence the one cast.
const catalog = basicCatalog as unknown as Catalog<ReactCatalogComponent>;

export type { ActionPayload };

export function A2uiCard(props: {
  messages: JsonObject[];
  onAction: (action: ActionPayload) => void;
}): JSX.Element {
  const { messages, onAction } = props;
  const processor = useMemo(
    () => new MessageProcessor<ReactCatalogComponent>([catalog], (action) => onAction(action)),
    // one processor per card; the handler is stable for the card's lifetime
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  const [surfaces, setSurfaces] = useState(() => Array.from(processor.model.surfacesMap.values()));
  useEffect(() => {
    processor.processMessages(messages as never);
    const sync = () => setSurfaces(Array.from(processor.model.surfacesMap.values()));
    sync();
    const created = processor.onSurfaceCreated(sync);
    const deleted = processor.onSurfaceDeleted(sync);
    return () => {
      created.unsubscribe();
      deleted.unsubscribe();
    };
  }, [processor, messages]);
  const names = new Set<string>();
  for (const message of messages) {
    const update = message["updateComponents"];
    if (update && typeof update === "object" && !Array.isArray(update)) {
      const components = update["components"];
      if (Array.isArray(components)) {
        for (const component of components) {
          if (component && typeof component === "object" && !Array.isArray(component)) {
            const name = component["component"];
            if (typeof name === "string") names.add(name);
          }
        }
      }
    }
  }
  return (
    <Bubble variant="outline" className="w-full max-w-full" data-testid="a2ui">
      <BubbleContent className="w-full max-w-full">
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          <Badge variant="secondary">A2UI</Badge>
          <span className="font-mono text-[0.7rem] text-muted-foreground">basic catalog · {Array.from(names).join(", ")}</span>
        </div>
        {surfaces.length === 0 && <div className="text-sm text-muted-foreground">A2UI surface pending</div>}
        {surfaces.map((surface) => (
          <A2uiSurface key={surface.id} surface={surface} />
        ))}
      </BubbleContent>
    </Bubble>
  );
}
