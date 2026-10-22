"""Bind before/after native precision measurements and verify audio invariance."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.verify_reference_transitions import identity
from scripts.verify_linked_split import decode


def main():
    before_path=ROOT/'research/native-media-comparison.json';after_path=ROOT/'research/native-media-comparison-precision.json'
    before=json.loads(before_path.read_text());after=json.loads(after_path.read_text())
    assert after['status']=='measured_all_cases' and before['source']['sha256']==after['source']['sha256']
    assert before['normalization']==after['normalization'] or all(before['normalization'][key]==after['normalization'][key] for key in ('width','height','fps','scale_flags','audio_sample_rate','audio_channels'))
    assert before['ffmpeg']['sha256']==after['ffmpeg']['sha256']
    original={c['native_timeline']:c for c in before['cases']};cases=[]
    for case in after['cases']:
        previous=original[case['native_timeline']]
        assert case['native_export']['sha256']==previous['native_export']['sha256']
        for record in (case['native_export'],case['independent_export'],previous['independent_export']):
            assert identity(Path(record['path']))['sha256']==record['sha256']
        old,new=previous['comparison']['images'],case['comparison']['images']
        assert new['frame_count_equal'] and new['mae_rgb_0_255']<old['mae_rgb_0_255'] and new['mse_rgb_0_255_squared']<old['mse_rgb_0_255_squared']
        audio_equal=decode(Path(previous['independent_export']['path']),True)==decode(Path(case['independent_export']['path']),True)
        assert audio_equal
        native=case['comparison']['native_source_identity_estimate']['estimated_sequence']
        independent=case['comparison']['independent_source_identity_estimate']['estimated_sequence']
        assert native==independent
        cases.append({'native_timeline':case['native_timeline'],'old_mae':old['mae_rgb_0_255'],'new_mae':new['mae_rgb_0_255'],
                      'old_mse':old['mse_rgb_0_255_squared'],'new_mse':new['mse_rgb_0_255_squared'],
                      'mse_reduction_percent':100*(1-new['mse_rgb_0_255_squared']/old['mse_rgb_0_255_squared']),
                      'audio_pcm_unchanged':audio_equal,'heuristic_source_sequence_matches':True,'frames':new['native_frame_count'],
                      'native_export':case['native_export'],'old_export':previous['independent_export'],'new_export':case['independent_export']})
    result={'status':'passed_measured_native_error_reduction','before':identity(before_path),'after':identity(after_path),'cases':cases,
            'mse_reduction_percent_range':[min(c['mse_reduction_percent'] for c in cases),max(c['mse_reduction_percent'] for c in cases)],
            'new_mae_range':[min(c['new_mae'] for c in cases),max(c['new_mae'] for c in cases)],
            'limitations':['Ten retained8-bit-source native retime/freeze fixtures normalized320x180RGB24; not universal color/HDR proof.',
                           'Nonzero pixel and original audio residuals remain. Source sequence matching is heuristic.',
                           'The corpus contains no transparent transition; alpha and high-bit-depth tests are separate independent checks.'],
            'full_resolve_parity':False}
    (ROOT/'research/precision-improvement-verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'status':result['status'],'cases':len(cases),'mse_reduction_percent_range':result['mse_reduction_percent_range']}))

if __name__=='__main__':main()
