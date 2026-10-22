# Hearth

**The family calendar that talks back and catches problems before they happen.**

Hearth is a self-hosted **MCP server** and **Agent Skill** that lets a whole family manage plans by voice or text,
enforces the family's own rules, and fixes clashes with one tap. Built for the Alexa+ track of the Amazon hackathon.

- **Standalone MCP server** (Streamable HTTP, spec 2025-11-25, `/mcp`) with 24 typed tools. Any MCP client can use it.
- **Deterministic conflict engine**, published as a separate package: [`family-conflicts`](packages/family_conflicts/README.md).
  Person clashes, coverage clashes (a child's event needs an adult), and rule violations, each with a plain-English *why*.
- **Learned family rules**: "Dadi can't do evening pickups" becomes a saved rule that is enforced later.
- **Fixes with Undo**: ranked options, confirm card, one-tap Undo. Changes never apply without confirmation.
- **Proactive Week Guard**, bulk add ("Tuesday gym at 7, Wednesday tuition 6 to 7..."), approval inbox for kids' events,
  circular import from pasted text, fair chores with the reason, planning-load report.
- **Streamlit app** acting as a real MCP client, with a Protocol Inspector showing the raw JSON-RPC.
- **Amazon**: Strands Agents SDK + Amazon Bedrock for the agent, Amazon Polly for spoken replies.

> **What is simulated:** there is no real Alexa+ device (Alexa+ tooling is partner-only). The web app acts as the MCP
> client; speaker chips (Mom, Dad, Rohan, Dadi) simulate voice profiles.
> The model never touches the database and never decides conflicts. Only the MCP tools do.

## Run it (one command)

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e .
cp .env.example .env          # LLM_PROVIDER=mock works offline; no AWS account needed
python run.py                 # seeds demo data, MCP server :8765 + app http://localhost:8501
```

`python run.py --server` runs only the MCP server; `python run.py --reset` wipes and re-seeds.
Use `HEARTH_NOW=2026-10-20T10:00:00+05:30` in `.env` to pin "today" for a repeatable demo.

### Use it from another MCP client
Point any Streamable HTTP client at `http://127.0.0.1:8765/mcp` and load
[`skills/family-coordinator`](skills/family-coordinator/SKILL.md) so the agent uses the tools well.

### Live Bedrock and Polly
Set `LLM_PROVIDER=bedrock`, `AWS_REGION`, `BEDROCK_MODEL` in `.env`, with AWS credentials configured and model access
enabled. Turn on "Speak replies" in the app sidebar. See [docs/aws_integration.md](docs/aws_integration.md).

## Demo script (under 3 minutes)
1. Mom: *"Tuesday gym at 7, Wednesday tuition 6 to 7, Friday Nani's birthday dinner"* -> three events.
2. Mom: *"Rohan's PTM is Thursday at 5 at school"*. Switch to Dad: *"I have a client call Thursday 5 to 6"* -> clash card.
3. **What can we do?** -> **Move it** -> **Yes, do it** -> **Undo** is shown.
4. Mom: *"Dadi can't do evening pickups"*, then *"Dadi will pick up Rohan from tuition Friday at 6"* -> rule enforced.
5. *"Any risks next week?"* -> Week Guard. Open **Under the hood** for the raw MCP traffic.

## Tests

```bash
pytest                      # 37 tests: engine, every MCP tool over real HTTP, golden demo, Ask-Dadi loop, Strands path, cards, lanes, .ics
python -m evals.run         # utterance -> tool eval (mock). Add --live for Bedrock
ruff check .
```

The Strands test runs the real Strands loop and Strands' MCP client against the real server with a stub model.
Mock-mode eval pass rates show the plumbing works; they are **not** a measure of model accuracy. Run `--live` for that.

## Layout
```
packages/family_conflicts/   open-source conflict engine (MIT)
server/                      MCP server, SQLite models, services, seed
app/                         Streamlit UI, agent (mock | Strands+Bedrock | Converse), voice, MCP client
skills/family-coordinator/   Agent Skill
tests/  evals/  docs/   # docs/demo_script.md and docs/judge_qa.md for the video and the judges
```

## Design notes
- Times are stored in UTC and shown in the family timezone (default Asia/Kolkata). Intervals are half-open.
- An event that needs an adult is covered if an adult attends it or a parent is free. If both parents are busy, the
  clash is reported and the fixes are ranked: move a parent's flexible event (keeping a 30 minute travel gap after a
  fixed event with a location), or ask a free adult such as Dadi to attend.
- If no end time or duration is given, one hour is assumed and the card says so.
- Child-created events wait in the approval inbox; children can't change adults' events.

MIT licensed. Pooja Jharani, 2026.
