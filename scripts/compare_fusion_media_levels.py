"""Replay all captured source-level cases through the configured MCP launcher."""
from collections import Counter
import argparse
import json
import operator
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.verify_fusion_nodes import ConfiguredClient,decode,identity


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-name',required=True);args=parser.parse_args()
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',args.run_name):parser.error('Invalid run name')
    reference=ROOT/'research/fusion-media-levels-runtime-all.json'
    rows=[r['case'] for r in json.loads(reference.read_text())['records'] if r['case'].get('after',{}).get('fusion_media_levels')]
    assert len(rows)==15 and all(r['completed'] for r in rows)
    workspace=ROOT/'workspace'/('fusion-media-levels-comparison-'+args.run_name);workspace.mkdir(exist_ok=True)
    client=ConfiguredClient(workspace);observations=[]
    try:
        tools=client.request('tools/list',{})['tools'];assert 'set_media_data_level' in {t['name'] for t in tools}
        for row in rows:
            a=row['after'];label=a['level'].lower()+'_b'+str(a['blend']).replace('.','p')
            client.tool('create_project',name='Measured MediaIn '+label,width=640,height=360,fps=24)
            media=client.tool('import_media',path=a['source']);client.tool('set_media_data_level',media_id=media['id'],mode=a['level'])
            clip=client.tool('append_clip',media_id=media['id'],out_frame=12)['id']
            def add(kind,**parameters):return client.tool('add_fusion_node',clip_id=clip,type=kind,parameters=parameters)['id']
            def connect(target,port,source):client.tool('connect_fusion_nodes',clip_id=clip,target_node_id=target,input=port,source_node_id=source)
            blue=add('Background',Blue=1,Alpha=a['alpha']);merge=add('Merge',Blend=a['blend'])
            connect(merge,'Background','MediaIn1');connect(merge,'Foreground',blue);connect('MediaOut1','Input',merge)
            project=workspace/(label+'.json');client.tool('save_project',path=str(project));client.tool('open_project',path=str(project))
            assert next(m for m in client.tool('get_state')['media'] if m['id']==media['id'])['data_level']==a['level']
            output=workspace/(label+'.mov');client.tool('render',output=str(output))
            native=ROOT/'workspace/fusion-level-native'/(row['timeline']+'.mov');original,own=decode(native),decode(output);assert len(original)==len(own)==12*640*360*3
            deltas=Counter(map(operator.sub,own,original));count=len(own);at=(180*640+320)*3
            result={'level':a['level'],'blend':a['blend'],'native':identity(native),'independent':identity(output),'project':identity(project),'frames':12,'rgb_mae':sum(abs(d)*n for d,n in deltas.items())/count,'rgb_mse':sum(d*d*n for d,n in deltas.items())/count,'rgb_max_abs':max(map(abs,deltas)),'native_center':list(original[at:at+3]),'independent_center':list(own[at:at+3]),'rgb_exact':original==own}
            observations.append(result);print(json.dumps({k:result[k] for k in ('level','blend','rgb_mae','rgb_mse','native_center','independent_center')},ensure_ascii=False),flush=True)
        report={'status':'measured_15_native_cases_not_general_equivalence','reference':identity(reference),'driver':identity(Path(__file__)),'production':[identity(ROOT/p) for p in ('frameforge/engine.py','frameforge/fusion.py','frameforge/media_levels.py')],'public_tools':len(tools),'server':client.server_info,'cases':observations,'calls':client.calls,'full_resolve_parity':False,'limitations':['Only static red RGB24 QTRLE with blue generator, captured level settings and ProRes exports.','Native export RGB is not an internal float buffer. Other codecs, HDR, color-management and interpolation parity remain unverified.']}
        target=ROOT/'research'/('fusion-media-levels-comparison-'+args.run_name+'.json');target.write_text(json.dumps(report,ensure_ascii=False,indent=2));print(target)
        assert len(observations)==15 and all(c['rgb_exact'] for c in observations), 'Captured native source-level RGB sequences differ'
    finally:client.close()


if __name__=='__main__':main()
