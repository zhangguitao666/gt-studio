# Native Cross Dissolve reference measurements

The six actual Resolve renders establish bounded transition placement, output lengths and flat-color blending observations. Five rendered dissolves fit a midpoint-linear RGB weight hypothesis to within 0.006535 of normalized weight in this fixture. **These measurements do not establish a universal native curve or independent-editor parity.**

## Inputs and reproducibility

Run `.venv/bin/python scripts/analyze_native_transitions.py` from the project root. The script decodes every video frame through the bundled FFmpeg executable, crops the center 64×64 ROI at x=288/y=148, explicitly converts to RGB24, and computes the channel mean over all 4,096 pixels. The frame-number text in the top-left is outside this ROI. No scaling, temporal interpolation or transfer-function linearization is applied. The retained decoder hash, full command arguments, ROI RGB values and decoded ROI hashes make the chosen measurement pipeline explicit.

Artifact chain:

- [Native probe JSON](transition-runtime-v1.json), SHA-256 `bb2f7e8cb471719010606c96d06776735113caa2616fe42c67f418e3449708d8`.
- [Saved reference project snapshot](evidence/reference-transitions-v1.sqlite), SHA-256 `371dc0a30fb478581048e3def0cc0ed7587c8d839871c66283a3a3592299c7dc`.
- Each case in [transition-media-measurements.json](transition-media-measurements.json) retains the native BtLockableBlob primary key, blob/decompressed hashes, all duplicate JSON byte offsets/lengths/hashes, before/after getter structures, MOV hash and per-frame RGB means.
- Extracted marker names identify bytes co-occurring in a decoded blob. JSON timeline values select cases; this analysis does not infer a private wrapper association.

Both generated sources decode to 72 frames. Source identities:

| Source | SHA-256 | Measured center RGB |
| --- | --- | --- |
| red.mp4 | `5ca28f572aaebbe6e9675b026d8fe3131b7081ece1b31a7cb18337f6ed0011c2` | [252.0, 0.0, 0.0] |
| blue.mp4 | `005db69c13e1c3cb7e83f0dd92d632a84a35484e39bac7b7e8d23d3533a9e306` | [0.0, 0.0, 253.0] |

The source fixtures include top-left frame-number text and generated 440 Hz/880 Hz audio according to the probe setup. This report measures the video ROI only: it does not decode those frame labels or verify audio frequencies/crossfades.

## Actual output and getter observations

Input metadata inspection identifies each MOV as ProRes HQ, 640×360 at 24 fps with stereo 48 kHz PCM 24-bit audio; the retained FFmpeg metadata text also identifies the Resolve encoder. This establishes stream metadata, not audio signal equivalence.

All output frames below are relative to the native timeline origin reported as 86400. Window ends are exclusive. The normal source range requests were 12→60; both video clips reported duration 48 and a cut at relative frame 48. The no-handles source requests were 0→72, both durations 72, and the cut at frame 72. Source-end getter values are retained exactly; their complete boundary convention is not inferred from these examples.

| Case | AddTransition returned item | Decoded frames | Getter transition window | Mixed-color frames measured | Max weight residual |
| --- | --- | ---: | --- | --- | ---: |
| center11 | True | 96 | [42, 53) | 42–52 | 0.005866 |
| center12 | True | 96 | [42, 54) | 42–53 | 0.006535 |
| left12 | True | 96 | [36, 48) | 36–47 | 0.006535 |
| nohandles | False | 144 | None | None (hard cut) | N/A |
| right12 | True | 96 | [48, 60) | 48–59 | 0.006535 |
| startcenter12 | True | 96 | [42, 54) | 42–53 | 0.006535 |

Every decoded output length matches its captured native timeline finish minus origin. The five successful transition cases each retain 96 total frames; the no-handles case retains 144. In the no-handles fixture, AddTransition returned no item, native transition metrics reported missing, and decoded video changes directly from pure red through frame 71 to pure blue from frame 72, with no mixed-color ROI frames.

For these successful cases, alignment places the transition relative to the cut as follows: left starts at cut−duration; right starts at cut; center starts at cut−ceil(duration/2). The odd 11-frame centered case starts at 42 and ends at 53 around cut 48. Adding the centered transition at the second clip start produces the same measured window and all-frame ROI sequence as adding it at the first clip end. This is a bounded observed relationship, not a claim about all transition categories or odd durations.

## Blend hypothesis and residuals

The tested hypothesis is `w_blue = (frame − transition_start + 0.5) / transition_duration`. For each native MOV, red/blue endpoint RGB vectors are measured from the first/last 12 frames; blue weight is estimated by projecting each measured RGB vector onto the line between those endpoints. This model is evaluated only over the reported transition window.

