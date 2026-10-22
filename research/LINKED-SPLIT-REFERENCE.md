# Linked A/V blade cut reference

In the dedicated native reference project, a new generated-media timeline `REA_LINKED_SPLIT_20261022_114808` contains one video and one audio item, source range requested12→60, duration48 at relative0. `SetClipsLinked` returned true. Current timecode was set to01:00:01:00 (relative24 at24fps). With native linked-selection control observed enabled, the Timeline→Split Clip menu action was invoked through CUA. Before and after GetLinkedItems readbacks were captured through separately guarded scripts and saved into marker payloads.

## Source-bound evidence

- `evidence/reference-linked-split.sqlite`: consistent sqlite3 backup of the saved dedicated project, SHA256 `4c7fff47476cb35ef27d668817dd6193a568612fcd56171015a39eaa1fb3b626`.
- `evidence/resolve-linked-split-markers.json`: canonical REA inspect_sqlite_database Evidence `ev_da0db5ee0b0dcd4ce1f1b02acc99215b1e9902a373f1071dbe6906f13da7bc8c`, exact PK and FieldsBlob columns;25rows, no row truncation. Both payloads reside in returned PK `a699d26c-711c-4dd9-ab71-51f67ac7c860`.
- `linked-split-runtime.json`: bounded standard-Zstd decoding and exact JSON extraction, retaining blob, payload hashes and byte offsets. Marker names establish decoded-blob co-occurrence only; no private wrapper association is inferred.
- `scripts/probe_resolve_linked_split_prepare.lua` and `..._capture.lua`: explicit native getters; UI invocation is separate CUA observation, not an API Split method.
- The initial wrong-column request is retained as `evidence/resolve-linked-split-invalid-column.json`; it is an input error and contributes no observation.

## Observed native relationship

Before: video[0,48) links to audio[0,48), and vice versa. After: video[0,24) links only to audio[0,24); video[24,48) links only to audio[24,48). Each audio item reports the reciprocal video peer. There are four items, with distinct prefix and tail groups; original prefix IDs remain stable.

This establishes one aligned normal-speed A/V pair and the observed menu/control state. It does not establish arbitrary offsets, disabled linked selection, selected subsets, track locks, retimes or other blade modes.

## Independent implementation and verification

`split_clip` now splits every linked member crossing the absolute timeline frame, retains exact rational source intervals, and partitions the group into before/after groups. Singletons become unlinked. A tail-only ripple delete then removes only the tail A/V pair. Independent non-crossing members are partitioned by side; that generic policy remains unverified against native offsets.

`verify_linked_split.py` uses actual stdio MCP and compares normalized before/after item locations, durations and peer relationships. Independent48-frame ProRes outputs before/after split have identical decoded RGB and PCM; deleting the tail produces24 prefix frames and the matching PCM prefix, and undo restores all four items. These media equalities compare independent outputs, not native rendered pixels/audio.

Five engine tests cover the native relationship, full decoded frames, rational50/150%/reverse/freeze structure, save/open, undo/redo and tail-only ripple deletion. The real Qt→HTTP linked-detach test also splits and deletes only one side. Split-stage suite111passed; subsequent transport-reconnection fixes bring the full suite to113passed;42publicMCPtools. Full Resolve parity remains open.
