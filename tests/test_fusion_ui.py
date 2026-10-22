import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import threading

from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from frameforge.client import rpc
from frameforge.service import Controller, EditorServer
from frameforge.ui import EditorWindow
from test_fusion import real_project
from test_transitions import colored_sources
from test_ui import wait_for


def test_canvas_controls_and_mcp_share_nodes_and_preview(tmp_path, colored_sources):
    e, clip_id = real_project(tmp_path, colored_sources)
    controller = Controller(tmp_path/'service'); controller.engine = e
    server = EditorServer(('127.0.0.1', 0), controller)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    app = QApplication.instance() or QApplication([])
    window = EditorWindow(url)
    errors = []
    window.client.failed.disconnect(window.show_error); window.client.failed.connect(errors.append)
    window.show_error = errors.append
    try:
        window.show()
        wait_for(app, lambda: window.state is not None)
        window.select_clip(clip_id, preview=False); window.set_page('Fusion')
        panel = window.fusion_panel
        assert panel.clip_id == clip_id and len(panel.items) == 2
        panel.type_choice.setCurrentText('Background'); panel.add_button.click()
        wait_for(app, lambda: len(panel.items) == 3)
        bg = next(n for n in panel.graph['nodes'] if n['type'] == 'Background')
        item = panel.items[bg['id']]
        start = panel.view.mapFromScene(item.sceneBoundingRect().center())
        previous_position = dict(bg['position'])
        QTest.mousePress(panel.view.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(panel.view.viewport(), start + QPoint(35, 20), delay=20)
        QTest.mouseRelease(panel.view.viewport(), Qt.MouseButton.LeftButton, pos=start + QPoint(35, 20))
        wait_for(app, lambda: next(n for n in panel.graph['nodes'] if n['id'] == bg['id'])['position'] != previous_position)
        panel.scene.clearSelection(); panel.items[bg['id']].setSelected(True)
        panel.parameters['Blue'].setValue(1); panel.parameters['Alpha'].setValue(0.5)
        panel.apply_button.click()
        wait_for(app, lambda: next(n for n in panel.graph['nodes'] if n['id'] == bg['id'])['parameters']['Blue'] == 1)
        panel.scene.clearSelection(); panel.items['MediaOut1'].setSelected(True)
        panel.source_choice.setCurrentIndex(panel.source_choice.findData(bg['id']))
        panel.connect_button.click()
        wait_for(app, lambda: next(n for n in panel.graph['nodes'] if n['id'] == 'MediaOut1')['inputs']['Input'] == bg['id'])
        assert panel.source_choice.currentData() == bg['id']
        wait_for(app, lambda: window.preview_signature == window.state_signature, seconds=8)
        assert window.preview_path and os.path.isfile(window.preview_path)
        sink = window.video.videoSink()
        wait_for(app, lambda: sink.videoFrame().isValid())
        assert window.player.playbackState() == window.player.PlaybackState.PausedState
        first_pixel = sink.videoFrame().toImage().pixelColor(16, 16)
        assert first_pixel.red() < 8 and first_pixel.green() < 8 and 120 <= first_pixel.blue() <= 136
        # Direct external node edits update both canvas properties and rendered preview.
        rpc(url, 'update_fusion_node', {'clip_id': clip_id, 'node_id': bg['id'], 'parameters': {'Blue': 0, 'Green': 1}})
        window.client.poll()
        wait_for(app, lambda: next(n for n in panel.graph['nodes'] if n['id'] == bg['id'])['parameters']['Green'] == 1)
        wait_for(app, lambda: window.preview_signature == window.state_signature, seconds=8)
        wait_for(app, lambda: sink.videoFrame().isValid() and sink.videoFrame().toImage().pixelColor(16, 16).green() > 120)
        panel.scene.clearSelection(); panel.items['MediaOut1'].setSelected(True)
        panel.disconnect_button.click()
        wait_for(app, lambda: 'Incomplete output' in panel.status.text())
        window.build_preview()
        assert 'Connect the Fusion output' in window.preview_hint.text()
        assert not rpc(url, 'get_fusion_graph', {'clip_id': clip_id})['render_ready']
        # Locked track disables graph mutations in the actual Qt controls.
        track_id = e.project['timelines'][0]['tracks'][0]['id']
        rpc(url, 'set_track_state', {'track_id': track_id, 'locked': True}); window.client.poll()
        wait_for(app, lambda: panel.locked)
        assert not panel.add_button.isEnabled() and not panel.clear_button.isEnabled()
        assert not panel.items[bg['id']].flags() & panel.items[bg['id']].GraphicsItemFlag.ItemIsMovable
        assert not errors
    finally:
        window.poll_timer.stop(); window.render_timer.stop(); window.transport_timer.stop()
        window.player.stop(); window.close(); window.client.manager.clearAccessCache()
        server.shutdown(); server.server_close(); thread.join(timeout=3)
