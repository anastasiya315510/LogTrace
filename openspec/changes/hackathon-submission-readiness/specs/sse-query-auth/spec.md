# Spec: SSE Query Auth

## Purpose

The SSE stream progress endpoint must be accessible to browser-native `EventSource` clients, which cannot send custom HTTP headers. The endpoint must accept the API key as a URL query parameter as an alternative authentication method.

## Requirements

### Authentication on the stream endpoint

- `GET /api/v1/submissions/{submission_id}/stream` MUST authenticate using either:
  - `X-API-Key` request header (existing behaviour, unchanged), OR
  - `?api_key=<value>` URL query parameter (new)
- When both are present, the header takes precedence.
- When neither is present, the endpoint returns HTTP 401.
- A missing or invalid value in either location returns HTTP 401.
- The key validation logic (SHA-256 hash + Redis cache + DB lookup) is identical regardless of how the key is supplied.

### Scope

- Query parameter auth applies **only** to the `/stream` endpoint. All other endpoints continue to require the `X-API-Key` header exclusively.
- The auth dependency used by all non-stream endpoints is not changed.

## Error Conditions

| Condition | Response |
|---|---|
| No API key supplied (neither header nor query param) | 401 Unauthorized |
| Invalid key value | 401 Unauthorized |
| Valid key but submission not found | 404 Not Found |
| Valid key and subscription succeeds | SSE stream (200, `text/event-stream`) |

## Scenarios

- **Browser EventSource with valid key**: `EventSource('/api/v1/submissions/abc/stream?api_key=dev-demo-key')` connects and receives events.
- **Header auth still works**: curl with `-H "X-API-Key: dev-demo-key"` connects as before.
- **No key**: GET without header or query param returns 401.
- **Invalid key**: GET with `?api_key=wrong` returns 401.
