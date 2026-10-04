/** Thin Pi 0.99.2+ extension. Pi owns conversation, context and agent lifecycle. */
import { Type } from "typebox";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const evidenceCheck = Type.Object({kind:Type.Union([Type.Literal("diff"),Type.Literal("tests"),Type.Literal("remote_sha")]),status:Type.Union([Type.Literal("observed"),Type.Literal("unknown")]),sources:Type.Array(Type.String()),remoteSha:Type.Optional(Type.String()),notes:Type.Optional(Type.String())});
export default function (pi: ExtensionAPI) {
  const host = process.env.AWF_HOST_URL;
  const token = process.env.AWF_EXTENSION_TOKEN;
  const task = process.env.AWF_TASK_ID;
  const role = process.env.AWF_ROLE;
  const lifecycleRevision = Number(process.env.AWF_LIFECYCLE_REVISION ?? "0");
  if (!Number.isSafeInteger(lifecycleRevision) || lifecycleRevision < 0) throw new Error("AWF task lifecycle is invalid");
  if (!host || !token || !task || !role) throw new Error("AWF extension requires a scoped Host session");
  async function call(action: string, toolCallId: string, body: object, signal?: AbortSignal) {
    const response = await fetch(`${host}/internal/tasks/${encodeURIComponent(task!)}/${action}`, {
      method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, "X-AWF-Role": role! },
      body: JSON.stringify({ requestId: `${task}:${toolCallId}`, ...body, lifecycleRevision }), signal,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error?.message || `AWF returned ${response.status}`);
    return { content: [{ type: "text" as const, text: JSON.stringify(data) }], details: data };
  }
  pi.registerTool({ name: "awf_task", label: "Read AWF task", description: "Read this task goal, acceptance criteria, plan, role sessions, execution evidence and budgets before planning or reviewing", parameters: Type.Object({}), execute: (id, params, signal) => call("context", id, params, signal) });
  if (role === "architect") {
    pi.registerTool({ name: "awf_finish", label: "Summarize AWF execution", description: "Complete the current native execution in this same Pi session. Review traced diff/test/remote-SHA output using evidenceChecks; unknown evidence requires needs_changes. Tool observations are not independent verification or proof of Git merge.", parameters: Type.Object({ executionRequestId: Type.String(), verdict: Type.Union([Type.Literal("done"),Type.Literal("needs_changes")]), summary: Type.String({minLength:1}), findings: Type.Array(Type.String()), evidenceChecks: Type.Array(evidenceCheck) }), execute: (id,params,signal) => call("finish",id,params,signal) });
    pi.registerTool({
      name: "awf_plan", label: "Propose AWF plan", description: "Publish a concrete task plan for the user's explicit confirmation. This NEVER authorizes or starts execution. Plan revisions invalidate earlier confirmation.",
      parameters: Type.Object({ content: Type.String({ minLength: 1, description: "Scope, approach, acceptance checks, branch and repository instructions for the executor" }) }),
      execute: (id, params, signal) => call("plan", id, params, signal),
    });
    pi.registerTool({
      name: "awf_execution", label: "Inspect authorized execution", description: "Read the existing explicitly user-authorized execution. The user must first click Confirm Plan and Start Execution. No chat text or tool call substitutes for that authorization.",
      parameters: Type.Object({}), execute: (id, params, signal) => call("execute", id, params, signal),
    });
  }
  if (role === "reviewer") pi.registerTool({
    name: "awf_review", label: "Submit AWF review", description: "Submit an independent review of the current completed native execution. Approved is a review conclusion, not proof of Git merge. Cite actual inspected artifact/test evidence; never infer evidence from claims.",
    parameters: Type.Object({ executionRequestId: Type.String(), verdict: Type.Union([Type.Literal("approved"), Type.Literal("needs_changes")]), summary: Type.String({ minLength: 1 }), findings: Type.Array(Type.String()) }),
    execute: (id, params, signal) => call("review", id, params, signal),
  });
}
