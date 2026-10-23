"""UI-to-service checks exercise the same state used by MCP clients."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import threading
import time

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox
from frameforge.service import Controller, EditorServer
from frameforge.client import rpc
from frameforge.ui import EditorWindow, STYLE, clips_of, fps_of, timeline_of


@pytest.fixture(autouse=True)
def report_unexpected_modal_errors(monkeypatch):
    errors = []
    def capture(parent, title, message, *args, **kwargs):
        errors.append(str(message))
        return QMessageBox.StandardButton.Ok
    monkeypatch.setattr(QMessageBox, 'critical', capture)
    yield
    assert not errors, 'Unexpected editor error dialog:\n' + '\n'.join(errors)


def wait_for(app, predicate, seconds=4):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(.01)
    assert predicate(), 'UI did not synchronize with service'


def test_native_editor_roundtrip(tmp_path):
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    controller = Controller(tmp_path)
    server = EditorServer(('127.0.0.1', 0), controller)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    window = EditorWindow(url)
    errors = []
    window.client.failed.disconnect(window.show_error)
    window.client.failed.connect(errors.append)
    try:
        window.rpc('create_project', {'name': 'Native shared project', 'fps': 29.97})
        wait_for(app, lambda: window.state and window.state['name'] == 'Native shared project')
        assert window.windowTitle() == 'Native shared project — GT Studio'
        assert window.findChild(QLabel, 'brand').text().strip() == 'GT STUDIO'
        assert abs(fps_of(window.state) - 29.97) < .001
        assert len(timeline_of(window.state)['tracks']) == 2
        rpc(url, 'set_page', {'page': 'Color'})
        rpc(url, 'set_playhead', {'frame': 37})
        window.client.poll_transport()
        wait_for(app, lambda: window.current_page == 'Color' and window.current_frame == 37)
        wait_for(app, lambda: controller.transport()['observed']['frame'] == 37)
        assert controller.transport()['ui_connected']
        window.seek_frame(55)
        rpc(url, 'set_page', {'page': 'Deliver'})
        window.client.poll_transport()
        wait_for(app, lambda: window.current_page == 'Deliver')
        assert window.current_frame == 55  # A page request must not replay stale frame37.
        # An external control mutation becomes visible in the desktop poll.
        controller.dispatch('add_marker', {'frame': 30, 'label': 'MCP marker'})
        window.client.poll()
        wait_for(app, lambda: len(timeline_of(window.state)['markers']) == 1)
        window.rpc('add_track', {'kind': 'audio'})
        wait_for(app, lambda: len(timeline_of(window.state)['tracks']) == 3)
        window.set_page('Photo')
        assert 'not implemented' in window.notice.text()
        window.set_page('Fusion')
        assert 'MediaIn' in window.notice.text()
        assert window.lower_pages.currentWidget() is window.fusion_panel
        window.show()
        app.processEvents()
        assert not window.grab().isNull()
        assert not errors
    finally:
        window.poll_timer.stop()
        window.transport_timer.stop()
        window.render_timer.stop()
        window.close()
        window.deleteLater()
        app.processEvents()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_rendered_timeline_preview_and_invalidation(tmp_path):
    import subprocess
    from pathlib import Path
    from frameforge.engine import ffmpeg_executable
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    source = tmp_path / 'source.mp4'
    subprocess.run([ffmpeg_executable(), '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=orange:s=160x90:r=24:d=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(source)], check=True)
    controller = Controller(tmp_path)
    controller.dispatch('create_project', {'name': 'Timeline preview', 'width': 160, 'height': 90})
    media = controller.dispatch('import_media', {'path': str(source)})
    clip = controller.dispatch('append_clip', {'media_id': media['id'], 'start_frame': 24})
    server = EditorServer(('127.0.0.1', 0), controller)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    window = EditorWindow(url)
    errors = []
    window.client.failed.disconnect(window.show_error)
    window.client.failed.connect(errors.append)
    preview_path = None
    try:
        wait_for(app, lambda: window.state is not None)
        window.select_clip(clip['id'])
        window.properties['opacity'].setValue(.8)
        window.properties['scale'].setValue(.9)
        window.properties['x'].setValue(5)
        window.properties['fade_in_frames'].setValue(4)
        window.properties['fade_out_frames'].setValue(4)
        window.apply_properties()
        wait_for(app, lambda: clips_of(window.state)[0]['properties']['fade_in_frames'] == 4)
        assert isinstance(clips_of(window.state)[0]['properties']['fade_out_frames'], int)
        assert clips_of(window.state)[0]['properties']['opacity'] == .8
        window.show()
        app.processEvents()
        rpc(url, 'set_playhead', {'frame': 12})
        rpc(url, 'set_playback', {'state': 'playing'})
        window.client.poll_transport()
        wait_for(app, lambda: window.playback_mode == 'timeline', seconds=15)
        wait_for(app, lambda: controller.transport()['observed']['playback'] == 'playing')
        wait_for(app, lambda: window.video.videoSink().videoFrame().isValid())
        assert window.player.duration() >= 1900
        rpc(url, 'set_playback', {'state': 'paused'})
        window.client.poll_transport()
        wait_for(app, lambda: controller.transport()['observed']['playback'] == 'paused')
        preview_path = Path(window.preview_path)
        assert preview_path.stat().st_size > 1000
        window.seek_frame(12)  # The rendered preview preserves the gap before the source.
        wait_for(app, lambda: abs(window.player.position() - 500) < 50)
        assert window.current_frame == 12
        assert window.preview_signature == window.state_signature
        window.show()
        window.timeline.scale = 8
        window.timeline.set_state(window.state)
        window.seek_frame(36)
        wait_for(app, lambda: abs(window.player.position() - 1500) < 50)
        app.processEvents()
        screenshot = Path(__file__).resolve().parent.parent / 'research' / 'ui-preview.png'
        screenshot.parent.mkdir(exist_ok=True)
        assert window.grab().save(str(screenshot))
        controller.dispatch('set_clip_properties', {'clip_id': clip['id'], 'properties': {'exposure': 1}})
        window.client.poll()
        wait_for(app, lambda: window.preview_signature is None)
        assert window.playback_mode == 'source'
        assert 'Refresh' in window.preview_button.text()
        window.ripple_delete()
        wait_for(app, lambda: not clips_of(window.state))
        assert window.selection is None
        assert not errors
    finally:
        window.poll_timer.stop()
        window.transport_timer.stop()
        window.render_timer.stop()
        window.player.stop()
        window.close()
        window.deleteLater()
        app.processEvents()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        if preview_path:
            preview_path.unlink(missing_ok=True)


def test_retime_inspector_uses_rendered_timeline_and_duration(tmp_path):
    import subprocess
    from pathlib import Path
    from frameforge.engine import ffmpeg_executable
    from frameforge.ui import duration, requires_timeline_preview
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    source = tmp_path / 'retime-source.mp4'
    subprocess.run([ffmpeg_executable(), '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=160x90:r=24:d=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(source)], check=True)
    controller = Controller(tmp_path)
    controller.dispatch('create_project', {'name': 'Retime UI', 'width': 160, 'height': 90})
    media = controller.dispatch('import_media', {'path': str(source)})
    clip = controller.dispatch('append_clip', {'media_id': media['id']})
    server = EditorServer(('127.0.0.1', 0), controller)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    window = EditorWindow(url)
    errors = []
    window.client.failed.disconnect(window.show_error)
    window.client.failed.connect(errors.append)
    preview_paths = []
    try:
        window.show()
        wait_for(app, lambda: window.state is not None)
        window.select_clip(clip['id'])
        window.pitch_correction.setChecked(False)
        window.ripple_speed.setChecked(True)
        for percentage, expected in [(50, 48), (-200, 12), (0, 12)]:
            if percentage == 0:
                window.seek_frame(0)
            window.clip_speed.setValue(percentage)
            window.apply_speed()
            wait_for(app, lambda: clips_of(window.state)[0].get('speed_percentage') == percentage)
            current = clips_of(window.state)[0]
            assert current['pitch_correction'] is False
            assert duration(current) == expected
            assert current['out_frame'] - current['in_frame'] == (1 if percentage == 0 else 24)
            assert requires_timeline_preview(current)
            # Selection/seek must queue a real render, never reverse-play the source.
            wait_for(app, lambda: window.playback_mode == 'timeline' and window.preview_signature == window.state_signature, seconds=15)
            preview_paths.append(Path(window.preview_path))
            window.timeline.repaint()
            app.processEvents()
            rect = next(rect for rect, item in window.timeline.hitboxes if item['id'] == clip['id'])
            assert rect.width() == expected * window.timeline.scale
            window.seek_frame(3)
            wait_for(app, lambda: abs(window.player.position() - 125) < 40)
        # MCP/native transport uses rendered output even for a freeze clip.
        rpc(url, 'set_playback', {'state': 'playing'})
        window.client.poll_transport()
        wait_for(app, lambda: controller.transport()['observed']['playback'] == 'playing')
        wait_for(app, lambda: window.video.videoSink().videoFrame().isValid())
        rpc(url, 'set_playback', {'state': 'paused'})
        window.client.poll_transport()
        wait_for(app, lambda: controller.transport()['observed']['playback'] == 'paused')
        assert not errors
    finally:
        window.poll_timer.stop()
        window.transport_timer.stop()
        window.render_timer.stop()
        window.player.stop()
        window.close()
        window.deleteLater()
        app.processEvents()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        for path in preview_paths:
            path.unlink(missing_ok=True)


def test_subtitle_panel_edits_srt_and_rendered_tail(tmp_path, monkeypatch):
    from pathlib import Path
    from frameforge.ui import Timeline
    from PySide6.QtWidgets import QFileDialog
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    controller = Controller(tmp_path)
    controller.dispatch('create_project', {'name': 'Subtitle UI', 'width': 320, 'height': 180})
    server = EditorServer(('127.0.0.1', 0), controller)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    window = EditorWindow(url)
    errors = []
    window.client.failed.disconnect(window.show_error)
    window.client.failed.connect(errors.append)
    preview_path = None
    try:
        window.show()
        wait_for(app, lambda: window.state is not None)
        window.pool_tabs.setCurrentIndex(1)
        window.subtitle_start.setValue(0)
        window.subtitle_end.setValue(24)
        window.subtitle_text.setPlainText('First subtitle')
        window.add_subtitle()
        wait_for(app, lambda: len(timeline_of(window.state)['subtitles']) == 1)
        cue_id = timeline_of(window.state)['subtitles'][0]['id']
        assert window.subtitle_id == cue_id
        window.subtitle_end.setValue(48)
        window.subtitle_text.setPlainText('Edited subtitle\nSecond line')
        window.update_subtitle()
        wait_for(app, lambda: timeline_of(window.state)['subtitles'][0]['end_frame'] == 48)
        assert window.subtitle_list.item(0).text().endswith('Edited subtitle\nSecond line')
        imported = tmp_path / 'tail.srt'
        imported.write_text('1\n00:00:40,000 --> 00:00:41,000\nTail cue\n', encoding='utf-8')
        monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args, **kwargs: (str(imported), 'SubRip subtitles (*.srt)'))
        window.import_subtitles()
        wait_for(app, lambda: len(timeline_of(window.state)['subtitles']) == 2)
        window.subtitle_style_numbers['font_size'].setValue(18)
        window.subtitle_style_numbers['margin_vertical'].setValue(10)
        window.subtitle_color.setText('#FFD040')
        window.subtitle_position.setCurrentText('center')
        window.apply_subtitle_style()
        wait_for(app, lambda: timeline_of(window.state)['subtitle_style']['font_size'] == 18)
        assert timeline_of(window.state)['subtitle_style']['position'] == 'center'
        exported = tmp_path / 'captions.srt'
        monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args, **kwargs: (str(exported), 'SubRip subtitles (*.srt)'))
        window.export_subtitles()
        wait_for(app, exported.exists)
        assert 'Tail cue' in exported.read_text(encoding='utf-8')
        window.timeline.repaint()
        app.processEvents()
        assert len(window.timeline.subtitle_hitboxes) == 2
        assert window.timeline.minimumWidth() >= 984 * window.timeline.scale + Timeline.HEADER + 120
        window.seek_frame(12)
        window.build_preview()  # Subtitle-only timelines are renderable.
        wait_for(app, lambda: window.playback_mode == 'timeline', seconds=20)
        preview_path = Path(window.preview_path)
        rpc(url, 'set_playback', {'state': 'playing'})
        window.client.poll_transport()
        wait_for(app, lambda: window.video.videoSink().videoFrame().isValid())
        assert window.player.duration() >= 41000
        rpc(url, 'set_playback', {'state': 'paused'})
        window.client.poll_transport()
        wait_for(app, lambda: controller.transport()['observed']['playback'] == 'paused')
        window.grab().save(str(Path(__file__).resolve().parent.parent / 'research' / 'ui-preview.png'))
        window.select_subtitle(cue_id, seek=False)
        window.delete_subtitle()
        wait_for(app, lambda: len(timeline_of(window.state)['subtitles']) == 1)
        assert timeline_of(window.state)['subtitles'][0]['text'] == 'Tail cue'
        assert not errors
    finally:
        window.poll_timer.stop()
        window.transport_timer.stop()
        window.render_timer.stop()
        window.player.stop()
        window.close()
        window.deleteLater()
        app.processEvents()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        if preview_path:
            preview_path.unlink(missing_ok=True)


def test_rapid_transport_retime_subtitle_submits_one_preview(tmp_path):
    """A seek and play in one transport batch must share the in-flight submission."""
    import subprocess
    from pathlib import Path
    from PySide6.QtMultimedia import QMediaPlayer
    from frameforge.engine import ffmpeg_executable
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    source = tmp_path / 'rapid-control.mp4'
    subprocess.run([ffmpeg_executable(), '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=160x90:r=24:d=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(source)], check=True)
    controller = Controller(tmp_path)
    controller.dispatch('create_project', {'name': 'Rapid native control', 'width': 160, 'height': 90})
    media = controller.dispatch('import_media', {'path': str(source)})
    clips = [controller.dispatch('append_clip', {'media_id': media['id']}) for _ in range(4)]
    controller.dispatch('set_clip_speed', {'clip_id': clips[0]['id'], 'percentage': 50, 'ripple': True})
    controller.dispatch('set_clip_speed', {'clip_id': clips[1]['id'], 'percentage': -100})
    controller.dispatch('set_clip_speed', {'clip_id': clips[2]['id'], 'percentage': 0})
    controller.dispatch('add_subtitle', {'start_frame': 0, 'end_frame': 120, 'text': 'Preview race regression'})
    controller.dispatch('set_subtitle_style', {'properties': {'font_size': 12}})
    server = EditorServer(('127.0.0.1', 0), controller)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    window = EditorWindow(url)
    window.poll_timer.stop()
    errors = []
    window.client.failed.disconnect(window.show_error)
    window.client.failed.connect(errors.append)
    try:
        window.show()
        wait_for(app, lambda: window.state is not None)
        assert window.selection is None
        assert not window.preview_path
        rpc(url, 'set_page', {'page': 'Color'})
        rpc(url, 'set_playhead', {'frame': 24})
        rpc(url, 'set_playback', {'state': 'playing'})
        window.client.poll_transport()
        wait_for(app, lambda: controller.jobs and all(job['status'] in ('completed', 'failed') for job in controller.jobs.values()), seconds=15)
        assert len(controller.jobs) == 1
        wait_for(app, lambda: controller.transport()['observed']['playback'] == 'playing')
        wait_for(app, lambda: window.video.videoSink().videoFrame().isValid())
        observed = controller.transport()['observed']
        assert observed['page'] == 'Color'
        assert observed['frame'] >= 24
        assert observed['applied_revision'] == 3
        assert controller.transport()['ui_connected']
        # Even replacing/reactivating an already valid preview preserves play intent.
        window.activate_preview(window.preview_path)
        wait_for(app, lambda: window.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
        assert not errors
    finally:
        window.poll_timer.stop()
        window.transport_timer.stop()
        window.render_timer.stop()
        window.player.stop()
        window.close()
        window.deleteLater()
        app.processEvents()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        for job in controller.jobs.values():
            Path(job['output']).unlink(missing_ok=True)


def test_failed_preview_submission_releases_latch(tmp_path, monkeypatch):
    from pathlib import Path
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path)
    controller.dispatch('create_project', {'name': 'Preview retry', 'width': 160, 'height': 90})
    controller.dispatch('add_subtitle', {'start_frame': 0, 'end_frame': 48, 'text': 'Retry preview'})
    original_dispatch = controller.dispatch
    reject = {'once': True}
    def reject_once(action, params):
        if action == 'submit_render' and reject['once']:
            reject['once'] = False
            raise ValueError('Temporary preview submission failure')
        return original_dispatch(action, params)
    monkeypatch.setattr(controller, 'dispatch', reject_once)
    server = EditorServer(('127.0.0.1', 0), controller)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    window = EditorWindow(f'http://127.0.0.1:{server.server_port}')
    errors = []
    window.client.failed.disconnect(window.show_error)
    window.client.failed.connect(errors.append)
    try:
        wait_for(app, lambda: window.state is not None)
        window.build_preview()
        wait_for(app, lambda: bool(errors))
        assert not window.preview_submitting
        assert window.preview_button.isEnabled()
        assert not controller.jobs
        window.build_preview()
        wait_for(app, lambda: window.playback_mode == 'timeline', seconds=15)
        assert not window.preview_submitting
        assert len(controller.jobs) == 1
    finally:
        window.poll_timer.stop()
        window.transport_timer.stop()
        window.render_timer.stop()
        window.player.stop()
        window.close()
        window.deleteLater()
        app.processEvents()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        for job in controller.jobs.values():
            Path(job['output']).unlink(missing_ok=True)


def test_freeze_at_playhead_selects_new_tail_and_preserves_following_clip(tmp_path, monkeypatch):
    import subprocess
    from pathlib import Path
    from frameforge.engine import ffmpeg_executable
    from frameforge.ui import duration
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path)
    source = tmp_path / 'freeze-ui.mp4'
    subprocess.run([ffmpeg_executable(), '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=160x90:r=24:d=2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(source)], check=True)
    controller.dispatch('create_project', {'name': 'Freeze at playhead', 'width': 160, 'height': 90})
    media = controller.dispatch('import_media', {'path': str(source)})
    original = controller.dispatch('append_clip', {'media_id': media['id'], 'out_frame': 47})
    following = controller.dispatch('append_clip', {'media_id': media['id'], 'out_frame': 24})
    actual_dispatch = controller.dispatch
    speed_requests = []
    def capture_speed(action, params):
        if action == 'set_clip_speed':
            speed_requests.append(dict(params))
        return actual_dispatch(action, params)
    monkeypatch.setattr(controller, 'dispatch', capture_speed)
    server = EditorServer(('127.0.0.1', 0), controller)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    window = EditorWindow(f'http://127.0.0.1:{server.server_port}')
    errors = []
    window.client.failed.disconnect(window.show_error)
    window.client.failed.connect(errors.append)
    try:
        window.show()
        wait_for(app, lambda: window.state is not None)
        window.select_clip(original['id'])
        window.seek_frame(12)
        window.clip_speed.setValue(0)
        window.apply_speed()
        wait_for(app, lambda: len(clips_of(window.state)) == 3)
        clips = clips_of(window.state)
        prefix = next(c for c in clips if c['id'] == original['id'])
        frozen = next(c for c in clips if c['speed_percentage'] == 0)
        after = next(c for c in clips if c['id'] == following['id'])
        assert speed_requests[0]['freeze_frame'] == 12
        assert prefix['start_frame'] == 0 and duration(prefix) == 12
        assert prefix['speed_percentage'] == 100
        assert frozen['start_frame'] == 12 and duration(frozen) == 35
        assert frozen['in_frame'] == 12 and frozen['out_frame'] == 13
        assert after['start_frame'] == 47
        assert window.selection == frozen['id']
        assert window.timeline.selection == frozen['id']
        assert window.clip_start.value() == 12
        assert window.clip_speed.value() == 0
        assert window.current_frame == 12
        wait_for(app, lambda: window.playback_mode == 'timeline' and window.preview_signature == window.state_signature, seconds=15)
        # A playhead away from the selected clip omits an explicit freeze point.
        window.select_clip(following['id'], preview=False)
        window.seek_frame(0)
        window.clip_speed.setValue(0)
        window.apply_speed()
        wait_for(app, lambda: next(c for c in clips_of(window.state) if c['id'] == following['id'])['speed_percentage'] == 0)
        assert 'freeze_frame' not in speed_requests[-1]
        assert len(clips_of(window.state)) == 3
        assert window.selection == following['id']
        assert not errors
    finally:
        window.poll_timer.stop()
        window.transport_timer.stop()
        window.render_timer.stop()
        window.player.stop()
        window.close()
        window.deleteLater()
        app.processEvents()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        for job in controller.jobs.values():
            Path(job['output']).unlink(missing_ok=True)


def test_cross_dissolve_inspector_window_and_mixed_preview(tmp_path):
    import json
    import subprocess
    from pathlib import Path
    from frameforge.engine import ffmpeg_executable
    from frameforge.ui import Timeline
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    controller = Controller(tmp_path)
    controller.dispatch('create_project', {'name': 'GT Studio Cross Dissolve', 'width': 160, 'height': 90})
    clips = []
    for color in ['red', 'blue']:
        source = tmp_path / f'{color}-handles.mp4'
        subprocess.run([ffmpeg_executable(), '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', f'color=c={color}:s=160x90:r=24:d=3', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(source)], check=True)
        media = controller.dispatch('import_media', {'path': str(source)})
        clips.append(controller.dispatch('append_clip', {'media_id': media['id'], 'in_frame': 12, 'out_frame': 60}))
    server = EditorServer(('127.0.0.1', 0), controller)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    window = EditorWindow(url)
    errors = []
    window.client.failed.disconnect(window.show_error)
    window.client.failed.connect(errors.append)
    try:
        window.show()
        wait_for(app, lambda: window.state is not None)
        window.select_clip(clips[0]['id'])
        window.transition_position.setCurrentText('end')
        window.transition_duration.setValue(12)
        window.transition_alignment.setCurrentText('center')
        window.add_transition()
        wait_for(app, lambda: len(timeline_of(window.state).get('transitions', [])) == 1)
        transition = timeline_of(window.state)['transitions'][0]
        assert (transition['cut_frame'], transition['start_frame'], transition['end_frame']) == (48, 42, 54)
        assert window.transition_id == transition['id']
        assert window.transition_list.count() == 1
        assert [c['start_frame'] for c in clips_of(window.state)] == [0, 48]
        window.timeline.scale = 6
        window.timeline.set_state(window.state)
        window.timeline.repaint()
        app.processEvents()
        rect, record = window.timeline.transition_hitboxes[0]
        assert rect.x() == Timeline.HEADER + 42 * window.timeline.scale
        assert rect.width() == 12 * window.timeline.scale
        assert record['track_id'] == transition['track_id']
        window.rpc('save_project')
        saved = Path(window.state['path'])
        wait_for(app, saved.exists)
        assert json.loads(saved.read_text())['timelines'][0]['transitions'][0]['id'] == transition['id']
        assert rpc(url, 'get_state')['timelines'][0]['transitions'][0] == transition
        window.select_transition(transition['id'])
        wait_for(app, lambda: window.playback_mode == 'timeline' and window.preview_signature == window.state_signature, seconds=15)
        window.seek_frame(48)
        window.player.play()
        def shows_mix():
            frame = window.video.videoSink().videoFrame()
            if not frame.isValid():
                return False
            image = frame.toImage()
            color = image.pixelColor(image.width() // 2, image.height() // 2)
            return color.red() > 60 and color.blue() > 60 and color.green() < 35
        wait_for(app, shows_mix)
        window.player.pause()
        window.grab().save(str(Path(__file__).resolve().parent.parent / 'research' / 'ui-preview.png'))
        window.delete_transition()
        wait_for(app, lambda: not timeline_of(window.state)['transitions'])
        assert window.transition_list.count() == 0
        assert window.preview_signature is None
        assert not errors
    finally:
        window.poll_timer.stop()
        window.transport_timer.stop()
        window.render_timer.stop()
        window.player.stop()
        window.close()
        window.deleteLater()
        app.processEvents()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        for job in controller.jobs.values():
            Path(job['output']).unlink(missing_ok=True)


@pytest.mark.parametrize("linked", [False, True])
def test_detach_audio_button_updates_shared_state_and_selection(tmp_path, linked):
    import subprocess
    from frameforge.engine import ffmpeg_executable
    from PySide6.QtWidgets import QPushButton
    source = tmp_path/'av.mp4'
    subprocess.run([ffmpeg_executable(), '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=red:s=160x90:r=24:d=1', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', '-shortest', '-c:v', 'libx264', '-c:a', 'aac', str(source)], check=True)
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path)
    controller.dispatch('create_project', {'name':'Detached audio', 'width':160, 'height':90})
    media = controller.dispatch('import_media', {'path':str(source)})
    clip = controller.dispatch('append_clip', {'media_id':media['id']})
    server = EditorServer(('127.0.0.1',0), controller)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url=f'http://127.0.0.1:{server.server_port}'
    window=EditorWindow(url)
    errors=[]
    window.client.failed.disconnect(window.show_error)
    window.client.failed.connect(errors.append)
    try:
        wait_for(app, lambda:window.state and window.state.get('name')=='Detached audio')
        window.select_clip(clip['id'], preview=False)
        button=next(b for b in window.findChildren(QPushButton) if b.text()==('Detach audio and link' if linked else 'Detach audio to track'))
        button.click()
        wait_for(app, lambda:len(clips_of(window.state))==2)
        audio=next(c for t in timeline_of(window.state)['tracks'] if t['kind']=='audio' for c in t['clips'])
        assert window.selection==audio['id'] and window.timeline.selection==audio['id']
        assert window.selected_clip()['audio_enabled'] is True
        if linked:
            assert audio.get('link_group_id')
            video_track=next(t['id'] for t in timeline_of(window.state)['tracks'] if t['kind']=='video')
            audio_track=next(t['id'] for t in timeline_of(window.state)['tracks'] if t['kind']=='audio')
            window.timeline.moved.emit(clip['id'],6,video_track)
            wait_for(app,lambda:all(c['start_frame']==6 for c in clips_of(window.state)))
            window.timeline.moved.emit(audio['id'],0,audio_track)
            wait_for(app,lambda:all(c['start_frame']==0 for c in clips_of(window.state)))
            window.seek_frame(12)
            window.split_clip()
            wait_for(app, lambda:len(clips_of(window.state))==4)
            rpc(url,'ripple_delete',{'clip_id':clip['id']})
            window.client.poll()
            wait_for(app, lambda:len(clips_of(window.state))==2)
            assert all(c['start_frame']==0 and c['duration_frames']==12 for c in clips_of(window.state))
        else:
            rpc(url,'delete_clip',{'clip_id':clip['id']})
            window.client.poll()
            wait_for(app, lambda:len(clips_of(window.state))==1)
            assert window.selected_clip()['id']==audio['id']
        assert not errors
    finally:
        window.poll_timer.stop(); window.transport_timer.stop(); window.render_timer.stop()
        window.close(); window.deleteLater(); app.processEvents()
        server.shutdown(); server.server_close(); thread.join(timeout=3)


def test_native_window_reconnects_when_service_revision_restarts(tmp_path):
    app=QApplication.instance() or QApplication([])
    old=Controller(tmp_path/'old')
    old.dispatch('create_project',{'name':'Old service'})
    for frame in range(8):old.dispatch('set_playhead',{'frame':frame})
    server=EditorServer(('127.0.0.1',0),old)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    url=f'http://127.0.0.1:{server.server_port}'
    window=EditorWindow(url)
    errors=[]
    window.client.failed.disconnect(window.show_error);window.client.failed.connect(errors.append)
    try:
        wait_for(app,lambda:window.transport_revision==8 and window.current_frame==7)
        old_session=window.transport_session_id
        new=Controller(tmp_path/'new');new.dispatch('create_project',{'name':'New service'})
        new.dispatch('set_page',{'page':'Deliver'})
        new.dispatch('set_playhead',{'frame':37})
        server.controller=new
        window.client.poll();window.client.poll_transport()
        wait_for(app,lambda:window.transport_session_id!=old_session and window.current_page=='Deliver' and window.current_frame==37)
        wait_for(app,lambda:new.transport()['observed']['applied_revision']==2)
        assert not new.transport()['pending'] and new.transport()['ui_connected']
        assert window.transport_revision==2 and not errors
    finally:
        window.poll_timer.stop();window.transport_timer.stop();window.render_timer.stop()
        window.close();window.deleteLater();app.processEvents()
        server.shutdown();server.server_close();thread.join(timeout=3)


from test_linked_split import linked_project


@pytest.mark.parametrize('edge',['start','end'])
def test_trim_edge_button_updates_linked_audio_over_http(tmp_path,linked_project,edge):
    from PySide6.QtWidgets import QPushButton
    app=QApplication.instance() or QApplication([])
    engine,v,a=linked_project
    controller=Controller(tmp_path/'control');controller.engine=engine
    server=EditorServer(('127.0.0.1',0),controller)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    window=EditorWindow(f'http://127.0.0.1:{server.server_port}')
    errors=[];window.client.failed.disconnect(window.show_error);window.client.failed.connect(errors.append)
    try:
        wait_for(app,lambda:window.state and len(clips_of(window.state))==2)
        window.select_clip(v['id'],preview=False);window.seek_frame(24)
        button=next(b for b in window.findChildren(QPushButton) if b.text()==f'Trim {edge} to playhead')
        button.click()
        wait_for(app,lambda:all(c['duration_frames']==24 for c in clips_of(window.state)))
        assert all(c['start_frame']==(24 if edge=='start' else 0) for c in clips_of(window.state))
        assert len({c['link_group_id'] for c in clips_of(window.state)})==1
        assert not errors
    finally:
        window.poll_timer.stop();window.transport_timer.stop();window.render_timer.stop()
        window.close();window.deleteLater();app.processEvents()
        server.shutdown();server.server_close();thread.join(timeout=3)


def test_new_project_transport_waits_for_matching_project_state(tmp_path):
    app=QApplication.instance() or QApplication([])
    controller=Controller(tmp_path)
    old=controller.dispatch('create_project',{'name':'Old transport project'})
    server=EditorServer(('127.0.0.1',0),controller)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    window=EditorWindow(f'http://127.0.0.1:{server.server_port}')
    errors=[];window.client.failed.disconnect(window.show_error);window.client.failed.connect(errors.append)
    try:
        wait_for(app,lambda:window.state and window.state['id']==old['id'])
        new=controller.dispatch('create_project',{'name':'New transport project'})
        controller.dispatch('set_playhead',{'frame':37})
        transport=controller.transport()
        # Deliberately deliver transport before its independently requested state.
        window.accept_transport(transport)
        assert window.transport_revision==0 and window.current_frame==0
        window.accept_state(new)
        window.accept_transport(transport)
        assert window.current_frame==37 and window.transport_revision==1
        wait_for(app,lambda:controller.transport()['observed']['applied_revision']==1)
        assert not errors
    finally:
        window.poll_timer.stop();window.transport_timer.stop();window.render_timer.stop()
        window.close();window.deleteLater();app.processEvents()
        server.shutdown();server.server_close();thread.join(timeout=3)


@pytest.mark.parametrize('conflict',[False,True])
def test_inspector_timing_is_one_atomic_linked_transaction(tmp_path,linked_project,conflict):
    from PySide6.QtWidgets import QPushButton
    app=QApplication.instance() or QApplication([])
    engine,v,a=linked_project
    if conflict:
        engine.dispatch('append_clip',{'media_id':v['media_id'],'start_frame':60,'in_frame':0,'out_frame':12})
    before=engine.get_state()
    controller=Controller(tmp_path/'control');controller.engine=engine
    server=EditorServer(('127.0.0.1',0),controller)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    window=EditorWindow(f'http://127.0.0.1:{server.server_port}')
    errors=[];window.client.failed.disconnect(window.show_error);window.client.failed.connect(errors.append)
    try:
        wait_for(app,lambda:window.state and window.state['id']==before['id'])
        window.select_clip(v['id'],preview=False)
        window.clip_in.setValue(18);window.clip_out.setValue(42);window.clip_start.setValue(48 if conflict else 8)
        next(b for b in window.findChildren(QPushButton) if b.text()=='Apply clip timing').click()
        if conflict:
            wait_for(app,lambda:bool(errors))
            assert engine.get_state()==before
            engine.dispatch('undo');assert len(engine._timeline()['tracks'][0]['clips'])==1
        else:
            wait_for(app,lambda:all(c['start_frame']==8 and c['duration_frames']==24 for c in clips_of(window.state)))
            assert all((c['in_frame'],c['out_frame'])==(18,42) for c in clips_of(window.state))
            engine.dispatch('undo');assert engine.get_state()==before
            assert not errors
    finally:
        window.poll_timer.stop();window.transport_timer.stop();window.render_timer.stop()
        window.close();window.deleteLater();app.processEvents()
        server.shutdown();server.server_close();thread.join(timeout=3)


def test_inspector_noop_omits_rounded_fractional_source_fields(tmp_path,linked_project):
    app=QApplication.instance() or QApplication([])
    engine,v,a=linked_project
    for item in (v,a):engine.dispatch('set_clip_speed',{'clip_id':item['id'],'percentage':50,'ripple':True})
    tail=engine.dispatch('split_clip',{'clip_id':v['id'],'frame':37})['second']
    before=engine.get_state()
    controller=Controller(tmp_path/'control');controller.engine=engine
    calls=[];dispatch=controller.dispatch
    def capture(action,params):
        if action=='trim_clip':calls.append(dict(params))
        return dispatch(action,params)
    controller.dispatch=capture
    server=EditorServer(('127.0.0.1',0),controller)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    window=EditorWindow(f'http://127.0.0.1:{server.server_port}')
    errors=[];window.client.failed.disconnect(window.show_error);window.client.failed.connect(errors.append)
    try:
        wait_for(app,lambda:window.state and len(clips_of(window.state))==4)
        window.select_clip(tail['id'],preview=False);window.apply_timing()
        wait_for(app,lambda:bool(calls))
        wait_for(app,lambda:window.client.pending==0)
        assert calls==[{'clip_id':tail['id'],'start_frame':37}]
        assert engine.get_state()==before and not errors
    finally:
        window.poll_timer.stop();window.transport_timer.stop();window.render_timer.stop()
        window.close();window.deleteLater();app.processEvents()
        server.shutdown();server.server_close();thread.join(timeout=3)


@pytest.mark.parametrize('percentage,ripple',[(50,True),(-100,False),(0,False)])
def test_speed_button_updates_linked_peers_and_selects_freeze_tail(tmp_path,linked_project,percentage,ripple):
    from PySide6.QtWidgets import QPushButton
    app=QApplication.instance() or QApplication([])
    engine,v,a=linked_project
    controller=Controller(tmp_path/'control');controller.engine=engine
    server=EditorServer(('127.0.0.1',0),controller)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    window=EditorWindow(f'http://127.0.0.1:{server.server_port}')
    errors=[];window.client.failed.disconnect(window.show_error);window.client.failed.connect(errors.append)
    try:
        wait_for(app,lambda:window.state and len(clips_of(window.state))==2)
        window.select_clip(v['id'],preview=False);window.seek_frame(18)
        window.clip_speed.setValue(percentage);window.ripple_speed.setChecked(ripple);window.pitch_correction.setChecked(False)
        next(b for b in window.findChildren(QPushButton) if b.text()=='Apply speed / reverse / freeze').click()
        if percentage==0:
            wait_for(app,lambda:len(clips_of(window.state))==4 and window.selection!=v['id'])
            selected=window.selected_clip();assert selected['start_frame']==18 and selected['duration_frames']==30
            peers=[c for c in clips_of(window.state) if c.get('link_group_id')==selected.get('link_group_id')]
            assert len(peers)==2 and all(c['speed_percentage']==0 and not c['pitch_correction'] for c in peers)
        else:
            wait_for(app,lambda:all(c['speed_percentage']==percentage for c in clips_of(window.state)))
            assert all(c['duration_frames']==(96 if percentage==50 else 48) and not c['pitch_correction'] for c in clips_of(window.state))
        assert not errors
    finally:
        window.poll_timer.stop();window.transport_timer.stop();window.render_timer.stop()
        window.close();window.deleteLater();app.processEvents()
        server.shutdown();server.server_close();thread.join(timeout=3)


def test_track_controls_guard_linked_edits_and_locked_canvas_drag(tmp_path,linked_project):
    from PySide6.QtCore import Qt,QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton
    app=QApplication.instance() or QApplication([])
    engine,v,a=linked_project;at=engine._clip(a['id'])[1];vt=engine._clip(v['id'])[1]
    controller=Controller(tmp_path/'control');controller.engine=engine
    server=EditorServer(('127.0.0.1',0),controller)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    window=EditorWindow(f'http://127.0.0.1:{server.server_port}')
    errors=[];window.client.failed.disconnect(window.show_error);window.client.failed.connect(errors.append)
    try:
        wait_for(app,lambda:window.state and window.track_choice.count()==2)
        window.track_choice.setCurrentIndex(window.track_choice.findData(at['id']))
        window.track_enabled.setChecked(False);window.track_locked.setChecked(True)
        button=next(b for b in window.findChildren(QPushButton) if b.text()=='Apply track state');button.click()
        wait_for(app,lambda:any(t['id']==at['id'] and t['locked'] and not t['enabled'] for t in timeline_of(window.state)['tracks']))
        before=engine.get_state()
        window.timeline.moved.emit(v['id'],6,vt['id'])
        wait_for(app,lambda:bool(errors));assert engine.get_state()==before
        window.show();app.processEvents();window.timeline.repaint();app.processEvents()
        rect=next(rect for rect,c in window.timeline.hitboxes if c['id']==a['id'])
        moves=[];window.timeline.moved.connect(lambda *args:moves.append(args))
        origin=rect.center().toPoint()
        QTest.mousePress(window.timeline,Qt.MouseButton.LeftButton,pos=origin)
        assert window.timeline.drag is None
        QTest.mouseRelease(window.timeline,Qt.MouseButton.LeftButton,pos=origin+QPoint(20,0))
        assert not moves and engine.get_state()==before
        window.track_enabled.setChecked(True);window.track_locked.setChecked(False);button.click()
        wait_for(app,lambda:any(t['id']==at['id'] and not t['locked'] and t['enabled'] for t in timeline_of(window.state)['tracks']))
        window.timeline.moved.emit(v['id'],6,vt['id'])
        wait_for(app,lambda:all(c['start_frame']==6 for c in clips_of(window.state)))
        assert len(errors)==1
    finally:
        window.poll_timer.stop();window.transport_timer.stop();window.render_timer.stop()
        window.close();window.deleteLater();app.processEvents()
        server.shutdown();server.server_close();thread.join(timeout=3)


def test_completed_preview_is_rebuilt_after_renderer_session_changes(tmp_path,linked_project):
    import copy
    app=QApplication.instance() or QApplication([])
    engine,v,a=linked_project
    old=Controller(tmp_path/'old');old.engine=engine
    server=EditorServer(('127.0.0.1',0),old)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    window=EditorWindow(f'http://127.0.0.1:{server.server_port}')
    errors=[];window.client.failed.disconnect(window.show_error);window.client.failed.connect(errors.append)
    try:
        wait_for(app,lambda:window.state and window.transport_session_id==old.transport_session_id)
        window.build_preview()
        wait_for(app,lambda:bool(window.preview_path) and window.preview_signature==window.state_signature,seconds=15)
        previous=window.preview_path;signature=window.state_signature
        new=Controller(tmp_path/'new');new.engine.project=copy.deepcopy(engine.project)
        server.controller=new;window.client.poll_transport()
        wait_for(app,lambda:window.transport_session_id==new.transport_session_id and window.preview_path is None)
        assert window.preview_signature is None and window.state_signature==signature
        window.build_preview()
        wait_for(app,lambda:bool(window.preview_path) and window.preview_signature==signature,seconds=15)
        assert window.preview_path!=previous and len(new.jobs)==1 and not errors
    finally:
        window.poll_timer.stop();window.transport_timer.stop();window.render_timer.stop()
        window.close();window.deleteLater();app.processEvents()
        server.shutdown();server.server_close();thread.join(timeout=3)


def test_source_data_level_ui_http_shared_media_roundtrip(tmp_path):
    from PySide6.QtGui import QImage, QColor
    from PySide6.QtWidgets import QPushButton
    app=QApplication.instance() or QApplication([])
    image=QImage(32,32,QImage.Format.Format_RGB32);image.fill(QColor(128,32,16))
    source=tmp_path/'source.png';assert image.save(str(source))
    controller=Controller(tmp_path/'service')
    controller.dispatch('create_project',{'name':'Shared source levels','width':32,'height':32})
    media=controller.dispatch('import_media',{'path':str(source)})
    first=controller.dispatch('append_clip',{'media_id':media['id'],'out_frame':6})
    controller.dispatch('append_clip',{'media_id':media['id'],'out_frame':6})
    server=EditorServer(('127.0.0.1',0),controller)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    url=f'http://127.0.0.1:{server.server_port}';window=EditorWindow(url)
    try:
        wait_for(app,lambda:bool(window.state))
        window.select_clip(first['id'],preview=False)
        assert window.media_data_level.currentText()=='Auto'
        window.media_data_level.setCurrentText('Video')
        next(b for b in window.findChildren(QPushButton) if b.text()=='Apply source data level').click()
        wait_for(app,lambda:controller.engine._media(media['id']).get('data_level')=='Video')
        wait_for(app,lambda:window.state['media'][0]['data_level']=='Video')
        assert len({c['media_id'] for c in clips_of(window.state)})==1
        rpc(url,'set_media_data_level',{'media_id':media['id'],'mode':'Full'})
        window.client.poll();wait_for(app,lambda:window.media_data_level.currentText()=='Full')
        rpc(url,'undo');window.client.poll()
        wait_for(app,lambda:window.media_data_level.currentText()=='Video')
        wait_for(app,lambda:not any(j['status'] in ('queued','running') for j in controller.jobs.values()),seconds=15)
    finally:
        window.poll_timer.stop();window.transport_timer.stop();window.render_timer.stop()
        window.close();window.deleteLater();app.processEvents()
        server.shutdown();server.server_close();thread.join(timeout=3)
