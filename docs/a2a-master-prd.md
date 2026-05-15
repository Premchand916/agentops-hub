# A2A v1.0 Extension — Master PRD
## AgentOps Hub: Agent-to-Agent Protocol Integration

**Version:** 1.0.0  
**Status:** Approved for implementation  
**Author:** Prem Chand  
**Date:** 2026-05-15  
**Branch target:** `main` (via feature branches per milestone)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Goals & Non-Goals](#3-goals--non-goals)
4. [A2A v1.0 Protocol Primer](#4-a2a-v10-protocol-primer)
5. [System Architecture](#5-system-architecture)
6. [Detailed Requirements](#6-detailed-requirements)
   - 6.1 Agent Card Discovery
   - 6.2 JSON-RPC 2.0 Transport
   - 6.3 Task State Machine
   - 6.4 SSE Streaming
   - 6.5 Push Notification Webhooks
   - 6.6 Signed Agent Cards
   - 6.7 Human-in-the-Loop (HITL) Approval
   - 6.8 Buyer Agent Simulator
   - 6.9 Observability Integration
7. [API Specification](#7-api-specification)
8. [Security Model](#8-security-model)
9. [Evaluation Criteria](#9-evaluation-criteria)
10. [Implementation Milestones](#10-implementation-milestones)
11. [File & Module Map](#11-file--module-map)
12. [Key Design Decisions](#12-key-design-decisions)
13. [Open Questions](#13-open-questions)

---

## 1. Executive Summary

AgentOps Hub currently operates as a **closed multi-agent system**: users interact via CLI or Chainlit UI, and four specialist agents (IT Help, Knowledge, Triage, Workflow) collaborate internally via LangGraph. No external agent can discover, invoke, or stream results from these agents.

This extension integrates the **Agent2Agent (A2A) v1.0 open protocol** — Google's inter-agent communication standard — to make AgentOps Hub a **network-addressable agent service**. After this extension:

- Any A2A-compliant agent (AutoGen, CrewAI, another LangGraph app, etc.) can discover AgentOps Hub's capabilities via a standard Agent Card endpoint.
- Remote agents can delegate tasks (IT troubleshooting, knowledge lookup, ticket workflows) over JSON-RPC 2.0.
- Long-running tasks stream partial results via Server-Sent Events (SSE).
- Sensitive workflow actions (ticket creation, password resets) require human approval before execution.
- All inter-agent traffic is traced in Langfuse with the same observability stack already in place.

---

## 2. Problem Statement

### Current Limitations

| Constraint | Impact |
|---|---|
| Single-entry-point CLI/UI | Other AI agents cannot programmatically invoke AgentOps Hub |
| No service discovery | External agents can't know what AgentOps Hub can do without reading source code |
| Synchronous only | Long RAG + reranking pipelines block the caller for 2–5 seconds with no progress signal |
| No auth boundary | Any process with network access could send arbitrary requests |
| Tool actions unguarded | `create_ticket` and `send_notification` execute immediately with no approval gate |

### Why A2A, Not a Custom REST API?

A custom REST API would solve the network-access problem but create a bespoke integration contract every consumer must learn. A2A v1.0 is emerging as the industry standard for agent interoperability (adopted by Google, LangChain, Microsoft AutoGen, and others). Building to the standard means:

- Zero custom SDK for consumers — they use their own A2A client.
- Future-proofing: A2A tooling (testing harnesses, observability, gateways) will work without code changes.
- Portfolio signal: demonstrates protocol-level interoperability knowledge.

---

## 3. Goals & Non-Goals

### Goals

1. **G1 — Agent Card discovery** at `/.well-known/agent.json` listing all skills, auth schemes, and streaming capability.
2. **G2 — Synchronous task execution** via `message/send` JSON-RPC endpoint.
3. **G3 — Streaming task execution** via `message/stream` SSE endpoint.
4. **G4 — Task lifecycle management** — `tasks/get`, `tasks/cancel` with full state machine.
5. **G5 — Signed Agent Cards** — JWK-backed signature so consumers can verify authenticity.
6. **G6 — Push notification webhooks** — HMAC-signed callbacks when long tasks complete.
7. **G7 — HITL approval gate** — High-risk tool actions (ticket creation, notifications) pause for human confirmation.
8. **G8 — Buyer agent simulator** — An end-to-end test agent that acts as an A2A consumer.
9. **G9 — Full Langfuse observability** for all A2A traffic (latency, task state, HITL decisions).
10. **G10 — Existing agents unchanged** — Zero modification to the LangGraph agent nodes; A2A is an adapter layer.

### Non-Goals

- **NG1** — Multi-tenant auth (API keys per user). v1.0 uses a single shared secret for the HMAC webhook and Bearer token for the server. Per-user auth is v2.0 scope.
- **NG2** — A2A client mode (AgentOps Hub calling other A2A agents). This PRD covers server mode only.
- **NG3** — Persistent task storage (database). Tasks are held in-memory with TTL. Persistent storage is v2.0.
- **NG4** — gRPC or WebSocket transport. A2A v1.0 mandates HTTP + SSE; no alternatives needed now.
- **NG5** — UI changes to the Chainlit app. The A2A server is a separate FastAPI process.

---

## 4. A2A v1.0 Protocol Primer

> This section documents the relevant spec facts that drive every design decision in §5–§8.

### 4.1 Agent Card

A static JSON document served at `GET /.well-known/agent.json` (no auth required). Describes the agent to consumers.

```json
{
  "name": "AgentOps Hub",
  "description": "IT operations assistant with RAG, workflow automation, and triage",
  "url": "https://agentops-hub.example.com",
  "version": "1.0.0",
  "capabilities": {
    "streaming": true,
    "pushNotifications": true,
    "stateTransitionHistory": false
  },
  "skills": [
    {
      "id": "it_help",
      "name": "IT Help",
      "description": "Troubleshoot hardware, VPN, and software issues using runbooks",
      "inputModes": ["text"],
      "outputModes": ["text"]
    }
  ],
  "authentication": {
    "schemes": ["Bearer"]
  }
}
```

**Signed Agent Cards (v1.0):** An optional `jwks_uri` field points to a JWKS endpoint. The card is additionally served as a JWS (JSON Web Signature) so consumers can cryptographically verify it was issued by the real agent, not a man-in-the-middle.

### 4.2 JSON-RPC 2.0 Transport

All requests are `POST /` (or `POST /rpc`) with `Content-Type: application/json`.

**Request envelope:**
```json
{
  "jsonrpc": "2.0",
  "id": "req-123",
  "method": "message/send",
  "params": { ... }
}
```

**Response envelope (success):**
```json
{
  "jsonrpc": "2.0",
  "id": "req-123",
  "result": { ... }
}
```

**Response envelope (error):**
```json
{
  "jsonrpc": "2.0",
  "id": "req-123",
  "error": { "code": -32600, "message": "Invalid Request", "data": {} }
}
```

### 4.3 Core Methods

| Method | Purpose |
|---|---|
| `message/send` | Submit a message; returns completed `Task` (blocking) |
| `message/stream` | Submit a message; returns SSE stream of `TaskStatusUpdateEvent` and `TaskArtifactUpdateEvent` |
| `tasks/get` | Fetch a task by ID |
| `tasks/cancel` | Request cancellation of a running task |
| `tasks/pushNotification/set` | Register a webhook URL for push notifications |
| `tasks/pushNotification/get` | Retrieve current webhook config for a task |

### 4.4 Task Object

```json
{
  "id": "task-uuid",
  "sessionId": "session-uuid",
  "status": {
    "state": "working",
    "message": { "role": "agent", "parts": [{ "type": "text", "text": "Searching runbooks..." }] },
    "timestamp": "2026-05-15T10:00:00Z"
  },
  "artifacts": [],
  "metadata": {}
}
```

### 4.5 Task State Machine

```
            ┌──────────┐
            │ submitted│  (client created the task)
            └────┬─────┘
                 │ agent picks up
            ┌────▼─────┐
            │  working │  (agent is processing)
            └──┬───┬───┘
    completes  │   │ requires human input
               │   ▼
               │ ┌──────────────┐
               │ │ input-needed │  (HITL: waiting for approval)
               │ └──────┬───────┘
               │        │ approved / rejected
          ┌────▼──┐  ┌──▼──────┐
          │  done │  │ failed  │
          └───────┘  └─────────┘
                  ▲
           ┌──────┴──┐
           │canceled │  (tasks/cancel called)
           └─────────┘
```

Terminal states: `completed`, `failed`, `canceled`.

### 4.6 Message Parts

A `Message` contains one or more `Part` objects:

| Part Type | Use case |
|---|---|
| `TextPart` | Natural language input/output |
| `FilePart` | Binary attachments (logs, screenshots) |
| `DataPart` | Structured JSON (tool results, ticket objects) |

### 4.7 SSE Streaming Events

When a client calls `message/stream`, the server returns `text/event-stream`:

```
data: {"jsonrpc":"2.0","id":"req-123","result":{"id":"task-uuid","status":{"state":"working","message":{...}}}}

data: {"jsonrpc":"2.0","id":"req-123","result":{"id":"task-uuid","artifact":{"index":0,"parts":[{"type":"text","text":"Found 2 relevant runbooks..."}]}}}

data: {"jsonrpc":"2.0","id":"req-123","result":{"id":"task-uuid","status":{"state":"completed","final":true}}}
```

The `final: true` flag on the last status event signals stream end.

### 4.8 Push Notifications

The client registers a webhook with `tasks/pushNotification/set`:

```json
{
  "taskId": "task-uuid",
  "pushNotificationConfig": {
    "url": "https://client.example.com/webhook",
    "token": "hmac-secret-token"
  }
}
```

The server sends a signed `POST` to that URL when the task reaches a terminal or `input-needed` state. The `X-A2A-Signature` header contains `HMAC-SHA256(body, token)`.

---

## 5. System Architecture

### 5.1 Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        External A2A Consumer                            │
│           (AutoGen agent, LangChain agent, buyer simulator)             │
└──────────────────────┬─────────────────────────┬────────────────────────┘
                       │ JSON-RPC 2.0 / SSE       │ Webhook POST
                       │                          │ (push notification)
┌──────────────────────▼──────────────────────────▼────────────────────────┐
│                    A2A Server  (FastAPI, port 8080)                       │
│                                                                           │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │                      A2A Router  (a2a/router.py)                 │    │
│  │                                                                  │    │
│  │  GET  /.well-known/agent.json  →  AgentCardHandler               │    │
│  │  GET  /.well-known/jwks.json   →  JWKSHandler                    │    │
│  │  POST /rpc                     →  JSONRPCDispatcher              │    │
│  │                                    ├── message/send              │    │
│  │                                    ├── message/stream            │    │
│  │                                    ├── tasks/get                 │    │
│  │                                    ├── tasks/cancel              │    │
│  │                                    ├── tasks/pushNotification/*  │    │
│  └──────────────────────────────────────────────────────────────────┘    │
│                                │                                          │
│  ┌─────────────────────────────▼────────────────────────────────────┐    │
│  │                    TaskManager  (a2a/task_manager.py)             │    │
│  │   in-memory task store  ·  state transitions  ·  TTL cleanup     │    │
│  └───────────────────────────────┬──────────────────────────────────┘    │
│                                  │ delegate to                           │
│  ┌───────────────────────────────▼──────────────────────────────────┐    │
│  │                    A2AAgentAdapter  (a2a/adapter.py)              │    │
│  │   translates A2A message → AgentHub.chat() input                 │    │
│  │   translates AgentHub response → A2A Task artifacts              │    │
│  │   intercepts HITL-flagged tool calls → pauses task               │    │
│  └───────────────────────────────┬──────────────────────────────────┘    │
│                                  │                                        │
└──────────────────────────────────┼────────────────────────────────────────┘
                                   │
┌──────────────────────────────────▼────────────────────────────────────────┐
│                   Existing AgentOps Hub Core (unchanged)                   │
│                                                                            │
│   agents/graph.py  ·  AgentHub.chat()  ·  ToolRegistry  ·  RAG Pipeline  │
│   Langfuse tracer  ·  Guardrails                                           │
└────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Process Model

- The existing CLI (`app/cli.py`) and Chainlit UI (`app/chainlit_app.py`) remain untouched.
- A new FastAPI app (`a2a/server.py`) runs on port **8080** alongside or instead of those.
- The `A2AAgentAdapter` is the only new code that touches the existing agent layer — it calls `AgentHub.chat()` exactly as the CLI does.
- The `TaskManager` holds tasks in a `dict[str, Task]` with asyncio background TTL cleanup (default 1 hour).

### 5.3 New Modules

```
agentops-hub/
└── a2a/
    ├── __init__.py
    ├── server.py          # FastAPI app, lifespan, CORS
    ├── router.py          # route definitions, auth middleware
    ├── models.py          # Pydantic models: Task, Message, Part, AgentCard, …
    ├── task_manager.py    # In-memory task store + state machine
    ├── adapter.py         # A2AAgentAdapter: bridges A2A ↔ AgentHub.chat()
    ├── streaming.py       # SSE generator for message/stream
    ├── push.py            # Webhook sender with HMAC signing
    ├── signing.py         # RSA key generation, JWS signing, JWKS endpoint
    ├── hitl.py            # HITL approval gate (asyncio.Event + timeout)
    └── simulator/
        ├── __init__.py
        └── buyer_agent.py # A2A consumer agent for end-to-end testing
```

---

## 6. Detailed Requirements

### 6.1 Agent Card Discovery

**Endpoint:** `GET /.well-known/agent.json`  
**Auth:** None (public)  
**Response:** `AgentCard` JSON

The card MUST advertise:

| Field | Value |
|---|---|
| `name` | `"AgentOps Hub"` |
| `version` | `"1.0.0"` |
| `capabilities.streaming` | `true` |
| `capabilities.pushNotifications` | `true` |
| `skills` | Array of 4 skills (see below) |
| `authentication.schemes` | `["Bearer"]` |
| `jwks_uri` | `"/.well-known/jwks.json"` (when signing enabled) |

**Skills to advertise:**

| Skill ID | Name | Description |
|---|---|---|
| `it_help` | IT Help | Troubleshoot VPN, hardware, and software using company runbooks |
| `knowledge` | Knowledge Base | Answer HR, policy, and operational questions |
| `triage` | Triage | Assess issue severity and recommend escalation path |
| `workflow` | Workflow Automation | Create tickets, check system status, send notifications |

**Acceptance criteria:**
- [ ] `GET /.well-known/agent.json` returns HTTP 200 with `Content-Type: application/json`.
- [ ] Card validates against A2A v1.0 JSON schema.
- [ ] Card is served without authentication.
- [ ] When signing is enabled, card also available as JWS at `GET /.well-known/agent.json?format=jws`.

---

### 6.2 JSON-RPC 2.0 Transport

**Endpoint:** `POST /rpc`  
**Auth:** `Authorization: Bearer <token>` (validated against `A2A_BEARER_TOKEN` env var)  
**Content-Type:** `application/json`

The dispatcher MUST:

1. Validate the JSON-RPC 2.0 envelope (jsonrpc field, id, method, params).
2. Return `-32600 Invalid Request` for malformed envelopes.
3. Return `-32601 Method not found` for unknown methods.
4. Return `-32602 Invalid params` when Pydantic validation fails on `params`.
5. Return `-32000 Internal error` for unexpected exceptions (with sanitized message — no stack traces in response).
6. Handle `id: null` (notification pattern) by processing but returning no response.

**Acceptance criteria:**
- [ ] Valid request → correct `result` in response.
- [ ] Missing `jsonrpc` field → `-32600` error response.
- [ ] Unknown method → `-32601` error response.
- [ ] Bearer token missing or wrong → HTTP 401 (not a JSON-RPC error).

---

### 6.3 Task State Machine

**`message/send` flow:**

1. Validate params: `{ message: Message, sessionId?: str, metadata?: dict }`.
2. Create Task in state `submitted`.
3. Transition to `working`.
4. Run `A2AAgentAdapter.run(message)` — blocks until agent finishes or HITL pause.
5. If HITL triggered: transition to `input-needed`, await approval (timeout = 5 min).
6. On completion: populate `task.artifacts`, transition to `completed`.
7. On exception: transition to `failed` with error message.
8. Return full `Task` object.

**`tasks/get` params:** `{ id: str }`  
**`tasks/cancel` params:** `{ id: str }`

Cancellation MUST:
- Set a `cancel_event` (asyncio.Event) that the adapter polls.
- Transition the task to `canceled` if it hasn't reached a terminal state.
- Return `-32001 Task not cancellable` if already in terminal state.

**Acceptance criteria:**
- [ ] Task progresses through `submitted → working → completed` on success.
- [ ] Task transitions to `failed` on agent exception.
- [ ] `tasks/cancel` during `working` eventually reaches `canceled`.
- [ ] `tasks/get` on unknown ID returns `-32001` error.
- [ ] Completed tasks are accessible for at least 1 hour post-completion.

---

### 6.4 SSE Streaming

**`message/stream` flow:**

1. Same params as `message/send`.
2. Create Task, transition to `working`.
3. Return HTTP 200 with `Content-Type: text/event-stream`.
4. Yield `TaskStatusUpdateEvent` on each state transition.
5. Yield `TaskArtifactUpdateEvent` for each intermediate artifact (e.g., RAG sources found, reranking score).
6. Yield final `TaskStatusUpdateEvent` with `status.state = "completed"` and `final: true`.
7. Close the SSE stream.

**Intermediate artifacts to stream:**

| Agent | Artifact yielded mid-stream |
|---|---|
| IT Help | `"Searching runbooks... found N chunks"` after retrieval, before reranking |
| Knowledge | `"Retrieving policy documents..."` |
| Workflow | `"Executing tool: create_ticket"` before tool call |
| Orchestrator | `"Routing to: IT_HELP (confidence: 0.88)"` |

**Acceptance criteria:**
- [ ] Client receives ≥ 2 SSE events before the `final: true` event.
- [ ] Stream closes cleanly after `final: true`.
- [ ] Client disconnect mid-stream cancels the underlying task.
- [ ] Reconnect with same task ID resumes from current state (using `tasks/get`).

---

### 6.5 Push Notification Webhooks

**Registration:** `tasks/pushNotification/set`  
**Params:** `{ id: str, pushNotificationConfig: { url: str, token: str } }`

The server MUST:
1. Validate `url` is HTTPS (reject HTTP in production; allow in test mode via `A2A_ALLOW_HTTP_WEBHOOKS=true`).
2. Validate `token` is at least 32 characters.
3. Store config in the Task object.
4. Send a signed POST when task reaches `completed`, `failed`, `canceled`, or `input-needed`.

**Webhook payload:**
```json
{
  "taskId": "task-uuid",
  "event": "status",
  "status": { "state": "completed", "timestamp": "..." },
  "artifacts": [...]
}
```

**Signature:** `X-A2A-Signature: sha256=<hex(HMAC-SHA256(raw_body, token))>`

**Delivery policy:**
- 3 retry attempts with exponential backoff (2s, 4s, 8s).
- Log delivery failure to Langfuse as a span tag `webhook.delivery = "failed"`.

**Acceptance criteria:**
- [ ] Webhook fires on `completed` state with correct payload.
- [ ] Webhook fires on `input-needed` state.
- [ ] `X-A2A-Signature` validates correctly in buyer simulator.
- [ ] HTTP webhook URL rejected with meaningful error.
- [ ] Failed delivery logged; task not re-run.

---

### 6.6 Signed Agent Cards

**Key management:**
- On startup, generate RSA-2048 key pair or load from `A2A_PRIVATE_KEY_PATH` env var.
- Persist key to `~/.agentops-hub/signing_key.pem` (outside repo) on first run.
- Expose public key as JWKS at `GET /.well-known/jwks.json`.

**JWS-signed card:**
- `GET /.well-known/agent.json?format=jws` returns a compact JWS (`header.payload.signature`).
- Algorithm: `RS256`.
- Payload: base64url-encoded Agent Card JSON.
- Consumers verify with the JWKS public key.

**Acceptance criteria:**
- [ ] `GET /.well-known/jwks.json` returns valid JWKS with at least one `RS256` key.
- [ ] JWS signature verifies using the JWKS public key (`python-jose` or `cryptography`).
- [ ] Signing key is NOT committed to the repository (covered by `.gitignore`).
- [ ] Key regenerated if `A2A_ROTATE_KEYS=true` at startup.

---

### 6.7 Human-in-the-Loop (HITL) Approval

**Trigger:** Any Workflow Agent tool call where `ToolSchema.requires_approval = True`.

Current tools requiring approval:
- `create_ticket` (creates a real ticket)
- `send_notification` (sends an alert)

**HITL flow:**
1. Adapter detects tool call targeting an approval-required tool.
2. Task transitions to `input-needed`.
3. Approval request stored: `{ tool: str, args: dict, task_id: str, expires_at: datetime }`.
4. Push notification fires if webhook registered.
5. Approver calls `message/send` with `{ type: "approval", decision: "approve" | "reject", taskId: str }`.
6. If approved: tool executes, task resumes to `working`, then `completed`.
7. If rejected: tool skipped, agent receives rejection reason, task completes with note.
8. If timeout (5 min): task transitions to `failed` with `"HITL timeout"`.

**UI for approvals (MVP):** A simple `/approvals` FastAPI endpoint returns pending approvals as JSON. A future Chainlit panel can render these.

**Acceptance criteria:**
- [ ] `create_ticket` call pauses task to `input-needed`.
- [ ] Task resumes to `completed` on approval.
- [ ] Task reaches `failed` on 5-minute timeout.
- [ ] Rejection reason included in final artifact.
- [ ] HITL decision logged to Langfuse as span event.

---

### 6.8 Buyer Agent Simulator

**Location:** `a2a/simulator/buyer_agent.py`

A script that acts as an A2A consumer to validate the full server integration end-to-end.

**Test scenarios:**

| # | Scenario | Method | Expected outcome |
|---|---|---|---|
| 1 | IT issue lookup | `message/send` | `completed` task with RAG answer |
| 2 | Knowledge question | `message/send` | `completed` task with policy answer |
| 3 | Ticket creation | `message/send` | `input-needed` → approve → `completed` |
| 4 | Streaming IT query | `message/stream` | ≥ 3 SSE events, final `completed` |
| 5 | Webhook notification | `message/send` + webhook | Webhook fires on `completed` |
| 6 | Cancel running task | `tasks/cancel` | `canceled` state |
| 7 | Signed card verify | `GET /.well-known/agent.json?format=jws` | JWS validates |
| 8 | Invalid auth | `POST /rpc` (no Bearer) | HTTP 401 |

**Acceptance criteria:**
- [ ] `python a2a/simulator/buyer_agent.py` runs all 8 scenarios and prints pass/fail.
- [ ] Exit code 0 if all pass, 1 if any fail.
- [ ] Simulator integrated into `evals/run_evals.py` as an optional `--a2a` flag.

---

### 6.9 Observability Integration

Every A2A request MUST create a Langfuse trace with the existing `AgentTracer`.

**Trace structure for A2A requests:**

```
Trace: a2a_request
  ├── Span: rpc_dispatch          (method, task_id, session_id)
  ├── Span: agent_execution       (route, agent_name, latency_ms)
  │     └── (existing agent spans from AgentHub.chat())
  ├── Span: hitl_approval         (tool_name, decision, wait_ms)   [if HITL]
  └── Span: webhook_delivery      (url_domain, status_code)         [if webhook]
```

**Tags added to existing AgentHub traces:**
- `a2a.task_id`
- `a2a.session_id`
- `a2a.method` (`message/send` | `message/stream`)

**Acceptance criteria:**
- [ ] Every `message/send` creates one Langfuse trace.
- [ ] HITL approval span records `decision` and `wait_ms`.
- [ ] Webhook delivery span records HTTP status code.
- [ ] Offline mode (no Langfuse env vars) falls back to JSONL without crashing.

---

## 7. API Specification

### 7.1 Authentication

All `POST /rpc` requests require:
```
Authorization: Bearer <A2A_BEARER_TOKEN>
```
Where `A2A_BEARER_TOKEN` is set as an environment variable. Missing or incorrect tokens → HTTP 401.

The Agent Card endpoint (`GET /.well-known/agent.json`) and JWKS endpoint are unauthenticated.

### 7.2 Complete Method Reference

#### `message/send`

```json
// Request params
{
  "message": {
    "role": "user",
    "parts": [
      { "type": "text", "text": "My VPN shows error E-4012" }
    ]
  },
  "sessionId": "optional-session-uuid",
  "metadata": {}
}

// Response result
{
  "id": "task-uuid",
  "sessionId": "session-uuid",
  "status": {
    "state": "completed",
    "timestamp": "2026-05-15T10:00:01Z"
  },
  "artifacts": [
    {
      "index": 0,
      "name": "response",
      "parts": [
        {
          "type": "text",
          "text": "Error E-4012 is caused by an expired VPN certificate. Steps: 1) Open VPN client..."
        }
      ]
    }
  ]
}
```

#### `message/stream`

Same params as `message/send`. Returns `text/event-stream`:

```
data: {"jsonrpc":"2.0","id":"req-1","result":{"id":"task-uuid","status":{"state":"working","message":{"role":"agent","parts":[{"type":"text","text":"Routing to IT Help Agent..."}]}}}}

data: {"jsonrpc":"2.0","id":"req-1","result":{"id":"task-uuid","artifact":{"index":0,"append":false,"parts":[{"type":"text","text":"Searching runbooks... found 3 relevant chunks"}]}}}

data: {"jsonrpc":"2.0","id":"req-1","result":{"id":"task-uuid","status":{"state":"completed","final":true,"timestamp":"..."}}}
```

#### `tasks/get`

```json
// Request params
{ "id": "task-uuid" }

// Response result: full Task object (same as message/send result)
```

#### `tasks/cancel`

```json
// Request params
{ "id": "task-uuid" }

// Response result
{ "id": "task-uuid", "status": { "state": "canceled", "timestamp": "..." } }
```

#### `tasks/pushNotification/set`

```json
// Request params
{
  "id": "task-uuid",
  "pushNotificationConfig": {
    "url": "https://consumer.example.com/webhook",
    "token": "minimum-32-character-secret-token-here"
  }
}

// Response result
{ "id": "task-uuid", "pushNotificationConfig": { "url": "...", "token": "***" } }
```

#### `tasks/pushNotification/get`

```json
// Request params
{ "id": "task-uuid" }

// Response result
{ "id": "task-uuid", "pushNotificationConfig": { "url": "...", "token": "***" } }
```

### 7.3 JSON-RPC Error Codes

| Code | Constant | Meaning |
|---|---|---|
| -32700 | Parse error | Request body is not valid JSON |
| -32600 | Invalid Request | JSON-RPC envelope is malformed |
| -32601 | Method not found | Unknown method name |
| -32602 | Invalid params | Pydantic validation failed on params |
| -32000 | Internal error | Unhandled exception |
| -32001 | Task not found | Unknown task ID |
| -32002 | Task not cancellable | Task already in terminal state |
| -32003 | HITL timeout | Approval window expired |

---

## 8. Security Model

### 8.1 Threat Model (Abbreviated)

| Threat | Mitigation |
|---|---|
| Unauthorized agent calls | Bearer token on all `/rpc` requests |
| Webhook forgery | HMAC-SHA256 signature on all webhook deliveries |
| Agent Card spoofing | JWS-signed card with RSA-2048 key pair |
| Prompt injection via A2A message | Existing guardrails in `evals/guardrails.py` applied to A2A input text |
| SSRF via webhook URL | Webhook URL validated against allowlist or HTTPS-only policy |
| Signing key leak | Key stored outside repo, in `.gitignore`-covered path |
| Denial of service via task flooding | `MAX_CONCURRENT_TASKS=50` env var; new tasks rejected with `-32000` when at limit |

### 8.2 Secrets & Configuration

New environment variables (add to `.env.example`):

```bash
# A2A Server
A2A_BEARER_TOKEN=change-me-in-production-min-32-chars
A2A_PORT=8080
A2A_BASE_URL=http://localhost:8080

# Signing
A2A_PRIVATE_KEY_PATH=~/.agentops-hub/signing_key.pem
A2A_ROTATE_KEYS=false

# HITL
A2A_HITL_TIMEOUT_SECONDS=300

# Webhooks
A2A_ALLOW_HTTP_WEBHOOKS=false   # true in local dev/test only

# Limits
A2A_MAX_CONCURRENT_TASKS=50
A2A_TASK_TTL_SECONDS=3600
```

### 8.3 Input Validation Pipeline for A2A Messages

```
Incoming message.parts[].text
         │
         ▼
   Guardrails.check_pii()        # existing PII detector
         │
         ▼
   Guardrails.check_scope()      # topic scope (IT, HR, ops only)
         │
         ▼
   A2AAgentAdapter.run()         # pass to AgentHub.chat()
```

---

## 9. Evaluation Criteria

### 9.1 Protocol Conformance

The buyer agent simulator (§6.8) constitutes the primary conformance test. All 8 scenarios must pass.

### 9.2 Integration with Existing Eval Suite

The existing 30-test YAML eval suite (`evals/test_cases/eval_suite.yaml`) will be extended with A2A-specific cases:

| Category | New tests | Total |
|---|---|---|
| a2a_routing | 5 (one per skill via A2A) | 5 |
| a2a_streaming | 3 (stream delivers partials) | 3 |
| a2a_hitl | 4 (approve, reject, timeout, cancel) | 4 |
| a2a_security | 3 (bad auth, SSRF attempt, PII in message) | 3 |

Target: maintain ≥ 80% pass rate gate in CI (these 15 new tests target 100%).

### 9.3 Performance Targets

| Metric | Target | Measurement |
|---|---|---|
| `message/send` p95 latency | < 5 seconds | Langfuse p95 |
| First SSE event latency | < 500 ms | Buyer simulator timer |
| Webhook delivery latency | < 2 seconds | Span `webhook_delivery` |
| HITL timeout precision | ± 5 seconds of configured TTL | Unit test |

---

## 10. Implementation Milestones

### M0 — Foundational Understanding (Pre-work, ~0.5 day)
- [ ] Read A2A v1.0 spec: `google/A2A` repo on GitHub
- [ ] Run the official A2A Python sample server
- [ ] Document protocol gaps vs. this PRD in §13 (Open Questions)
- **Commit:** `docs(a2a): foundational understanding of A2A v1.0 protocol`

### M1 — Agent Card + Bare Server (~1 day)
- [ ] `a2a/models.py`: Pydantic models for AgentCard, Skill, Capabilities
- [ ] `a2a/server.py`: FastAPI app skeleton with lifespan
- [ ] `a2a/router.py`: `GET /.well-known/agent.json` handler
- [ ] Unit test: card validates against JSON schema
- **Commit:** `feat(a2a): implement A2A v1.0 Agent Card discovery endpoint`

### M2 — JSON-RPC Dispatcher + message/send (~1 day)
- [ ] `a2a/models.py`: Task, Message, Part, JSONRPCRequest/Response models
- [ ] `a2a/router.py`: `POST /rpc` with Bearer auth middleware
- [ ] `a2a/task_manager.py`: in-memory store, state transitions
- [ ] `a2a/adapter.py`: `A2AAgentAdapter.run()` calling `AgentHub.chat()`
- [ ] Integration test: `message/send` → `completed`
- **Commit:** `feat(a2a): implement JSON-RPC 2.0 message/send and tasks/get`

### M3 — Task State Machine + Cancellation (~0.5 day)
- [ ] `tasks/get` and `tasks/cancel` methods
- [ ] `cancel_event` asyncio.Event plumbed through adapter
- [ ] TTL cleanup background task
- [ ] Unit tests for all state transitions
- **Commit:** `feat(a2a): implement task state machine with cancellation`

### M4 — SSE Streaming (~1 day)
- [ ] `a2a/streaming.py`: async generator yielding SSE events
- [ ] `message/stream` method in dispatcher
- [ ] Adapter emits intermediate artifacts via asyncio.Queue
- [ ] Integration test: ≥ 3 events before `final: true`
- **Commit:** `feat(a2a): implement SSE streaming for message/stream`

### M5 — Push Notifications (~0.5 day)
- [ ] `a2a/push.py`: HMAC signing + HTTP delivery + retry logic
- [ ] `tasks/pushNotification/set` and `tasks/pushNotification/get` methods
- [ ] Webhook URL validation (HTTPS enforcement)
- [ ] Integration test: webhook fires on completion
- **Commit:** `feat(a2a): implement signed push notification webhooks`

### M6 — Signed Agent Cards (~0.5 day)
- [ ] `a2a/signing.py`: RSA key generation, JWS signing, JWKS serialization
- [ ] `GET /.well-known/jwks.json` endpoint
- [ ] `GET /.well-known/agent.json?format=jws` endpoint
- [ ] Unit test: JWS verifies with JWKS public key
- **Commit:** `feat(a2a): implement Signed Agent Cards (A2A v1.0)`

### M7 — Buyer Agent Simulator (~1 day)
- [ ] `a2a/simulator/buyer_agent.py`: all 8 test scenarios
- [ ] Exit code 0/1 convention
- [ ] `--a2a` flag in `evals/run_evals.py`
- [ ] CI: add simulator run to `eval.yml`
- **Commit:** `feat: A2A v1.0 buyer agent simulator for AgentOps Hub`

### M8 — HITL + Observability (~1 day)
- [ ] `a2a/hitl.py`: approval store, asyncio.Event, timeout logic
- [ ] `ToolSchema.requires_approval` flag on `create_ticket`, `send_notification`
- [ ] Adapter intercepts approval-required tool calls
- [ ] `GET /approvals` endpoint (JSON list of pending approvals)
- [ ] Langfuse spans for HITL and webhook delivery
- [ ] All new tests passing; existing 30 tests still green
- **Commit:** `feat(hitl): human-in-the-loop approval + Langfuse observability`

### M9 — Production Hardening & Release (~0.5 day)
- [ ] `docker-compose.yml` updated to expose port 8080
- [ ] `README.md` updated with A2A quick start section
- [ ] `A2A_BEARER_TOKEN` added to `.env.example`
- [ ] `requirements.txt` updated (httpx for webhook delivery, python-jose for JWS)
- [ ] All 45 tests (30 existing + 15 A2A) passing
- **Commit:** `feat: A2A v1.0.0 — production-ready A2A v1.0 extension`

---

## 11. File & Module Map

### New files

| File | Purpose |
|---|---|
| `a2a/__init__.py` | Package init, version constant |
| `a2a/server.py` | FastAPI app, lifespan (key generation, task TTL cleanup) |
| `a2a/router.py` | Route definitions + Bearer auth middleware |
| `a2a/models.py` | Pydantic v2 models for all A2A protocol objects |
| `a2a/task_manager.py` | In-memory task store, state machine, TTL cleanup |
| `a2a/adapter.py` | Bridges A2A message → `AgentHub.chat()` → A2A artifacts |
| `a2a/streaming.py` | Async SSE generator, intermediate artifact queue |
| `a2a/push.py` | HMAC-signed webhook delivery with retries |
| `a2a/signing.py` | RSA key pair, JWS signing, JWKS serialization |
| `a2a/hitl.py` | Approval gate: store, asyncio.Event, timeout |
| `a2a/simulator/__init__.py` | Simulator package |
| `a2a/simulator/buyer_agent.py` | End-to-end A2A consumer for all 8 test scenarios |

### Modified files (minimal)

| File | Change |
|---|---|
| `tools/schemas.py` | Add `requires_approval: bool = False` field to `ToolSchema` |
| `tools/backends.py` | Set `requires_approval=True` on `create_ticket`, `send_notification` |
| `evals/run_evals.py` | Add `--a2a` CLI flag; call buyer_agent simulator |
| `evals/test_cases/eval_suite.yaml` | Add 15 A2A test cases |
| `.github/workflows/eval.yml` | Start A2A server in background before eval run |
| `docker/docker-compose.yml` | Expose port 8080 for A2A server |
| `.env.example` | Add all new A2A env vars |
| `requirements.txt` | Add `httpx`, `python-jose[cryptography]`, `sse-starlette` |
| `pyproject.toml` | Add `a2a*` to packages list |

### Unchanged files (zero modification)

`agents/graph.py`, `agents/orchestrator.py`, `agents/specialists.py`, `agents/workflow.py`, `agents/state.py`, `rag/`, `config/`, `observability/tracer.py`, `app/cli.py`, `app/chainlit_app.py`

---

## 12. Key Design Decisions

### Why FastAPI over Flask or raw ASGI?

FastAPI has native async support (required for SSE and async task management), automatic OpenAPI docs, and first-class Pydantic integration. The rest of the stack already uses Pydantic v2. Flask would require a sync-to-async bridge. Raw ASGI adds unnecessary boilerplate.

### Why in-memory task store over Redis/Postgres?

Redis adds operational complexity (another dependency in docker-compose). For a v1.0 portfolio project with single-process deployments, an in-memory `dict` with TTL cleanup is sufficient and zero-dependency. The PRD explicitly marks persistent storage as v2.0 scope (NG3).

### Why asyncio.Event for HITL, not a database queue?

HITL approvals are short-lived (5-minute timeout) and co-located in the same process. `asyncio.Event.wait(timeout=300)` is the simplest correct implementation. A message queue (Celery, Redis Streams) would be over-engineering for in-process signaling.

### Why RSA-2048 for signing, not Ed25519?

A2A v1.0 spec example implementations use RS256 (RSA + SHA-256). Ed25519 (EdDSA) has better performance but lower library support in the Python `python-jose` ecosystem. RS256 is the safe, spec-aligned default for v1.0.

### Why `sse-starlette` over manual SSE encoding?

`sse-starlette` integrates cleanly with FastAPI's `StreamingResponse` and handles connection lifecycle (client disconnects, keepalive pings). Manual SSE encoding is ~30 lines of code that would need its own tests. The library is battle-tested and adds no transitive dependencies beyond Starlette (already present via FastAPI).

### Zero changes to existing agent layer

The `A2AAgentAdapter` is the sole new code touching `AgentHub.chat()`. It calls the same interface as `app/cli.py` — just with a different string input (extracted from `message.parts[0].text`). This preserves all existing tests and avoids regressions in the 30-test eval suite.

---

## 13. Open Questions

| # | Question | Owner | Target resolution |
|---|---|---|---|
| Q1 | Does A2A v1.0 spec require `sessionId` to be persisted across requests, or is it advisory only? | Implementer | M0 (spec read) |
| Q2 | Should `GET /approvals` require Bearer auth? (Currently planned as unauthed for MVP simplicity) | Prem Chand | M8 design |
| Q3 | When an A2A consumer sends a `FilePart`, should we extract text for RAG or return an unsupported error? | Implementer | M2 |
| Q4 | Does the buyer simulator need to run against a live Ollama instance in CI, or should the adapter be mockable? | Implementer | M7 — recommend mock for CI speed |
| Q5 | Should the A2A server be the new primary entry point (replacing CLI), or a sidecar process? | Prem Chand | Architecture decision before M1 |
| Q6 | A2A spec allows multiple `authentication.schemes`. Should we also support `ApiKey` for consumers that can't set Bearer headers? | Future | v2.0 |

---

*This PRD is the authoritative specification for the A2A v1.0 extension to AgentOps Hub. All implementation decisions that deviate from this document should be noted in the relevant commit message.*
