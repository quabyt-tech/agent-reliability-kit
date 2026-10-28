# Contributing

Bug reports, new scorers and rubric improvements are all welcome.

## Set up

```bash
uv sync
uv run pytest
uv run ruff check . && uv run mypy src
```

## What we'll merge

- Fixes, with a test that fails without them.
- New scorers that need no new dependency, or put it behind an optional extra.
- Changes to the scorecard rubric or trap taxonomy, with the reasoning in the pull request. These change how teams are scored, so expect discussion.

Keep the core dependency list short. A scorer that needs a model takes it as a plain function (`prompt -> text`), so the kit never imports a provider SDK.

## Licence

By contributing you agree your contribution is licensed under Apache-2.0, as described in section 5 of the [LICENSE](LICENSE).
