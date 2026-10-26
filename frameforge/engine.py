"""Independent, non-destructive editing engine.

Project schema 1: {id,name,path,fps:{num,den},width,height,sample_rate,
 media:[{id,path,name,duration_seconds,still,video,audio,width,height}],
 timelines:[{id,name,tracks:[{id,name,kind,enabled,locked,clips:[{id,media_id,start_frame,
 in_frame,out_frame,duration_frames,speed_percentage,pitch_correction,
 source_start:{num,den},source_end:{num,den},
 properties:{exposure,contrast,saturation,gamma,volume,
 opacity,scale,x,y,rotation,fade_in_frames,fade_out_frames}}]}],
 markers:[{id,frame,name,color}],transitions:[{id,type,track_id,left_clip_id,
 right_clip_id,alignment,duration_frames,cut_frame,start_frame,end_frame}]}],
 active_timeline_id}.
Timeline positions and durations use integer project frames; out_frame is
exclusive. Retime source boundaries are exact rational project-frame positions,
with in_frame/out_frame bounding them by floor/ceil. Duration rounds exact source
span / absolute speed downward to a whole frame, minimum one frame. With
ripple disabled, speed retains timeline duration by changing the source range;
reaching the media boundary shortens the clip without moving following clips. Negative
speed reverses; zero speed freezes in_frame and retains duration with muted audio.
Splits retain fractional source boundaries and preserve the decoded frame sequence.
Transforms scale around the canvas center, then rotate clockwise and translate by
x/y pixels; opacity and fades reveal lower layers. Ripple deletion affects the
selected track, or each member track of an explicitly linked clip group. Video tracks composite in array order (later tracks on top); clip source audio
mixes across all tracks. Still images default to five seconds and loop during
rendering. MP4 uses H.264/AAC, MOV uses ProRes HQ/24-bit PCM, and WAV exports 16-bit PCM audio.
Identity clip processing retains16-bit RGBA intermediates and main compositing
uses10-bit YUV422 before final encoding. Transparent canvases use planar16-bit
RGB; some active filters and alpha negotiation still have lower precision. This
is not a managed HDR/ACES pipeline.
Mono source audio duplicates to both stereo channels at unity gain. The mixer
sums without normalization or an implicit limiter; integer PCM packing clips
overload, matching the captured default-bus PCM24 cases. Configured bus effects
and other output formats have not been calibrated. Cross Dissolve uses measured half-frame midpoint
weights, source handles, and pair compositing before surrounding video tracks.
Embedded audio can be detached into an independent audio-track clip without
doubling the mix. Default import still embeds it. Explicit groups support linked
ripple deletion, offset-preserving moves, non-ripple timeline edge trims and blade
cuts with separate groups on each side. Source-range and position edits commit atomically across peers. Native linked
selection and general move/split/trim/speed/inspector rules remain open. Explicit
linked speed edits propagate to all peers; interior freezes partition groups. Other transition types and structural
edits that invalidate a surviving transition are unsupported and reject atomically.
Track enabled/locked default to true/false for older projects. Video enable masks
picture while retaining embedded source audio; audio enable masks its audio items.
Locks reject clip/transition changes, including indirect group edits; explicit track
state changes, undo/redo and project switching remain available.
JSON edits never alter original media. Undo is in-memory.
"""
from __future__ import annotations
import copy
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid
from fractions import Fraction
from .subtitles import SubtitleActions, subtitle_migrate_validate, build_subtitle_filters
from .transitions import TransitionActions, validate_transitions, window_at_cut
from .linking import LinkingActions
from .fusion import FusionActions, validate_graph, compile_graph, has_processing, place_image, premultiplied_over, float_to_rgba16

PROPERTY_DEFAULTS = {"exposure": 0.0, "contrast": 1.0, "saturation": 1.0, "gamma": 1.0, "volume": 1.0, "pan": 0.0, "opacity": 1.0, "scale": 1.0, "x": 0.0, "y": 0.0, "rotation": 0.0, "fade_in_frames": 0, "fade_out_frames": 0}


def clip_duration(clip):
    """Timeline frames, including retime; legacy clips default to source span."""
    return clip.get('duration_frames', clip['out_frame'] - clip['in_frame'])


def _rational(value):
    if isinstance(value, dict):
        if set(value) != {'num', 'den'} or any(isinstance(value[k], bool) or not isinstance(value[k], int) for k in value) or value['den'] <= 0:
            raise ValueError('Invalid rational source position')
        return Fraction(value['num'], value['den'])
    return Fraction(value)


def _ratio(value):
    value = Fraction(value)
    return {'num': value.numerator, 'den': value.denominator}


def _timing(clip):
    clip.setdefault('speed_percentage', 100)
    clip.setdefault('pitch_correction', True)
    clip.setdefault('duration_frames', clip['out_frame'] - clip['in_frame'])
    clip.setdefault('source_start', _ratio(clip['in_frame']))
    clip.setdefault('source_end', _ratio(clip['out_frame']))
    return clip


