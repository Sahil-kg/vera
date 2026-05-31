# Vera Precision Bot

Vera Precision Bot is a dependency-light Python bot for the magicpin challenge. It stores merchant, category, customer, and trigger context, ranks available triggers, composes deterministic merchant/customer messages, and handles merchant replies without any AI or LLM runtime layer.

## What the Bot Does

- Accepts context payloads for categories, merchants, customers, and triggers.
- Ranks trigger opportunities using deterministic scoring.
- Builds merchant-facing and customer-facing message drafts from rules, insights, and stored context.
- Tracks conversations, opt-outs, objections, topic drift, auto-replies, and suppressions.
- Exposes HTTP endpoints for context ingestion, ticking, replies, metadata, health checks, and teardown.

## Project Files

- `server.py` - dependency-free HTTP server and route handlers.
- `__init__.py` - main bot orchestration for `tick`, `reply`, metadata, and health.
- `compose_merchant.py` - deterministic merchant message composition.
- `compose_customer.py` - deterministic customer message composition and reply follow-up bodies.
- `scoring.py` - trigger archetypes, ranking, urgency, and priority logic.
- `insights.py` - context and trigger insight extraction for stronger message plans.
- `intents.py` - category/intent helpers, CTAs, offers, and wording utilities.
- `state.py` - in-memory state, metadata, patterns, and conversation helpers.
- `suppression.py` - context storage, ID aliasing, and send suppression keys.
- `profiles.py` - merchant profile memory and repeated auto-reply tracking.
- `sanitization.py` - text cleanup, safe formatting, and output guards.
- `trigger_fusion.py` - trigger grouping/fusion helpers.
- `models.py` - shared dataclasses.

## Run Locally

From the repository root:

```powershell
python -m bot.server
```

By default the server listens on:

```text
http://0.0.0.0:8080
```

You can override the host and port:

```powershell
$env:HOST = "127.0.0.1"
$env:PORT = "8081"
python -m bot.server
```

## API Endpoints

### `GET /v1/healthz`

Returns server health, uptime, loaded context count, active suppressions, conversation count, auto-reply state count, and insight cache size.

### `GET /v1/metadata`

Returns team and bot metadata.

### `POST /v1/context`

Stores a context payload.

Required JSON fields:

```json
{
  "scope": "merchant",
  "context_id": "merchant_123",
  "version": 1,
  "payload": {}
}
```

Supported scopes are `category`, `merchant`, `customer`, and `trigger`.

### `POST /v1/tick`

Creates actions for available triggers.

```json
{
  "now": "2026-05-31T00:00:00Z",
  "available_triggers": ["trigger_123"]
}
```

### `POST /v1/reply`

Handles an incoming merchant reply for an existing conversation.

```json
{
  "conversation_id": "merchant_123:trigger_123",
  "merchant_id": "merchant_123",
  "customer_id": null,
  "message": "yes",
  "turn_number": 1
}
```

### `POST /v1/teardown`

Clears in-memory contexts, conversations, suppressions, merchant auto-reply counts, and insight cache.

## Debug Endpoints

- `GET /debug/state`
- `GET /debug/contexts`
- `GET /debug/suppressions`

## Notes

- State is in memory only. Restarting the process clears contexts, conversations, suppressions, and profiles.
- Message generation is deterministic and does not call `ai_layer.py`, OpenAI, LangChain, or any external AI service.
- The server uses only Python standard-library HTTP primitives.
