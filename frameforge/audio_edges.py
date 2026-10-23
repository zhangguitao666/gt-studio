"""Default anti-click edges observed in Resolve PCM exports.

At 48 kHz, isolated audio edges have 72-sample linear ramps. Contiguous
source ranges on one track join without an internal ramp. Other source/rate
combinations are independent extrapolations until specifically compared.
"""
from fractions import Fraction


def automatic_edges(clips, media):
    """Return head/tail ramp flags for active, non-frozen audio instances."""
    by_track={}
    for track,clip in clips:
        source=media[clip['media_id']]
        if source['audio'] and clip.get('audio_enabled',True) and clip.get('speed_percentage',100)!=0 and (track['kind']=='video' or track.get('enabled',True)):
            by_track.setdefault(track['id'],[]).append(clip)
    edges={c['id']:[True,True] for group in by_track.values() for c in group}
    def point(clip,name,legacy):
        value=clip.get(name,clip[legacy])
        return Fraction(value['num'],value['den']) if isinstance(value,dict) else Fraction(value)
    def duration(clip):return clip.get('duration_frames',clip['out_frame']-clip['in_frame'])
    for group in by_track.values():
        group.sort(key=lambda c:c['start_frame'])
        for left,right in zip(group,group[1:]):
            if left['start_frame']+duration(left)!=right['start_frame']:continue
            if media[left['media_id']]['path']!=media[right['media_id']]['path']:continue
            speed=left.get('speed_percentage',100)
            if speed!=right.get('speed_percentage',100) or left.get('pitch_correction',True)!=right.get('pitch_correction',True):continue
            lp,rp=left['properties'],right['properties']
            if lp.get('volume',1)!=rp.get('volume',1) or lp.get('fade_out_frames',0) or rp.get('fade_in_frames',0):continue
            exact_span=point(left,'source_end','out_frame')-point(left,'source_start','in_frame')
            if exact_span!=duration(left)*abs(Fraction(str(speed)))/100:continue
            touching=(point(left,'source_end','out_frame')==point(right,'source_start','in_frame') if speed>0 else point(left,'source_start','in_frame')==point(right,'source_end','out_frame'))
            if touching:edges[left['id']][1]=False;edges[right['id']][0]=False
    return edges
