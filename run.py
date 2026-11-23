# one sync run: start a session, watch it work, download what it made, then apply what you approve
# usage: python run.py ["what to add or change"] [--budget 300] [--resume path.pdf]
import argparse
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

import anthropic

import config
from review import ask, review


def public_repos():
    out = subprocess.run(
        ["gh", "repo", "list", config.github_user, "--limit", "100", "--json", "name,isPrivate,isFork"],
        capture_output=True, text=True, check=True,
    ).stdout
    return sorted(r["name"] for r in json.loads(out) if not r["isPrivate"] and not r["isFork"])


def latest_resume():
    pdfs = sorted(config.downloads.glob("Rooney_James_Owino_Resume*.pdf"), key=lambda p: p.stat().st_mtime)
    return pdfs[-1] if pdfs else None


def upload(client, path, name):
    with open(path, "rb") as f:
        return client.beta.files.upload(file=(name, f))


def task_text(repos, note):
    text = (
        f"today is {datetime.now():%Y-%m-%d}. check the resume, the github profile readme and the portfolio site "
        f"against these public repos: {', '.join(repos)}. fix what is out of date and write the deliverables."
    )
    if note:
        text += f"\n\nthe developer also asked for this: {note}"
    return text


def short(value, n=100):
    value = " ".join(str(value).split())
    return value if len(value) <= n else value[: n - 3] + "..."


def watch(client, session_id, outcome):
    with client.beta.sessions.events.stream(session_id=session_id) as stream:
        # stream first, then kick off, so no early events are missed
        client.beta.sessions.events.send(session_id=session_id, events=[outcome])
        for event in stream:
            if event.type == "agent.message":
                for block in event.content:
                    if block.type == "text":
                        print(block.text, end="", flush=True)
                print()
            elif event.type == "agent.tool_use":
                detail = event.input.get("command") or event.input.get("file_path") or event.input
                print(f"  [{event.name}] {short(detail)}")
                if event.evaluated_permission == "ask":
                    result = "allow" if ask(f"  allow this {event.name} call?") else "deny"
                    client.beta.sessions.events.send(
                        session_id=session_id,
                        events=[{"type": "user.tool_confirmation", "tool_use_id": event.id, "result": result}],
                    )
                elif event.evaluated_permission == "deny":
                    print("  denied by the server as high risk")
            elif event.type == "span.outcome_evaluation_end":
                print(f"\n-- grader, round {event.iteration + 1}: {event.result}\n{event.explanation}\n")
            elif event.type == "session.error":
                print(f"\n-- session error: {event}")
            elif event.type == "session.status_idle":
                if event.stop_reason.type == "budget_reached":
                    print("\n-- stopped at the budget cap, outputs so far are below")
                    return
                if event.stop_reason.type != "requires_action":
                    return
            elif event.type == "session.status_terminated":
                print("\n-- session terminated")
                return


def download_outputs(client, session_id, run_dir):
    run_dir.mkdir(parents=True, exist_ok=True)
    files = []
    # outputs take a few seconds to show up after the session goes idle
    for _ in range(5):
        files = list(client.beta.files.list(scope_id=session_id, betas=["managed-agents-2026-04-01"]))
        if files:
            break
        time.sleep(3)
    for f in files:
        client.beta.files.download(f.id).write_to_file(run_dir / Path(f.filename).name)
    return sorted(p.name for p in run_dir.iterdir())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("note", nargs="?", default="", help="anything to add or change, in plain words")
    parser.add_argument("--budget", type=int, default=config.default_budget_cents, help="cap in us cents")
    parser.add_argument("--resume", type=Path, default=latest_resume())
    args = parser.parse_args()

    if not config.ids_file.exists():
        raise SystemExit("run python setup_agent.py first")
    if not args.resume or not args.resume.exists():
        raise SystemExit("could not find the resume pdf, pass it with --resume")
    ids = json.loads(config.ids_file.read_text())
    client = anthropic.Anthropic()

    repos = public_repos()
    print(f"repos: {', '.join(repos)}\nresume: {args.resume}\nbudget: ${args.budget / 100:.2f}")

    resources = [
        {"type": "file", "file_id": upload(client, args.resume, "resume.pdf").id, "mount_path": "/resume.pdf"},
        {"type": "file", "file_id": upload(client, config.project_dir / "measure.py", "measure.py").id, "mount_path": "/measure.py"},
    ]
    if config.resume_source.exists():
        resources.append({"type": "file", "file_id": upload(client, config.resume_source, "resume.md").id, "mount_path": "/resume.md"})

    session = client.beta.sessions.create(
        agent=ids["agent_id"],
        environment_id=ids["environment_id"],
        title=f"sync {datetime.now():%Y-%m-%d %H:%M}",
        resources=resources,
        budget={"type": "limit", "max_list_cost": {"amount": str(args.budget), "currency": "USD"}},
    )
    print(f"watch it live: https://platform.claude.com/workspaces/default/sessions/{session.id}\n")

    watch(client, session.id, {
        "type": "user.define_outcome",
        "description": task_text(repos, args.note),
        "rubric": {"type": "text", "content": config.rubric},
        "max_iterations": 2,
    })

    run_dir = config.runs_dir / f"{datetime.now():%Y-%m-%d_%H%M}"
    names = download_outputs(client, session.id, run_dir)
    print(f"\noutputs in {run_dir}: {', '.join(names) or 'none'}")
    if "report.md" in names:
        print(f"read the report first: {run_dir / 'report.md'}")

    review(run_dir)

if __name__ == "__main__":
    main()
