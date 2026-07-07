# Guardrail-as-a-Service — Design Doc

**Author:** intern (draft for Eby review)
**Status:** DRAFT — awaiting scope approval
**Repo:** `A:\python\guardrail-service` (fresh, not yet git-initialized)
**Consumer:** `A:\python\email-agent-prototype` (Python 3.12, FastAPI, LangGraph, Ollama, Qdrant, Redis, Postgres)

---

## 0. Summary

A standalone HTTP microservice that the email agent calls to check user input and/or
generated output against four guardrail categories — denied topics, word filters,
sensitive-information filters, and content filters — modeled on AWS Bedrock
Guardrails' framework but scoped to what B2B Qatar/GCC finance email workflows
actually need. The agent calls it instead of running these checks inline.

---

## Part 1 — Architecture

### 1a. Directory structure

```
guardrail-service/
├── docs/
│   └── design.md                  # this file
├── app/
│   ├── main.py                    # FastAPI app, lifespan, route registration
│   ├── config.py                  # env vars, settings (mirrors config/settings.py pattern)
│   ├── schemas.py                 # Pydantic request/response models
│   ├── rules/
│   │   ├── loader.py               # loads YAML rule files (MVP) or DB-backed rules (full)
│   │   ├── denied_topics.yaml      # per-tenant or global topic descriptions
│   │   ├── word_filters.yaml       # blocklist strings/regex
│   │   └── pii_patterns.yaml       # regex patterns per PII category
│   ├── checks/
│   │   ├── base.py                 # GuardrailCheck protocol — check(text, direction) -> CheckResult
│   │   ├── denied_topics.py        # LLM intent classifier
│   │   ├── word_filter.py          # exact/regex string match
│   │   ├── pii_filter.py           # regex (+ optional NER) redaction
│   │   └── content_filter.py       # moderation classifier (Llama Guard 3 / toxic-bert)
│   ├── orchestrator.py            # runs enabled checks, combines into one decision
│   └── logging_setup.py           # structured logging (mirrors structured_logger.py pattern)
├── tests/
│   ├── test_word_filter.py
│   ├── test_pii_filter.py
│   ├── test_denied_topics.py
│   ├── test_content_filter.py
│   └── test_orchestrator.py
├── .env.example
├── requirements.txt
├── Dockerfile                     # should-have, not day-1 (see Part 4)
└── README.md
```

This mirrors the existing agent's layout conventions (`config/` for settings,
flat top-level modules, `tests/` sibling directory) so Eby and future
contributors don't have to context-switch between two different project
shapes.

### 1b. Framework

**FastAPI**, matching the existing stack exactly (`api.py` in
email-agent-prototype runs FastAPI 0.138.0 on Pydantic 2.13.4 / uvicorn
0.49.0). Pin the same major versions in this service's `requirements.txt` to
avoid a Pydantic v1/v2 model mismatch across the two codebases, since the
same team maintains both.

### 1c. Port

**9000.** The existing agent's FastAPI layer already owns 8000
(`uvicorn api:app --host 127.0.0.1 --port 8000`, per `api.py`'s module
docstring). Streamlit and other agent-side processes may claim other
common ports. 9000 avoids collision and is easy to remember as "the
guardrail sidecar."

### 1d. Storage for rules

Recommendation: **tiered by scope option**, not a single fixed answer —

- **Spike / MVP:** flat YAML files under `app/rules/`, loaded at startup and
  cached in memory. Editing a rule = editing a file + restarting the
  service (or a `/admin/reload` endpoint that re-reads from disk without a
  full restart — cheap to add, avoids a restart-per-edit workflow).
- **Full:** Postgres-backed, tenant-scoped tables (`denied_topics`,
  `word_filters`, `pii_categories_enabled`), since the existing agent
  already depends on Postgres (`psycopg[binary]`, `USE_POSTGRES` flag in
  `config/settings.py`) — no new infra to stand up, just new tables. An
  admin API (`POST/GET/DELETE /admin/rules/{category}`) fronts the tables
  so rules can be edited without touching YAML or redeploying.

Do not reach for Redis here — Redis in the existing stack is used for
session/TTL state (`sessions.py`), not config. Rules are low-write,
read-heavy — Postgres or flat files both outperform Redis for this shape
and avoid adding a second source of truth for config.

