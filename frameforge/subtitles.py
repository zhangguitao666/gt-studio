"""Independent subtitle cues, UTF-8 SRT interchange and literal textfile burn-in.

Times round to nearest integer with exact rational arithmetic, ties upward.
Cue end_frame is exclusive and overlaps are allowed. Text is preserved verbatim
apart from normalized CRLF/CR line endings. FFmpeg drawtext reads UTF-8 files
with expansion disabled, preserving literal braces, backslashes and percent.
"""
from __future__ import annotations
import copy
from fractions import Fraction
import math
import os
from pathlib import Path
import re
import tempfile
import uuid

DEFAULT_STYLE = {'font': 'Arial', 'font_size': 36, 'color': '#FFFFFF',
                 'position': 'bottom', 'margin_vertical': 28, 'outline': 2}
_TIMESTAMP = re.compile(r'^(\d{2,}):([0-5]\d):([0-5]\d),(\d{3})$')
_TIMING = re.compile(r'^(\d{2,}:[0-5]\d:[0-5]\d,\d{3}) --> (\d{2,}:[0-5]\d:[0-5]\d,\d{3})$')


def _rate(fps):
    try:
        value = Fraction(fps['num'], fps['den']) if isinstance(fps, dict) else Fraction(str(fps))
    except (ValueError, TypeError, ZeroDivisionError, KeyError) as exc:
        raise ValueError('Invalid subtitle frame rate') from exc
    if value <= 0:
        raise ValueError('Subtitle frame rate must be positive')
    return value


def _nearest(value):
    return (value.numerator * 2 + value.denominator) // (value.denominator * 2)


def milliseconds_to_frames(milliseconds, fps):
    if isinstance(milliseconds, bool) or not isinstance(milliseconds, int) or milliseconds < 0:
        raise ValueError('Subtitle milliseconds must be a nonnegative integer')
    return _nearest(Fraction(milliseconds, 1000) * _rate(fps))


def frames_to_milliseconds(frame, fps):
    _frame(frame)
    return _nearest(Fraction(frame * 1000, 1) / _rate(fps))


def _frame(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError('Subtitle frame must be a nonnegative integer')
    return value


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Subtitle text must be nonempty')
    value = value.replace('\r\n', '\n').replace('\r', '\n')
    try:
        value.encode('utf-8')
    except UnicodeError as exc:
        raise ValueError('Subtitle text must be valid Unicode') from exc
    if '\x00' in value or any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise ValueError('Subtitle text contains a control character')
    if any(not line.strip() for line in value.split('\n')):
        raise ValueError('Subtitle text cannot contain blank lines')
    return value


def validate_cues(cues):
    if not isinstance(cues, list):
        raise ValueError('Subtitle cues must be a list')
    result, ids = [], set()
    for cue in cues:
        if not isinstance(cue, dict):
            raise ValueError('Subtitle cue must be an object')
        start, end = _frame(cue.get('start_frame')), _frame(cue.get('end_frame'))
        if end <= start:
            raise ValueError('Subtitle end must be after start')
        ident = cue.get('id')
        if not isinstance(ident, str) or not ident or ident in ids:
            raise ValueError('Subtitle cue IDs must be unique nonempty strings')
        ids.add(ident)
        result.append({'id': ident, 'start_frame': start, 'end_frame': end, 'text': _text(cue.get('text'))})
    return result


def _timestamp_ms(value):
    match = _TIMESTAMP.fullmatch(value)
    if not match:
        raise ValueError('Invalid SRT timestamp')
    hours, minutes, seconds, milliseconds = map(int, match.groups())
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + milliseconds


def parse_srt(path, fps):
    rate = _rate(fps)
    try:
        content = Path(path).expanduser().read_text(encoding='utf-8-sig')
    except (OSError, UnicodeError) as exc:
        raise ValueError('Cannot read UTF-8 SRT: ' + str(exc)) from exc
    content = content.replace('\r\n', '\n').replace('\r', '\n').strip('\n')
    if not content:
        return []
    cues, previous_index = [], 0
    for block in re.split(r'\n[ \t]*\n', content):
        lines = block.split('\n')
        if len(lines) < 3 or not re.fullmatch(r'[1-9]\d*', lines[0]):
            raise ValueError('Invalid SRT cue index or missing text')
        index = int(lines[0])
        if index <= previous_index:
            raise ValueError('SRT cue indexes must increase')
        previous_index = index
        match = _TIMING.fullmatch(lines[1])
        if not match:
            raise ValueError('Invalid SRT timing line')
        start_ms, end_ms = map(_timestamp_ms, match.groups())
        if end_ms <= start_ms:
            raise ValueError('SRT end must be after start')
        start, end = milliseconds_to_frames(start_ms, rate), milliseconds_to_frames(end_ms, rate)
        if end <= start:
            raise ValueError('SRT cue becomes empty at the project frame rate')
        cues.append({'id': 'subtitle_' + uuid.uuid4().hex[:12], 'start_frame': start,
                     'end_frame': end, 'text': _text('\n'.join(lines[2:]))})
    return validate_cues(cues)


def _atomic_text(path, text):
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix='.frameforge-subtitle-', dir=destination.parent)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return str(destination)


def _srt_time(milliseconds):
    seconds, ms = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}'


def write_srt(cues, path, fps):
    rate = _rate(fps)
    blocks = []
    for index, cue in enumerate(sorted(validate_cues(cues), key=lambda c: (c['start_frame'], c['end_frame'])), 1):
        start, end = frames_to_milliseconds(cue['start_frame'], rate), frames_to_milliseconds(cue['end_frame'], rate)
        if end <= start:
            raise ValueError('Subtitle duration is below SRT millisecond precision')
        blocks.append(f'{index}\n{_srt_time(start)} --> {_srt_time(end)}\n{cue["text"]}\n')
    return _atomic_text(path, '\n'.join(blocks))


