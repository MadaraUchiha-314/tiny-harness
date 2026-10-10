import { useState } from "react";
import type { JSX } from "react";
import type { TaskExtensionData } from "../generated/task";

type Tab = "task" | "plan" | "trace";
const TABS: Tab[] = ["task", "plan", "trace"];
const MARK: Record<string, string> = { done: "done", active: "active", pending: "", failed: "failed" };

export function TaskPane(props: { ext: TaskExtensionData | null; trace: string[] }): JSX.Element {
  const [tab, setTab] = useState<Tab>("task");
  const { ext, trace } = props;
  return (
    <aside aria-label="Task">
      <div className="tabs" role="tablist">
        {TABS.map((name) => (
          <button
            key={name}
            role="tab"
            id={`tab-${name}`}
            aria-selected={tab === name}
            aria-controls={`panel-${name}`}
            onClick={() => setTab(name)}
          >
            {name[0]?.toUpperCase() + name.slice(1)}
          </button>
        ))}
      </div>
      <div className="panel" id="panel-task" role="tabpanel" aria-labelledby="tab-task" hidden={tab !== "task"}>
        {ext === null ? (
          <p className="mono">No task yet.</p>
        ) : (
          <>
            <div>
              <h2>Goal</h2>
              <p>{ext.goal}</p>
            </div>
            {ext.acceptance_criteria && ext.acceptance_criteria.length > 0 && (
              <div>
                <h2>Acceptance criteria</h2>
                <ul className="ac">
                  {ext.acceptance_criteria.map((c) => (
                    <li key={c.text} className={c.met ? "met" : ""}>
                      {c.text}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <div>
              <h2>Participants</h2>
              <div className="people">
                {(ext.participants ?? []).map((p) => (
                  <span key={p.id}>
                    {p.id}
                    {p.kind === "agent" ? " (A2A)" : ""} <span className="role">{p.role}</span>
                  </span>
                ))}
              </div>
            </div>
            {ext.sub_tasks && ext.sub_tasks.length > 0 && (
              <div>
                <h2>Sub-tasks</h2>
                <p className="mono">
                  {ext.sub_tasks.map((t) => (t.agent ? `${t.agent.id}/` : "") + t.task_id).join(" · ")}
                </p>
              </div>
            )}
          </>
        )}
      </div>
      <div className="panel" id="panel-plan" role="tabpanel" aria-labelledby="tab-plan" hidden={tab !== "plan"}>
        {ext?.plan ? (
          <div>
            <h2>Plan · {ext.plan.steps.length} steps · DAG</h2>
            <ol className="steps">
              {ext.plan.steps.map((step, index) => (
                <li key={step.id} className={`step ${MARK[step.state ?? "pending"] ?? ""}`}>
                  <span className="n">{index + 1}</span>
                  <div>
                    {step.name}
                    <div className="meta">
                      {step.output
                        ? `output: ${step.output}`
                        : step.depends_on && step.depends_on.length > 0
                          ? `depends on ${step.depends_on.join(", ")}`
                          : ""}
                    </div>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        ) : (
          <p className="mono">No plan yet.</p>
        )}
      </div>
      <div className="panel" id="panel-trace" role="tabpanel" aria-labelledby="tab-trace" hidden={tab !== "trace"}>
        <div>
          <h2>Trace</h2>
          {trace.length === 0 ? <p className="mono">No events yet.</p> : trace.map((line, i) => <p key={i} className="mono">{line}</p>)}
        </div>
      </div>
    </aside>
  );
}
