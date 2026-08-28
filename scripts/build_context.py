import os
import re
import sys

SRC_DIR = "src"
MAX_BYTES = 300_000

IMPORT_RE = re.compile(r"""(?:from\s+['"]|import\s*\(\s*['"])([^'"]+)['"]""")


def changed_files(base_ref):
    out = os.popen(f"git diff origin/{base_ref}...HEAD --name-only").read()
    return [f for f in out.splitlines() if f.strip()]


def resolve_import(importer_path, spec):
    if not spec.startswith("."):
        return None
    base = os.path.join(SRC_DIR, os.path.dirname(importer_path))
    cand = os.path.normpath(os.path.join(base, spec))
    for p in (
        cand,
        cand + ".ts",
        cand + ".tsx",
        cand + ".js",
        os.path.join(cand, "index.ts"),
        os.path.join(cand, "index.js"),
    ):
        if os.path.isfile(p):
            return os.path.relpath(p, SRC_DIR)
    return None


def local_imports(rel_path):
    try:
        with open(os.path.join(SRC_DIR, rel_path), encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return []
    return [r for spec in IMPORT_RE.findall(content) if (r := resolve_import(rel_path, spec))]


def build_importers(all_files):
    importers = {}
    for f in all_files:
        for dep in local_imports(f):
            importers.setdefault(dep, []).append(f)
    return importers


def gather(base_ref):
    changed = [f for f in changed_files(base_ref) if os.path.isfile(os.path.join(SRC_DIR, f))]
    all_src = []
    for root, _, files in os.walk(SRC_DIR):
        for name in files:
            if name.endswith((".ts", ".tsx", ".js")):
                all_src.append(os.path.relpath(os.path.join(root, name), SRC_DIR))
    importers = build_importers(all_src)

    ordered = []
    for f in changed:
        ordered.append(f)
        ordered.extend(local_imports(f))
        ordered.extend(importers.get(f, []))
    ordered = list(dict.fromkeys(ordered))

    sections, size, truncated = [], 0, None
    for f in ordered:
        try:
            content = open(os.path.join(SRC_DIR, f), encoding="utf-8").read()
        except OSError:
            continue
        if size + len(content) > MAX_BYTES:
            truncated = f
            break
        sections.append(f"### FILE: {f}\n{content}")
        size += len(content)
    return changed, sections, truncated


def write_context(base_ref):
    changed, sections, truncated = gather(base_ref)
    if not changed:
        return 0
    body = "\n".join(["=== CHANGED FILES (repo paths) ===", *changed, "", "=== REPO CONTEXT (current file contents) ===", ""])
    body += "\n\n\n".join(sections)
    if truncated:
        body += (
            f"\n\n[context truncated at {MAX_BYTES} bytes; not all related files were included. "
            f"First omitted: {truncated}]"
        )
    with open("context.txt", "w", encoding="utf-8") as f:
        f.write(body)
    return len(sections)


def main():
    write_context(os.environ["BASE_REF"])
    print("context.txt written")


def _selftest():
    os.makedirs("src/a", exist_ok=True)
    os.makedirs("src/a/dir", exist_ok=True)
    with open("src/a/b.ts", "w") as f:
        f.write("")
    with open("src/z.ts", "w") as f:
        f.write("")
    with open("src/a/dir/index.ts", "w") as f:
        f.write("")
    try:
        assert resolve_import("a/x.ts", "./b") == "a/b.ts"
        assert resolve_import("a/x.ts", "../z") == "z.ts"
        assert resolve_import("a/x.ts", "@nestjs/core") is None
        assert resolve_import("a/x.ts", "./dir") == "a/dir/index.ts"
        print("selftest ok")
    finally:
        os.remove("src/a/b.ts")
        os.remove("src/z.ts")
        os.remove("src/a/dir/index.ts")
        os.rmdir("src/a/dir")
        os.rmdir("src/a")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()