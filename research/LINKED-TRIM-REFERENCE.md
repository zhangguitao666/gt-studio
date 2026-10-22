# Linked non-ripple timeline edge trims

Two new guarded native timelines contain generated motion.mp4, source requested12→60, duration48 at relative48. One video/audio pair is explicitly linked and native linked-selection control is observed enabled. The playhead is set to01:00:03:00 (relative72 at24fps). CUA selects all clips under the playhead, then executes Trim→Resize→Start/End To Playhead. These cases do not isolate a single selected member from its linked peer.

## Observed native readbacks

| Case | Start | Duration | Source start→end | Linked peers |
|---|---:|---:|---|---|
| Before either trim |48|48|12→60|Reciprocal video/audio|
| Trim end to72 |48|24|12→36|Retained, both items|
| Trim start to72 |72|24|36→60|Retained, both items|

All starts subtract captured origin86400. Original item IDs remain stable. These normal-speed examples return source-end values matching an exclusive interval; this does not generalize to native retime/reverse boundary conventions.

## Source-bound evidence

The saved project was captured through sqlite3 backup into `evidence/reference-linked-trim.sqlite`, SHA256 `5d5a1ed5754933a7590f2902b9320c41dc0f845139057d9e4c31629e7c2b4228`. REA exact PK/FieldsBlob inspection is retained in `evidence/resolve-linked-trim-markers.json`, Evidence `ev_9a72e0ea286c15b47ef1afc142a180b63a79771ab4c082ccac5a916e19829870`;28rows, no truncation, all extracted record anchors present.

`linked-trim-runtime.json` retains four exact before/after payloads, blob/payload hashes and offsets from bounded standard-Zstd extraction. Marker strings prove decoded-blob co-occurrence only; native wrapper associations are not inferred. Prepare/capture Lua scripts guard the dedicated reference project and new timeline prefixes. One CUA menu lookup failed because entry indices changed; it performed no trim, and the action was resumed using fresh named menu entries before capture.

## Independent implementation

`trim_clip_edge(clip_id,edge,frame)` moves a selected absolute timeline boundary and applies the same edge delta to explicit group peers. It preserves timeline/source mapping, including rational constant-speed and reverse positions; freeze retains its sampled source range. Non-ripple trims leave unrelated and following items in place. Source exhaustion, nonpositive duration, negative start, peer collision or invalid surviving transitions reject the entire dispatch and preserve undo history.

`trim_clip` now atomically edits source fields and optional timeline start across explicit peers; this is distinct from the edge-addressed API. Unspecified rational source endpoints are retained. The inspector submits only changed source endpoints and uses one transaction. The prior item-only source edit limitation is removed for these explicit groups; universal native inspector behavior remains unverified.

`verify_linked_trim.py` replays both native cases through actual stdio MCP, comparing normalized starts/durations/link peers and exact source getter values for these fixtures. Independent after outputs decode96frames for start trim and72for end trim. Retained RGB/PCM equals the corresponding independent pre-trim intervals, and newly black opening duration has silent audio. Undo/redo and save are checked. These media checks do not compare native rendered pixels/audio.

Tests additionally cover rational50/150%,reverse,freeze,source bounds,peer collision and transition rollback. Both UI buttons are tested against the real HTTP service. Native outward trim, offset/mixed-length groups, locks, selected subsets, ripple/roll/slip/slide, general retimes and full Edit parity remain open.

Final integration:128tests pass after fixing transport-before-project-state ordering. The configured Codex MCP launcher advertises43tools and successfully trims the live dedicated demo via stdio into shared HTTP state. Actual running-window verification of the new controls is pending: CUA reported the Mac locked. See linked-trim-integration-verification.json for the explicit pending state.
