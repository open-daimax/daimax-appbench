# samples/

Copy-and-learn examples for getting started with the `evalapp` evaluation tool.
Everything here is **synthetic and self-contained** — no real API keys, internal
URLs, or proprietary data. Use these files as templates and references; nothing in
this directory is loaded by the tool automatically.

## What's inside

| Path | What it is | How to use it |
|------|------------|---------------|
| [`config/evalapp.yaml.minimal`](config/evalapp.yaml.minimal) | The smallest working config — just platforms and the two AI model slots, with every field commented. | `cp config/evalapp.yaml.minimal ../evalapp.yaml`, then fill in the API keys (or set the matching env vars). For all options see the repo-root `evalapp.yaml.example`. |
| [`dataset/demo/`](dataset/demo/) | One example evaluation sample (`meta.json` + a README) showing the dataset directory convention. | Read [`dataset/demo/README.md`](dataset/demo/README.md) to understand what a sample is and which fields a spec needs; mirror the layout when authoring a real sample under `dataset/V1` or `dataset/V2`. |
| [`reports/example_report.json`](reports/example_report.json) | A mock of the aggregated report the tool writes (`report/scores_summary.json`) — meta, summary, top-level metrics, and one fully worked per-sample result with E2E case outcomes. | Reference the structure when parsing or post-processing real report output. |

## Suggested path for a newcomer

1. **Understand the config** — open `config/evalapp.yaml.minimal` to see the minimum
   the tool needs to run, then compare against the full `evalapp.yaml.example`.
2. **Understand a sample** — read `dataset/demo/README.md` and `dataset/demo/meta.json`
   to learn how requirements are specified and how sample directories are laid out.
3. **Understand the output** — inspect `reports/example_report.json` to see the scores,
   platform results, and timestamps the tool emits, and how per-case E2E results roll
   up into the top-level metrics.

## Notes

- These examples are **not** part of the V1/V2 sample sets and are never picked up by
  an evaluation run — they are documentation-by-example.
- The production sample loader reads `sample.yaml`; the demo uses `meta.json` purely
  for readability. The field meanings are identical (see the demo README).
- Report values are mock numbers chosen to look realistic; they are not the result of
  any actual evaluation.
