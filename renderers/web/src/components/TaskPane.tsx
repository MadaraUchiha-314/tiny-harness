import type { JSX } from "react";
import { CheckIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { TaskExtensionData } from "../generated/task";
import { cn } from "@/lib/utils";

function Heading(props: { children: string }): JSX.Element {
  return <h2 className="mb-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">{props.children}</h2>;
}

function Empty(props: { children: string }): JSX.Element {
  return <p className="font-mono text-xs text-muted-foreground">{props.children}</p>;
}

export function TaskPane(props: { ext: TaskExtensionData | null; trace: string[] }): JSX.Element {
  const { ext, trace } = props;
  return (
    <aside aria-label="Task" className="flex min-h-0 min-w-0 flex-col border-l bg-background">
      <Tabs defaultValue="task" className="flex min-h-0 flex-1 flex-col gap-0">
        <TabsList className="w-full justify-start rounded-none border-b bg-transparent px-2">
          <TabsTrigger value="task">
            Task
          </TabsTrigger>
          <TabsTrigger value="plan">
            Plan
          </TabsTrigger>
          <TabsTrigger value="trace">
            Trace
          </TabsTrigger>
        </TabsList>
        <TabsContent value="task" className="flex flex-col gap-4 overflow-y-auto px-4 py-4 text-sm">
          {ext === null ? (
            <Empty>No task yet.</Empty>
          ) : (
            <>
              <div>
                <Heading>Goal</Heading>
                <p>{ext.goal}</p>
              </div>
              {ext.acceptance_criteria && ext.acceptance_criteria.length > 0 && (
                <div>
                  <Heading>Acceptance criteria</Heading>
                  <ul className="flex flex-col gap-1">
                    {ext.acceptance_criteria.map((c) => (
                      <li key={c.text} className={cn("flex items-start gap-2", c.met && "text-muted-foreground")}>
                        <span
                          aria-hidden
                          className={cn(
                            "mt-0.5 grid size-4 shrink-0 place-items-center rounded-sm border",
                            c.met && "border-primary bg-primary text-primary-foreground",
                          )}
                        >
                          {c.met ? <CheckIcon className="size-3" /> : null}
                        </span>
                        <span>{c.text}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <div>
                <Heading>Participants</Heading>
                <ul className="flex flex-col gap-1.5">
                  {(ext.participants ?? []).map((p) => (
                    <li key={p.id} className="flex items-center gap-2">
                      <span>
                        {p.id}
                        {p.kind === "agent" ? " (A2A)" : ""}
                      </span>
                      <Badge variant="outline">{p.role}</Badge>
                    </li>
                  ))}
                </ul>
              </div>
              {ext.sub_tasks && ext.sub_tasks.length > 0 && (
                <div>
                  <Heading>Sub-tasks</Heading>
                  <p className="font-mono text-xs">
                    {ext.sub_tasks.map((t) => (t.agent ? `${t.agent.id}/` : "") + t.task_id).join(" · ")}
                  </p>
                </div>
              )}
            </>
          )}
        </TabsContent>
        <TabsContent value="plan" className="flex flex-col gap-4 overflow-y-auto px-4 py-4 text-sm">
          {ext?.plan ? (
            <div>
              <Heading>{`Plan · ${ext.plan.steps.length} steps · DAG`}</Heading>
              <ol className="flex flex-col gap-2">
                {ext.plan.steps.map((step, index) => {
                  const state = step.state ?? "pending";
                  return (
                    <li key={step.id} className="grid grid-cols-[1.5rem_1fr] items-start gap-2">
                      <span
                        className={cn(
                          "grid size-5 place-items-center rounded-full border-2 text-[0.65rem] font-medium",
                          state === "done" && "border-primary bg-primary text-primary-foreground",
                          state === "active" && "border-primary",
                          state === "failed" && "border-destructive text-destructive",
                        )}
                      >
                        {index + 1}
                      </span>
                      <div>
                        {step.name}
                        <div className="text-xs text-muted-foreground">
                          {step.output
                            ? `output: ${step.output}`
                            : step.depends_on && step.depends_on.length > 0
                              ? `depends on ${step.depends_on.join(", ")}`
                              : ""}
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ol>
            </div>
          ) : (
            <Empty>No plan yet.</Empty>
          )}
        </TabsContent>
        <TabsContent value="trace" className="flex flex-col gap-1 overflow-y-auto px-4 py-4">
          <Heading>Trace</Heading>
          {trace.length === 0 ? (
            <Empty>No events yet.</Empty>
          ) : (
            trace.map((line, i) => (
              <p key={i} className="font-mono text-xs text-muted-foreground">
                {line}
              </p>
            ))
          )}
        </TabsContent>
      </Tabs>
    </aside>
  );
}