### 1e. Tenant-specific rules

**Yes — the schema should carry `tenant_id` from day one**, even in the
MVP where rules are hardcoded/global. Reasoning: the existing agent's
`config/tenants.py` already treats tenants as hard-isolated (separate IMAP
accounts, separate Qdrant/Chroma collections, separate system prompts per
`role`) — "Accounts & Finance," "Personal / Individual," "Marketing,"
"Customer Service" are functionally different businesses sharing
infrastructure. A denied topic that makes sense for the `askme` (customer
service) tenant may be irrelevant or wrong for `accounts` (finance). Baking
tenant awareness into the request schema now (even if the MVP's rule
resolution just falls back to a global default when no tenant-specific
rule exists) avoids a breaking schema change later — this is the one
design decision that's much cheaper to make correctly up front than to
retrofit.

### 1f. API contract shape

**`POST /guardrails/check`**

Request:
```json
{
  "request_id": "uuid-generated-by-caller",
  "tenant_id": "accounts",
  "session_id": "sess_abc123",
  "direction": "input",
  "text": "the user message or the agent's draft answer",
  "categories": ["denied_topics", "word_filters", "sensitive_info", "content_filter"]
}
```

- `direction`: `"input"` (checking the user's message before the router
  sees it) or `"output"` (checking the synthesis LLM's answer before it's
  returned). Some categories only make sense in one direction — e.g. word
  filters and content filters apply both ways, but sensitive-info
  redaction is far more consequential on `output` (leaking a customer's
  bank account number back to them or a third party) than on `input`
  (the user typing their own data). The orchestrator uses `direction` to
  decide which categories are active for a given call, but the caller can
  also pass `categories` explicitly to override the default set.
- `categories`: optional; omit to run all enabled categories for that
  direction. Lets the agent selectively skip categories on hot paths that
  don't need all four checks (e.g. `output` might skip `denied_topics`,
  since that's an input-classification concept).
- `tenant_id`: required, validated the same way `api.py`'s `chat_endpoint`
  already validates against the `TENANTS` dict (404 on unknown tenant) —
  the guardrail service should 404 the same way rather than silently
  falling back to a global default, so a typo'd tenant_id fails loudly.
- `session_id`, `request_id`: for correlating guardrail decisions back to
  the originating chat turn in logs — `request_id` is caller-generated
  (agent side) so a single logical request can be traced end-to-end across
  both services' logs.

Response:
```json
{
  "request_id": "uuid-generated-by-caller",
  "decision": "block",
  "redacted_text": null,
  "findings": [
    {
      "category": "sensitive_info",
      "subtype": "bank_account_number",
      "action": "block",
      "span": [42, 58],
      "detail": "matched pattern for GCC IBAN"
    }
  ],
  "latency_ms": 340
}
```

- `decision`: the single combined verdict — `"allow"`, `"block"`, or
  `"redact"`. Combination rule: **most restrictive wins** — if any category
  returns `block`, the overall decision is `block` regardless of what
  other categories say; if the worst finding is `redact` and nothing
  blocks, decision is `redact` and `redacted_text` is populated; otherwise
  `allow`. This mirrors how AWS Bedrock Guardrails combines its policy
  results and is the safest default for a finance-adjacent product — the
  cost of a false block (a mildly-worded but retryable rejection) is much
  lower than the cost of a false allow (leaked PII or an off-policy
  answer reaching a customer).
- `findings`: itemized per category so the agent (or a log viewer) can show
  *why* something was blocked/redacted, not just that it was. Empty list on
  `allow`.
- `redacted_text`: populated only when `decision == "redact"` — the
  caller swaps this in for the original text rather than re-deriving
  redaction client-side.
- `latency_ms`: self-reported service-side latency, for logging/alerting
  without the caller having to time the HTTP round trip separately.

### How the caller identifies itself

