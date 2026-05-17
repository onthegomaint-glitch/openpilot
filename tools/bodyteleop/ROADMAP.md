# Body Teleop V2 Roadmap

This roadmap is organized to preserve the current UI first, improve correctness before structure, and treat legacy cleanup as deliverable work instead of "later".

## Migration Order

This work should not be rewritten all at once. It should happen in this order:

1. Keep the current UI, but add a typed `command_service` behind `web.py`.
2. Replace param-trigger commands with `cereal` command/result messages.
3. Move video/capture code into separate modules.
4. Make auth real.
5. Split `web.py` into gateway + services once the contracts settle.

That sequencing is intentional: improve correctness first, then structure.

## Guiding Principles

- Keep the current UI working during early phases.
- Prefer typed command/status contracts over param toggles.
- Migrate one feature at a time.
- Delete old paths as soon as replacements are stable.
- Treat cleanup as a tracked milestone, not a background task.

## Milestone 1: Typed Commands Behind Current UI

Goal: improve correctness without rewriting the frontend.

Scope:

- Keep the current UI and routes working.
- Add a typed `command_service` behind `web.py`.
- Define internal command, ack, result, and status contracts.
- Route current button actions through the new command layer.
- Add audit logging for command submission and completion.

Suggested issues:

- `teleop: define typed teleop command/result schemas`
- `teleop: add command_service behind web.py`
- `teleop: route remote start through command_service`
- `teleop: route charge start/stop through command_service`
- `teleop: route sentry toggle through command_service`
- `teleop: add audit logging for teleop commands`

Exit criteria:

- The current UI works unchanged.
- Command submission has one internal path.
- Command outcomes are represented explicitly, not inferred ad hoc.

## Milestone 2: Replace Param Triggers With Cereal Messaging

Goal: remove fragile command triggering.

Scope:

- Replace param-toggle command flow with typed `cereal` messages.
- Update workers to consume typed requests and publish typed results.
- Add timeout, failure reason, and retry-aware handling.
- Preserve existing user-visible behavior while changing the transport.

Suggested issues:

- `teleop: add TeleopCommand cereal message`
- `teleop: add TeleopCommandAck cereal message`
- `teleop: add TeleopCommandResult cereal message`
- `teleop: migrate remote_startd from Params trigger to cereal`
- `teleop: migrate charge controls from Params trigger to cereal`
- `teleop: migrate sentry control from Params trigger to cereal`
- `teleop: expose command result state in status responses`

Cleanup issues:

- `teleop: remove LanRemoteStartRequested trigger path`
- `teleop: remove legacy command param toggles after cereal migration`

Exit criteria:

- No privileged command depends on toggling params to fire.
- Workers consume typed requests and emit typed outcomes.
- The UI receives reliable success/failure state.

## Milestone 3: Extract Video And Capture Modules

Goal: separate non-command features from the control path.

Scope:

- Move video library code into a focused module or service.
- Move capture job logic into a focused module or service.
- Keep API compatibility where practical during transition.
- Reduce the responsibility of `web.py`.

Suggested issues:

- `teleop: extract video library module`
- `teleop: extract video stream/protect/delete handlers`
- `teleop: extract capture job manager`
- `teleop: move capture subprocess lifecycle into manager`
- `teleop: unify capture and library status reporting`

Cleanup issues:

- `teleop: remove direct capture bookkeeping from web.py`
- `teleop: remove file-management helpers from the gateway path`

Exit criteria:

- Video and capture logic are no longer embedded in the main teleop handler file.
- Command/control code is clearly separate from library and job management code.

## Milestone 4: Make Auth Real

Goal: secure the system before expanding or polishing it.

Scope:

- Replace fake auth endpoints with real LAN auth and session handling.
- Add permission tiers for viewer, operator, and admin-style access.
- Gate privileged commands separately from read-only status/media access.
- Add pairing, session expiry, and audit logging.

Suggested issues:

- `teleop: design LAN auth and session model`
- `teleop: implement real auth status/setup/login/logout flows`
- `teleop: add role/permission checks for privileged commands`
- `teleop: gate video deletion and control actions by permission`
- `teleop: add session and CSRF protections for browser clients`

Cleanup issues:

- `teleop: remove always-authenticated backend behavior`
- `teleop: remove auth-disabled UI copy`
- `teleop: remove dead auth config shims after auth rollout`

Exit criteria:

- Privileged actions require real authentication.
- Fake auth code is gone.
- Local-network-only is no longer the only protection.

## Milestone 5: Split web.py Into Gateway + Services

Goal: improve structure once contracts are stable.

Scope:

- Split `web.py` into a thin gateway plus focused services.
- Keep `webrtcd` for media transport, but isolate media setup logic.
- Formalize service boundaries for gateway, commands, status, media, and library.
- Refactor the frontend to talk to stable APIs instead of implementation quirks.

Suggested issues:

- `teleop: create gateway module from web.py`
- `teleop: create status service`
- `teleop: create media service wrapper around webrtcd`
- `teleop: create library service`
- `teleop: split frontend into commands/status/media/library clients`
- `teleop: document service boundaries and request flows`

Cleanup issues:

- `teleop: remove monolithic route ownership from web.py`
- `teleop: remove duplicate helpers after service extraction`
- `teleop: remove direct testJoystick assumptions from UI where possible`

Exit criteria:

- `web.py` is no longer a god-file.
- Each feature area has one backend owner.
- Frontend code depends on stable contracts, not backend internals.

## Milestone 6: Legacy Code Removal Sweep

Goal: complete the migration by actually deleting the old world.

Scope:

- Audit old routes, params, helpers, modules, JS paths, and compatibility shims.
- Remove dead code immediately once replacements are live.
- Verify no stale callers remain.
- Reduce long-term maintenance surface.

Suggested issues:

- `teleop: inventory remaining legacy routes and shims`
- `teleop: remove deprecated command handlers`
- `teleop: remove unused auth/config helpers`
- `teleop: remove stale frontend branches and controls`
- `teleop: run final grep audit for legacy teleop paths`
- `teleop: add tests covering only the new architecture`

Exit criteria:

- No duplicate control path exists for the same feature.
- No deprecated endpoint remains wired into the UI.
- No compatibility shim survives without an explicit reason.

## Concrete Cleanup Targets

Track these explicitly so cleanup does not get lost:

- Fake auth endpoints in `tools/bodyteleop/web.py`
- "Auth disabled" UI state in `tools/bodyteleop/static/index.html`
- Param-toggle command flow in `tools/bodyteleop/web.py`
- Old remote start trigger flow in `tools/bodyteleop/remote_startd.py`
- Monolithic route ownership in `tools/bodyteleop/web.py`
- Direct `testJoystick` wire format coupling in `tools/bodyteleop/static/js/webrtc.js`

## GitHub Project Board Layout

Suggested columns:

- `Backlog`
- `Ready`
- `In Progress`
- `Review`
- `Cleanup`
- `Done`

Suggested label set:

- `teleop`
- `roadmap`
- `security`
- `frontend`
- `backend`
- `cereal`
- `cleanup`
- `migration`
- `breaking-change`

Suggested milestone labels:

- `M1 typed-commands`
- `M2 cereal-messaging`
- `M3 video-capture-extraction`
- `M4 auth`
- `M5 gateway-services-split`
- `M6 legacy-removal`

## Recommended Execution Pattern

For each feature:

1. Build the replacement path.
2. Migrate one caller or feature at a time.
3. Verify behavior and logs.
4. Delete the old path immediately after stabilization.

This avoids carrying "temporary" compatibility code for months.
