# Review evidence tools

These opt-in, offline tools index Markdown and check whether quoted text occurs
in its cited section. A matched quote establishes source presence only. Every
result leaves semantic `support` as `unverified`. Findings and source files are
never modified. Current review panels, seats, efforts and workflows are unchanged.

## Commands

```sh
python3 scripts/markdown_section_index.py example.md --document-id docs/example.md --json > index.json
python3 scripts/check_quotes.py --document example.md --document-id docs/example.md --expected-sha256 DOCUMENT_SHA256 --index index.json --findings findings.jsonl --json
```

The checker requires an independently retained snapshot digest. It checks that
digest against the actual bytes and index metadata. Index hashes cover canonical
JSON except `index_sha256` and optional `comparison`; parser hashes cover a map
of repository-relative parser/shared-module filenames to their exact source
digests. Canonical JSON uses sorted keys, compact separators, UTF-8, no NaN,
and exactly one final newline. Duplicate JSON keys are errors. Filenames are
repository-relative POSIX paths; redundant dot components and backslashes are
canonicalized. Absolute paths and escaping traversal are rejected.

Both tools emit versioned JSON. Exit 0 means a complete report, including missing
legacy quotes and completed mismatches; exit 1 means unverifiable quote evidence;
exit 2 means structural input or snapshot failure. A stale snapshot produces one
`invalid_snapshot` result with no quote evaluations. Reports contain positions,
counts and codes, without source excerpts or absolute input paths.

## Optional quote contract

A finding has string `id`, `claim`, `location` and an optional `quote`. Existing
`location` joins and `raw`/`upheld`/`refuted` stamps retain their meaning.

```json
{"id":"example","claim":"A synthetic claim","location":"docs/example.md:2","quote":{"section_id":"s-example","text":"The exact passage."}}
```

`quote` accepts one object or a nonempty ordered array of objects, each with
nonempty strings `section_id` and `text`. Missing/null quotes are `missing`.
Malformed containers and members are `unverifiable`, retaining array indices.
Results include `quote_index`, `status`, `reason`, `match_mode`, `spans`,
`diagnostics`, `occurrence_ambiguous` and `support`. Positions are one-based
Unicode character columns, with exclusive ends. All repeated occurrences are
retained. Finding rollups prefer missing, then unverifiable, then mismatched,
then matched, and retain separate counts. A mismatch is a completed check.

Literal matching runs first. Prose normalization permits only ASCII whitespace
collapse (including CRLF) and curly-to-straight single/double quotes. It preserves
case, punctuation, dashes, accents, backticks, zero-width characters and markup.
Normalized searches cannot cross a code/prose boundary. Code permits literal
matches only. Unmatched `...`, `…` or `[…]` yields `elision_ambiguous`; fragments
are never joined. Text found elsewhere cannot rescue a cited section.

Diagnostic searches can report descendant presence, heading-boundary crossings,
location disagreement or unparseable locations. `markup_drop_match` is diagnostic
only: balanced `**strong**`, `__strong__`, `*em*` and `_em_` are removed from
prose using non-word outer and non-whitespace inner boundaries. It never removes
code delimiters or permits a match on its own.

Redaction takes precedence over presence, including a match overlapping any part
of a redaction marker. The marker is imported from the existing hook module
without invoking its entry point. Known transformed quotes are unverifiable.
Optional quote `provenance.text_state` is `original`, `transformed` or `unknown`;
`original_text_sha256` may retain a digest of original bytes. An imported row is
one with `source.import` (the import branch contract), or explicit
`source_type: "imported"`. Without original quote provenance it yields
`transformation_unknown`. Raw imported output is never used to recover originals.
Explicit document attribution or a parsed location identifying a different
document yields `out_of_scope`, without forcing exit 1.
Location paths use the same canonicalization as document identities. A bare
basename matching the indexed target is an alias within this single-document
invocation. Line/column forms such as `example.md:2:5` and
`example.md:2:5-3:9` retain their line range. Unparseable or invalid location
identities never silently skip quote evaluation; their agreement stays unknown.
When either path differs by a leading directory prefix at a slash boundary,
the checker evaluates source presence with `location_uncertain`. This is neither
an alias assertion nor evidence of location agreement. Other directory paths
remain distinct; a shared basename alone does not equate two qualified paths.

The findings reader accepts JSONL, a JSON array, one finding, or a `findings`
array wrapper. Explicit `type`/`record_type` metadata and event rows are skipped
with diagnostics; malformed untyped rows are errors. Canonically identical rows
collapse. Snapshot mode rejects conflicting IDs. `--input-mode ledger` permits
last-full-row stamp changes only in `status`, `convergence_refs`,
`disagreement_refs`, `novelty`, `risk`, `taste`, `taste_kind` and `cluster_id`.
Claim, quote, location and provenance changes are errors. Partial stamp records
are unsupported. Row hashes and indices remain in diagnostics.

## Markdown index contract

