# Word-accurate timing and "Tidy up lines" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Time every subtitle cue from the words Whisper heard, and (setting on by default) re-cut cues into sentence-based, ≤ 2-row subtitles with repaired capitals.

**Architecture:** The existing `align()` stays as the rough placement. A new `words.py` tokenises cues and matches subtitle words to Whisper words in a ±4 s band around the rough position; `refine()` retimes the original cues from those words. A new `reshape.py` regroups the timed tokens into new cues. `pipeline.process()` (new, pure function) runs the steps; the window, the CLI and a dev replay tool all call it.

**Tech Stack:** Python 3.12 (embedded runtime), numpy, rapidfuzz; tests are stdlib `unittest` scripts (no pytest in the runtime); Go launcher only for help text and version.

**Spec:** `docs/superpowers/specs/2026-11-10-word-timing-and-tidy-lines-design.md`

## Global Constraints

- Words are never added, removed or changed; only cue boundaries, row wrapping and letter case.
- Limits: ≤ 2 rows, ≤ 42 characters per row, 1–7 s on screen, ≤ 20 characters per second (`align.MIN_DURATION`, `MAX_DURATION`, `MAX_CPS`); end = last word end + `align.SPEECH_TAIL` (0.3 s); `align.GAP` (0.084 s) before the next cue; no overlaps.
- Word band ±4.0 s around the rough-placed time; fuzzy word equality = rapidfuzz `ratio ≥ 80`.
- Cues stay in file order; a refined start must satisfy `prev_start + 0.05 ≤ start ≤ next_start − 0.05`, otherwise the rough time is kept (CLAUDE.md lessons 6–7).
- Word matching and re-cutting only when the audio language is `en`; other languages: today's timing, and (tidy on) only cues taller than 2 rows are split, time divided by character count.
- Setting key `"tidy"`, default `True`; CLI `--keep-layout` sets it off. `CACHE_VERSION` unchanged.
- Per-line details: `logs\details\<video stem>.tsv`, keep the 200 newest files.
- Repo is public: no personal info in code, tests, commits. Commits have **no** `Co-Authored-By` / AI trailers. `git pull` before every commit.
- Version 1.2.0.

## Review Focus

1. Long stretches where Whisper heard nothing usable (music, a different cut): cues there must keep their rough times, never collapse onto one time → `test_unmatched_stretch_keeps_rough_times` (Task 2).
2. Original cues that overlap or are out of time order (lesson 6): refining must never reorder cues → `test_refine_never_reorders` (Task 3).
3. Very fast dialogue (two short sentences per second): re-cut cues must never overlap, even when the 1 s minimum can't be met → `test_fast_dialogue_no_overlap` (Task 6).
4. A subtitle with no speech at all, or a cue that is only `(Music)`: no crash, cue kept → `test_sound_only_cues_kept` (Task 6).
5. Typographic apostrophes and dashes (`I’m`, `—`) in the subtitle against Whisper's ASCII: must still match → `test_curly_apostrophe_matches` (Task 2).

---

## File structure

| File | Responsibility |
|---|---|
| `app/subsync/words.py` (new) | `Tok`, `tokenize()`, `match_words()`, `refine()` |
| `app/subsync/reshape.py` (new) | sentence building, splitting, wrapping, short replies, sounds/labels/tags/dashes, `fix_case()`, `split_tall()`, `reshape()` |
| `app/subsync/details.py` (new) | write/prune `logs\details\*.tsv` |
| `app/subsync/pipeline.py` | new `process()`; `_align_loop` calls it; `done` payload gains `tidy` stats |
| `app/subsync/gui.py`, `app/cli.py`, `launcher/cli.go` | setting / flag / summary / report |
| `tools/replay.py`, `tools/measure.py` (new) | dev tools: re-run `process()` on a cached transcript; measure cue starts/ends against Whisper words |
| `tests/test_words.py`, `tests/test_reshape.py` (new) | unit tests |

