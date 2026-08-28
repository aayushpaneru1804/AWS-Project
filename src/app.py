"""FirstCommit Lambda application.

Repository facts are collected deterministically first. Amazon Bedrock can
interpret that evidence, but a model failure never makes the scanner unusable.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

import boto3


GITHUB_API = "https://api.github.com"
MAX_TREE_FILES = 700
MAX_FILE_BYTES = 18000
MAX_CONTEXT_CHARS = 55000
JSON_HEADERS = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}


def make_response(status: int, payload: Any, headers: dict[str, str] | None = None) -> dict[str, Any]:
    merged = {**JSON_HEADERS, **(headers or {})}
    body = payload if isinstance(payload, str) else json.dumps(payload)
    return {"statusCode": status, "headers": merged, "body": body}


def github_get(path: str) -> Any:
    request = Request(
        f"{GITHUB_API}{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "FirstCommit/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=12) as result:
            return json.loads(result.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return None


def parse_repository_url(repository_url: str) -> tuple[str, str] | None:
    parsed = urlparse(repository_url.strip())
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != "github.com":
        return None
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) != 2:
        return None
    owner, repo = parts
    repo = repo.removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", owner) or not re.fullmatch(r"[A-Za-z0-9_.-]+", repo):
        return None
    return owner, repo


def decode_github_file(data: Any) -> str:
    if not isinstance(data, dict) or data.get("encoding") != "base64":
        return ""
    try:
        return base64.b64decode(data.get("content", ""))[:MAX_FILE_BYTES].decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return ""


def get_file(owner: str, repo: str, path: str) -> str:
    return decode_github_file(github_get(f"/repos/{quote(owner)}/{quote(repo)}/contents/{quote(path, safe='/')}"))


def path_basename(path: str) -> str:
    return path.rsplit("/", 1)[-1].lower()


def is_manifest(name: str) -> bool:
    return name in {"package.json", "go.mod", "requirements.txt", "pyproject.toml", "cargo.toml", "pom.xml", "build.gradle", "composer.json", "gemfile", "mix.exs"}


def important_files(paths: list[str]) -> list[dict[str, str]]:
    reasons = {
        "readme": "Project purpose and setup",
        "contributing": "Contributor workflow and project conventions",
        "manifest": "Dependencies and development scripts",
        "docs": "Architecture and usage documentation",
        "entry": "Likely application entry point",
        "environment": "Local environment or infrastructure",
        "tests": "Existing tests and expected behavior",
    }
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for path in paths:
        name = path_basename(path)
        lower = path.lower()
        reason = ""
        if name.startswith("readme"):
            reason = reasons["readme"]
        elif name.startswith("contributing") or name in {"development.md", "code_of_conduct.md"}:
            reason = reasons["contributing"]
        elif is_manifest(name):
            reason = reasons["manifest"]
        elif name in {"docker-compose.yml", "docker-compose.yaml", "dockerfile", "sam.yml", "template.yaml"}:
            reason = reasons["environment"]
        elif name in {"main.go", "main.py", "main.ts", "main.js", "server.ts", "server.js", "app.py", "index.ts", "index.js"}:
            reason = reasons["entry"]
        elif "/tests/" in f"/{lower}/" or "/test/" in f"/{lower}/" or name.endswith("_test.go") or name.startswith("test_"):
            reason = reasons["tests"]
        elif lower.startswith("docs/"):
            reason = reasons["docs"]
        if reason and path not in seen:
            found.append({"path": path, "reason": reason})
            seen.add(path)
    priority = {reasons["readme"]: 0, reasons["contributing"]: 1, reasons["manifest"]: 2, reasons["docs"]: 3, reasons["entry"]: 4, reasons["environment"]: 5, reasons["tests"]: 6}
    return sorted(found, key=lambda item: (priority.get(item["reason"], 9), item["path"]))[:12]


def project_type(paths: list[str], languages: list[str]) -> str:
    lower = [path.lower() for path in paths]
    if any("terraform" in path or path.endswith(".tf") for path in lower):
        return "Infrastructure or cloud application"
    if any("dockerfile" in path or "docker-compose" in path for path in lower):
        return "Containerized application"
    if {"typescript", "javascript"}.intersection(language.lower() for language in languages) and any("src/" in path or "app/" in path for path in lower):
        return "Web application"
    if any(path_basename(path) in {"manage.py", "main.py", "pyproject.toml"} for path in lower):
        return "Python application"
    return "Open-source software project"


def architecture_areas(paths: list[str], languages: list[str]) -> list[dict[str, str]]:
    groups = [
        ("Frontend", ("frontend", "web", "ui", "client", "components"), "User-facing application code"),
        ("Backend", ("backend", "server", "api", "services", "handlers"), "Application logic and service endpoints"),
        ("Infrastructure", ("infra", "terraform", "deploy", "docker", ".github"), "Deployment and operational configuration"),
        ("Tests", ("test", "tests", "spec"), "Automated behavior and regression coverage"),
        ("Documentation", ("docs", "readme", "contributing"), "Project usage and contribution guidance"),
    ]
    lower_paths = [path.lower() for path in paths]
    areas = [{"name": name, "description": description} for name, markers, description in groups if any(any(marker in path for marker in markers) for path in lower_paths)]
    return (areas or [{"name": "Core project", "description": f"Primary source files, using {', '.join(languages[:3]) or 'multiple technologies'}"}])[:5]


def issue_difficulty(issue: dict[str, Any]) -> str:
    labels = {str(label.get("name", "")).lower() for label in issue.get("labels", []) if isinstance(label, dict)}
    title = str(issue.get("title", "")).lower()
    if labels.intersection({"good first issue", "beginner", "first-timers-only", "help wanted"}):
        return "Beginner"
    if labels.intersection({"advanced", "hard", "complex"}) or any(word in title for word in ("redesign", "migration", "performance")):
        return "Advanced"
    return "Intermediate"


def issue_files(issue: dict[str, Any], paths: list[str]) -> list[str]:
    haystack = f"{issue.get('title', '')} {issue.get('body', '')}".lower()
    tokens = [token for token in re.findall(r"[a-z0-9_-]{3,}", haystack) if token not in {"the", "and", "with", "this", "that", "from"}]
    matches: list[str] = []
    for path in paths:
        if any(token in path.lower() for token in tokens[:20]) and path not in matches:
            matches.append(path)
    return matches[:3]


def summarize_issues(issues: list[Any], paths: list[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for issue in issues:
        if not isinstance(issue, dict) or "pull_request" in issue:
            continue
        labels = [str(label.get("name")) for label in issue.get("labels", []) if isinstance(label, dict) and label.get("name")]
        level = issue_difficulty(issue)
        likely = issue_files(issue, paths)
        result.append({
            "number": issue.get("number"),
            "title": issue.get("title", "Untitled issue"),
            "url": issue.get("html_url", ""),
            "labels": labels[:5],
            "difficulty": level,
            "estimated_scope": "Small" if level == "Beginner" else "Medium" if level == "Intermediate" else "Large",
            "files_likely": likely or ["To be confirmed from the issue discussion"],
            "confidence": "High" if likely else "Medium",
            "explanation": "This issue appears approachable from the repository metadata and public discussion." if level == "Beginner" else "Review the surrounding module and tests before choosing this issue.",
        })
    return result[:6]


def readiness_score(experience: str, paths: list[str], issues: list[dict[str, Any]]) -> int:
    score = {"Beginner": 58, "Intermediate": 76, "Advanced": 88}.get(experience, 65)
    if any(path_basename(path).startswith("readme") for path in paths):
        score += 4
    if any("test" in path.lower() for path in paths):
        score += 4
    if issues:
        score += 3
    return min(score, 98)


def deterministic_analysis(repo: dict[str, Any], paths: list[str], contributing: str, issues: list[dict[str, Any]], experience: str, goal: str) -> dict[str, Any]:
    languages = list(repo.get("languages", {}).keys())
    important = important_files(paths)
    name = repo.get("full_name") or repo.get("name") or "this repository"
    description = repo.get("description") or f"{name} is an open-source project hosted on GitHub."
    reading_order = [item["path"] for item in important[:5]] or paths[:5] or ["Start with the repository README and contribution guide."]
    issue_summary = summarize_issues(issues, paths)
    return {
        "summary": description,
        "plain_language": f"Think of {name} as a project you can explore in small steps. Start with its documentation, trace one entry point, and use the tests to understand expected behavior.",
        "repository": {
            "name": name,
            "url": repo.get("html_url", ""),
            "primary_language": languages[0] if languages else repo.get("language") or "Not specified",
            "languages": languages[:8],
            "project_type": project_type(paths, languages),
            "complexity": experience if experience in {"Beginner", "Intermediate", "Advanced"} else "Intermediate",
            "stars": repo.get("stargazers_count", 0),
            "open_issues": repo.get("open_issues_count", 0),
            "license": (repo.get("license") or {}).get("spdx_id") if isinstance(repo.get("license"), dict) else None,
            "has_contributing": bool(contributing),
        },
        "architecture": architecture_areas(paths, languages),
        "important_files": important,
        "reading_order": reading_order,
        "issues": issue_summary,
        "learning_requirements": [
            f"Review the {languages[0]} project conventions" if languages else "Identify the main language and project conventions",
            "Run the existing tests before changing behavior" if any("test" in path.lower() for path in paths) else "Find the project's validation or test command",
            "Read the contribution guide before opening a pull request" if contributing else "Look for maintainer guidance before opening a pull request",
        ],
        "roadmap": [
            "Set up the development environment",
            f"Read {reading_order[0]}",
            "Trace one application entry point",
            "Run the existing checks",
            f"Choose a {goal.lower()} issue" if goal else "Choose a focused issue",
            "Make a small change and update tests",
            "Prepare a pull request that explains the change",
        ],
        "readiness_score": readiness_score(experience, paths, issue_summary),
        "source": "GitHub repository evidence",
    }


def build_context(repo: dict[str, Any], paths: list[str], readme: str, contributing: str, important: list[dict[str, str]], issues: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "repository": {key: repo.get(key) for key in ("full_name", "description", "language", "default_branch", "html_url", "stargazers_count", "open_issues_count")},
        "languages": repo.get("languages", {}),
        "structure": paths[:MAX_TREE_FILES],
        "documentation": {"readme": readme[:12000], "contributing": contributing[:8000]},
        "importantFiles": important,
        "issues": [{key: issue.get(key) for key in ("number", "title", "body", "labels", "html_url")} for issue in issues[:12]],
    }


def bedrock_text(prompt: str) -> str | None:
    if os.environ.get("ENABLE_BEDROCK", "true").lower() != "true":
        return None
    try:
        client = boto3.client("bedrock-runtime")
        payload = {
            "schemaVersion": "messages-v1",
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
            "inferenceConfig": {"max_new_tokens": 1800, "temperature": 0.2},
        }
        result = client.invoke_model(modelId=os.environ.get("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0"), body=json.dumps(payload), contentType="application/json", accept="application/json")
        decoded = json.loads(result["body"].read().decode("utf-8"))
        return decoded.get("output", {}).get("message", {}).get("content", [{}])[0].get("text")
    except Exception:
        return None


def parse_json_text(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    try:
        parsed = json.loads(text.strip())
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        try:
            parsed = json.loads(match.group(0)) if match else None
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None


def enrich_with_bedrock(analysis: dict[str, Any], context: dict[str, Any], experience: str, goal: str) -> dict[str, Any]:
    prompt = f"""You are FirstCommit, an open-source onboarding guide. Analyze only the repository evidence below. Never invent files, dependencies, or issue details. If evidence is incomplete, say so and use confidence Medium or Low. Return JSON only with these keys: summary (string), plain_language (string), architecture (array of objects with name and description), important_files (array of objects with path and reason), reading_order (array of strings), learning_requirements (array of strings), roadmap (array of strings), contribution_suggestions (array of strings). Keep it practical for a {experience} contributor whose goal is {goal}. Preserve deterministic file paths when supported by evidence.

