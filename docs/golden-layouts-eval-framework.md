# Golden Layouts: Model & Evaluation Strategy

*Evidence-based recommendation for FY27 Priority #1 — the SharePoint Authoring evaluation system.*
*Prepared 2026-09-18. Assumptions and confidence levels are called out inline; see [Assumptions](#assumptions--open-questions) at the end.*

---

## Executive summary

**Recommendation: Tier 1 (composition-constraint library) + Tier 2 (best-of-N against a tuned critic), on a model-agnostic harness fronted by Azure AI Foundry for production and direct frontier APIs for R&D. Do not fine-tune the generator yet.**

- Prompting + constitution + exemplars (Tier 0) will likely clear the accessibility/performance gates but will **not** clear the distinctiveness bar — the constitution is written entirely in loss-avoidance language, which optimizes for competent and forgettable, not memorable.
- The cheapest, fastest lever you haven't priced yet is **Tier 1**: turn the golden corpus into a curated library of layout skeletons, type systems, and color systems so the model *composes* instead of *invents*. Build this in Phase 0 regardless of model choice — it improves every other tier for free.
- **Tier 2 (best-of-N, k≈8, against a constitution+distinctiveness critic)** is the second-cheapest lever and directly targets the exact failure mode you're worried about: distinctiveness is high-variance, so best-of-8 beats average-of-8 by a wide margin, and it costs cents per page with prompt caching.
- **Fine-tune the critic, not the generator, first.** It's smaller, needs far less data, is reusable across every generator you swap in, and — critically — it quality-gates everything downstream: a Tier-2→Tier-3 distillation pipeline is only as trustworthy as the critic that curated the winners.
- Instrument the critique→revision trace schema (below) starting in Phase 0, while still in Tier 0. It's near-zero marginal cost and is exactly the preference-pair data DPO/LoRA tuning consumes later — this removes the labeling-budget problem before it exists.
- **D3 (blind provenance test) is the headline metric**, not the constitution compliance score. Trigger serious Tier 3 (generator fine-tune) investment only if detection accuracy stays reliably ≥65% *after* Tiers 0–2 have been tried — and even then, default to LoRA-scale style adaptation, not a full fine-tune, because this is a style gap, not a capability gap.
- 84 pages is enough for a directional Phase 1 read, not a precise one. Treat n=50 as a go/no-go signal; the statistical lever you actually control is *judgments per page* (multiple raters, multiple mixes), not page count.
- The real budget line is human expert time (critique authorship, rater judgments, spot-checks), not API cost — compute is a rounding error at this volume even with 8x sampling.

---

## 1. Recommended stack

**Orchestration:** a thin, model-agnostic harness — not Copilot Studio, not a single vendor SDK. The one piece of IP that must never be vendor-locked is the **Page Intermediate Representation (IR)**: a versioned JSON Schema describing a page as sections → columns → typed blocks (hero, card-grid, rich-text, image, chart, etc.), independent of any model's native output format and structurally aligned with the SharePoint canvas/web-part schema you'll extract in §4. Every model, regardless of vendor, is constrained to emit this IR via structured outputs / tool-calling / grammar-constrained decoding. A separate, deterministic renderer turns IR → real SharePoint canvas JSON (and → HTML/screenshot for scoring). This is what "swap models without rewriting the pipeline" actually means in practice: swapping a model is a config change (endpoint + adapter), because the contract on both sides of it never changes.

**Where models run:**
- **Azure AI Foundry** for anything that will touch real tenant content in production: it's the governed gateway (private networking, tenant AAD, content filtering, data-residency controls) and hosts OpenAI's models plus a broad partner catalog (Meta, Mistral, xAI, DeepSeek, and others). **Caveat, stated plainly:** as of my training, Anthropic's Claude models run on Anthropic's own API, AWS Bedrock, and Google Vertex AI — not natively in the Azure AI Foundry catalog. If Claude is on your shortlist (it should be — see §2), it's called via direct API/Bedrock behind your own network controls, not through Foundry. Confirm current catalog contents before committing; this shifts quarterly.
- **Direct frontier APIs** (Anthropic, Google Vertex) for R&D, benchmarking, and — especially — as **judges**, where using a model from a different vendor/architecture than the generator reduces shared-blind-spot gaming (§5e).
- **A self-hosted open-weight vision-capable model** (via Azure ML or a GPU box you control), reserved specifically for the critic fine-tune and any eventual LoRA generator tuning. This is the one place where owning weights matters — everything else in the stack should assume generators are commodities you'll swap every few months.

**Why not Copilot Studio as the harness:** it's the right layer for a citizen-developer agent surface later, but it constrains exactly what this project needs most — a custom JSON Schema output contract, full trace logging of every generation/critique/revision, and a hand-rolled best-of-N + critic loop. Revisit it as a *distribution* surface once the evaluation system is proven, not as the evaluation system itself.

---

## 2. Model shortlist

| Model | Why it earns a slot | Confidence |
|---|---|---|
| **Claude Opus 5** (Anthropic API) | Highest-reasoning tier for the critique/revision step and as judge; Anthropic's own alignment approach is literally "Constitutional AI," which is a genuine methodological fit for a constitution-driven critique loop, not just branding. Long context (reported ~1M token window in the 5-series) comfortably holds constitution + principles + exemplar set. | Model identity/IDs are from my own system configuration — high confidence. Comparative benchmark claims beyond my Jan 2026 cutoff are not. |
| **Claude Sonnet 5** (Anthropic API) | Cost/latency workhorse for high-volume generation and for the Tier-2 sampler (you need k=8 to be cheap to be worth it). Same long-context/structured-output profile as Opus 5 at a fraction of the price. | Same as above. |
| **A GPT-5-series flagship** (Azure AI Foundry) | Native Azure hosting is the path of least resistance for the production/tenant-data path; OpenAI's structured-outputs feature gives hard schema-conformance guarantees, which matters a lot for an IR-first pipeline. | Directional — verify current model name/version in your Foundry region; don't trust version numbers from SEO comparison sites (several turned up in research and look inconsistent/fabricated — see Sources). |
| **Gemini 3 Pro** (Vertex AI) | Largest context window among the shortlist and strong native multimodal input — makes it a natural second, architecturally-independent **vision judge** for the composition-principle scoring in §5 and for D1's vision-dependent tells, reducing single-vendor judge bias. | Directional, same caveat as above. |
| **An open-weight vision-capable model** (e.g., current-generation Llama/Qwen-VL class, self-hosted or via a managed endpoint) | Not competitive on raw generation quality — the point is that it's the only class of model you can actually own and iterate weights on. This is your Tier 3 substrate: critic fine-tune first, generator LoRA if the D3 gap survives Tiers 0–2. | Directional; pick the specific model at Phase 0 time based on then-current open-weight leaderboard, not now. |

I'm deliberately not asserting exact current benchmark numbers for the non-Anthropic models — my knowledge cutoff is January 2026 and it's September 2026; the comparison sites that came up in research (Eden AI, MorphLLM, tech-insider.org, PromptQuorum) cite version strings and scores that don't cross-check cleanly against each other and read like programmatic SEO content. **Run your own Phase 0 pilot to get real numbers rather than trusting any of these secondary sources** — that pilot is cheap (§11) and is the actual point of a bake-off.

---

## 3. Corpus split discipline

Do this before anything else, per your own framing — a corpus can't be both prompt and exam.

### Curation, from what's specified

I don't have the full 84-item manifest, only the annotations in Appendix C. Here's the arithmetic that follows from those annotations, plus the method for the rest, which is a Phase 0 task (see the curation template shipped alongside this doc).

| Category | Items (as specified) | Count |
|---|---|---|
| Materials Strategy duplicate cluster | 5, 7, 9, 50, 63 | 5 (1 keeper + 4 variants) |
| Nov 2026 Roadmap duplicate cluster | 13, 14, 15 (note: item 13's title/slug disagree — verify by hand) | 3 (1 keeper + 2 variants) |
| Scratch/untitled `Page(N)` | 6, 17, 20, 21, 24 | 5 |
| `Test page` | 11 | 1 |
| Structural template (not a scored page) | 8 | 1 |
| Repeated archetypes across sites (Home, Rhythm of the Business, Team) | not enumerated in the appendix — identify all instances in Phase 0 | unknown |

Working the numbers: 84 total → **1 template excluded entirely** (it's a structural reference, not a page) → 83 candidate pages → collapsing the two duplicate clusters to one representative each removes 4 + 2 = 6 from the "distinct" count → **77 distinct page entities**, of which 6 (the `Page(N)` + `Test page` set) are pre-flagged weak/scratch.

**On "count of genuinely distinct strong layouts": I can give you 77 distinct entities with confidence — that's arithmetic. I cannot give you a strong-layout count without eyes on the corpus.** "Strong" is a quality judgment, not a dedup operation. My honest estimate is that you have on the order of 71 pages (77 minus the 6 known-weak) that are *not obviously broken*, and that number will split further into strong / mid / weak-but-valuable once someone runs a first-pass constitutional + distinctiveness score over them — which is Phase 0 Task 1, not something inferable from a corpus summary. Don't let "71" get quoted around the org as "71 strong layouts"; it isn't.

### The split

| Bucket | Recommended size | Composition | Rule |
|---|---|---|---|
| **Exemplars** (in-prompt, few-shot) | ~16 | Strong-tier only, one representative per major archetype (home, news/announcement, dashboard, team/directory, strategy/roadmap, wiki/onboarding), 2–3 per archetype where strong examples allow | Never includes both instances of a repeated-archetype pair — always leave a same-archetype instance on the held-out side, otherwise you can't tell "learned the archetype" from "memorized the page" |
| **Frozen benchmark** (iterated against during Tier 0–2 development) | ~46 | Mix of strong, mid, and weak-but-valuable tiers, including the 6 scratch/weak pages | Weak pages serve as calibration floor anchors for the rubric/judge — if a judge scores `Test page` highly, that's a free judge-validity failure signal, not noise to filter out |
| **Final blind holdout** (touched exactly once, before the Phase 1→2 go/no-go) | ~12 | At least one instance from each archetype, at least one repeated-archetype instance not used as an exemplar, and both duplicate-variant clusters held back in full | The duplicate-variant pairs are uniquely valuable here as ranked-comparison stimuli — "can the judge correctly rank the human revision quality between variants" is a direct sanity check on whether the critic tracks the constitution or just surface polish. This bucket also supplies the human-made pages for the D3 test — never reuse them anywhere else, or D3 stops being blind. |

This is a starting allocation — revisit exact counts once Phase 0 curation classifies all 77 distinct pages by tier and confirms which sites host the repeated archetypes.

---

## 4. Extraction approach

These are modern (client-side/canvas) `.aspx` pages, not standalone HTML documents. Three extraction methods, each losing something different — capture all three per page, keyed by a stable page ID, as one versioned bundle:

| Method | Captures | Loses |
|---|---|---|
| **Canvas JSON** (PnP PowerShell/Core SDK — `Get-PnPPage` / `Export-PnPPage`, web part `PropertiesJSON`) | Authoritative structural ground truth: sections, columns, web part types and order. Machine-readable, diffable, versionable — the natural source for the Page IR and for structural scoring (section rhythm, skeleton hashing in §6). | Final rendered visual truth — resolved theme/fonts, real image cropping/focal points, responsive behavior, computed color contrast, custom CSS/branding overlays. |
| **Rendered screenshots** (headless Playwright, authenticated session, 3 breakpoints: desktop/tablet/mobile) | The actual visual truth the composition principles are about — needed for vision-judge scoring, the D3 blind test stimuli (raters need to see a page, not JSON), and the vision-dependent D1 tells (gradient hero, uniform card heights, emoji-as-icon). | Not directly queryable/diffable as a raster; without DOM correlation you lose the mapping from "this pixel region" back to "this authored section," which the critique loop needs to point at a rule violation concretely. |
| **Live DOM + computed accessibility tree** (Playwright `page.content()` / accessibility snapshot, ideally captured in the same pass as CDP/Lighthouse timing) | What automated a11y tooling (axe-core) and contrast-ratio computation actually run against; semantic HTML lint; render-without-error and performance-budget checks. | Higher-level authoring structure — canvas section/column boundaries collapse into generic containers after theme rendering, so you can't cleanly recover "this was a 3-column section" from DOM alone. |

**Make the extraction schema double as the generation output contract.** If the Page IR mirrors the PnP canvas JSON schema, generated IR round-trips through the same PnP APIs to produce a real, renderable page — closing the loop for screenshot capture and live a11y testing without a second bespoke renderer, and keeping the "output contract constant across models" requirement in §7 trivially true.

Practical note: 84 pages is small enough to extract by a hand-checked script in an afternoon against the Zava demo tenant. Do this once, cache it, content-hash it — this bundle becomes "golden corpus v1," the thing every experiment manifest in §7 points back to.

---

## 5. Evaluation design

### 5a. Gates vs. graded dimensions

| Law | Ship gate? | Rationale |
|---|---|---|
| 05 — Accessibility | **Gate** (explicit in your brief) | WCAG AA via axe-core automated pass (industry estimates put automated tooling coverage around 30–40% of WCAG success criteria — this is a widely-cited approximation, not a hard number I can source precisely for your exact ruleset) + contrast ratio computed from rendered DOM + a manual/AT spot-check sample. Automated pass is necessary, not sufficient. |
| 03 — Performance | **Gate** | Objectively measurable on the rendered page: Lighthouse/CDP performance score above a threshold, no console errors, image payload within budget. No judgment call needed, so it belongs as a gate. |
| 04 — Privacy, Trust & User Control | **Narrow gate + mostly N/A** | Most of this law is about interactive product behavior (reversibility, agency over multi-step flows), which doesn't apply cleanly to a static content page. Gate the applicable slice only: no dark-pattern CTAs, no misleading claims in copy. Flag the rest as "revisit when generating interactive web parts," not force-fit into a page-level gate. |
| 02 — Immediate Comprehension | **Split** | The qualitative claim ("understand without interpretation") needs judgment — graded. But a cheap deterministic proxy is gateable: page has an identifiable title/H1, clear heading hierarchy, no orphaned CTA. Gate the proxy, grade the substance. |
| 01 — Task Efficiency (Usability) | **Graded** | Defined in terms of time-to-completion and error rate — real measurement requires actual usability testing, which isn't affordable at 50–500 pages of static generation. Score a structural proxy (is the primary action reachable within N scannable regions, is nav depth reasonable) via judge, not a hard gate, until/unless a real usability panel is added later. |
| 5 Principles (Clarity, Hierarchy, Consistency, Simplicity, Speed) | **Graded** | Inherently comparative, not binary — score 1–5 via judge + human spot-check. |

### 5b. Scoring the 14 composition principles

Be honest about what's actually measurable: several of these principles are defined in terms of a ground truth (real eye-tracking scanpaths) this project has no instrument or budget to measure. The practical posture is scoring *design choices known to correlate with* the pattern, not the phenomenon itself. Group them by what that measurement actually looks like:

| Family | Principles | Method |
|---|---|---|
| **Geometric/compositional** | Golden ratio/spiral, golden triangle, F-pattern, Z-pattern, rule of thirds, alignment lines | Semi-automatable, cheap, no judge call needed: extract bounding rects from the rendered screenshot + DOM, and check proportions/placement against known ratios and reading-pattern zones (e.g., is the primary CTA in the Z-pattern's terminal fixation zone; is the hero/content split within tolerance of 1:1.618). Run on 100% of pages. |
| **Perceptual/weight** | Visual weight distribution, figure-ground, negative space framing, focal point dominance, center bias | Needs real vision analysis: a saliency/attention-heatmap pass over the screenshot, corroborated by vision-judge scoring against a rubric description of each principle. This is the family where a vision-capable judge (Gemini 3 Pro, or Claude/GPT-5 with image input) earns its keep. |
| **Structural/relational** | Common region/container, visual hierarchy pyramid, leading lines | Largely DOM/structural: grouping-box analysis, heading structure — cheap, automatable. |

### 5c. Measurement mix

Automated gates decide ship/no-ship. The judge model produces graded rubric scores (1–5 per dimension) in a format that **cites the specific law/principle and quotes or points at the evidence** — free-text scores with no cited evidence are discarded, not trusted; this is the single cheapest lever against vibes-scoring. Human spot-check on a stratified ~15–20% random sample per run, plus 100% human review of anything the judge scores near a gate threshold (the cheap-but-targeted use of scarce expert time).

### 5d. Scale, agreement, and an honest confidence read

50 pages is enough to detect a medium-to-large effect between two conditions with a paired test at conventional power — it is **not** enough for a tight read on a proportion like D3's detection rate. For a binomial proportion, standard error is √(p(1−p)/n): at p=0.5, n=50 gives SE≈7.1%, a 95% CI of roughly ±14 points around 50% — wide enough that an observed 45% detection rate is statistically indistinguishable from an observed 60%. That's not usable for a threshold decision.

**The lever is judgments, not pages.** The same 46–50 benchmark pages, rated by multiple raters across multiple randomized mixed batches, can produce 150–200+ independent judgments; at n=200 the CI tightens to roughly ±6–7 points, which is usable. Design D3's rating protocol around judgment count from the start, and don't report a Phase 1 D3 number as more precise than the CI it actually carries.

**Rater agreement:** calibrate with ≥3 raters on a subset before trusting single-rater scores; target Krippendorff's alpha or Fleiss' kappa ≥0.6–0.7 as usable. Use the known weak pages (low anchor) and known-strong exemplars-not-used-as-exemplars (high anchor) to calibrate rubric anchors before the real run.

### 5e. Detecting rubric gaming

- **Cross-family judging.** Judge with a model from a different vendor/architecture than the generator — reduces the odds a model games a rubric it wasn't optimized against.
- **Evidence-required scoring.** No cited evidence, no score — a judge output with a bare number is a discarded output, not a low-confidence one.
- **Canary negatives in every batch.** Include a known-bad "naive prompt" generation (§8, cost ≈ free) in every scoring batch. If a canary scores unexpectedly well, the run's scores are untrustworthy and the rubric — or the judge prompt — needs a patch before anything else in that batch is trusted.
- **The definitive signal: judge score vs. D3 divergence.** If a model's judge/constitution score climbs while its D3 "reads as human" rate does not — or worsens — that's gaming, not improvement. This is the concrete reason D3 has to be the headline metric and not a nice-to-have: it's the check that catches the constitution being satisfied on paper while the page still reads as AI-made.
- **Blind human audit.** Periodic human-only review, blind to both model identity and the judge's score, on a random subsample, to catch judge/generator collusion drift over time.

---

## 6. Distinctiveness — gates vs. grades

Agreeing with your framing: the constitution is written entirely in terms of what it protects *against* (friction, confusion, frustration, anxiety, exclusion), and the principles push toward reuse and cognitive simplicity. A page can satisfy all ten and still be forgettable. Distinctiveness needs a separate axis, scored separately, never blended into the constitution composite — averaging is exactly how a high-compliance, low-distinctiveness page slips through unnoticed.

### D1 — Generic-tell gate (page level)

| Tell | Detection method | Cost |
|---|---|---|
| Three-card-row default grouping | Structural: sibling pattern of 3 near-identical bounding boxes | Static, cheap |
| Uniform card heights / identical internal structure | Geometry: variance of heights + child-shape hash across a card set | Static, cheap |
| Everything centered, no asymmetric composition | Geometry: horizontal center-of-mass distribution of major elements | Static, cheap |
| Repeating heading→paragraph→card-grid rhythm, 3+ times | Structural: section-type sequence pattern match on the IR | Static, cheap |
| Equal visual weight, no dominant focal point | Visual-weight scoring (§5b perceptual family) | Vision, moderate |
| Perfectly symmetric grids, no intentional break | Geometry: grid regularity/symmetry score | Static, cheap |
| Gradient hero banner (blue/purple/teal diagonal) | Pixel heuristic on the hero crop: hue/gradient-direction detection | CV, cheap (no judge call needed) |
| Emoji as iconography | Unicode/regex scan of copy and icon slots | Static, trivial |
| Untouched framework defaults (8px radius, stock shadow, single accent) | Computed-CSS fingerprint match against known defaults | Static/DOM, cheap |
| One font, one–two weights | Enumerate distinct type treatments used; flag <3 | Static, cheap |
| Stock openers / tricolon headers / superlatives / category-naming headings | Regex + a cheap text-only judge pass (no vision needed) | Text-judge, cheap, run on 100% |
| Decorative imagery with no informational role | Semantic relevance check between image and surrounding copy | Vision-judge, moderate |
| Page-archetype mismatch (news page laid out as dashboard) | Judge: does structure match declared purpose | Text+structure judge, cheap |

**Weighting proposal, and a disagreement with the brief's implicit framing:** the deterministic static/geometry checks should be the backbone — they're ungameable by a text-only model trying to sound designed, and they run on 100% of pages at near-zero cost. I'd narrow strict zero-tolerance gate membership to those (plus the cheap CV/text checks), and **move "decorative imagery relevance," "archetype mismatch," and the perceptual-family checks like focal-point-dominance-absence down into D4 (graded) rather than gating on them.** A false gate failure blocks a possibly-fine page and erodes trust in the whole gate system; reserve hard gates for checks you'd bet money on being unambiguous, and let judgment calls accumulate as graded signal instead.

### D2 — Template-collapse gate (batch level)

This is the gate that's invisible at 5 pages and decisive at 500 — and it's a necessary counterweight to your own harness design, not incidental: a schema-first IR contract (§1) is exactly the kind of structured, templated generation that measurably reduces output diversity (see *The Price of Format: Diversity Collapse in LLMs*, ACL Findings 2025, in Sources — structured/templated prompting yields lower diversity than freer prompting across tasks). Building reliability into the pipeline creates the pressure D2 exists to catch.

Metric, computed over a sampled batch (e.g., every 20 generated pages):
1. **Section-skeleton hash distribution** — hash the sequence of section types + column layout per page (from the IR); measure entropy/concentration across the batch.
2. **Layout fingerprint clustering** — cluster normalized bounding-box geometry vectors; measure the % of the batch falling in the single largest cluster.
3. **Type/color system variance** — count distinct heading type-treatments and accent-color clusters used across the batch, excluding shared brand color.

**Proposed threshold:** batch fails if >40% of pages share the same section-skeleton hash, or the largest layout-fingerprint cluster exceeds 50% of the batch — regardless of individual page scores. Fail response: regenerate with a diversity-forcing intervention (explicit archetype rotation, drawing from different Tier 1 pattern-library entries per page), not a rubric re-score.

### D3 — Blind provenance test (headline metric)

Mix generated pages with human-made golden pages from the never-touched holdout, screenshots only, randomized order; raters (mix of design experts and naive raters) guess human vs. AI plus confidence. Report detection accuracy with a CI sized as in §5d (target ≥150–200 judgments, not 50).

**Win condition:** CI overlaps 50% with a reasonably tight band (~±7pp), i.e., detection is genuinely indistinguishable from chance, not just numerically close on too few judgments.

**Threshold to trigger Tier 3 investment (direct answer to your question):** move to serious tuning planning only if detection accuracy is reliably **≥65%** (CI lower bound clearly separated from chance, e.g. above ~58%) **and** this persists after both Tier 1 (pattern library) and Tier 2 (best-of-N against the critic) have been tried — pull the cheapest lever first. If the result lands in the ambiguous 55–65% band after Tiers 0–2, that reads as a **style gap**, which is the LoRA-scale problem in §8, not grounds for a full fine-tune.

### D4 — Editorial distinctiveness score (graded)

Sub-scores, human + judge-model, same 1–5 scale as the constitution grades for comparability but **reported and tracked as a separate axis, never averaged in**:
- Typographic range
- Compositional confidence (deliberate asymmetry/negative space use, beyond mere gate-compliance)
- Memorability (would a rater recall this page distinctly after seeing ten others)
- Intentional risk-taking (a deviation from the "safe" reading that still serves the content)

### The affirmative side — mapped back to the 14 principles

A prohibition list alone produces blandness-avoidance, not good design, agreed. Affirmative criteria and where they map:

| Affirmative criterion | Maps to composition principle(s) |
|---|---|
| Intentional asymmetry | Golden triangle / Z-pattern (deliberately weighted diagonal), rule of thirds (off-center placement at true intersection points, not dead-center) |
| Genuine scale contrast | Visual hierarchy pyramid, visual weight distribution — a real jump between primary and secondary elements, not a timid 1.2× |
| Content-driven rather than grid-driven layout | Figure-ground composition (subject dictates the frame), leading lines (lines emerging from actual content — a chart axis, a photo horizon — not decorative dividers) |
| Varied section shapes | Common region/container pattern used deliberately with irregular/varied containers, not uniform card shapes |
| A memorable anchor element | Focal point dominance, scored affirmatively rather than only as "not equal weight everywhere" |
| One deliberate typographic risk | **Gap in the 14 as given** — typography isn't explicitly named among the composition principles; fold it into visual weight distribution for now, or propose it as a 15th principle if this project owns updates to the constitution's appendix. |

---

## 7. Controls

Version and hash, per generation batch, into a single run manifest:

- Corpus bundle (content hash of the extraction snapshot, §4)
- System prompt (versioned)
- Constitution text (versioned — the constitution itself may evolve; pin a version per experiment)
- Exemplar set (which pages, what order, what format)
- Output contract / Page IR schema version
- Model + provider + exact snapshot/date where the API allows pinning (frontier models get silently updated behind a stable name — pin dated model IDs wherever offered)
- Sampling parameters (temperature, top_p, seed if supported)
- Judge model + judge prompt version + rubric version

This doesn't need a heavy MLOps platform at this scale — a structured JSON manifest committed alongside each batch's outputs is enough to make "a regression is attributable" literally true: if next week's scores drop, diff the manifests to see whether the model snapshot moved, the prompt changed, or the corpus changed. Don't over-invest in experiment-tracking tooling before Phase 2 volume justifies it.

---

## 8. The tune-vs-prompt decision

### Four tiers, priced

| Tier | What it is | Cost | Expected effect |
|---|---|---|---|
| **0 — Prompting + constitution + exemplars** | Baseline | ~1 generation call/page | Likely clears law compliance (a11y, performance are tractable via explicit instruction + automated feedback). Unlikely to clear distinctiveness — this is exactly the axis helpfulness-tuned models regress toward the mean on. |
| **1 — Composition constraints, not model learning** | A curated library of layout archetypes/section skeletons, type systems, and color systems (derived directly from the golden corpus's strong tier — this is a byproduct of §3's curation work, not a separate project) that the model selects and composes from instead of inventing | Days–weeks of design+engineering time, near-zero marginal per-generation cost | Highest leverage-per-dollar item on this whole list. Price and build this in Phase 0 regardless of which model wins — it improves Tier 2's sampling pool and would still help a Tier 3 tuned model. |
| **2 — Best-of-N against a critic** | Generate k candidates, score against constitution + distinctiveness rubric, keep the winner | See cost model below — order of $0.35–0.65/page all-in at k=8 with Sonnet-5-class pricing | Distinctiveness is high-variance; best-of-8 beats mean-of-8 by a wide margin. This buys exactly the thing you're short on, using inference compute instead of training compute. |
| **3 — Tune** | Only if Tiers 0–2 leave a measured D3 gap | See §8 data-volume section | Default to LoRA-scale style adaptation, not a full fine-tune (see below) |

**Tier 2 cost model** (illustrative, based on published Claude Sonnet 5 pricing found in research — $2/$10 per M input/output tokens, cached input $0.50/M — verify against current listed pricing before budgeting): with the constitution + exemplars cached (they're identical across every page in a run, so prompt caching turns "every generation carries the constitution plus exemplars" from a cost concern into a non-issue), a single-shot generation runs roughly $0.03/page; k=8 best-of-N runs roughly $0.25–0.30/page in generation plus $0.10–0.15/page in critic scoring, landing around **$0.35–0.65/page all-in**. At 500 pages that's on the order of $175–325 for generation+scoring — a rounding error against an FY27 Priority #1 budget. **I'm estimating token counts from reasonable assumptions about IR size, not measured figures — validate with an actual Phase 0 token count before trusting this multiplier at 500-page scale.**

### The economics levers, addressed directly

**Tune the critic, not the generator — agreed, and I'd go further.** The critic only needs to output a score + citation, a far lower-entropy task than generating a full page, so it needs less data and a much smaller base model. It's the durable, reusable asset across every generator swap, which is this project's actual thesis. But there's a sequencing implication worth naming explicitly: **a Tier 2→3 distillation pipeline (best-of-N winners → fine-tuning data) is only as trustworthy as the critic that curated the winners.** If the critic is miscalibrated or gameable, distillation launders bad judgments into the tuned generator's weights — worse than not tuning at all, because now it's baked in. Critic-tuning is a prerequisite for trustworthy downstream distillation, not a parallel nice-to-have — sequence it first.

**Capture now, decide later — the trace schema.** Instrument this from Phase 0, while still in Tier 0:

```json
{
  "trace_id": "…",
  "page_id": "…",
  "corpus_split": "exemplar | benchmark | holdout",
  "model_id": "…",
  "model_snapshot": "…",
  "prompt_version": "…",
  "constitution_version": "…",
  "draft": { "ir_ref": "content-hash", "screenshot_ref": "content-hash" },
  "critique": [
    {
      "rule_id": "law-05 | principle-clarity | composition-14 | d1-gradient-hero | …",
      "verdict": "pass | fail | flag",
      "evidence": "quoted text or bounding-box ref",
      "severity": "…"
    }
  ],
  "revision": {
    "ir_diff": "structural diff on the IR, not raw text",
    "rule_addressed": "rule_id",
    "expected_improvement": "free text + which graded dimension it targets",
    "tradeoff": "free text — what got worse or was risked, or explicit 'none'"
  },
  "acceptance": {
    "gates": { "law-05": "pass", "law-03": "pass", "…": "…" },
    "graded_scores": { "clarity": 4, "hierarchy": 3, "d4_editorial": 2, "…": "…" },
    "d3_result": "optional, if measured on this item"
  },
  "human_reviewed": { "reviewed": false, "reviewer_id": null, "override_score": null }
}
```

For this to be usable as preference-tuning data later, two things matter more than the schema itself: (1) **`tradeoff` must be honest and structured enough to filter on** — a (draft, revision) pair only becomes a clean DPO preference pair when the revision improves without a new flagged regression elsewhere; auto-exclude pairs where `tradeoff` names a new failure, or you'll train the critic to "improve X by breaking Y." (2) **`rule_id` must be granular enough to slice by axis** — you'll want to preferentially train on distinctiveness-driving pairs specifically if D3 turns out to be the weak point, and you can't do that if critiques aren't tagged down to the individual law/principle/tell.

**Each tier produces the next tier's dataset — confirmed, with the sequencing caveat above.** Best-of-N winners are a self-scored, already-curated corpus, exactly the shape rejection-sampling distillation wants: tune a *small* model on the winners, reserve frontier calls for hard pages. This composition is sound *conditional on* the critic quality-gate above.

**Style gap vs. capability gap.** My assessment: your gaps are predominantly style (~90%), not capability (~10%, edge cases in content-to-layout mapping for genuinely novel content types). The shortlist models are already strong instruction-followers — that's why they're on the shortlist — so "doesn't look AI-generated" is adaptation of a distribution the model already has the capability to produce, not a new skill. That's the LoRA case, not the full-fine-tune case, and it should be priced and budgeted as such: weeks of engineering + data prep, modest LoRA training compute, versus months of infra and data for a full fine-tune that isn't justified here regardless.

**Negative data is nearly free — agreed, concretely.** Run a standing "naive prompt" baseline generator (no constitution, no exemplars) in parallel with every real batch at trivial marginal cost — it's just another cheap generation call, auto-labeled negative without needing a human to label it. Feeds both the critic's negative class and preference tuning (draft=naive-output, chosen=pipeline-output), though this pair is less informative than real critique-loop pairs since the gap is obvious — treat it as a calibration floor, the same role the corpus's weak pages play in §3 and §5d. Pair the two: naive-prompt slop plus corpus weak pages as your negative-adjacent set.

**Honest minimum viable N, by tier:**

| Tier | Minimum viable N | Where it comes from |
|---|---|---|
| Critic SFT | A few hundred to ~1,000 labeled critique examples before trusting a tuned critic to *replace* (not just corroborate) a frontier judge | 84 corpus pages × expert critique write-ups (Appendix A step 02) is a start but thin on its own (84 examples); accumulate through Tier 0/1/2 run trace data until you cross this floor. Until then, frontier-model-as-judge stays primary. |
| Generator LoRA (style adaptation) | Roughly 500–2,000 high-quality (context, strong-output) pairs, per general LoRA style-tuning practice | 84 golden pages alone is below this floor — I'd push back slightly on treating 84 as "plausibly enough" on its own. It becomes viable combined with: Tier 2 best-of-N winners (hundreds to low-thousands, produced as a byproduct of running Phases 1–2 anyway), revision-loop trace pairs, and Tier-1-pattern-library-constrained synthetic variation, critic-filtered. Realistic path: 84 + ~500–1,000 best-of-N winners + trace pairs ≈ 1,000–2,000 usable examples, arriving as a natural byproduct of Phases 0–2 rather than a bespoke labeling project. |
| Full fine-tune (generator, from scratch) | Tens of thousands+ examples, full training infra | Not justified for this problem — the gap is style, not capability. Explicitly off the table. |

---

## 9. Scale economics

| | 50 pages | 500 pages |
|---|---|---|
| Generation (Tier 0, single-shot) | ~$1.50–2 (Sonnet-5-class) | ~$15–20 |
| Generation (Tier 2, k=8) | ~$17–25 | ~$175–250 |
| Critic scoring (Tier 2) | ~$5–8 | ~$50–75 |
| Human spot-check (~15–20% sample, ~15–20 min/page, design reviewer) | ~2–3 reviewer-hours | ~26 reviewer-hours |
| D3 rating (200 judgments target, multiple raters) | ~5–7 rater-hours | Similar, reused across drift-check re-runs (§11) |

Compute does **not** break at 500 pages — it's a rounding error even at 8x sampling. What actually breaks, in rough order:

1. **Human review bandwidth.** This is the real bottleneck, not tokens — 26 reviewer-hours at Phase 2 is a meaningful ask on expert designer time, and it recurs every time you re-run the D3 drift check.
2. **Provider rate limits / concurrency caps** at high fan-out (k=8 × many pages in parallel) — best-of-N latency stays acceptable only if the harness parallelizes candidates; check provider concurrency limits before assuming full parallelism at 500-page scale.
3. **SharePoint/Graph API throttling** if pushing generated IR back into real sites for rendering/a11y testing at volume — worth a technical spike before Phase 2, not an assumption.
4. **Judge-model drift** if a frontier judge gets silently updated mid-project — mitigated by pinning snapshots (§7), but budget for periodic re-calibration regardless.

---

## 10. Deployment reality

**Data handling.** The golden corpus lives on a Microsoft demo tenant (`m365x00104473.sharepoint.com`, "Zava") — I'm assuming this is synthetic/demo content, not real customer data, which is a materially lower-risk starting point for R&D. **Verify this assumption explicitly** rather than inheriting it; if any of the 84 pages contain accidentally-real business content, treat it with production-tier handling. Generated pages eventually target real authoring, which is a different tier: no customer content should go to a foundation model provider without the applicable enterprise no-training-on-inputs terms in place — confirm current terms with Legal/Compliance per vendor contract, this isn't something to assert generically.

**Prototype vs. production.** Phases 0–1, on the synthetic Zava corpus: free to use whatever gets the best signal fastest, including direct frontier APIs. Phase 2+, once real content is in the loop: constrained to whatever posture IT/Legal approves — most likely Azure-hosted models behind private networking, or an approved enterprise agreement with the frontier provider for the non-Azure models on the shortlist. The harness abstraction in §1 is what makes this transition a config change rather than a rebuild.

---

## 11. Phased plan

| Phase | Scope | Duration | Go/no-go |
|---|---|---|---|
| **0 — Pilot** | Small N (5–10 pages across archetypes), all shortlisted models, single-shot only. Full corpus curation (§3) on all 84 items. Extraction pipeline (§4) and Page IR schema stood up. Trace capture instrumented from day one. Initial gate/D1 implementation. A D3 *mechanic* sanity check (not a real threshold read — n too small). | 2–3 weeks | Harness works end-to-end against ≥2 model backends; gates are computably scoreable; D1 reliably flags a naive-prompt baseline. |
| **1 — 50 pages** | Narrow to winner + runner-up from Phase 0. Run Tier 0, Tier 1, and Tier 2 (k=4–8) across both, against the 46-page frozen benchmark. Full gate+grade scoring, D1/D2 on generated batches, D3 designed for ≥150–200 judgments using the 12-page holdout. Rater calibration. Trace data accumulating throughout for critic-tuning. | 3–4 weeks | If D3 detection stays ≥65% after Tier 2, plan Tier 3 (critic first, then generator LoRA if still needed) using accumulated trace + best-of-N winner data. If D3 is near chance, Tier 1/2 is validated as sufficient — proceed to Phase 2 on that configuration. |
| **2 — Scale to 500** | Lock the winning tier/model config. Run at volume against the real page backlog. Keep D2 live continuously via sampled batch checks, not a one-time gate. Keep stratified human spot-check running. Feed all production traces back into the critic-training set. Re-run the full D3 test periodically (e.g., every ~100 pages) as a drift monitor — a silent provider-side model update can regress distinctiveness without touching law-compliance scores. | 4–6 weeks initial rollout, then ongoing | Sustained D3 near-chance and D2 within threshold across drift checks; escalate to Tier 3 investment only on a confirmed, persistent regression, not a single bad batch. |

---

## Comparison table: candidate platform approaches

| Approach | Harness/swap fit | Structured output | Distinctiveness/eval control | Tenant/data fit | Fine-tuning path | Time to first result |
|---|---|---|---|---|---|---|
| **Recommended hybrid** (Foundry for production + direct frontier APIs for R&D/judging + self-hosted OSS for critic/LoRA) | Best — model-agnostic IR contract, swap = config change | High — pick per-model structured-output feature | Full control — custom harness, full trace logging | Best — Foundry path for production, frontier APIs sandboxed to synthetic corpus in R&D | Full — own the critic and eventual LoRA weights | Moderate — harness build-out is the up-front cost |
| **Azure AI Foundry only** (single-vendor, OpenAI + partner catalog) | Good within Foundry's catalog; excludes Claude natively | High (native structured outputs) | Good, if you build the same custom harness on top | Best — single governed gateway | Native SFT/LoRA support in-catalog | Fast — least new infra |
| **Direct frontier APIs only** (no Foundry) | Good if you build the adapter layer yourself | High | Full control | Weakest — no built-in tenant governance layer; you build it | Depends on vendor (Anthropic/Google fine-tuning offerings vary) | Fastest for R&D, slowest to production-harden |
| **Copilot Studio** | Poor — wrong layer, limited custom schema/trace control | Limited — built for conversational/agent flows, not a rigid IR contract | Weak — not designed for this kind of instrumented eval loop | Good (Microsoft-governed) | Not really applicable | Fast to a demo, wrong foundation for the evaluation system itself |
| **Self-hosted open-weight only** | Good once built, but you own all infra | Depends on model; generally weaker guarantees than frontier structured-output features | Full control, and you own the weights | Best possible (fully on-prem/VNet if desired) | Full — cheapest to iterate on repeatedly | Slowest — infra + likely weaker Tier 0 baseline |

---

## Where your framing is right, where I'd push back, and what's cheaper

- **Right:** the corpus-triple-duty problem (exemplar/benchmark/holdout) is real and correctly flagged. I'd add a fourth implicit demand on it — it's also the source material for the Tier 1 pattern library — which isn't a conflict, but means the §3 curation pass should be scoped to serve all of §3, §4, and §8-Tier-1 in one pass, not redone per use.
- **Push back:** Copilot Studio doesn't belong in this bake-off as a harness candidate. It's a distribution layer for a later phase, not infrastructure for building an evaluation system that needs custom schemas and full trace logging.
- **Push back, gently:** 84 golden layouts being "plausibly enough" for LoRA on its own is optimistic — it's enough once combined with Tier 2 byproducts, not standing alone. Worth correcting before it becomes a budget assumption.
- **Cheaper path not in your list:** growing the strong-exemplar pool via a small amount of human designer time (not AI at all) may be cheaper than any model-side lever if Phase 0 curation shows the strong tier is thinner than hoped. Don't assume every gap here is best closed by generation — some of it is a design-team task.
- **Cheaper path not in your list:** a tiered *serving* strategy, not just tiered *tuning* — some fraction of the 500 pages (simple announcement/news pages, say) may not need full generative layout invention at all; templated composition with light AI-assisted content-fitting could handle the "easy" fraction at near-zero generic-risk, reserving expensive generation + best-of-N for pages that actually need layout judgment.
- **Missing from the plan as given:** the real budget line is expert human time — critique authorship (Appendix A step 02), D3 rating, spot-checks — not API cost. Size this explicitly in the Phase 1/2 budget rather than treating it as incidental to the "model cost" conversation.

---

## Assumptions & open questions

1. The Zava tenant corpus is synthetic/demo content, not real customer data — verify before treating it as low-risk for direct frontier API use.
2. "Structured output" is read as: the generation contract is a versioned JSON Schema (Page IR) enforced via each provider's native schema/tool-calling feature, not raw HTML string generation validated after the fact.
3. I do not have the full 84-item corpus manifest — only the items named in Appendix C's notes. The distinct-entity arithmetic in §3 (77 distinct, 6 pre-flagged weak) follows from those notes; the strong/mid/weak tier split and the repeated-archetype-across-sites enumeration require an actual Phase 0 look at the corpus.
4. Claude model identities and pricing cited here (Opus 5, Sonnet 5, $2/$10 and $5/$25 per M tokens, prompt-cache discount) come from my own system configuration and are load-bearing for the cost model in §9 — treat as reliable. Comparative claims about GPT-5-series and Gemini 3-series specifics come from post-cutoff web search against sources that read as low-quality SEO content with internally inconsistent version numbers — treat as directional only, and replace with real Phase 0 measurements before committing budget.
5. "Copilot Studio" is read as Microsoft Copilot Studio, the low-code conversational/agent-building product.
6. 500 pages is read as a rough target volume for AI-assisted generation, not a hard ceiling on distinct archetypes needed.

---

## Sources

Benchmark/pricing claims for post-cutoff models are flagged above as low-confidence; the following were consulted and should be independently re-verified rather than cited as ground truth:

- [Claude Sonnet 5 vs GPT-5.6 Sol vs Gemini 3.1](https://www.edenai.co/post/claude-sonnet-5-vs-gpt-5-6-sol-vs-gemini-3-1-benchmarks-pricing-which-to-use)
- [Claude Benchmarks (2026) — MorphLLM](https://www.morphllm.com/claude-benchmarks)
- [Claude API Pricing (September 2026) — BenchLM.ai](https://benchlm.ai/anthropic/api-pricing)
- [Claude Pricing in 2026 — CloudZero](https://www.cloudzero.com/blog/claude-pricing/)
- [Fine-tuning Azure OpenAI models in Azure AI Foundry — InfoWorld](https://www.infoworld.com/article/3630565/fine-tuning-azure-openai-models-in-azure-ai-foundry.html)
- [Customize a model with fine-tuning — Microsoft Learn](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/fine-tuning)
- [Announcing new fine-tuning models and techniques in Azure AI Foundry — Microsoft Azure Blog](https://azure.microsoft.com/en-us/blog/announcing-new-fine-tuning-models-and-techniques-in-azure-ai-foundry/)
- [The Price of Format: Diversity Collapse in LLMs — ACL Findings 2025](https://aclanthology.org/2025.findings-emnlp.836.pdf)
- [Rejection Sampling — RLHF and Post-Training Book, Nathan Lambert](https://rlhfbook.com/c/09-rejection-sampling)
- [Inference-Aware Fine-Tuning for Best-of-N Sampling](https://arxiv.org/pdf/2412.15287)
- [Export-PnPPage — PnP PowerShell](https://pnp.github.io/powershell/cmdlets/Export-PnPPage.html)
- [Working with modern client-side pages using PnP PowerShell — Microsoft Learn](https://learn.microsoft.com/en-us/microsoft-365/community/working-with-modern-clientside-pages-using-pnp-powershell)
- [Who's Your Judge? On the Detectability of LLM-Generated Judgments](https://arxiv.org/pdf/2509.25154)
