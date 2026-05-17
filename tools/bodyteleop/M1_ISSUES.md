# Milestone 1 Tickets: Typed Commands Behind Current UI

This breaks Milestone 1 from [ROADMAP.md](./ROADMAP.md) into concrete GitHub-style issues tied to the current implementation.

## Scope

- Keep the current UI and routes working.
- Add one internal command path behind `web.py`.
- Make remote-start/charge/sentry command handling explicit.
- Avoid broad file-splitting or UI rewrites in this phase.

## Current Hot Spots

- `tools/bodyteleop/web.py`
  - Owns `COMMAND_PARAMS`, fake auth handlers, `api_status`, and `api_command`.
  - Also owns capture and video concerns that should stay untouched for now.
- `tools/bodyteleop/remote_startd.py`
  - Polls `LanRemoteStartRequested` and writes status through `Params`.
- `tools/bodyteleop/remote_start_status.py`
  - Owns current remote-start request/config/status helpers.
- `tools/bodyteleop/static/js/jsmain.js`
  - Calls `/api/status` and `/api/command/{name}` directly.

## Issue 1

**Title**
`teleop: inventory current command and status flow`

**Why**
We should document the live behavior before we insert a new command layer, otherwise cleanup later gets guessy.

**Files to inspect**
- [tools/bodyteleop/web.py](/C:/Users/msher/OneDrive/Desktop/Cursor projects/sunnypilot-clean/tools/bodyteleop/web.py:1)
- [tools/bodyteleop/remote_startd.py](/C:/Users/msher/OneDrive/Desktop/Cursor projects/sunnypilot-clean/tools/bodyteleop/remote_startd.py:1)
- [tools/bodyteleop/remote_start_status.py](/C:/Users/msher/OneDrive/Desktop/Cursor projects/sunnypilot-clean/tools/bodyteleop/remote_start_status.py:1)
- [tools/bodyteleop/static/js/jsmain.js](/C:/Users/msher/OneDrive/Desktop/Cursor projects/sunnypilot-clean/tools/bodyteleop/static/js/jsmain.js:1)

**Tasks**
- List every command exposed by `/api/command/{name}`.
- Record which `Params` keys each command mutates today.
- Record which status fields the UI reads today.
- Note which flows are synchronous responses vs async status polling.

**Acceptance**
- One short doc or issue comment exists with the current command matrix.
- Remote start, charge start/stop, and sentry toggle all have current-state notes.

## Issue 2

**Title**
`teleop: define internal command service contract`

**Why**
Before moving behavior, we need one typed internal shape for command submission and outcomes.

**Primary files**
- [tools/bodyteleop/web.py](/C:/Users/msher/OneDrive/Desktop/Cursor projects/sunnypilot-clean/tools/bodyteleop/web.py:1)
- New module: `tools/bodyteleop/command_service.py`

**Tasks**
- Define a typed internal request model for:
  - `remote_start`
  - `charge_start`
  - `charge_stop`
  - `sentry_toggle`
- Define a typed internal result model with fields like:
  - `command`
  - `accepted`
  - `state`
  - `reason`
  - `updated_at`
  - `details`
- Decide whether to use `dataclass`es, typed dicts, or both.
- Document which parts are Milestone 1 internal-only and which are future `cereal` candidates.

**Acceptance**
- `command_service.py` exists with typed request/result structures.
- The contract is usable from `web.py` without changing the UI payload shape.

## Issue 3

**Title**
`teleop: add command_service behind api_command`

**Why**
`api_command` currently mixes validation, param writes, remote-start config shaping, and direct side effects in one handler.

**Primary files**
- [tools/bodyteleop/web.py](/C:/Users/msher/OneDrive/Desktop/Cursor projects/sunnypilot-clean/tools/bodyteleop/web.py:281)
- New module: `tools/bodyteleop/command_service.py`

**Tasks**
- Move command parsing/validation out of `api_command`.
- Add one service entrypoint like `execute_command(name, payload, params, now=time.time())`.
- Keep the route `/api/command/{name}` and current response behavior compatible enough for `jsmain.js`.
- Return explicit result objects rather than raw ad hoc dicts from branch code.

**Acceptance**
- `api_command` becomes a thin HTTP wrapper.
- All four supported commands go through the same service entrypoint.
- The current frontend keeps working unchanged.

