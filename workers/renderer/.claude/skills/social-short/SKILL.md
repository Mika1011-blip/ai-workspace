---
name: social-short
description: The rules of a vertical social-media short (Reels/TikTok/Shorts) — hook, beats, captions, length — used both to make one and to review one.
---

# social-short

A vertical short: 9:16 (1080×1920), 20–60 s, watched with the sound off
first. Everything below is a rule the reviewer checks; a maker that can't
meet one says so in its summary instead of pretending.

## Hook — the first 2 seconds
- The first line on screen is the hook. It must land **by 2 s** and be
  readable in one glance (≤ 8 words).
- Pick **one** hook kind and name it in the script:
  - `question` — "Why does your cat …?"
  - `contrast` — "Everyone does X. Do Y."
  - `result-first` — show the end state, then "here's how".
  - `bold-claim` — a surprising, defensible statement.
- No logos, intros or "hey guys" before the hook.

## Structure — three beats
1. **Hook** (0–2 s), then **promise** (2–5 s): what the viewer gets.
2. **Payload** (5 s → 80 % of the length): 2–4 points max, one per card,
   each ≤ 12 words on screen.
3. **Payoff + call to action** (last 15 %): the one-line takeaway, then
   one ask (follow / comment / the question back).

## Captions
- Every spoken line appears as a caption; captions are the primary
  channel, not a fallback.
- ≤ 2 lines, ≤ 12 words per card; sentence case; no trailing period on
  single lines.
- Safe area: nothing in the top 12 % or bottom 20 % (UI overlays).

## Pace
- A new card at least every 3 s; no card longer than 5 s.
- Total 20–60 s. Under 20 s is a teaser, over 60 s is not a short.

## Script file format (`01-script.md`)
```
# <title>
Hook kind: question
Length target: 38 s

## Beat 1 — hook + promise (0–5 s)
[0.0–2.0] CARD: Why does your cat sound like an engine?
[2.0–5.0] CARD: Three reasons, 30 seconds.
## Beat 2 — payload
[5.0–9.0] CARD: 1. It's happy — purring starts at 2 weeks old
…
## Beat 3 — payoff + CTA
[..] CARD: <takeaway>
[..] CARD: <one ask>
```
Timestamps in seconds, every card ≤ 12 words.

## Review rubric (what a reviewer checks, in this order)
1. Hook by 2 s, one named kind, ≤ 8 words.
2. Three beats present and in order; payload has 2–4 points.
3. Every card ≤ 12 words, ≤ 2 lines; safe area respected.
4. Pace: cards ≤ 5 s, total 20–60 s.
5. Payoff + exactly one call to action.
A review lists each item as PASS or FAIL with one line of why; any FAIL
means `needs_input`, with the fixes stated as instructions to the maker.