The index includes a preamble, ATX/Setext headings, heading ancestry, parent IDs,
heading spans, inclusive direct and subtree line ranges, content hashes, and
`ceil-unicode-chars/4` token estimates. Every source line has one direct owner;
an empty document has no owned lines. Fenced/indented code, frontmatter and HTML
comments cannot contribute headings or declarations. This is a conservative
subset, without Markdown rendering or HTML parsing. Seven-plus hash headings
produce unsupported-heading diagnostics.
Source lines end only at LF, consistently with locations and span reporting;
CRLF is preserved and other whitespace characters do not create new lines.
Inline code protects literal comment markers; active HTML comments close even
on indented lines. Trailing heading comments are excluded from heading identity.
Comment contents are removed without padding, so changing an embedded comment's
length cannot change an implicit ID. A standalone HTML comment block owns its
whole closing line; text there cannot introduce a heading. A multiline inline
comment is explicitly diagnosed at its opener, including any potential hidden
structure; unclosed-comment spans also identify their original opener.
Nested list content is prose when supported by a preceding list container;
indentation at least four spaces beyond that container's content column is code.
Fences use indentation relative to the list content column. Fences and thematic
breaks reset list context, so stale list state cannot reclassify later code as prose.
An unclosed opening frontmatter delimiter produces an explicit diagnostic and
the source is parsed as Markdown. Multiline Setext headings are explicitly
unsupported and diagnosed across their whole block, without guessing a shorter
heading. Text-search diagnostics include counts and original source spans;
emphasis diagnostics search each prose segment independently of adjacent code.

Explicit trailing `{#anchor}` IDs are hashed with document identity; duplicate
anchors invalidate the index. Otherwise IDs hash document identity, exact trimmed
heading ancestry and identical-sibling occurrence ordinals. Body edits and line
drift preserve unique paths. Heading/ancestor renames, moves and heading-status
changes change implicit IDs. Duplicate headings and descendants have
`snapshot_only` identity. Citations always bind a snapshot even with stable IDs.
`--previous index.json` reports retained/added/removed/content-changed IDs and
duplicate ambiguity, without fuzzy remapping. Local fragments resolve explicit
anchors only; renderer-specific slugs are not inferred.

Explicit declarations include `Ruling key`/`Term name` headings and
`**Ruling key:** ...`/`**Term name:** ...` lines. Named wiki references, fragment
links, external links and explicit Markdown reference definitions/usages retain
resolution states and source spans. Definitions are syntactic declarations,
without authority claims. Profile candidates are kept separately from definitions.

## Declarative syntax profiles

`--syntax-profile profile.json` accepts this closed, versioned schema:

```json
{"schema_version":1,"id":"synthetic","version":1,"rules":[{"id":"numbers","scope":"heading","recognizer":"numbered_heading","trailing_dot":true},{"id":"refs","scope":"all","recognizer":"section_reference"},{"id":"relations","scope":"all","recognizer":"relationship","vocabulary":["depends on","superseded by"],"case_sensitive":false}]}
```

Rule IDs are unique. Scopes are `heading`, `body`, `all`. Recognizers are
`numbered_heading`, `section_reference`, `heading_annotation`, `heading_status`,
`relationship`, `bold_lead`. The annotation/status/relationship recognizers require
literal `vocabulary`; `case_sensitive` defaults true. Optional `candidate_kind`
is one of `ruling_candidate`, `status_candidate`, `relationship_candidate`,
`term_candidate`. Unknown recognizers/parameters fail closed. No expressions,
modules, code execution or network resources are accepted.

Leading dotted heading numbers preserve canonical `number` and `number_raw`.
Generic mode accepts `N(.M)*` followed by whitespace/end. Only a profile with
`trailing_dot: true` also permits one trailing dot terminator: `4.` becomes
canonical `4` and raw `4.`; leading zeroes remain distinct. Section references
resolve by canonical number: zero targets unresolved, one resolved, multiple
ambiguous with all target IDs. `§a–b`, `§a—b`, `§a-b` are explicit
`range_unexpanded` references retaining both endpoints; intermediate sections are
never inferred or silently counted as resolved.
A bare range endpoint requires an adjacent dash and number (`§2–3`). Spaced
dashes require an explicit second section marker (`§2 — §3`); prose punctuation
such as `§2 — 3 seats` retains the ordinary resolved `§2` reference.

Relationship candidates retain direction and source section. After the literal
phrase, the allowed gap is ASCII spaces/tabs, colons and emphasis characters
`*`/`_`. Commas and `and`/`or` join multiple explicit targets. A phrase with no
immediate target remains a `no_target` candidate. A range is one unexpanded target.
Candidates never become authoritative dependency or supersession edges. Bold-lead
terms include list forms and cover the single-line syntactic declaration block.

Profiles belong to their target project. Only independently authored synthetic
profiles and fixtures belong here. Private target acceptance uses pinned source
bytes and count-only reports, independently checking heading/syntax counts and
line ownership. Document-derived text, transcripts and review bodies stay out of
public artifacts. Live melange integration is a separate change after the import
contract lands; these tools are independently usable now.

## Verification

```sh
uv run --project tests pytest tests/structural/test_review_quote_check.py tests/structural/test_markdown_section_index.py -q
```
