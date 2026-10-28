"""Measure native/product differences; this diagnostic is not a parity gate."""
import argparse
import base64
from collections import Counter
import hashlib
import json
import re
from pathlib import Path
import struct
import subprocess
import sys
import zlib
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from frameforge.engine import Engine,ffmpeg_executable
from scripts.verify_fusion_image_precision import make_source


def diagnose(names,output):
    ffmpeg=ffmpeg_executable()
    cases=json.loads((ROOT/'tests/fixtures/fusion-media-levels.json').read_text())['cases']
    references=json.loads((ROOT/'tests/fixtures/fusion-prores-reference.json').read_text())
    work=output.parent/'native-color-work';work.mkdir(parents=True,exist_ok=True)
    source=make_source(work,has_alpha=False)
    results=[]
    for name in names:
        case=next(c for c in cases if c['id']==name)
        e=Engine(work/name)
        e.dispatch('create_project',{'width':640,'height':360,'fps':24,'name':'Color diagnostic'})
        media=e.dispatch('import_media',{'path':str(source)})
        e.dispatch('set_media_data_level',{'media_id':media['id'],'mode':case['mode']})
        clip=e.dispatch('append_clip',{'media_id':media['id'],'out_frame':12})['id']
        bg=e.dispatch('add_fusion_node',{'clip_id':clip,'type':'Background','parameters':{'Blue':1,'Alpha':case['alpha']}})['id']
        merge=e.dispatch('add_fusion_node',{'clip_id':clip,'type':'Merge','parameters':{'Blend':case['blend']}})['id']
        for target,port,node in [(merge,'Background','MediaIn1'),(merge,'Foreground',bg),('MediaOut1','Input',merge)]:
            e.dispatch('connect_fusion_nodes',{'clip_id':clip,'target_node_id':target,'input':port,'source_node_id':node})
        movie=work/(name+'.mov');commands=[];negotiation=[];run=subprocess.run
        def record(command,*args,**kwargs):
            if '-filter_complex' in command and 'prores_ks' in command:
                commands.append(list(command));command=list(command);command[command.index('-loglevel')+1]='verbose'
                result=run(command,*args,**kwargs)
                negotiation.extend(line for line in result.stderr.splitlines() if 'auto_scale' in line or 'auto-inserting' in line)
                return result
            return run(command,*args,**kwargs)
        with patch('frameforge.engine.subprocess.run',side_effect=record):
            e.dispatch('render',{'output':str(movie)})
        assert len(commands)==1
        ref=references['carriers'][references['cases'][name]['carrier_sha256']]
        carrier=zlib.decompress(base64.b64decode(ref['base64']))
        assert hashlib.sha256(carrier).hexdigest()==ref['sha256']

        def decode(native,fmt,first=False):
            args=[ffmpeg,'-v','error','-i','pipe:0' if native else str(movie)]
            if first:args+=['-frames:v','1']
            args+=['-an','-pix_fmt',fmt,'-f','rawvideo','pipe:1']
            return subprocess.run(args,input=carrier if native else None,capture_output=True,check=True).stdout

        native,own=decode(True,'rgb24'),decode(False,'rgb24');assert len(native)==len(own)==12*640*360*3
        n=640*360;first_a=native[:n*3];first_b=own[:n*3]
        positions=[i for i in range(n) if first_a[i*3:i*3+3]!=first_b[i*3:i*3+3]]
        box=None if not positions else [min(i%640 for i in positions),min(i//640 for i in positions),max(i%640 for i in positions),max(i//640 for i in positions)]
        def colors(raw):return [[list(k),v] for k,v in Counter(zip(raw[::3],raw[1::3],raw[2::3])).most_common(12)]
        yuv={}
        for key,native_flag in [('native',True),('own',False)]:
            raw=decode(native_flag,'yuv422p10le',True);values=struct.unpack('<'+str(len(raw)//2)+'H',raw)
            yuv[key]={'first':[values[0],values[n],values[n+n//2]],
                'plane_values':[Counter(part).most_common(8) for part in (values[:n],values[n:n+n//2],values[n+n//2:])],
                'sha256':hashlib.sha256(raw).hexdigest()}
        row={'case':name,'rgb_exact':native==own,'first_bad_bbox':box,'first_bad_pixel':None if not positions else {'xy':[positions[0]%640,positions[0]//640],'native':list(first_a[positions[0]*3:positions[0]*3+3]),'own':list(first_b[positions[0]*3:positions[0]*3+3])},
            'native_colors':colors(first_a),'own_colors':colors(first_b),'yuv10':yuv,
            'native_frame_hashes':[hashlib.sha256(native[i*n*3:(i+1)*n*3]).hexdigest() for i in range(12)],
            'own_frame_hashes':[hashlib.sha256(own[i*n*3:(i+1)*n*3]).hexdigest() for i in range(12)]}
        # Replay the exact filter graph into a lossless carrier to distinguish
        # pre-encoder edge pixels from ProRes encode/decode edge handling.
        command=commands[0];lossless=list(command)
        at=lossless.index('-profile:v');del lossless[at:at+2]
        at=lossless.index('-movflags');del lossless[at:at+2]
        lossless[lossless.index('prores_ks')]='rawvideo'
        raw_carrier=work/(name+'-pre-encoder.nut');lossless[-1]=str(raw_carrier)
        subprocess.run(lossless,capture_output=True,check=True)
        def yuv_summary(path):
            data=subprocess.check_output([ffmpeg,'-v','error','-i',str(path),'-frames:v','1','-an','-pix_fmt','yuv422p10le','-f','rawvideo','-'])
            values=struct.unpack('<'+str(len(data)//2)+'H',data)
            return {'sha256':hashlib.sha256(data).hexdigest(),'plane_values':[Counter(part).most_common(8) for part in (values[:n],values[n:n+n//2],values[n+n//2:])]}
        stages={'pre_encoder':yuv_summary(raw_carrier)}
        # Tap the RGB16 input to the final color conversion without changing
        # any upstream filters; then convert that carrier independently.
        rgb_cmd=list(lossless);at=rgb_cmd.index('-filter_complex')+1
        upstream,last=rgb_cmd[at].rsplit(';',1)
        before_label=re.match(r'^\[([^]]+)\]',last)[1]
        conversion=last.split(']',1)[1].rsplit('[',1)[0]
        rgb_cmd[at]=upstream
        at=rgb_cmd.index('-map')+1;rgb_cmd[at]='['+before_label+']'
        rgb_cmd[rgb_cmd.index('-pix_fmt')+1]='gbrp16le'
        rgb_carrier=work/(name+'-pre-conversion.nut');rgb_cmd[-1]=str(rgb_carrier)
        subprocess.run(rgb_cmd,capture_output=True,check=True)
        data=subprocess.check_output([ffmpeg,'-v','error','-i',str(rgb_carrier),'-frames:v','1','-an','-pix_fmt','gbrp16le','-f','rawvideo','-'])
        values=struct.unpack('<'+str(len(data)//2)+'H',data)
        stages['pre_conversion_rgb16']={'sha256':hashlib.sha256(data).hexdigest(),'plane_values':[Counter(values[i*n:(i+1)*n]).most_common(8) for i in range(3)]}
        for scalar in (False,True):
            target=work/(name+'-convert-'+str(scalar)+'.nut')
            opts=['-cpuflags','0'] if scalar else []
            subprocess.run([ffmpeg,'-v','error','-y',*opts,'-i',str(rgb_carrier),'-an','-vf',conversion,'-c:v','rawvideo',str(target)],capture_output=True,check=True)
            stages['isolated_conversion_scalar_'+str(scalar)]=yuv_summary(target)
        for threads in (0,1):
            recoded=work/(name+'-reencode-'+str(threads)+'.mov')
            subprocess.run([ffmpeg,'-v','error','-y','-i',str(raw_carrier),'-an','-c:v','prores_ks','-profile:v','3','-threads:v',str(threads),str(recoded)],capture_output=True,check=True)
            stages['reencoded_threads_'+str(threads)]=yuv_summary(recoded)
        if name=='auto_b0':
            taps=['v0','mix0_placed','mix0_aligned','mix0_front','mix0_mask','mix0_weighted']
            tap_cmd=list(lossless);at=tap_cmd.index('-filter_complex')+1;graph=tap_cmd[at]
            for label in taps:
                marker='['+label+']';assert marker in graph
                graph=graph.replace(marker,'['+label+'_probe_source]',1)
                graph+=';['+label+'_probe_source]split=2['+label+']['+label+'_probe]'
            tap_cmd[at]=graph;tap_cmd[tap_cmd.index('-pix_fmt')+1]='gbrap16le'
            target=work/(name+'-pipeline-taps.nut')
            tap_cmd[-1:]=sum((['-map','['+label+'_probe]'] for label in taps),[])+['-frames:v','1',str(target)]
            subprocess.run(tap_cmd,capture_output=True,check=True)
            stages['pipeline_taps']={}
            for i,label in enumerate(taps,1):
                data=subprocess.check_output([ffmpeg,'-v','error','-i',str(target),'-map','0:v:'+str(i),'-frames:v','1','-pix_fmt','gbrap16le','-f','rawvideo','-'])
                values=struct.unpack('<'+str(len(data)//2)+'H',data);assert len(values)==n*4
                stages['pipeline_taps'][label]={'sha256':hashlib.sha256(data).hexdigest(),'plane_values':[Counter(values[j*n:(j+1)*n]).most_common(8) for j in range(4)]}
        stages['filter_negotiation']=negotiation
        row['stages']=stages
        results.append(row);print(json.dumps(row),flush=True)
    report={'decoder':subprocess.check_output([ffmpeg,'-version'],text=True).splitlines()[0],
        'cases':results,'scope':'Diagnostics only; inspect the full test job for acceptance','full_resolve_parity':False}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases',nargs='+',default=['auto_b0','full_b0p75'])
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();diagnose(args.cases,args.output)
