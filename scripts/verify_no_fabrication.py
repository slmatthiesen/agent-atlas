"""Gate for the build-gcp-dashboard skill: flag values that were typed in, not read.

It cannot prove a number is true. It finds the shapes fabrication takes — literal metrics
in markup, placeholder URLs, invented HTTP codes, eval results the harness could not have
produced, success-shaped fallbacks, leftover demo branding — so each one either gets a
named source or gets removed.

    python scripts/verify_no_fabrication.py                      # working tree vs main
    python scripts/verify_no_fabrication.py --head feat/x        # a committed branch
    python scripts/verify_no_fabrication.py --brand "Acme" --target ~/code/acme

FAIL = always wrong, exit 1. TRACE = must be paired with its source in the report.
"""
import argparse
import ast
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEMO_BRANDS = ("Meridian", "Horizon Realty", "Apex Clearing")
PAGES = ("business_portal.html", "agent_console.html")

PLACEHOLDER = re.compile(r"xxxx|your-project|example\.com|placeholder|lorem ipsum|TODO", re.IGNORECASE)
HTTP_CODE_IN_STATUS = re.compile(r"\b(ALLOWED|REFUSED|DENIED)\s*\(\s*\d{3}\b")
ABSOLUTE_HOME_PATH = re.compile(r"(/Users/|/home/|[A-Z]:\\\\Users\\\\)\w+")
FAKE_RUN_ID = re.compile(r"\brun_[a-z]+_\d{8}\b")
METRIC = re.compile(r"\$\d[\d,]*(\.\d+)?|\b\d+(\.\d+)?\s?%|\b\d{1,3}(,\d{3})+\b|\b\d{2,}\s+[A-Za-z]+")
LIVE_LABEL = re.compile(r"prov-badge live|\blive\b[^<]{0,40}(sink|feed|stream|telemetry)|●[^<]*\blive\b", re.IGNORECASE)
MASKED_FAILURE = [
    (re.compile(r"except[^:]*:\s*pass\b|except[^:]*:\s*$"), "broad except — confirm it re-raises or returns an error status"),
    (re.compile(r"max\(\s*0\.\d+\s*,"), "score floor — a floored score reads as a real match"),
    (re.compile(r"TokenCount\"?\s*:\s*\d+"), "hardcoded token usage"),
    (re.compile(r"\"(GROUNDED_)?SUCCESS\""), "success literal — confirm it is only reachable on success"),
]
GCP_RESOURCE = re.compile(r"run\.app|cloudfunctions\.net|gs://|Cloud Run|BigQuery|Cloud Function|Pub/Sub", re.IGNORECASE)
MODEL_NAME = re.compile(r"\b(claude|gemini|gpt|llama|mistral)[\w.-]*(\s[\d.]+)?(\s(pro|flash|lite|haiku|sonnet|opus))*", re.IGNORECASE)

findings: list[tuple[str, str, str]] = []


def flag(level: str, where: str, what: str) -> None:
    findings.append((level, where, what))


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True).stdout


def read(path: str, head: str | None) -> str | None:
    if head:
        try:
            return git("show", f"{head}:{path}")
        except subprocess.CalledProcessError:
            return None
    file = ROOT / path
    return file.read_text(encoding="utf-8") if file.exists() else None


def added_lines(base: str, head: str | None) -> list[tuple[str, int, str]]:
    """(file, line, text) for every line added since `base`, untracked files included."""
    out = git("diff", "-U0", base, *([head] if head else []))
    lines, current, lineno = [], "", 0
    for raw in out.splitlines():
        if raw.startswith("+++ "):
            current = raw[6:] if raw.startswith("+++ b/") else ""
        elif raw.startswith("@@"):
            lineno = int(re.search(r"\+(\d+)", raw).group(1))
        elif raw.startswith("+") and current:
            lines.append((current, lineno, raw[1:]))
            lineno += 1
    if not head:
        for path in git("ls-files", "--others", "--exclude-standard").splitlines():
            text = (ROOT / path).read_text(encoding="utf-8", errors="ignore")
            lines += [(path, i, t) for i, t in enumerate(text.splitlines(), 1)]
    return lines


def visible_text(line: str) -> str:
    """Text a reader sees: tag bodies and string literals, not attributes, CSS or SVG paths."""
    no_tags = re.sub(r"<[^>]*>", " ", line) if "<" in line else ""
    literals = " ".join(m.group(2) for m in re.finditer(r"([\"'`])(.*?)\1", line) if "<" not in line)
    return f"{no_tags} {literals}"