`tenant_id` (required, validated against the same tenant set the agent
uses), `session_id` (required, for log correlation, not for
authorization — this service doesn't need to know about chat history),
`request_id` (required, caller-generated UUID, for tracing). No separate
service-to-service auth is proposed for the MVP/spike since both services
run on the same host/VPC trust boundary in the current deployment; revisit
if the guardrail service is ever exposed outside that boundary (see Part 6
open questions).

---

## Part 2 — Detection strategies per category

| Category | Technique | Latency budget | False-positive risk | Rule storage |
|---|---|---|---|---|
| **Denied topics** | Small/fast LLM intent classifier via Ollama (`qwen2.5:7b` — already warm on the host, since it's the agent's own router model) prompted with the tenant's denied-topic descriptions and asked for a structured allow/block + reason | Biggest risk category, budget ≤3-5s | **Highest** of the four — natural-language topic classification is inherently fuzzy; a badly-worded denied-topic description ("legal investment recommendations") can over-trigger on benign finance questions the whole product exists to answer | YAML (MVP) → Postgres tenant-scoped table (full) |
| **Word filters** | Exact string match + optional regex, case-insensitive, word-boundary aware (avoid substring false hits, e.g. blocking "class" because it contains "ass") | <5ms — negligible | Low, if the list is curated; regex misuse (overly broad patterns) is the main risk | YAML (MVP) → Postgres (full) |
| **Sensitive info filters** | Regex patterns per category (bank account, Aadhaar, PAN, OTP, passport, phone, email, credit card) — all of these have well-defined formats and are exactly what regex is good at. NER model (spaCy/HF) is optional and only buys you name/org detection, which regex can't do | <20ms without NER; +100-300ms if an NER pass is added | Low for regex-detectable formats (numeric patterns are precise); NER adds false positives on names (common words, tenant employee names) if enabled — treat NER as a stretch add, not MVP scope | Pattern definitions in YAML/code (these change rarely — they're format specs, not business rules) |
| **Content filters** | Local moderation classifier via Ollama — **Llama Guard 3** is the stronger choice over `unitary/toxic-bert`: it's multi-category (hate/sexual/violence/illegal/self-harm) in one pass and already runs the same way the agent's other models do (`ChatOllama`), vs. pulling in a second ML runtime (HF transformers pipeline) just for toxic-bert. Also covers prompt-injection pattern detection reasonably well as an added category | 2-5s depending on GPU headroom — competes with the agent's own router/synthesis calls for the same RTX 3050, see latency note below | Moderate — moderation classifiers trained on general web content tend to over-flag finance/legal terminology (e.g. "aggressive collection," "default," "breach of contract") unless prompted with domain context | Model choice + threshold are config, not per-tenant rules — same model/threshold across tenants unless a real need emerges |

**Cross-cutting latency note:** the user's own framing — "a chat turn
already takes 30-90s, so we can't add another 30s" — is the binding
constraint. `denied_topics` and `content_filter` both call Ollama, and the
agent's `email_agent.py` already runs two Ollama calls per turn minimum
(router `qwen2.5:7b`, synthesis `qwen3:8b`) on a single RTX 3050. Adding
two more LLM-backed guardrail calls **on the same GPU** is where latency
risk actually lives — not in the regex-based checks, which are
sub-millisecond. Two mitigations worth planning for regardless of which
option ships:
1. Run `denied_topics` and `word_filters`/`sensitive_info` **in parallel**,
   not sequentially, inside the orchestrator — the regex checks finish
   before the LLM check starts, so parallelizing costs nothing and saves
   whatever the regex checks would have added serially.
2. On `input` direction, `word_filters` + `sensitive_info` + `denied_topics`
   all matter. On `output` direction, seriously consider **skipping
   `denied_topics`** by default (it's an input-intent concept — the
   synthesis LLM's answer isn't "asking about" a topic, it's answering
   one) — cuts one LLM round-trip per turn.

---

## Part 3 — Integration plan with the existing agent

### Where the agent calls the guardrail service

Recommendation: **both directions, but as two thin call sites, not
scattered through the graph.**

- **Input check** — in `api.py`, inside `chat_endpoint()`, right after
  tenant validation (after line 101 in the current file, i.e. right after
  `if req.tenant_id not in TENANTS: raise HTTPException(...)`) and before
  the Postgres history load / agent invocation. This is the earliest point
  the raw user text is available and the tenant is already known-valid —
  no wasted work checking a message that never reaches the agent.
