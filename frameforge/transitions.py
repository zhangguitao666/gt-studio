"""Persistent transition structure and referential validation.

Cross Dissolve alignment offsets follow captured native runtime measurements.
The engine separately validates source handles and renders the measured
half-frame blend curve. Other transition types remain unsupported. A transition window is an exclusive [start_frame,end_frame)
interval; source clips remain adjacent in the editing model.
"""
from __future__ import annotations
import copy


def _frame(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, int) or value < (1 if positive else 0):
        raise ValueError('Transition frames must be nonnegative integers; duration must be positive')
    return value


def validate_transitions(timeline, duration_of):
    """Return a copied, validated list without changing the input project.

    Referential checks establish model integrity only, not native behavior.
    Alignment-to-window mapping and source handle sufficiency are checked
    separately by the engine action/renderer.
    """
    records = timeline.get('transitions', [])
    if not isinstance(records, list):
        raise ValueError('Timeline transitions must be a list')
    tracks = {track['id']: track for track in timeline['tracks']}
    known, boundaries, output = set(), set(), []
    required = {'id', 'type', 'track_id', 'left_clip_id', 'right_clip_id', 'alignment', 'duration_frames', 'cut_frame', 'start_frame', 'end_frame'}
    for transition in records:
        if not isinstance(transition, dict) or set(transition) != required:
            raise ValueError('Invalid transition record fields')
        for field in ('id', 'track_id', 'left_clip_id', 'right_clip_id'):
            if not isinstance(transition[field], str) or not transition[field]:
                raise ValueError('Transition references must be nonempty strings')
        if transition['id'] in known:
            raise ValueError('Duplicate transition ID')
        known.add(transition['id'])
        if transition['type'] != 'Cross Dissolve':
            raise ValueError('Only Cross Dissolve is supported')
        if transition['alignment'] not in ('left', 'center', 'right'):
            raise ValueError('Invalid transition alignment')
        for field in ('start_frame', 'end_frame', 'cut_frame'):
            _frame(transition[field])
        _frame(transition['duration_frames'], positive=True)
        if transition['end_frame'] - transition['start_frame'] != transition['duration_frames']:
            raise ValueError('Transition window disagrees with duration')
        if not transition['start_frame'] <= transition['cut_frame'] <= transition['end_frame']:
            raise ValueError('Transition window must include its cut')
        track = tracks.get(transition['track_id'])
        if track is None or track['kind'] != 'video':
            raise ValueError('Transition must reference an existing video track')
        clips = {clip['id']: clip for clip in track['clips']}
        left, right = clips.get(transition['left_clip_id']), clips.get(transition['right_clip_id'])
        if left is None or right is None or left is right:
            raise ValueError('Transition must reference two distinct clips on its track')
        cut = left['start_frame'] + duration_of(left)
        if cut != right['start_frame'] or cut != transition['cut_frame']:
            raise ValueError('Transition clips must remain adjacent at their cut')
        if transition['start_frame'] < left['start_frame'] or transition['end_frame'] > right['start_frame'] + duration_of(right):
            raise ValueError('Transition window extends outside its participating clips')
        boundary = (track['id'], left['id'], right['id'])
        if boundary in boundaries:
            raise ValueError('Only one transition may occupy a clip boundary')
        boundaries.add(boundary)
        output.append(copy.deepcopy(transition))
    ordered = sorted(output, key=lambda item: (item['track_id'], item['start_frame']))
    for previous, following in zip(ordered, ordered[1:]):
        if previous['track_id'] == following['track_id'] and previous['end_frame'] > following['start_frame']:
            raise ValueError('Transition windows cannot overlap on the same track')
    return output


def window_at_cut(cut, duration, alignment):
    """Native captured offsets: center has ceil(duration/2) before the cut."""
    _frame(cut)
    _frame(duration, positive=True)
    if alignment not in ('left', 'center', 'right'):
        raise ValueError('Invalid transition alignment')
    before = duration if alignment == 'left' else (duration+1)//2 if alignment == 'center' else 0
    return cut-before, cut-before+duration


class TransitionActions:
    def add_transition(self, clip_id, position='end', duration_frames=12, alignment='center', type='Cross Dissolve'):
        import uuid
        if type != 'Cross Dissolve' or position not in ('start', 'end'):
            raise ValueError('Only a start/end Cross Dissolve is supported')
        clip, track = self._clip(clip_id)
        if track['kind'] != 'video':
            raise ValueError('Cross Dissolve requires a video track')
        ordered = sorted(track['clips'], key=lambda item: item['start_frame'])
        index = ordered.index(clip)
        left_index = index if position == 'end' else index-1
        if left_index < 0 or left_index+1 >= len(ordered):
            raise ValueError('Cross Dissolve requires an adjacent clip at this edge')
        left, right = ordered[left_index:left_index+2]
        cut = right['start_frame']
        start, end = window_at_cut(cut, duration_frames, alignment)
        timeline = next(t for t in self.project['timelines'] if any(tr['id'] == track['id'] for tr in t['tracks']))
        record = {'id':'transition_'+uuid.uuid4().hex[:12], 'type':type, 'track_id':track['id'], 'left_clip_id':left['id'], 'right_clip_id':right['id'], 'alignment':alignment, 'duration_frames':duration_frames, 'cut_frame':cut, 'start_frame':start, 'end_frame':end}
        proposed = dict(timeline, transitions=timeline.get('transitions',[])+[record])
        self._validate_transition_timeline(proposed)
        timeline['transitions'] = proposed['transitions']
        return copy.deepcopy(record)

    def delete_transition(self, transition_id):
        for timeline in self._require()['timelines']:
            for transition in timeline.get('transitions',[]):
                if transition['id'] == transition_id:
                    timeline['transitions'].remove(transition)
                    return {'deleted':transition_id}
        raise ValueError('Transition does not exist')
