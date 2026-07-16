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
FOCUS_AREAS_RAW = os.environ.get("FOCUS_AREAS", "bugs,security,edge-cases,readability,performance,tests")
EXTRA_IGNORE_PATTERNS_RAW = os.environ.get("EXTRA_IGNORE_PATTERNS", "")

GITHUB_API = "https://api.github.com"
MODELS_API = "https://models.github.ai/inference/chat/completions"
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3

# Marker so we can find & update our own previous comment instead of piling up new ones
COMMENT_MARKER = "<!-- ai-pr-review-action -->"

DEFAULT_IGNORED_PATH_PATTERNS = (
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "composer.lock",
    "Cargo.lock", "poetry.lock",
    ".min.js", ".min.css", ".map",
    "dist/", "build/", "vendor/", "node_modules/",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".ttf",
)

FOCUS_AREA_DESCRIPTIONS = {
    "bugs": "Bugs or correctness issues",
    "security": "Security vulnerabilities (e.g. injection, unsafe deserialization, secrets in code, auth issues)",
    "edge-cases": "Edge cases that may be missed (empty input, nulls, concurrency, boundary values)",
    "readability": "Readability and maintainability",
    "performance": "Performance concerns (e.g. unnecessary loops, N+1 queries, inefficient algorithms)",
    "tests": "Missing or insufficient test coverage for the changes",
}

github_headers = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def get_ignored_patterns() -> tuple:
    extra = tuple(p.strip() for p in EXTRA_IGNORE_PATTERNS_RAW.split(",") if p.strip())
    return DEFAULT_IGNORED_PATH_PATTERNS + extra


def get_focus_descriptions() -> list:
    keys = [k.strip() for k in FOCUS_AREAS_RAW.split(",") if k.strip()]
    descriptions = [FOCUS_AREA_DESCRIPTIONS[k] for k in keys if k in FOCUS_AREA_DESCRIPTIONS]
    unknown = [k for k in keys if k not in FOCUS_AREA_DESCRIPTIONS]
    if unknown:
        print(f"Warning: ignoring unknown focus_areas: {unknown}", file=sys.stderr)
    return descriptions or list(FOCUS_AREA_DESCRIPTIONS.values())


def request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    last_exc = None
    resp = None
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
    return resp


def is_ignored_path(path: str) -> bool:
    return any(pattern in path for pattern in get_ignored_patterns())


def get_pr_diff() -> str:
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


def build_prompt(diff: str) -> str:
    focus_list = "\n".join(f"- {desc}" for desc in get_focus_descriptions())
    return f"""You are an experienced software engineer reviewing a pull request.
Review ONLY the diff below. Be concise and specific, and reference file names
and line numbers from the diff where possible.

Focus areas for this review:
{focus_list}

Organize your response into exactly these four sections, using markdown
headers. Omit a section entirely if it has nothing to report (don't write
"none" — just skip it):

### 🚨 Must Fix
Critical issues that should block merging (bugs, security holes, broken logic).

### ⚠️ Should Fix
Real problems that aren't urgent but should be addressed soon.

### 💡 Suggestions
Optional improvements — style, minor readability, nice-to-haves.

### ✅ Good
Brief, genuine positives worth calling out. Skip generic praise.

If the diff looks clean, keep the response short and say so briefly instead
of inventing issues.

Diff:
```diff
{diff}
```
"""


def get_ai_review(diff: str) -> str:
    resp = request_with_retry(
        "POST",
        MODELS_API,
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": build_prompt(diff)}],
            "max_tokens": 1500,
        },
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def find_existing_review_comment_id():
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