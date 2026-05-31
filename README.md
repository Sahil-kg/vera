# Vera Precision Bot

Vera Precision Bot is a deterministic WhatsApp-style merchant assistant built for the magicpin challenge. It receives business context, decides which trigger deserves action, writes a merchant/customer message, remembers the conversation, and handles replies through simple rule-based logic.

The bot does not use OpenAI, LangChain, Gemini, or any external AI layer. All behavior comes from Python code, stored context, scoring rules, insight extraction, and message templates.

## High-Level Flow

The judge or client talks to the bot through HTTP:

```text
1. POST /v1/context
   Push category, merchant, customer, and trigger data into memory.

2. POST /v1/tick
   Ask the bot: "Given these active triggers, do you want to send anything now?"

3. Bot ranks triggers, composes messages, stores conversation state, and returns actions.

4. POST /v1/reply
   Send a merchant reply back to the bot.

5. Bot classifies the reply and returns send, wait, or end.
```

This makes the bot stateful. It does not need a database for the challenge because all state is kept in memory while the process is running.

## Core Concepts

### Category Context

Category context describes the business vertical, such as dentists, salons, restaurants, gyms, or pharmacies.

It usually contains:

- Category voice and tone rules.
- Offer templates.
- Peer benchmarks.
- Research, events, seasonal beats, and trend signals.
- Category-specific language constraints.

The bot uses this to avoid generic messages. For example, a dentist message should sound clinical and peer-to-peer, while a restaurant message should sound like an operator-focused growth suggestion.

### Merchant Context

Merchant context describes the actual business.

It usually contains:

- Merchant name, owner name, locality, city, and language preferences.
- Subscription state.
- Performance numbers like views, calls, CTR, leads, and directions.
- Active offers.
- Customer aggregates.
- Business signals such as stale posts, low CTR, dormant usage, or high repeat rate.

The bot uses this for merchant fit. A good message should feel like it was written for this specific merchant, not for the whole category.

### Customer Context

Customer context is optional. It appears when the bot is composing a customer-facing message on behalf of a merchant.

It usually contains:

- Customer name and language preference.
- Last visit and visit count.
- Preferences such as preferred slots.
- Consent and opt-in scope.
- Customer state, such as active, lapsed, or churned.

When customer context exists, the bot sends as `merchant_on_behalf`. Otherwise it sends as `vera`.

### Trigger Context

Trigger context is the reason to speak now.

Examples:

- `perf_spike`
- `perf_dip`
- `festival_upcoming`
- `competitor_opened`
- `recall_due`
- `appointment_tomorrow`
- `chronic_refill_due`
- `gbp_unverified`
- `dormant_with_vera`

Every proactive message should be tied to a trigger. This is important because the judge scores "why now" very strictly.

## Request Flow In Detail

### 1. Server Entry Point

`server.py` starts a standard-library HTTP server:

```python
ThreadingHTTPServer((HOST, PORT), Handler)
```

It reads:

- `HOST`, default `0.0.0.0`
- `PORT`, default `8080`
- `MAX_REQUEST_BYTES`, default `500 KB`

Render automatically provides `PORT`, so the server is already deployment-ready.

### 2. Context Storage

When `/v1/context` is called, `server.py` forwards the payload to `push_context()`.

Context is stored in the `CONTEXTS` dictionary using:

```text
(scope, context_id)
```

Supported scopes:

- `category`
- `merchant`
- `customer`
- `trigger`

The bot also tracks versions. If an older version arrives after a newer one, it rejects the stale update.

### 3. Tick Processing

When `/v1/tick` is called, the bot receives:

```json
{
  "now": "2026-05-31T00:00:00Z",
  "available_triggers": ["trigger_123"]
}
```

The `tick()` function then:

1. Loads each trigger from memory.
2. Finds the merchant connected to that trigger.
3. Finds the merchant category.
4. Adds a payload summary and cached trigger tokens.
5. Ranks triggers using deterministic scoring.
6. Skips triggers already blocked by suppression.
7. Loads customer context if the trigger is customer-scoped.
8. Calls `compose()` to build the message.
9. Stores conversation state.
10. Returns actions to the caller.

The response looks like:

```json
{
  "actions": [
    {
      "conversation_id": "merchant_123:trigger_123",
      "merchant_id": "merchant_123",
      "customer_id": null,
      "send_as": "vera",
      "trigger_id": "trigger_123",
      "template_name": "vera_perf_spike_v1",
      "template_params": ["message body"],
      "body": "Final WhatsApp message",
      "cta": "draft_post",
      "suppression_key": "perf_spike:merchant_123",
      "rationale": "Why this message was chosen"
    }
  ]
}
```

### 4. Trigger Ranking

`scoring.py` decides priority. It looks at:

- Trigger kind.
- Urgency.
- Deadline pressure.
- Severity or risk level.
- Business impact.
- Merchant/category relevance.
- Payload facts.
- Performance and customer signals.

This prevents the bot from blindly sending every available trigger. Higher-value or more urgent triggers come first.

### 5. Message Composition

`compose_merchant.py` and `compose_customer.py` create the actual message body.

Merchant-facing messages use:

- Owner salutation.
- Business name and locality.
- Trigger facts.
- Merchant performance numbers.
- Active offers.
- Category-specific wording.
- A single clear CTA.

Customer-facing messages use:

- Customer name.
- Merchant name.
- Last visit or appointment facts.
- Offer or slot information.
- A confirmation CTA.

The final composed object includes:

- `body`
- `cta`
- `send_as`
- `suppression_key`
- `rationale`

### 6. Insight Extraction

`insights.py` turns raw context into useful business facts.

For example, instead of only saying:

