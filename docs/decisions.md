# docs/decisions.md — Architectural Decision Record

Running log of decisions made during development.
Add an entry per stage (features.md) and before submission.
Format: ## ADR-NNN: Title / Date / Decision / Rationale

---

## ADR-001: LLM provider — Gemini only
Date: 2026-09-12
Decision: Use Google Gemini API exclusively (gemini-2.5-flash for extraction,
  optionally pro-tier for ambiguous vision or final explanation polish).
Rationale: Native multimodal input handles image-based amount extraction.
  Strict JSON-schema structured output mode fits the fixed-schema extraction
  tasks exactly. One provider = one usage report, no key/model provisioning
  risk. NIM/OpenAI explicitly ruled out in main.md.

## ADR-002: Deterministic core, LLM at edges only
Date: 2026-09-12
Decision: All financial computations (FX conversion, 90-day simulation,
  amount_safe_to_pay, plan ranking) are deterministic Python using Decimal.
  LLM is called only for (a) blank-amount image extraction and (b) optional
  explanation fluency polish, both with strict JSON schemas.
Rationale: Graded fields are exact-match or numeric-closeness — LLM reasoning
  about numbers will occasionally hallucinate; deterministic code cannot.
  Same input -> same output (determinism test) is impossible with free-form LLM output.

## ADR-003: Decimal throughout, never float
Date: 2026-09-12
Decision: Every monetary value uses Python decimal.Decimal from CSV ingestion
  through output write. Convert to string only at the final CSV boundary.
Rationale: Floating-point drift over 90-day simulation with FX conversion
  can silently break exact-match scoring. Decimal is exact.

## ADR-004: Template-first explanation, LLM polish optional + validated
Date: 2026-09-12
Decision: decision_explanation is built from a deterministic template
  populated with the exact computed facts. Gemini may polish for fluency
  only. Validator regex-extracts every number/date from the LLM output and
  diffs against source facts; any mismatch -> discard LLM version, use template.
Rationale: Consistency failure (LLM invents/misstates a number) is both a
  scoring failure and a visible quality failure in the transcript. Making
  inconsistency structurally impossible is higher-value than polish.

## ADR-005: Cache all LLM calls by input hash
Date: 2026-09-12
Decision: Every Gemini call is cached on disk (cache/ directory, gitignored)
  keyed by hash of exact inputs (image bytes hash or message text + context hash).
Rationale: Reruns after downstream bug fixes must not re-spend tokens.
  Cache also makes the determinism test pass (same extraction every time).

## ADR-006: Real column names confirmed against actual CSVs
Date: 2026-09-12
Decision: schema.md updated in-place with verified column names.
Key corrections found:
  - financial_profiles: available_balance -> current_available_balance
  - financial_profiles: 4 missing columns (expense_categories_to_protect,
    expense_categories_user_is_willing_to_reduce,
    expense_categories_user_is_willing_to_stop, max_installment_months)
  - financial_events: event_type enum has 8 values, not 4
  - financial_events: status includes scheduled and unrealized (not in spec)
  - financial_events: flexibility and minimum_allowed_amount columns not in spec
  - request_payment_options: column names differ from schema description
  - exchange_rates: no direct ZAR<->IDR/INR pairs; must chain via USD
  - messages: message_id, sent_at, source_type columns not in spec

## ADR-007: max_installment_months gates plan eligibility
Date: 2026-09-12
Decision: When financial_profiles.max_installment_months is non-empty,
  installment options with number_of_payments > max_installment_months
  are ineligible regardless of safety.
Rationale: This column exists in the data and clearly constrains user
  preference. Ignoring it would recommend plans users explicitly exclude.

## ADR-008: scheduled status treated as confirmed future debit
Date: 2026-09-12
Decision: Events with status=scheduled are included in the 90-day timeline
  (treated like pending debits). Events with status=unrealized are excluded.
Rationale: scheduled = confirmed future payment (e.g. known rent on a future
  date). unrealized = investment mark-to-market, non-cash, explicitly excluded
  by spec. The problem statement omits these two statuses from its filter list
  but they appear in the real data.

## ADR-009: Live Gemini model selection — gemini-3.8-flash
Date: 2026-09-12
Decision: Use gemini-3.8-flash as the primary LLM for structured extraction and
  multimodal receipt reading, with gemini-flash-latest as fallback.
Rationale: Live API testing against the user's Gemini key revealed that older
  generation models (gemini-2.5-flash / gemini-2.5-pro) are deprecated (404),
  while Pro preview models without cloud billing have a 0-rate quota limit on
  free-tier keys. gemini-3.8-flash connects successfully with zero temperature,
  supports native multimodal vision extraction on dataset images (validated
  on image_01.png with 100% confidence), enforces strict JSON schemas, and
  provides the lowest latency and optimal token efficiency required by evaluation.md.
