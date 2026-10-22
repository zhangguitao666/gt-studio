"""Subtitle interchange and actual literal-text rasterization/time windows."""
import copy
from fractions import Fraction
from pathlib import Path
import subprocess
import pytest
from frameforge.engine import ffmpeg_executable
from frameforge.subtitles import (SubtitleActions, parse_srt, write_srt,
    milliseconds_to_frames, frames_to_milliseconds, validate_cues, validate_style,
    build_subtitle_filters, subtitle_migrate_validate)


def test_unicode_roundtrip_and_rational_rounding(tmp_path):
    source = tmp_path / '多语言.srt'
    source.write_text('1\n00:00:00,500 --> 00:00:01,500\n你好，世界！\nCafé \\N {literal} %{pts}\n\n2\n00:00:01,000 --> 00:00:02,000\nOverlap ✓\n', encoding='utf-8')
    cues = parse_srt(source, {'num': 24000, 'den': 1001})
    assert cues[0]['text'] == '你好，世界！\nCafé \\N {literal} %{pts}'
    assert cues[0]['start_frame'] == 12 and cues[1]['start_frame'] == 24
    exported = tmp_path / 'out.srt'
    write_srt(cues, exported, Fraction(24000,1001))
    again = parse_srt(exported, {'num': 24000, 'den': 1001})
    assert [(c['start_frame'],c['end_frame'],c['text']) for c in again] == [(c['start_frame'],c['end_frame'],c['text']) for c in cues]
    assert milliseconds_to_frames(500,1) == 1
    assert frames_to_milliseconds(1,16) == 63


@pytest.mark.parametrize('content', [
    '1\n00:00:00,000 --> 00:00:00,000\ntext',
    '1\n00:99:00,000 --> 00:00:02,000\ntext',
    '1\n00:00:00.000 --> 00:00:02,000\ntext',
    '1\n00:00:00,000 --> 00:00:00,001\ntext',
    '1\n00:00:00,000 --> 00:00:02,000\n ',
    'bad\n00:00:00,000 --> 00:00:02,000\ntext',
])
def test_malformed_srt_rejected(tmp_path, content):
    source = tmp_path / 'bad.srt'; source.write_text(content)
    with pytest.raises(ValueError): parse_srt(source,24)


def test_invalid_export_preserves_file_and_styles_reject_injection(tmp_path):
    destination = tmp_path / 'keep.srt'; destination.write_text('unchanged')
    with pytest.raises(ValueError):
        write_srt([{'id':'x','start_frame':5,'end_frame':4,'text':'bad'}],destination,24)
    assert destination.read_text()=='unchanged'
    for properties in [{'font':'Arial\nInjected'}, {'font':'Arial,0'}, {'color':'red:enable=1'}, {'position':'unknown'}, {'font_size':float('nan')}, {'outline':True}]:
        with pytest.raises(ValueError): validate_style(properties)


class Harness(SubtitleActions):
    def __init__(self,tmp_path):
        self.project={'fps':{'num':24,'den':1},'path':str(tmp_path/'project.json'),'media':[]}
        self.timeline={}
    def _require(self): return self.project
    def _timeline(self): return self.timeline


def test_actions_atomic_and_overlap_allowed(tmp_path):
    harness=Harness(tmp_path)
    first=harness.add_subtitle(1,24,'Hello')
    second=harness.add_subtitle(12,36,'Overlap')
    before=copy.deepcopy(harness.timeline)
    with pytest.raises(ValueError): harness.update_subtitle(first['id'],end_frame=0)
    assert harness.timeline==before
    harness.update_subtitle(first['id'],text='Updated\nUnicode 字幕')
    harness.set_subtitle_style({'position':'top','font_size':30})
    assert harness.export_subtitles(str(tmp_path/'export.srt'))['exported']==2
    harness.delete_subtitle(second['id'])
    source=tmp_path/'invalid.srt';source.write_text('broken')
    before=copy.deepcopy(harness.timeline)
    with pytest.raises(ValueError):harness.import_subtitles(str(source))
    assert harness.timeline==before
    with pytest.raises(ValueError):harness.export_subtitles(harness.project['path'])
    subtitle_migrate_validate({})


