"""Comparator verification uses synthetic fixtures, not native parity claims."""
import array
import json
from pathlib import Path
import shutil
import subprocess
import pytest
from scripts.compare_native_retime_media import (MCPProjectClient, audio_metrics, compare_paths, count_original_frames, decode_video, estimate_source_sequence, frame_feature, image_metrics, load_cases, recreate_case)
from frameforge.engine import ffmpeg_executable


def test_unthresholded_image_errors_and_missing_frames():
    exact = bytes([0, 10, 20])
    shifted = bytes([10, 20, 30])
    metrics = image_metrics([exact, exact], [shifted])
    assert metrics['mae_rgb_0_255'] == 10
    assert metrics['mse_rgb_0_255_squared'] == 100
    assert metrics['exact_channel_fraction'] == 0
    assert metrics['unmatched_native_frames'] == 1
    assert not metrics['frame_count_equal']
    assert not metrics['all_decoded_frames_byte_equal']
    same = image_metrics([exact], [exact])
    assert same['all_decoded_frames_byte_equal']
    assert same['mae_rgb_0_255'] == 0


def test_source_identity_is_an_estimate_with_ambiguity_retained():
    low = bytes([20,0,0])*(320*180)
    high = bytes([200,0,0])*(320*180)
    features = [frame_feature(low),frame_feature(high)]
    result = estimate_source_sequence([high,low,high],features)
    assert result['estimated_sequence'] == [1,0,1]
    assert result['frames'][0]['best_feature_mse'] == 0
    assert result['frames'][0]['second_best_feature_mse'] > 0
    ambiguous = estimate_source_sequence([low],[features[0],features[0]])
    assert ambiguous['frames'][0]['separation_mse'] == 0


def test_audio_correlation_does_not_hide_amplitude_or_length_difference():
    def audio(samples):
        return {'present':True,'samples':array.array('h',samples),'sample_rate':48000,'channels':2}
    result = audio_metrics(audio([1,2,3,4,5,6,7,8]),audio([2,4,6,8,10,12]))
    assert not result['sample_frame_count_equal']
    assert result['pearson_correlation_aligned'] == pytest.approx(1)
    assert result['mae_pcm16'] > 0
    assert not result['aligned_pcm_byte_equal']
    assert result['native']['sample_frames'] == 4
    assert result['independent']['sample_frames'] == 3


def test_real_mcp_reconstruction_and_identical_copy_comparison(tmp_path):
    source = tmp_path/'motion.mp4'
    created = subprocess.run([ffmpeg_executable(),'-v','error','-y','-f','lavfi','-i','testsrc2=s=640x360:r=24:d=3','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=3','-shortest','-c:v','libx264','-c:a','aac',str(source)],capture_output=True)
    assert created.returncode == 0, created.stderr.decode()
    case = next(item['case'] for item in load_cases() if item['case']['percentage']==100)
    client = MCPProjectClient(tmp_path/'workspace')
    try:
        independent, recreation = recreate_case(client,case,source,tmp_path/'renders',width=640,height=360)
    finally:
        client.close()
    assert independent.is_file()
    assert recreation['render_geometry'] == {'width':640,'height':360,'fps':24}
    project = json.loads(Path(recreation['project']['path']).read_text())
    assert (project['width'],project['height']) == (640,360)
    assert any(call['action']=='render' and not call['is_error'] for call in recreation['mcp_calls'])
    assert count_original_frames(independent) == 94
    reference_copy = tmp_path/'identical-fixture.mov'
    shutil.copyfile(independent,reference_copy)
    decoded_source = decode_video(source)
    assert len(decoded_source['frames']) == count_original_frames(source) == 72
    features = [frame_feature(frame) for frame in decoded_source['frames']]
    result = compare_paths(reference_copy,independent,features)
    assert result['images']['all_decoded_frames_byte_equal']
    assert result['images']['mae_rgb_0_255'] == 0
    assert result['audio']['aligned_pcm_byte_equal']
    assert result['audio']['native']['sample_frames'] == 188000
    assert result['native_source_identity_estimate']['estimated_sequence'] == result['independent_source_identity_estimate']['estimated_sequence']
    bounded = decode_video(independent,max_frames=2)
    assert not bounded['complete']
    assert bounded['observed_frame_count'] == 3
    assert len(bounded['frames']) == 2
