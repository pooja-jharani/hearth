# AWS integration: where each call lives

| Service | Used for | Code | Verified how |
|---------|----------|------|--------------|
| Strands Agents SDK | agent loop; MCP tools from `tools/list` | `app/agent.py::_strands` | `tests/test_strands_path.py` runs the real Strands loop and Strands' MCP client against the real server with a stub model |
| Amazon Bedrock (Strands `BedrockModel`) | understand speech, choose tools | `app/agent.py::_strands` | **Not yet run**: needs your AWS account. Set `LLM_PROVIDER=bedrock`, then `python -m evals.run --live` |
| Amazon Bedrock Converse (fallback) | same loop without Strands | `app/agent.py::_converse` | **Not yet run** (same reason) |
| Amazon Polly | spoken replies (voice Kajal neural, Aditi fallback) | `app/voice.py` | **Not yet run** |
| Kiro | spec-driven dev | `docs/kiro/` | you must use it and keep screenshots |
| Amazon Devices Builder Tools | docs and guided setup in your coding assistant | n/a | you must use it and log it |

## Before the first live call
1. Set an AWS budget alert (credits are gone; check current pricing).
2. Enable model access for your chosen model in the Bedrock console and set `BEDROCK_MODEL` and `AWS_REGION` in `.env`.
3. `LLM_PROVIDER=bedrock python run.py`. Keep a screenshot of Bedrock usage as evidence.
4. If Strands fails to start, the app logs it and falls back to the Converse loop automatically.
