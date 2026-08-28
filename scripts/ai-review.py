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

SYSTEM_PROMPT = """You are a senior code reviewer specialized in NestJS, TypeScript, and REST API best practices.
Analyze the provided diff and focus ONLY on higher-impact issues:
1. Bugs or incorrect logic that would cause wrong behavior
2. Security issues (input validation, data exposure, injection, hardcoded secrets)
3. NestJS best practice violations that affect correctness (incorrect DI, DTOs without validation, missing guards/pipes)
4. Performance issues (N+1 queries, missing pagination, etc.)

Do NOT report minor style/formatting issues (missing trailing newlines, whitespace, naming conventions, minor readability preferences). These are not worth flagging.

Be concise. Report at most the 5 most important findings, ranked by impact. Each issue and suggestion should be one short sentence.

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