# Paperclip company quota manager

This directory is company-level coordination infrastructure, not fraud-product code. It implements a deterministic, standard-library-only monitor, pre-provider launch guard, and active-run control plane. The company policy is complete and validated against Maya-approved Cloud Provider Quota Protection Policy v1.1, so `validate` reports no missing values. A Maya-approved Windows Scheduled Task now supervises the monitor, so shared state stays FRESH continuously and is restored within one minute if the monitor stops. The remaining activation step is the launch guard: no agent has been pointed at a guard wrapper yet, pending Maya's approval of the per-agent setting. Because state goes stale after 180 seconds, every guarded launch fails closed whenever the monitor is not running.

## Authoritative locations

- Schema: `company-policy.schema.json`
- Company policy: `companies/e6b7cf59-43ee-4b47-82b0-d1a3ed33b26e/policy.json`
- Shared-state schema: `shared-state.schema.json`
- Preventive-control event schema: `control-event.schema.json`
- Shared state (created by the monitor only after it is deliberately run): `companies/e6b7cf59-43ee-4b47-82b0-d1a3ed33b26e/state.json`
- Preventive-control ledger (created only by enabled enforcement): `companies/e6b7cf59-43ee-4b47-82b0-d1a3ed33b26e/control-events.jsonl`

Agents and tasks do not carry threshold, reserve, polling, or concurrency values. The state is atomically replaced JSON, so guards perform only one cheap local read.

## Evidence-backed provider sources

Claude Code's stream-JSON protocol accepts a `control_request` with subtype `get_usage` and `skip_behaviors: true`. Its successful response includes `rate_limits_available`, subscription type, five-hour and seven-day utilization/reset data, and possibly additional forward-compatible fields. The response's session metrics showed zero API duration and no model usage in the local investigation, so this is a control request rather than an inference turn. The monitor removes Anthropic/API-routing overrides and sets the configured subscription profile directory before launching it. Any missing response, authentication/transport failure, `rate_limits_available != true`, or unusable required window becomes UNKNOWN.

Codex CLI 0.156.1 exposes `account/rateLimits/read` over `codex app-server --stdio`. The monitor initializes JSON-RPC and reads `ordinaryUsageAllowed`, the primary/secondary windows (`usedPercent`, duration, reset), plus account metadata. This creates no prompt, thread, or inference turn. A null/false availability signal, authentication/network/RPC failure, or malformed required window does not become GREEN. `ordinaryUsageAllowed=false` is RED; missing/null availability is UNKNOWN.

Paperclip 2026.1001.0 also has `/api/companies/{companyId}/costs/quota-windows`, but its installed Claude adapter currently calls the Anthropic OAuth usage HTTP endpoint first and has an interactive fallback. This implementation uses the repository-approved non-inference Claude control request instead. Active shared consumers come from Paperclip's read-only `/api/companies/{companyId}/live-runs?minCount=0`; each queued/running record includes run ID, agent ID/name, and adapter type. The query page size is policy-supplied, not treated as a maximum-agent policy: reaching it makes concurrency UNKNOWN rather than silently undercounting consumers.

## Normalization and fail safety

Each cloud provider remains a separate quota pool and state record. Claude's `five_hour` and `seven_day` windows and Codex's `primary` and `secondary` windows are evaluated independently. Every persisted window contains its provider-native ID and metric, observed and effective values, reset metadata, its own thresholds and reserve, the concurrency adjustment applied to that window, its individual state, and whether it determines the provider-level state. Provider state is the worst window state. Raw provider responses and credentials are never persisted.

Only those four subscription plan windows are capacity inputs. Claude extra-usage, purchased-credit, promotional, or provider-added pools and Codex credit details are neither normalized as available capacity nor used by classification. The Codex request explicitly skips reset-credit detail. The manager only reads reset timestamps; it contains no operation that resets, purchases, enables, reloads, or consumes credits.

