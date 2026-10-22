# REA findings and eight-page reconstruction checklist

The saved REA records identify the installed Resolve package, native executable layout and packaged resources. They do not establish its internal feature algorithms or parity with GT Studio. The current independent project contains an editing/rendering implementation and MCP adapter; **all eight page-level parity requirements remain open**.

This report summarizes [summary.json](summary.json), regenerated with `python3 scripts/summarize_rea.py`. That script validates inventory array counts and captures source hashes and declaration anchors for the current independent implementation. It does not execute Resolve or assume runtime behavior from file names.

## Saved REA evidence

| Record | Evidence ID | Immutable subject SHA-256 |
| --- | --- | --- |
| [Info.plist](evidence/resolve-plist.json) | `ev_ce19d34ad04b8054c6d1601bace39f8c57662045c2318ffc8606ab02b7f9a60b` | `7539507115e554d8b936253934c394d9ded2b8f509eb5edd1cb58b047391a2f4` |
| [Mach-O](evidence/resolve-macho.json) | `ev_b5b52901c547ca2744b48f7918c8e59b58d6af9309da58ee0fa1dc7275785970` | `cc134e9e1c352e7dc77dc665b47529009b2a9d6d284b6d668fadf9a7bdf46499` |
| [Artifact inspection](evidence/resolve-artifact.json) | `ev_8ba2ba923f14abf1e9846fb0ff339300492109d75cc8367ce45ef3ffec37bfe3` | `4acddce977520bdeaf6ffae6880e2e7e678e0ab3612572741ea3369aeed8b599` |
| Nested artifact inventory | `ev_0ae16c4eca8df053b55cf16f196af422229fe0ddc0083b122925fdebba251920` | Same artifact subject digest |

The plist's `/normalized_result/bundle` identifies `com.blackmagic-design.DaVinciResolve`, executable `Resolve`, short version `21.1.1`, bundle version `21.1.10010`. These installed metadata fields are separate from the later successful Lua Console version query described below.

The nested inventory at `/normalized_result/substeps/0/evidence/normalized_result` contains **3,624 deduplicated artifact nodes, 4,624 path occurrences and 4,578 containment edges**. The summary script checks array lengths against manifest counts and checks unique artifact/occurrence IDs. These are artifact counts, not features, source modules, or functions. Graph digest: `c729967ff56b1e3329db1a1deee374269fab303f02ce3189678082f41ecd66d2`. Directory identity is the REA artifact-manifest identity, not a hash of one arbitrary file.

The Mach-O `/normalized_result/architectures/items` identifies x86_64 and arm64 slices. Inspection selected arm64 at container offset 533,102,592. Build metadata records minimum macOS 15.0 and SDK 26.2. `/normalized_result/dependencies` contains **136 load dependencies**, marked exhaustive for this inspected slice. This is not an exhaustive list of dynamically loaded plugins or runtime-used libraries.

Mach-O imports contain 24,120 observed records and exports 15,998 observed records. Both have `total: null` and `exhaustive: false`. Preserve those distinctions: symbol names may be stripped, hidden, chained or unsupported by inspection tools. These tables do not establish a recovered source implementation or complete call graph.

## Packaged names as investigation leads

The following absolute paths are observed package occurrences. Every matching occurrence, artifact SHA-256 where available, occurrence ID and exact JSON-pointer anchor is retained in `summary.json#/packaged_name_leads`. Symlink/path occurrences may have no content artifact or hash; absence of a hash must not be replaced with an invented file identity.

| Candidate area | Concrete package path | Interpretation boundary |
| --- | --- | --- |
| Fusion | `/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/libFusionPage.dylib` | Candidate native page component; node registry and evaluation remain unknown. |
| Fairlight | `/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/libFairlightPage.dylib` | Candidate audio page component; no routing/DSP behavior inferred. |
| Audio plugins | `/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/libBMDAudioPlugins.dylib` | Name lead only; plugin inventory and DSP require additional evidence. |
| Color | `/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/libOpenColorIO.2.5.dylib` | Packaged library presence does not prove a particular active transform. |
| Media | `/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/libavcodec.60.dylib` | Codec capability and licensing cannot be inferred as the complete Resolve format matrix. |
| Camera media | `/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/REDDecoder.dylib` | Camera SDK lead; actual decode outputs and options require testing. |
| AI | `/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/libonnxruntime.1.13.1.dylib` | Inference runtime name does not establish available models, inference parameters or output quality. |
| Hardware | `/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/libDaVinciPanels.dylib` | Control-surface lead only; no protocol or hardware equivalence established. |
| Cloud | `/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/libdavcloudclient.dylib` | Candidate network component; no cloud traffic or synchronization semantics observed. |

