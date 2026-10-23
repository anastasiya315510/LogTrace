# Spec Delta

## Purpose

Produces a structured incident report for each correlated incident by classifying
events with Nemotron Nano 8B, generating a root-cause analysis with Nemotron Ultra
253B via streaming, fetching fix suggestions from Tavily, and persisting the full
report so engineers can also ask follow-up questions and export the findings.

## ADDED Requirements

### Requirement: Classify events in parallel batches with Nemotron Nano 8B

The system SHALL classify all LogEvents for an incident by sending them to Nemotron
Nano 8B in batches of up to 20, with up to 10 concurrent requests.

#### Scenario: Classification succeeds
- **WHEN** an incident has 40 events
- **THEN** 2 batches of 20 are sent concurrently and each event receives a category label

#### Scenario: Malformed Nano response handled gracefully
- **WHEN** the Nano API returns invalid JSON or a response whose array length does not
  match the batch size
- **THEN** affected events are marked `noise`/`unknown` and processing continues without
  raising an exception

### Requirement: Generate root-cause analysis with Nemotron Ultra 253B via streaming

The system SHALL call Nemotron Ultra 253B with full incident context and stream the
response token-by-token to the SSE channel for the submission.

#### Scenario: Tokens forwarded in real time
- **WHEN** Ultra begins generating a response
- **THEN** each token is published to `sse:submission:{submission_id}` and appears in the
  SSE stream within 200 ms of generation

#### Scenario: Structured JSON block extracted
- **WHEN** Ultra completes its response containing a `<ANALYSIS_JSON>` block
- **THEN** the fields `root_cause_service`, `root_cause_method`, `confidence_score`,
  `cascade_chain`, and `alternative_hypotheses` are parsed and stored on IncidentAnalysis

### Requirement: Fetch fix suggestions from Tavily

The system SHALL issue two Tavily queries per incident — one for remediation, one for
known vulnerabilities — and store the top 3 deduplicated results by score.

#### Scenario: Suggestions stored
- **WHEN** Tavily returns results for both queries
- **THEN** results are deduplicated by URL, sorted by `tavily_score` descending, and the
  top 3 are stored as FixSuggestion rows

#### Scenario: Tavily failure handled gracefully
- **WHEN** both Tavily queries fail or time out
- **THEN** the incident report is still delivered with an empty fix-suggestions list;
  no error propagates to the caller

### Requirement: Publish completion sentinel on SSE channel

The system SHALL publish a `__DONE__` sentinel to `sse:submission:{submission_id}` after
all Stage-2 steps complete, and update the Incident status to `complete`.

#### Scenario: SSE stream closes cleanly
- **WHEN** Stage-2 finishes
- **THEN** the SSE endpoint receives `__DONE__`, yields the final `complete` event, and
  closes the stream

### Requirement: Support interactive Q&A backed by Ultra 253B

The system SHALL accept follow-up questions about a completed incident and stream
answers token-by-token, maintaining conversation history across turns (max 20 turns).

#### Scenario: Question answered with streaming response
- **WHEN** `POST /api/v1/incidents/{id}/chat` receives a question for a completed incident
- **THEN** the response streams tokens as SSE and the full answer is appended to
  `conversation_history_json`

#### Scenario: History capped at 20 turns
- **WHEN** the conversation reaches 20 turns (40 messages)
- **THEN** the oldest turns are discarded so the history stays within the cap

#### Scenario: Incomplete incident rejected
- **WHEN** a chat request arrives for an incident whose status is not `complete`
- **THEN** the endpoint returns HTTP 400

### Requirement: Export incident report as Markdown

The system SHALL serve a downloadable Markdown report for any complete incident.

#### Scenario: Markdown file returned
- **WHEN** `GET /api/v1/incidents/{id}/export` is called for a complete incident
- **THEN** the response has `Content-Type: text/markdown` and `Content-Disposition:
  attachment`, and includes the root cause, confidence score, cascade chain, analysis
  text, and fix suggestions