- **Output check** — also in `api.py`, immediately after
  `result = await run_question_async(...)` returns (around line 159) and
  before the response is persisted to history / sent over the WebSocket.
  Checking the *final* synthesized answer, not intermediate tool-call
  content, keeps this to one call regardless of how many tool round-trips
  LangGraph did internally.

### Exact files that need touching

- **`api.py`** — the only file that needs a code change for the
  integration itself:
  - `chat_endpoint()` (`api.py:97-219`): add the input check after tenant
    validation, add the output check after `run_question_async()` returns,
    before Postgres/Redis writes.
  - `branch_endpoint()` (`api.py:224-325`): same two call sites — branch
    also runs a fresh LLM turn (`run_question_async` at line 275) and
    should not bypass guardrails just because it's a forked conversation.
  - Add a small `guardrail_client.py` (new file, in email-agent-prototype,
    not this repo) — a thin async HTTP wrapper (`httpx.AsyncClient`) around
    `POST /guardrails/check`, so `api.py` calls one function
    (`check_guardrails(text, tenant_id, session_id, direction)`) instead of
    constructing the request inline in two places.
- **`email_agent.py`** — **no changes needed.** This is the key
  least-invasive property: `run_question_async()` stays a pure
  question-in/answer-out function. Guardrails wrap it from the outside in
  `api.py`, they don't get threaded through `AgentState`, the LangGraph
  nodes, or the tool executor. This also means the Streamlit path
  (`app.py`, if it calls `run_question` directly rather than through
  `api.py`) is a separate integration decision — worth flagging to Eby
  explicitly (see Part 6 open questions) rather than assuming both UIs get
  guardrails for free.
- **No middleware layer needed.** A FastAPI middleware would run on every
  request including `/sessions/{sid}`, `/conversations/{sid}/history`,
  the WebSocket handshake, etc. — most of those don't carry user-authored
  text that needs checking, and middleware makes the direction (`input` vs
  `output`) and the "check before persist, not after" ordering harder to
  express than two explicit calls inside the one endpoint that actually
  needs them (`chat_endpoint`, `branch_endpoint`).

### Recommended integration shape (pseudocode, not to be implemented yet)

```python
# inside chat_endpoint(), after tenant validation:
input_check = await check_guardrails(
    text=req.question, tenant_id=req.tenant_id,
    session_id=req.session_id, direction="input",
)
if input_check.decision == "block":
    return ChatResponse(answer=BLOCKED_MESSAGE, sources=[], turn_index=0,
                         error="guardrail_blocked")
if input_check.decision == "redact":
    req.question = input_check.redacted_text  # rare on input, but handled

# ... existing agent invocation unchanged ...

# after result = await run_question_async(...):
output_check = await check_guardrails(
    text=result["response"], tenant_id=req.tenant_id,
    session_id=req.session_id, direction="output",
)
if output_check.decision == "block":
    result["response"] = BLOCKED_MESSAGE
elif output_check.decision == "redact":
    result["response"] = output_check.redacted_text
```

This is the "one HTTP call at the beginning, one at the end" shape asked
for — no changes inside LangGraph, no new nodes in the agent graph, no
changes to `agent_tools.py`.

---

## Part 4 — Deployment shape

### 4a. Docker from day one?

**No — should-have, not must-have**, matching the ask. Build it as a
plain `uvicorn` process during the spike/MVP phase; write the `Dockerfile`
once the service's shape has stabilized (rule storage decided, categories
finalized) rather than iterating on a container image while the API
contract is still moving. Do keep the repo Docker-ready in spirit — no
hardcoded absolute paths, config entirely via env vars — so containerizing
later is a Dockerfile + no code changes, not a refactor.

### 4b. Environment variables

```
GUARDRAIL_PORT=9000
GUARDRAIL_HOST=127.0.0.1

OLLAMA_HOST=http://localhost:11434       # same Ollama instance the agent uses
DENIED_TOPICS_MODEL=qwen2.5:7b
CONTENT_FILTER_MODEL=llama-guard3        # requires `ollama pull llama-guard3`

RULES_BACKEND=yaml                       # yaml | postgres — matches MVP vs full
RULES_PATH=./app/rules                   # only used when RULES_BACKEND=yaml

POSTGRES_HOST=localhost                  # only used when RULES_BACKEND=postgres
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=
POSTGRES_DB=guardrails                   # separate DB from email_agent's, or a separate schema

LOG_LEVEL=INFO
LOG_RAW_TEXT_ON_BLOCK=false              # see Part 6 open question on this
```

