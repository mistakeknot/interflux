# fd-security (seed adjacent)

## Findings Index
- [P0] document.md:20-22 — token_id from untrusted query string used in os.path.join without sanitization → path traversal outside CACHE_DIR
- [P0] document.md:25-30 — store() writes plaintext secret to attacker-influenceable path; combined with traversal, arbitrary file overwrite
- [P1] document.md:33-45 — lookup() trusts in-process index, never re-reads/re-validates file expires; revoked/rotated credential served from memory
- [P1] document.md:48-51 — purge_all() only clears local _index; multi-process means rotated token stays live in sibling processes until TTL
- [P2] document.md:28-29 — open(path,"w") with no explicit mode; secret file may be world-readable under permissive umask
- [P2] document.md:44-45 — secret returned as immutable str, lingers in heap, exposed in core dumps
- [P2] document.md:13 — CACHE_DIR hardcoded, un-namespaced; co-resident service can read/inject token files
- [P3] document.md:9 — hashlib imported but unused; abandoned safe-filename design left traversal surface exposed [t]

## Findings
- **[F1] P0 document.md:20-22** — Path traversal: token_id from query string concatenated into path with no sanitization.
  evidence: `return os.path.join(CACHE_DIR, token_id + ".json")`; comment says "token_id comes straight from the request query string."
- **[F2] P0 document.md:25-30** — Plaintext secret written to attacker-influenced path; with F1, arbitrary file overwrite.
  evidence: `with open(path, "w") as f: json.dump({"secret": secret, ...}, f)` — no path validation, no atomic write.
- **[F3] P1 document.md:33-45** — Index-disk desync breaks revocation; lookup reads expires only from _index, opens file but never re-checks file's expires.
  evidence: comment L43 "Index says live -> return without re-reading or re-validating the file"; `json.load(f)["secret"]` discards file expires.
- **[F4] P1 document.md:48-51** — Cross-process revocation gap: purge_all clears only local index; siblings serve revoked tokens up to 300s.
  evidence: `_index.clear()` local; context "each process has its own _index"; TTL_SECONDS=300.
- **[F5] P2 document.md:28-29** — Default umask exposes secret files; no os.open(...,0o600) or chmod.
  evidence: `with open(path, "w") as f:` no mode argument.
- **[F6] P2 document.md:44-45** — Secret lingers in heap as immutable str, exposed in memory dump.
  evidence: `return json.load(f)["secret"]`.
- **[F7] P2 document.md:13** — Hardcoded un-namespaced CACHE_DIR shared across services.
  evidence: `CACHE_DIR = "/var/run/tokcache"`.
- **[F8] P3 document.md:9** — hashlib imported but unused; abandoned safe-filename design.
  evidence: `import hashlib` never referenced again.

## Verdict
Dangerous trust boundary: raw attacker input names files and locates secrets; multi-process makes purge_all ineffective for revocation. Highest-risk intersection is F1+F2 (arbitrary file write).
