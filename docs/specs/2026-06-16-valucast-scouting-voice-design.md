# ValuCast Scouting Voice — Standard + Generator Spec

> 2026-06-16. ValuCast-owned. This voice is **separate from Diamond Dynasties'
> scouting reports and the Dug Discord bot** — no shared persona, prompt, or ban
> module with DD/Dug. ValuCast reports sound like a sharp baseball analyst, not a
> clubhouse character and not a chatbot.

## Status

- **Voice standard: active now**, applied to ValuCast's existing *deterministic*
  card copy (the threshold-banked "ValuCast Read" in `web/prospect_percentiles.py`
  and the share-card PNG read in `app.py:_prospect_player_card_read`). That copy
  was already ~90% on-voice; the 2026-06-16 pass tightened the remaining filler
  (killed "is carrying", "usable … shape", "full green light", "changes games",
  trailing "right now", finance-jargon "priced in").
- **LLM generator: future build** (spec below). ValuCast has no LLM scouting
  report today. When one is built, this voice is its prompt foundation.

## The voice standard (canonical)

Write like a sharp baseball analyst, not a chatbot.

- Lead with the actual baseball read. Name the skill or risk in behavioral terms
  — what the player *does*, not a label.
- Mention the stat signal that caused the read (one or two, to anchor — never a
  recited stat line).
- Be direct about the flaw or risk. **No fake balance.** If the profile is good,
  say why. If it's limited, say why. Don't hedge into mush.
- Conviction when the data supports it. Have a lean. "Could go either way" is not
  a take.
- **No fake scouting certainty.** ValuCast reads from *stats*, not eyes. Prefer
  "the current stat shape" over pretending we watched the player. **Never invent
  velo, pitch shapes, swing mechanics, defensive grades, makeup, or scouting
  looks** — only fields that exist in the data.
- One confidence/risk sentence is enough. No repeated disclaimer stacks.
- Short, specific sentences. Vary rhythm so cards don't read templated.
- Baseball language: damage, chase, contact, swing-and-miss, approach, command,
  role risk, starter traits, relief risk, carrying tool, floor.

**Banned generic-AI / SaaS filler:** "game-changer", "it's important to note",
"unlock", "robust", "nuanced", "moving forward", "worth monitoring".
**Banned fantasy-site clichés:** "intriguing", "tantalizing", "sturdy
foundation", "upside is evident", "high-floor/high-ceiling" as a stock phrase,
"carrying skill" as a literal phrase.

**Guardrail against overcorrection:** dense and baseball-native, *not* "edgy human
writing." For repeatable card copy especially, stay clean and professional and
invent no texture.

### Report shape (LLM generator only)

Not a rigid template — the deterministic copy varies order by design, and the LLM
should too. The read should cover, in whatever order reads best:
1. The role/value read.
2. The strongest supporting stat signal.
3. The main risk or limiting factor.
4. (When the sample is thin/stale) one confidence/sample-context sentence.

Bad: "He has an intriguing profile and could be worth monitoring if everything
clicks."
Better: "The bat is carrying the profile right now. A .397 OBP with a
96th-percentile strikeout rate gives him a real everyday foundation, even if the
power is still more projection than proof."

Bad: "He can finish hitters, but strike throwing is the failure point."
Better: "The miss is real, but the strike throwing is dragging the role. A 13.3
K/9 keeps starter upside alive; a 6.2 BB/9 points toward bullpen risk unless the
command tightens."

## Future LLM generator spec (option 1 groundwork)

A net-new module in this repo (e.g. `scouting/report_generator.py` +
`scouting/voice.py`), wholly owned by ValuCast.

- **Inputs — ValuCast-owned data only.** Current stat line + percentiles, level/
  age context, sample size, availability/injury status, and (for prospects) the
  ValuCast prospect model signals already on the card. **No DD values, no DD
  ranks, no external rankings, no market values** in the prompt — same honesty
  boundary as the rest of ValuCast (DD is a comparison lens, never an input).
- **Prompt foundation:** the voice standard above, plus the data labeled so the
  model can't blend samples (current MLB line vs MiLB line vs projection, each
  tagged — mirror the discipline ValuCast's deterministic copy already enforces).
- **Anti-hallucination:** prompt rule that only data-present fields may be named;
  no velo/pitch-shape/mechanics/defense/makeup. Back it with a deterministic
  post-gen validator that (a) flags the banned phrase lists and (b) flags any
  number not present in the supplied data — a ValuCast-local validator, **not**
  DD's `scouting_validator.py`.
- **Honesty framing:** thin/stale/injured samples get the "current stat shape" +
  one confidence sentence, never silent pass-through of old data as current.
- **Gating:** ship behind a flag; spot-check against the deterministic copy before
  it becomes the default card read. The deterministic path stays as the fallback.

## Where the voice lives in code today

`web/prospect_percentiles.py` (`_hitter_parts`, `_pitcher_parts`,
`_sample_context`, `_no_sample_report`) and `app.py`
(`_prospect_player_card_read`, `_graphic_read_intro`, the callout helpers). These
are deterministic string banks — the voice is enforced by curating the literals,
not by a prompt. The honesty machinery (injured/stale/low-sample "confidence is
low" sentences) and the variation system (hash-stable choice + rank-rotation) are
load-bearing; keep them when editing copy.
