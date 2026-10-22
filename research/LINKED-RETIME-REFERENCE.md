# Explicit linked speed, reverse and freeze

set_clip_speed now applies percentage and pitch options to every explicit linked member in a single dispatch. Ripple changes each member duration and shifts following clips on that member track. Non-ripple preserves duration while source handles allow, inheriting the previously measured single-clip source-bound rules. No keyframe stretch or general native synchronization policy is claimed.

An interior freeze applies the selected member's relative offset to every peer. The offset must fit every member, otherwise the whole action rolls back. Moving prefixes and frozen tails form separate link groups; a tail-only ripple delete retains the prefixes. Frozen audio is muted. Source samples follow each member's own rate and source range. Arbitrary offset/mixed-length native behavior remains unverified.

A related correction shifts a future transition window when upstream ripple retime moves both endpoints equally. Retiming a transition endpoint itself can still invalidate that transition and reject; complete native retime/transition interaction remains open.

## Retained native evidence and decoded-output bridge

verify_linked_retime.py consumes the ten existing cases in native-media-comparison.json and its source-bound retime/freeze records. It verifies the original native exports, previous independent embedded-audio exports, their saved projects, source media and exact decoder identity before reuse. Each case is recreated through actual stdio MCP with audio detached and explicitly linked before applying the captured action parameters.

All ten linked video timing sequences match the retained native start/duration/percentage readbacks. Independent audio items have matching timing, but native audio item getter structures were not captured by the original probe and are not inferred here.

Each new linked export is fully decoded at640×360RGB24 and48kHz stereo PCM16. These streams are byte-identical to the prior independent embedded representation. The existing native image/audio metrics can therefore be retained under the verified artifact/decoder chain; this does not erase the original nonzero pixel/audio residuals or turn old measurements into new runtime observations. Exact hashes and prior metrics are stored per case in linked-retime-verification.json.

The older default-playhead freeze retains its original selected-state reconstruction: freeze whole independent clip at0 then set frozen source46→47. It is not evidence that the original out-of-clip/default playhead action is equivalent. The three controlled freeze positions retain their explicitly captured playheads.

## Checks and remaining obligations

Eleven engine tests cover linked vs embedded decoded RGB/PCM for eight speed/ripple variants, pitch disabled, interior freeze PCM prefix/silent tail, separate link groups, peer range rejection, future A/V positions and surviving transition windows. Three real Qt→HTTP speed-button tests cover half speed,reverse,freeze and selecting the new frozen tail. The older mixed frozen/moving source-edit fixture now explicitly unlinks before freezing one side, because linked speed updates correctly freeze both sides.

Full suite150passed. The configured Codex MCP launcher exposes43tools and applies linked200% ripple with pitch correction disabled to the shared demo: both tracks become23frames at0 followed by47frames at23. One undo restores the whole prior group arrangement and redo restores the edit. See configured-mcp-linked-retime-verification.json and linked-retime-integration-verification.json.

Actual current desktop-window verification remains pending after the earlier Mac-lock condition. No CUA interaction or native runtime observation is invented for this stage. Full Resolve parity remains open, including linked selection,track locks,mixed media/group policies,keyframes,speed curves,retime interpolation,source-audio algorithms and the larger Fusion/Color/Fairlight/codec/hardware requirements.
