"""Rebuild captured precision scenes through configured stdio MCP."""
import argparse
import array
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from frameforge.engine import ffmpeg_executable
from scripts.verify_fusion_nodes import ConfiguredClient, identity

FIXTURE = ROOT/'tests/fixtures/fusion-image-precision.json'


def make_source(work, has_alpha=True):
    work = Path(work); work.mkdir(parents=True, exist_ok=True)
    stem = 'rgba252' if has_alpha else 'rgb252'
    source, png = work/(stem+'-qtrle.mov'), work/(stem+'.png')
    pixel = bytes([252, 0, 0, 255] if has_alpha else [252, 0, 0])
    if not source.exists():
        if not png.exists():
            subprocess.run([ffmpeg_executable(), '-v', 'error', '-f', 'rawvideo', '-pixel_format', 'rgba' if has_alpha else 'rgb24',
                '-video_size', '640x360', '-i', 'pipe:0', '-frames:v', '1', str(png)], input=pixel*(640*360), check=True)
        subprocess.run([ffmpeg_executable(), '-v', 'error', '-nostdin', '-loop', '1', '-framerate', '24',
            '-i', str(png), '-t', '2', '-pix_fmt', 'argb' if has_alpha else 'rgb24', '-c:v', 'qtrle', str(source)], check=True)
    raw = subprocess.check_output([ffmpeg_executable(), '-v', 'error', '-i', str(source),
        '-an', '-pix_fmt', 'rgba', '-f', 'rawvideo', '-'])
    assert raw == bytes([252,0,0,255])*(640*360*48), 'The workspace source does not match the captured source pixels'
    return source


def build_case(call, case, source):
    graph_case = case['kind']=='graph'
    call('create_project', name='Precision '+case['name'], width=640 if graph_case else 320,
         height=360 if graph_case else 320, fps=24)
    media = call('import_media', path=str(source))
    if 'source_pixel_format' in case:
        assert media['pixel_format']==case['source_pixel_format']
    if 'data_level' in case:
        call('set_media_data_level',media_id=media['id'],mode=case['data_level'])
    clip = call('append_clip', media_id=media['id'], out_frame=case['frames'])['id']
    def add(kind, **parameters):
        return call('add_fusion_node', clip_id=clip, type=kind, parameters=parameters)['id']
    def connect(node, port, target):
        call('connect_fusion_nodes', clip_id=clip, target_node_id=node, input=port, source_node_id=target)
    def background(p):
        values = {key:p['TopLeft'+key] for key in ('Red','Green','Blue','Alpha')}
        if 'Depth' in p: values['Depth'] = p['Depth']
        return add('Background', **values)
    if not graph_case:
        target = background(case['inputs'])
        if case['kind']=='merge':
            front = background(case['front_inputs']); merge = add('Merge', Blend=case['blend'])
            connect(merge,'Background',target); connect(merge,'Foreground',front); target=merge
    else:
        nodes = case['nodes']; target = background(next(n['inputs'] for n in nodes if n['class']=='Background'))
        for node in sorted((n for n in nodes if n['class']=='Transform'), key=lambda n:n['name']):
            p = node['inputs']; assert p['FilterMethod']==2 and p['FlattenTransform']==0
            transform = add('Transform', Size=p['Size'], Angle=p['Angle'], CenterX=p['Center'][0], CenterY=p['Center'][1])
            connect(transform,'Input',target); target=transform
        merges = [n for n in nodes if n['class']=='Merge']
        if merges:
            p=merges[0]['inputs']; merge=add('Merge', Blend=p['Blend'], CenterX=p['Center'][0], CenterY=p['Center'][1])
            connect(merge,'Background','MediaIn1'); connect(merge,'Foreground',target); target=merge
    connect('MediaOut1','Input',target)
    return clip


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--run-name',required=True);args=parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',args.run_name):parser.error('Invalid run name')
    reference=json.loads(FIXTURE.read_text()); work=ROOT/'workspace'/('fusion-image-precision-mcp-'+args.run_name)
    source=make_source(work)
    sources={'argb':source}
    if any(c.get('source_pixel_format')=='rgb24' for c in reference['cases']):sources['rgb24']=make_source(work,has_alpha=False)
    client=ConfiguredClient(work);results=[]
    try:
        tools=client.request('tools/list',{})['tools'];schema=next(t for t in tools if t['name']=='add_fusion_node')['inputSchema']
        assert schema['properties']['parameters']['properties']['Depth']['enum']==[0,1,2,3,4]
        for case in reference['cases']:
            assert case['native_status']['JobStatus']=='Complete'
            clip=build_case(client.tool,case,sources[case.get('source_pixel_format','argb')]); project=work/(case['name']+'.json')
            client.tool('save_project',path=str(project));client.tool('open_project',path=str(project));before=client.tool('get_state')
            for frame in (0,case['frames']-1):
                output=work/(case['name']+'-'+str(frame)+'.png')
                client.tool('render_fusion_frame',clip_id=clip,frame=frame,output=str(output))
                raw=subprocess.check_output([ffmpeg_executable(),'-v','error','-i',str(output),'-pix_fmt','rgba64le','-f','rawvideo','-'])
                digest=hashlib.sha256(raw).hexdigest()
                row={'name':case['name'],'frame':frame,'rgba16_exact':digest==case['native_rgba64le_frame0_sha256'],
                    'native_sha256':case['native_rgba64le_frame0_sha256'],'own_sha256':digest,'output':identity(output)}
                results.append(row);print(json.dumps(row),flush=True)
            assert client.tool('get_state')==before
        report={'fixture':identity(FIXTURE),'source':identity(source),'sources':{k:identity(v) for k,v in sources.items()},'driver':identity(Path(__file__)),
                'fusion':identity(ROOT/'frameforge/fusion.py'),'precision':identity(ROOT/'frameforge/fusion_precision.py'),
                'server':client.server_info,'tools':len(tools),'cases':results,'calls':client.calls,
                'scope':reference['scope'],'full_resolve_parity':False}
        (ROOT/'research'/('fusion-image-precision-mcp-'+args.run_name+'.json')).write_text(json.dumps(report,indent=2)+'\n')
        assert len(results)==2*len(reference['cases']) and all(r['rgba16_exact'] for r in results)
    finally:client.close()


if __name__=='__main__':main()
