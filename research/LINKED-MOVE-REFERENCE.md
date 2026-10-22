# Linked A/V move reference

A new guarded native timeline `REA_LINKED_MOVE_20261022_120000` uses generated motion.mp4, requested source12→60,48frames at relative48, one explicitly linked video/audio pair. The native linked-selection control is observed enabled. CUA Trim→Select Nearest Clip For→Move and Trim→Nudge→Right One Frame were invoked. Saved before/after getters show both items at48→49, durations48 unchanged, reciprocal linked IDs retained. This is a bounded native observation of a single aligned pair.

The attempted coordinate drag returned noWindowsAvailable and is not claimed executed. The native window's screenshot was initially stale relative to its accessibility tree; raising the window refreshed it. The final measured operation used named menu entries, not inferred drag coordinates.

## Provenance

- Consistent sqlite3 backup `evidence/reference-linked-move.sqlite`, SHA256 `a64df762f926e208b1298ba2e6cbde0aa48338aed5e358807512ab11fff2e133`.
- REA exact PK/FieldsBlob inspection `evidence/resolve-linked-move-markers.json`: Evidence `ev_aa606e61c9687c96f351f7488e9953a48bbfe63becb86fa95b3762948a8fd56f`,26rows, no truncation. Both extracted payload PKs are present in the returned rows.
- `linked-move-runtime.json` preserves exact payload and blob hashes/offsets from standard-Zstd extraction; marker names prove decoded-blob co-occurrence only, not a private wrapper association.
- `probe_resolve_linked_move_prepare.lua` and `..._capture.lua` guard the dedicated reference project and timeline prefix. UI commands occur between these captures.

## Independent behavior and limits

move_clip applies the selected timeline delta to every explicit group member. The selected item may move to another same-kind track in the same timeline; peers retain their tracks. All final tracks validate before commit. Negative peer positions or any peer collision roll back the entire dispatch and undo history. When both endpoints of a surviving transition move together on one track, its window shifts equally.

verify_linked_move.py compares native before/after normalized item starts, durations and link peers through actual stdio MCP. Independent outputs decode96frames before and97after; their48-frame source video and PCM segments are byte-identical after removing the respective48/49-frame lead. The49-frame audio lead is silent. Save/undo/redo are checked. These pixel/audio comparisons use independent outputs, not native rendered media.

Engine tests additionally cover peer offset preservation, audio-track conflict rollback, negative peer starts, selected-item track changes, same-kind destination constraints and surviving transition movement. The Qt timeline move signal is exercised in both directions against the real HTTP service.

Generic native overwrite/collision rules, vertical peer track mapping, disabled linked selection, track locks and offset/mixed-length linked groups still require reference cases. Native linked trim/speed, complete UI selection and full Edit parity remain open.