Health is one of `FRESH`, `UNAVAILABLE`, `STALE`, `MALFORMED`, or `CONFIGURATION_INCOMPLETE`; quota state is `GREEN`, `AMBER`, `RED`, or `UNKNOWN`. Ollama is explicitly `EXCLUDED`. Missing/malformed state, stale timestamps, failed probes, policy-version mismatch, or incomplete policy deny a new cloud launch. They never produce GREEN. When configured, concurrency adds the centrally configured adjustment for each additional active consumer in the same provider pool before thresholds are evaluated.

Policy v1.1 separates a transient telemetry failure from persistent UNKNOWN/STALE. A failed probe writes `health` and `telemetry.probedAt` for the attempt while retaining the last trustworthy reading under `telemetry.lastTrustworthyAt`/`lastTrustworthyState`/`lastTrustworthyCausingWindows`, so consecutive failures keep measuring age from the original observation instead of restarting the clock on every retry. New provider work is denied from the first failure. Active work keeps following the retained reading until it ages past the same central `monitoring.staleAfterSeconds` threshold, after which the provider is fail-closed `UNKNOWN`/`STATE_STALE` and the unchanged `unknown` behavior applies. A positively observed `RED` is unaffected and still stops active work at once, and a reading retained across a failure keeps the `RED` it recorded. The retained reading is carried only while `companyId` and `configurationVersion` still match, so a configuration change grants no grace. This introduces no new threshold and changes no other behavior.

## Runtime boundary and active-run control

`host/bin/claude.cmd` and `host/bin/codex.cmd` are pre-provider wrappers for the adapters' supported `adapterConfig.command` seam. Their basenames deliberately stay `claude` and `codex`: the Claude adapter applies its minimum-CLI-version-for-model preflight only when the configured command's basename is the provider's own, so a differently named wrapper would silently skip that check. Each calls `quota_manager.py exec`, reads central policy/state, and starts the real CLI only on ALLOW. Thus a blocked launch uses no Claude/Codex turn. The wrapper forwards only the adapter's own arguments; the executable is taken from the centrally configured provider command, so the guarded launch cannot drift from the binary the monitor probes and never depends on PATH shim resolution (the installed `claude`/`codex` PATH entries are `.cmd`/`.ps1` shims, which `CreateProcess` cannot execute directly). An allowed launch is unresolvable rather than silently PATH-resolved when the central command is missing. Do not configure agents to use these wrappers until the policy is complete and a supervised monitor is running; otherwise fail-closed behavior will intentionally block them.

This boundary reliably prevents **new CLI-engine processes**. Paperclip's ACP engine uses `agentCommand` and may keep a provider process alive across work units, so launch guards alone cannot protect a process that is already running.

The installed Paperclip 2026.1001.0 runtime supplies the least-invasive supported active-run boundary:

- `GET /api/companies/{companyId}/live-runs` exposes queued/running heartbeat records with run, agent, adapter, runtime, issue, process, session, and output metadata. The monitor maps configured adapter types to the central provider pool; all agents in the same pool are considered together.
- `POST /api/agents/{agentId}/pause` is a board-only route; this local deployment's implicit-board mode can call it on the configured loopback URL. It first makes the agent non-invokable, then calls `cancelActiveForAgent`. That covers the agent's queued, running, and scheduled-retry heartbeat runs. It is safer than cancelling one run because another queued run cannot immediately replace it.
- Native ACP cancellation publishes the cancellation boundary synchronously before asking the provider transport to interrupt. The harness then suppresses non-cancellation events and refuses a later `startTurn`. Claude and Codex use their native interrupt/cancel facilities through this common boundary. Legacy execution is terminated through Paperclip's tracked process ownership/group cleanup.
- Paperclip persists the run row, lifecycle/output events, session identifiers, issue context, and workspace changes. Cancellation does not manufacture a provider-authored summary or comment. Those durable records plus the quota manager's intent/result ledger are the recoverable checkpoint.
- The paused run is terminalized as `cancelled` with Paperclip error code `agent_paused`. The agent remains paused until an operator explicitly resumes it. Paperclip classifies `agent_paused` as default/retryable *after resume*, so continuation can proceed then; it is not classified as `provider_quota`, does not create a provider-quota reset-time retry, and cannot dispatch while the agent is paused.