All four 12-frame cases have identical measured transition ROI sequences; their maximum absolute weight residual is 0.006535, RMS 0.003923, and maximum channel residual is 3.792 on the 8-bit scale. The 11-frame case has maximum weight residual 0.005866, RMS 0.003908, and maximum channel residual 3.5. Outside each getter window the ROI matches the pure endpoints in this decode pipeline. Spatial channel spans are zero throughout the selected ROI, confirming the samples avoid the frame-number overlay.

The nonzero residuals are retained rather than presented as exact equality. Codec quantization, YUV↔RGB conversion, range/matrix choices and native color processing are not separated by this small fixture. Red/blue inputs and one ProRes output configuration cannot identify a general RGB/light-space transfer function, interpolation curve or alpha/HDR behavior.

## Preservation and remaining questions

All six cases have byte-equivalent canonical before/after getter structures for the first and second video clips, including recorded source bounds, starts, durations and exposed properties. The transition is an additional timeline item in the five successful cases. This supports the narrow statement that those two video-clip readbacks stayed unchanged; it does not show the whole project was unchanged.

The source files, native MOVs, probe JSON and snapshot hashes were checked unchanged during this offline analysis. That is not a source-file comparison across the earlier native rendering session, for which no uncaptured pre-render hash is invented.

Open obligations include source-handle sample identity and frame-number decoding, audio transition behavior, insufficient-handle edge cases beyond this one fixture, linked/multitrack interactions, retimed sources, fades/other transitions, non-flat images, alpha, color-management/HDR and performance. Independent output comparison is a separate task. No full Resolve feature parity is claimed.

## Native deletion lifecycle: separate video/audio behavior

The subsequently captured [deletion probe JSON](transition-deletion-runtime.json) and [saved deletion snapshot](evidence/reference-transition-deletion.sqlite) add three getter-based lifecycle observations. The script includes their original cases and record anchors/hashes under `native_deletion_lifecycle` in the measurements JSON. These are structural readbacks, not rendered deletion-output comparisons.

Deletion snapshot SHA-256: `9347f3cd7d89311f0cb08790ad5f1fa8a36538a464be365e9bf060cd0134efde`. Extracted JSON SHA-256: `78b1df82fdc12e44acba6627e809c65b5bc12586c0e14d75259d138fbb6fcf80`. All three cases returned `delete_return=true` and completed the probe. Relative starts below subtract the earliest recorded pre-deletion video start (86400).

| Operation | Video items after deletion | Audio items after deletion |
| --- | --- | --- |
| Delete only the transition, no ripple | Red 48 frames at 0; blue 48 frames at 48 | Red 48 at 0; blue 48 at 48, unchanged |
| Delete first video clip, no ripple | Transition and red video removed; blue 48 frames remains at 48 | **Both** red 48 at 0 and blue 48 at 48 remain unchanged |
| Ripple-delete first video clip | Red video and transition removed; blue 48 frames moves to 0 | Red audio removed; blue 48 frames moves to 0 |

These results distinguish native video-item deletion from linked/ripple A/V behavior. Cascading removal of an attached transition when deleting its video reference is only one bounded requirement. The independent editor currently embeds source audio with a video clip; that representation cannot reproduce the normal native video-only deletion shown here without separately selectable audio items and the corresponding linkage/ripple semantics. Complete linked A/V behavior remains open. Do not describe transition cascade as full lifecycle or Resolve editing parity.

## Upstream ripple and independent acceptance

The separate saved upstream-ripple snapshot has SHA-256 `802ae07a1729d65f20c9d4fa0100d12baa93c7a14f5820cb0ccbfb6ad733e925`; extracted getter records are retained in `transition-upstream-runtime.json`. Deleting the first 48-frame video item moves both surviving endpoints and their transition window from [90,102) to [42,54), with cut 96→48. The native-linked audio scope is distinct from the independent editor's current same-track contract.

`test_native_upstream_ripple_moves_surviving_transition_window` compares the captured native item locations, checks decoded moving blend frames and undo/redo. `reference-transition-comparison.json` records six independent stdio MCP replays and rendered outputs: window placement, acceptance/rejection and frame counts pass; retained RGB samples differ. The actual desktop MCP acceptance advertises 39 tools and observes playback advancement and pause. These bounded checks do not close general transition, linked audio, pixel or full application parity.

Independent audio implementation update: explicit `detach_audio` now supplies separately selectable audio items and disables embedded audio on the original video clip. `detached-audio-verification.json` compares the two non-ripple deletion readbacks successfully after explicit separation and checks independent PCM preservation. The earlier embedded-default and linked/ripple gaps remain; this does not claim native default import or linked-edit parity.

Linked ripple update: explicit same-timeline clip groups now reproduce all three captured native deletion item readbacks, including ripple_true, through actual stdio MCP. The updated verifier writes linked-audio-verification.json and a distinct linked-audio-acceptance workspace, preserving the earlier two-case report and artifacts. The ripple case decodes48 blue video frames; independent WAV PCM equals the retained blue interval from the pre-deletion render. Native rendered audio is not compared. Full default linking and other linked editing semantics remain open.
