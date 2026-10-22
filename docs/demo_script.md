# Hearth demo script (target 2:30, limit is 3:00)

Everything below runs on the real MCP server and real tools. The Alexa+ device is **not** involved: the "voice" is the
text box (and Polly playback only if AWS credentials are set). Say so in the video.
Reset first: `python run.py --reset`. Set `HEARTH_NOW=2026-10-20T10:00:00+05:30` for a repeatable week.

| Time | Do | Say |
|---|---|---|
| 0:00 | Today tab, "Speaking as Mom" | "Every family has one person who holds the whole week in their head. Hearth moves it into an agent the whole family can talk to." |
| 0:15 | Type: *Tuesday gym at 7, Wednesday tuition 6 to 7, Friday Nani's birthday dinner* | "One sentence, three events, added through MCP tools." |
| 0:30 | Type: *Rohan's PTM is Thursday at 5 at school* | "The PTM needs an adult. Mom is covering it." |
| 0:45 | Switch to Dad: *I have a client call Thursday 5 to 6* | "Now both parents are busy. The clash is found by plain code, not by the model, so it never guesses." |
| 1:05 | *What can we do?* | "Ranked options, each with a reason." |
| 1:20 | Click **Ask Dadi** | "Nothing changes yet. Dadi gets a request." |
| 1:35 | Switch to Dadi, click **Yes, I'll go** | "She answers like a family member would. Clash gone, one tap to undo." |
| 1:55 | Switch to Mom: *Dadi can't do evening pickups* then *Dadi will pick up Rohan from tuition Friday at 6* | "A house rule, remembered and enforced on later plans." |
| 2:15 | *Who should do dishes?* | "Fair chores from the last two weeks of history." |
| 2:30 | Under the hood toggle, show the JSON-RPC | "Same server works from any MCP client, and Alexa+ is the voice front door we are designing for." |

Do not claim: a live Alexa+ skill, Bedrock results you did not run, user numbers, or a household pilot you did not do.