The quota manager groups active consumers by provider pool and agent. Adapter-type mappings must be disjoint, so one run cannot be attributed to two pools. For a centrally configured `pause_agents` action it appends an intent record before invoking the pause endpoint and a result record afterward. Each record identifies provider, pool, quota state/reason, causal windows (for AMBER/RED), agent, observed run IDs, and explicitly records that no provider inference or automatic resume was requested. A failure to pause one agent is recorded and does not prevent attempts for other affected agents. Paperclip's supported control unit is the agent, not the quota-manager-observed run: pausing an affected provider-bound agent conservatively cancels all of that agent's cancellable runs, while other agents and provider pools are untouched.

No stable public interface was found to inject an arbitrary deterministic checkpoint/control message into an already-running ACP turn. Runtime requests answer an already-pending provider question; steering, where supported internally, is another provider interaction and is not a quota-free cancellation primitive. No general pre-prompt, pre-turn, or pre-tool quota hook exists. A provider's quota can therefore deteriorate during one long turn before Paperclip naturally regains control. The supported pause/cancel endpoint is the RED-safe mechanism because it requires no further provider inference.

## Deterministic continuation checkpoints

After Paperclip confirms a preventive pause, Quota Manager persists the result
event and dispatches one idempotent task per interrupted run to the Local
Evidence & Validation Worker (`48ed952b-bcbe-4fa1-86e2-5048b76535ce`). The
dispatch identity is the SHA-256 digest of the company, provider, interrupted
agent, source task, and source run. Paperclip's issue-creation idempotency key is
derived from that identity, so reconciliation replays the original collector
task rather than creating a duplicate.

Before dispatch, Quota Manager snapshots an allowlisted subset of the persisted
Paperclip run and source issue together with the confirmed control result. The
assigned `local-worker-run` invokes `checkpoint_collector.py`, declares the
checkpoint JSON as its required artifact, and uses no model or provider. The
collector validates the exact task/run/agent identity. A matching `paused`
receipt produces `pause.status = confirmed`; every other shape produces
`pause_unconfirmed`. Existing Paperclip continuation-summary text is preserved
as quoted observed evidence and is not parsed into claims. Completed work is
reported only from explicit mechanically verified records with stable evidence
references. Missing completed work, next work, or workspace-change evidence is
written as `unknown` rather than inferred.

Generated runtime material is kept beside the company control log under
`checkpoint-evidence/`, `checkpoints/`, and `checkpoint-dispatches.jsonl` and is
ignored by Git.

Paperclip currently has no supported central pre-resume/pre-turn hook that can
require a manually resumed cloud agent to read an arbitrary checkpoint artifact
before beginning new investigation. This implementation therefore creates the
durable checkpoint but does not claim resume enforcement. The smallest future
integration point is a server-owned addition to Paperclip's heartbeat-context
assembly that resolves the newest checkpoint for the task/run lineage and
includes it before provider invocation. Agent prompt edits and queued steering
comments are deliberately not used as substitutes.

AMBER is policy-selectable: `none` lets the current run continue, while `pause_agents` takes the same deterministic preventive pause. Runtime actions must align with the central active-work behavior (`finish_current` to `none`, `checkpoint_stop` to `pause_agents`), preventing two policy fields from giving contradictory directions. `behaviors.telemetryFailure` has no runtime action of its own because, by v1.1, a transient failure takes none; the action that eventually applies is the one configured for the state the retained reading resolves to, or for `unknown` once the window has elapsed. An orderly provider-generated checkpoint is not implemented because Paperclip has no reliable non-substantive checkpoint signal. RED and UNKNOWN are constrained to `pause_agents` when runtime control is enabled. The implementation does not patch the installed npm cache, alter live agent configuration, or create STOP tasks.

