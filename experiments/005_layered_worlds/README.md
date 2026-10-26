# v5: two constructors, two independent verifiers, deterministic adjudication

**Completed on 2026-10-26:** all 104 frozen fresh-dev pairs now have their four V5
responses and separate A27 control. V5 scores 69/104 (66.35%); A27 scores 90/104
(86.54%). See the [complete real experiment report](RESUMPTION_20261026_RESULTS.md),
[full tables](continuation_tables.md), and [resumption audit](resumption_20261026_audit.json).
The exact [2026-10-24 checkpoint](checkpoints/20261024_quota_stop/CONTINUATION_RESULTS.md)
preserves the earlier 58-pair TPD stop. The [r2 continuation workflow](CONTINUATION.md)
remains available for reproduction; all scheduled inference is complete.
The r1 results/configuration below remain the historical first run;
do not resume r1 and r2 concurrently, because r2 already reuses r1's received answers.

Based on `codex/groq-27b-v4` at `5425613d937148f862e3583caddafef5603d5546`.
The eight English templates and two schemas are copied byte-for-byte from the supplied
task package. Their original SHA-256 manifest is checked before any request. Four roles
use the same hosted `qwen/qwen3.8-27b` weights in four independent contexts.

For every item the fixed order is constructor T, constructor F, verifier T, verifier F.
Both verifiers receive only their own candidate, original evidence and original claim.
The Python mapper alone emits the final label. A separate, paired A27 control uses the
unchanged v2 A2 prompt/schema and v4 1024-token budget. Semantic failure does not skip
any role, trigger regeneration or invoke a fallback. A technical or quota failure pauses
the entire run; it is recorded as incomplete, not treated as a selected shorter workflow.

`CANDIDATE_INVALID` and `UNDETERMINED` map to UNKNOWN. UNKNOWN produces
`UNRESOLVED_BRANCH`; two infeasible branches produce `UNRESOLVED_CONTRADICTION`.
All unresolved and missing items count as errors in the all-scheduled denominator.
Coverage and conditional accuracy are reported separately. These are LLM estimates,
not SAT/SMT proofs.

## Reproduce

Use the repository virtual environment; do not print or put the API key in commands.
The CLI reads `GROQ_API_KEY` or an ignored, untracked `.env.local`. Existing Free Plan
authorization is documented in v4; no plan, endpoint or model change is permitted.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ab_factcheck.cli_worlds_v5 doctor
.\.venv\Scripts\python.exe -m ab_factcheck.cli_worlds_v5 smoke --env-local --free-plan-confirmed
.\.venv\Scripts\python.exe -m ab_factcheck.cli_worlds_v5 freeze
.\.venv\Scripts\python.exe -m ab_factcheck.cli_worlds_v5 run --env-local --free-plan-confirmed
.\.venv\Scripts\python.exe -m ab_factcheck.cli_worlds_v5 report --phase smoke
.\.venv\Scripts\python.exe -m ab_factcheck.cli_worlds_v5 report --phase fresh
.\.venv\Scripts\python.exe scripts/audit_worlds_v5.py --output experiments/005_layered_worlds/integrity_audit.json
```

The commands reuse completed nodes. The formal command first rechecks the complete
cached technical/synthetic gates without issuing replacement requests. Semantic smoke
mistakes remain documented observations; protocol failures block execution. When
quota prevents completing smoke, a manifest may still be frozen after the offline
synthetic validation to prepare the next run; no fresh-dev request is permitted until
the actual smoke protocol gate completes. This scheduling exception never changes
selection according to predictions or labels.

`fresh_dev_v5.json` selects one entire unused group per mechanism in each development
dataset using SHA-256 ranking with seed 20261024, excluding the union of all old pilot
groups. Rankings, input hashes, full assignments and label/mechanism counts are saved.
The original held-out test is never loaded by the inference or selection paths. Groups
are interleaved across datasets, and paired arms are executed together per item. The
predeclared prefix is retained if a quota stop occurs; unfinished groups are visible.

## Storage, quota and recovery

Raw JSON responses live only in ignored `outputs/runs/<run>_smoke` and `<run>_fresh`.
Per-item folders use the SHA-256 of `[dataset, id]` and contain `generate_T.json`,
`generate_F.json`, `verify_T.json`, `verify_F.json`, `verdict.json`, and the separate
`baseline_A27.json`. Each model node contains exact requests, response metadata,
parsing results, error reasons, nonthinking checks, upstream hashes and integrity hash.
Errors and `.inflight` records survive a stop. A received invalid completion cannot be
retried. Ambiguous read/write failures and crashed inflight requests require inspection;
there is no automatic resend or forced cache override. Definite connect failures and
429/5xx receive at most two bounded retries. Terminal 403 errors are retained.

The shared `outputs/groq/quota.json` is preserved and appended using the v4 locking,
reservation and accounting code. Limits remain 800 attempts / 180000 conservatively
charged tokens per rolling 24 hours, 25 RPM, 7000 TPM, minimum 3 seconds spacing.
Unknown failed usage retains its reservation. Each request reserves serialized UTF-8
bytes plus 512 and its actual completion cap, using the inherited conservative rule. Existing ledger
entries are never removed or reset. Long reset waits cause a normal resumable stop.

Reports contain derived research summaries and hashes, not complete API envelopes.
The separate audit script rechecks messages, schemas, deterministic verdicts, all saved
history hashes and the original ledger prefix. Semantic review by the assistant is
explicitly distinguished from human adjudication and from automatic protocol checks.

## Provider documentation checked on 2026-10-24

The provider lists Qwen3.8-27B strict JSON Schema support in its
[structured output documentation](https://console.groq.com/docs/structured-outputs),
`reasoning_effort=none` in the [API reference](https://console.groq.com/docs/api-reference),
and Free Plan reference limits of 30 RPM / 1000 RPD / 8000 TPM / 200000 TPD in the
[rate limit documentation](https://console.groq.com/docs/rate-limits).
Actual response headers and the shared ledger govern execution. The headers do not
prove organization-wide TPD balance or zero billing; hosted weights are not exposed.
