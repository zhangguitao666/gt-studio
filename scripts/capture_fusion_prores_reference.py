"""Preserve owned native color-reference packets without re-encoding pixels."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zlib

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from frameforge.engine import ffmpeg_executable


def capture(manifest,output):
    if output.exists():
        raise ValueError('Choose a new output; captured references are not overwritten')
    original=json.loads((ROOT/'tests/fixtures/fusion-media-levels.json').read_text())
    measured=json.loads(manifest.read_text())
    ffmpeg=ffmpeg_executable()
    carriers,cases={},{}

    def packet_hashes(path=None,data=None):
        result=subprocess.run([ffmpeg,'-v','error','-i',str(path) if path else 'pipe:0',
            '-map','0:v:0','-c:v','copy','-f','framehash','-hash','sha256','pipe:1'],
            input=data,capture_output=True,check=True).stdout.decode()
        return [line.split(',')[-1].strip() for line in result.splitlines() if line and not line.startswith('#')]

    for case in original['cases']:
        row=next(c for c in measured['cases'] if c['level']==case['mode'] and c['blend']==case['blend'])
        path=Path(row['native']['path']).resolve()
        assert path.is_relative_to(ROOT/'workspace/fusion-level-native')
        assert hashlib.sha256(path.read_bytes()).hexdigest()==case['native_file_sha256']
        data=subprocess.check_output([ffmpeg,'-v','error','-i',str(path),'-map','0:v:0',
            '-c:v','copy','-map_metadata','-1','-map_metadata:s:v','-1','-map_chapters','-1',
            '-fflags','+bitexact','-f','nut','pipe:1'])
        packets=packet_hashes(path=path)
        assert len(packets)==12 and packets==packet_hashes(data=data)
        rgb=subprocess.run([ffmpeg,'-v','error','-i','pipe:0','-an','-pix_fmt','rgb24',
            '-f','rawvideo','pipe:1'],input=data,capture_output=True,check=True).stdout
        assert len(rgb)==12*640*360*3
        assert hashlib.sha256(rgb).hexdigest()==case['native_decoded_sha256']
        identity=hashlib.sha256(data).hexdigest()
        carriers[identity]={'sha256':identity,'bytes':len(data),'compression':'zlib',
            'base64':base64.b64encode(zlib.compress(data,9)).decode(),'packet_sha256':packets}
        cases[case['id']]={'carrier_sha256':identity,'original_mov_sha256':case['native_file_sha256'],
            'acquisition_rgb_sha256':case['native_decoded_sha256'],'frames':12,'width':640,'height':360}
    result={'schema_version':1,
        'scope':'Video-only metadata-stripped NUT stream copies of owned synthetic native ProRes exports; encoded packets are unchanged. Native reference and product output must be decoded with the same backend. Historical acquisition RGB SHA remains in the original fixture.',
        'native_version':original['native_version'],
        'source':'Owned constant RGB24 red source and blue generator; no third-party footage or app/database files',
        'acquisition_decoder':subprocess.check_output([ffmpeg,'-version'],text=True).splitlines()[0],
        'carriers':carriers,'cases':cases,'full_resolve_parity':False}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2)+'\n')
    return {'cases':len(cases),'unique_carriers':len(carriers),'bytes':output.stat().st_size}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,default=ROOT/'research/fusion-media-levels-comparison-unorm-yuv.json')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(capture(args.manifest,args.output)))


if __name__=='__main__':main()
