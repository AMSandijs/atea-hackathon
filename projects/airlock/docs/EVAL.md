# Eval — Local AI Airlock

Almost no hackathon team measures anything. This is the differentiator, and with a
technical judge in the room it is what separates you from the other redaction pitches.
Build it before tuning detectors.

## Corpus

Eight to twelve files under `eval/corpus/`, realistic in shape, entirely invented in
content:

| File | Contains |
|---|---|
| `arm-template.json` | resource IDs, subscription GUID, resource names, a connection string in a setting |
| `main.bicep` | parameters, resource names, a tenant GUID |
| `alert-export.csv` | rule names, resource names, timestamps, a mix of prd and uat |
| `runbook.md` | prose with organisation names, person names, an FQDN, a step referencing a key vault |
| `ticket-thread.txt` | free text, informal, person names, a pasted error with a SAS token |
| `terraform.tfvars` | subscription ID, IPs, an IBAN in a billing comment |
| `app-settings.json` | connection strings, storage keys, endpoints |
| `incident-notes.md` | mixed prose and console output, a JWT, public IPs |
| `clean-docs.md` | **no** identifying content — Azure service names, SKUs, regions only. Measures false positives. |

**Invented organisations and people only.** Use names like `nordbro`, `meridian-logistics`,
`Lars Olesen` is fine as an invented person but must not correspond to a real contact.
Realistic shapes, fictional content. This is a hard rule — see `AGENTS.md`.

## Ground truth

`eval/seeds.yaml` records every planted identifier:

```yaml
- file: arm-template.json
  entity_type: AZURE_SUBSCRIPTION_ID
  text: 8f4c2b91-3d07-4a1e-b8c2-77e3a9d61f04
  offset: 412
  must_detect: true

- file: clean-docs.md
  entity_type: AZURE_REGION
  text: westeurope
  offset: 88
  must_detect: false        # a hit here is a false positive
```

Generate this file with a script when you build the corpus rather than maintaining
offsets by hand.

## Metrics

**Recall** — of the `must_detect: true` seeds, what fraction was found, and correctly
tiered. Report overall and per entity type. This is the headline number. Report the
misses explicitly, with file and offset; a team that shows its misses reads as honest,
a team that shows only a percentage reads as marketing.

**Precision** — of all findings, what fraction corresponds to a real seed. Hits in
`clean-docs.md` are pure false positives. Over-flagging is the quiet killer: it trains
users to click through the checkpoint without reading.

**Answer-quality delta** — run each of ten fixed questions twice, once through the
airlock and once directly, with the same cloud model. Record both answers. Judge each
pair as *equivalent*, *degraded but usable*, or *broken*. Report as a count, and be ready
to talk about the degraded ones. If a specific entity type keeps causing degradation,
that is an argument for moving it to `pass`, and saying so on stage is a strength.

**Added latency** — per stage: rules, entropy, model sweep, vault, rehydrate. Measured on
the actual presentation laptop, not a dev machine. Report the median and the worst case.

## Reporting

`airlock eval` writes `eval/results-<date>.json` and prints a summary table. The slide
is four numbers plus one line of honesty:

```
recall     94%   (47/50 seeds; 3 misses, all ORG_NAME in prose)
precision  88%   (6 false positives, 5 of them in clean-docs.md)
quality    9/10 equivalent, 1 degraded (resource-name convention question)
latency    +1.8s median, +4.1s worst
```

Then: *recall is not 100% and will never be 100%. That is why a human approves before
anything is sent.*

## Regression discipline

Once T8 exists, every detector change reruns the eval. If recall goes up but precision
falls off a cliff, that is a worse detector, not a better one. Keep each results file
committed so the trend is visible over the weekend.
