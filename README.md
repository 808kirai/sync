sync

sync is an agent that keeps my resume, GitHub profile README and portfolio site in line with what my repos actually contain. It checks every number and claim against the repos, fixes what is stale, and nothing reaches GitHub or my resume folder until I say yes.

There are two ways to run it. agent.py is our own harness, the loop is written by hand. run.py runs the same job on Claude Managed Agents, where Anthropic hosts the loop and a sandbox.

The parts of our own harness

- prompt.py - the instructions, fixed for the whole run so the prompt cache keeps hitting
- tools.py - what the agent can do. every path is locked to the run's workspace, repos/ is read only, and pytest_collect needs my yes
- agent.py - the loop. send the conversation, run the tools Claude asks for, send the results back, stop on end_turn, the budget or the turn limit
- measure.py - the counting, done in code so the numbers come out the same every run
- render_resume.py - turns resume.md into a one page pdf, same layout every time
- review.py - the checkpoint. shows each patch and the new resume and only applies what I approve

How a run works

- agent.py clones fresh copies of myPortfolio and the profile repo into runs/<date>/work/, so the real clones are untouched while it works
- Claude calls measure_repos, reads the resume, the profile README and the portfolio pages, and fixes what does not match
- it writes out/report.md with every claim, the claimed value, the measured value and the head commit
- the edits become git patches, and review.py asks before applying and staging each one in the real clones. nothing is committed or pushed
- a changed resume is saved as resume/resume.md and as the next numbered pdf in Downloads, old versions stay
- the whole conversation is saved to runs/<date>/transcript.jsonl

Setup

- pip install -r requirements.txt
- set ANTHROPIC_API_KEY
- gh has to be logged in, it lists the public repos

Running

- python agent.py - check everything and fix what is stale
- python agent.py "add my newest project to the portfolio" - same, plus a change in plain words
- python agent.py --budget 1.50 - stop at about this many dollars, default 3
- python setup_agent.py once, then python run.py - the managed version
