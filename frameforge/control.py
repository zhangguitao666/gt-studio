"""Shared editor control contract used by the native UI, HTTP and MCP."""

def object_schema(properties=None, required=()):
    return {"type": "object", "properties": properties or {},
            "required": list(required), "additionalProperties": False}

STRING = {"type": "string", "minLength": 1}
FRAME = {"type": "integer", "minimum": 0}
NUMBER = {"type": "number"}
BOOLEAN = {"type": "boolean"}
FUSION_PARAMETERS = object_schema({key: NUMBER for key in ('Red', 'Green', 'Blue', 'Alpha', 'CenterX', 'CenterY', 'Size', 'Angle', 'Blend')})
FUSION_PARAMETERS['properties']['Depth'] = {'type':'number', 'enum':[0,1,2,3,4]}
NODE_POSITION = object_schema({'x': NUMBER, 'y': NUMBER}, ['x', 'y'])

SCHEMAS = {
    "list_actions": object_schema(),
    "get_state": object_schema(),
    "create_project": object_schema({"name": STRING, "path": STRING, "fps": {"oneOf": [NUMBER, object_schema({"num": {"type": "integer", "minimum": 1}, "den": {"type": "integer", "minimum": 1}}, ["num", "den"])]}, "width": {"type": "integer", "minimum": 2}, "height": {"type": "integer", "minimum": 2}, "sample_rate": {"type": "integer", "minimum": 1}}, ["name"]),
    "set_project_settings": object_schema({"name": STRING, "fps": object_schema({"num": {"type": "integer", "minimum": 1}, "den": {"type": "integer", "minimum": 1}}, ["num", "den"]), "width": {"type": "integer", "minimum": 2}, "height": {"type": "integer", "minimum": 2}, "sample_rate": {"type": "integer", "minimum": 1}}),
    "open_project": object_schema({"path": STRING}, ["path"]),
    "save_project": object_schema({"path": STRING}),
    "import_media": object_schema({"path": STRING}, ["path"]),
    "set_media_data_level": object_schema({"media_id": STRING, "mode": {"type":"string", "enum":["Auto","Full","Video"]}}, ["media_id", "mode"]),
    "probe_media": object_schema({"path": STRING}, ["path"]),
    "inspect_fusion_settings": object_schema({"path": STRING, "detail": {"type": "string", "enum": ["summary", "nodes"]}, "offset": FRAME, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, ["path"]),
    "get_fusion_graph": object_schema({"clip_id": STRING}, ['clip_id']),
    "render_fusion_frame": object_schema({"clip_id": STRING, "output": STRING, "node_id": STRING, "frame": FRAME}, ['clip_id', 'output']),
    "add_fusion_node": object_schema({"clip_id": STRING, "type": {"type": "string", "enum": ['MediaIn', 'Background', 'Transform', 'Merge']}, "name": STRING, "parameters": FUSION_PARAMETERS, "position": NODE_POSITION}, ['clip_id', 'type']),
    "update_fusion_node": object_schema({"clip_id": STRING, "node_id": STRING, "name": STRING, "parameters": FUSION_PARAMETERS, "position": NODE_POSITION}, ['clip_id', 'node_id']),
    "connect_fusion_nodes": object_schema({"clip_id": STRING, "target_node_id": STRING, "input": {"type": "string", "enum": ['Input', 'Background', 'Foreground']}, "source_node_id": STRING}, ['clip_id', 'target_node_id', 'input']),
    "delete_fusion_node": object_schema({"clip_id": STRING, "node_id": STRING}, ['clip_id', 'node_id']),
    "clear_fusion_graph": object_schema({"clip_id": STRING}, ['clip_id']),
    "create_timeline": object_schema({"name": STRING}, ["name"]),
    "set_active_timeline": object_schema({"timeline_id": STRING}, ["timeline_id"]),
    "add_track": object_schema({"kind": {"type": "string", "enum": ["video", "audio"]}, "name": STRING}, ["kind"]),
    "set_track_state": object_schema({"track_id": STRING, "enabled": BOOLEAN, "locked": BOOLEAN}, ["track_id"]),
    "append_clip": object_schema({"media_id": STRING, "track_id": STRING, "in_frame": FRAME, "out_frame": FRAME, "start_frame": FRAME}, ["media_id"]),
    "detach_audio": object_schema({"clip_id": STRING, "track_id": STRING, "linked": BOOLEAN}, ["clip_id"]),
    "link_clips": object_schema({"clip_ids": {"type": "array", "items": STRING, "minItems": 2, "uniqueItems": True}}, ["clip_ids"]),
    "unlink_clips": object_schema({"clip_id": STRING}, ["clip_id"]),
    "split_clip": object_schema({"clip_id": STRING, "frame": FRAME}, ["clip_id", "frame"]),
    "trim_clip": object_schema({"clip_id": STRING, "in_frame": FRAME, "out_frame": FRAME, "start_frame": FRAME}, ["clip_id"]),
    "trim_clip_edge": object_schema({"clip_id": STRING, "edge": {"type": "string", "enum": ["start", "end"]}, "frame": FRAME}, ["clip_id", "edge", "frame"]),
    "move_clip": object_schema({"clip_id": STRING, "start_frame": FRAME, "track_id": STRING}, ["clip_id", "start_frame"]),
    "delete_clip": object_schema({"clip_id": STRING}, ["clip_id"]),
    "ripple_delete": object_schema({"clip_id": STRING}, ["clip_id"]),
    "set_clip_properties": object_schema({"clip_id": STRING, "properties": object_schema({"exposure": NUMBER, "contrast": NUMBER, "saturation": NUMBER, "gamma": NUMBER, "volume": NUMBER, "volume_db": {"type":"number", "minimum":-100, "maximum":30}, "pan": NUMBER, "opacity": NUMBER, "scale": NUMBER, "x": NUMBER, "y": NUMBER, "rotation": NUMBER, "fade_in_frames": FRAME, "fade_out_frames": FRAME})}, ["clip_id", "properties"]),
    "set_clip_speed": object_schema({"clip_id": STRING, "percentage": {"type": "number", "minimum": -1600, "maximum": 1600}, "ripple": BOOLEAN, "pitch_correction": BOOLEAN, "freeze_frame": FRAME}, ["clip_id", "percentage"]),
    "add_transition": object_schema({"clip_id": STRING, "position": {"type": "string", "enum": ["start", "end"]}, "duration_frames": {"type": "integer", "minimum": 1}, "alignment": {"type": "string", "enum": ["left", "center", "right"]}, "type": {"type": "string", "enum": ["Cross Dissolve"]}}, ["clip_id"]),
    "delete_transition": object_schema({"transition_id": STRING}, ["transition_id"]),
    "import_subtitles": object_schema({"path": STRING}, ["path"]),
    "add_subtitle": object_schema({"start_frame": FRAME, "end_frame": FRAME, "text": STRING}, ["start_frame", "end_frame", "text"]),
    "update_subtitle": object_schema({"cue_id": STRING, "start_frame": FRAME, "end_frame": FRAME, "text": STRING}, ["cue_id"]),
    "delete_subtitle": object_schema({"cue_id": STRING}, ["cue_id"]),
    "export_subtitles": object_schema({"path": STRING}, ["path"]),
    "set_subtitle_style": object_schema({"properties": object_schema({"font": STRING, "font_size": NUMBER, "color": STRING, "position": {"type": "string", "enum": ["bottom", "center", "top"]}, "margin_vertical": NUMBER, "outline": NUMBER})}, ["properties"]),
    "add_marker": object_schema({"frame": FRAME, "label": STRING, "color": STRING}, ["frame", "label"]),
    "undo": object_schema(), "redo": object_schema(),
    "render": object_schema({"output": STRING, "format": {"type": "string", "enum": ["mp4", "mov", "wav"]}}, ["output"]),
    "submit_render": object_schema({"output": STRING, "format": {"type": "string", "enum": ["mp4", "mov", "wav"]}}, ["output"]),
    "get_render_job": object_schema({"job_id": STRING}, ["job_id"]),
    "list_render_jobs": object_schema(),
    "get_capabilities": object_schema(),
    "get_transport": object_schema(),
    "set_playhead": object_schema({"frame": FRAME}, ["frame"]),
    "set_playback": object_schema({"state": {"type": "string", "enum": ["playing", "paused", "stopped"]}}, ["state"]),
    "set_page": object_schema({"page": {"type": "string", "enum": ["Media", "Photo", "Cut", "Edit", "Fusion", "Color", "Fairlight", "Deliver"]}}, ["page"]),
    "report_transport": object_schema({"page": STRING, "frame": FRAME, "playback": {"type": "string", "enum": ["playing", "paused", "stopped"]}, "applied_revision": FRAME, "session_id": STRING}, ["page", "frame", "playback"]),
}

DESCRIPTIONS = {
    "set_clip_properties": "Set clip image/audio properties. volume is linear amplitude (zero mutes), or use volume_db in -100..30 dB; reject both in one update. Projects retain canonical linear volume. pan is -100..100 (zero centered), currently calibrated only at 48000 Hz. Selected static mono/stereo DC cases match native PCM; waveform/automation/offset/general Fairlight parity remains unverified.",
    "set_media_data_level": "Set source media Data Level (Auto, Full, Video), shared by every timeline instance and undoable. Auto QTRLE follows captured Resolve video-level behavior; other Auto formats use decoder interpretation. RGB video levels retain negative/superwhite values inside the Fusion graph. Full HDR/color management equivalence remains unverified.",
    "render_fusion_frame": "Export a selected node (default MediaOut) to a lossless RGBA16 PNG, before clip grade/transforms/opacity and timeline compositing. Frame is zero-based and clip-local after retime. Incomplete unrelated branches are ignored; selected branch must be complete. Generator-only branches can render without opening offline source media. Does not change project/history. Associated RGB may exceed alpha; PNG viewers may assume straight alpha. Float32 carriers honor node image precision (Background Depth 0..4, inherited by Transform and matched to the Merge background). PNG clips negative/superwhite RGB; full native equivalence unverified.",
    "get_fusion_graph": "Read a clip-local independent compositing graph and node catalog; absent graphs read as MediaIn to MediaOut without changing project/history. Initial five-node subset; native Fusion equivalence is unverified.",
    "add_fusion_node": "Add a clip-local MediaIn, Background, Transform or Merge node. Background Depth selects 0=default (8-bit in this model), 1=8-bit integer, 2=16-bit integer, 3=16-bit float, 4=32-bit float. Incomplete disconnected nodes can be saved/edited; rendering requires a connected reachable path. Each MediaIn uses the same retimed clip on the project canvas.",
    "update_fusion_node": "Update node name, canvas position or supported numeric parameters atomically. Background RGBA 0..1; Transform CenterX/Y uses normalized bottom-left coordinates, Size uniform scaling, Angle counterclockwise degrees; Merge supports normal alpha-over and Blend only. Native parameter/render equivalence remains unverified.",
    "connect_fusion_nodes": "Connect an image Output to a target input on the same clip. Omit source_node_id to disconnect. Cycles, missing IDs and invalid ports reject atomically. Incomplete reachable paths block video rendering.",
    "delete_fusion_node": "Delete a graph node and disconnect its consumers in one undoable action. The designated MediaOut cannot be deleted.",
    "clear_fusion_graph": "Remove a clip's independent graph and restore the direct MediaIn to MediaOut path in one undoable action.",
    "inspect_fusion_settings": "Read a local Fusion .setting/.comp as literal data without executing Lua or changing the project. Summary gives active node classes and connection counts; detail=nodes pages nodes, explicit ports, keyframes and opaque expressions. Macro scopes are preserved, historical CustomData is excluded from active nodes. Does not import or render Fusion nodes.",
    "create_project": "Create an independent GT Studio project; does not modify Resolve projects.",
    "get_state": "Read the same live project displayed in the native editor.",
    "split_clip": "Split at an absolute timeline frame, preserving source in/out positions.",
    "append_clip": "Place a source range on a timeline track. Frame units follow project FPS.",
    "detach_audio": "Separate embedded video audio into an independently editable audio-track item, retaining source timing, retime, gain and fades without doubling audio. Optionally select a free audio track in the same timeline. Set linked=true to group the separated pair for linked ripple deletion. Default is unlinked; full native linked-selection/edit semantics remain unimplemented.",
    "link_clips": "Persist an explicit same-timeline clip group for linked move, ripple deletion and blade cuts. Splitting partitions linked members into independent groups before/after the timeline frame. Ordinary delete remains item-only. Linked timeline/source-range trims and speed changes are supported; complete native linked selection rules remain unimplemented.",
    "move_clip": "Move a clip and all explicitly linked peers by the same frame delta, retaining source ranges and peer offsets. Optional same-kind destination track applies to the selected item only. Any peer collision rejects the whole move. Native verification covers one aligned normal-speed A/V pair nudged right by one frame; generic vertical track mapping remains unverified.",
    "split_clip": "Split a clip at an absolute timeline frame, including linked peers crossing that frame. Each side becomes a separate link group. Source sampling retains rational retime positions. Native verification currently covers one aligned normal-speed A/V pair; complete offset/track-lock/selection behavior remains open.",
    "trim_clip_edge": "Set a timeline start or exclusive end to an absolute frame; linked peers adjust the same edge delta, retaining source mapping and offsets. Non-ripple trim: later clips stay put. Source-bound or peer-collision failures reject all changes. Native verified cases cover inward start/end trims of an aligned normal-speed A/V pair; general native trim semantics remain open.",
    "trim_clip": "Atomically update source in/out and optional timeline start for the selected clip and explicit linked peers. Omit unchanged source endpoints to preserve fractional retime positions. Source changes map through each peer's signed constant speed; no ripple. Native readback comparisons cover aligned normal-speed inward trims only; generic inspector semantics remain unverified.",
    "set_track_state": "Set persistent enabled/locked flags. Video enable affects picture, retaining embedded audio; audio enable affects its audio items. Locked tracks reject clip changes including indirect linked/ripple edits, atomically. Undo/redo and explicit unlock remain available. Native lock/API/sync-lock behavior is not yet runtime-compared.",
    "unlink_clips": "Remove the selected item's entire explicit clip link group, retaining all timeline items.",
    "render": "Render the current timeline with the independent engine: MP4 H.264/AAC, MOV ProRes/PCM24 or WAV PCM16. Inferred from suffix unless format is explicit.",
    "submit_render": "Render an immutable project snapshot in the background; returns a job ID.",
    "get_capabilities": "Read implemented capabilities and explicitly unimplemented Resolve parity requirements.",
    "get_transport": "Read requested and desktop-observed playback/page state. ui_connected proves recent desktop heartbeat only.",
    "set_playhead": "Request the live native editor seek to an absolute timeline frame. Query get_transport for observed effect.",
    "set_playback": "Request desktop play/pause/stop. If the UI is disconnected the command remains pending.",
    "set_page": "Select one native editor page. Selecting an unimplemented page does not implement its tools.",
    "report_transport": "Native editor heartbeat reporting observed page/playhead/playback; intended for the desktop client.",
    "set_clip_speed": "Set speed in percent on the selected item and explicit linked peers; negative reverses. Ripple changes each member duration and shifts following clips on member tracks; without ripple, preserve duration while source handles allow. Zero freezes from freeze_frame (absolute timeline frame), splitting off a moving prefix when inside the clip and partitioning linked prefix/tail groups; omitted frame uses a connected/pending playhead inside the clip, otherwise clip start. Frozen audio is muted. Linked freeze offsets are relative to each member start and must fit all members. Frame mapping stays rational. Native linked-audio getter semantics and arbitrary offset groups remain unverified.",
    "add_transition": "Add a video Cross Dissolve between adjacent same-track clips using source handles. Clips keep their timeline positions. Duration and left/center/right alignment define the transition window; audio remains unchanged. Other native transition types and complete behavioral parity are not implemented.",
    "delete_transition": "Remove a Cross Dissolve from the active project, retaining both source clips and their timeline positions.",
    "import_subtitles": "Import Unicode SRT cues into the active timeline. Timing is rounded to project frames; existing cues are retained.",
    "export_subtitles": "Write the active timeline subtitle cues to an SRT sidecar file atomically.",
}

def capabilities():
    return {
        "application": "GT Studio", "version": "0.1.0", "full_resolve_parity": False,
        "actions": sorted(SCHEMAS),
        "implemented_subsystems": ["JSON project persistence", "persistent clip-local five-node compositing graph, canvas editing and independent render execution", "media probing/import including still images", "frame timeline edits and ripple deletion", "persistent track enable masks and transactional lock enforcement", "constant speed/reverse/freeze across explicit linked peers with rational source positions and optional pitch correction", "adjacent video Cross Dissolve with source handles", "basic clip color and volume; calibrated 48kHz static clip pan", "clip transforms, opacity and fades", "multitrack video composite and audio mix", "default 1.5ms audio edge ramps and contiguous source joins; MOV nearest-even PCM24 quantization", "16-bit RGBA clip intermediates and 10-bit YUV422 main compositing", "explicit independent audio detachment preserving source timing and gain", "persistent clip groups with linked moves, timeline edge trims, atomic source-range/position edits, blade partitioning and ripple deletion on member tracks", "Unicode SRT interchange and frame-addressed subtitle burn-in/styles", "MP4 H264/AAC, MOV ProRes/PCM24, WAV PCM16 export", "shared desktop/HTTP/MCP control", "requested and desktop-observed playback/page control"],
        "unimplemented_subsystems": ["Resolve project/database format compatibility", "complete Fusion node engine, modifiers, masks, 3D and native settings execution", "ACES/HDR managed grading", "Fairlight bus/plugin engine", "AI/Neural Engine", "Blackmagic hardware", "cloud collaboration", "complete codec/format matrix", "exact UI and native behavioral equivalence"],
        "fusion_interchange": {"inspection": "read-only literal .setting/.comp graph inspection", "rendering": "independent clip-local MediaIn/MediaOut/Background/Transform/Merge subset", "node_checkpoints": "associated RGBA16 samples in PNG before clip/timeline processing; ordinary viewers may assume straight alpha", "compositing_precision": "Float32 carriers with Background depths default/8/16 integer and half/full float; Transform inherits source precision, Merge matches its background. Integer nodes clip out-of-range RGB. Adjacent default Transforms concatenate before inverse sampling with widened triangle shrink footprints. RGB8 inputs normalize as UNORM before data-level interpretation. Associated ProRes exports use explicit SMPTE170M video-range YUV10 conversion calibrated on captured SD cases. Source resize and timeline/PNG remain integer boundaries; native preference inheritance, arbitrary output color matrices, general DoD, Merge concatenation and full HDR are unverified", "expression_execution": False, "native_node_equivalence_verified": False, "setting_import": False},
        "evidence": "research/feature-inventory.json and research/evidence/",
    }

def validate(action, params):
    if action not in SCHEMAS:
        raise ValueError(f"Unknown action: {action}")
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    schema = SCHEMAS[action]
    missing = set(schema["required"]) - params.keys()
    extra = params.keys() - schema["properties"].keys()
    if missing or extra:
        raise ValueError(f"Invalid parameters; missing={sorted(missing)}, unknown={sorted(extra)}")
    def check(value, rule, label):
        if "oneOf" in rule:
            errors = []
            for candidate in rule["oneOf"]:
                try:
                    check(value, candidate, label)
                    return
                except ValueError as e:
                    errors.append(str(e))
            raise ValueError(f"{label}: invalid type")
        kind = rule.get("type")
        valid = {"string": isinstance(value, str), "boolean": isinstance(value, bool), "integer": isinstance(value, int) and not isinstance(value, bool),
                 "number": isinstance(value, (float, int)) and not isinstance(value, bool), "object": isinstance(value, dict), "array": isinstance(value, list)}
        if kind in valid and not valid[kind]:
            raise ValueError(f"{label}: expected {kind}")
        if kind == "number":
            import math
            if not math.isfinite(value):
                raise ValueError(f"{label}: must be finite")
        if "minimum" in rule and value < rule["minimum"]:
            raise ValueError(f"{label}: below minimum")
        if "maximum" in rule and value > rule["maximum"]:
            raise ValueError(f"{label}: above maximum")
        if "minLength" in rule and len(value) < rule["minLength"]:
            raise ValueError(f"{label}: empty string")
        if "enum" in rule and value not in rule["enum"]:
            raise ValueError(f"{label}: unsupported value")
        if kind == "array":
            if len(value) < rule.get("minItems", 0):
                raise ValueError(f"{label}: too few items")
            for index, item in enumerate(value):
                check(item, rule.get("items", {}), f"{label}[{index}]")
            if rule.get("uniqueItems") and len(set(value)) != len(value):
                raise ValueError(f"{label}: duplicate items")
        if kind == "object":
            if set(rule.get("required", [])) - value.keys():
                raise ValueError(f"{label}: missing fields")
            for key, child in value.items():
                if key not in rule.get("properties", {}):
                    raise ValueError(f"{label}: unknown field {key}")
                check(child, rule["properties"][key], f"{label}.{key}")
    for key, value in params.items():
        check(value, schema["properties"][key], key)
