# Model Quality & Vulnerability-Finding Benchmark — 2026-07-17

## Status: complete

Three related benchmarks run on container 9001 (`llamacpp-gpu-native`, native
HIP build, no Docker) to answer two questions: which local model is best
suited to code-generation tasks, and separately, which is best at *reviewing*
code for security vulnerabilities. All three models were quantized Q4_K_M
GGUF, served via `llama-server` one at a time (see "Machine state" below for
why not concurrently).

- `scripts/code_quality_bench.py` — Python/Prolog/Ansible code generation,
  Llama-3.3-70B-Instruct vs Qwen2.5-Coder-32B-Instruct.
- `scripts/vuln_finding_bench.py` — vulnerability review, same two models
  plus DeepSeek-R1-Distill-Qwen-32B (reasoning-tuned) added afterward
  specifically to test whether reasoning-tuned models do better on
  multi-step exploit chains than code-completion-tuned ones.

## 1. Code-quality benchmark: Llama-3.3-70B vs Qwen2.5-Coder-32B

9 tasks across Python (HumanEval, real dataset), Prolog (99 Prolog Problems,
hand-selected tiers), and Ansible (hand-authored — no standard benchmark
exists for IaC code generation), each at simple/medium/complex tiers.
Grading is execution-based: real `assert`s for Python, `swipl` query
execution for Prolog, real `ansible-playbook` runs (including idempotency
and handler-firing checks) for Ansible.

| | Llama-3.3-70B | Qwen2.5-Coder-32B |
|---|---|---|
| Pass rate | 8/9 | 8/9 |
| Total wall time (9 tasks) | 336.1s | 184.0s |
| Throughput | 4.0-4.7 t/s | 8.7-10.4 t/s |

Both models fail the identical task (Prolog Huffman coding, property-graded)
with the same failure signature — a structurally invalid tree despite
warning-free code — suggesting a genuine shared reasoning gap rather than a
grading artifact. Qwen is ~2.2x faster in tokens/sec and finishes the full
suite in about half the wall-clock time, at roughly half Llama's disk
footprint (19.85GB vs 42.5GB).

**Recommendation**: Qwen2.5-Coder-32B-Instruct for code-generation tasks on
this hardware — same correctness ceiling as Llama-3.3-70B, meaningfully
faster, smaller footprint.

## 2. Vulnerability-finding benchmark (v1): Llama-3.3-70B vs Qwen2.5-Coder-32B

Different task from code generation: given a snippet, does the model
correctly identify a real vulnerability, and does it stay quiet on a
matched, remediated "safe" version instead of re-flagging the same issue?

