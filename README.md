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

      - uses: muhammedshibilm/ai-pr-review-action@v1.0.0
        # optional inputs:
        # with:
        #   model: openai/gpt-4o          # default: openai/gpt-4o-mini
        #   max_diff_chars: 30000          # default: 20000
```

That's it — no secrets to configure. It authenticates using the
`GITHUB_TOKEN` GitHub Actions already provides.

## Example output

Once installed, every pull request gets an automatic review comment like this:

![AI PR Review example](./docs/example-review.png)

## Inputs

| Input            | Required | Default              | Description                                      |
|-------------------|----------|-----------------------|--------------------------------------------------|
| `model`           | No       | `openai/gpt-4o-mini`  | Any model available via GitHub Models             |
| `max_diff_chars`  | No       | `20000`               | Diff is truncated beyond this to stay under model limits |
| `github_token`    | No       | `${{ github.token }}` | Override only if you need a different token       |

## How it works

1. Checks out the PR and fetches its diff via the GitHub API.
2. Sends the diff to a GitHub Models-hosted model with a review-focused prompt.
3. Posts the result as a comment on the pull request.

## Rate limits

GitHub Models' free tier has rate limits (roughly 10 requests/min, and a
daily cap that's higher for "mini" models than full-size ones). This is
usually plenty for typical PR volume. If you hit limits, the Action logs
will show the error clearly.

## Contributing

Issues and PRs welcome! Ideas that would be great contributions:
- Support for reviewing only changed files instead of the whole diff
- Inline comments on specific lines instead of one summary comment
- Configurable prompt / focus areas via input
- Support for additional GitHub Models

Found a bug or have an idea? Open an issue at
[github.com/muhammedshibilm/ai-pr-review-action/issues](https://github.com/muhammedshibilm/ai-pr-review-action/issues).

## License

MIT — see [LICENSE](./LICENSE).