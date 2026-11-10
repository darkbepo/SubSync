# Word-accurate timing and "Tidy up lines" (v1.2.0)

Status: design approved by the owner in conversation on 2026-11-10; this document is the written version for review.

## Problem

Measured on a real broadcast-caption episode (808 cues, English audio), comparing every cue with the Whisper word timings (the owner confirmed those timings by watching):

- 11.2 % of cues start more than 0.5 s off after syncing (11.4 % before): SubSync fixed almost none of them. Most are 0.6–1.9 s **late**.
- 22 cues disappear before their last word is spoken.
- The file as a whole was already in sync (applied shift only −0.3 … +0.4 s); the errors are per line.

Root cause, from `align.py`:

1. Cues are placed at the **start of a Whisper phrase** (`build_phrases`: split at pauses > 0.3 s and sentence ends). Broadcast captions cut mid-sentence (110 cues start lowercase) or join the end of one sentence to the start of the next (231 cues). A cue starting mid-phrase (`is lying in a pool | of his own blood.`) has no phrase start to land on and keeps its late time. A cue opening with a short sentence (`Hmm. Let me see. I don't rightly recall.`) matches the *later* phrase pair (`Let me see.` + next), so the measured offset is ≈ 0 and the cue stays 1.3 s late.
2. Per-anchor offsets are median-smoothed with neighbours; lone deviations under 0.8 s are absorbed into the run.
3. Endings: captions run back to back (482 of 807 gaps are 0), and `fix_endings` never extends a cue into the next one, so a cue whose successor starts late is cut off before its words finish.

Separately, the owner wants the layout fixed: 80 cues are 3–4 rows tall, captions mix speakers in one cue without dashes, and capitals are lost (`i`, `van pelt`, `c.H.P.`).

## Goals

- Every cue starts at its first spoken word and ends after its last, for English audio.
- New setting **"Tidy up lines"** (default **on**): one sentence (or natural part of a long one) per cue, max 2 rows × 42 characters, speakers separated, capitals repaired. Words themselves are never added, removed or changed — only where cues break, how rows wrap, and letter case.
- Nothing gets worse for files that are already good, or for other-language audio.

Non-goals: subtitle languages other than English; ASS output keeping styles; using Whisper's text as subtitle text.

## Approach

Chosen: **time every word first, then re-cut using those times.** (Rejected: Whisper text as subtitles — changes words and inherits mishearings; re-cut text first then time — new cuts fall mid-phrase, exactly where the current timing fails.)

Pipeline per episode (`pipeline._align_loop`):