def test_literal_burn_in_exact_time_windows(tmp_path):
    # Filename punctuation exercises FFmpeg's two parser layers; text exercises
    # ASS/drawtext expression injection characters and multiline Unicode.
    directory=tmp_path / "text 'quoted', comma: 你好"
    text='Literal {\\pos(0,0)} \\N %{pts}\nCafé 字幕'
    cues=[{'id':'test','start_frame':6,'end_frame':12,'text':text}]
    filters=build_subtitle_filters(cues,24,640,180,directory,{'font_size':24,'position':'center','outline':0})
    assert (directory/'subtitle-0.txt').read_text()==text
    assert 'expansion=none' in filters[0]
    proc=subprocess.run([ffmpeg_executable(),'-hide_banner','-loglevel','error','-f','lavfi','-i','color=black:s=640x180:r=24:d=0.75','-vf',','.join(filters),'-pix_fmt','gray','-f','rawvideo','-'],capture_output=True)
    assert proc.returncode==0,proc.stderr.decode()
    size=640*180
    assert len(proc.stdout)==18*size
    bright=[sum(value>100 for value in proc.stdout[i*size:(i+1)*size]) for i in range(18)]
    assert bright[:6]==[0]*6
    assert all(n>200 for n in bright[6:12])
    assert bright[12:]==[0]*6
    # Exact textfile content proves no rewriting into ASS escape glyphs; changing
    # an apparent override produces actual pixels rather than hiding all text.
    assert len(set(bright[6:12]))==1


@pytest.mark.parametrize('with_source', [False, True])
def test_engine_subtitle_tail_and_sidecar_do_not_add_undo(tmp_path, with_source):
    from frameforge.engine import Engine
    engine=Engine(tmp_path/'workspace')
    engine.dispatch('create_project',{'name':'Subtitle tail','width':320,'height':120,'fps':24})
    if with_source:
        source=tmp_path/'short-black.mp4'
        proc=subprocess.run([ffmpeg_executable(),'-v','error','-f','lavfi','-i','color=black:s=320x120:r=24:d=0.25','-c:v','libx264',str(source)],capture_output=True)
        assert proc.returncode==0,proc.stderr.decode()
        media=engine.dispatch('import_media',{'path':str(source)})
        engine.dispatch('append_clip',{'media_id':media['id']})
    # Entirely subtitle-only timelines render black/silent media to the cue end;
    # cue begins after a blank lead-in and requires no artificial source clip.
    cue=engine.dispatch('add_subtitle',{'start_frame':12,'end_frame':24,'text':'Literal {\\alpha&HFF&} \\N %{pts}'})
    engine.dispatch('set_subtitle_style',{'properties':{'font_size':20,'position':'center','outline':0}})
    before=engine.get_state()
    history=copy.deepcopy(engine._undo)
    for filename in ('first.srt','second.srt'):
        result=engine.dispatch('export_subtitles',{'path':str(tmp_path/filename)})
        assert result['exported']==1
        assert engine.get_state()==before
        assert engine._undo==history
    result=engine.dispatch('render',{'output':str(tmp_path/'subtitles.mp4')})
    assert result['duration_frames']==24
    assert engine._undo==history
    decoded=subprocess.run([ffmpeg_executable(),'-v','error','-i',result['output'],'-pix_fmt','gray','-f','rawvideo','-'],capture_output=True)
    assert decoded.returncode==0,decoded.stderr.decode()
    size=320*120
    assert len(decoded.stdout)==24*size
    counts=[sum(v>100 for v in decoded.stdout[i*size:(i+1)*size]) for i in range(24)]
    assert counts[:12]==[0]*12
    assert all(value>100 for value in counts[12:])
    # Render also stays side-effect free, while undo removes the style edit.
    engine.dispatch('undo')
    assert engine._timeline()['subtitles'][0]['id']==cue['id']
    assert engine._timeline()['subtitle_style']['font_size']!=20