## Runtime boundary

The saved [native UI result](evidence/resolve-native-ui.json) is a **`VALIDATION_ERROR`**, caused by missing numeric `pid` and `windowId`. It has no REA evidence ID and contains no runtime UI observation. It must not be counted as successful UI evidence. The summary records this as `error_not_observation`.

The later [runtime-observations.json](runtime-observations.json) retains CUA-transcribed native UI and Lua Console facts separately from canonical REA evidence. The Console probe reported **52 invocations with successful `pcall`**, runtime version `21.1.1.10`, product `DaVinci Resolve`, `IsStudio=false`, current page `deliver`, and an exact match for the dedicated `REA Reference · 2026-10-21` project. The reported settings table has 158 entries; render formats 22 entries and audio formats 7. Per-extension codec table counts are retained in that observation file. Repeated codec queries mean 52 invocations must not be presented as 52 distinct API methods. The later archived per-query payload contains 25 distinct successfully invoked method names; this is an invocation inventory, not complete semantic verification.

Successful `pcall` establishes that the invocation did not raise a Lua error in that context. It does not prove a useful return, complete method semantics, an encode, or output fidelity. In particular the current-timeline call returned nil. Empty-table/sentinel behavior remains uninvestigated. The 22 reported render formats are reference-application table entries, not 22 independent output formats implemented by GT Studio.

The original retained 34,333-byte JSON payload was later saved into a reference timeline marker and recovered from an offline SQLite backup. Exact bytes are now in `evidence/resolve-runtime-api-payload.json`; `runtime-api-archive.json` records the derivation. The original payload's io-related persistence field remains unchanged historical data; its cause was not established. The old requested `resolve-runtime-api.json` path is still absent. Canonical REA SQLite Evidence binds the saved marker fields (`ev_2fa61bbaaa32bea338230110e6fe37872e2064ae7f3b1b804f14620d996ef5ef`), while the extracted native probe payload retains its separate provenance.

The earlier external MCP bridge attempt remains recorded as `BRIDGE_UNAVAILABLE`. It occurred before successful internal Lua Console probing and does not negate those Console observations. Conversely Console success does not prove the external bridge is now available. Native observations also confirm the eight page controls; selecting Photo still showed Cut-style content, so complete Photo semantics remain unknown.

## Current implementation: source inspection

The independent [engine](../frameforge/engine.py) uses JSON project persistence and FFmpeg-based probing/rendering. Its present source implements frame-addressed clip placement, split/trim/move/delete, ripple deletion, constant speed/reverse/freeze, rational source boundaries, tracks, markers, history, still-image import, transforms/opacity, fades, SRT cues and basic color/audio properties. Its renderer builds a filter graph with letterboxing, transformed overlays/opacity, image/audio fades, basic color adjustments, per-clip gain and stereo mixing. Output paths include MP4 H.264/AAC, MOV ProRes/PCM and WAV PCM. This is a concrete implementation choice, not evidence of Resolve's algorithms.

The [control contract](../frameforge/control.py) declares 38 control actions at the current source snapshot, of which 37 are public MCP tools and one is a desktop heartbeat (counts derived from source and verified tool listing). The [service](../frameforge/service.py) serializes shared project access and submits background renders against copied project state; job state is held in memory. Requested playhead/playback/page state and desktop-observed heartbeat state are represented separately, including pending commands; this is not proof every requested command was applied. The [MCP adapter](../frameforge/mcp.py) implements newline JSON-RPC initialization, tool listing/calls, resource listing/reads, and forwards actions to the shared local service. Source inspection proves these code paths exist; runtime correctness is the subject of separate execution/test artifacts.

