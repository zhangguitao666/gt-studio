"""Measure isolated precision/identity-filter candidates against retained native media.

Experiments patch only this process's render command. Production source, original
projects and retained baseline media are never rewritten.
"""
import importlib.util
import importlib
import hashlib
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.compare_native_retime_media import decode_video,image_metrics
from scripts.verify_reference_transitions import identity


def main():
    baseline_path=ROOT/'research/native-media-comparison.json'
    report=json.loads(baseline_path.read_text())
    case=next(c for c in report['cases'] if c['native_timeline'].endswith('_100_false'))
    native=Path(case['native_export']['path']);project=Path(case['reconstruction']['project']['path'])
    assert identity(native)['sha256']==case['native_export']['sha256']
    assert identity(project)['sha256']==case['reconstruction']['project']['sha256']
    workspace=ROOT/'workspace/color-precision-diagnostic';workspace.mkdir(parents=True,exist_ok=True)
    archive=workspace/'source-before'
    if not (archive/'engine.py').is_file():raise RuntimeError('Select the retained source-before package; do not silently substitute current production')
    spec=importlib.util.spec_from_file_location('gtstudio_precision_baseline',archive/'__init__.py',submodule_search_locations=[str(archive)])
    package=importlib.util.module_from_spec(spec);sys.modules[spec.name]=package;spec.loader.exec_module(package)
    Engine=importlib.import_module('gtstudio_precision_baseline.engine').Engine
    native_frames=decode_video(native)['frames']
    variants=[('baseline',False,None,None),('skip_identity',True,None,None),
              ('rgba16_overlay422',True,'rgba64le','yuv422p10'),
              ('rgba16_overlay444',True,'rgba64le','yuv444p10'),
              ('rgba8_overlay444',True,None,'yuv444p10')]
    results=[]
    original_run=subprocess.run
    for name,skip,rgba,overlay in variants:
        engine=Engine(workspace/name);engine.dispatch('open_project',{'path':str(project)})
        commands=[]
        def run(command,*args,**kwargs):
            if '-filter_complex' in command:
                command=list(command);index=command.index('-filter_complex')+1;graph=command[index]
                if skip:
                    graph=graph.replace(',eq=brightness=0:contrast=1.0:saturation=1.0:gamma=1.0','')
                    graph=graph.replace(',lutrgb=r=val*1.0:g=val*1.0:b=val*1.0','')
                if rgba:graph=graph.replace(',format=rgba,',',format='+rgba+',')
                if overlay:graph=graph.replace(':eof_action=pass:enable=',':format='+overlay+':eof_action=pass:enable=')
                command[index]=graph;commands.append(command)
            return original_run(command,*args,**kwargs)
        output=workspace/f'{name}.mov'
        subprocess.run=run
        try:engine.dispatch('render',{'output':str(output)})
        finally:subprocess.run=original_run
        frames=decode_video(output)['frames'];metrics=image_metrics(native_frames,frames)
        results.append({'variant':name,'output':identity(output),'command':commands[0],
                        'metrics':{k:v for k,v in metrics.items() if k!='per_frame'}})
        print(json.dumps({'variant':name,'mae':metrics['mae_rgb_0_255'],'mse':metrics['mse_rgb_0_255_squared']}),flush=True)
    result={'status':'measured_experimental_candidates','baseline_report':identity(baseline_path),'native':identity(native),'project':identity(project),
            'comparison':'complete94-frame sequence normalized320x180RGB24 with retained decoder; one normal-speed fixture only',
            'variants':results,'production_source_before':[identity(p) for p in sorted(archive.glob('*.py'))],'production_changed':False,'full_resolve_parity':False}
    (ROOT/'research/color-precision-diagnostic.json').write_text(json.dumps(result,indent=2)+'\n')

if __name__=='__main__':main()
