# Resolve reconstruction: fidelity evidence and open requirements

The requested end state is an independent project named **GT Studio**, with all functionality identical to the installed DaVinci Resolve, operable through MCP. **That end state is not established.** A scripting bridge into the installed application, an API-shaped facade, visual shell, or successful sample export cannot demonstrate complete independent functional parity.

Current implementation update: constant retime/reverse/freeze and Unicode SRT subtitle editing/burn-in now have executable independent implementations and output tests. See `retime-subtitle-verification.json` and `DEVELOPMENT_LOG.md`. The first native two-clip probe failed its precondition. Subsequent controlled two-clip probes now have saved before/after readbacks in `retime-runtime-v2.json` and `freeze-all-runtime-v3.json`; their bounded timing comparisons are tracked in `RETIME-COMPARISON.md`. Decoded image/audio and general behavioral equivalence remain unverified. These additions do not close the Edit, Fairlight or subtitle-system parity requirements below.

This report records installed declaration evidence and defines the remaining proof obligations. It deliberately makes no completion claim about core/UI/service work being developed separately.

## Evidence boundary

The reproducible manifest [feature-inventory.json](feature-inventory.json) inventories the complete AST of the installed [DaVinciResolveScript.pyi](/Library/Application%20Support/Blackmagic%20Design/DaVinci%20Resolve/Developer/Scripting/DaVinciResolveScript.pyi). It records absolute source paths, SHA-256 identities, class and member source line spans, parameter/return declarations, constant/type fields, heuristic page assignments, and package directory inventory. It copies declarations only, with no proprietary method implementations or full documentation prose.

Run `python3 scripts/inventory_resolve_api.py` from the project root to regenerate. The script accepts `--scripting-root`, `--app`, and `--output` for an explicitly selected installation. Source paths and hashes bind the manifest to inspected bytes; updates to the application require a fresh inventory and parity review.

| Measure | Observed count |
| --- | ---: |
| All declared classes | 67 |
| API object classes | 16 |
| TypedDict schema classes | 51 |
| Declared object methods / unique qualified names | 416 / 416 |
| Module functions | 1 (`scriptapp`) |
| Module aliases or assignments | 43 |
| Declared class fields and constants | 774 |
| Methods runtime-verified by the AST inventory script | 0 |

| API object | Methods | Stub starting line |
| --- | ---: | ---: |
| Resolve | 46 | 1320 |
| ProjectManager | 27 | 1695 |
| Project | 60 | 1779 |
| MediaPool | 28 | 1962 |
| MediaPoolItem | 44 | 2049 |
| Timeline | 64 | 2184 |
| TimelineItem | 93 | 2379 |
| ColorGroup | 5 | 2661 |
| Folder | 13 | 2679 |
| Gallery | 8 | 2721 |
| GalleryStill | 0 | 2748 |
| GalleryStillAlbum | 6 | 2751 |
| Graph | 11 | 2772 |
| MediaStorage | 11 | 2809 |
| Fusion | 0 | 2845 |
| FusionComp | 0 | 2846 |

Fusion and FusionComp are empty declarations in this stub. Zero methods here means missing declaration coverage, not a featureless compositor. GalleryStill is similarly opaque here.

The installed `Resolve.OpenPage` declaration at lines 1577–1579 lists **eight page tokens**, including `photo`, in addition to `media`, `cut`, `edit`, `fusion`, `color`, `fairlight`, and `deliver`. `GetCurrentPage` at line 1580 repeats the set. The AST inventory does not verify runtime behavior. Later native observations confirm all eight page controls; selecting Photo still showed Cut-style content, so complete Photo workflow and edition behavior remain unverified. The conventional seven-page grouping must therefore remain open to this installed extension.

The manifest groups methods for navigation using class/name heuristics. Groups overlap: Media 96, Cut 185, Edit 185, Fusion 17, Color 45, Fairlight 29, Deliver 42, Shared 84. These are **organizational counts**, not exact page availability counts or feature coverage percentages. Every declared method remains individually addressable in `classes[].methods[]` with its source anchor.

## Installed documentation findings

The local scripting README is dated 31 August 2026; its prerequisites at line 28 require a running, loaded application and suitable scripting configuration. Its configuration section starts at line 38. This does not establish the current preference value or successful external access.

