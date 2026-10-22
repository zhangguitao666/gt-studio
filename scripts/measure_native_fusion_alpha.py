"""Record actual decoded RGBA and frame/packet identities for native alpha jobs."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from frameforge.engine import ffmpeg_executable
from scripts.verify_fusion_nodes import identity


def run(path, args):
    return subprocess.run([ffmpeg_executable(),'-v','error','-i',str(path),*args,'-'],capture_output=True,check=True).stdout


def main():
    source=ROOT/'research/fusion-native-alpha-runtime.json'
    records=json.loads(source.read_text())['records'];assert len(records)==12
    observations=[]
    for record in records:
        row=record['case'];after=row['after'];assert row['completed']
        path=Path(after['settings']['TargetDir'])/(after['settings']['CustomName']+'.mov')
        rgba=run(path,['-frames:v','1','-pix_fmt','rgba64le','-f','rawvideo'])
        assert len(rgba)==640*360*8
        hashes=run(path,['-map','0:v','-an','-pix_fmt','rgba64le','-f','framemd5']).decode()
        frames=[line for line in hashes.splitlines() if line and not line.startswith('#')]
        assert len(frames)==48
        packets=run(path,['-map','0:v','-c','copy','-f','data'])
        samples=[]
        for x,y in [(160,90),(480,90),(320,180)]:
            at=(y*640+x)*8;samples.append({'xy':[x,y],'rgba16':list(struct.unpack('<4H',rgba[at:at+8]))})
        observations.append({'timeline':row['timeline'],'requested_alpha_mode':after['mode'],'job_id':after['job_id'],'artifact':identity(path),'samples':samples,
                             'first_decoded_rgba16_sha256':hashlib.sha256(rgba).hexdigest(),
                             'video_packet_sha256':hashlib.sha256(packets).hexdigest(),'frame_count':len(frames),'frame_md5':hashes})
    pairs=[]
    for timeline in sorted({r['timeline'] for r in observations}):
        a,b=sorted([r for r in observations if r['timeline']==timeline],key=lambda r:r['requested_alpha_mode'])
        pairs.append({'timeline':timeline,'decoded_rgba_frames_equal':a['frame_md5']==b['frame_md5'],
                      'video_packets_equal':a['video_packet_sha256']==b['video_packet_sha256']})
    report={'status':'measured_twelve_native_prores4444_alpha_exports','reference':identity(source),'cases':observations,'mode_pairs':pairs,
            'decoder':identity(Path(ffmpeg_executable())), 'driver':identity(Path(__file__).resolve()),
            'limitations':['Numeric AlphaMode requests are retained and job metadata read back separately; equal FFmpeg output is not proof of all native alpha-mode semantics.',
                           'RGBA values are FFmpeg-decoded export samples, not a direct read of Fusion internal image buffers.',
                           'No independent alpha export or native Fusion parity is claimed.'],'full_resolve_parity':False}
    target=ROOT/'research/fusion-native-alpha-measurements.json';target.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'report':str(target),'cases':len(observations),'pairs':pairs},ensure_ascii=False))


if __name__=='__main__':main()