## Commands

Use the repository's bundled Python executable:

```powershell
.\Python\bin\python.exe .\.paperclip\quota-manager\quota_manager.py validate --policy .\.paperclip\quota-manager\companies\e6b7cf59-43ee-4b47-82b0-d1a3ed33b26e\policy.json
.\Python\bin\python.exe .\.paperclip\quota-manager\quota_manager.py observe --policy <policy> --state <state>
.\Python\bin\python.exe .\.paperclip\quota-manager\quota_manager.py enforce --policy <policy> --state <state> --events <events>
.\Python\bin\python.exe .\.paperclip\quota-manager\quota_manager.py monitor --policy <policy> --state <state>
.\Python\bin\python.exe .\.paperclip\quota-manager\quota_manager.py guard --provider anthropic --work new --policy <policy> --state <state>
```

`observe` performs one refresh. `enforce` performs one active-control pass. `monitor` repeats both using the configured interval when both monitoring and runtime control are enabled. None of these commands is scheduled or started by this change.

## Company policy values

Every operational value above is now supplied by the approved company policy and verified by `validate`. The five values Maya resolved last are the extra per-window reserve (0 percentage points), the provider quota probe timeout (30 seconds), the Paperclip active-run query timeout (10 seconds), the active-run result cap (50), and the agent-pause request timeout (15 seconds).

## Supervised monitor host

Maya approved a Windows Scheduled Task as the monitor host. The registered definition is kept in `host/quota-monitor-task.xml` so it is reproducible and auditable.

- Task: `\Paperclip\Quota Monitor`, running as the interactive desktop user at least privilege.
- Action: `Python/bin/pythonw.exe monitor-service.py --company <companyId>`. `monitor-service.py` is host plumbing only: it contributes no policy value, points the standard streams of the console-less `pythonw.exe` host at `companies/<companyId>/monitor.log` (rotated once at 1 MiB), and delegates to `quota_manager.py monitor`.
- Triggers: at logon, plus a daily trigger repeating every minute indefinitely. The repeating trigger is what restarts the monitor after an unexpected stop; a logon trigger alone does not, and neither does `RestartOnFailure` for an on-demand run.
- `MultipleInstancesPolicy` is `IgnoreNew`, so a repetition that fires while the monitor is healthy is refused instead of starting a second monitor. During normal operation the task's last result is therefore usually `0x800710E0` ("the operator or administrator has refused the request"). That is the expected steady state, not a failure.
- Battery and idle stops are disabled, and the execution time limit is unlimited, because a stopped monitor fails closed and blocks all cloud agent work.
- Reversal: delete the scheduled task. Nothing else on the host is modified.

Supervision is verified by stopping the monitor process and observing the scheduler start a new one within the 180-second stale threshold while state stays FRESH.

## Guarded launch seams

Paperclip starts an applicable agent through one of two engines, and they start
different programs, so each engine has its own wrapper and its own central
binding. Both wrappers deny without consuming a provider turn: the launch target
is never started when the decision is not ALLOW.

| Engine | Agent setting | Wrapper | Central binding |
|---|---|---|---|
| `cli` | `adapterConfig.command` | `host/bin/claude.cmd`, `host/bin/codex.cmd` | `providers.<p>.source.command` — the same binary the monitor probes |
| ACP (the adapter default) | `adapterConfig.agentCommand` | `host/bin/claude-agent-acp.cmd`, `host/bin/codex-acp.cmd` | `providers.<p>.launch.acp` — `command` (interpreter) and `module` (ACP server entry) |