Mirrors the existing agent's `.env` / `config/settings.py` pattern
(`load_dotenv()` + `os.environ.get(..., "false").lower() == "true"` flags)
so it's immediately familiar to anyone who's touched
`email-agent-prototype`.

### 4c. Communicating with Ollama on the host

Same Ollama instance the agent already uses — this service is not a
second model host, it's another client of the one already running
locally (`OLLAMA_HOST=http://localhost:11434`, same default the agent's
`ChatOllama` calls assume). Once/if this moves into Docker, `localhost`
inside the container won't reach the host's Ollama — that's the point at
which `OLLAMA_HOST` needs to become `http://host.docker.internal:11434`
(Docker Desktop on Windows resolves that automatically) — noted here so
it's not a surprise later, not something to solve now.

### 4d. Local dev workflow

```
uvicorn app.main:app --host 127.0.0.1 --port 9000 --reload
```

Same shape as the agent's own `uvicorn api:app --host 127.0.0.1 --port
8000` — both processes run side by side on the dev machine, no
orchestration tooling needed for local dev.

---

## Part 5 — Scope options

### OPTION A — FULL (5-7 days)

**Ships:** all 4 categories (denied topics via LLM classifier, word
filters, PII regex + redaction, content filter via Llama Guard 3),
tenant-scoped rules in Postgres, admin API for rule CRUD, structured
logging (mirroring `structured_logger.py`'s pattern in the existing repo),
`/health` endpoint, Dockerfile, integration on both agent input and
output.

**Deferred:** NER-based PII detection (name/org redaction beyond
regex-detectable formats), any rate-limiting/auth beyond same-VPC trust,
per-tenant content-filter threshold tuning.

**Estimate:** 5-7 days including buffer.

**Biggest engineering risk: denied topics.** It's the only category
where correctness depends on prompt-engineering an LLM classifier against
fuzzy natural-language topic descriptions *and* getting tenant-scoped
Postgres rule resolution right at the same time — two moving pieces
compounding risk in the same category, and it's also the category most
likely to need actual tuning against real query traffic before it's
trustworthy (see false-positive risk in Part 2).

### OPTION B — MVP (2-3 days)

**Ships:** all 4 categories, but rules hardcoded (denied topics/word
lists/PII patterns/content thresholds all in YAML, edited by hand, no
tenant scoping — one global rule set), minimal structured logging
(request_id/decision/latency, not full findings detail), integration on
**agent input only** (skip the output check for now).

**Deferred:** tenant-specific rules, admin API, Postgres backend, Docker,
output-side checking.

**Estimate:** 2-3 days, but see Part 6 — this is optimistic if
`denied_topics` needs any real tuning; treat day 3 as the buffer, not a
stretch goal.

**Biggest engineering risk: still denied topics**, for the same
prompt-tuning reason as Option A, just without the added Postgres
complexity — the LLM-classifier correctness problem doesn't get smaller
just because the storage layer got simpler.

### OPTION C — SPIKE (1 day)

**Ships:** word filter + sensitive-info filter only — both are pure
regex/string-match, zero LLM dependency, so latency and false-positive
risk are both low and the whole thing is testable with unit tests alone
(no Ollama warm-up, no model-behavior nondeterminism to work around).
Proves the microservice pattern (separate HTTP service, `/guardrails/check`
contract, agent calls it) end to end.

**Deferred:** denied topics, content filter — i.e. both LLM-backed
categories, which are also the two hardest and riskiest ones. This is a
deliberate "ship the easy 50%, defer the hard 50%" cut, not an arbitrary
one.

**Estimate:** 1 day, realistic — this is genuinely small in scope.

**Biggest engineering risk:** none of the four categories, really — the
risk in this option is scope creep back toward MVP mid-spike ("while I'm
in here, let me just add..."). The discipline is staying at two
categories.

---

## Part 6 — Recommendation and open questions

### Recommendation: **Option B (MVP)**, with a fallback to Option C if week bandwidth is tighter than expected.

Reasoning:

- Eby wants this **shipped and demoable** — Option A's 5-7 days is a
  full sprint on its own, and the existing Phase 11 branching arc *just*
  took a full week including bug fixes on work that was better-understood
  going in (extending an existing agent) than this is (a brand-new
  service + a new integration contract). Option A's timeline risk is real.
- Option C undersells what Eby asked for — "four guardrail categories"
  was explicit in the ask, and shipping only two (leaving out the two
  LLM-backed ones, which are also the two most novel/interesting parts of
  the pattern) risks reading as an incomplete demo rather than a scoped
  first cut, even though technically it's the lowest-risk option.
- Option B ships all four categories — the actual demoable claim ("the
  agent now has guardrails") is true — while deferring the two things
  that add real schedule risk without changing what's demoable:
  tenant-scoped rules (global rules are fine for a demo with 4 known
  tenants) and the admin API (hand-editing YAML is fine at this scale).
- Given the LinkedIn content-plan work running in parallel, Option B's
  2-3 days (treat as 3-4 with buffer, per the estimate note above) fits a
  realistic week better than Option A's full-week commitment does.

If, once work starts, `denied_topics` prompt-tuning turns out to be
harder than expected (this is the one place in the whole design most
likely to blow the estimate), the fallback isn't "cut scope on other
categories" — it's "ship Option C's two categories first, demo that the
pattern works, then follow up with the LLM-backed ones once there's
real traffic to tune `denied_topics` against." That sequencing point is
worth raising with Eby directly rather than deciding unilaterally.

### Open questions for Eby

1. **Are denied topics tenant-specific or the same across all four
   tenants (`accounts`, `joel`, `marketing`, `askme`)?** This determines
   whether Option B's "one global rule set" is actually acceptable for
   the MVP or whether tenant-scoping needs to be pulled forward from
   Option A. Given how differently-scoped the four tenants already are
   (finance vs. personal vs. marketing vs. customer service — see
   `config/tenants.py`), my guess is yes they should differ eventually,
   but MVP-global may be fine as a first cut — Eby's call.
2. **What's the acceptable latency budget for the guardrail check,
   specifically?** The brief says "we can't add another 30s," but doesn't
   give a target ceiling. Knowing whether 3-5s total is acceptable (vs.
   needing to stay under 1s) changes whether `denied_topics` and
   `content_filter` can both run as full LLM calls per turn, or whether
   one of them needs to be cut/simplified for latency reasons alone.
3. **Should PII redaction happen inline (return the redacted text
   automatically) or block-and-return-error (reject the whole message,
   force the user/agent to rephrase)?** This changes both the API
   contract's `decision` semantics and the agent-side integration code —
   worth locking down before implementation starts, not after.
4. **Do we log the raw user input/agent output on a block/redact event, or
   only the guardrail decision + category?** Logging the raw text is far
   more useful for debugging false positives and tuning `denied_topics`,
   but it also means PII that was correctly caught ends up sitting in a
   log file — which may itself be a compliance problem for GCC finance
   data. Needs an explicit answer, not a default assumption.
5. **Does the Streamlit UI path (`app.py` / `ui.py`, which may call
   `email_agent.run_question()` directly rather than through `api.py`'s
   `/chat` endpoint) need guardrails too, or is FastAPI the only
   integration point for now?** If Streamlit bypasses `api.py`, the
   integration plan in Part 3 doesn't cover it, and guardrails would only
   apply to API-driven traffic.
6. **Is there any requirement for the guardrail service to be reachable
   from outside the current host/VPC** (e.g. a future multi-host
   deployment, or a separate ops team hitting it directly)? The API
   contract in Part 1f assumes same-trust-boundary and proposes no
   service-to-service auth — that assumption needs to be confirmed before
   Option A's Docker/VPC deployment work begins, since adding auth
   retroactively touches the contract Eby will have already approved.

---

*End of design doc — draft for review, no code written, no existing files
in `email-agent-prototype` modified.*