def validate_style(properties=None):
    properties = {} if properties is None else properties
    if not isinstance(properties, dict) or set(properties) - DEFAULT_STYLE.keys():
        raise ValueError('Unknown subtitle style properties')
    style = dict(DEFAULT_STYLE, **properties)
    if not isinstance(style['font'], str) or not re.fullmatch(r'[\w .-]{1,80}', style['font'], re.UNICODE):
        raise ValueError('Invalid subtitle font')
    if not isinstance(style['color'], str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', style['color']):
        raise ValueError('Subtitle color must be #RRGGBB')
    if style['position'] not in ('bottom', 'center', 'top'):
        raise ValueError('Subtitle position must be bottom, center or top')
    for key, lower, upper in [('font_size', 1, 500), ('margin_vertical', 0, 4000), ('outline', 0, 20)]:
        value = style[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lower <= value <= upper:
            raise ValueError('Invalid subtitle ' + key)
    return style


def escape_filter_path(path):
    """Escape a path for an unquoted FFmpeg filter option in direct argv.

    Apply option-value escaping first and filter-graph escaping second. The
    returned value must not be wrapped in another pair of quotes.
    """
    value = str(Path(path).expanduser().resolve())
    option = ''.join('\\' + c if c in "\\':" else c for c in value)
    return ''.join('\\' + c if c in "\\'[],;" else c for c in option)


class SubtitleActions:
    def import_subtitles(self, path):
        cues = parse_srt(path, self._require()['fps'])
        timeline = self._timeline()
        existing = validate_cues(timeline.get('subtitles', []))
        timeline['subtitles'] = validate_cues(existing + cues)
        return {'cues': copy.deepcopy(cues), 'imported': len(cues)}

    def add_subtitle(self, start_frame, end_frame, text):
        cue = validate_cues([{'id': 'subtitle_' + uuid.uuid4().hex[:12], 'start_frame': start_frame, 'end_frame': end_frame, 'text': text}])[0]
        timeline = self._timeline()
        timeline['subtitles'] = validate_cues(timeline.get('subtitles', []) + [cue])
        return copy.deepcopy(cue)

    def update_subtitle(self, cue_id, start_frame=None, end_frame=None, text=None):
        timeline = self._timeline()
        cues = validate_cues(timeline.get('subtitles', []))
        cue = next((c for c in cues if c['id'] == cue_id), None)
        if cue is None:
            raise ValueError('Unknown subtitle cue')
        for key, value in [('start_frame', start_frame), ('end_frame', end_frame), ('text', text)]:
            if value is not None:
                cue[key] = value
        cues = validate_cues(cues)
        timeline['subtitles'] = cues
        return copy.deepcopy(next(c for c in cues if c['id'] == cue_id))

    def delete_subtitle(self, cue_id):
        timeline = self._timeline()
        cues = validate_cues(timeline.get('subtitles', []))
        if not any(c['id'] == cue_id for c in cues):
            raise ValueError('Unknown subtitle cue')
        timeline['subtitles'] = [c for c in cues if c['id'] != cue_id]
        return {'deleted': cue_id}

    def export_subtitles(self, path):
        project = self._require()
        destination = Path(path).expanduser().resolve()
        if str(destination) in {m['path'] for m in project.get('media', [])} or destination == Path(project['path']):
            raise ValueError('Subtitle output must not overwrite project or source media')
        cues = self._timeline().get('subtitles', [])
        return {'path': write_srt(cues, path, project['fps']), 'exported': len(cues)}

    def set_subtitle_style(self, properties):
        timeline = self._timeline()
        current = timeline.get('subtitle_style', {})
        if not isinstance(properties, dict):
            raise ValueError('Subtitle style properties must be an object')
        style = validate_style(dict(current, **properties))
        timeline['subtitle_style'] = style
        return copy.deepcopy(style)


def subtitle_migrate_validate(timeline):
    """Validate then normalize subtitle fields on a timeline (atomic per fields)."""
    cues = validate_cues(timeline.get('subtitles', []))
    style = validate_style(timeline.get('subtitle_style', {}))
    timeline['subtitles'], timeline['subtitle_style'] = cues, style
    return timeline


def build_subtitle_filters(cues, fps, width, height, directory, style=None):
    """Build literal UTF-8 drawtext filters; directory must survive FFmpeg rendering.

    expansion=none and textfile prevent user cue text from being parsed as filter,
    ASS or drawtext expressions. Frame n selects the exact [start,end) interval.
    Source text is written verbatim, including ASCII braces/backslashes/percent.
    """
    _rate(fps)
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 2 for v in (width, height)):
        raise ValueError('Invalid subtitle canvas size')
    cues, style = validate_cues(cues), validate_style(style)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    positions = {'bottom': f'h-text_h-{style["margin_vertical"]}',
                 'center': '(h-text_h)/2', 'top': str(style['margin_vertical'])}
    filters = []
    for index, cue in enumerate(cues):
        path = directory / f'subtitle-{index}.txt'
        _atomic_text(path, cue['text'])
        filters.append(f"drawtext=font='{style['font']}':textfile={escape_filter_path(path)}:expansion=none:"
                       f"fontsize={style['font_size']}:fontcolor={style['color']}:borderw={style['outline']}:bordercolor=black:"
                       f"x=(w-text_w)/2:y={positions[style['position']]}:"
                       f"enable='gte(n,{cue['start_frame']})*lt(n,{cue['end_frame']})'")
    return filters
