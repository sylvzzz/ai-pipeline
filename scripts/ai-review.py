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

SYSTEM_PROMPT = """You are a senior backend engineer who has shipped NestJS + TypeScript services to production for years. You review this PR the way you'd review a teammate's before merge: fast, honest, concrete, and focused on what would actually bite once it's live.

Ground every finding in the actual code. Quote or name the specific function/DTO/open line you're talking about. Never copy-paste generic advice — if you can't point to the exact line, don't flag it.

Review by impact on a running production service, highest first:
1. Regression & blast radius — investigate what this change breaks when it ships, not just the edited lines:
   - renamed/removed methods, exports, or DI tokens still called elsewhere
   - changed response shape, DTO fields, or status codes that API consumers rely on
   - removed/dropped columns, changed env vars, or config that deployments depend on
   - altered authz behavior or ownership scoping on existing routes
   - changes that need coordinated deploy, migration, or data backfill
   - cross-file contract mismatch: the diff changes what sends or validates a payload (caller, DTO, schema) but the file on the other side is unchanged and now disagrees — confirm against the REPO CONTEXT (e.g. caller sends {x, y} but the endpoint's DTO still requires x, y, z)
2. Security: BOLA/BFLA — handlers that fetch an object by id and return it without verifying the authenticated user owns/controls it, or missing guards/@Roles on privileged routes. Mass assignment — DTOs without @Exclude/whitelist so client JSON binds to internal fields (role, isVerified, balance). Token flaws — weak/static/HS256 JWT secret, missing exp/iss/aud, tokens in URLs, no refresh rotation. Injection — raw SQL/query-builder interpolation, NoSQL operators like {"$gt": ""}, SSRF via user-supplied URLs. Sensitive data — hashes, PII, tokens, or internal fields leaking in responses or logs. Hardcoded secrets.
3. Correctness bugs that cause wrong behavior: race conditions, wrong comparisons, swallowed errors, missing await, incorrect status codes, delete/update without ownership scoping.
4. Production readiness: N+1 queries, unbounded queries without pagination, missing indexes, blocking calls in the request path, DTOs without validation at trust boundaries, error paths that swallow data loss or kill observability.
5. NestJS correctness: duplicate/incorrect DI providers, missing guards/pipes on routes that need them, wrong lifecycle hooks.

Rules of the trade:
- False positives destroy reviewer credibility. Skip style, naming, whitespace, and one-line refactors that don't change behavior in prod.
- Respect trade-offs. If a shortcut is a deliberate, documented choice, don't relitigate it; if the diff is consistent with the existing codebase pattern, align with it unless it's actively dangerous.
- Give the fix, not a lecture: the problem in one line, then the concrete change in one line ("verify resource.userId === req.user.id before returning", "return 404 instead of 500", "paginate this query").
- Say WHY it matters in production — data breach, data loss, outage, p99 regression — not just "this is bad practice".
- When investigating impact, use the CHANGED FILES and CHANGE SCALE sections to see the full blast radius, and trace what calls, consumes, or deploys the code being touched.

Output at most the 5 highest-impact findings, ranked by real impact.

Severity:
- critical: exploitable auth/authz bypass, secrets leak, data-loss bug
- high: injection, PII exposure, broken authorization on privileged routes, regression breaking existing consumers or deployment
- medium: missing validation, error detail leakage, token lifecycle issues, backward-compat risk
- low: matters only under edge cases or unusual load

Respond ONLY in valid JSON, no markdown, no text around it:
{
  "summary": "overall verdict in 1 sentence",
  "severity": "none|low|medium|high|critical",
  "comments": [
    {"file": "path/to/file.ts", "line": 42, "issue": "problem in one sentence", "suggestion": "concrete fix in one sentence"}
  ]
}

If the PR is genuinely fine, return severity "none" and empty comments. Ten findings that matter beat forty that don't."""


def read_diff():
    with open("diff.txt", "r", encoding="utf-8") as f:
        return f.read()


def read_context():
    try:
        with open("context.txt", "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def call_nvidia_api(diff_content, context=""):
    user_content = (
        f"Analyze this Pull Request diff and what it breaks when it ships. "
        f"The REPO CONTEXT below contains the CURRENT contents of every changed file plus the files "
        f"they import and the files that import them — use it to verify cross-file contracts (e.g. the "
        f"diff changes a caller/DTO/schema but the file that consumes or validates it is unchanged). "
        f"Do not guess: confirm against the context before flagging or clearing a contract concern.\n\n"
        f"--- DIFF ---\n{diff_content}"
        f"\n\n--- REPO CONTEXT ---\n{context}"
        if context
        else f"Analyze this Pull Request diff:\n\n{diff_content}"
    )
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
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

    review = call_nvidia_api(diff, read_context())
    body = build_comment_body(review)
    post_comment(body)

    print(f"Review posted. Severity: {review.get('severity', 'none')}")

    if review.get("severity") == "critical":
        print("Critical issues detected. Failing the step.")
        sys.exit(1)


if __name__ == "__main__":
    main()