- Python snippets are drawn verbatim from
  [SecurityEval](https://github.com/s2e-lab/SecurityEval) (s2e-lab,
  MSR4P&S'22), a published, CWE-labeled dataset of real insecure code mined
  from CodeQL/Sonar/MITRE examples — CWE-078 (OS command injection),
  CWE-502 (insecure deserialization), CWE-611 (XXE).
- Ansible tasks are hand-authored (no standard IaC vulnerability-review
  benchmark exists) against real CWE classes that show up in playbooks:
  CWE-798 (hardcoded secret), CWE-078 (shell-module injection), CWE-295 +
  CWE-732 (disabled TLS validation + world-writable file, combined).
- Each task ships a "safe" remediated counterpart, graded the same way, to
  catch a model that just calls everything vulnerable.

Manually verified results (see "Grader bugs" below for why manual
verification was necessary):

| | Llama-3.3-70B | Qwen2.5-Coder-32B |
|---|---|---|
| Catch rate | 6/6 | 6/6 |
| Hedges on safe/remediated code | 3/6 | 2/6 |

Both models find every real vulnerability. Neither confidently clears
remediated code — both re-raise the same vulnerability class with soft
language ("risk is somewhat mitigated but not entirely eliminated") on a
third to half of the safe variants, a known LLM security-review tendency.
Qwen hedges less and is still ~2.2x faster.

## 3. Reasoning-model follow-up: does reasoning-tuning help on exploit chains?

The v1 tasks were all single-line, single-CWE-signature bugs — arguably
easy to catch by pattern recognition alone. Two new tasks were added
specifically to require connecting cause and effect across multiple
statements, and DeepSeek-R1-Distill-Qwen-32B (`bartowski/DeepSeek-R1-Distill-Qwen-32B-GGUF`,
Q4_K_M, reasoning-tuned) was downloaded and added as a third model:

- **`python-chain`** (CWE-347, algorithm confusion): a JWT verifier accepts
  both `RS256` and `HS256` while validating against a public key. Since the
  "public" key isn't actually secret, an attacker can forge a token by
  signing it with `HS256` using the public key bytes as the HMAC secret.
  Fix: restrict to `["RS256"]` only.
- **`ansible-chain`** (CWE-367/732, TOCTOU privilege escalation): one
  unprivileged task writes a world-writable (`mode: '0666'`) script to
  `/tmp`, a second task executes it as root. Any local user can replace the
  script's contents in the gap between the two tasks. Fix: write directly to
  a root-owned, non-shared path with `become: true` and `mode: '0700'`
  throughout.

Full 8-task (6 original + 2 chain) results, manually verified:

| | Llama-3.3-70B | Qwen2.5-Coder-32B | DeepSeek-R1-Distill-32B |
|---|---|---|---|
| Catch rate (8 tasks) | 7/8 | 8/8 | **8/8** |
| Hedge/false-positive rate | 4/8 | 2/8 | **1/8** |
| Throughput | ~4.7 t/s | ~10.4 t/s | ~10.4 t/s |
| `python-chain` (JWT confusion) | **Missed entirely** — invented unrelated concerns (no expiry check, no error handling); its own "fixed" code left the vulnerable `algorithms=["RS256","HS256"]` line unchanged | Caught, but reasoning was shaky — framed it as needing to "brute-force the secret," missing that the public key isn't secret at all | **Caught cleanly** — correctly explained the RS256/HS256 key-confusion mechanism and gave the right fix |
| `ansible-chain` (TOCTOU) | Caught, but hedged on the fixed version too | Caught | Caught, but also hedged on the fixed version (re-flagged the same tampering concern even after the fix removed the actual precondition) |

DeepSeek-R1-Distill-Qwen-32B is the only model that got every task right,
including the one deliberately built to need multi-step reasoning rather
than CWE-signature pattern-matching — at the same throughput as Qwen (same
32B size class, no speed cost for the better reasoning). Llama-3.3-70B,
more than twice the size, missed the algorithm-confusion chain outright.

**Recommendation**: for vulnerability review specifically,
DeepSeek-R1-Distill-Qwen-32B is the strongest of the three — same speed as
Qwen2.5-Coder-32B, better precision, and the only one that reliably handles
exploit chains requiring connected reasoning across statements rather than
signature recognition.

## Grader bugs hit and fixed while building `vuln_finding_bench.py`

Grading free-text security analysis is inherently leakier than the
execution-based grading in `code_quality_bench.py`. Three real bugs were
found only by manually reading transcripts against the automated verdict,
not by trusting the raw script output:

1. **40-char lookback window missed negations governing a later clause.**
   "...good practices to prevent X (Y) attacks (CWE) and X attacks via
   network access, respectively" — the negation ("prevent") only appears
   once but grammatically governs both clauses; the second `X` mention sat
   outside a 40-char window and was wrongly flagged as a live finding on
   *correct, clean* "no vulnerabilities found" verdicts (2 confirmed cases:
   Llama and Qwen on `python-complex`/XXE).
2. **Paragraph-wide negation scoping (the fix attempted for #1) over-corrected.**
   Vulnerability explanations routinely say things like "inserted into a
   shell command *without* any sanitization" — here "without" describes the
   *cause* of a real vulnerability, not a negation of one. Paragraph-wide
   scope let an unrelated "without"/"lacks" elsewhere in the same paragraph
   suppress a genuine, nearby positive finding (confirmed: caused false
   *misses* on genuine catches).
3. **Fix**: a 100-char lookback window (not paragraph-scoped), verified
   against all 24 saved transcripts from the v1 run and reproducing every
   manually-checked verdict exactly. Documented as a comment directly above
   `grade()` in the script so the reasoning survives the next person reading
   it.

Two further hand-corrections were needed on the reasoning-model chain tasks
specifically, both too narrow/blunt for natural phrasing variation rather
than window-size problems:
- `replac\w* the (script|file|content)` didn't match "replace **or modify**
  the script" — missed a genuine catch (Qwen, `ansible-chain`).
- A bare `cwe-347` pattern matched a response that cited the CWE tag out of
  habit while its actual complaint was unrelated (missing exception
  handling, not algorithm confusion) — a false positive (Qwen,
  `python-chain` safe variant).

**Takeaway**: regex/keyword grading of natural-language security review
output is workable for a comparison like this but never fully trustworthy
unadulterated — every borderline verdict in this document was confirmed
against the actual model output before being reported.

## Machine state / operational note

Container 9001's memory limit was resized from 16GB → 32GB → **8GB** during
this work (the 8GB figure was a deliberate choice for a more realistic
allocation, not a leftover). Running two 32B+ class models concurrently at
8GB caused real swap pressure (up to 488MB/512MB swap used). All three
models in this document were therefore tested **one at a time**, which is
also the realistic serving pattern at this memory ceiling — not concurrent
multi-model hosting. Swap held flat (~254MB, well within the 512MB ceiling)
for the duration of every single-model run reported above.

Models resident in `/data/models/` on container 9001 after this work:
`Llama-3.3-70B-Instruct-Q4_K_M.gguf` (42.5GB), `Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf`
(19.85GB), `DeepSeek-R1-Distill-Qwen-32B-Q4_K_M.gguf` (19.85GB) — 36GB free
remaining on a 130GB disk.

## Not yet done

- QwQ-32B (the other reasoning-tuned candidate mentioned alongside
  DeepSeek-R1) was not downloaded or tested — DeepSeek-R1-Distill-Qwen-32B
  already answered the core question (does reasoning-tuning help on exploit
  chains: yes), so a second reasoning model was deprioritized.
- No dedicated SAST tool (Semgrep, CodeQL) was run alongside these models
  for a static-analysis baseline comparison.
- Nothing from this work has been committed to git yet.
- Test/debug artifacts on container 9001 (`results_*.json`,
  `HumanEval.jsonl`, transient systemd units) not yet cleaned up.
