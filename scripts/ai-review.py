import json
import os
import sys
import urllib.request
import urllib.error

NVIDIA_API_KEY = os.environ["NVIDIA_API_KEY"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
PR_NUMBER = os.environ["PR_NUMBER"]
REPO = os.environ["REPO"]

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
MODEL = "deepseek-ai/deepseek-v4-pro-0813"

SYSTEM_PROMPT = """You are a senior code reviewer specialized in NestJS, TypeScript, and REST API best practices, applying OWASP API Security Top 10 (2023).
Analyze the provided diff and focus ONLY on higher-impact issues. When scanning, check for these categories in priority order:

1. Security (treat as highest impact when present):
   - Broken Object/Function Level Authorization (BOLA/BFLA): handlers that fetch objects by id and return them without verifying the authenticated user owns/controls that resource; missing @Roles/@Public decorators, guards, or role checks on privileged routes
   - Mass assignment: DTOs that omit @Exclude or explicit whitelist so client JSON is bound to internal fields (role, isVerified, balance) — check @Exclude/@Expose and class-transformer whitelist:true
   - Broken authentication / token flaws: JWT signing with weak/HS256/static secret, missing exp/iss/aud claims, tokens in query strings, no refresh-token rotation, endpoints writeable without auth
   - Injection: raw SQL/query-builder interpolation, unvalidated input fed to queries, NoSQL operator injection ({{$gt: ""}}), SSRF via user-supplied URLs
   - Sensitive data exposure: password hashes, PII, tokens, or internal fields returned in API responses; verbose error messages leaking stack traces, DB queries, or internal paths
   - Hardcoded secrets/keys committed inline (API keys, DB URLs with credentials)
2. Bugs or incorrect logic that cause wrong behavior (race conditions, wrong comparisons, swallowed errors, missing await, incorrect status codes)
3. NestJS correctness violations (incorrect/duplicate DI providers, DTOs without class-validator decorators, missing guards/pipes on routes that need them, wrong lifecycle hooks)
4. Performance (N+1 queries, missing pagination, missing indexes, blocking calls in request path)

Do NOT report minor style/formatting issues (missing trailing newlines, whitespace, naming conventions, minor readability preferences, trivial refactors). These are not worth flagging.

Severity guidance:
- critical: exploitable auth/authz bypass, secrets leakage, data breach surface
- high: injection, data exposure of PII, broken authorization on privileged routes
- medium: missing validation, error details leakage, token lifecycle issues
- low: minor robustness issues

Be concise. Report at most the 5 most important findings, ranked by impact. Each issue and suggestion should be one short, concrete sentence that gives a specific fix (e.g. "Add a ownership check comparing req.user.id to resource.userId").

Respond ONLY in valid JSON, no markdown, no extra text, in this exact format:
{
  "summary": "overall summary in 1 sentence",
  "severity": "none|low|medium|high|critical",
  "comments": [
    {"file": "path/to/file.ts", "line": 42, "issue": "short description of the problem", "suggestion": "short suggested fix"}
  ]
}

If the diff has no meaningful issues, return severity "none" and empty comments. Quality over quantity — it's better to return fewer, high-value findings than to pad the list."""


def read_diff():
    with open("diff.txt", "r", encoding="utf-8") as f:
        return f.read()


def call_nvidia_api(diff_content):
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Analyze this Pull Request diff:\n\n{diff_content}"},
        ],
        "temperature": 0.2,
        "max_tokens": 1500,
        "chat_template_kwargs": {"thinking": False},
    }

    req = urllib.request.Request(
        NVIDIA_BASE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {NVIDIA_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=280) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"Error calling NVIDIA API: {e.code} {e.reason}")
        print(e.read().decode("utf-8"))
        sys.exit(1)

    text = data["choices"][0]["message"]["content"]
    clean = text.replace("```json", "").replace("```", "").strip()

    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        print("Warning: AI response is not valid JSON. Raw content:")
        print(text)
        return {"summary": "Could not parse the AI response.", "severity": "none", "comments": []}


def build_comment_body(review):
    severity_emoji = {
        "none": "✅",
        "low": "🟢",
        "medium": "🟡",
        "high": "🟠",
        "critical": "🔴",
    }
    severity = review.get("severity", "none")
    emoji = severity_emoji.get(severity, "")

    body = f"## 🤖 AI Code Review\n\n**Severity:** {emoji} {severity}\n\n{review.get('summary', '')}\n\n"

    comments = review.get("comments", [])
    if comments:
        body += "### Findings\n\n"
        for c in comments:
            file = c.get("file", "?")
            line = c.get("line")
            location = f"{file}:{line}" if line else file
            body += f"**`{location}`**\n- Issue: {c.get('issue', '')}\n- Suggestion: {c.get('suggestion', '')}\n\n"
    else:
        body += "_No relevant issues found._"

    return body


def post_comment(body):
    url = f"https://api.github.com/repos/{REPO}/issues/{PR_NUMBER}/comments"
    payload = json.dumps({"body": body}).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        print(f"Error posting comment on PR: {e.code} {e.reason}")
        print(e.read().decode("utf-8"))
        sys.exit(1)


def main():
    diff = read_diff()

    if not diff.strip():
        print("No relevant changes to analyze.")
        return

    review = call_nvidia_api(diff)
    body = build_comment_body(review)
    post_comment(body)

    print(f"Review posted. Severity: {review.get('severity', 'none')}")

    if review.get("severity") == "critical":
        print("Critical issues detected. Failing the step.")
        sys.exit(1)


if __name__ == "__main__":
    main()