```text
views=2410, calls=18
```

the bot can reason:

```text
2,410 views but only 18 calls means the profile has attention but weak conversion.
```

This improves specificity, decision quality, and engagement.

### 7. Suppression

`suppression.py` prevents repeated sends for the same business situation.

For example, if a trigger has already produced a message with a suppression key, the bot avoids sending the same type of nudge again in the same run.

This matters because repeated WhatsApp nudges reduce trust and can hurt judge scores.

### 8. Reply Handling

When `/v1/reply` receives a merchant message, `reply()` classifies it using deterministic patterns.

The bot handles:

- Stop or opt-out messages.
- Hostile messages.
- WhatsApp Business auto-replies.
- Off-topic replies.
- Objections.
- Positive confirmations.
- Generic replies.

Possible outputs:

```json
{ "action": "send", "body": "...", "cta": "take_action", "rationale": "..." }
```

```json
{ "action": "wait", "wait_seconds": 14400, "rationale": "..." }
```

```json
{ "action": "end", "rationale": "..." }
```

Auto-reply handling is important. If a merchant sends repeated canned replies like "Thank you for contacting us", the bot waits first and eventually ends the conversation instead of wasting turns.

## File Responsibilities

### `server.py`

HTTP layer. It parses requests, validates JSON, routes endpoints, and returns JSON responses.

### `__init__.py`

Main orchestration layer. It owns `tick()`, `reply()`, `healthz()`, `metadata()`, and conversation creation.

### `compose_merchant.py`

Merchant-facing composition. It contains handler functions for known trigger kinds such as performance dips, competitor openings, festivals, milestones, GBP verification, planning intent, and seasonal shifts.

### `compose_customer.py`

Customer-facing composition. It handles reminders, recall due messages, lapsed customer winbacks, appointment reminders, refill reminders, and reply follow-up bodies.

### `scoring.py`

Trigger scoring and business priority logic. It decides which triggers are more important.

### `insights.py`

Extracts structured facts and implications from trigger, merchant, category, and customer data.

### `intents.py`

Shared wording, CTA, offer, salutation, category-family, and decision helpers.

### `state.py`

In-memory state. It stores metadata, contexts, suppressions, conversations, known patterns, and helper functions.

### `suppression.py`

Context storage and suppression-key helpers.

### `profiles.py`

Merchant profile memory, open/resolved issues, and auto-reply tracking.

### `sanitization.py`

Text cleanup, date display, percent formatting, money formatting, and safe string helpers.

### `models.py`

Small dataclasses used across the bot.

## API Endpoints

### `GET /v1/healthz`

Returns health and memory state:

```json
{
  "status": "ok",
  "uptime_seconds": 123,
  "contexts_loaded": {
    "category": 5,
    "merchant": 50,
    "customer": 200,
    "trigger": 100
  },
  "suppressions_active": 3,
  "conversations": 10,
  "auto_reply_counts": 1,
  "insight_cache_size": 20
}
```

### `GET /v1/metadata`

Returns team and bot identity.

### `POST /v1/context`

Stores context:

```json
{
  "scope": "merchant",
  "context_id": "merchant_123",
  "version": 1,
  "payload": {}
}
```

### `POST /v1/tick`

Creates proactive actions:

```json
{
  "now": "2026-05-31T00:00:00Z",
  "available_triggers": ["trigger_123"]
}
```

### `POST /v1/reply`

Handles merchant/customer replies:

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

Clears all in-memory state. Useful for judge resets and local testing.

## Debug Endpoints

- `GET /debug/state`
- `GET /debug/contexts`
- `GET /debug/suppressions`

These are useful during development, but should not be treated as persistent storage.

## Running Locally

If you are inside the package folder itself:

```bash
cd vera
python server.py
```

This works because `server.py` bootstraps the package imports when it is run directly.

If you are at the repository root and your package folder is named `vera`:

```bash
python -m vera.server
```

If your package folder is named `bot`:

```bash
python -m bot.server
```

Default URL:

```text
http://localhost:8080
```

Override the port:

```bash
PORT=8081 python -m vera.server
```

On PowerShell:

```powershell
$env:PORT = "8081"
python -m vera.server
```

## Render Deployment

If your GitHub repo contains a `vera/` folder:

```text
repo-root/
└── vera/
    ├── __init__.py
    ├── server.py
    ├── compose_merchant.py
    ├── state.py
    ├── requirements.txt
    └── README.md
```

Use these Render settings:

```text
Root Directory: leave blank
Build Command: pip install -r vera/requirements.txt
Start Command: python -m vera.server
```

Alternative Render setup: set `Root Directory` to `vera`, then use:

```text
Build Command: pip install -r requirements.txt
Start Command: python server.py
```

If the files are directly at the repository root:

```text
repo-root/
├── __init__.py
├── server.py
├── compose_merchant.py
├── state.py
├── requirements.txt
└── README.md
```

Use:

```text
Root Directory: leave blank
Build Command: pip install -r requirements.txt
Start Command: python server.py
```

Render automatically sets `PORT`. The server already reads that value:

```python
PORT = int(os.getenv("PORT", "8080"))
```

So no custom port environment variable is required.

## Requirements

The bot currently uses only the Python standard library. `requirements.txt` is intentionally empty except for a comment.

## Important Notes

- State is in memory only. Restarting the Render service clears contexts, conversations, suppressions, insight cache, and profiles.
- This is acceptable for the challenge harness because it pushes context during evaluation.
- There is no external AI call, so hosting is cheap and startup is fast.
- Message quality comes from deterministic rules, context extraction, and trigger-specific composition.
- The bot should always be started as a Python module when it lives inside a package folder: `python -m vera.server`.
