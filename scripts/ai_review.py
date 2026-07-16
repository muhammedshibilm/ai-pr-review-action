import os
import sys
import time
import requests

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
PR_NUMBER = os.environ["PR_NUMBER"]
REPO = os.environ["REPO"]
MODEL = os.environ.get("MODEL", "openai/gpt-4o-mini")
MAX_DIFF_CHARS = int(os.environ.get("MAX_DIFF_CHARS", "20000"))
FAIL_ON_ERROR = os.environ.get("FAIL_ON_ERROR", "false").lower() == "true"

GITHUB_API = "https://api.github.com"
MODELS_API = "https://models.github.ai/inference/chat/completions"
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3

# Marker so we can find & update our own previous comment instead of piling up new ones
COMMENT_MARKER = "<!-- ai-pr-review-action -->"

# Files that add noise but no review value — skipped before sending to the model
IGNORED_PATH_PATTERNS = (
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "composer.lock",
    "Cargo.lock", "poetry.lock",
    ".min.js", ".min.css", ".map",
    "dist/", "build/", "vendor/", "node_modules/",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".ttf",
)

github_headers = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    """Wraps requests with retry + exponential backoff on 429 / 5xx."""
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = 2 ** attempt
                print(f"Got {resp.status_code} from {url}, retrying in {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            return resp
        except requests.RequestException as e:
            last_exc = e
            wait = 2 ** attempt
            print(f"Request error ({e}), retrying in {wait}s...", file=sys.stderr)
            time.sleep(wait)
    if last_exc:
        raise last_exc
    return resp  # last response, even if it was a 429/5xx after exhausting retries


def is_ignored_path(path: str) -> bool:
    return any(pattern in path for pattern in IGNORED_PATH_PATTERNS)


def get_pr_diff() -> str:
    """Fetch the unified diff, filtering out noisy files. Falls back to
    per-file patches if the unified diff endpoint fails for any reason."""
    url = f"{GITHUB_API}/repos/{REPO}/pulls/{PR_NUMBER}"
    headers = {**github_headers, "Accept": "application/vnd.github.v3.diff"}
    resp = request_with_retry("GET", url, headers=headers)

    if resp.status_code == 200:
        diff = filter_diff_text(resp.text)
    else:
        print(f"Unified diff fetch failed ({resp.status_code}), falling back to per-file patches.", file=sys.stderr)
        diff = get_diff_from_files_endpoint()

    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + "\n\n... [diff truncated for length] ..."
    return diff


def filter_diff_text(diff_text: str) -> str:
    """Removes hunks for ignored files from a unified diff string."""
    lines = diff_text.split("\n")
    kept_lines = []
    skipping = False
    for line in lines:
        if line.startswith("diff --git"):
            skipping = is_ignored_path(line)
        if not skipping:
            kept_lines.append(line)
    return "\n".join(kept_lines)


def get_diff_from_files_endpoint() -> str:
    """Fallback: reconstruct a pseudo-diff from the /files endpoint's per-file patches."""
    files = []
    page = 1
    while True:
        resp = request_with_retry(
            "GET",
            f"{GITHUB_API}/repos/{REPO}/pulls/{PR_NUMBER}/files",
            headers=github_headers,
            params={"per_page": 100, "page": page},
        )
        resp.raise_for_status()
        batch = resp.json()
        files.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    parts = []
    for f in files:
        if is_ignored_path(f.get("filename", "")):
            continue
        patch = f.get("patch")
        if patch:
            parts.append(f"--- {f['filename']} ---\n{patch}")
    return "\n\n".join(parts)


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
    resp = request_with_retry(
        "POST",
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
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def find_existing_review_comment_id() -> int | None:
    """Looks for a previous comment from this bot on this PR, so we can update
    it instead of posting a new one each time."""
    page = 1
    while True:
        resp = request_with_retry(
            "GET",
            f"{GITHUB_API}/repos/{REPO}/issues/{PR_NUMBER}/comments",
            headers=github_headers,
            params={"per_page": 100, "page": page},
        )
        resp.raise_for_status()
        batch = resp.json()
        for comment in batch:
            if COMMENT_MARKER in comment.get("body", ""):
                return comment["id"]
        if len(batch) < 100:
            break
        page += 1
    return None


def post_or_update_comment(body: str) -> None:
    full_body = f"{COMMENT_MARKER}\n### 🤖 AI Review (via GitHub Models — {MODEL})\n\n{body}"
    existing_id = find_existing_review_comment_id()

    if existing_id:
        url = f"{GITHUB_API}/repos/{REPO}/issues/comments/{existing_id}"
        resp = request_with_retry("PATCH", url, headers=github_headers, json={"body": full_body})
    else:
        url = f"{GITHUB_API}/repos/{REPO}/issues/{PR_NUMBER}/comments"
        resp = request_with_retry("POST", url, headers=github_headers, json={"body": full_body})

    resp.raise_for_status()


def main():
    diff = get_pr_diff()
    if not diff.strip():
        post_or_update_comment("No reviewable changes detected (all changed files were filtered out or the diff was empty).")
        return
    review = get_ai_review(diff)
    post_or_update_comment(review)


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        body = e.response.text if e.response is not None else ""
        print(f"AI review failed: {e} — response body: {body}", file=sys.stderr)
        sys.exit(1 if FAIL_ON_ERROR else 0)
    except Exception as e:
        print(f"AI review failed: {e}", file=sys.stderr)
        sys.exit(1 if FAIL_ON_ERROR else 0)