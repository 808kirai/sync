# the agent's hands. each tool has a schema the model reads and a function the harness runs
# every path is checked against the workspace so the agent cannot reach anything else on the machine
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from pypdf import PdfReader

import measure
import render_resume

max_result_chars = 15000
skip_dirs = {".git", "node_modules", "__pycache__", "venvs", ".venv", "venv"}

schemas = [
    {
        "name": "measure_repos",
        "description": "Clone every public repo of the developer into repos/ and return commit counts, test function counts, head commits and last commit dates as JSON. Call this first, before checking any claim.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_files",
        "description": "List files under a folder of the workspace, recursively. Use it to find the portfolio pages or a repo's test files.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "folder relative to the workspace, e.g. myPortfolio"}},
            "required": ["path"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a text file from the workspace. Lines come back numbered as 'n| text'; the numbers are not part of the file. Read a file before editing it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "file relative to the workspace, e.g. myPortfolio/projects.html"},
                "offset": {"type": "integer", "description": "first line to return, starting at 1. default 1"},
                "limit": {"type": "integer", "description": "how many lines to return. default 400"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_files",
        "description": "Search text files under a workspace folder with a regular expression and return matching lines as path:line: text. Use it to find every place a number or project name appears.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "python regular expression"},
                "path": {"type": "string", "description": "folder relative to the workspace"},
            },
            "required": ["pattern", "path"],
        },
    },
    {
        "name": "edit_file",
        "description": "Replace one exact piece of text in a file under myPortfolio/, 808kirai/ or out/. old_text must appear exactly once, copied from read_file output without the line numbers. Include enough surrounding text to make it unique.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "file relative to the workspace"},
                "old_text": {"type": "string", "description": "the exact text to replace"},
                "new_text": {"type": "string", "description": "the replacement"},
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
    {
        "name": "write_file",
        "description": "Create or overwrite a file under out/. Use it for out/report.md and to create out/resume.md the first time. Change existing files with edit_file instead.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "file under out/, e.g. out/report.md"},
                "content": {"type": "string", "description": "the full file content"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "read_resume",
        "description": "Return the text of the developer's current resume pdf. Use it to check claims and to write out/resume.md when it does not exist yet.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "render_resume",
        "description": "Build out/resume.pdf from out/resume.md and return the page count. Call it after every change to out/resume.md; the result must be 1 page.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "pytest_collect",
        "description": "Install one repo's requirements in its own virtual environment and run pytest --collect-only to get the real test count, including parametrized cases. Slow, and the developer must approve it. Only call it when a claimed test count differs from measure_repos.",
        "input_schema": {
            "type": "object",
            "properties": {"repo": {"type": "string", "description": "repo name, e.g. Rahah"}},
            "required": ["repo"],
        },
    },
]

# tools with side effects the developer has to approve
needs_approval = {"pytest_collect"}
editable_roots = ("myPortfolio", "808kirai", "out")


class ToolError(Exception):
    pass


class Workspace:
    def __init__(self, root, repos, resume_pdf):
        self.root = Path(root).resolve()
        self.repos = repos
        self.resume_pdf = Path(resume_pdf)

    def path(self, rel, writable=False):
        p = (self.root / rel).resolve()
        if p != self.root and self.root not in p.parents:
            raise ToolError("that path is outside the workspace")
        top = p.relative_to(self.root).parts[:1]
        if writable and top and top[0] not in editable_roots:
            raise ToolError(f"you can only change files under {', '.join(editable_roots)}")
        return p

    def run(self, name, args):
        handler = getattr(self, f"tool_{name}", None)
        if handler is None:
            raise ToolError(f"unknown tool {name}")
        result = handler(**args)
        if len(result) > max_result_chars:
            result = result[:max_result_chars] + f"\n... cut at {max_result_chars} characters, narrow the request"
        return result

    def tool_measure_repos(self):
        return json.dumps(measure.measure_all(self.repos, self.root / "repos"), indent=1)

    def tool_list_files(self, path):
        base = self.path(path)
        if not base.is_dir():
            raise ToolError(f"{path} is not a folder")
        found = []
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in skip_dirs)
            found += [(Path(dirpath) / f).relative_to(self.root).as_posix() for f in sorted(filenames)]
        return "\n".join(found[:500]) + ("\n... more files not shown" if len(found) > 500 else "")

    def tool_read_file(self, path, offset=1, limit=400):
        p = self.path(path)
        if not p.is_file():
            raise ToolError(f"{path} does not exist")
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(offset, 1)
        chunk = lines[start - 1:start - 1 + limit]
        body = "\n".join(f"{n}| {line}" for n, line in enumerate(chunk, start))
        if start - 1 + limit < len(lines):
            body += f"\n... {len(lines)} lines in total, read on with offset={start + limit}"
        return body

    def tool_search_files(self, pattern, path):
        try:
            regex = re.compile(pattern)
        except re.error as e:
            raise ToolError(f"bad regular expression: {e}")
        base = self.path(path)
        hits = []
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in skip_dirs)
            for f in sorted(filenames):
                p = Path(dirpath) / f
                try:
                    text = p.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                for n, line in enumerate(text.splitlines(), 1):
                    if regex.search(line):
                        hits.append(f"{p.relative_to(self.root).as_posix()}:{n}: {line.strip()[:200]}")
        return "\n".join(hits[:300]) or "no matches"

    def tool_edit_file(self, path, old_text, new_text):
        p = self.path(path, writable=True)
        if not p.is_file():
            raise ToolError(f"{path} does not exist")
        raw = p.read_bytes()
        text = raw.decode("utf-8").replace("\r\n", "\n")
        count = text.count(old_text)
        if count != 1:
            raise ToolError(f"old_text appears {count} times, it must appear exactly once")
        # keep the file's own line endings
        newline = "\r\n" if b"\r\n" in raw else "\n"
        p.write_text(text.replace(old_text, new_text), encoding="utf-8", newline=newline)
        return f"edited {path}"

    def tool_write_file(self, path, content):
        p = self.path(path, writable=True)
        if p.relative_to(self.root).parts[0] != "out":
            raise ToolError("write_file only works under out/, use edit_file for other files")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8", newline="\n")
        return f"wrote {path}"

    def tool_read_resume(self):
        text = "\n".join(page.extract_text() for page in PdfReader(str(self.resume_pdf)).pages)
        # the current pdf stores its bullets as a control character
        return text.replace("\x7f", "-")

    def tool_render_resume(self):
        md = self.root / "out" / "resume.md"
        if not md.exists():
            raise ToolError("out/resume.md does not exist yet")
        pages = render_resume.render(md, self.root / "out" / "resume.pdf")
        return f"out/resume.pdf has {pages} page(s)" + ("" if pages == 1 else ", it must be 1, tighten the wording")

    def tool_pytest_collect(self, repo):
        if repo not in self.repos:
            raise ToolError(f"{repo} is not one of the public repos")
        repo_dir = self.root / "repos" / repo
        if not repo_dir.exists():
            raise ToolError("run measure_repos first")
        venv = self.root / "venvs" / repo
        python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        steps = [[sys.executable, "-m", "venv", str(venv)], [str(python), "-m", "pip", "install", "-q", "pytest"]]
        if (repo_dir / "requirements.txt").exists():
            steps.append([str(python), "-m", "pip", "install", "-q", "-r", "requirements.txt"])
        steps.append([str(python), "-m", "pytest", "--collect-only", "-q"])
        out = ""
        for step in steps:
            try:
                done = subprocess.run(step, cwd=repo_dir, capture_output=True, text=True, timeout=600)
            except subprocess.TimeoutExpired:
                raise ToolError(f"timed out on: {' '.join(step[-3:])}")
            out = done.stdout + done.stderr
            # setup steps must pass, the collect step returns its output even with errors
            if done.returncode != 0 and step is not steps[-1]:
                raise ToolError(f"failed on {' '.join(step[-3:])}:\n{out[-2000:]}")
        # the summary line is at the end, the collected ids above it are noise
        return out[-3000:]
