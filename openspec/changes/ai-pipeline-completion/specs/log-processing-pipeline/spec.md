# Spec Delta

## Purpose

Transforms raw log events from Redis Streams or object storage into structured Incident
rows with correlated events and a service dependency topology, ready for AI analysis.

## ADDED Requirements

### Requirement: Parse JSON-formatted log lines

The system SHALL parse JSON log lines into LogEvent rows, mapping known fields and
placing unrecognised keys into a `metadata` JSONB column.

#### Scenario: Full-schema JSON event
- **WHEN** a JSON line contains `timestamp`, `level`, `service`, `message`, `trace_id`,
  `error_type`, and `stack_trace`
- **THEN** all fields map to the corresponding LogEvent columns with no data loss

#### Scenario: Partial JSON event
- **WHEN** a JSON line omits optional fields such as `trace_id`
- **THEN** the event is accepted with those fields set to NULL; no exception is raised

#### Scenario: Malformed JSON line
- **WHEN** a line cannot be parsed as JSON
- **THEN** the line is skipped and recorded as a parse warning; processing continues

### Requirement: Parse plaintext log lines via pattern matching

The system SHALL parse plaintext log lines using at least two regex patterns covering
common timestamp-level-message layouts.

#### Scenario: Standard plaintext format parsed
- **WHEN** a line matches `[TIMESTAMP] LEVEL SERVICE: MESSAGE`
- **THEN** the event is parsed into a LogEvent with the correct fields

#### Scenario: Unrecognised format skipped gracefully
- **WHEN** a line matches no known pattern
- **THEN** the line is skipped with a warning; remaining lines continue to be parsed

### Requirement: Log level normalised to uppercase

The system SHALL normalise all `level` values to uppercase (e.g. `warning` → `WARN`,
`error` → `ERROR`) before storing the LogEvent.

#### Scenario: Mixed-case level normalised
- **WHEN** an event has `level = "Warning"`
- **THEN** the stored LogEvent has `level = "WARN"`

### Requirement: Correlate events that share a trace ID

The system SHALL group events that share a `trace_id` into a single Incident.

#### Scenario: Shared trace ID produces one incident
- **WHEN** 10 events from different services share the same `trace_id`
- **THEN** exactly one Incident row is created containing all 10 events

#### Scenario: Events without trace IDs fall through to time-window correlation
- **WHEN** none of the ERROR/CRITICAL events carry a `trace_id`
- **THEN** the time-window correlator is used instead of trace-ID grouping

### Requirement: Correlate events within a configurable time window

The system SHALL group ERROR and CRITICAL events that occur within a configurable
sliding time window (default 30 seconds) into Incident rows.

#### Scenario: Events in window grouped
- **WHEN** 6 ERROR events occur within 30 seconds across services
- **THEN** they are grouped into one Incident

#### Scenario: Events outside window form separate incidents
- **WHEN** 4 ERROR events occur at t=0 and 4 others at t=120s
- **THEN** two separate Incident rows are created

#### Scenario: Duplicate events within 1 second deduplicated
- **WHEN** the same service emits identical message+level 3 times within 1 second
- **THEN** only one copy is retained in the Incident

### Requirement: Infer service dependency topology

The system SHALL build a directed service dependency graph from correlated events,
assign each node a role, and store the result as `service_topology_json` on the Incident.

#### Scenario: Chain topology detected
- **WHEN** errors appear in `payment-service`, then `order-service`, then `api-gateway`
  within a 5-second sliding window
- **THEN** the topology JSON contains edges `payment-service→order-service` and
  `order-service→api-gateway`, with `payment-service` assigned `root_cause`

#### Scenario: Role assignment by in-degree
- **WHEN** a service has in-degree 0 (or the earliest ERROR timestamp)
- **THEN** its role is `root_cause`; depth-1 nodes are `propagated_error`; deeper nodes
  are `symptom`

#### Scenario: Cycle detected and broken
- **WHEN** the inferred edges form a cycle
- **THEN** the lowest-weight edge is removed so the graph remains a DAG

#### Scenario: Single-service incident
- **WHEN** all events belong to one service
- **THEN** the topology contains exactly one node with no edges

### Requirement: Dispatch Stage-2 for each created Incident

The system SHALL enqueue a Stage-2 job for every Incident it creates.

#### Scenario: Stage-2 dispatched after incident creation
- **WHEN** Stage-1 inserts an Incident row
- **THEN** the incident ID is placed on the analysis queue so Stage-2 picks it up