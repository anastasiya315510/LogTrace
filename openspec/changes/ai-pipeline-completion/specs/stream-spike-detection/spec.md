# Spec Delta

## Purpose

Continuously monitors per-service Redis Streams and automatically creates a submission
when an error spike or critical event is detected, so that incident analysis begins
without any human action.

## ADDED Requirements

### Requirement: Consume Redis Streams with consumer group

The system SHALL read all `stream:ingest:{service}` Redis Streams using XREADGROUP with
a named consumer group, so that each event is processed exactly once and unacknowledged
messages are recoverable on restart.

#### Scenario: Events consumed and acknowledged
- **WHEN** events exist on a `stream:ingest:{service}` stream
- **THEN** the processor reads them via XREADGROUP and ACKs each after processing

#### Scenario: New services discovered automatically
- **WHEN** a new `stream:ingest:{service}` stream appears
- **THEN** the processor joins it within one discovery interval without restart

### Requirement: Single-service error-rate spike triggers a submission

The system SHALL trigger a submission when a single service produces ≥ 10 ERROR or
CRITICAL events within a rolling 60-second window.

#### Scenario: Spike threshold crossed
- **WHEN** service `payment-service` emits 10 ERROR events within 60 seconds
- **THEN** a Submission row is inserted with `source_method = "auto_trigger"` and Stage-1 is dispatched

#### Scenario: Below threshold — no trigger
- **WHEN** a service emits 9 ERROR events within 60 seconds
- **THEN** no submission is created

### Requirement: CRITICAL event triggers a submission immediately

The system SHALL trigger a submission for any service the moment a CRITICAL-level event
is received.

#### Scenario: CRITICAL event received
- **WHEN** any event with `level = "CRITICAL"` arrives on any stream
- **THEN** a submission is created immediately without waiting for the spike window

### Requirement: Cross-service error-type spike triggers a submission

The system SHALL trigger a submission when the same `error_type` value appears in
three or more distinct services within a 30-second window.

#### Scenario: Same error type across services
- **WHEN** `PoolTimeoutError` appears in `payment-service`, `order-service`, and
  `api-gateway` within 30 seconds
- **THEN** a single submission is created

### Requirement: Per-service debounce prevents duplicate submissions

The system SHALL not trigger a second submission for the same service within 120 seconds
of a prior trigger.

#### Scenario: Rapid consecutive spikes
- **WHEN** a service triggers at t=0 and another spike occurs at t=90s
- **THEN** the second spike is suppressed; no additional submission is created

#### Scenario: Debounce window expired
- **WHEN** a service triggered at t=0 and a new spike occurs at t=125s
- **THEN** a new submission is created

### Requirement: Demo state updated on auto-trigger

The system SHALL set `demo:state.auto_triggered = 1` and store the `submission_id` in
`demo:state` when an auto-triggered submission is created.

#### Scenario: Demo state reflects trigger
- **WHEN** an auto-trigger fires during an active demo session
- **THEN** `GET /demo/status` returns `auto_triggered: true` and the correct `submission_id`