`launch.acp` is an environment binding, not an approved policy value, so it is
optional in the schema and absent from `validate`'s required set. A missing or
moved ACP install therefore denies the launch (`LAUNCH_COMMAND_UNRESOLVED`,
exit 64) instead of being retried through PATH.

Two naming constraints are load-bearing, and a test asserts both:

- the CLI wrappers keep the basename `claude`/`codex`, because the Claude adapter
  applies its minimum-CLI-version preflight only when the configured command's
  basename is the provider's own;
- the ACP wrappers keep the basename `claude-agent-acp`/`codex-acp`, because acpx
  identifies an ACP lane by basename with the extension stripped, and only a
  recognized lane gets its provider-specific handling (for Claude, resolving
  `CLAUDE_CODE_EXECUTABLE`).

For the ACP engine, stdout carries the agent protocol (newline-delimited
JSON-RPC). `exec` therefore writes every diagnostic to stderr, which Paperclip
captures per run, so a denial is visible without being read as a protocol
message.

### ACP guard verification

`host/acp-guard-smoke.mjs` spawns a wrapper exactly as acpx does (a `.cmd`
command resolves to `shell: true`) and stops at `initialize`, so it consumes no
provider quota turn. Measured against the live wrappers:

- **stdio is transparent, on both lanes.** A full `initialize` handshake completed
  through each wrapper against a GREEN provider state — valid JSON-RPC responses,
  `protocolVersion` 1, and the real agent identities `@agentclientprotocol/claude-agent-acp`
  0.73.0 and `@agentclientprotocol/codex-acp` 1.13.1. In both cases the first byte
  on stdout was the protocol response and stderr was empty.
- **A denial never reaches the ACP server.** `claude-agent-acp.cmd` against a
  live UNKNOWN provider state exited 75 with **0 bytes on stdout** and the
  decision on stderr. No ACP server process was started.
- **Cancellation reclaims the whole tree.** The guard chain at steady state is
  `cmd.exe` → `python.exe` → the ACP server, one process deeper than the npm shim
  it replaces. Paperclip cancels by sending SIGKILL to the direct child it
  captured and nothing deeper, so this was measured rather than assumed: after
  that kill, every descendant was gone on both lanes — three for Claude, and all
  nine for Codex including `codex.exe` and both Node processes. Cleanup is driven
  by stdin EOF reaching the server, which the extra process layer preserves.

## Activation status

Live quota protection is active for `Implementation Engineer` and not yet applied
to the other five applicable agents.

**Applied (Maya-approved).** `Implementation Engineer` runs on the CLI engine, so
its `adapterConfig.command` now points at `host/bin/claude.cmd`. Nothing else in
its configuration changed. Maya approved this with the stated consequence: the
agent refuses to start whenever its provider state is not GREEN or the monitor is
down. That consequence has since been observed in production — see below.

**Built and verified, deliberately not applied.** The five remaining applicable
agents (`Product & Architecture Planner`, `Independent Reviewer`, `AI Model
Qualification Researcher`, `QA & Workflow Validation Engineer`, `QA Automation
Developer`) all run on the adapter's default ACP engine. Their wrappers now exist
and are verified (see **ACP guard verification** above), but pointing a live agent
at one is a change to live agent configuration that Maya asked to authorize
separately. The setting each needs is `adapterConfig.agentCommand` =
`host/bin/claude-agent-acp.cmd`, except `QA Automation Developer` (`codex_local`),
which needs `host/bin/codex-acp.cmd`.

The engines do not fall back to one another: when ACP is unavailable the run fails
with `adapter_engine_unavailable`. Each agent therefore has exactly one correct
guard seam, and a CLI wrapper is never a valid `agentCommand`.

## Observed fail-closed behavior

On 2026-10-07 the Claude `get_usage` probe began returning
`rate_limits_available: true` with `rate_limits: null` — a response with no usable
window, which this monitor classifies as UNKNOWN (see **Evidence-backed provider
sources**). Ten consecutive direct probes reproduced it. The approved policy
applied as written:

- new Claude work was denied (`host/bin/claude.cmd` → exit 75, `DENY UNAVAILABLE`);
- the active affected agent was preventively paused, recorded in
  `control-events.jsonl` as an intent/result pair with a confirmed receipt and
  `failureClassification: quota_manager_preventive_stop`;
- automatic resume stayed disabled, so the pause persists until a human clears it.

This is the policy behaving correctly, not a defect, and the classification is the
documented one. It does mean a transient provider-signal gap pauses affected
agents and requires a manual unpause. Note also that Paperclip records the pause
with `pauseReason: "manual"`; `control-events.jsonl` is the authoritative record
of why an agent was paused.

### Failed-probe diagnostics

Because that failure is intermittent and the investigation could not distinguish
Claude Code snapshot/cache behavior from upstream Anthropic telemetry, a failed
probe now preserves bounded structural evidence under
`providers.<provider>.error.diagnostic` so the next occurrence can be classified
without re-probing. The diagnostic is never a capacity input, never refreshes
`telemetry.lastTrustworthyAt`, and never changes a decision; `rate_limits: null`
remains `CLAUDE_LIMITS_UNAVAILABLE`.

Retained fields, by failure class:

| Field | Meaning |
| --- | --- |
| `rateLimitsAvailable` | The provider's `rate_limits_available` value, kept verbatim only when it is a boolean or number; any other type is reduced to its shape name. |
| `rateLimitsKind` | Shape of `rate_limits`: `null`, `object`, `array`, `string`, `number`, `boolean`, `absent`, or `invalid`. |
| `planWindows`, `planWindowUtilization` | Per-plan-window shape when `rate_limits` was an object with no usable window. |
| `jsonLines`, `controlResponses` | Counts of parsed stream-JSON lines and `control_response` messages. |
| `controlResponseSubtypes` | First 20 unique observed control-response subtypes, in encounter order. |
| `failureClassification` | Provider-supplied failure label from a non-success control response. |
| `successResponseKind` | Shape of the success payload: `null` when none arrived, otherwise the unusable shape. |
| `exitCode` | Probe process exit code. |
| `stderr` | Redacted, bounded stderr from the usage fetch. |
| `failureClass`, `errno` | Exception class and errno when the probe could not be launched. |

Secret safety and bounding are structural, not best-effort:

- stderr is drained on its own thread in fixed `STDERR_READ_CHUNK_SIZE` reads. Only
  the first `STDERR_CAPTURE_LIMIT` (8192) raw characters are accumulated; the rest
  is drained and discarded so an unterminated record cannot grow memory with its
  length and the child cannot block on a full pipe;
- the bounded raw prefix is reassembled before redaction, so credentials crossing
  arbitrary read boundaries are matched as one value. When the raw prefix reaches
  the capture limit, its incomplete trailing lexical span is conservatively
  replaced before pattern matching, preventing a credential crossing that boundary
  from surviving as a partial value;
- every retained free-text field passes through `redact()` before its final
  `bounded()` retention limit. Redacted shapes: `sk-`/`pk-`/`rk-` keys, JWTs, `Bearer`/`Basic`
  authorization, labelled credential assignments including underscored environment
  names such as `CLAUDE_CODE_MESSAGING_TOKEN=`, email addresses, long hex, and long
  base64 blobs;
- retained stderr is then truncated to `STDERR_DIAGNOSTIC_LIMIT` (1024 characters)
  and provider-supplied messages to `MESSAGE_DIAGNOSTIC_LIMIT` (200), each marked
  `...[truncated]`;
- values are recorded as shape names rather than contents, so the raw provider
  response — and anything inside it, such as account or token fields — is never
  persisted.

Capture is passive. No retry, recovery probe, or additional provider call was
added: a failed probe still results in exactly one process launch.