def check_added(lines: list[tuple[str, int, str]], target: pathlib.Path | None) -> None:
    for path, n, text in lines:
        where = f"{path}:{n}"
        if path == "scripts/verify_no_fabrication.py" or path.endswith(".md"):
            continue
        if PLACEHOLDER.search(text):
            flag("FAIL", where, f"placeholder: {text.strip()[:100]}")
        if ABSOLUTE_HOME_PATH.search(text):
            flag("FAIL", where, "absolute home-directory path — not portable, leaks a username")
        if FAKE_RUN_ID.search(text):
            flag("FAIL", where, f"literal run id {FAKE_RUN_ID.search(text).group()} — ids come from the run")
        if path.endswith(".html"):
            shown = visible_text(text)
            for m in METRIC.finditer(shown):
                flag("TRACE", where, f"literal metric '{m.group().strip()}' — name the query that produces it, or render it from the API")
            if LIVE_LABEL.search(text):
                flag("TRACE", where, "'live' label — name the wired source, or change it to 'sample'")
        if path.endswith(".py"):
            for pattern, why in MASKED_FAILURE:
                if pattern.search(text):
                    flag("TRACE", where, why)
        if target:
            for m in MODEL_NAME.finditer(text):
                name = m.group().strip()
                slug = re.sub(r"[\s.]+", "-", name.lower())
                if not target_mentions(target, name, slug):
                    flag("TRACE", where, f"model '{name}' not found in {target} — take model names from its code")


def target_mentions(target: pathlib.Path, *needles: str) -> bool:
    for needle in needles:
        hit = subprocess.run(["git", "-C", str(target), "grep", "-qiF", needle], capture_output=True, check=False)
        if hit.returncode == 0:
            return True
    return False


def check_catalog(path: pathlib.Path) -> None:
    if not path.exists():
        return
    for n, text in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        where = f"{path.name}:{n}"
        if PLACEHOLDER.search(text):
            flag("FAIL", where, f"placeholder: {text.strip()[:100]}")
        if HTTP_CODE_IN_STATUS.search(text):
            flag("FAIL", where, f"HTTP code in status '{text.strip()[:60]}' — IAM policy gives ALLOWED/REFUSED, not a response")
        if GCP_RESOURCE.search(text):
            flag("TRACE", where, f"GCP resource — cite the gcloud output that lists it: {text.strip()[:80]}")


def literal_assign(source: str, name: str):
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return node.value
    return None


def check_eval_results(head: str | None) -> None:
    results, harness, dataset = (read(p, head) for p in
                                 ("evals/results/latest.json", "evals/run_eval.py", "evals/dataset.py"))
    if not (results and harness and dataset):
        return
    payload = json.loads(results)
    tasks = literal_assign(harness, "TASKS")
    runnable = {k.value: v.elts[1].args[0].id for k, v in zip(tasks.keys, tasks.values)}
    priced = set(ast.literal_eval(literal_assign(harness, "PRICING")))
    case_ids = {name: {c["id"] for c in ast.literal_eval(literal_assign(dataset, name))}
                for name in runnable.values()}
    for task, body in payload.get("tasks", {}).items():
        where = f"evals/results/latest.json:{task}"
        if task not in runnable:
            flag("FAIL", where, "task is not in run_eval.py TASKS — the harness cannot have produced it")
            continue
        ids = case_ids[runnable[task]]
        if body.get("cases") != len(ids):
            flag("FAIL", where, f"cases={body.get('cases')} but dataset has {len(ids)}")
        for model, stats in body.get("models", {}).items():
            if model not in priced:
                flag("FAIL", where, f"model {model} is not in run_eval.py PRICING")
            for case in set(stats.get("failed_cases", [])) - ids:
                flag("FAIL", where, f"failed case '{case}' does not exist in evals/dataset.py")


def check_brand(brand: str, head: str | None) -> None:
    for page in PAGES:
        html = read(page, head) or ""
        if brand.lower() not in html.lower():
            flag("FAIL", page, f"brand '{brand}' never appears")
        heads = re.findall(r"<title>(.*?)</title>|<h1[^>]*>(.*?)</h1>", html)
        for demo in DEMO_BRANDS:
            if demo.lower() not in brand.lower() and any(demo.lower() in "".join(h).lower() for h in heads):
                flag("FAIL", page, f"<title>/<h1> still says '{demo}'")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="main", help="compare against this ref (default: main)")
    parser.add_argument("--head", help="check this ref instead of the working tree")
    parser.add_argument("--catalog", default=str(ROOT / "agents_catalog.json"))
    parser.add_argument("--brand", help="the target product's name; checks titles/headers")
    parser.add_argument("--target", type=pathlib.Path, help="target project checkout, for model-name checks")
    args = parser.parse_args()

    check_added(added_lines(args.base, args.head), args.target)
    check_catalog(pathlib.Path(args.catalog))
    check_eval_results(args.head)
    if args.brand:
        check_brand(args.brand, args.head)

    for level in ("FAIL", "TRACE"):
        for lvl, where, what in findings:
            if lvl == level:
                print(f"{lvl:5} {where}  {what}")
    fails = sum(1 for f in findings if f[0] == "FAIL")
    traces = len(findings) - fails
    print(f"\n{fails} FAIL, {traces} TRACE. Every TRACE needs a named source in the summary, or removal.")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