def _duration_for_range(start, end, percentage):
    if percentage == 0:
        raise ValueError('Freeze duration must be retained explicitly')
    exact = (end - start) * 100 / abs(Fraction(str(percentage)))
    return max(1, exact.numerator // exact.denominator)


def _id(prefix):
    return prefix + '_' + uuid.uuid4().hex[:12]


def ffmpeg_executable():
    path = os.environ.get('FRAMEFORGE_FFMPEG') or shutil.which('ffmpeg')
    if path:
        return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as exc:
        raise ValueError('FFmpeg is required for media probing and rendering') from exc


class Engine(SubtitleActions, TransitionActions, LinkingActions, FusionActions):
    ACTIONS = ('list_actions', 'create_project', 'open_project', 'save_project',
               'get_state', 'probe_media', 'inspect_fusion_settings', 'get_fusion_graph', 'render_fusion_frame', 'add_fusion_node', 'update_fusion_node', 'connect_fusion_nodes', 'delete_fusion_node', 'clear_fusion_graph', 'import_media', 'set_media_data_level', 'create_timeline',
               'set_active_timeline', 'add_track', 'set_track_state', 'append_clip', 'detach_audio', 'link_clips', 'unlink_clips', 'split_clip',
               'trim_clip', 'trim_clip_edge', 'set_clip_speed', 'move_clip', 'delete_clip', 'ripple_delete', 'set_clip_properties',
               'add_marker', 'add_transition', 'delete_transition', 'set_project_settings', 'import_subtitles', 'add_subtitle', 'update_subtitle', 'delete_subtitle', 'export_subtitles', 'set_subtitle_style', 'render', 'undo', 'redo')

    def __init__(self, workspace):
        self.workspace = Path(workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.project = None
        self._undo = []
        self._redo = []

    def dispatch(self, action, params=None):
        if action not in self.ACTIONS:
            raise ValueError('Unknown action: ' + str(action))
        params = params or {}
        if not isinstance(params, dict):
            raise ValueError('Action parameters must be an object')
        readonly = {'list_actions', 'get_state', 'probe_media', 'inspect_fusion_settings', 'get_fusion_graph', 'render_fusion_frame', 'render', 'save_project', 'undo', 'redo', 'open_project', 'create_project'}
        before = copy.deepcopy(self.project)
        undo_before, redo_before = list(self._undo), list(self._redo)
        try:
            result = getattr(self, action)(**params)
            if before is not None and self.project is not None and action not in readonly:
                current_tracks = {track['id']: track for t in self.project['timelines'] for track in t['tracks']}
                for timeline in before['timelines']:
                    for track in timeline['tracks']:
                        if track.get('locked', False):
                            old_transitions = [t for t in timeline.get('transitions', []) if t['track_id'] == track['id']]
                            new_transitions = [t for current in self.project['timelines'] for t in current.get('transitions', []) if t['track_id'] == track['id']]
                            if track['id'] not in current_tracks or current_tracks[track['id']]['clips'] != track['clips'] or old_transitions != new_transitions:
                                raise ValueError('Track is locked: ' + track['name'])
            if action not in {'get_state','list_actions','probe_media','inspect_fusion_settings','get_fusion_graph','render_fusion_frame','render','save_project','undo','redo'} and self.project is not None:
                self._validate_links()
                for timeline in self.project['timelines']:
                    self._validate_transition_timeline(timeline)
        except (TypeError, KeyError) as exc:
            self.project = before
            self._undo, self._redo = undo_before, redo_before
            raise ValueError(str(exc)) from exc
        except Exception:
            self.project = before
            self._undo, self._redo = undo_before, redo_before
            raise
        if action not in readonly and before != self.project:
            self._undo.append(before)
            self._undo = self._undo[-100:]
            self._redo.clear()
        return result

    def list_actions(self):
        return {'actions': list(self.ACTIONS)}

    def get_state(self):
        return copy.deepcopy(self.project) if self.project else {'project': None}

    def _require(self):
        if self.project is None:
            raise ValueError('Create or open a project first')
        return self.project

    def _timeline(self, timeline_id=None):
        p = self._require()
        target = timeline_id or p['active_timeline_id']
        for t in p['timelines']:
            if t['id'] == target:
                return t
        raise ValueError('Timeline does not exist')

    def _track(self, track_id):
        for t in self._require()['timelines']:
            for track in t['tracks']:
                if track['id'] == track_id:
                    return track
        raise ValueError('Track does not exist')

    def _clip(self, clip_id):
        for t in self._require()['timelines']:
            for track in t['tracks']:
                for clip in track['clips']:
                    if clip['id'] == clip_id:
                        return clip, track
        raise ValueError('Clip does not exist')

    def _media(self, media_id):
        for media in self._require()['media']:
            if media['id'] == media_id:
                return media
        raise ValueError('Media does not exist')

    def _fps(self):
        p = self._require()['fps']
        return p['num'] / p['den']

    @staticmethod
    def _frame(value):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError('Frame values must be non-negative integers')
        return value

    def create_project(self, name='Untitled', path=None, fps=24, width=1920, height=1080, sample_rate=48000):
        if not isinstance(name, str) or not name.strip():
            raise ValueError('Project name is required')
        if isinstance(fps, (int, float)):
            from fractions import Fraction
            rate = Fraction(str(fps)).limit_denominator(1001000)
            fps = {'num': rate.numerator, 'den': rate.denominator}
        self._validate_settings(fps, width, height, sample_rate)
        target = Path(path).expanduser().resolve() if path else self.workspace / (_id('project') + '.json')
        self.project = {'schema_version': 1, 'id': _id('project'), 'name': name, 'path': str(target), 'fps': fps, 'width': width, 'height': height, 'sample_rate': sample_rate, 'media': [], 'timelines': [], 'active_timeline_id': None}
        self.create_timeline('Timeline 1')
        self._undo.clear()
        self._redo.clear()
        return self.get_state()

    @staticmethod
    def _validate_settings(fps, width, height, sample_rate):
        if not isinstance(fps, dict) or not all(isinstance(fps.get(k), int) and fps[k] > 0 for k in ('num', 'den')):
            raise ValueError('fps must be a positive rational {num,den}')
        if not 1 <= fps['num'] / fps['den'] <= 240:
            raise ValueError('Frame rate must be between 1 and 240')
        if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in (width, height, sample_rate)) or width % 2 or height % 2:
            raise ValueError('Dimensions must be positive even integers, sample_rate positive')

    def set_project_settings(self, **settings):
        p = self._require()
        if set(settings) - {'name', 'width', 'height', 'sample_rate', 'fps'}:
            raise ValueError('Unsupported project setting')
        proposed = {**p, **settings}
        self._validate_settings(proposed['fps'], proposed['width'], proposed['height'], proposed['sample_rate'])
        if 'fps' in settings and settings['fps'] != p['fps'] and any(tr['clips'] for t in p['timelines'] for tr in t['tracks']):
            raise ValueError('Cannot change frame rate after editing clips')
        p.update(settings)
        return self.get_state()

    def save_project(self, path=None):
        p = self._require()
        target = Path(path or p['path']).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        previous = p['path']
        p['path'] = str(target)
        temp = None
        try:
            with tempfile.NamedTemporaryFile('w', dir=target.parent, prefix='.' + target.name, delete=False, encoding='utf8') as out:
                temp = out.name
                json.dump(p, out, indent=2, ensure_ascii=False, allow_nan=False)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temp, target)
        except Exception:
            p['path'] = previous
            if temp and os.path.exists(temp):
                os.unlink(temp)
            raise
        return {'path': str(target), 'saved': True}

    def open_project(self, path):
        target = Path(path).expanduser().resolve()
        try:
            p = json.loads(target.read_text(encoding='utf8'))
            if p.get('schema_version') != 1 or not isinstance(p['media'], list) or not isinstance(p['timelines'], list):
                raise ValueError('Unsupported project format')
            self._validate_settings(p['fps'], p['width'], p['height'], p['sample_rate'])
            self.project = p
            self.project['path'] = str(target)
            self._timeline()
            seen_ids = set()
            def check_id(obj):
                identity = obj.get('id')
                if not isinstance(identity, str) or not identity or identity in seen_ids:
                    raise ValueError('Missing or duplicate object ID')
                seen_ids.add(identity)
            check_id(p)
            for media in p['media']:
                check_id(media)
                if not isinstance(media.get('path'), str) or not isinstance(media.get('duration_seconds'), (int, float)) or not math.isfinite(media['duration_seconds']) or media['duration_seconds'] < 0:
                    raise ValueError('Invalid media record')
                media.setdefault('still', False)
                channels = media.get('audio_channels')
                if channels is not None and (isinstance(channels, bool) or not isinstance(channels, int) or channels < 1):
                    raise ValueError('Invalid audio channel count')
                if not isinstance(media['still'], bool):
                    raise ValueError('Invalid still image flag')
                if not isinstance(media.get('video'), bool) or not isinstance(media.get('audio'), bool):
                    raise ValueError('Invalid media stream flags')
                from .media_levels import MODES
                if media.get('data_level', 'Auto') not in MODES:
                    raise ValueError('Invalid media data level')
                for field in ('video_codec', 'pixel_format'):
                    if field in media and not isinstance(media[field], str):
                        raise ValueError('Invalid media ' + field)
            for t in p['timelines']:
                check_id(t)
                subtitle_migrate_validate(t)
                t.setdefault('transitions', [])
                for transition in t['transitions']:
                    check_id(transition)
                for cue in t['subtitles']:
                    check_id(cue)
                for marker in t['markers']:
                    check_id(marker)
                    self._frame(marker['frame'])
                for track in t['tracks']:
                    check_id(track)
                    if track['kind'] not in ('video', 'audio'):
                        raise ValueError('Invalid track kind')
                    for field, default in (('enabled', True), ('locked', False)):
                        track.setdefault(field, default)
                        if not isinstance(track[field], bool):
                            raise ValueError('Invalid track ' + field + ' flag')
                    for c in track['clips']:
                        check_id(c)
                        _timing(c)
                        self._validate_clip(c, track)
                        if not isinstance(c['properties'], dict) or not {'exposure', 'contrast', 'saturation', 'gamma', 'volume'} <= set(c['properties']) or set(c['properties']) - set(PROPERTY_DEFAULTS):
                            raise ValueError('Invalid clip properties')
                        c['properties'] = {**PROPERTY_DEFAULTS, **c['properties']}
                        self._validate_properties(c['properties'])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError('Invalid project format: ' + str(exc)) from exc
        self._undo.clear()
        self._redo.clear()
        return self.get_state()

    def inspect_fusion_settings(self, path, detail='summary', offset=0, limit=25):
        from .fusion_settings import inspect_fusion_settings
        return inspect_fusion_settings(path, detail, offset, limit)

    def probe_media(self, path):
        target = Path(path).expanduser().resolve()
        if not target.is_file():
            raise ValueError('Media file not found: ' + str(target))
        proc = subprocess.run([ffmpeg_executable(), '-hide_banner', '-i', str(target)], capture_output=True, text=True)
        log = proc.stderr
        duration = re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)', log)
        video = bool(re.search(r'Stream .*Video:', log))
        audio = bool(re.search(r'Stream .*Audio:', log))
        if not video and not audio:
            raise ValueError('No supported audio or video streams: ' + log[-1500:])
        seconds = sum(float(v) * factor for v, factor in zip(duration.groups(), (3600, 60, 1))) if duration else 0
        audio_description = next((line for line in log.splitlines() if re.search(r'Stream .*Audio:', line)), '')
        layout_match = re.search(r'Audio:.*?\b\d+\s*Hz,\s*([^,]+)', audio_description)
        audio_layout = layout_match[1].strip() if layout_match else None
        known_layouts = {'mono': 1, 'stereo': 2, '2.1': 3, '3.0': 3, 'quad': 4, '4.0': 4, '5.0': 5, '5.1': 6, '5.1(side)': 6, '7.1': 8, '7.1(wide)': 8}
        channel_match = re.fullmatch(r'(\d+) channels', audio_layout or '')
        audio_channels = known_layouts.get(audio_layout, int(channel_match[1]) if channel_match else None)
        still = video and not audio and duration is None and target.suffix.lower() in {'.png', '.jpg', '.jpeg', '.bmp', '.webp', '.tif', '.tiff'}
        if still:
            seconds = 5.0
        dimensions = re.search(r'Video:.*?\b(\d{2,6})x(\d{2,6})\b', log)
        codec = re.search(r'Video:\s*([\w]+)', log)
        pixel_format = re.search(r'Video:.*?,\s*((?:rgb|bgr|gbr|argb|abgr|yuv|yuva|gray|ya)[\w]*)', log)
        return {'path': str(target), 'name': target.name, 'duration_seconds': seconds, 'still': still, 'video': video, 'audio': audio, 'audio_channels': audio_channels, 'audio_layout': audio_layout, 'width': int(dimensions[1]) if dimensions else 0, 'height': int(dimensions[2]) if dimensions else 0,
                'video_codec': codec[1] if codec else '', 'pixel_format': pixel_format[1] if pixel_format else '', 'data_level': 'Auto'}

    def _media_level_info(self, media):
        if ('video_codec' in media and 'pixel_format' in media) or not Path(media['path']).is_file():
            return media
        return {**self.probe_media(media['path']), **media}

    def set_media_data_level(self, media_id, mode):
        from .media_levels import MODES
        if mode not in MODES:
            raise ValueError('Data level must be Auto, Full or Video')
        media = self._media(media_id)
        if not media['video']:
            raise ValueError('Data level requires video media')
        media['data_level'] = mode
        return copy.deepcopy(media)

    def import_media(self, path):
        p = self._require()
        media = self.probe_media(path)
        media['id'] = _id('media')
        p['media'].append(media)
        return copy.deepcopy(media)

    def create_timeline(self, name='Timeline'):
        t = {'id': _id('timeline'), 'name': name, 'tracks': [], 'markers': []}
        subtitle_migrate_validate(t)
        t['transitions'] = []
        self._require()['timelines'].append(t)
        self.project['active_timeline_id'] = t['id']
        self.add_track('video')
        self.add_track('audio')
        return copy.deepcopy(t)

    def set_active_timeline(self, timeline_id):
        t = self._timeline(timeline_id)
        self.project['active_timeline_id'] = t['id']
        return copy.deepcopy(t)

    def add_track(self, kind='video', name=None, timeline_id=None):
        if kind not in ('video', 'audio'):
            raise ValueError('Track kind must be video or audio')
        t = self._timeline(timeline_id)
        track = {'id': _id('track'), 'name': name or kind.title() + ' ' + str(1 + sum(x['kind'] == kind for x in t['tracks'])), 'kind': kind, 'enabled': True, 'locked': False, 'clips': []}
        t['tracks'].append(track)
        return copy.deepcopy(track)

    def set_track_state(self, track_id, enabled=None, locked=None):
        track = self._track(track_id)
        for field, value in (('enabled', enabled), ('locked', locked)):
            if value is not None:
                if not isinstance(value, bool):
                    raise ValueError(field + ' must be boolean')
                track[field] = value
        return copy.deepcopy(track)

    def _validate_clip(self, clip, track, ignore_id=None):
        _timing(clip)
        if 'fusion_graph' in clip:
            if track['kind'] != 'video':
                raise ValueError('Fusion graph requires a video clip')
            validate_graph(clip['fusion_graph'])
        for key in ('in_frame', 'out_frame', 'start_frame'):
            self._frame(clip[key])
        media = self._media(clip['media_id'])
        if clip['out_frame'] <= clip['in_frame']:
            raise ValueError('Clip out_frame must exceed in_frame')
        if media['duration_seconds'] > 0 and clip['out_frame'] > math.ceil(media['duration_seconds'] * self._fps()) + 1:
            raise ValueError('Clip extends beyond source media')
        if not isinstance(clip.get('audio_enabled', True), bool):
            raise ValueError('audio_enabled must be boolean')
        if not media[track['kind']]:
            raise ValueError('Media lacks a ' + track['kind'] + ' stream')
        self._frame(clip['duration_frames'])
        if clip['duration_frames'] < 1:
            raise ValueError('Clip duration must be positive')
        percentage = clip['speed_percentage']
        if isinstance(percentage, bool) or not isinstance(percentage, (int, float)) or not math.isfinite(percentage) or not -1600 <= percentage <= 1600 :
            raise ValueError('Speed percentage must be finite and between -1600 and 1600')
        if not isinstance(clip['pitch_correction'], bool):
            raise ValueError('pitch_correction must be boolean')
        if not isinstance(clip['source_start'], dict) or not isinstance(clip['source_end'], dict):
            raise ValueError('Source boundaries must be rational objects')
        source_start, source_end = _rational(clip['source_start']), _rational(clip['source_end'])
        if source_start < clip['in_frame'] or source_end > clip['out_frame'] or source_start >= source_end:
            raise ValueError('Invalid fractional source range')
        if clip['in_frame'] != math.floor(source_start) or clip['out_frame'] != math.ceil(source_end):
            raise ValueError('Integer source metadata must bound fractional source range')
        if percentage != 0:
            exact_duration = (source_end - source_start) * 100 / abs(Fraction(str(percentage)))
            # Existing schema-1 projects rounded nearest; retain their source mapping
            # while newly requested speed changes follow observed whole-frame floor.
            if abs(Fraction(clip['duration_frames']) - exact_duration) >= 1:
                raise ValueError('Clip duration disagrees with retime source range')
        end = clip['start_frame'] + clip_duration(clip)
        for other in track['clips']:
            if other['id'] in (clip['id'], ignore_id):
                continue
            other_end = other['start_frame'] + clip_duration(other)
            if clip['start_frame'] < other_end and other['start_frame'] < end:
                raise ValueError('Clips overlap on the same track; use another track for compositing')

    def append_clip(self, media_id, track_id=None, in_frame=0, out_frame=None, start_frame=None):
        m = self._media(media_id)
        track = self._track(track_id) if track_id else next((tr for tr in self._timeline()['tracks'] if tr['kind'] == ('video' if m['video'] else 'audio')), None)
        if track is None:
            track = self._track(self.add_track('video' if m['video'] else 'audio')['id'])
        clip = {'id': _id('clip'), 'media_id': media_id, 'start_frame': start_frame if start_frame is not None else max((c['start_frame'] + clip_duration(c) for c in track['clips']), default=0), 'in_frame': in_frame, 'out_frame': out_frame if out_frame is not None else round(m['duration_seconds'] * self._fps()), 'properties': dict(PROPERTY_DEFAULTS)}
        self._validate_clip(clip, track)
        track['clips'].append(clip)
        return copy.deepcopy(clip)

    def detach_audio(self, clip_id, track_id=None, linked=False):
        if not isinstance(linked, bool):
            raise ValueError('linked must be boolean')
        clip, video_track = self._clip(clip_id)
        if video_track['kind'] != 'video' or not self._media(clip['media_id'])['audio']:
            raise ValueError('Select a video clip containing audio')
        if not clip.get('audio_enabled', True):
            raise ValueError('Clip audio has already been detached')
        timeline = next(t for t in self._require()['timelines'] if video_track in t['tracks'])
        target = self._track(track_id) if track_id else None
        if target is not None and (target['kind'] != 'audio' or target not in timeline['tracks']):
            raise ValueError('Destination must be an audio track in the same timeline')
        audio = copy.deepcopy(clip)
        audio.pop('fusion_graph', None)
        audio.update(id=_id('clip'), audio_enabled=True)
        if target is None:
            for candidate in timeline['tracks']:
                if candidate['kind'] != 'audio' or candidate.get('locked', False):
                    continue
                try:
                    self._validate_clip(audio, candidate)
                except ValueError:
                    continue
                target = candidate
                break
            if target is None:
                target = {'id': _id('track'), 'name': 'Audio ' + str(1 + sum(t['kind'] == 'audio' for t in timeline['tracks'])), 'kind': 'audio', 'enabled': True, 'locked': False, 'clips': []}
                timeline['tracks'].append(target)
        self._validate_clip(audio, target)
        target['clips'].append(audio)
        clip['audio_enabled'] = False
        if linked:
            self.link_clips([clip['id'], audio['id']])
        return {'video': copy.deepcopy(clip), 'audio': copy.deepcopy(audio), 'audio_track_id': target['id']}

    def split_clip(self, clip_id, frame):
        self._frame(frame)
        members = self._link_members(clip_id)
        selected, _ = self._clip(clip_id)
        if not selected['start_frame'] < frame < selected['start_frame'] + clip_duration(selected):
            raise ValueError('Split frame must be inside clip (absolute timeline frame)')
        if len(members) == 1:
            return self._split_single_clip(clip_id, frame)
        first_ids, second_ids, results = [], [], {}
        for member, _ in members:
            start, end = member['start_frame'], member['start_frame'] + clip_duration(member)
            if start < frame < end:
                result = self._split_single_clip(member['id'], frame)
                results[member['id']] = result
                first_ids.append(result['first']['id'])
                second_ids.append(result['second']['id'])
            elif end <= frame:
                first_ids.append(member['id'])
            else:
                second_ids.append(member['id'])
        # A blade cut creates independent groups on either side of the playhead.
        # Keeping the old group on every part would make a later ripple delete
        # incorrectly delete both halves of the original source.
        for ids in (first_ids, second_ids):
            for identity in ids:
                self._clip(identity)[0].pop('link_group_id', None)
            if len(ids) > 1:
                self.link_clips(ids)
        result = results[clip_id]
        return {'first': copy.deepcopy(self._clip(result['first']['id'])[0]),
                'second': copy.deepcopy(self._clip(result['second']['id'])[0]),
                'linked_splits': [{'original_clip_id': identity,
                                   'first_clip_id': parts['first']['id'],
                                   'second_clip_id': parts['second']['id']}
                                  for identity, parts in results.items()]}

    def _split_single_clip(self, clip_id, frame):
        clip, track = self._clip(clip_id)
        self._frame(frame)
        offset = frame - clip['start_frame']
        _timing(clip)
        if not 0 < offset < clip_duration(clip):
            raise ValueError('Split frame must be inside clip (absolute timeline frame)')
        second = copy.deepcopy(clip)
        second.update(id=_id('clip'), start_frame=frame, duration_frames=clip_duration(clip) - offset)
        source_start, source_end = _rational(clip['source_start']), _rational(clip['source_end'])
        if clip['speed_percentage']:
            delta = Fraction(offset) * abs(Fraction(str(clip['speed_percentage']))) / 100
            if clip['speed_percentage'] > 0:
                boundary = min(source_end, source_start + delta)
                clip['source_end'], second['source_start'] = _ratio(boundary), _ratio(boundary)
            else:
                boundary = max(source_start, source_end - delta)
                clip['source_start'], second['source_end'] = _ratio(boundary), _ratio(boundary)
            for part in (clip, second):
                part['in_frame'] = math.floor(_rational(part['source_start']))
                part['out_frame'] = math.ceil(_rational(part['source_end']))
        clip['duration_frames'] = offset
        track['clips'].insert(track['clips'].index(clip) + 1, second)
        return {'first': copy.deepcopy(clip), 'second': copy.deepcopy(second)}

    def trim_clip(self, clip_id, in_frame=None, out_frame=None, start_frame=None):
        selected, track = self._clip(clip_id)
        source_edit = in_frame is not None or out_frame is not None
        target = copy.deepcopy(selected)
        _timing(target)
        if start_frame is not None:
            target['start_frame'] = self._frame(start_frame)
        if in_frame is not None:
            target['source_start'] = _ratio(self._frame(in_frame))
        if out_frame is not None:
            target['source_end'] = _ratio(self._frame(out_frame))
        old_low, old_high = _rational(selected['source_start']), _rational(selected['source_end'])
        low, high = _rational(target['source_start']), _rational(target['source_end'])
        rate = Fraction(str(target['speed_percentage'])) / 100
        if source_edit and rate:
            target['duration_frames'] = _duration_for_range(low, high, target['speed_percentage'])
        target.update(in_frame=math.floor(low), out_frame=math.ceil(high))
        shift = target['start_frame'] - selected['start_frame']
        duration_change = target['duration_frames'] - selected['duration_frames']
        if rate > 0:
            lead, tail = (low - old_low) / rate, (high - old_high) / rate
        elif rate < 0:
            lead, tail = (high - old_high) / rate, (low - old_low) / rate
        members = self._link_members(clip_id)
        proposals = []
        for clip, owner in members:
            proposed = copy.deepcopy(target if clip['id'] == clip_id else clip)
            if clip['id'] != clip_id:
                proposed['start_frame'] += shift
                if source_edit:
                    peer_rate = Fraction(str(clip['speed_percentage'])) / 100
                    peer_low, peer_high = _rational(clip['source_start']), _rational(clip['source_end'])
                    if rate and peer_rate:
                        if peer_rate > 0:
                            peer_low += lead * peer_rate
                            peer_high += tail * peer_rate
                        else:
                            peer_high += lead * peer_rate
                            peer_low += tail * peer_rate
                        proposed['duration_frames'] = _duration_for_range(peer_low, peer_high, clip['speed_percentage'])
                    elif not rate and peer_rate:
                        raise ValueError('Unlink moving peers before editing a frozen source range')
                    elif not rate:
                        peer_low += low - old_low
                        peer_high += high - old_high
                    else:
                        proposed['duration_frames'] += duration_change
                    proposed.update(source_start=_ratio(peer_low), source_end=_ratio(peer_high),
                                    in_frame=math.floor(peer_low), out_frame=math.ceil(peer_high))
            if source_edit:
                media = self._media(proposed['media_id'])
                if not media.get('still') and media['duration_seconds'] > 0:
                    source_frames = round(Fraction(str(media['duration_seconds'])) * Fraction(self.project['fps']['num'], self.project['fps']['den']))
                    if _rational(proposed['source_end']) > source_frames:
                        raise ValueError('Trim extends beyond source media')
            proposals.append((proposed, owner))
        identities = {clip['id'] for clip, _ in proposals}
        final_tracks = {owner['id']: copy.deepcopy(owner) for _, owner in members}
        for owner in final_tracks.values():
            owner['clips'] = [clip for clip in owner['clips'] if clip['id'] not in identities]
        for clip, owner in proposals:
            final_tracks[owner['id']]['clips'].append(clip)
        for owner in final_tracks.values():
            for clip in owner['clips']:
                self._validate_clip(clip, owner)
        for proposed, _ in proposals:
            self._clip(proposed['id'])[0].update(proposed)
        if shift:
            timeline = next(t for t in self._require()['timelines'] if track in t['tracks'])
            self._shift_moved_transitions(timeline, identities, shift)
        return copy.deepcopy(self._clip(clip_id)[0])

    def trim_clip_edge(self, clip_id, edge, frame):
        self._frame(frame)
        if edge not in ('start', 'end'):
            raise ValueError('Trim edge must be start or end')
        selected, _ = self._clip(clip_id)
        boundary = selected['start_frame'] + (clip_duration(selected) if edge == 'end' else 0)
        delta = frame - boundary
        members = self._link_members(clip_id)
        proposed = []
        for member, track in members:
            clip = copy.deepcopy(member)
            _timing(clip)
            low, high = _rational(clip['source_start']), _rational(clip['source_end'])
            rate = abs(Fraction(str(clip['speed_percentage']))) / 100
            if edge == 'start':
                clip['start_frame'] += delta
                clip['duration_frames'] -= delta
                if clip['speed_percentage'] > 0:
                    low += delta * rate
                elif clip['speed_percentage'] < 0:
                    high -= delta * rate
            else:
                clip['duration_frames'] += delta
                if clip['speed_percentage'] > 0:
                    high += delta * rate
                elif clip['speed_percentage'] < 0:
                    low -= delta * rate
            clip.update(source_start=_ratio(low), source_end=_ratio(high),
                        in_frame=math.floor(low), out_frame=math.ceil(high))
            media = self._media(clip['media_id'])
            if not media.get('still') and media['duration_seconds'] > 0:
                source_frames = round(Fraction(str(media['duration_seconds'])) * Fraction(self.project['fps']['num'], self.project['fps']['den']))
                if high > source_frames:
                    raise ValueError('Trim extends beyond source media')
            proposed.append((clip, track))
        # Validate against the complete final arrangement, including other peers.
        identities = {clip['id'] for clip, _ in proposed}
        tracks = {track['id']: copy.deepcopy(track) for _, track in members}
        for track in tracks.values():
            track['clips'] = [c for c in track['clips'] if c['id'] not in identities]
        for clip, track in proposed:
            tracks[track['id']]['clips'].append(clip)
        for track in tracks.values():
            for clip in track['clips']:
                self._validate_clip(clip, track)
        for clip, _ in proposed:
            self._clip(clip['id'])[0].update(clip)
        return {'clip': copy.deepcopy(self._clip(clip_id)[0]),
                'trimmed_clip_ids': [clip['id'] for clip, _ in proposed],
                'edge': edge, 'frame': frame}

    def set_clip_speed(self, clip_id, percentage, ripple=False, pitch_correction=True, freeze_frame=None):
        members = self._link_members(clip_id)
        if len(members) == 1:
            return self._set_single_clip_speed(clip_id, percentage, ripple, pitch_correction, freeze_frame)
        offset = None
        if freeze_frame is not None:
            self._frame(freeze_frame)
            if percentage != 0:
                raise ValueError('freeze_frame applies only to zero speed')
            selected, _ = self._clip(clip_id)
            offset = freeze_frame - selected['start_frame']
            if any(not 0 <= offset < clip_duration(member) for member, _ in members):
                raise ValueError('Linked freeze offset must be inside every member')
        results, prefixes, tails = {}, [], []
        for member, _ in members:
            current, _ = self._clip(member['id'])
            peer_frame = current['start_frame'] + offset if offset is not None else None
            changed = self._set_single_clip_speed(member['id'], percentage, ripple, pitch_correction, peer_frame)
            results[member['id']] = changed['id']
            if changed['id'] != member['id']:
                prefixes.append(member['id'])
            tails.append(changed['id'])
        if prefixes:
            # Interior freezes must not leave moving prefixes linked to frozen
            # tails, otherwise a tail ripple delete removes both source halves.
            for ids in (prefixes, tails):
                for identity in ids:
                    self._clip(identity)[0].pop('link_group_id', None)
                if len(ids) > 1:
                    self.link_clips(ids)
            self._clean_links()
        return copy.deepcopy(self._clip(results[clip_id])[0])

    def _set_single_clip_speed(self, clip_id, percentage, ripple=False, pitch_correction=True, freeze_frame=None):
        clip, track = self._clip(clip_id)
        if not isinstance(ripple, bool) or not isinstance(pitch_correction, bool):
            raise ValueError('ripple and pitch_correction must be booleans')
        if isinstance(percentage, bool) or not isinstance(percentage, (int, float)) or not math.isfinite(percentage) or not -1600 <= percentage <= 1600 :
            raise ValueError('Invalid speed percentage')
        proposed = copy.deepcopy(track)
        target = next(c for c in proposed['clips'] if c['id'] == clip_id)
        _timing(target)
        old_duration = clip_duration(target)
        if freeze_frame is not None:
            self._frame(freeze_frame)
            if percentage != 0:
                raise ValueError('freeze_frame applies only to zero speed')
            offset = freeze_frame - target['start_frame']
            if not 0 <= offset < old_duration:
                raise ValueError('Freeze frame must be inside the selected clip')
            source_low, source_high = _rational(target['source_start']), _rational(target['source_end'])
            previous_rate = abs(Fraction(str(target['speed_percentage']))) / 100
            if target['speed_percentage'] < 0:
                sample = math.ceil(source_high - offset * previous_rate) - 1
            elif target['speed_percentage'] > 0:
                sample = math.floor(source_low + offset * previous_rate)
            else:
                sample = target['in_frame']
            sample = max(target['in_frame'], min(target['out_frame'] - 1, sample))
            if offset:
                prefix = target
                tail = copy.deepcopy(target)
                tail.update(id=_id('clip'), start_frame=freeze_frame, duration_frames=old_duration - offset)
                if previous_rate:
                    if prefix['speed_percentage'] > 0:
                        prefix['source_end'] = _ratio(source_low + offset * previous_rate)
                    else:
                        prefix['source_start'] = _ratio(source_high - offset * previous_rate)
                    prefix['in_frame'] = math.floor(_rational(prefix['source_start']))
                    prefix['out_frame'] = math.ceil(_rational(prefix['source_end']))
                prefix['duration_frames'] = offset
                proposed['clips'].insert(proposed['clips'].index(prefix) + 1, tail)
                target = tail
            target.update(in_frame=sample, out_frame=sample + 1, source_start=_ratio(sample), source_end=_ratio(sample + 1))
        target.update(speed_percentage=percentage, pitch_correction=pitch_correction)
        if percentage != 0:
            low, high = _rational(target['source_start']), _rational(target['source_end'])
            rate = abs(Fraction(str(percentage))) / 100
            if ripple:
                target['duration_frames'] = _duration_for_range(low, high, percentage)
            else:
                desired_span = old_duration * rate
                media = self._media(target['media_id'])
                media_frames = Fraction(round(Fraction(str(media['duration_seconds'])) * Fraction(self.project['fps']['num'], self.project['fps']['den'])))
                # A source endpoint is an exclusive rational interval boundary,
                # not Resolve's direction-dependent GetSourceEndFrame readback.
                if percentage > 0:
                    high = min(low + desired_span, media_frames) if media_frames > 0 else low + desired_span
                else:
                    low = max(Fraction(0), high - desired_span)
                target['source_start'], target['source_end'] = _ratio(low), _ratio(high)
                target['in_frame'], target['out_frame'] = math.floor(low), math.ceil(high)
                target['duration_frames'] = min(old_duration, _duration_for_range(low, high, percentage))
        shifted = set()
        shift = 0
        if ripple and percentage != 0:
            old_end = target['start_frame'] + old_duration
            shift = clip_duration(target) - old_duration
            for later in proposed['clips']:
                if later['id'] != clip_id and later['start_frame'] >= old_end:
                    later['start_frame'] += shift
                    shifted.add(later['id'])
        for c in proposed['clips']:
            self._validate_clip(c, proposed)
        track['clips'] = proposed['clips']
        if shift:
            timeline = next(t for t in self._require()['timelines'] if track in t['tracks'])
            self._shift_moved_transitions(timeline, shifted, shift)
        return copy.deepcopy(target)

    def move_clip(self, clip_id, start_frame, track_id=None):
        self._frame(start_frame)
        clip, old = self._clip(clip_id)
        new = self._track(track_id) if track_id else old
        timeline = next(t for t in self._require()['timelines'] if old in t['tracks'])
        if new not in timeline['tracks'] or new['kind'] != old['kind']:
            raise ValueError('Move destination must be a same-kind track in the same timeline')
        delta = start_frame - clip['start_frame']
        members = self._link_members(clip_id)
        identities = {member['id'] for member, _ in members}
        affected = {track['id']: track for _, track in members}
        affected[new['id']] = new
        proposed = {identity: copy.deepcopy(track) for identity, track in affected.items()}
        for track in proposed.values():
            track['clips'] = [c for c in track['clips'] if c['id'] not in identities]
        for member, track in members:
            target = new if member['id'] == clip_id else track
            moved = copy.deepcopy(member)
            moved['start_frame'] += delta
            proposed[target['id']]['clips'].append(moved)
        for track in proposed.values():
            for member in track['clips']:
                self._validate_clip(member, track)
        for identity, track in affected.items():
            track['clips'] = proposed[identity]['clips']
        self._shift_moved_transitions(timeline, identities, delta)
        return copy.deepcopy(self._clip(clip_id)[0])

    def _shift_moved_transitions(self, timeline, identities, delta):
        for transition in timeline.get('transitions', []):
            if {transition['left_clip_id'], transition['right_clip_id']} <= identities:
                left_track = self._clip(transition['left_clip_id'])[1]
                right_track = self._clip(transition['right_clip_id'])[1]
                if left_track['id'] == right_track['id']:
                    transition['track_id'] = left_track['id']
                    for key in ('cut_frame', 'start_frame', 'end_frame'):
                        transition[key] += delta

    def delete_clip(self, clip_id):
        clip, track = self._clip(clip_id)
        track['clips'].remove(clip)
        self._remove_clip_transitions(clip_id)
        self._clean_links()
        return {'deleted': clip_id}

    def ripple_delete(self, clip_id):
        clip, track = self._clip(clip_id)
        duration = clip_duration(clip)
        members = self._link_members(clip_id)
        deleted_ids = {c['id'] for c, _ in members}
        affected = {tr['id']: tr for _, tr in members}
        shifted, offsets = [], {}
        for target in affected.values():
            ranges = sorted((c['start_frame'], c['start_frame'] + clip_duration(c))
                            for c in target['clips'] if c['id'] in deleted_ids)
            proposed = copy.deepcopy(target)
            proposed['clips'] = [c for c in proposed['clips'] if c['id'] not in deleted_ids]
            for later in proposed['clips']:
                shift = sum(end - start for start, end in ranges if end <= later['start_frame'])
                if shift:
                    later['start_frame'] -= shift
                    offsets[later['id']] = shift
                    shifted.append(later['id'])
            for later in proposed['clips']:
                self._validate_clip(later, proposed)
            target['clips'] = proposed['clips']
        for identity in deleted_ids:
            self._remove_clip_transitions(identity)
        for timeline in self.project['timelines']:
            for transition in timeline.get('transitions',[]):
                left = offsets.get(transition['left_clip_id'], 0)
                right = offsets.get(transition['right_clip_id'], 0)
                if left and left == right:
                    for key in ('cut_frame','start_frame','end_frame'):
                        transition[key] -= left
        self._clean_links()
        return {'deleted': clip_id, 'deleted_clip_ids': [c['id'] for c, _ in members],
                'shifted_clip_ids': shifted, 'shift_frames': duration, 'shift_frames_by_clip': offsets}

    def _remove_clip_transitions(self, clip_id):
        for timeline in self._require()['timelines']:
            timeline['transitions'] = [transition for transition in timeline.get('transitions',[]) if clip_id not in (transition['left_clip_id'],transition['right_clip_id'])]

    def set_clip_properties(self, clip_id, properties=None, **kwargs):
        clip, _ = self._clip(clip_id)
        if properties is not None and not isinstance(properties, dict):
            raise ValueError('Clip properties must be an object')
        values = {**(properties or {}), **kwargs}
        if 'volume_db' in values:
            if 'volume' in values:
                raise ValueError('Specify either volume or volume_db, not both')
            db = values.pop('volume_db')
            if isinstance(db, bool) or not isinstance(db, (float, int)) or not -100<=db<=30 or not math.isfinite(db):
                raise ValueError('volume_db must be between -100 and 30 dB')
            values['volume'] = 10**(db/20)
        self._validate_properties(values)
        clip['properties'].update(values)
        return copy.deepcopy(clip)

    @staticmethod
    def _validate_properties(values):
        if not isinstance(values, dict):
            raise ValueError('Clip properties must be an object')
        limits = {'exposure': (-10, 10), 'contrast': (0, 10), 'saturation': (0, 10), 'gamma': (0.1, 10), 'volume': (0, 10**(30/20)), 'pan': (-100, 100), 'opacity': (0, 1), 'scale': (0.1, 10), 'x': (-1000000, 1000000), 'y': (-1000000, 1000000), 'rotation': (-360000, 360000)}
        for key, value in values.items():
            if key in ('fade_in_frames', 'fade_out_frames'):
                Engine._frame(value)
                continue
            if isinstance(value, bool) or key not in limits or not isinstance(value, (float, int)) or not math.isfinite(value) or not limits[key][0] <= value <= limits[key][1]:
                raise ValueError('Invalid clip property: ' + key)

    def add_marker(self, frame, name='Marker', color='#f2b84b', timeline_id=None, label=None):
        self._frame(frame)
        name = label if label is not None else name
        marker = {'id': _id('marker'), 'frame': frame, 'name': name, 'label': name, 'color': color}
        self._timeline(timeline_id)['markers'].append(marker)
        return copy.deepcopy(marker)

    def undo(self):
        if not self._undo:
            raise ValueError('Nothing to undo')
        self._redo.append(copy.deepcopy(self.project))
        self.project = self._undo.pop()
        return self.get_state()

    def redo(self):
        if not self._redo:
            raise ValueError('Nothing to redo')
        self._undo.append(copy.deepcopy(self.project))
        self.project = self._redo.pop()
        return self.get_state()

    def _transition_segment(self, clip, transition):
        """Extend the existing rational source mapping into required handles."""
        virtual = copy.deepcopy(clip)
        _timing(virtual)
        rate = abs(Fraction(str(virtual['speed_percentage']))) / 100
        offset_start = transition['start_frame'] - clip['start_frame']
        offset_end = transition['end_frame'] - clip['start_frame']
        low, high = _rational(virtual['source_start']), _rational(virtual['source_end'])
        if virtual['speed_percentage'] > 0:
            low, high = low + offset_start*rate, low + offset_end*rate
        elif virtual['speed_percentage'] < 0:
            low, high = high - offset_end*rate, high - offset_start*rate
        media = self._media(clip['media_id'])
        available = round(Fraction(str(media['duration_seconds'])) * Fraction(self.project['fps']['num'], self.project['fps']['den']))
        if media.get('still',False):
            low, high = Fraction(0), Fraction(max(1,transition['duration_frames'])) * (rate or 1)
        if not media.get('still',False) and (low < 0 or high > available):
            raise ValueError('Insufficient source handles for Cross Dissolve')
        virtual.update(start_frame=0, duration_frames=transition['duration_frames'], source_start=_ratio(low), source_end=_ratio(high), in_frame=math.floor(low), out_frame=math.ceil(high))
        virtual['_property_time_offset_frames'] = offset_start
        virtual['_property_duration_frames'] = clip_duration(clip)
        return virtual

    def _validate_transition_timeline(self, timeline):
        try:
            records = validate_transitions(timeline, clip_duration)
        except ValueError as exc:
            raise ValueError(str(exc) + '; delete the affected transition before this structural edit') from exc
        clips = {c['id']:c for track in timeline['tracks'] for c in track['clips']}
        for transition in records:
            if window_at_cut(transition['cut_frame'],transition['duration_frames'],transition['alignment']) != (transition['start_frame'],transition['end_frame']):
                raise ValueError('Transition alignment disagrees with its window')
            self._transition_segment(clips[transition['left_clip_id']], transition)
            self._transition_segment(clips[transition['right_clip_id']], transition)
        return records

    def _video_selection(self, clip, p):
        rate = f'{p["fps"]["num"]}/{p["fps"]["den"]}'
        fps = p['fps']['num']/p['fps']['den']
        length = clip_duration(clip)/fps
        low, high = _rational(clip['source_start']), _rational(clip['source_end'])
        speed = abs(Fraction(str(clip['speed_percentage'])))/100
        if speed == 0:
            selection = f'fps={rate},trim=start_frame={clip["in_frame"]}:end_frame={clip["in_frame"]+1},loop=loop=-1:size=1:start=0,setpts=round(N/({rate})/TB)'
        else:
            floor_low, ceil_high = math.floor(low), math.ceil(high)
            backwards = clip['speed_percentage'] < 0
            phase = Fraction(ceil_high)-high if backwards else low-floor_low
            reverse_filter = ',reverse' if backwards else ''
            selection = f'fps={rate},trim=start_frame={floor_low}:end_frame={ceil_high}{reverse_filter},settb=expr=1/1000000000,setpts=(N-{phase.numerator}/{phase.denominator})/({speed.numerator}/{speed.denominator})/({rate})/TB,fps={rate}:round=up:start_time=0,tpad=stop_mode=clone:stop_duration={length}'
        selection += f',trim=end_frame={clip_duration(clip)},setpts=round(N/({rate})/TB)'
        return selection

    def _video_filters(self, source, clip, p, label, *, full_canvas=False, associated_canvas=False):
        props = {**PROPERTY_DEFAULTS, **clip['properties']}
        rate = f'{p["fps"]["num"]}/{p["fps"]["den"]}'
        fps = p['fps']['num']/p['fps']['den']
        length = clip_duration(clip)/fps
        selection = self._video_selection(clip, p)
        transformed = any(props[key] != PROPERTY_DEFAULTS[key] for key in ('scale','x','y','rotation'))
        padding = 'black@0' if transformed else 'black'
        width = max(2,round(p['width']*props['scale']/2)*2)
        height = max(2,round(p['height']*props['scale']/2)*2)
        graph_filters = []
        associated = has_processing(clip.get('fusion_graph'))
        media = self._media_level_info(next(m for m in p['media'] if m['id'] == clip['media_id']))
        if associated:
            padding = 'black@0'
        input_chain = f'[{source}:v]{selection}'
        if 'fusion_graph' in clip:
            compiled = compile_graph(clip['fusion_graph'], input_chain, p, clip_duration(clip), label, media=media)
            if compiled is not None:
                graph_filters, node_output = compiled
                input_chain = f'[{node_output}]'
                # A link label must be followed directly by its first filter.
                chain = input_chain + f'scale={p["width"]}:{p["height"]}:force_original_aspect_ratio=decrease,setsar=1'
            else:
                chain = input_chain + f',scale={p["width"]}:{p["height"]}:force_original_aspect_ratio=decrease,setsar=1'
        else:
            chain = input_chain + f',scale={p["width"]}:{p["height"]}:force_original_aspect_ratio=decrease,setsar=1'
        if not associated:
            from .media_levels import level_filters
            before, after = level_filters(media)
            chain = input_chain + before + f',scale={p["width"]}:{p["height"]}:force_original_aspect_ratio=decrease,setsar=1' + (',format=gbrapf32le' + after if after else '')
        if associated or before or after:
            float_label, integer_label = label+'_float_output', label+'_integer_output'
            graph_filters.append(chain+f'[{float_label}]')
            graph_filters.extend(float_to_rgba16(float_label, integer_label))
            chain = f'[{integer_label}]null'
        if any(props[key] != PROPERTY_DEFAULTS[key] for key in ('contrast', 'saturation', 'gamma')):
            chain += f',eq=brightness=0:contrast={props["contrast"]}:saturation={props["saturation"]}:gamma={props["gamma"]}'
        if props['exposure']:
            chain += f',lutrgb=r=val*{2**props["exposure"]}:g=val*{2**props["exposure"]}:b=val*{2**props["exposure"]}'
        chain += f',format=gbrap16le,format=rgba64le,pad={p["width"]}:{p["height"]}:(ow-iw)/2:(oh-ih)/2:color={padding},scale={width}:{height}'
        if props['rotation']:
            angle=props['rotation']*math.pi/180
            chain += f',rotate={angle}:ow=rotw({angle}):oh=roth({angle}):c=black@0'
        if associated:
            chain += ',format=gbrap16le,setpts=PTS-STARTPTS'
            factors = [str(props['opacity'])]
            offset = clip.get('_property_time_offset_frames', 0)/fps
            original_length = clip.get('_property_duration_frames', clip_duration(clip))/fps
            if props['fade_in_frames']:
                factors.append(f'min(max((T+({offset}))/({props["fade_in_frames"]/fps}),0),1)')
            if props['fade_out_frames']:
                factors.append(f'min(max(({original_length}-T-({offset}))/({props["fade_out_frames"]/fps}),0),1)')
            factor = '*'.join(factors)
            chain += ',' + 'geq=' + ':'.join(f"{component}='{sample}(X,Y)*({factor})'" for component,sample in (('r','r'),('g','g'),('b','b'),('a','alpha')))
        else:
            chain += f',colorchannelmixer=aa={props["opacity"]},setpts=PTS-STARTPTS'
        if not associated and '_property_time_offset_frames' in clip:
            factors=[]
            offset=clip['_property_time_offset_frames']/fps
            if props['fade_in_frames']:
                factors.append(f'min(max((T+({offset}))/({props["fade_in_frames"]/fps}),0),1)')
            if props['fade_out_frames']:
                factors.append(f'min(max(({clip["_property_duration_frames"]/fps}-T-({offset}))/({props["fade_out_frames"]/fps}),0),1)')
            if factors:
                chain += ",geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='alpha(X,Y)*"+'*'.join(factors)+"'"
        elif not associated:
            if props['fade_in_frames']:
                chain += f',fade=t=in:st=0:d={props["fade_in_frames"]/fps}:alpha=1'
            if props['fade_out_frames']:
                fade_length=props['fade_out_frames']/fps
                chain += f',fade=t=out:st={max(0,length-fade_length)}:d={fade_length}:alpha=1'
        if not full_canvas:
            return graph_filters + [chain+f',setpts=PTS+round({clip["start_frame"]}/({rate})/TB)[{label}]']
        raw, canvas = label+'_raw',label+'_canvas'
        if associated or associated_canvas:
            if not associated:
                chain += ',format=gbrap16le,premultiply=inplace=1'
            placed = label+'_placed'
            return graph_filters + [chain+f'[{raw}]'] + place_image(raw, placed, p['width'], p['height'], props['x'], props['y']) + [f'[{placed}]settb=expr=1/({rate}),setpts=N,fps={rate}[{label}]']
        return graph_filters + [chain+f'[{raw}]',f'color=c=black@0:s={p["width"]}x{p["height"]}:r={rate}:d={length},format=gbrap16le[{canvas}]',f'[{canvas}][{raw}]overlay=x=(W-w)/2+{props["x"]}:y=(H-h)/2+{props["y"]}:format=auto:eof_action=pass,format=gbrap16le,premultiply=inplace=1[{label}]']

    def _fusion_composite(self, background, foreground, output, p, start, duration, enable, x=0, y=0):
        placed, aligned = output+'_placed', output+'_aligned'
        filters = place_image(foreground, placed, p['width'], p['height'], x, y)
        factor = enable.replace('n,', 'N,')
        mask = ':'.join(f"{component}='{sample}(X,Y)*({factor})'" for component,sample in (('r','r'),('g','g'),('b','b'),('a','alpha')))
        rate = f'{p["fps"]["num"]}/{p["fps"]["den"]}'
        filters.append(f'[{placed}]settb=expr=1/({rate}),setpts=N,fps={rate},tpad=start={start}:stop={duration}:start_mode=add:stop_mode=add:color=black@0,trim=end_frame={duration},setpts=N,geq={mask}[{aligned}]')
        clocked_back = output+'_background'
        filters.append(f'[{background}]settb=expr=1/({rate}),setpts=N,fps={rate}[{clocked_back}]')
        return filters + premultiplied_over(clocked_back, aligned, output)

    def render(self, output, timeline_id=None, format=None):
        with tempfile.TemporaryDirectory(prefix="gt-studio-audio-") as audio_temp:
            return self._render(output, timeline_id, format, audio_temp)

    def _render(self, output, timeline_id, format, audio_temp):
        p = copy.deepcopy(self._require())
        timeline = copy.deepcopy(self._timeline(timeline_id))
        clips = [(track, clip) for track in timeline['tracks'] for clip in sorted(track['clips'], key=lambda c: c['start_frame'])]
        subtitle_migrate_validate(timeline)
        self._validate_transition_timeline(timeline)
        if not clips and not timeline['subtitles']:
            raise ValueError('Timeline is empty')
        fps = p['fps']['num'] / p['fps']['den']
        duration_frames = max([c['start_frame'] + clip_duration(c) for _, c in clips] + [cue['end_frame'] for cue in timeline['subtitles']])
        duration = duration_frames / fps
        destination = Path(output).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        output_format = format or destination.suffix.lower().lstrip('.')
        if output_format not in {'mp4', 'mov', 'wav'}:
            raise ValueError('Render format must be mp4, mov or wav')
        if str(destination) in {m['path'] for m in p['media']} or destination == Path(p['path']):
            raise ValueError('Output must not overwrite project or source media')
        cmd = [ffmpeg_executable(), '-hide_banner', '-loglevel', 'error', '-y', '-filter_complex_threads', '1', '-f', 'lavfi', '-i', f'color=c=black:s={p["width"]}x{p["height"]}:r={p["fps"]["num"]}/{p["fps"]["den"]}:d={duration:.9f}', '-f', 'lavfi', '-i', f'anullsrc=r={p["sample_rate"]}:cl=stereo']
        filters = [f'[1:a]atrim=duration={duration:.9f}[silence]']
        if output_format != 'wav':
            filters.insert(0, '[0:v]setpts=PTS-STARTPTS[base]')
        video_label = 'base'
        audio_labels = ['silence']
        input_indices = {}
        next_input = 2
        from .audio_edges import automatic_edges
        audio_edges = automatic_edges(clips, {m['id']:m for m in p['media']})
        associated_timeline = any(track['kind'] == 'video' and track.get('enabled', True) and has_processing(clip.get('fusion_graph')) for track, clip in clips)
        for index, (track, clip) in enumerate(clips):
            media = next(m for m in p['media'] if m['id'] == clip['media_id'])
            video_enabled = track['kind'] == 'video' and track.get('enabled', True) and media['video']
            # Video-track enable controls its picture. Embedded source audio is
            # retained, like a separate native audio item; audio-track enable
            # controls only the audio items on that track.
            audio_enabled = media['audio'] and clip.get('audio_enabled', True) and (track['kind'] == 'video' or track.get('enabled', True))
            if not (video_enabled and output_format != 'wav') and not (audio_enabled and clip.get('speed_percentage', 100) != 0):
                continue
            _timing(clip)
            source_low, source_high = _rational(clip['source_start']), _rational(clip['source_end'])
            source_start = float(source_low) / fps
            source_length = float(source_high - source_low) / fps
            length = clip_duration(clip) / fps
            speed = abs(Fraction(str(clip['speed_percentage']))) / 100
            start = clip['start_frame'] / fps
            if media.get('still', False):
                cmd += ['-loop', '1', '-framerate', f'{p["fps"]["num"]}/{p["fps"]["den"]}', '-t', f'{max(length, float(source_high) / fps):.9f}', '-i', media['path']]
            else:
                cmd += ['-i', media['path']]
            source = next_input
            next_input += 1
            input_indices[clip['id']] = source
            props = {**PROPERTY_DEFAULTS, **clip['properties']}
            if output_format != 'wav' and video_enabled:
                v = 'v' + str(index)
                rate = f'{p["fps"]["num"]}/{p["fps"]["den"]}'
                ordinary_associated = associated_timeline and not has_processing(clip.get('fusion_graph'))
                filters.extend(self._video_filters(source,clip,p,v,full_canvas=ordinary_associated,associated_canvas=ordinary_associated))
                merged = 'mix' + str(index)
                enable = f'gte(n,{clip["start_frame"]})*lt(n,{clip["start_frame"]+clip_duration(clip)})'
                for transition in timeline.get('transitions',[]):
                    if clip['id'] in (transition['left_clip_id'],transition['right_clip_id']):
                        enable += f'*(1-gte(n,{transition["start_frame"]})*lt(n,{transition["end_frame"]}))'
                if associated_timeline:
                    x, y = (0, 0) if ordinary_associated else (props['x'], props['y'])
                    filters.extend(self._fusion_composite(video_label, v, merged, p, clip['start_frame'], duration_frames, enable, x, y))
                else:
                    filters.append(f'[{video_label}][{v}]overlay=x=(W-w)/2+{props["x"]}:y=(H-h)/2+{props["y"]}:format=yuv422p10:eof_action=pass:enable=\'{enable}\'[{merged}]')
                video_label = merged
            if audio_enabled and speed != 0:
                a = 'a' + str(index)
                delay = round(start * p["sample_rate"])
                chain = f'[{source}:a]atrim=start={source_start:.12f}:duration={source_length:.12f},asetpts=PTS-STARTPTS'
                if clip['speed_percentage'] < 0:
                    chain += ',areverse'
                if clip['pitch_correction']:
                    remaining = float(speed)
                    while remaining > 2:
                        chain += ',atempo=2'
                        remaining /= 2
                    while remaining < .5:
                        chain += ',atempo=0.5'
                        remaining /= .5
                    if remaining != 1:
                        chain += f',atempo={remaining}'
                else:
                    chain += f',aresample={p["sample_rate"]},asetrate={p["sample_rate"]}*{float(speed)}'
                channels = media.get('audio_channels')
                if channels is None:
                    channels = self.probe_media(media['path']).get('audio_channels')
                channel_mapping = 'pan=stereo|c0=c0|c1=c0' if channels == 1 else 'aformat=channel_layouts=stereo'
                chain += f',aresample={p["sample_rate"]},{channel_mapping},apad,atrim=duration={length:.12f},volume={props["volume"]}'
                samples = round(Fraction(clip_duration(clip)*p['fps']['den']*p['sample_rate'],p['fps']['num']))
                ramp = max(1,round(Fraction(3*p['sample_rate'],2000)))
                head, tail = audio_edges[clip['id']]
                if props['pan']:
                    # Native waveform captures distinguish the order that DC
                    # inputs cannot: anti-click fades act on source samples
                    # before pan. Keep afade's double coefficient, then round
                    # the faded sample to float32 at the pan multiplication.
                    if head and not props['fade_in_frames']:
                        chain += f',afade=t=in:start_sample=0:nb_samples={ramp}:curve=tri'
                    if tail and not props['fade_out_frames']:
                        chain += f',afade=t=out:start_sample={max(0,samples-ramp)}:nb_samples={ramp}:curve=tri'
                    head, tail = False, False
                    from .audio_pan import write_envelope, targets
                    envelope = Path(audio_temp)/(clip['id']+'.wav')
                    count = write_envelope(envelope, props['pan'], samples, p['sample_rate'])
                    cmd += ['-i', str(envelope)]
                    env_input = next_input
                    next_input += 1
                    filters.append(chain+f'[{a}_before_pan]')
                    constant_tail = '|'.join(f'if(lt(n,{count}),val({channel}),{gain!r})'
                                             for channel, gain in enumerate(targets(props['pan'])))
                    filters.append(f"[{env_input}:a]apad,atrim=duration={length:.12f},aeval=exprs='{constant_tail}':channel_layout=stereo,aformat=sample_fmts=flt[{a}_pan_gain]")
                    chain = f'[{a}_before_pan][{a}_pan_gain]amultiply'
                if props['fade_in_frames']:
                    chain += f',afade=t=in:st=0:d={props["fade_in_frames"] / fps}'
                elif head:
                    chain += f',afade=t=in:start_sample=0:nb_samples={ramp}:curve=tri'
                if props['fade_out_frames']:
                    fade_length = props['fade_out_frames'] / fps
                    chain += f',afade=t=out:st={max(0, length-fade_length)}:d={fade_length}'
                elif tail:
                    chain += f',afade=t=out:start_sample={max(0,samples-ramp)}:nb_samples={ramp}:curve=tri'
                filters.append(chain + f',adelay={delay}S|{delay}S[{a}]')
                audio_labels.append(a)
            if output_format != 'wav' and track.get('enabled', True) and (index+1 == len(clips) or clips[index+1][0]['id'] != track['id']):
                for transition in timeline.get('transitions',[]):
                    if transition['track_id'] != track['id']:
                        continue
                    segment_labels=[]
                    originals = [self._clip(transition[side+'_clip_id'])[0] for side in ('left','right')]
                    associated_transition = associated_timeline
                    for side, original in zip(('left','right'), originals):
                        segment=self._transition_segment(original,transition)
                        input_index=input_indices[original['id']]
                        segment_label=transition['id']+'_'+side
                        filters.extend(self._video_filters(input_index,segment,p,segment_label,full_canvas=True,associated_canvas=associated_transition))
                        segment_labels.append(segment_label)
                    dissolved=transition['id']+'_dissolved'
                    weight=f'(N-0.5)/{transition["duration_frames"]}'
                    rate=f'{p["fps"]["num"]}/{p["fps"]["den"]}'
                    conversion = '' if associated_transition else ',unpremultiply=inplace=1,format=rgba64le'
                    filters.append(f'[{segment_labels[0]}][{segment_labels[1]}]blend=all_expr=\'A*(1-({weight}))+B*({weight})\'{conversion},setpts=PTS+round({transition["start_frame"]}/({rate})/TB)[{dissolved}]')
                    merged=transition['id']+'_composite'
                    if associated_transition:
                        enable = f'gte(n,{transition["start_frame"]})*lt(n,{transition["end_frame"]})'
                        filters.extend(self._fusion_composite(video_label, dissolved, merged, p, transition['start_frame'], duration_frames, enable))
                    else:
                        filters.append(f'[{video_label}][{dissolved}]overlay=format=yuv422p10:eof_action=pass:enable=\'gte(n,{transition["start_frame"]})*lt(n,{transition["end_frame"]})\'[{merged}]')
                    video_label=merged
        # Captured native PCM exports retain the summed waveform above unity
        # until integer packing clips it. An automatic limiter changes both
        # overload peaks and neighbouring samples through its gain envelope.
        audio_mix = ''.join('[' + x + ']' for x in audio_labels) + f'amix=inputs={len(audio_labels)}:duration=longest:normalize=0'
        if output_format == 'mov':
            # PCM24 packing drops the low S32 byte. Quantize to the target grid
            # first. Native overlap samples use nearest, ties to even.
            expressions=[]
            for channel in (0,1):
                value=f'val({channel})*8388608'
                expressions.append(f'if(eq(mod(abs({value}),1),0.5),2*round(({value})/2),round({value}))/8388608')
            audio_mix += ",aeval=exprs='"+'|'.join(expressions)+"':channel_layout=stereo"
        filters.append(audio_mix+'[aout]')
        subtitle_temp = None
        if output_format != 'wav' and timeline['subtitles']:
            subtitle_temp = tempfile.TemporaryDirectory(prefix='frameforge-subtitles-')
            try:
                text_filters = build_subtitle_filters(timeline['subtitles'], p['fps'], p['width'], p['height'], subtitle_temp.name, timeline['subtitle_style'])
                filters.append(f'[{video_label}]' + ','.join(text_filters) + '[subtitled]')
                video_label = 'subtitled'
            except Exception:
                subtitle_temp.cleanup()
                raise
        # Render to a sibling temporary file so failed encodes preserve existing exports.
        handle, temporary = tempfile.mkstemp(prefix='.frameforge-', suffix='.' + output_format, dir=destination.parent)
        os.close(handle)
        cmd += ['-filter_complex', ';'.join(filters)]
        if output_format != 'wav':
            cmd += ['-map', '[' + video_label + ']', '-r', f'{p["fps"]["num"]}/{p["fps"]["den"]}', '-fps_mode', 'cfr']
        cmd += ['-map', '[aout]', '-t', f'{duration:.9f}']
        if output_format == 'mp4':
            cmd += ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart']
        elif output_format == 'mov':
            cmd += ['-c:v', 'prores_ks', '-profile:v', '3', '-pix_fmt', 'yuv422p10le', '-c:a', 'pcm_s24le', '-movflags', '+faststart']
        else:
            cmd += ['-c:a', 'pcm_s16le']
        cmd.append(temporary)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode:
                raise ValueError('Render failed: ' + result.stderr[-6000:])
            os.replace(temporary, destination)
        finally:
            if subtitle_temp is not None:
                subtitle_temp.cleanup()
            if os.path.exists(temporary):
                os.unlink(temporary)
        return {'output': str(destination), 'format': output_format, 'duration_frames': duration_frames, 'duration_seconds': duration, 'bytes': destination.stat().st_size}