The changelog is dated 1 September 2026. Its 21.1 section begins at line 8 and lists API changes such as multicam, audio rendering, transitions, clone operations, DCTL, settings/keyboard presets, and native audio properties. This dates the installed documentation. Separate subsequent Lua Console observations report runtime version `21.1.1.10`; they establish only the exact observed invocations, not full runtime coverage.

The README Studio/AI section at line 416 explicitly distinguishes declarations from availability: edition, hardware requirements, and downloaded Extras can affect call success. AI methods must be tested on the actual installed edition and models. The deprecated API section at line 447 and unsupported section at line 615 also prevent assuming every historic calling convention remains valid. This manifest captures the current stub declarations, not deprecated prose signatures.

## Subsequent runtime observations

[Runtime observations](runtime-observations.json) record a dedicated reference project and a native Lua Console probe reporting 52 successful `pcall` invocations, runtime version `21.1.1.10`, product `DaVinci Resolve`, `IsStudio=false`, current page `deliver`, project settings with 158 entries, 22 render-format entries and 7 audio-format entries. This is CUA-transcribed Console evidence, separate from canonical REA Evidence. Repeated format-specific codec calls mean 52 invocations are not a verified count of unique methods. A successful `pcall` may return nil; the current timeline query did so. Encoding, complete API semantics and parity are not established by these reads.

The AST inventory's zero runtime-verified count describes what that static script verifies, not a claim that no runtime calls have subsequently occurred. The original 34,333-byte Console payload was subsequently archived from its retained global into a dedicated reference timeline marker, then recovered from an offline SQLite backup. `research/evidence/resolve-runtime-api-payload.json` preserves its exact bytes (SHA-256 `c5084086e21a56e69a05f188f7bc0258cf8261821f733e1914e632b2180bfe9d`); `runtime-api-archive.json` retains the derivation. It remains a native probe payload, not canonical REA runtime Evidence. The older requested `resolve-runtime-api.json` path remains absent; its recorded io-related persistence status is historical and its cause was not independently established. The external bridge's earlier `BRIDGE_UNAVAILABLE` status is a separate access path from the later successful internal Console invocations.

The independent application's native preview was observed showing a moving test pattern with the playhead advancing from `00:00:00:00` to `00:00:00:08`. Source inspection now also shows transforms/opacity, fades, stills, ripple deletion, MP4/ProRes MOV/WAV rendering and requested/desktop-observed transport controls. These are bounded implementation/observation facts and do not close page-level parity requirements. See [REA-FINDINGS.md](REA-FINDINGS.md) for current implementation mappings and the eight-page checklist.

## Package observations

The manifest inventories the selected app's `Contents` directories. Observed names include `MacOS`, `Frameworks`, `Libraries`, `PlugIns`, `Resources`, and `XPCServices`. Library entries include `libFusionPage.dylib`, `libFairlightPage.dylib`, `libOpenColorIO.2.5.dylib`, `libavcodec.60.dylib`, `libavformat.60.dylib`, camera/RAW SDK-named libraries, voice-isolation and ML-named libraries. Resources include a local PDF manual, Fusion resources, UI resources, QML, and a bundled Python directory.

These observations establish packaged file presence only. They do not establish active loading, exact algorithms, an exhaustive plugin/codec inventory, performance, entitlement, or functional equivalence. Separate REA evidence files (`evidence/resolve-plist.json`, `resolve-macho.json`, `resolve-artifact.json`) are maintained by the main investigation and must be interpreted with their own recorded limitations.

## Requirements that still need proof

All rows below are **open parity requirements**. Their scripting anchors are investigation entry points, not implementation specifications. The machine-readable manifest includes corresponding `feature_requirements` with source references and required evidence.

