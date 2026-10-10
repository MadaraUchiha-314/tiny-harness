# Decision 003: No authentication inside tiny-harness in the first release

- **Status:** proposed (accepted when the issue-3 design is approved)
- **Date:** 2026-10-09
- **Deciders:** @MadaraUchiha-314 (approver), the-loop (proposer)
- **Work item:** [issue #3](https://github.com/MadaraUchiha-314/tiny-harness/issues/3)

## Context

The requirements raised which A2A security scheme the demo should require. The approver
answered that enterprises deploy the harness behind their own authentication, that
authentication should not be the focus of this work item, and that requests are assumed
unauthenticated for now, with A2A's standard mechanism to be used later.

## Decision

- The A2A server declares no security scheme in its agent card and performs no
  authentication or authorization of requests.
- The deployment documentation states that the server must sit behind an
  authenticating perimeter (gateway or reverse proxy) and must not be exposed directly.
- Participant identity on channels and tasks is carried in message metadata and is
  self-asserted; membership checks use it as given.
- The integration point for the future is the A2A SDK's security-scheme declaration and
  server call context (the authenticated user it carries), so adding authentication
  later touches the server adapter and the participant resolver, not the core.

## Consequences

- Every other trust boundary (tool registry, plugin paths, schema validation, secret
  redaction, channel membership) is enforced as designed; only the ingress identity is
  delegated to the perimeter.
- Abuse case 1 of the requirements (unauthenticated client) is defeated by the
  perimeter, not by the harness, and the testing plan records it as such.
- A deployment without a perimeter is insecure by construction; the docs say so.

## Alternatives considered

- **API key header declared in the card** — small to build, but the approver wants no
  authentication code in this release.
- **OAuth2 or mTLS** — enterprise mechanisms the perimeter already provides.
