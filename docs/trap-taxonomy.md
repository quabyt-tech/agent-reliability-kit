# Trap taxonomy

Adversarial cases are grouped by the six attack classes in the [AI Agent Traps](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6372438) paper (Franklin, Tomašev, Jacobs, Leibo and Osindero, SSRN, March 2026). Tagging each case with its class lets `arkit run` report and gate pass rates per class, instead of one adversarial pass rate that averages strong areas with weak ones.

## The six classes

| Class tag | Target | Sub-trap tags from the paper | Typical defences |
| --- | --- | --- | --- |
| `content_injection` | Perception: how raw input is parsed | `web_standard_obfuscation`, `dynamic_cloaking`, `steganographic_payload`, `syntactic_masking` | Scan fetched pages, documents and tool output for hidden text before the model sees it |
| `semantic_manipulation` | Reasoning | `biased_framing`, `critic_evasion`, `persona_hyperstition` | LLM-judge scorers for unsupported framing; prompt hardening |
| `cognitive_state` | Memory and learning | `rag_knowledge_poisoning`, `latent_memory_poisoning`, `contextual_learning` | Retrieval provenance checks (source allowlist, trust floor); memory-replay regression tests |
| `behavioural_control` | Actions | `embedded_jailbreak`, `data_exfiltration`, `sub_agent_spawning` | Tool allowlists, human approval, forbidden arguments, policies on generated SQL, code and commands |
| `systemic` | Multi-agent dynamics | `congestion`, `cascade`, `tacit_collusion`, `compositional_fragment`, `sybil` | Limits on spawn depth, fan-out and total agents; provenance on what agents pass each other |
| `human_in_the_loop` | The human reviewer | `cognitive_fatigue`, `automation_bias` | Scorers that check the agent's claims against ground truth; review screens that show the risky framing |

## Tagging

Give each adversarial case exactly one `trap:<class>` tag and one `subtrap:<sub>` tag. Other tags are free-form and only used for filtering (`arkit run --tag pii`).

```jsonl
{"id": "a-html-01", "input": {"message": "..."}, "tags": ["trap:content_injection", "subtrap:web_standard_obfuscation"]}
```

Class tags are a closed list, because they map to the paper and to the scorecard. Sub-trap tags are open: coverage is reported per class, so a domain-specific sub-trap such as `statement_stacking` for a SQL agent adds detail without changing what CI gates. Write down any sub-trap you add; a tag nobody documented is one nobody can audit against.

Edge cases that aren't attacks (empty input, hedged language) don't need trap tags. They're scored like golden cases.

## Coverage report

`arkit run` prints a table like this when any case carries a trap tag:

```
Trap class               Cases  Pass rate
content_injection            5    100% (5/5)
semantic_manipulation        4    100% (4/4)
cognitive_state              3     67% (2/3)
behavioural_control          6    100% (6/6)
```

With `--trap-fail-under 0.8`, the run fails if any class that has cases drops below 80%. Classes with no cases are left out of the gate, but they score low on the scorecard: no cases means the surface wasn't tested.

## Out of scope

- Training-time hardening, such as adversarial fine-tuning, is the model provider's job.
- Steganographic payloads in images need image-pipeline tooling; the tags exist so you can record cases, but the kit has no image scorer.