| Area | Investigation evidence | Required independent-project proof |
| --- | --- | --- |
| Media | MediaStorage at stub 2809; MediaPool 1962; MediaPoolItem 2049 | Decode real codec/RAW corpus; preserve frames, audio layouts, metadata, timecode, media interpretation, proxy generation, relink, bins, cloning/checksums, and cache behavior. |
| Cut | Multicam API, synchronization, timeline methods | Source tape and Cut-specific UI/gestures, sync bins, source/record behavior, fast review and smart-switch results need source observations and reproducible comparison. |
| Edit | Timeline 2184; TimelineItem 2379 | Frame-accurate trim/ripple/roll/slip/slide, linked A/V, overwrite/insert, gaps, nested/compound/multicam, transitions, subtitle/title layout, keyframes, retiming, optical flow, undo/redo, interchange and project persistence. |
| Fusion | Resolve.Fusion at 1562; empty Fusion/FusionComp stubs at 2845 | Actual node registry and every parameter/modifier/expression, 2D/3D evaluation, particles, tracking, GPU processing, fonts/media, caching and rendering. Separate Fusion SDK/runtime evidence is needed. |
| Color | Graph 2772; ColorGroup 2661; Gallery 2721; Dolby analysis method 2351 | Node evaluation/order, primaries/secondaries, masks, qualifiers, tracking, noise reduction, scopes, LUT interpolation, color-space transforms, ACES/HDR/output metadata and consistent high-precision frames. |
| Fairlight | Audio mappings 2153/2156; Fairlight preset 1937; voice isolation 2366/2369 | Sample-accurate DSP, track/bus routing, mixers, gain/pan, native and third-party plugins, automation, loudness, latency compensation, monitoring, ADR and multichannel/immersive output. |
| Deliver | Project render format/codecs 1889–1898; render jobs and Timeline.Export | Runtime codec/container matrix, frame/audio correctness, metadata/timecode, subtitle handling, job persistence/cancellation/errors, individual/combined clips, presets and interchange. |
| Photo | OpenPage declaration 1577 | Observe actual installed workflows; enumerate and verify them before claiming scope coverage. |
| AI | Transcription, captions, speech, reframe, slate/intellisearch and smart-switch declarations | Model availability, supported languages, inference output, timing, quality, nondeterminism and edition/hardware constraints across representative datasets. |
| Projects and collaboration | ProjectManager 1695; database 1757; cloud 1766 | Schema/format roundtrip, project libraries, backup/restore, migrations, concurrent edits, locking/conflicts, cloud synchronization and recovery. |
| Hardware and runtime | Packaged backend/control-surface libraries are leads only | GPU parity, realtime scheduling, memory/cache pressure, external capture/output, control panels and audio devices, platform capability differences, stability and performance. |
| UI and interaction | Layout and keyboard preset declarations | Complete workflow capture, screenshots, menu/dialog discovery, shortcuts, focus, accessibility, interaction timings, color-managed display and undo history. |
| MCP | The independent project's own MCP server and execution engine | Discoverable schemas/resources, stable object identities, actual state mutations and media effects, error semantics, cancellations, concurrency and stdio lifecycle. Forwarding a request to Resolve proves only integration with Resolve. |

## Acceptance and evidence discipline

1. Preserve the user's complete functional scope. Build a workflow/feature ledger from source UI, manual, API, package and runtime evidence; retain unknowns rather than inferring completeness from 416 method declarations.
2. For each operation, record source version/edition, prerequisites, input fixtures, actions, expected observable outputs, and reference artifacts. Compare state, decoded frames/audio, metadata, errors, timing constraints, undo and persistence.
3. Label findings as installed declarations, observed runtime behavior, inference, implementation, or verified parity. Add a runtime evidence record only after executing and inspecting that exact behavior.
4. Independently exercise the replacement through its UI and MCP, using the same fixtures. A process startup, schema response, method-name match, or mocked test does not prove feature parity.
5. Audit every required subsystem and workflow before declaring completion. Native algorithms, unenumerated nodes/plugins, hardware, AI and collaboration remain explicit obligations. No current evidence supports an assertion that all Resolve functionality has been reproduced.

## Native media export comparison

Ten original reference timelines were exported as640x360 ProResHQ/PCM24 MOV. `native-render-status.json` records all ten jobs Complete and rendering=false. `native-media-comparison.json` measures them against independent MCP reconstructions. Frame counts and estimated source identities match within these cases, but RGB bytes and time-stretched audio still differ; no pixel/audio parity requirement is closed. The first attempted320x180 native output was silently clamped to320x256, so the valid comparison uses the subsequent16:9 exports. See RETIME-COMPARISON.md for evidence and limits.

