# AI PR Review Action

A free, open-source GitHub Action that reviews pull requests using
[GitHub Models](https://docs.github.com/en/github-models) — no API key,
no hosting, no cost.

## Usage

Add this workflow to any repo you want reviewed:

```yaml
# .github/workflows/ai-review.yml
name: AI PR Review

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write
  models: read

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: muhammedshibilm/ai-pr-review-action@v1.2.0
        # optional inputs:
        # with:
        #   model: openai/gpt-4o
        #   max_diff_chars: 30000
        #   fail_on_error: "true"
        #   focus_areas: "bugs,security,tests"
        #   extra_ignore_patterns: "generated/,*.snap"
```

No secrets required — uses the built-in `GITHUB_TOKEN`.

## What's new in v1.2.0

- **Prioritized feedback** — reviews are now organized into 🚨 Must Fix,
  ⚠️ Should Fix, 💡 Suggestions, and ✅ Good, instead of one flat list.
- **Configurable focus areas** — choose which categories the review
  focuses on via the `focus_areas` input (bugs, security, edge-cases,
  readability, performance, tests).
- **Configurable ignore patterns** — add your own path patterns to skip
  via `extra_ignore_patterns`, on top of the built-in defaults.

## Inputs

| Input                    | Required | Default                                                     | Description                                                        |
|----------------------------|----------|----------------------------------------------------------------|----------------------------------------------------------------------|
| `model`                   | No       | `openai/gpt-4o-mini`                                          | Any model available via GitHub Models                                |
| `max_diff_chars`          | No       | `20000`                                                        | Diff is truncated beyond this to stay under model limits             |
| `fail_on_error`           | No       | `"false"`                                                      | If `"true"`, a review failure fails the whole check                  |
| `focus_areas`             | No       | `bugs,security,edge-cases,readability,performance,tests`      | Comma-separated list of what the review should focus on              |
| `extra_ignore_patterns`   | No       | `""`                                                           | Comma-separated extra path substrings to exclude from review         |
| `github_token`            | No       | `${{ github.token }}`                                          | Override only if you need a different token                          |

## How it works

1. Checks out the PR and fetches its diff via the GitHub API (falls back to
   per-file patches if the unified diff endpoint fails).
2. Filters out noisy files (lock files, generated/minified code, binaries,
   plus anything you add via `extra_ignore_patterns`).
3. Sends the filtered diff to a GitHub Models-hosted model with a
   review-focused prompt, scoped to your chosen `focus_areas`.
4. Posts a prioritized review as a comment — or updates its own previous
   comment if one already exists on this PR, so active PRs don't get
   spammed with duplicates on every push.

Requests to both the GitHub API and GitHub Models retry with exponential
backoff on rate limits (429) or transient server errors (5xx).

## Rate limits

GitHub Models' free tier has rate limits (roughly 10 requests/min, and a
daily cap that's higher for "mini" models than full-size ones). If you hit
limits, the action retries automatically; if it still fails, it logs
clearly and — by default — does not fail your CI check (`fail_on_error`).

## Contributing

Issues and PRs welcome! Ideas that would be great contributions:
- Inline comments on specific lines instead of one summary comment
- `/ai-review` comment-triggered mode as an alternative to automatic runs
- Support for additional GitHub Models

Found a bug or have an idea? Open an issue at
[github.com/muhammedshibilm/ai-pr-review-action/issues](https://github.com/muhammedshibilm/ai-pr-review-action/issues).

## License

MIT — see [LICENSE](./LICENSE).