Repository evidence:
{json.dumps(context, ensure_ascii=False)[:MAX_CONTEXT_CHARS]}"""
    generated = parse_json_text(bedrock_text(prompt))
    if not generated:
        return analysis
    for key in ("summary", "plain_language", "architecture", "important_files", "reading_order", "learning_requirements", "roadmap"):
        if generated.get(key):
            analysis[key] = generated[key]
    analysis["source"] = "GitHub repository evidence + Amazon Bedrock"
    return analysis


def fallback_answer(question: str, analysis: dict[str, Any]) -> str:
    question_lower = question.lower()
    files = analysis.get("important_files", [])
    if "auth" in question_lower:
        matches = [item["path"] for item in files if "auth" in item.get("path", "").lower()]
        if matches:
            return f"The scan found these likely authentication-related locations: {', '.join(matches)}. Treat this as a starting point and confirm by following the routes and tests."
        return "The scan did not identify an authentication file with high confidence. Start with the application entry point, route definitions, and configuration files."
    if "run" in question_lower or "local" in question_lower:
        return "Start with the README and project manifest. Look for setup, dev, start, test, or compose scripts, then run the smallest documented check before making a change."
    if "read" in question_lower or "file" in question_lower:
        order = analysis.get("reading_order", [])[:5]
        return f"The recommended reading order is: {' -> '.join(order)}." if order else "Start with README.md, the dependency manifest, the main entry point, and one nearby test."
    return "Start from the recommended reading order, then trace one user-facing flow into its service or API boundary. The issue cards show where a first contribution may fit."


def answer_question(question: str, analysis: dict[str, Any]) -> str:
    context = json.dumps({"repository": analysis.get("repository"), "summary": analysis.get("summary"), "architecture": analysis.get("architecture"), "important_files": analysis.get("important_files"), "reading_order": analysis.get("reading_order"), "issues": analysis.get("issues")}, ensure_ascii=False)[:MAX_CONTEXT_CHARS]
    prompt = f"Answer the contributor's question using only this FirstCommit repository analysis. Be concise, educational, and mention uncertainty when appropriate. Do not invent paths. Question: {question}\n\nAnalysis: {context}"
    return bedrock_text(prompt) or fallback_answer(question, analysis)


def save_scan(scan_id: str, analysis: dict[str, Any]) -> None:
    table_name = os.environ.get("SCANS_TABLE")
    if not table_name:
        return
    try:
        boto3.resource("dynamodb").Table(table_name).put_item(Item={"scan_id": scan_id, "created_at": datetime.now(timezone.utc).isoformat(), "repository": analysis.get("repository", {}).get("name", ""), "payload": json.dumps(analysis, ensure_ascii=False)})
    except Exception:
        pass


def load_scan(scan_id: str) -> dict[str, Any] | None:
    table_name = os.environ.get("SCANS_TABLE")
    if not table_name:
        return None
    try:
        item = boto3.resource("dynamodb").Table(table_name).get_item(Key={"scan_id": scan_id}).get("Item")
        return json.loads(item["payload"]) if item and item.get("payload") else None
    except Exception:
        return None


def scan_repository(body: dict[str, Any]) -> dict[str, Any]:
    parsed = parse_repository_url(str(body.get("repository_url", "")))
    if not parsed:
        raise ValueError("Enter a public GitHub URL in the form https://github.com/owner/repository")
    owner, repo = parsed
    metadata = github_get(f"/repos/{quote(owner)}/{quote(repo)}")
    if not isinstance(metadata, dict) or not metadata.get("full_name"):
        raise ValueError("GitHub could not find that public repository, or its API rate limit was reached.")
    languages = github_get(f"/repos/{quote(owner)}/{quote(repo)}/languages")
    metadata["languages"] = languages if isinstance(languages, dict) else {}
    branch = metadata.get("default_branch") or "main"
    tree_result = github_get(f"/repos/{quote(owner)}/{quote(repo)}/git/trees/{quote(branch)}?recursive=1")
    tree = tree_result.get("tree", []) if isinstance(tree_result, dict) else []
    paths = [str(item.get("path")) for item in tree if item.get("type") == "blob" and item.get("path")][:MAX_TREE_FILES]
    readme = get_file(owner, repo, "README.md") or get_file(owner, repo, "README.rst")
    contributing = get_file(owner, repo, "CONTRIBUTING.md") or get_file(owner, repo, "CONTRIBUTING.rst")
    issues = github_get(f"/repos/{quote(owner)}/{quote(repo)}/issues?state=open&per_page=15")
    issues = issues if isinstance(issues, list) else []
    experience = str(body.get("experience", "Intermediate"))
    goal = str(body.get("goal", "Make my first contribution"))
    analysis = deterministic_analysis(metadata, paths, contributing, issues, experience, goal)
    evidence = build_context(metadata, paths, readme, contributing, analysis["important_files"], issues)
    analysis = enrich_with_bedrock(analysis, evidence, experience, goal)
    analysis["scan_id"] = hashlib.sha256(f"{metadata['full_name']}:{uuid.uuid4()}".encode()).hexdigest()[:16]
    analysis["scanned_at"] = datetime.now(timezone.utc).isoformat()
    save_scan(analysis["scan_id"], analysis)
    return analysis


def request_body(event: dict[str, Any]) -> dict[str, Any]:
    body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")
    try:
        parsed = json.loads(body) if isinstance(body, str) else body
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_context = event.get("requestContext", {})
    method = str(event.get("httpMethod") or request_context.get("http", {}).get("method") or "GET").upper()
    path = str(event.get("rawPath") or event.get("path") or request_context.get("http", {}).get("path") or "/")
    if path.endswith("/") and path != "/":
        path = path[:-1]
    if method == "OPTIONS":
        return make_response(204, "", {"Content-Type": "text/plain"})
    if method == "GET" and path in {"", "/", "/index.html"}:
        try:
            html = (Path(__file__).parent / "web" / "index.html").read_text(encoding="utf-8")
            return make_response(200, html, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-cache"})
        except OSError:
            return make_response(500, {"error": "Web application asset is unavailable."})
    if method == "GET" and path == "/health":
        return make_response(200, {"ok": True, "service": "firstcommit"})
    if method == "POST" and path == "/scan":
        try:
            return make_response(200, scan_repository(request_body(event)))
        except ValueError as error:
            return make_response(400, {"error": str(error)})
        except Exception:
            return make_response(502, {"error": "The repository scan could not be completed. Please try again."})
    if method == "POST" and path == "/ask":
        body = request_body(event)
        question = str(body.get("question", "")).strip()
        if not question:
            return make_response(400, {"error": "Ask a question about the scanned repository."})
        analysis = body.get("analysis") if isinstance(body.get("analysis"), dict) else load_scan(str(body.get("scan_id", "")))
        if not analysis:
            return make_response(400, {"error": "Scan a repository before asking a question."})
        return make_response(200, {"answer": answer_question(question, analysis)})
    return make_response(404, {"error": "Not found"})

