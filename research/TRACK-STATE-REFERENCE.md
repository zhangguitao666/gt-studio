# Track enable/lock: independent contract and native declaration evidence

The installed Timeline scripting declarations expose SetTrackEnable,GetIsTrackEnabled,SetTrackLock,GetIsTrackLocked at lines2252–2263. track-state-api-evidence.json records the exact declaration anchors and source SHA256 against feature-inventory.json. This is declaration evidence only: native rendering and native locked UI/API mutation behavior have not been runtime-compared for this milestone.

## Implemented independent behavior

Tracks persist enabled/locked booleans, defaulting to true/false when older schema1 projects are opened. set_track_state updates either flag and participates in undo/redo. The desktop has an explicit track selector, Enabled/Locked controls and Apply track state; timeline labels show OFF/LOCKED and disabled clips are dimmed.

Video-track enable masks picture, retaining embedded source audio; audio-track enable masks its audio items. Independent detached A/V therefore has separate picture/sound controls. Disabled upper video reveals lower layers; disabled video transitions do not composite. Timeline duration includes disabled clips. Sources with no active output contribution are not opened, so disabled offline media cannot block export when it contributes neither picture nor audio. Embedded audio still needs its source when video is off.

Locked tracks reject changed clip data or their transition records at the shared transaction boundary, including indirect linked moves,trims,splits,speed,linking and ripple edits. Rejected edits restore the whole project and undo/redo history. The canvas avoids starting a drag on a locked clip. Explicit output/lock changes,undo/redo,project switching and non-track changes remain available. This deliberately stated independent policy is not asserted to match all native API exceptions,track sync-lock rules or selection behavior.

## Executed checks

Fifteen engine cases cover locked direct/linked edits,transition insertion/removal,actual RGB/PCM stream masks,embedded audio retention,lower-layer reveal,old-project migration,flag validation,persistence and disabled offline sources. One real Qt→HTTP control test locks/disables audio,rejects an indirect video move,checks actual mouse events cannot initiate a locked drag,then unlocks and moves both members.

verify_track_state.py exercises actual stdio MCP and decodes three independent MOV outputs. Video-off retains48frames of black picture with baseline PCM; audio-off retains baseline RGB with silent PCM. Failed linked speed leaves the locked state unchanged; one undo restores both flags. Saved flags reopen correctly. The configured Codex MCP launcher separately advertises44tools and renders a48-frame visible/silent demo while rejecting a linked move through its locked audio peer. Source and output hashes are retained in the verification reports.

The new source-input filtering path also replays all ten retained retime/freeze cases with --run-name track-state. Full decoded linked RGB/PCM remains identical to the previous embedded baseline, and prior native residuals remain unchanged under the verified artifact/decoder chain. This run uses a separate workspace/report to preserve the earlier milestone artifacts.

Full current suite166passed. Actual running desktop controls and native enable/lock policy comparisons remain pending; the earlier desktop lock requires manual unlock before CUA work can resume. No declaration,offscreen test or independent output is represented as that missing native runtime proof. Full Resolve parity remains open.
