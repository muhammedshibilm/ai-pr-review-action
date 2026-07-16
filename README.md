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

      - uses: muhammedshibilm/ai-pr-review-action@v1.1.0
        # optional inputs:
        # with:
        #   model: openai/gpt-4o          # default: openai/gpt-4o-mini
        #   max_diff_chars: 30000          # default: 20000
        #   fail_on_error: "true"          # default: "false" (non-blocking)
```

That's it — no secrets to configure. It authenticates using the
`GITHUB_TOKEN` GitHub Actions already provides.

## Example output

Once installed, every pull request gets an automatic review comment.
On later pushes to the same PR, the **same comment gets updated** instead
of a new one being posted each time — so active PRs don't get spammed.

## What it filters out

Lock files, minified/generated code, and binary/image assets are excluded
from what gets sent to the model — they add no review value and would
just eat into the diff size limit. See `IGNORED_PATH_PATTERNS` in
`scripts/ai_review.py` to customize.

## Inputs

| Input            | Required | Default              | Description                                      |
|-------------------|----------|-----------------------|--------------------------------------------------|
| `model`           | No       | `openai/gpt-4o-mini`  | Any model available via GitHub Models             |
| `max_diff_chars`  | No       | `20000`               | Diff is truncated beyond this to stay under model limits |
| `fail_on_error`   | No       | `"false"`             | If `"true"`, a review failure fails the whole check. Default is non-blocking — a rate limit or API hiccup won't block your merge. |
| `github_token`    | No       | `${{ github.token }}` | Override only if you need a different token       |

## How it works

1. Checks out the PR and fetches its diff via the GitHub API (falls back to
   per-file patches if the unified diff endpoint fails for any reason).
2. Filters out noisy files (lock files, generated/minified code, binaries).
3. Sends the filtered diff to a GitHub Models-hosted model with a
   review-focused prompt.
4. Posts the result as a comment on the pull request — or updates its own
   previous comment if one already exists on this PR.

Requests to both the GitHub API and GitHub Models retry with exponential
backoff on rate limits (429) or transient server errors (5xx).

## Rate limits

GitHub Models' free tier has rate limits (roughly 10 requests/min, and a
daily cap that's higher for "mini" models than full-size ones). This is
usually plenty for typical PR volume. If you hit limits, the action retries
automatically; if it still fails, it logs clearly and — by default — does
not fail your CI check (see `fail_on_error` above).

## Contributing

Issues and PRs welcome! Ideas that would be great contributions:
- Inline comments on specific lines instead of one summary comment
- Configurable prompt / focus areas via input
- Configurable ignore patterns via input (not just hardcoded)
- Support for additional GitHub Models

Found a bug or have an idea? Open an issue at
[github.com/muhammedshibilm/ai-pr-review-action/issues](https://github.com/muhammedshibilm/ai-pr-review-action/issues).

## License

MIT — see [LICENSE](./LICENSE).