## Bounded Cross Dissolve implementation

Six saved native cases and original renders now support the structural comparisons in `reference-transition-comparison.json` and measurements in `TRANSITION-REFERENCE.md`. Independent source-handle compositing, opacity/multitrack behavior and upstream same-track ripple are exercised by tests; native pixels retain residuals. The real native GT Studio window is reachable through 39 public MCP tools. Full linked video/audio deletion, all transitions, general color/retime interactions and complete Edit parity remain open. Latest saved JUnit: 97 passed, no failures or skips.

## Independent audio item progress

Explicit detach_audio now separates video audio into an independently editable timeline audio item, without doubling the render mix. Two non-ripple native deletion getter cases match after explicit separation; actual independent PCM is byte-identical before/after detachment and video deletion at tested speeds. See detached-audio-verification.json and verify_detached_audio.py. This changes the previous representation limitation, but default append still embeds audio and complete native linkage, cross-track ripple and linked edit behavior remain open. Latest full suite:103 passed;40 public MCP tools.

## Explicit linked ripple deletion

Persistent link_clips/unlink_clips groups and detach_audio(linked=true) are implemented. Ripple deletion removes every member, closes the removed intervals on member tracks and shifts surviving transition windows when both endpoints shift equally; ordinary deletion stays item-only and removes orphan group metadata. Undo/redo and persistence are tested. verify_detached_audio.py now replays all three saved native deletion cases via actual MCP; linked-audio-verification.json retains native normalized item readbacks, 96/48/96 decoded frames and independent PCM interval comparisons.

This closes the earlier bounded ripple_true example after explicit grouping. It does not establish default native append/link behavior, native linked selection/move/split/trim/speed semantics, track sync-lock behavior, arbitrary offset/mixed-length grouping, or all-track ripple rules. Latest full suite:106 passed;42 public MCP tools. Complete Resolve parity remains unachieved.

## Linked blade partitioning

Native reference menu execution and saved GetLinkedItems readbacks confirm independent prefix/tail A/V link groups for one aligned48-frame pair split at24. split_clip now performs linked splits and repartitions groups; verified through real MCP, decoded independent RGB/PCM preservation, tail-only ripple delete and undo. See LINKED-SPLIT-REFERENCE.md and linked-split-verification.json. Generic offset/selection/lock behavior remains unverified; native linked move/trim/speed and full Edit requirements remain open.111tests pass.

## Linked clip movement

A new native nudge reference confirms an explicitly linked normal-speed A/V pair moves together48→49 with durations48 and reciprocal peers unchanged. move_clip now moves group members by the same delta, preserving relative offsets and source timing; peer collisions or negative positions roll back atomically. Surviving transitions follow if both endpoints move together. See LINKED-MOVE-REFERENCE.md and linked-move-verification.json for source-bound REA evidence, actual MCP readback and decoded independent payload comparisons.116tests pass;42publicMCPtools. Native vertical mapping, overwrite rules, locked tracks, disabled linked selection and general linked edit parity remain unproven; trim/speed linkage remains open.

## Non-ripple linked timeline edge trimming

Two new normal-speed native menu cases establish aligned A/V start/end inward trim readbacks, preserving links. trim_clip_edge and separate desktop controls now implement timeline-boundary linked trims; see LINKED-TRIM-REFERENCE.md. Actual MCP/readback and independent retained media checks pass;128tests pass. The configured launcher exposes43tools and mutates the shared demo correctly. New actual-window controls/playback remain pending because CUA reported Mac locked; no replacement success claim is made. Direct source-field inspector editing remains item-only. General outward/retimed/offset/lock/ripple/roll/slip/slide/selection behavior remains open.

## Atomic inspector timing update

Direct source/start edits now propagate through explicit peers and commit as a single validated transaction. Unspecified rational source endpoints survive unchanged. Two existing native trim cases match using this API, and independent output retention and configured MCP tests pass;136tests total,43publictools. See ATOMIC-TIMING.md. General native mixed-speed/freeze/offset/source-field inspector rules remain unverified, and the actual updated running-window check is pending after the earlier lock condition. Linked speed/selection and full application fidelity remain open.

