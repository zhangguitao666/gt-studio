#!/usr/bin/env python3
"""Measure native transition renders and retain bounded color/readback evidence.

The midpoint linear RGB blend is a hypothesis fitted to two flat-color sources,
not a reverse-engineered transfer function or complete transition parity proof.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
ROI={'x':288,'y':148,'width':64,'height':64}


def sha(raw):return hashlib.sha256(raw).hexdigest()


def identity(path):
    raw=path.read_bytes()
    return {'path':str(path.resolve()),'bytes':len(raw),'sha256':sha(raw)}


def json_sha(value):
    return sha(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8'))


def executable():
    existing=os.environ.get('FRAMEFORGE_FFMPEG') or shutil.which('ffmpeg')
    if existing:return Path(existing).resolve()
    import imageio_ffmpeg
    return Path(imageio_ffmpeg.get_ffmpeg_exe()).resolve()


def read_roi(path,ffmpeg):
    before=identity(path)
    metadata_command=[str(ffmpeg),'-nostdin','-hide_banner','-i',str(path)]
    metadata=subprocess.run(metadata_command,capture_output=True,text=True)
    if 'Video:' not in metadata.stderr:
        raise ValueError('No video stream identified: '+metadata.stderr)
    filters=f'crop={ROI["width"]}:{ROI["height"]}:{ROI["x"]}:{ROI["y"]},format=rgb24'
    command=[str(ffmpeg),'-nostdin','-v','error','-i',str(path),'-map','0:v:0','-vf',filters,'-fps_mode','passthrough','-f','rawvideo','-pix_fmt','rgb24','-']
    completed=subprocess.run(command,capture_output=True)
    if completed.returncode:raise ValueError('Native ROI decode failed: '+completed.stderr.decode('utf-8',errors='replace'))
    pixels=ROI['width']*ROI['height'];size=pixels*3
    if len(completed.stdout)%size:raise ValueError('Partial decoded RGB frame')
    means,spans=[],[]
    for offset in range(0,len(completed.stdout),size):
        frame=completed.stdout[offset:offset+size]
        means.append([sum(frame[channel::3])/pixels for channel in range(3)])
        spans.append([max(frame[channel::3])-min(frame[channel::3]) for channel in range(3)])
    if identity(path)!=before:raise ValueError('Input changed while decoded')
    return {'file':before,'metadata_command':metadata_command,'metadata_stderr':metadata.stderr,
            'metadata_return_code':metadata.returncode,'metadata_note':'No output requested; FFmpeg normally exits 1 after reporting input metadata.',
            'decode_command':command,'decoded_rgb_sha256':sha(completed.stdout),
            'decoded_frame_count':len(means),'roi_mean_rgb_by_frame':means,
            'maximum_spatial_channel_span':max((max(s) for s in spans),default=0),
            'unchanged_during_analysis':True}


def average(rows):
    return [sum(row[channel] for row in rows)/len(rows) for channel in range(3)]


def read_lifecycle(path):
    if not path.is_file():return None
    before=identity(path)
    document=json.loads(path.read_text())
    snapshot=Path(document['snapshot']['path'])
    snapshot_identity=identity(snapshot)
    if snapshot_identity['sha256']!=document['snapshot']['sha256']:
        raise ValueError('Lifecycle snapshot hash differs from native record provenance')
    cases=[]
    for record in document['records']:
        case=record['case']
        starts=[item['start'] for item in case['before']['video'] if item['kind']=='video']
        origin=min(starts)
        normalize=lambda rows:[dict(item,start_relative_frame=item['start']-origin) for item in rows]
        cases.append({'case':case,'origin_inferred_from_earliest_before_video_start':origin,
            'before_video_relative':normalize(case['before']['video']),
            'after_video_relative':normalize(case['after']['video']),
            'before_audio_relative':normalize(case['before']['audio']),
            'after_audio_relative':normalize(case['after']['audio']),
            'audio_getter_rows_unchanged':case['before']['audio']==case['after']['audio'],
            'native_record_anchor':{'table':record['table'],'primary_key':record['primary_key'],
                'column':record['column'],'blob_sha256':record['blob_sha256'],'decoded_sha256':record['decoded_sha256'],
                'all_json_occurrences':[{'decoded_offset':item['decoded_offset'],'bytes':item['bytes'],'sha256':item['sha256']} for item in record['json_occurrences']],
                'case_canonical_json_sha256':json_sha(case)}})
    if identity(path)!=before or identity(snapshot)!=snapshot_identity:
        raise ValueError('Lifecycle evidence changed while inspected')
    return {'evidence':before,'snapshot':snapshot_identity,'cases':cases,
        'limitations':['These are recorded native getter results, not decoded deletion renders.',
            'Normal deletion in this fixture preserves separate audio items; an editor with embedded clip audio has a different model unless independent A/V selection/linkage is implemented.',
            'Video transition cascade alone cannot establish full linked A/V or ripple semantics.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence',type=Path,default=ROOT/'research/transition-runtime-v1.json')
    parser.add_argument('--media-root',type=Path,default=ROOT/'workspace/transition-reference')
    parser.add_argument('--lifecycle-evidence',type=Path,default=ROOT/'research/transition-deletion-runtime.json')
    parser.add_argument('--output',type=Path,default=ROOT/'research/transition-media-measurements.json')
    args=parser.parse_args()
    ffmpeg=executable()
    source_evidence=identity(args.evidence)
    evidence=json.loads(args.evidence.read_text())
    snapshot=Path(evidence['snapshot']['path'])
    snapshot_before=identity(snapshot)
    if snapshot_before['sha256']!=evidence['snapshot']['sha256']:raise ValueError('Snapshot hash differs from native record provenance')
    sources={name:read_roi(args.media_root/(name+'.mp4'),ffmpeg) for name in ('red','blue')}
    cases=[]
    for record in evidence['records']:
        case=record['case'];name=case['timeline']
        output=read_roi(args.media_root/'native-v1'/(name+'.mov'),ffmpeg)
        colors=output['roi_mean_rgb_by_frame']
        red=average(colors[:12]);blue=average(colors[-12:]);delta=[b-r for b,r in zip(blue,red)]
        square=sum(v*v for v in delta)
        if not square:raise ValueError('Render has no distinguishable color endpoints')
        weights=[sum((c-r)*d for c,r,d in zip(color,red,delta))/square for color in colors]
        before=case['before'];after=case['after'];origin=before['origin'];cut=before['first']['finish']-origin
        transition=after['transition']
        actual_window=None
        fit=None
        if not transition.get('missing'):
            start=transition['start']-origin;end=transition['finish']-origin;duration=end-start
            actual_window={'start_frame':start,'end_frame_exclusive':end,'duration_frames':duration}
            predicted_start={'left':cut-duration,'right':cut,'center':cut-(duration+1)//2}[case['alignment']]
            residuals=[];pixel_errors=[];samples=[]
            for frame in range(start,end):
                expected=(frame-start+.5)/duration
                residual=weights[frame]-expected
                predicted=[r+expected*d for r,d in zip(red,delta)]
                errors=[a-b for a,b in zip(colors[frame],predicted)]
                residuals.append(residual);pixel_errors.extend(errors)
                samples.append({'frame':frame,'mean_rgb':colors[frame],'projected_blue_weight':weights[frame],
                                'midpoint_weight':expected,'weight_residual':residual,'rgb_residual':errors})
            outside=[abs(weights[frame]-(0 if frame<start else 1)) for frame in range(len(colors)) if not start<=frame<end]
            fit={'formula':'blue weight = (frame - start_frame + 0.5) / duration_frames',
                 'endpoint_model':'Projection onto each render\'s measured pure-red/pure-blue ROI endpoint RGB vector.',
                 'tested_frame_samples':samples,'maximum_absolute_weight_residual':max(map(abs,residuals)),
                 'root_mean_square_weight_residual':math.sqrt(sum(r*r for r in residuals)/len(residuals)),
                 'maximum_absolute_rgb_residual_8bit':max(map(abs,pixel_errors)),
                 'maximum_outside_window_endpoint_weight_residual':max(outside,default=0),
                 'hypothesis_threshold_weight':.01,'fits_bounded_color_fixture':max(map(abs,residuals))<.01,
                 'alignment_start_formula_matches_getter':predicted_start==start}
        mixed=[i for i,w in enumerate(weights) if .005<w<.995]
        clips_unchanged=all(before[key]==after[key] for key in ('first','second'))
        cases.append({'timeline':name,'label':name.rsplit('_',1)[-1],
            'native_record_anchor':{'evidence_file':str(args.evidence),'table':record['table'],'primary_key':record['primary_key'],
                'column':record['column'],'blob_sha256':record['blob_sha256'],'decoded_sha256':record['decoded_sha256'],
                'all_json_occurrences':[{'decoded_offset':item['decoded_offset'],'bytes':item['bytes'],'sha256':item['sha256']} for item in record['json_occurrences']],
                'case_canonical_json_sha256':json_sha(case)},
            'requested':{key:case[key] for key in ('alignment','duration','in_frame','out_frame','position')},
            'native_probe_case_completed':case['completed'],'add_returned_item':after['add_returned_item'],
            'native_before_clip_readbacks':{key:before[key] for key in ('first','second')},
            'native_after_clip_readbacks':{key:after[key] for key in ('first','second')},
            'native_before_readbacks_sha256':json_sha({key:before[key] for key in ('first','second')}),
            'native_after_readbacks_sha256':json_sha({key:after[key] for key in ('first','second')}),
            'two_video_clip_readbacks_unchanged':clips_unchanged,
            'timeline_origin_getter':origin,'cut_relative_frame':cut,
            'timeline_finish_getter':after['finish'],'getter_timeline_duration_frames':after['finish']-origin,
            'actual_transition_getter':transition,'actual_window_relative':actual_window,
            'render':output,'decoded_frame_count_matches_finish_getter':len(colors)==after['finish']-origin,
            'measured_red_endpoint_rgb':red,'measured_blue_endpoint_rgb':blue,
            'projected_blue_weight_by_frame':weights,'mixed_frame_indices':mixed,'midpoint_linear_hypothesis':fit,
            'hard_cut_measured':not mixed and all(abs(w-(0 if i<cut else 1))<.005 for i,w in enumerate(weights))})
    if identity(args.evidence)!=source_evidence or identity(snapshot)!=snapshot_before:
        raise ValueError('Evidence input changed during analysis')
    by_label={case['label']:case for case in cases}
    twelve=[case for case in cases if case['actual_window_relative'] and case['actual_window_relative']['duration_frames']==12]
    sequences=[case['render']['roi_mean_rgb_by_frame'][case['actual_window_relative']['start_frame']:case['actual_window_relative']['end_frame_exclusive']] for case in twelve]
    comparisons={'center12_startcenter12_roi_all_frames_identical':by_label['center12']['render']['roi_mean_rgb_by_frame']==by_label['startcenter12']['render']['roi_mean_rgb_by_frame'],
        'twelve_frame_cases_transition_roi_sequences_identical':all(sequence==sequences[0] for sequence in sequences),
        'interpretation':'Equality is restricted to the measured flat-color ROI, not full images, audio or source sampling.'}
    report={'schema_version':1,'evidence_type':'decoded_native_render_color_measurements',
        'native_probe_evidence':source_evidence,'native_project_snapshot':snapshot_before,
        'snapshot_and_probe_json_unchanged_during_analysis':True,'decoder':identity(ffmpeg),'roi':ROI,
        'color_pipeline':'FFmpeg crop then explicit rgb24; channel arithmetic mean over every pixel in each 64x64 ROI frame. No transfer-function linearization is applied.',
        'sources':sources,'case_count':len(cases),'cases':cases,'cross_case_comparisons':comparisons,
        'native_deletion_lifecycle':read_lifecycle(args.lifecycle_evidence),
        'limitations':['Pure red/blue and one ROI constrain only this color/codec/project configuration; midpoint weight fit is a hypothesis, not an exact native curve implementation.',
            'No source-frame number OCR or handle sampling identity is established; timeline placement and blending are distinct questions.',
            'No audio crossfade, pitch, phase, loudness, plugin, other transition, HDR, alpha or high-bit-depth equivalence measured.',
            'Before/after clip readbacks prove only the captured getter structure unchanged; they do not prove every project field unchanged.',
            'File hash stability is measured during this offline analysis, not across an uncaptured original render session.',
            'Marker bytes establish decoded-blob co-occurrence, not native wrapper association; retained JSON timeline values select these cases.',
            'These native measurements alone do not compare or prove independent implementation parity.'],
        'full_resolve_parity':False}
    args.output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'output':str(args.output),'cases':len(cases),'summary':[{'label':c['label'],'frames':c['render']['decoded_frame_count'],
        'window':c['actual_window_relative'],'unchanged_clips':c['two_video_clip_readbacks_unchanged'],
        'max_weight_residual':c['midpoint_linear_hypothesis']['maximum_absolute_weight_residual'] if c['midpoint_linear_hypothesis'] else None,
        'hard_cut':c['hard_cut_measured']} for c in cases]}))

if __name__=='__main__':main()
