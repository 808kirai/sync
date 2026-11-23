# our own harness: the loop that sends the task to claude, runs the tools it asks for and feeds the results back
# usage: python agent.py ["what to add or change"] [--budget 3.00] [--max-turns 60] [--resume path.pdf]
import argparse
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import anthropic

import config
import prompt
import render_resume
import tools
from review import ask, review
from run import latest_resume, public_repos

model = "claude-opus-5-5"
# usd per million tokens: input, output, cache read, cache write. estimates for the budget guard, the console has the real bill
prices = {
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
    "claude-opus-5": (5.00, 25.00, 0.50, 6.25),
}


def cost(response):
    p_in, p_out, p_read, p_write = prices.get(response.model, prices["claude-opus-5"])
    u = response.usage
    return ((u.input_tokens or 0) * p_in + (u.output_tokens or 0) * p_out
            + (u.cache_read_input_tokens or 0) * p_read + (u.cache_creation_input_tokens or 0) * p_write) / 1_000_000


def short(value, n=100):
    value = " ".join(str(value).split())
    return value if len(value) <= n else value[: n - 3] + "..."


def show(response):
    # thinking summaries make the plan visible, text is what claude says, tool_use is what it wants done
    for block in response.content:
        if block.type == "thinking" and block.thinking:
            print(f"  (thinking) {short(block.thinking, 300)}")
        elif block.type == "text" and block.text.strip():
            print(block.text.strip())
        elif block.type == "tool_use":
            detail = block.input.get("path") or block.input.get("repo") or block.input.get("pattern") or ""
            print(f"  [{block.name}] {short(detail)}")
        elif block.type == "fallback":
            print(f"  (the request was declined and {block.to.model} carried on)")


def run_tool(ws, block):
    # one tool call in, one tool_result out. errors go back to claude so it can change approach
    schema = next((s for s in tools.schemas if s["name"] == block.name), None)
    missing = [k for k in (schema or {}).get("input_schema", {}).get("required", []) if k not in block.input]
    try:
        if schema is None or missing:
            raise tools.ToolError(f"unknown tool or missing fields: {missing}")
        if block.name in tools.needs_approval and not ask(f"  allow {block.name} {json.dumps(block.input)}?"):
            raise tools.ToolError("the developer declined this call, carry on without it and say so in the report")
        return {"type": "tool_result", "tool_use_id": block.id, "content": ws.run(block.name, block.input)}
    except tools.ToolError as e:
        message = str(e)
    except Exception as e:
        message = f"{type(e).__name__}: {e}"
    print(f"    error: {short(message)}")
    return {"type": "tool_result", "tool_use_id": block.id, "content": message, "is_error": True}


def agent_loop(client, ws, task, budget, max_turns, log):
    messages = [{"role": "user", "content": task}]
    spent = 0.0
    for turn in range(1, max_turns + 1):
        if spent >= budget:
            print(f"\n-- stopped at the budget, about ${spent:.2f} spent")
            return spent
        response = client.beta.messages.create(
            model=model,
            max_tokens=16000,
            system=prompt.system_prompt,
            tools=tools.schemas,
            messages=messages,
            thinking={"type": "adaptive", "display": "summarized"},
            output_config={"effort": "medium"},
            # caches the growing conversation so each turn only pays full price for what is new
            cache_control={"type": "ephemeral"},
            # if a turn is declined by the safety classifiers, the api retries it on a fallback model
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        spent += cost(response)
        log.write(json.dumps({"turn": turn, "spent": round(spent, 4), "response": response.to_dict()}) + "\n")
        show(response)
        # the full content goes back unchanged, thinking blocks included, and history is never edited
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            print(f"\n-- done in {turn} turns, about ${spent:.2f}")
            return spent
        if response.stop_reason != "tool_use":
            print(f"\n-- stopped early: {response.stop_reason}")
            return spent

        results = [run_tool(ws, b) for b in response.content if b.type == "tool_use"]
        log.write(json.dumps({"turn": turn, "tool_results": results}) + "\n")
        # all results for one turn go back together in a single user message
        messages.append({"role": "user", "content": results})
    print(f"\n-- stopped at {max_turns} turns, about ${spent:.2f}")
    return spent


def prepare(run_dir):
    # the agent works on fresh clones, the real ones are only touched in review
    root = run_dir / "work"
    for name, local in config.clones.items():
        subprocess.run(["git", "clone", "--quiet", str(local), str(root / name)], check=True)
    (root / "out").mkdir(parents=True)
    if config.resume_source.exists():
        shutil.copy(config.resume_source, root / "out" / "resume.md")
    return root


def collect(root):
    # turn the agent's edits into patches, and drop the resume if it did not change
    out = root / "out"
    for name in config.clones:
        diff = subprocess.run(["git", "-C", str(root / name), "diff"], capture_output=True, check=True).stdout
        if diff.strip():
            (out / f"{name}.patch").write_bytes(diff)
    md, pdf = out / "resume.md", out / "resume.pdf"
    if md.exists():
        before = config.resume_source.read_text(encoding="utf-8") if config.resume_source.exists() else None
        if md.read_text(encoding="utf-8") == before:
            md.unlink()
            pdf.unlink(missing_ok=True)
        elif not pdf.exists() or pdf.stat().st_mtime < md.stat().st_mtime:
            render_resume.render(md, pdf)
    return out


def task_text(repos, note, has_resume_md):
    text = (
        f"today is {datetime.now():%Y-%m-%d}. check the resume, the github profile readme and the portfolio site "
        f"against these public repos: {', '.join(repos)}. fix what is out of date, then write out/report.md."
    )
    text += "\nout/resume.md already exists, edit it there." if has_resume_md else "\nout/resume.md does not exist yet."
    if note:
        text += f"\n\nthe developer also asked for this: {note}"
    return text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("note", nargs="?", default="", help="anything to add or change, in plain words")
    parser.add_argument("--budget", type=float, default=config.default_budget_cents / 100, help="stop at about this many usd")
    parser.add_argument("--max-turns", type=int, default=60)
    parser.add_argument("--resume", type=Path, default=latest_resume())
    args = parser.parse_args()
    if not args.resume or not args.resume.exists():
        raise SystemExit("could not find the resume pdf, pass it with --resume")

    repos = public_repos()
    run_dir = config.runs_dir / f"{datetime.now():%Y-%m-%d_%H%M}"
    root = prepare(run_dir)
    ws = tools.Workspace(root, repos, args.resume)
    print(f"repos: {', '.join(repos)}\nresume: {args.resume}\nbudget: about ${args.budget:.2f}\nworkspace: {root}\n")

    client = anthropic.Anthropic()
    with open(run_dir / "transcript.jsonl", "w", encoding="utf-8") as log:
        try:
            agent_loop(client, ws, task_text(repos, args.note, (root / "out" / "resume.md").exists()),
                       args.budget, args.max_turns, log)
        except KeyboardInterrupt:
            print("\n-- stopped by you, reviewing what was done so far")
        except anthropic.APIError as e:
            print(f"\n-- api error, reviewing what was done so far: {e}")

    out = collect(root)
    if (out / "report.md").exists():
        print(f"\nread the report first: {out / 'report.md'}")
    review(out)


if __name__ == "__main__":
    main()