## Explicit linked retime representation

Speed/reverse/pitch/freeze now propagates through explicit groups, and interior freezes partition prefix/tail groups. Ten retained native video timing cases replay correctly; new linked RGB/PCM exactly matches verified prior embedded independent outputs. Prior native residual metrics remain nonzero and native audio getter structures remain uncaptured.150tests pass;43configuredMCPtools. See LINKED-RETIME-REFERENCE.md. General native synchronization,selection,locks,keyframes,retime curves,algorithms and actual current-window verification remain open.

## Track masks and lock state

Persistent enabled/locked flags,stream-specific output masks and transactional clip/transition lock enforcement now have executed independent implementations. Installed native declarations are source-bound in track-state-api-evidence.json, but original runtime policy remains unverified. Fifteen engine tests,Qt→HTTP controls and mouse-event checks,actualMCP decoded exports and ten retained retime regressions pass;166tests total,44configuredMCPtools. See TRACK-STATE-REFERENCE.md. Native lock/API exceptions,sync locks and real-window controls remain pending,along with complete application parity.

## Measured image precision update

RGBA16 clip intermediates and10-bit YUV422 main compositing reduce MSE30.25%–32.00% across ten retained native fixtures under the existing normalization. RGB/PCM and source-identity limitations remain explicit in COLOR-PRECISION.md. Transparent canvases use planar16-bit RGB after fixing an observed alpha-negotiation failure. Five new media tests plus preview-session invalidation bring the full suite to172passed;44configuredMCPtools. Active-filter/alpha precision,full color management,HDR/ACES,tags and actual-window parity remain open.


## Fusion 五节点执行阶段

已加入可持久化、可经MCP和Qt画布编辑的MediaIn/MediaOut/Background/Transform/Merge子集，并导出验证48帧、共享节点分支和音频路径不变。Transform/Merge经过8位RGB合成边界，原版节点绑定、采样与所有算法尚未运行对照，不属于已证明原版等效的功能。原版设置文件仍仅只读检查，不自动执行。212项回归及真实窗口参数回显/写回、第0帧暂停预览证据仅覆盖FUSION-NODES.md所列范围，完整目标仍未达到。


## 首轮原版 Fusion 运行对照

24个选定原版导出任务实际完成，六个同尺寸案例经GT Studio MCP重建并比较全部48帧。几何位置基本对应；半透明背景RGB MAE42.666667、半混合6.317713，仍有实质差距。独立RGBA检查点及透明下层对照是下一步，尚不具备直接替换Alpha约定或声称节点等效的证据。ProRes4444两个AlphaMode在本批导出的包/解码帧相同，其余格式语义未知。见FUSION-REFERENCE.md及对应运行/媒体收据。

## 独立节点 RGBA 检查点

已实现render_fusion_frame与Fusion页节点PNG保存入口，52个公开MCP工具，完整224项独立回归通过。六案例首帧RGBA16检查点显示背景/变换/共享分支内部接近原版带Alpha导出，但主时间线半透明输出仍显著变暗；Merge本身已经存在明显色差。原版参照仍是编码导出而非内部缓冲，Transform/Merge仍有8位处理边界，未据此更改Alpha算法。真实窗口与MCP保存同一节点/帧的PNG逐字节相同，工程未变。见FUSION-CHECKPOINTS.md。后续仍需透明/不透明下层和参数梯度对照、算法校准及其余完整功能。

## 关联Alpha原版校准

13组原版Alpha/Blend/下层实验、26个精确任务句柄均完成。由观察推断并实现16位整数关联over，保留Alpha=0的非零RGB，修正重复乘Alpha；移除Transform/Merge的8位RGB边界，主时间线、透明度/淡化及混合普通媒体的叠化使用相应关联路径。13组中9组全RGB序列相同，其余生成器MAE最高1.333333；媒体输入Merge仍为10.333333。旧六组48帧中的背景/分支完全相同，变换MAE从10.623762降至0.085567，Merge MSE从232.773485降至44.760979。241项独立测试通过。浮点HDR、源色彩解释、几何边缘及完整功能仍未等效，见FUSION-ASSOCIATED-ALPHA.md。