1. **Rough placement** — existing `align()` unchanged: runs, splits, drift, per-line offset curve. Its output is the prior for step 2.
2. **Word matching** (new, `app/subsync/words.py`) — English audio only.
   - Tokenise subtitle speech words in file order (via `speech_text`, keeping each token's cue index and its position in the original text) and Whisper words; normalise (lowercase, strip punctuation, unify apostrophes, numbers ↔ digits where cheap).
   - Monotonic word alignment (DP / difflib-style, fuzzy token equality via rapidfuzz ratio ≥ 0.8 for misspellings), **restricted to a band**: a subtitle word may only match a Whisper word within ±4 s of its rough-placed time. This prevents matches to repeated phrases far away.
   - Unmatched subtitle words get times by interpolation between the nearest matched words (by character position), clamped to the band.
   - Result per subtitle token: `(start, end, matched: bool)`.
   - A cue's measured start/end is trusted only if its first/last word (or one of its first/last two) was matched; otherwise its rough-placed time is kept for that edge.
3. **Re-cutting** (new, `app/subsync/reshape.py`) — only with the setting on.
4. **Timing** — cue start = first word start; end = last word end + `SPEECH_TAIL` (0.3 s), then the existing reading rules (`MIN_DURATION` 1 s, `MAX_DURATION` 7 s, `MAX_CPS` 20) and the no-overlap rule (`GAP` 0.084 s before the next cue). Because the next cue now also starts at its real first word, back-to-back captions no longer cut endings off.

With the setting **off**, steps 2 and 4 still run on the original cues (original layout, word-accurate times). With **other-language audio**, step 2 is skipped and today's timing is used; with the setting on, only cues taller than 2 rows are split by text, and their time is divided in proportion to character count.

Safety rules (from CLAUDE.md lessons 6–7): cues stay in file order; a refined start must stay strictly between the neighbouring cues' starts (`lo + 0.05 ≤ ns ≤ hi − 0.05`), otherwise the rough time is kept.

## Re-cutting rules (setting on)

Input: the stream of subtitle tokens with times, plus sound descriptions and formatting tags in their original positions.

- **Limits:** ≤ 2 rows, ≤ 42 characters per row, 1–7 s on screen, ≤ ~20 characters per second.
- **Break priority:** (1) sentence end (`. ? ! …`), preferred when followed by a pause ≥ 0.3 s; (2) if a sentence exceeds 2 × 42 characters or 7 s: after a comma/semicolon/colon or at a pause ≥ 0.25 s; (3) last resort between words, never between closely bound words. No row or cue may end on an article, preposition or conjunction (`a an the of to in on at for and or but with`).
- **Joining:** consecutive fragments of one sentence are joined into one cue when the result fits the limits.
- **Two rows:** break at the natural point closest to balanced length (bottom row may be slightly longer).
- **Short replies:** a sentence that would be under 1 s on screen is combined with its neighbour if both fit in 2 rows: with a pause ≥ 0.5 s between them → two rows with dashes (`- Thanks.` / `- You're welcome.`), treated as a reply; otherwise joined without dashes as the same speaker. This is a guess and is only used for very short sentences.
- **Sound descriptions** (`(Chuckles)`, `[door slams]`): an embedded one goes with the following sentence; one at the very end of an original cue stays with the preceding sentence. Speaker labels (`(Patrick)`) stay at the start of the sentence they introduce. Cues containing only descriptions keep their own cue, timed as today (from neighbours).
- **Capitals:** `i` → `I` (incl. `i'm i've i'll i'd`); first letter of each sentence upper-case; a word takes Whisper's capitalisation when Whisper wrote it capitalised in a non-sentence-initial position (`van pelt` → `Van Pelt`); dotted abbreviations with flipped case are repaired (`c.H.P.` → `C.H.P.`). Only letter case changes.
- **Formatting tags** (`<i>`, `{\an8}` etc.) stay attached to their words; a tag span cut by a new cue boundary is closed and reopened.

## Settings, output, diagnostics

- `settings.json`: `"tidy": true` (default). Window: **"Tidy up lines"** toggle next to "Overwrite existing", with a tooltip. CLI: on by default, `--keep-layout` turns it off; help text in both `app/cli.py` and `launcher/cli.go` (requires rebuilding the exes).
- Result summary and hover details add: cues before → after, joined, split, capitals fixed. JSON report adds `subtitles_before`, `subtitles_after`, `joined`, `split`, `capitals_fixed`, `tidy`.
- Per-line diagnostics: each run writes `logs\details\<video stem>.tsv` (one row per output cue: original cue numbers and times, new times, matched/total words, what changed and why). Overwritten per video; the folder keeps at most the 200 newest files.
- Transcript cache format and `CACHE_VERSION` unchanged, so existing caches stay valid.

## Testing

- New unit tests (`tests/test_words.py`, `tests/test_reshape.py`) with synthetic words + cues: mid-sentence caption cues, sentence-pair cues, 3–4 row cues, back-and-forth replies, embedded and standalone sound descriptions, speaker labels, capitals and abbreviations, italic tags across a split, repeated phrases outside the band, other-language audio path.
- Existing `tests/sim.py` accuracy must not drop; `gui_e2e.py` / `cli_e2e.py` updated for the new setting and summary.
- Real-episode check on the owner's PC (broadcast captions, English audio): ≥ 95 % of cues start within 0.3 s of their first spoken word (now ≈ 85 %), and no cue ends before its last word unless the next cue starts first. The measurement uses the same Whisper timings, so the owner's viewing of a short list of spots is the final check.
- Speed: word matching + re-cutting target < 2 s per 45-minute episode.

## Release

Version 1.2.0 (`launcher/cli.go`, `app/cli.py`, and `launcher/app.rc` + `.syso` rebuild). Update `README.md` (setting, what it fixes), `README-CLI.md` (`--keep-layout`, report fields), `CHANGELOG.md`, and the status in `CLAUDE.md`. Release zip, SHA-256 and notes prepared for the owner to publish.
