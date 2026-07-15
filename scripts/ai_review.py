"""
AI PR review logic — powered by free GitHub Models.

Called by action.yml. Reads its configuration entirely from environment
variables set by the composite action, so it works the same whether it's
run directly or referenced as `uses: your-username/ai-pr-review-action@v1`
from someone else's workflow.

Required env vars (all provided automatically by action.yml):
  GITHUB_TOKEN    - used to read the PR diff, post comments, and call GitHub Models
  PR_NUMBER       - pull request number
  REPO            - "owner/repo"
  MODEL           - GitHub Models model name, e.g. openai/gpt-4o-mini
  MAX_DIFF_CHARS  - truncation limit for the diff sent to the model
"""

import os
import sys
import requests

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
PR_NUMBER = os.environ["PR_NUMBER"]
REPO = os.environ["REPO"]
MODEL = os.environ.get("MODEL", "openai/gpt-4o-mini")
MAX_DIFF_CHARS = int(os.environ.get("MAX_DIFF_CHARS", "20000"))

GITHUB_API = "https://api.github.com"
MODELS_API = "https://models.github.ai/inference/chat/completions"

github_headers = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def get_pr_diff() -> str:
    url = f"{GITHUB_API}/repos/{REPO}/pulls/{PR_NUMBER}"
    headers = {**github_headers, "Accept": "application/vnd.github.v3.diff"}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    diff = resp.text
    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + "\n\n... [diff truncated for length] ..."
    return diff


def get_ai_review(diff: str) -> str:
    prompt = f"""You are an experienced software engineer reviewing a pull request.
Review ONLY the diff below. Be concise and specific.

Focus on:
- Bugs or correctness issues
- Security concerns
- Edge cases that may be missed
- Readability / maintainability
- Anything genuinely good, briefly

Skip nitpicks about formatting that a linter would catch.
Use markdown. If the diff looks fine, say so briefly instead of inventing issues.

Diff:
```diff
{diff}
```
"""
    resp = requests.post(
        MODELS_API,
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1200,
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def post_comment(body: str) -> None:
    url = f"{GITHUB_API}/repos/{REPO}/issues/{PR_NUMBER}/comments"
    comment = f"### 🤖 AI Review (via GitHub Models — {MODEL})\n\n{body}"
    resp = requests.post(url, headers=github_headers, json={"body": comment}, timeout=30)
    resp.raise_for_status()


def main():
    diff = get_pr_diff()
    if not diff.strip():
        post_comment("No changes detected in this diff.")
        return
    review = get_ai_review(diff)
    post_comment(review)


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        print(f"AI review failed: {e} — response body: {e.response.text}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"AI review failed: {e}", file=sys.stderr)
        sys.exit(1)
