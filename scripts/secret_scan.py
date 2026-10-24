"""Pre-push secret scan: the gate Ash ordered before the public repo push.

Scans every file that would be committed (respects .gitignore patterns for
.env, .venv, data/, __pycache__) for secret-shaped values. Reports file,
line number, and pattern category only; it NEVER prints a matched value.
Exit 0 = clean. Exit 1 = findings to clear before pushing.

Run: .venv/bin/python scripts/secret_scan.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SKIP_DIRS = {".venv", "data", "__pycache__", ".git", "node_modules", ".pytest_cache"}
SKIP_FILES = {".env"}
SKIP_SUFFIXES = {".db", ".sqlite", ".pyc"}

PATTERNS = [
    ("paypal client secret assignment",
     re.compile(r'(?i)(paypal[_-]?client[_-]?secret|client[_-]?secret)\s*[:=]\s*["\']?[A-Za-z0-9_\-]{16,}')),
    ("llm api key assignment",
     re.compile(r'(?i)(llm[_-]?api[_-]?key|openai[_-]?api[_-]?key|api[_-]?key)\s*[:=]\s*["\']?(sk-|[A-Za-z0-9_\-]{20,})')),
    ("bearer token literal",
     re.compile(r'(?i)bearer\s+[A-Za-z0-9_\-\.]{20,}')),
    ("generic secret value assignment",
     re.compile(r'(?i)(secret|password|passwd|token)\s*[:=]\s*["\'][^"\']{8,}["\']')),
    ("private key block",
     re.compile(r'-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----')),
    ("paypal sandbox email with password",
     re.compile(r'sb-[a-z0-9]+@personal\.example\.com\s*/\s*\S+')),
]


def candidate_files():
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        if path.name in SKIP_FILES or path.suffix in SKIP_SUFFIXES:
            continue
        yield path


def main():
    findings = []
    scanned = 0
    for path in candidate_files():
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            continue
        scanned += 1
        rel = path.relative_to(ROOT)
        for lineno, line in enumerate(text.splitlines(), 1):
            for name, rx in PATTERNS:
                if rx.search(line):
                    findings.append(f"{rel}:{lineno}: {name}")
                    break
    print(f"scanned {scanned} files")
    if findings:
        print("FINDINGS (clear before pushing):")
        for f in findings:
            print(" ", f)
        return 1
    print("CLEAN: no secret-shaped values in committable files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
