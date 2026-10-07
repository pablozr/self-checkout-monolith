---
date: 2026-04-02
topic: "Stripe webhook normalization"
status: validated
---

## Problem Statement

The Stripe webhook path verifies signatures correctly but fails after event construction when it tries to persist `event["data"]["object"]` into `stripe_events.event_object`.

The immediate issue is a runtime type mismatch: the service assumes a plain JSON-serializable dictionary, while Stripe returns SDK objects that support mapping-style access but are not safe to hand directly to `json.dumps(...)`.

## Constraints

- `stripe_events.event_object` is `JSONB NOT NULL`, so persisted payloads must be valid JSON.
- Dedupe registration and business updates intentionally share one database transaction.
- Redis/SSE publication must remain post-transaction.
- The service layer owns orchestration and direct SQL in this codebase; we are not introducing a repository abstraction.
- The fix must preserve current webhook semantics for supported Stripe event types and duplicate-event handling.

## Approach

We will normalize the Stripe event payload at the service boundary immediately after `stripe.Webhook.construct_event(...)` and before any persistence or dispatch logic.

I chose this because it fixes the real bug once, aligns runtime behavior with the service's existing dict-based contracts, and avoids scattering Stripe-SDK-specific handling across persistence, parsing, and dispatch.

I considered two alternatives and rejected both:

- Converting only inside `_register_event`: too narrow, because `_dispatch_event` and `_parse_checkout_data` would still operate on SDK objects while claiming to consume dictionaries.
- Using permissive JSON serialization like `default=str`: too lossy, because it can silently flatten nested provider data into strings and weaken both auditing and future event handling.

## Architecture

The webhook service keeps the same high-level shape: verify, normalize, register, dispatch, then publish.

The only architectural change is a new normalization boundary between Stripe SDK output and our internal service contract. After that boundary, the rest of the flow works exclusively with plain JSON-native Python structures.

## Components

**Webhook route:**

- Reads raw request body and Stripe signature header.
- Delegates unchanged payload bytes to the service.
- Continues mapping service envelopes to HTTP 200, 400, and 500.

**Webhook service orchestrator:**

- Verifies the signature with Stripe.
- Normalizes the Stripe event tree into plain dictionaries, lists, strings, numbers, booleans, and nulls.
- Opens the transaction and coordinates dedupe registration plus business dispatch.
- Publishes the admin event only after a successful commit.

**Event registration step:**

- Persists the normalized event object into `stripe_events.event_object`.
- Preserves `ON CONFLICT (event_id) DO NOTHING` dedupe behavior.
- Continues acting as the first transactional gate before domain updates.

**Dispatch and validation path:**

- Consumes the normalized event object, not Stripe SDK objects.
- Reuses existing metadata parsing and DB reconciliation flow.
- Preserves current payment and order transition rules.

**Tests:**

- Expand service-level coverage so realistic Stripe-shaped objects are normalized before persistence.
- Keep existing duplicate-event and transition tests, but anchor them on the normalized contract.

## Data Flow

1. The route receives raw webhook bytes and the Stripe signature header.
2. The service verifies the webhook with Stripe.
3. The verified Stripe event is normalized into plain JSON-compatible structures.
4. The service extracts `event_id`, `event_type`, and the normalized `data.object` payload.
5. Inside one transaction, the normalized object is inserted into `stripe_events` for dedupe and audit.
6. If the event is new, the normalized payload is parsed and validated against current payment and order state.
7. Domain updates are applied to `payments` and `orders`.
8. After commit, the admin SSE event is published.

This keeps the current transaction boundary intact while making the input contract explicit and safe.

## Error Handling

We will separate provider-shape problems from internal failures more clearly.

**Expected invalid input:**

- Bad signatures remain an explicit invalid-signature path.
- Missing or malformed normalized metadata remains a `ValueError` path and returns a client-facing 400-style service error.

**Unexpected internal failures:**

- Serialization or database issues remain generic internal errors with exception logging.
- Transaction rollback behavior remains unchanged, so partial state changes are still prevented.

**Operational outcome:**

- A successfully verified and normalized webhook should no longer fail before dedupe registration.
- Stripe retries should drop sharply because legitimate events stop returning 500 due to serialization.

## Testing Strategy

We will verify the fix at three levels.

**Service tests:**

- Confirm Stripe SDK event/object input is normalized before persistence.
- Confirm the persisted payload is JSON-serializable and preserves nested provider fields.
- Confirm invalid normalized metadata still fails through the current validation path.

**Integration tests:**

- Re-run webhook peak tests for duplicate-event mode and unique-event mode.
- Verify duplicates short-circuit cleanly after the first insert.
- Verify unique events update DB state and return success instead of 500.

**Regression checks:**

- Re-run the full pytest suite.
- Re-run the documented webhook load-test commands with the real webhook payload template.
- Re-check API logs for unexpected fallback exceptions.

## Open Questions

There are no design blockers.

The only follow-up question is performance quality after correctness is restored: once webhooks stop failing, we should measure whether 100-request unique-event throughput is acceptable or whether the bottleneck shifts to database locking or downstream updates.