## Issue 4

**Title**
`teleop: route remote_start through typed command result handling`

**Why**
Remote start is the best first migration because it already has config, async status, and a dedicated worker, which exposes the current design weaknesses clearly.

**Primary files**
- [tools/bodyteleop/web.py](/C:/Users/msher/OneDrive/Desktop/Cursor projects/sunnypilot-clean/tools/bodyteleop/web.py:281)
- [tools/bodyteleop/remote_startd.py](/C:/Users/msher/OneDrive/Desktop/Cursor projects/sunnypilot-clean/tools/bodyteleop/remote_startd.py:1)
- [tools/bodyteleop/remote_start_status.py](/C:/Users/msher/OneDrive/Desktop/Cursor projects/sunnypilot-clean/tools/bodyteleop/remote_start_status.py:1)

**Tasks**
- Normalize the incoming remote-start payload into one typed config object.
- Return an explicit accepted/requested result from `command_service`.
- Centralize the initial `"requested"` status write in one place.
- Leave the worker transport alone in Milestone 1, but make the command path look like the future architecture.

**Acceptance**
- Remote-start submission no longer has bespoke handler logic living directly in `api_command`.
- The UI still shows remote-start progress through `/api/status`.
- Follow-up Milestone 2 work can swap the transport without reworking the HTTP layer again.

## Issue 5

**Title**
`teleop: route charge and sentry commands through command_service`

**Why**
Even the simple commands should use the same path now, or we’ll immediately re-create two architectures.

**Primary files**
- [tools/bodyteleop/web.py](/C:/Users/msher/OneDrive/Desktop/Cursor projects/sunnypilot-clean/tools/bodyteleop/web.py:281)
- [tools/bodyteleop/static/js/jsmain.js](/C:/Users/msher/OneDrive/Desktop/Cursor projects/sunnypilot-clean/tools/bodyteleop/static/js/jsmain.js:114)

**Tasks**
- Move charge start/stop param toggle behavior behind `command_service`.
- Move sentry-toggle behavior behind `command_service`.
- Normalize success/error responses so the UI can treat commands consistently.

**Acceptance**
- Charge start, charge stop, remote start, and sentry toggle all share one internal backend path.
- `jsmain.js` does not need command-specific branching beyond building the remote-start payload.

## Issue 6

**Title**
`teleop: add command audit logging and result surfacing`

**Why**
If commands become explicit, we should be able to see who requested what and what happened, even before `cereal` messaging exists.

**Primary files**
- [tools/bodyteleop/web.py](/C:/Users/msher/OneDrive/Desktop/Cursor projects/sunnypilot-clean/tools/bodyteleop/web.py:281)
- New module: `tools/bodyteleop/command_service.py`

**Tasks**
- Log command submission with command name and safe summary fields.
- Log command acceptance/rejection consistently.
- Surface enough state in `/api/status` for the current UI to reflect outcomes cleanly.
- Avoid logging secrets or oversized payload blobs.

**Acceptance**
- Every command has a consistent log trail.
- Status responses can represent command outcomes explicitly enough for the UI.

## Issue 7

**Title**
`teleop: add tests for command_service behavior`

**Why**
Milestone 1 is about correctness first. The command layer should be testable before we start deeper transport changes.

**Primary files**
- New test module under the repo’s existing Python test conventions
- `tools/bodyteleop/command_service.py`

**Tasks**
- Add unit tests for:
  - unknown command rejection
  - remote-start payload normalization
  - charge start/stop command dispatch
  - sentry-toggle behavior
- Mock `Params` interactions rather than depending on device-only state.

**Acceptance**
- The new command layer has focused tests.
- Regression risk is lower before Milestone 2 begins.

## Suggested Order

1. Issue 1: inventory current flow
2. Issue 2: define internal command contract
3. Issue 3: add `command_service` behind `api_command`
4. Issue 4: route remote start through typed command handling
5. Issue 5: route charge and sentry through `command_service`
6. Issue 6: add audit logging and status surfacing
7. Issue 7: add tests

## Not In This Milestone

- Replacing `Params` triggers with `cereal` transport
- Splitting capture/video code into separate modules
- Real auth
- Breaking up `web.py` into gateway + services
- UI redesign

Those come later on purpose. This milestone should make the backend command path more explicit without forcing a risky rewrite.
