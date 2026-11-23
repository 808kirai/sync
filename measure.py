# clones repos and counts what the agent checks claims against
# used by tools.py locally, and runs on its own inside the managed sandbox: python measure.py <repo> <repo> ...
import json
import re
import subprocess
import sys
from pathlib import Path

user = "808kirai"
test_def = re.compile(r"^\s*(async\s+)?def\s+test_\w*\s*\(", re.M)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def is_test_file(path):
    name = path.name
    return name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))


def measure(name, repos_dir):
    repo = Path(repos_dir) / name
    if not repo.exists():
        subprocess.run(["git", "clone", "--quiet", f"https://github.com/{user}/{name}.git", str(repo)], check=True)
    files = [p for p in repo.rglob("*.py") if is_test_file(p) and ".git" not in p.parts]
    per_file = {p.relative_to(repo).as_posix(): len(test_def.findall(p.read_text(errors="ignore"))) for p in files}
    return {
        "repo": name,
        "branch": git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
        "head": git(repo, "rev-parse", "--short", "HEAD"),
        "last_commit_date": git(repo, "log", "-1", "--format=%cs"),
        "commits": int(git(repo, "rev-list", "--count", "HEAD")),
        # plain def test_ count, parametrized cases are not expanded
        "test_functions": sum(per_file.values()),
        "test_files": per_file,
    }


def measure_all(names, repos_dir):
    Path(repos_dir).mkdir(parents=True, exist_ok=True)
    facts = []
    for name in names:
        try:
            facts.append(measure(name, repos_dir))
        except subprocess.CalledProcessError as e:
            facts.append({"repo": name, "error": (e.stderr or str(e)).strip()})
    return facts


def main():
    facts = measure_all(sys.argv[1:], "/workspace/repos")
    Path("/workspace/facts.json").write_text(json.dumps(facts, indent=2))
    print(json.dumps(facts, indent=2))


if __name__ == "__main__":
    main()