Run unit tests with the embedded runtime (has numpy + rapidfuzz), e.g. on the dev PC:
`G:\subsync\runtime\python\python.exe tests\test_words.py` — each test file starts like `tests/sim.py` (inserts `<repo>/app` into `sys.path`) and ends with `unittest.main()`.

---

### Task 1: Tokeniser

**Files:**
- Create: `app/subsync/words.py`
- Test: `tests/test_words.py`

**Interfaces:**
- Consumes: `subtitles.Line`
- Produces:
  ```python
  @dataclass
  class Tok:
      cue: int            # index of the original cue
      row: int            # row inside that cue (0-based)
      text: str           # exactly as in the file: "afghanistan.", "(Lock click)", "<i>", "-"
      kind: str           # "word" | "sound" | "label" | "tag" | "dash"
      norm: str = ""      # words only: lowercase, punctuation stripped, ’→'
      start: float | None = None
      end: float | None = None
      matched: bool = False
  def tokenize(lines: list[Line]) -> list[Tok]
  def norm(word: str) -> str
  ```
  `"label"` = a parenthesised/bracketed single capitalised name at the start of a row (`(Patrick)`, `[TRINA]`) or an ALL-CAPS `NAME:` prefix; other `(...)`/`[...]`/`♪...♪` spans are `"sound"`. `"tag"` = `<...>` and `{...}`. `"dash"` = a leading `-`/`–`/`—` on a row.

