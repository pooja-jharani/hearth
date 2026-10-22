"""Look and feel: CSS, member chips, friendly time formatting."""
from __future__ import annotations

import html
from datetime import datetime

CSS = """
<style>
:root { --teal:#0F766E; --teal-soft:#E3F1EF; --red:#B42318; --red-soft:#FDECEA; --ink:#2B2B2B; --muted:#6B6B6B; }
html, body, [class*="css"] { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
#MainMenu, footer, [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"] { display:none !important; }
.block-container { padding-top: 1.2rem; padding-bottom: 6rem; max-width: 1180px; }
[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 12px; box-shadow: 0 1px 3px rgba(40,30,10,.08); background:#fff; }
h1.hearth { font-size: 1.7rem; font-weight: 700; margin:0; letter-spacing:-.01em; color: var(--teal); }
.tagline { color: var(--muted); font-size:.9rem; margin-top:-2px; }
.chip { display:inline-flex; align-items:center; justify-content:center; width:26px; height:26px; border-radius:50%;
        color:#fff; font-size:.72rem; font-weight:700; margin-right:6px; vertical-align:middle; }
.who { white-space:nowrap; margin-right:10px; font-size:.9rem; }
.banner { border-radius:12px; padding:.6rem .9rem; margin:.4rem 0 .8rem; font-size:.95rem; }
.banner.bad { background: var(--red-soft); color: var(--red); border:1px solid #F4C7C3; }
.banner.ok  { background: var(--teal-soft); color: var(--teal); border:1px solid #BFE0DB; }
.reply { background:#fff; border-radius:12px; padding:.9rem 1.1rem; box-shadow:0 1px 3px rgba(40,30,10,.08);
         font-size:1.08rem; line-height:1.45; border-left:4px solid var(--teal); }
.reply.empty { color: var(--muted); border-left-color:#D9D3C7; }
.card-title { font-weight:650; margin-bottom:.15rem; }
.card-sub { color: var(--muted); font-size:.88rem; }
.why { color: var(--red); font-weight:600; }
.pill { display:inline-block; padding:1px 9px; border-radius:999px; font-size:.75rem; font-weight:600;
        background: var(--teal-soft); color: var(--teal); margin-right:4px; }
.pill.red { background: var(--red-soft); color: var(--red); }
.bar { height:8px; border-radius:999px; background:#EAE4D8; overflow:hidden; }
.bar > span { display:block; height:100%; background: var(--teal); }
.stButton > button { border-radius:10px; font-weight:600; }

.lanes { background:#fff; border-radius:12px; box-shadow:0 1px 3px rgba(40,30,10,.08); padding:.6rem .7rem .4rem; position:relative; }
.lanes-scroll { overflow-x:auto; }
.lanes-inner { position:relative; min-width:680px; }
.lanes.compact .lanes-inner { min-width:340px; }
.lanes.compact .lane-name { width:72px; font-size:.78rem; }
.lanes.compact .chip { width:22px; height:22px; font-size:.65rem; margin-right:4px; }
.lane-head, .lane { display:flex; align-items:stretch; }
.lane-name { width:var(--nw,96px); flex:none; font-size:.85rem; display:flex; align-items:center; padding-right:6px; white-space:nowrap; }
.lane-track { position:relative; flex:1; border-top:1px solid #EFE9DD; }
.lane-track.hdr { height:22px; border-top:none; }
.hr { position:absolute; transform:translateX(-50%); font-size:.7rem; color:var(--muted); white-space:nowrap; }
.grid { position:absolute; top:0; bottom:0; width:1px; background:#F1EDE6; }
.lbar { position:absolute; border-radius:7px; color:#fff; font-size:.78rem; font-weight:600; padding:0 7px; overflow:hidden;
       white-space:nowrap; text-overflow:ellipsis; line-height:24px; box-sizing:border-box; }
.lbar.clash { background:var(--red-soft); color:var(--red); border:2px solid var(--red); line-height:20px; }
.lbar.stripe { background:repeating-linear-gradient(45deg,#FDECEA,#FDECEA 6px,#F6C9C4 6px,#F6C9C4 12px) !important; }
.lbar.pending { opacity:.7; border:2px dashed #fff; line-height:20px; }
.now-line { position:absolute; top:0; bottom:0; width:2px; background:var(--teal); opacity:.8; }
@media (max-width: 760px) { .block-container { padding-left:.8rem; padding-right:.8rem; } h1.hearth { font-size:1.4rem; } }
</style>
"""

ELDER_CSS = """
<style>
html { font-size: 21px; }
.reply { font-size: 1.35rem; }
.stButton > button { min-height: 3rem; font-size: 1.1rem; }
[data-testid="stSidebar"] { display:none; }
</style>
"""


def esc(x) -> str:
    return html.escape(str(x))


def chip(name: str, members: dict[str, dict]) -> str:
    m = members.get(name, {})
    return (f'<span class="who"><span class="chip" style="background:{m.get("color", "#6B6B6B")}">'
            f'{esc(m.get("initials") or name[:1])}</span>{esc(name)}</span>')


def chips(names: list[str], members: dict[str, dict]) -> str:
    return "".join(chip(n, members) for n in names)


def when(iso: str, end_iso: str | None = None) -> str:
    s = datetime.fromisoformat(iso)
    text = f"{s.strftime('%a %d %b')}, {_t(s)}"
    if end_iso:
        e = datetime.fromisoformat(end_iso)
        text += f" – {_t(e)}"
    return text


def _t(d: datetime) -> str:
    h = d.hour % 12 or 12
    return f"{h}{'' if d.minute == 0 else f':{d.minute:02d}'} {'am' if d.hour < 12 else 'pm'}"
