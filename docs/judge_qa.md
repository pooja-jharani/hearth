# Judge Q&A (honest answers)

**Is it running on Alexa+?** No. It is an MCP server plus an Agent Skill that an Alexa+ agent could call; the demo
uses a web app as the stand-in for voice. Say this first.

**Does the model decide conflicts?** No. A deterministic engine (`packages/family_conflicts`, 12 tests) finds clashes
and ranks fixes. The model only chooses tools and phrases replies.

**What if the model is wrong or hallucinates?** Changes go pending, then need a confirm, are audit-logged and undoable.
Tools return structured errors, never stack traces. Children cannot change adults' events.

**Is Bedrock/Polly used?** The code supports Strands + Bedrock, a plain Converse fallback and Polly. Not run live in
our tests: the default demo uses the scripted mock provider. Tests drive the real Strands path with a stub model.
Update this answer if you run it.

**Hindi?** The prompt and Polly language selection support Hindi. Mock mode is English only; Hindi needs live Bedrock
and has not been tested.

**Privacy?** Local SQLite, no accounts, no calendar scraping. .ics import/export is a file the family chooses.

**Why MCP?** One typed tool surface, usable by Alexa+, Claude, Kiro or the Streamlit app, with no per-client glue.

**What's next?** A real household pilot, Alexa+ integration, repeating events in .ics import (currently skipped).
