# Agent Reliability Scorecard

A rubric for deciding whether an AI agent is ready for production. It scores eight dimensions from 0 to 5 and combines them into a weighted overall score. Every score should come with evidence: a file path, a trace id, a CI run.

`arkit template` writes the YAML to fill in, and `arkit report` renders it.

## Scoring scale

| Score | Meaning |
| --- | --- |
| 0 | Absent. No artifact, no practice. |
| 1 | Ad hoc. Tried once, not maintained. |
| 2 | Inconsistent. Exists for some flows and not others. |
| 3 | Adequate. Covers the happy path and the obvious edge cases. |
| 4 | Mature. Versioned, automated, owned and audited. |
| 5 | Exemplary. Continuously improved; failure modes are anticipated before they happen. |

A 3 on every dimension is the production bar. Below that, the system has failure modes nobody has addressed, and real traffic will find them.

## The eight dimensions

### 1. Eval coverage (20%)

How thoroughly is the agent's behaviour measured?

- [ ] Versioned golden eval set in source control
- [ ] Adversarial set aimed at known failure modes (jailbreaks, PII leakage, tool misuse)
- [ ] Per-step evals for multi-step agents, not only end to end
- [ ] LLM-judge scorers checked against a human-labelled sample, with the agreement rate reported
- [ ] Production samples feed back into the dataset

### 2. Regression detection (15%)

Will a bad prompt or model change be caught before users see it?

- [ ] Evals run in CI on every change to prompts, tools or models
- [ ] Merges blocked when results regress past a set threshold
- [ ] Results trended over time, not only pass or fail
- [ ] Model versions pinned; upgrades go through an eval comparison

### 3. Guardrails (15%)

Are inputs and outputs validated, and are tool calls bounded?

- [ ] Input: PII detection, prompt-injection detection, schema validation
- [ ] Output: schema validation, grounding checks where they can be verified, toxicity and safety
- [ ] Tool policy: allowed tools per agent role, argument validation, rate limits
- [ ] Human approval on high-stakes actions
- [ ] Every guardrail decision is logged and reviewable

### 4. Observability (15%)

Can you debug a failed conversation from a user report?

- [ ] Every model call, tool call and guardrail decision traced
- [ ] OpenTelemetry `gen_ai.*` semantic conventions used
- [ ] Traces linked to user, session and tenant ids
- [ ] Retention long enough to investigate (30 days or more of production traffic)
- [ ] AI traces and the rest of the system's telemetry viewable together

### 5. Cost controls (10%)

Is the bill predictable, and can you find leaks?

- [ ] Token and dollar accounting per request
- [ ] Cost attributed to tenant, feature and model
- [ ] Per-request budget enforced, soft or hard
- [ ] Cheaper model first, with escalation when confidence is low, where quality allows
- [ ] Prompt caching where it applies

### 6. Failure-mode mapping (10%)

Has the team written down what can go wrong?

- [ ] A failure-mode list (hallucination, tool failure, loops, cost runaway, provider outage and so on)
- [ ] A detection mechanism for each
- [ ] A mitigation or playbook for each
- [ ] Post-incident reviews update the list

### 7. Security and data handling (10%)

Would this pass a security review tomorrow?

- [ ] No PII or secrets in prompts unless redacted
- [ ] Least-privilege credentials for tools; no agent has more access than its job needs
- [ ] Audit log of every action an agent takes on user data
- [ ] Prompt injection treated as a real threat, for direct and indirect input
- [ ] Provider data handling configured (no-training settings, region pinning)
- [ ] Trap-class coverage scored with the sub-rubric below

### 8. Deployment and operations (5%)

Can the team ship and operate the agent safely?

- [ ] Infrastructure as code; prompts and tool configuration version-controlled
- [ ] Feature flags or staged rollouts for new agent behaviour
- [ ] An on-call runbook for AI-specific incidents (quality drop, latency, cost)
- [ ] A rollback that doesn't mean redeploying everything

## Overall score

```
overall = sum(dimension_score * weight)
```

| Overall | Verdict |
| --- | --- |
| Below 2.0 | Not production-ready. High risk of incident; don't scale traffic. |
| 2.0 to 2.9 | Pilot quality. Real users will hit visible problems. |
| 3.0 to 3.9 | Acceptable for non-critical workloads, with a plan for the known gaps. |
| 4.0 to 4.5 | Mature. Suitable for critical workloads with monitoring. |
| Above 4.5 | Rare. |

## Trap-class coverage (inside dimension 7)

Adapted from the [AI Agent Traps](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6372438) paper (Franklin et al., 2026). Score each class 0 to 5 on the scale above. A class at 0 or 1 is an attack surface nobody has measured, so don't read it as low risk. [trap-taxonomy.md](./trap-taxonomy.md) has the sub-traps and tags.

| Class | What a 3 looks like |
| --- | --- |
| Content injection (perception) | Adversarial cases cover hidden HTML or CSS, Markdown link payloads and at least one cloaking case; a scanner checks all externally sourced text before it reaches the model. |
| Semantic manipulation (reasoning) | Cases probe biased framing, critic evasion and persona hyperstition; a scorer flags unsupported authoritative framing in replies. |
| Cognitive state (memory and learning) | With RAG: a poisoning case is in the set and retrieval has a provenance check. With long-term memory: a regression test replays a latent-poisoning scenario. |
| Behavioural control (action) | Embedded-jailbreak, data-exfiltration and sub-agent-spawning cases are present; tool policy enforces an allowlist and human approval; forbidden arguments are listed. |
| Systemic (multi-agent) | For multi-agent systems, at least one sybil case and one compositional-fragment case. For a single agent, mark it N/A rather than 0. |
| Human in the loop (overseer) | Cases include urgency bait and automation bias; the review screen shows the reviewer the adversarial framing, not only the agent's recommendation. |

A 4 in a class means the cases are versioned, tagged, gated in CI with a per-class threshold (`arkit run --trap-fail-under`), and a matching guardrail or scorer is in place. A 5 adds production samples feeding that class's adversarial set.

## Where teams usually score low

A common picture: some evals exist, so eval coverage scores 2 or 3, but there's no CI gate (regression detection at 0 or 1) and no written failure-mode list (failure-mode mapping at 0 or 1). In that case, fix things in this order:

1. Pin prompt, tool and model versions
2. Run evals in CI
3. Write the failure-mode list
4. Add guardrails
5. Add tracing
6. Add cost controls
7. Write the runbook

Once versions are pinned and evals gate CI, every later change is measured, which makes each following step safer.