The [UI](../frameforge/ui.py) contains a media pool, source viewer, timeline and property controls. Its eight page buttons and `set_page` notices describe current limitations. Selecting a page button alone does not create a separate native feature engine. The separately captured CUA observation verifies a moving test pattern in the native preview and a playhead change from `00:00:00:00` to `00:00:00:08` with Pause active. This establishes that bounded playback interaction, not complete real-time timeline parity; compositing, transforms, fades, color and audio effects still require fixture-specific preview/export comparison.

`summary.json#/implementation` records hashes, function/class source line spans and the action list at regeneration time. Since other development continues, regenerate the summary after changes before treating those anchors as current.

## Eight-page parity checklist

All boxes remain unchecked because end-to-end reference equivalence has not been demonstrated. Existing actions are development entry points; they are not substitutes for the missing obligations.

| Page | Existing implementation/actions by inspection | Open obligations and acceptance evidence |
| --- | --- | --- |
| ☐ Media | `probe_media`, `import_media` including still handling; engine media methods; UI import/media pool/source preview | Full format/RAW metadata and decode corpus, storage browsing/bins, relink/proxy/optimized-media semantics, stereo/multichannel interpretation, clone checksums, frame/timecode and metadata equality. |
| ☐ Photo | Page button and explicit unsupported-workflow notice | Observe original Photo workflows and controls, define complete requirements, then implement and compare actual processing/persistence/output. A still on the timeline is insufficient. |
| ☐ Cut | `append_clip`, `split_clip`, `trim_clip`, `move_clip`, `delete_clip`, `ripple_delete`, markers | Source tape, sync bins, Cut-specific editing/gestures, multicam switching, synchronized review and exact clip/ripple/trim behavior with reference project fixtures. |
| ☐ Edit | Frame tracks/timelines, edits, constant speed/reverse/freeze, SRT cues/burn-in, transforms/opacity/fades, `undo`/`redo`, project save/open and shared transport requests | Full edit semantics, transitions, linked A/V, nesting, titles/subtitles, keyframe interpolation, retime/optical-flow, compound/multicam, realtime composited playback, interchange and full undo/persistence equivalence. |
| ☐ Fusion | Page button with no node compositor | Actual Fusion tool registry, every node/parameter/modifier/expression, 2D/3D processing, particles, masks/tracking, GPU/caching and reference-frame comparisons. |
| ☐ Color | `set_clip_properties`: exposure/contrast/saturation/gamma; FFmpeg export filters | Native grading/node graph, primaries/secondaries, masks/qualifiers/tracking, scopes, noise reduction, ACES/HDR, LUT math, high-bit-depth/color management and measured reference output. |
| ☐ Fairlight | Per-clip `volume`; renderer stereo resampling/mix/limiter | Sample-accurate DSP/routing, tracks/buses, automation, plugins, loudness, compensation/monitoring, ADR, spatial/immersive outputs and waveform/sample comparisons. |
| ☐ Deliver | `render`, `submit_render`, `get_render_job`, `list_render_jobs`; MP4 H.264/AAC, MOV ProRes/PCM, WAV PCM paths | Full codec/container/preset/export matrix, reference image/audio/metadata, individual/combined clip modes, render range/handles, cancellation/recovery, persistent queue and interchange validation. |

Shared obligations also remain open: Resolve project/database compatibility, complete UI/keyboard/accessibility fidelity, cloud/collaboration/conflict behavior, AI model/output equivalence, hardware capture/output/control panels, GPU/performance/stability, and complete MCP access to the final implemented feature set. See [FIDELITY.md](FIDELITY.md) for the full acceptance discipline and [feature-inventory.json](feature-inventory.json) for installed API anchors.

The original retime setup and its evidence limits are recorded in [RETIME-REFERENCE.md](RETIME-REFERENCE.md). The independent retime/subtitle pipeline is verified separately in [retime-subtitle-verification.json](retime-subtitle-verification.json). Neither establishes complete original-reference equivalence.

## Native exported-media comparison update

See `NATIVE-MEDIA-COMPARISON.md` and `native-media-comparison.json`: ten actual original exports and independent MCP reconstructions now have matching frame counts and estimated source identities under matched640x360 export geometry. Pixel and retimed-audio differences remain measured; default mono-channel gain handling was corrected from the comparison. None of the page-level obligations above are closed. GT Studio naming is verified in `branding-verification.json`; latest full test suite is74passed.
