# Atomic linked source-range and position editing

The inspector previously sent trim_clip and move_clip as separate asynchronous edits. If the final move failed, the first trim could remain. It also always resubmitted rounded integer in/out metadata, potentially replacing exact fractional source positions even when the user did not change those fields.

## Implemented contract

trim_clip now accepts optional in_frame,out_frame,start_frame and requires only clip_id. It constructs the complete selected/linked-peer arrangement before validation and commits it as one undo transaction. Source in/out remain project-frame coordinates; timeline start is an absolute frame. Omitted source endpoints preserve the existing rational boundary. The inspector submits only source values changed from its displayed metadata and includes the requested start in the same request.

For moving clips, source leading/trailing changes are divided by the selected signed speed and applied through each peer's signed speed, retaining each peer's source base, direction and relative timeline offset. Frozen peers retain their sampled range and adjust duration when a moving selected clip's span changes. A frozen selected source edit cannot map a moving peer and currently rejects atomically; unlinking remains necessary for that case. Native behavior of this mixed case is unverified.

All final tracks validate together, so a source expansion that collides at the old position may succeed at a free final position. Any peer source exhaustion, negative range, collision or invalid surviving transition rolls back the whole project and undo/redo history. Following clips do not ripple. Moving both transition endpoints shifts its window as before.

## Evidence and validation

`verify_linked_trim.py --source-fields` replays the two saved aligned normal-speed native inward-trim readbacks using the source/start inspector API. Exact normalized starts,durations,source bounds and peer relationships match. Independent retained RGB/PCM, save and single undo/redo checks pass. A distinct atomic-timing-acceptance workspace and atomic-timing-verification.json preserve the earlier edge-API artifacts.

Five new engine tests cover final-position validation,peer conflict rollback,signed-speed/offset source mapping,rational split phase preservation,omitted endpoints,media exhaustion and the frozen/moving rejection. Three real Qt→HTTP inspector tests cover one-step success,one-step failure without partial source mutation,and unchanged fractional source fields. Full suite136passed. Native comparisons cover the existing two aligned normal-speed fixtures, not universal inspector/retime/selection behavior.

The configured Codex MCP launcher exposes43tools and accepts the extended trim_clip schema. It updated both shared demo items to start60,duration12,source18→30 in one request; one undo restored the complete pair and redo restored the edit. See configured-mcp-atomic-timing-verification.json and atomic-timing-integration-verification.json.

Actual running-window verification remains pending after the prior CUA Mac-lock failure. Qt/HTTP tests are not represented as that missing native-window check. The updated inspector source will load when the app is next relaunched. Full Resolve parity remains open, including default A/V import,linked selection/speed,general editing and the larger Fusion/Color/Fairlight/codec/hardware systems.
