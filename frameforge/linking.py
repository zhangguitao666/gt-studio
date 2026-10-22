"""Persistent clip groups used by explicit linked ripple deletion.

Linked moves preserve peer offsets and splits partition groups at the playhead; speed and freeze edits propagate through groups; complete native linked selection remains unfinished.
"""
import uuid


class LinkingActions:
    def _link_members(self, clip_id):
        clip, track = self._clip(clip_id)
        timeline = next(t for t in self._require()['timelines'] if track in t['tracks'])
        group = clip.get('link_group_id')
        return [(c, tr) for tr in timeline['tracks'] for c in tr['clips']
                if c['id'] == clip_id or (group and c.get('link_group_id') == group)]

    def _clean_links(self):
        for timeline in self._require()['timelines']:
            groups = {}
            for track in timeline['tracks']:
                for clip in track['clips']:
                    group = clip.get('link_group_id')
                    if group:
                        groups.setdefault(group, []).append(clip)
            for clips in groups.values():
                if len(clips) == 1:
                    clips[0].pop('link_group_id', None)

    def _validate_links(self):
        owners = {}
        for timeline in self._require()['timelines']:
            for track in timeline['tracks']:
                for clip in track['clips']:
                    if 'link_group_id' not in clip:
                        continue
                    group = clip['link_group_id']
                    if not isinstance(group, str) or not group.strip():
                        raise ValueError('Invalid link group ID')
                    if owners.setdefault(group, timeline['id']) != timeline['id']:
                        raise ValueError('Linked clips must belong to the same timeline')

    def link_clips(self, clip_ids):
        if not isinstance(clip_ids, list) or len(clip_ids) < 2 or any(not isinstance(i, str) for i in clip_ids) or len(set(clip_ids)) != len(clip_ids):
            raise ValueError('Provide at least two distinct clip IDs')
        selected = [self._clip(i) for i in clip_ids]
        timelines = {t['id'] for t in self._require()['timelines']
                     if any(track in t['tracks'] for _, track in selected)}
        if len(timelines) != 1:
            raise ValueError('Linked clips must belong to the same timeline')
        # Relinking selected items removes them from old groups, retaining other members.
        group = 'link_' + uuid.uuid4().hex[:12]
        for clip, _ in selected:
            clip['link_group_id'] = group
        self._clean_links()
        return {'link_group_id': group, 'clip_ids': list(clip_ids)}

    def unlink_clips(self, clip_id):
        members = self._link_members(clip_id)
        for clip, _ in members:
            clip.pop('link_group_id', None)
        return {'unlinked_clip_ids': [c['id'] for c, _ in members]}
