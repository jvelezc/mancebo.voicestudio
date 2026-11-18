# Mancebo managed studio

Status: **staged integration, not a published customer service**. The Mancebo
marketing guides distinguish the available preset library from the pending full
studio. This change does not make cloning, design or dubbing available through
the customer API, MCP or Hermes.

## Why this mode exists

Mancebo customers already have a workspace and sign-in. Asking them for the
underlying studio's operator key or network PIN creates a second account system
and does not establish workspace isolation. Hosted mode uses the original
studio interface with Mancebo branding and a session issued by Mancebo.

## What the renderer accepts

The authenticated gateway supplies a display-only `window.__MANCEBO_STUDIO__`
object containing a canonical `workspaceId`, `canOperate` and `platformAdmin`.
It also sets the existing `window.__OMNIVOICE_API_BASE__` to exactly
`https://api.mancebo.ai/studio/workspaces/{workspaceId}`. The web page must itself
be served from `https://api.mancebo.ai`. These values contain no credential.

Desktop and ordinary web installations stay standalone when this explicit
bootstrap is absent. Invalid managed metadata stops the managed launch; it
never falls back to asking for an operator key. The branding includes a visible
link to this fork's source at the actual build revision; upstream attribution,+licenses and standalone behavior remain intact.

Display flags do not authorize a request. The gateway must verify current
Mancebo membership and operation permissions independently on every request.
The worker's own credential remains server-side and must not enter a URL,
browser bundle, local storage or customer instructions.

## How sign-in and recovery work

1. The Mancebo parent page uses its existing signed-in Edge/Core boundary to
   request a short-lived, single-use launch for the selected workspace.
2. The gateway rechecks current identity, redeems the launch and sets its
   workspace-specific, host-only, Secure/HttpOnly session cookie.
3. The native renderer calls `/mancebo/session` under its exact workspace API
   prefix. It opens the studio only when that response names the same workspace
   and explicitly reports `execution_available: true`. Liveness alone is insufficient.
4. Expired or revoked access shows a Mancebo recovery action, without an API-key
   or PIN field. An embedded renderer sends only the message type and workspace
   ID to the exact `https://mancebo.ai` parent. The parent must verify the frame's
   source, origin and current selected workspace before repeating its launch.
5. A previous in-flight success cannot reopen a session after a newer expiry
   event. Repeated expiry events request only one automatic reconnection; an
   explicit retry can ask again. Network failures show a retry action.

The planned return route is `https://mancebo.ai/voice-studio?business={workspace}`.
That route, the session alias, native HTTP/WebSocket proxy, persistent work,
typed customer APIs/MCP and full Mancebo launch are still pending qualification.
Do not inject the managed bootstrap into a publicly exposed standalone server
and assume it supplies these server boundaries.

## Before enabling a workspace

Use distinct worker processes, private data/database roots, uploads, voices,
projects and artifacts. Share only immutable approved model weights. Customer
users must not acquire platform installation, global settings, filesystem or
operator authority through the native UI or its API.

Qualify actual installed models, reference consent, two speakers, translation,
review, export/download, interruption/recovery and cross-workspace refusal.
Return real results and authorized downloads. Preserve the existing preset
speech service. The [native CPU engine](engines/qwen-native.md) is an independent
runtime capability; a successful short sample is not full hosted acceptance.

Use Mancebo's existing customer key or managed organization connection for
qualified external-assistant tools. Discover the current capability contract
before choosing an operation. The existing `voicestudio.speak` tool supports
presets and must not be described as cloning or dubbing.