- [ ] **Step 1: Write failing tests** — `test_tokenize_kinds`: `Line(0,1,"Hey, i know.\n(Lock click) <i>Thanks</i>")` → kinds `["word","word","word","sound","tag","word","tag"]`, rows `[0,0,0,1,1,1,1]`, norms of words `["hey","i","know","thanks"]`. `test_tokenize_label_and_dash`: `"(Patrick)\n- He snuck in,"` → kinds `["label","dash","word","word","word"]`. `test_norm_curly_apostrophe`: `norm("I’m,") == "i'm"`, `norm("—Yes!") == "yes"`. `test_sound_only_line`: `"(Engine turns off)"` → one `"sound"` token.
- [ ] **Step 2: Run** `G:\subsync\runtime\python\python.exe tests\test_words.py` → FAIL (`ImportError: words`).
- [ ] **Step 3: Implement** `Tok`, `norm`, `tokenize` (regex scan per row; reuse the `_TAGS`/`_HI`/`_SPEAKER` patterns from `subtitles.py`).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: tokenise subtitle cues into words, sounds, labels and tags`

### Task 2: Banded word matching

**Files:** Modify `app/subsync/words.py`; Test `tests/test_words.py`

**Interfaces:**
- Consumes: `Tok`, `tokenize`
- Produces: `def match_words(toks: list[Tok], words: list[tuple[float, float, str]], rough: list[Line], band: float = 4.0) -> tuple[int, dict[int, int]]` — fills `start/end/matched` on every `"word"` token, returns the number matched and `match` (token index → Whisper word index, matched tokens only; used by Task 7). `rough[k]` is cue `k` after rough placement (`align.Result.lines`).

Algorithm (not determined by the tests):
```
expected time of word token t = rough[t.cue].start + (rough.end - rough.start) * (char offset of t in its cue / cue speech length)
candidates(t) = Whisper words w with |w.start - expected| <= band and ratio(t.norm, norm(w.text)) >= 80
score = ratio/100
maximum-weight strictly monotonic matching over (token index, word index):
  iterate tokens in order; best(t, w) = score + prefix_max over word indices < w of finished tokens;
  keep a Fenwick tree (prefix max) over word indices, update it only after all candidates of token t are scored
  (so one token can't match two words); back-pointers recover the matching.
unmatched word tokens: interpolate start/end linearly between the nearest matched tokens before/after
  (by character position across cue boundaries), clamped to [expected - band, expected + band];
  with no matched neighbour on a side, use expected.
```

- [ ] **Step 1: Write failing tests** — `test_exact_match_times`: three cues, Whisper words with known times → every token `matched` and `start` equals the Whisper word start. `test_band_blocks_far_repeat`: cue "Come on. Move." rough at 552.0, Whisper has "Come on." at 546.7 *and* 551.9 → matches 551.9. `test_fuzzy_misspelling`: subtitle `"degeorge"` vs Whisper `"DeGeorge,"` and `"colour"` vs `"color"` → matched. `test_curly_apostrophe_matches`: `"I’m"` vs `"I'm"` → matched. `test_interpolates_unmatched`: middle word missing from Whisper → its `start` lies strictly between neighbours, `matched is False`. `test_unmatched_stretch_keeps_rough_times`: 20 cues, Whisper words only for the first 5 → tokens of cues 6–20 have `start` within 0.5 s of the rough expected time and strictly increasing.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement `match_words`.**
- [ ] **Step 4: Run** → PASS; also time it on 6 000 tokens × 6 000 words of synthetic data inside the test (`assert elapsed < 1.5`).
- [ ] **Step 5: Commit** `feat: match subtitle words to Whisper words within a time band`

### Task 3: Retime original cues (`refine`)

**Files:** Modify `app/subsync/words.py`; Test `tests/test_words.py`

**Interfaces:**
- Consumes: `Tok` with times, `align.fix_endings(new, orig, speech_end) -> (n_speech, n_read, n_limited)`
- Produces: `def refine(orig: list[Line], rough: list[Line], toks: list[Tok]) -> tuple[list[Line], dict[int, float], int]` — new cues (original text), `speech_end` per cue (last word end, only if one of the last two word tokens matched), number of cues whose start came from words.

Rules: start = first word token's `start` if the first or second word token of the cue is matched, else `rough.start`; apply the neighbour-order rule from Global Constraints (compare against the *previous refined* start and the *next rough* start); end = `max(rough.end - rough.start + start, start + 0.5)` before `fix_endings`; then call `align.fix_endings(new, new_copy_as_orig, speech_end)` — pass a copy of the new cues as `orig` so back-to-back captions count as "originally separate".

- [ ] **Step 1: Write failing tests** — `test_refine_mid_sentence_start`: cues `"The man who'd pay | her ransom"` @357.86 and `"is lying in a pool | of his own blood."` @359.79, Whisper one continuous sentence from 357.73 with "is" @358.87 → cue 2 start `== 358.87 ± 0.01`. `test_refine_short_first_sentence`: `"Hmm. Let me see. | I don't rightly recall."` @540.60, Whisper "Hmm." @539.28 → start `539.28 ± 0.01`. `test_refine_back_to_back_end`: cue A @15.90–17.28 whose last word ends 19.12, cue B starts in Whisper at 19.20 → A.end ≥ 19.12 and A.end ≤ B.start − 0.084. `test_refine_never_reorders`: original cues with starts `[10, 9.5, 11]` (file order, overlapping) and Whisper times that would put cue 1 before cue 0 → output starts strictly increasing in file order, cue 1 keeps its rough start. `test_refine_unmatched_keeps_rough`: cue with no matched words → equals rough cue.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement `refine`.**
- [ ] **Step 4: Run** `tests\test_words.py` → PASS.
- [ ] **Step 5: Commit** `feat: retime cues from their first and last spoken words`

### Task 4: `pipeline.process`, details file, dev tools — timing-only end to end

**Files:**
- Create: `app/subsync/details.py`, `tools/replay.py`, `tools/measure.py`
- Modify: `app/subsync/pipeline.py:248-275` (`_align_loop`)
- Test: `tests/test_words.py` (process-level test), `tests/sim.py` (run unchanged)

**Interfaces:**
- Consumes: `align.align`, `words.tokenize/match_words/refine`
- Produces:
  ```python
  @dataclass
  class Processed:
      res: align.Result            # rough result (unchanged semantics; .ok/.reason used as today)
      lines: list[Line]            # what gets written
      stats: dict                  # {"tidy": bool, "word_timed": int, "subtitles_before": int, "subtitles_after": int,
                                   #  "joined": int, "split": int, "capitals_fixed": int}
      details: list[dict]          # one per output cue: {"n","from_cues","orig_start","start","end","words","matched","changes"}
  def process(lines, words, lang, embed, tidy: bool, progress=lambda f: None) -> Processed
  # details.py
  def write(video_path: str, rows: list[dict]) -> str     # returns the file path; prunes to 200 newest
  ```
  In this task `process` ignores `tidy` (Task 9 wires it). Non-`en` audio: `lines = res.lines`.
  `tools/replay.py ROOT VIDEO SUBTITLE OUT.srt [--keep-layout]`: sets `SUBSYNC_ROOT=ROOT`, loads the cached transcript via `pipeline._cache_file(video, audio_n)` (audio_n from `media.pick_audio_stream`), real `Embedder(paths.MINILM_DIR)`, runs `process`, writes `OUT.srt`, prints `stats`. Must be run with `ROOT\runtime\python\python.exe`.
  `tools/measure.py TRANSCRIPT.json.gz RESULT.srt`: global difflib word alignment of the result's speech words to Whisper words (independent of `match_words`); prints: % cues with |start − first word| ≤ 0.3 s, > 0.5 s late/early counts, cues ending > 0.3 s before their last word *where the next cue does not start before that word ends*, overlaps, cues with > 2 rows, max row length.

- [ ] **Step 1: Write failing test** — `test_process_timing_only`: synthetic episode from `sim.make(seed=1)` with a fake embedder (reuse `sim.fake_embed`) → `process(..., lang="en", tidy=False)` returns `ok`, `len(lines) == len(input)`, and ≥ 95 % of starts within 0.3 s of `truth`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `process`, `details.write`; change `_align_loop` to call `process(..., tidy=bool(s.get("tidy", True)))`, write `p.lines`, call `details.write(job["video"], p.details)` (ignore `OSError`), add `"tidy": p.stats` to the `done` payload.
- [ ] **Step 4: Run** `tests\test_words.py` → PASS; `tests\sim.py` → "within0.3s" for `same` seeds not lower than before (record before/after numbers in the commit message).
- [ ] **Step 5: Real episode (dev PC):** `G:\subsync\runtime\python\python.exe tools\replay.py G:\subsync <episode.mp4> <original .en.srt> %TEMP%\timing.srt --keep-layout` then `... tools\measure.py <cache file> %TEMP%\timing.srt`. Expected: ≥ 95 % of cues within 0.3 s (baseline 84.8 %), late > 0.5 s count well below 54.
- [ ] **Step 6: Commit** `feat: word-accurate cue timing in the pipeline, per-line details file, replay/measure tools`

### Task 5: Re-cutting core — sentences, splitting, wrapping

**Files:** Create `app/subsync/reshape.py`; Test `tests/test_reshape.py`

**Interfaces:**
- Consumes: `Tok` (timed)
- Produces:
  ```python
  MAX_ROW = 42
  STOP = {"a","an","the","of","to","in","on","at","for","and","or","but","with"}
  @dataclass
  class Cue:
      toks: list[Tok]
      start: float
      end: float            # last word end (speech end), before fix_endings
      dashed: bool = False
  def sentences(toks: list[Tok]) -> list[list[Tok]]      # word/sound/label/tag groups; breaks after . ? ! … and at dash tokens
  def split_long(sent: list[Tok]) -> list[list[Tok]]     # recursive; pieces fit 2×MAX_ROW and ≤ MAX_DURATION
  def wrap(toks: list[Tok]) -> str                       # ≤ 2 rows, balanced, never a row ending on STOP
  ```
  Split choice in `split_long`: candidates after `, ; :` tokens or where the gap to the next word ≥ 0.25 s; else any word boundary not after a `STOP` word; pick the candidate nearest the middle (by characters) among the highest-priority class.

- [ ] **Step 1: Write failing tests** — `test_join_caption_fragments`: tokens of `"The man who'd pay\nher ransom"` + `"is lying in a pool\nof his own blood."` → one sentence; `wrap` → `"The man who'd pay her ransom\nis lying in a pool of his own blood."`. `test_split_two_sentences`: `"Hmm. Let me see.\nI don't rightly recall."` → 3 sentences. `test_split_long_at_comma`: a 120-character sentence with one comma → 2 pieces split after the comma, each `wrap`s to ≤ 2 rows ≤ 42. `test_wrap_no_stopword_row_end`: `"I need assistance with my investigation of the case"` → no row ends with a `STOP` word. `test_wrap_single_row`: text ≤ 42 chars → no `\n`.
- [ ] **Step 2: Run** `tests\test_reshape.py` → FAIL.
- [ ] **Step 3: Implement** `Cue`, `sentences`, `split_long`, `wrap`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: sentence-based re-cutting and two-row wrapping`

### Task 6: Re-cutting details — replies, sounds, labels, tags, dashes, assembly

**Files:** Modify `app/subsync/reshape.py`; Test `tests/test_reshape.py`

**Interfaces:**
- Consumes: Task 5, `align.fix_endings`, `align` constants
- Produces: `def reshape(orig: list[Line], rough: list[Line], toks: list[Tok], words: list[tuple[float, float, str]], match: dict[int, int]) -> tuple[list[Line], dict[int, float], dict]` — new cues, `speech_end` per new cue index, stats `{"joined","split"}` (Task 7 adds `"capitals_fixed"`). `words`/`match` are unused until Task 7 calls `fix_case` from here.

Rules (from the spec): sound before words → prefix of the following sentence; sound that is the last token of its original cue → suffix of the preceding sentence; a label stays at the start of the sentence it introduces; cues with no word tokens stay as their own cue at the rough time. Short reply: a piece with `end − start + SPEECH_TAIL < MIN_DURATION` is combined with the neighbour (next, else previous) when each fits one row ≤ 42: gap ≥ 0.5 s → `dashed=True`, rows `"- A"` / `"- B"`; else joined and wrapped. Original dash tokens are dropped except when a dashed pair is produced. Tags: an original cue with a position tag `{\an…}` puts it at the start of every new cue containing its words; `<i>…</i>` spans cut by a boundary are closed at the end of the cue and reopened at the start of the next. Timing: starts from first word, enforced strictly increasing (+0.05), then `fix_endings`.

- [ ] **Step 1: Write failing tests** — `test_two_speakers_separate`: `"All right. Put out\nan amber alert and a b.O.L.O.\nAlready did. I've set up\na perimeter and notified c.H.P."` with a 0.6 s pause before "Already" → ≥ 2 cues, none with > 2 rows. `test_short_reply_dashed`: "Thanks." (0.4 s) then 0.7 s pause then "You're welcome." → one cue `"- Thanks.\n- You're welcome."`. `test_short_same_speaker_joined`: "Okay." then 0.1 s gap then "Let's go." → one cue without dashes. `test_sound_attaches_forward`: `"marshal gorman.\n(Chuckles) At ease, grace."` → a cue text starting `"(Chuckles) At ease, grace."`. `test_sound_at_cue_end_attaches_back`: `"We're not invading\nafghanistan.\n(Lock click)"` → `(Lock click)` is in the same cue as "afghanistan.". `test_sound_only_cues_kept`: `"(Engine turns off)"` cue → output contains it unchanged at its rough time. `test_italic_across_split`: `"<i>One sentence here. Another one</i>\n<i>follows.</i>"` → every output cue has balanced `<i>`/`</i>`. `test_fast_dialogue_no_overlap`: 6 one-word sentences 0.3 s apart → output ends ≤ next start − GAP for all cues. `test_stats_joined_split`: the join and split fixtures above report `joined ≥ 1` / `split ≥ 1`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement `reshape`.**
- [ ] **Step 4: Run** `tests\test_reshape.py` → PASS.
- [ ] **Step 5: Commit** `feat: re-cut cues by speaker and sentence, keep sound descriptions and tags`

### Task 7: Capitals

**Files:** Modify `app/subsync/reshape.py`; Test `tests/test_reshape.py`

**Interfaces:**
- Produces: `def fix_case(toks: list[Tok], words: list[tuple[float, float, str]], match: dict[int, int]) -> int` — mutates word `Tok.text` in place (letter case only), returns tokens changed. `match` is the second value returned by `match_words` (Task 2).

Rules: `i`, `i'm`, `i've`, `i'll`, `i'd` → capital I; first letter of a sentence's first word upper-case; a matched token takes Whisper's capitalisation when the Whisper word is capitalised and is not first after `. ? !` in the transcript; dotted abbreviations `x.Y.Z.` → `X.Y.Z.`. Assert in code that `tok.text.lower()` is unchanged.

- [ ] **Step 1: Write failing tests** — `test_case_i`: "i know i'm late" → "I know I'm late". `test_case_names_from_whisper`: "agent van pelt" with Whisper "agent Van Pelt" → "agent Van Pelt"; "afghanistan" with Whisper "Afghanistan." mid-sentence → "Afghanistan". `test_case_sentence_start`: sentence "yeah, sure." → "Yeah, sure.". `test_case_abbrev`: "c.H.P." → "C.H.P.", "b.O.L.O." → "B.O.L.O.". `test_case_sentence_initial_whisper_ignored`: Whisper "Well." at sentence start must not capitalise subtitle mid-sentence "well". `test_case_returns_count`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**, call `fix_case` inside `reshape` before building text, add `"capitals_fixed"` to its stats. **Step 4: Run** both test files → PASS.
- [ ] **Step 5: Commit** `feat: repair capitals using Whisper's spelling`

### Task 8: Other-language audio — split tall cues

**Files:** Modify `app/subsync/reshape.py`; Test `tests/test_reshape.py`

**Interfaces:** `def split_tall(lines: list[Line]) -> tuple[list[Line], int]` — cues with > 2 rows split into consecutive cues of ≤ 2 rows (prefer splitting after a row that ends with `. ? !`), each cue's time divided in proportion to visible characters; returns new lines and the number of cues split.

- [ ] **Step 1: Test** `test_split_tall_four_rows`: one 4-row cue 10.0–14.0 with 20/20/20/20 chars → two cues 10.0–12.0 and 12.0–14.0 (± GAP), two rows each. `test_split_tall_leaves_two_rows`: 2-row cue unchanged.
- [ ] **Step 2–4:** run → FAIL, implement, run → PASS.
- [ ] **Step 5: Commit** `feat: split cues taller than two rows when audio is not English`

### Task 9: Wire tidy into `process`; real-episode check

**Files:** Modify `app/subsync/pipeline.py` (`process`); Test `tests/test_words.py`

- [ ] **Step 1: Test** `test_process_tidy_on`: synthetic episode with 3- and 4-row cues and mid-sentence cues, `tidy=True` → no cue > 2 rows or > 42 chars per row, no overlaps, `stats["subtitles_after"] != stats["subtitles_before"]`, the multiset of normalised words in the output equals the input's. `test_process_tidy_foreign`: same with `lang="da"` → `split_tall` path, no cue > 2 rows, timing equal to `res.lines` for cues that were not split.
- [ ] **Step 2–4:** run → FAIL; in `process`: `en` + tidy → `reshape`; `en` + not tidy → `refine`; other + tidy → `split_tall(res.lines)`; other + not tidy → `res.lines`. Fill `stats` and `details` (`changes` lists e.g. `"joined 3+4"`, `"split from 12"`, `"start from words"`, `"end +0.6 speech"`, `"capitals 2"`). Run → PASS; `tests\sim.py` unchanged numbers.
- [ ] **Step 5: Real episode:** `tools\replay.py` without `--keep-layout`, then `tools\measure.py`. Expected: ≥ 95 % starts within 0.3 s, 0 cues > 2 rows, max row ≤ 42, 0 overlaps. Open the `logs\details` TSV and spot-read 20 rows for nonsense joins.
- [ ] **Step 6: Commit** `feat: Tidy up lines in the pipeline`

### Task 10: Setting, window, CLI, report, launcher help, e2e

**Files:** Modify `app/subsync/gui.py:470-490, 615-625, 727-750`, `app/cli.py:3-4, 50-58, 120-125`, result/report code in `app/cli.py` (the `done` handler), `launcher/cli.go:45-50`, `tests/gui_e2e.py`, `tests/cli_e2e.py`, `tests/fake_worker.py` if needed.

- [ ] **Step 1:** Window: `ToggleSwitch` + label **"Tidy up lines"** after "Overwrite existing", tooltip `"One sentence per subtitle, at most 2 lines, capital letters repaired. Timing is fixed either way."`; `settings["tidy"]`, default `True`. Result detail adds `" · {before} → {after} subtitles"` when they differ; tooltip adds lines `Subtitles: before → after`, `Joined: n`, `Split: n`, `Capitals fixed: n`, `Timed from words: n`.
- [ ] **Step 2:** CLI: `--keep-layout` (`store_true`) → `settings["tidy"] = not args.keep_layout`; usage docstring; result line adds `, {before} -> {after} subtitles` when different; JSON item adds `tidy`, `subtitles_before`, `subtitles_after`, `joined`, `split`, `capitals_fixed`. `launcher/cli.go` help gains `  --keep-layout           keep the original line layout and capitals (timing is still fixed)`.
- [ ] **Step 3:** Update `gui_e2e.py` (toggle off and on, check the detail text) and `cli_e2e.py` (`--keep-layout` run, report fields). Run where their fixtures exist (they need espeak-ng + ffmpeg; on Windows also adapt `/tmp` paths to `tempfile.gettempdir()`); if they cannot run, say so in the report — don't skip silently.
- [ ] **Step 4:** Real run in the window on the dev PC is not possible until the exe is rebuilt (the exe restores `app\` from its embedded copy) — covered in Task 11.
- [ ] **Step 5: Commit** `feat: Tidy up lines setting in the window and --keep-layout on the command line`

### Task 11: Docs, version, build, release prep

**Files:** `README.md`, `README-CLI.md`, `CHANGELOG.md`, `CLAUDE.md` (Current status + architecture lines for `words.py`/`reshape.py`/`details.py`/tools), `launcher/cli.go` (`appVersionString`), `app/cli.py` (`subsync_version`), `launcher/app.rc` + `.syso` if `windres` is available.

- [ ] **Step 1:** Docs: README "What SubSync fixes" (word-accurate starts/ends; Tidy up lines), Settings table row, "Reading the result"; README-CLI `--keep-layout`, report fields, `logs\details`. Keep the owner's existing wording elsewhere. CHANGELOG `## 1.2.0`.
- [ ] **Step 2:** Version 1.2.0 in the three places. If no `windres`, leave `app.rc` (already an open item) and say so.
- [ ] **Step 3:** Build: Go ≥ 1.24 is **not installed on the dev PC** — ask the owner before installing it. Then `./build/build.sh`. Copy the new exes into a test folder, run `subsync-cli check`, then the real episode through `subsync-cli sync` and through the window; confirm the setting and summary appear.
- [ ] **Step 4:** Launcher tests (`tests/launcher/run.sh`) only changed help text; they need wine + Xvfb — run if available, otherwise report not run.
- [ ] **Step 5:** Owner viewing check: give the owner ~8 timestamps from the episode (mid-sentence joins, a split long sentence, a dashed reply, a sound description, a capitals fix) to watch.
- [ ] **Step 6:** Commit `docs: 1.2.0`; prepare `SubSync-v1.2.0-windows-x64.zip` (both exes, both READMEs, LICENSE), its SHA-256 and release notes for the owner (named `DD-MM-YYYY-...` outside the repo). Push only when the owner says so.
