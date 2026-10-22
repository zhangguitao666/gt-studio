# Color precision: measured native-error reduction

The previous pipeline forced RGBA8 clip intermediates and default YUV4208 overlay before ProRes10 output. Current FFmpeg filter-help confirms overlay defaults to yuv420. Isolated experiments against the retained94-frame normal-speed native export compare unchanged baseline,identity-filter bypass,RGBA16 plus YUV42210/YUV44410 overlay,and RGBA8 plus YUV44410. Commands,source snapshots and unthresholded measurements are retained in color-precision-diagnostic.json. The pre-change independent package is archived under workspace/color-precision-diagnostic/source-before; the diagnostic imports that archive so future production changes do not silently replace the baseline.

Identity EQ/LUT removal alone did not improve the measured0.869373 MAE. RGBA16 plus YUV42210 reduced it to0.701864,while RGBA8/YUV44410 worsened it to0.928341. The selected production path therefore uses16-bit RGBA clip intermediates and explicit10-bit YUV422 main overlays,skipping default EQ/exposure filters. This is an evidence-based precision change,not a fitted per-color correction or a universal managed-color algorithm.

## Full retained native corpus

native-media-comparison-precision.json recreates and renders all ten original retime/freeze cases through actual stdio MCP at640×360,then compares complete sequences under the existing320×180RGB24/24fps normalization. Native files,source,decoder and prior measurements are preserved. New RGB MAE ranges0.623587–0.704949 versus previous0.771428–0.869554. Every case improves; MSE falls30.2509%–32.0022%. All frame counts and heuristic nearest-source-frame sequences still match. New independent PCM is byte-identical to the prior independent PCM; original audio differences remain.

precision-improvement-verification.json binds before/after reports and records every case. Nonzero pixel residuals remain. This corpus uses one generated8-bit color/motion source and does not establish all resolutions,codecs,color spaces or HDR behavior. Native output includes color metadata absent from current independent exports; no unsupported global tag correction was applied.

## Alpha and ten-bit checks

The first transparency regression failed: current FFmpeg's transparent color source negotiated directly into packed rgba64le produced opaque alpha65535. A planar gbrap16le canvas preserves alpha0. The exact pixel probes,decoder identity and overlay help are retained in color-precision-alpha-diagnostic.json. The fix passes existing layered .5-opacity dissolve checks and new .25/.75-opacity cases. Auto-overlay alpha negotiation can still quantize alpha; this is not an all-16-bit alpha or linear-light compositing claim.

A synthetic FFV1 ten-bit near-black ramp decodes128 source luma levels. The archived old pipeline retained48levels with1.375 luma MSE; the upgraded path retained128levels with zero measured luma error in that fixture. Diagnostic source/export hashes and rows are retained. Tests additionally check three legal-range ramp regions,decoded ProRes luma error<=1 and at least120 distinct levels. Active EQ filters can still negotiate lower precision; full high-bit-depth grading,HDR,ACES,transfer functions and color-management remain open.

## Integrated results

Six original dissolve cases were replayed into separate precision artifacts. Ten explicit linked-retime cases also exactly match the new independently measured embedded representation; the linked verifier now defaults to native-media-comparison-precision.json and accepts --baseline-report for historical comparisons. Earlier media/reports are preserved.

Full suite172passed. The configured Codex MCP launcher exposes44tools and exports94frames with RGB/PCM identical to the measured new reference. A new Qt→HTTP regression rebuilds a completed preview after the renderer session changes,even with an unchanged project signature; old rendered pixels cannot be silently reused after an engine update.

Actual running-window validation remains pending after the earlier lock condition. It is not replaced by offscreen tests. Full Resolve functional/visual parity remains unachieved.
