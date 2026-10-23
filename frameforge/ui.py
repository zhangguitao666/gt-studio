"""Native desktop editor. The HTTP service owns all editable project state."""
from __future__ import annotations
import json
import math
import os
import sys
import uuid
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QAction, QKeySequence, QIcon
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton, QVBoxLayout,
    QHBoxLayout, QSplitter, QListWidget, QListWidgetItem, QFileDialog,
    QInputDialog, QMessageBox, QFormLayout, QDoubleSpinBox, QSpinBox,
    QComboBox, QScrollArea, QFrame, QToolBar, QCheckBox, QTabWidget, QTextEdit, QLineEdit, QStackedWidget,
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget


def values(obj):
    return list(obj.values()) if isinstance(obj, dict) else list(obj or [])


def timeline_of(state):
    if not state:
        return {}
    ts = state.get('timelines', [])
    active = state.get('active_timeline_id') or state.get('active_timeline')
    if isinstance(active, dict):
        return active
    if isinstance(state.get('timeline'), dict):
        return state['timeline']
    return next((t for t in values(ts) if t.get('id') == active), next(iter(values(ts)), {}))


def clips_of(state):
    timeline = timeline_of(state)
    clips = values(timeline.get('clips'))
    if not clips:
        for track in values(timeline.get('tracks')):
            clips += [dict(c, track_id=track['id']) for c in values(track.get('clips'))]
    return clips


def has_timeline_content(state):
    return bool(clips_of(state) or timeline_of(state).get('subtitles'))


def fps_of(state):
    timeline = timeline_of(state)
    rate = timeline.get('fps') or (state or {}).get('fps') or (state or {}).get('settings', {}).get('fps') or 24
    return float(rate['num']) / float(rate['den']) if isinstance(rate, dict) else float(rate)


def duration(clip):
    if 'duration_frames' in clip:
        return max(1, int(clip['duration_frames']))
    return max(1, int(clip.get('out_frame', 1)) - int(clip.get('in_frame', 0)))


def requires_timeline_preview(clip):
    if clip.get('fusion_graph'):
        return True
    if clip.get('speed_percentage', 100) != 100:
        return True
    for precise, legacy in [('source_start', 'in_frame'), ('source_end', 'out_frame')]:
        value = clip.get(precise)
        if isinstance(value, dict) and value.get('num') != clip.get(legacy, 0) * value.get('den', 1):
            return True
    return duration(clip) != int(clip.get('out_frame', 1)) - int(clip.get('in_frame', 0))


def timecode(frame, fps):
    f = int(round(fps))
    seconds, frames = divmod(max(0, int(frame)), f)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours:02}:{minutes:02}:{seconds:02}:{frames:02}'


class RpcClient(QWidget):
    state_received = Signal(object)
    transport_received = Signal(object)
    failed = Signal(str)
    busy_changed = Signal(bool)

    def __init__(self, url):
        super().__init__()
        self.url = url.rstrip('/')
        self.manager = QNetworkAccessManager(self)
        self.manager.setTransferTimeout(300000)
        self.polling = False
        self.transport_polling = False
        self.pending = 0

    def poll(self):
        if self.polling:
            return
        self.polling = True
        reply = self.manager.get(QNetworkRequest(QUrl(self.url + '/state')))
        reply.finished.connect(lambda: self.finish(reply, True))

    def poll_transport(self):
        if self.transport_polling:
            return
        self.transport_polling = True
        reply = self.manager.get(QNetworkRequest(QUrl(self.url + '/transport')))
        reply.finished.connect(lambda: self.finish(reply, 'transport'))

    def rpc(self, action, params=None, callback=None, refresh=True, quiet=False, on_error=None):
        request = QNetworkRequest(QUrl(self.url + '/rpc'))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, 'application/json')
        self.pending += 1
        self.busy_changed.emit(True)
        reply = self.manager.post(request, json.dumps({'action': action, 'params': params or {}}).encode())
        reply.finished.connect(lambda: self.finish(reply, False, callback, refresh, quiet, on_error))

    def finish(self, reply, poll, callback=None, refresh=True, quiet=False, on_error=None):
        if poll == 'transport':
            self.transport_polling = False
        elif poll:
            self.polling = False
        else:
            self.pending -= 1
            self.busy_changed.emit(self.pending > 0)
        try:
            body = json.loads(bytes(reply.readAll()).decode())
            if body.get('error'):
                raise ValueError(str(body['error']))
            if reply.error() != QNetworkReply.NetworkError.NoError:
                raise ValueError(reply.errorString())
            result = body.get('result')
            if poll == 'transport':
                self.transport_received.emit(result)
            elif poll:
                self.state_received.emit(result)
            else:
                if callback:
                    callback(result)
                if refresh:
                    self.poll()
        except Exception as exc:
            if not poll and on_error:
                on_error(str(exc))
            if not poll and not quiet:
                self.failed.emit(str(exc))
        finally:
            reply.deleteLater()


class Timeline(QWidget):
    selected = Signal(str)
    subtitle_selected = Signal(str)
    transition_selected = Signal(str)
    seek = Signal(int)
    moved = Signal(str, int, str)
    HEADER = 104
    RULER = 32
    LANE = 66

    def __init__(self):
        super().__init__()
        self.state = None
        self.frame = 0
        self.selection = None
        self.scale = 2.0
        self.hitboxes = []
        self.subtitle_hitboxes = []
        self.subtitle_selection = None
        self.transition_selection = None
        self.transition_hitboxes = []
        self.drag = None
        self.setMinimumSize(900, 260)
        self.setMouseTracking(True)

    def set_state(self, state):
        self.state = state
        clips = clips_of(state)
        subtitles = timeline_of(state).get('subtitles', [])
        end = max([int(c.get('start_frame', 0)) + duration(c) for c in clips] + [c['end_frame'] for c in subtitles] + [int(fps_of(state) * 30)])
        tracks = values(timeline_of(state).get('tracks'))
        self.setMinimumSize(max(900, int(end * self.scale) + self.HEADER + 120), max(260, self.RULER + (len(tracks) + bool(subtitles)) * self.LANE + 30))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor('#171a20'))
        tracks = values(timeline_of(self.state).get('tracks'))
        fps = fps_of(self.state)
        p.setFont(QFont('Arial', 10))
        step = max(1, math.ceil(100 / (self.scale * fps)))
        for second in range(0, int((self.width() - self.HEADER) / self.scale / fps) + 1, step):
            x = self.HEADER + second * fps * self.scale
            p.setPen(QColor('#343943'))
            p.drawLine(int(x), 25, int(x), self.height())
            p.setPen(QColor('#969eae'))
            p.drawText(int(x + 5), 19, timecode(int(second * fps), fps))
        self.hitboxes = []
        media = {m['id']: m for m in values((self.state or {}).get('media'))}
        for i, track in enumerate(tracks):
            y = self.RULER + i * self.LANE
            p.fillRect(0, y, self.width(), self.LANE - 1, QColor('#1c2028' if i % 2 == 0 else '#20242c'))
            p.fillRect(0, y, self.HEADER - 1, self.LANE - 1, QColor('#292e38'))
            p.setPen(QColor('#c5cad5'))
            p.drawText(12, y + 26, track.get('name', track.get('kind', 'Track')))
            p.setPen(QColor('#7f8b9d'))
            status = str(track.get('kind', 'video')).upper() + (' · OFF' if not track.get('enabled', True) else '')
            p.drawText(12, y + 45, status)
            if track.get('locked', False):
                p.drawText(12, y + 60, 'LOCKED')
            for c in clips_of(self.state):
                if c.get('track_id') != track.get('id'):
                    continue
                x = self.HEADER + int(c.get('start_frame', 0)) * self.scale
                w = max(5, duration(c) * self.scale)
                rect = QRectF(x, y + 7, w, self.LANE - 15)
                audio = track.get('kind') == 'audio'
                p.setPen(QPen(QColor('#e1edff') if c['id'] == self.selection else QColor('#273e54'), 2 if c['id'] == self.selection else 1))
                p.setBrush(QColor(('#336858' if audio else '#365a83') if track.get('enabled', True) else '#424650'))
                p.drawRoundedRect(rect, 4, 4)
                p.save()
                p.setClipRect(rect.adjusted(5, 1, -4, -1))
                p.setPen(QColor('#eef4ff'))
                p.drawText(int(x + 8), y + 29, c.get('name') or media.get(c.get('media_id'), {}).get('name', 'Clip'))
                p.setPen(QColor('#c1cfdf'))
                p.drawText(int(x + 8), y + 46, f'{duration(c)} frames · {c.get("speed_percentage", 100):g}%')
                p.restore()
                self.hitboxes.append((rect, c))
        self.transition_hitboxes = []
        for transition in timeline_of(self.state).get('transitions', []):
            lane = next((index for index, track in enumerate(tracks) if track['id'] == transition['track_id']), None)
            if lane is None:
                continue
            rect = QRectF(self.HEADER + transition['start_frame'] * self.scale, self.RULER + lane * self.LANE + 8, max(3, (transition['end_frame'] - transition['start_frame']) * self.scale), 17)
            p.setPen(QPen(QColor('#effffb') if transition['id'] == self.transition_selection else QColor('#7dcaba'), 2))
            p.setBrush(QColor('#377c6f'))
            p.drawRect(rect)
            p.drawLine(rect.topLeft(), rect.bottomRight())
            p.drawLine(rect.bottomLeft(), rect.topRight())
            self.transition_hitboxes.append((rect, transition))
        self.subtitle_hitboxes = []
        subtitles = timeline_of(self.state).get('subtitles', [])
        if subtitles:
            y = self.RULER + len(tracks) * self.LANE
            p.fillRect(0, y, self.width(), self.LANE - 1, QColor('#282329'))
            p.fillRect(0, y, self.HEADER - 1, self.LANE - 1, QColor('#342c35'))
            p.setPen(QColor('#e2c8a3'))
            p.drawText(10, y + 28, 'Subtitles')
            for cue in subtitles:
                rect = QRectF(self.HEADER + cue['start_frame'] * self.scale, y + 9, max(5, (cue['end_frame'] - cue['start_frame']) * self.scale), self.LANE - 19)
                p.setPen(QPen(QColor('#ffe9ab') if cue['id'] == self.subtitle_selection else QColor('#ac874d'), 2))
                p.setBrush(QColor('#705835'))
                p.drawRoundedRect(rect, 4, 4)
                p.save()
                p.setClipRect(rect.adjusted(6, 0, -4, 0))
                p.setPen(QColor('#fff3d1'))
                p.drawText(rect.adjusted(7, 5, -3, -3), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, cue['text'].replace('\n', ' / '))
                p.restore()
                self.subtitle_hitboxes.append((rect, cue))
        for marker in timeline_of(self.state).get('markers', []):
            mx = self.HEADER + marker.get('frame', 0) * self.scale
            p.setPen(QColor('#f2bf68'))
            p.drawLine(int(mx), 21, int(mx), 31)
            p.drawText(int(mx + 4), 31, marker.get('label', ''))
        x = self.HEADER + self.frame * self.scale
        p.setPen(QPen(QColor('#fa6a59'), 2))
        p.drawLine(int(x), 0, int(x), self.height())
        p.setBrush(QColor('#fa6a59'))
        p.drawRect(QRectF(x - 4, 0, 8, 9))
        if not tracks and not subtitles:
            p.setPen(QColor('#8190a6'))
            p.drawText(self.HEADER + 24, 95, 'Create a project, import media, then append a clip to begin.')
        p.end()

    def mousePressEvent(self, event):
        point = event.position()
        for rect, cue in reversed(self.subtitle_hitboxes):
            if rect.contains(point):
                self.subtitle_selection = cue['id']
                self.subtitle_selected.emit(cue['id'])
                self.seek.emit(cue['start_frame'])
                self.update()
                return
        for rect, transition in reversed(self.transition_hitboxes):
            if rect.contains(point):
                self.transition_selection = transition['id']
                self.transition_selected.emit(transition['id'])
                self.seek.emit(transition['cut_frame'])
                self.update()
                return
        for rect, clip in reversed(self.hitboxes):
            if rect.contains(point):
                self.selection = clip['id']
                self.selected.emit(clip['id'])
                owner = next((t for t in timeline_of(self.state).get('tracks', []) if t['id'] == clip.get('track_id')), {})
                self.drag = None if owner.get('locked', False) else (point.x(), clip)
                self.update()
                return
        self.seek.emit(max(0, round((point.x() - self.HEADER) / self.scale)))

    def mouseReleaseEvent(self, event):
        if not self.drag:
            return
        x, clip = self.drag
        delta = round((event.position().x() - x) / self.scale)
        if abs(event.position().x() - x) > 6:
            tracks = values(timeline_of(self.state).get('tracks'))
            lane = int((event.position().y() - self.RULER) / self.LANE)
            track_id = tracks[lane]['id'] if 0 <= lane < len(tracks) else clip.get('track_id')
            self.moved.emit(clip['id'], max(0, int(clip.get('start_frame', 0)) + delta), track_id)
        self.drag = None


STYLE = '''
QMainWindow, QWidget { background:#20242c; color:#dce2ec; font-family:Arial; font-size:12px; }
QLabel#brand { font-size:18px; font-weight:600; color:#f0f4fc; }
QLabel#section { color:#9ba8bc; font-size:11px; font-weight:600; padding:7px 0; }
QLabel#timecode { font-family:Menlo; font-size:16px; color:#dce9ff; }
QPushButton { background:#343c49; border:1px solid #465163; border-radius:4px; padding:7px 11px; }
QPushButton:hover { background:#46536a; }
QPushButton:checked { background:#385779; border-color:#719bd1; }
QPushButton#accent { background:#357baf; border-color:#559bd0; }
QTabWidget::pane { border:0; }
QTabBar::tab { background:#2b323d; color:#b9c4d5; padding:8px 13px; border:1px solid #414b5a; }
QTabBar::tab:selected { background:#385779; color:#f0f4ff; }
QLineEdit,QTextEdit { background:#171b22; border:1px solid #465163; padding:5px; border-radius:3px; }
QListWidget { background:#191d24; border:1px solid #353d4a; border-radius:4px; padding:4px; }
QListWidget::item { padding:10px 6px; border-bottom:1px solid #303641; }
QListWidget::item:selected { background:#355375; }
QSpinBox,QDoubleSpinBox,QComboBox { background:#171b22; border:1px solid #465163; padding:5px; border-radius:3px; }
QToolBar { background:#282e38; spacing:6px; border:0; padding:5px; }
QStatusBar { background:#161a20; color:#9aa6b8; }
QSplitter::handle { background:#12161c; width:3px; height:3px; }
QScrollArea { border:0; }
QMenuBar,QMenu { background:#282e38; }
'''


class EditorWindow(QMainWindow):
    def __init__(self, url):
        super().__init__()
        self.setWindowTitle('GT Studio — Video editor')
        self.resize(1460, 930)
        self.state = None
        self.selection = None
        self.current_frame = 0
        self.current_page = 'Edit'
        self.subtitle_id = None
        self.transition_id = None
        self.transport_revision = 0
        self.transport_session_id = None
        self.pending_transport_play = False
        self.follow_transport_playing = False
        self.loaded_path = None
        self.state_signature = ''
        self.render_timer = QTimer(self)
        self.render_timer.setInterval(1000)
        self.render_jobs = {}
        self.preview_submitting = False
        self.render_polling = set()
        self.playback_mode = "source"
        self.preview_path = None
        self.preview_signature = None
        self.pending_seek_ms = None
        self.pause_on_load = False
        self.render_timer.timeout.connect(self.check_render)
        self.client = RpcClient(url)
        self.client.state_received.connect(self.accept_state)
        self.client.transport_received.connect(self.accept_transport)
        self.client.failed.connect(self.show_error)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.video = QVideoWidget()
        self.video.setMinimumSize(360, 220)
        self.player.setVideoOutput(self.video)
        self.player.positionChanged.connect(self.position_changed)
        self.player.mediaStatusChanged.connect(self.media_ready)
        self.player.playbackStateChanged.connect(self.playback_state_changed)
        self.player.errorOccurred.connect(lambda *args: self.statusBar().showMessage(self.player.errorString(), 10000))
        self.build_ui()
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.client.poll)
        self.poll_timer.timeout.connect(self.client.poll_transport)
        self.poll_timer.start(700)
        self.client.poll()
        self.client.poll_transport()
        self.transport_timer = QTimer(self)
        self.transport_timer.timeout.connect(self.report_transport)
        self.transport_timer.start(1000)

    def button(self, text, action, accent=False):
        b = QPushButton(text)
        b.clicked.connect(action)
        if accent:
            b.setObjectName('accent')
        return b

    def section(self, text):
        label = QLabel(text)
        label.setObjectName('section')
        return label

    def build_ui(self):
        toolbar = QToolBar('Project')
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        brand = QLabel('  GT STUDIO  ')
        brand.setObjectName('brand')
        toolbar.addWidget(brand)
        for label, callback in [('New', self.new_project), ('Open', self.open_project), ('Save', lambda: self.rpc('save_project')), ('Save as', self.save_as), ('Import media', self.import_media), ('Undo', lambda: self.rpc('undo')), ('Redo', lambda: self.rpc('redo'))]:
            toolbar.addWidget(self.button(label, callback))
        self.project_name = QLabel('  No project')
        toolbar.addWidget(self.project_name)
        for shortcut, callback in [('Ctrl+N', self.new_project), ('Ctrl+O', self.open_project), ('Ctrl+S', lambda: self.rpc('save_project')), ('Ctrl+I', self.import_media), ('Ctrl+Z', lambda: self.rpc('undo')), ('Ctrl+Shift+Z', lambda: self.rpc('redo')), ('Space', self.toggle_play), ('Ctrl+B', self.split_clip)]:
            action = QAction(self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(callback)
            self.addAction(action)
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(7)
        self.notice = QLabel('EDIT  /  Source playback · timeline changes are shared live with MCP')
        self.notice.setStyleSheet('color:#a4b3c9; padding:5px;')
        outer.addWidget(self.notice)
        vertical = QSplitter(Qt.Orientation.Vertical)
        upper = QSplitter(Qt.Orientation.Horizontal)
        pool = QWidget()
        pl = QVBoxLayout(pool)
        pl.setContentsMargins(0, 0, 4, 0)
        pl.addWidget(self.section('MEDIA POOL'))
        self.media_list = QListWidget()
        self.media_list.itemDoubleClicked.connect(lambda item: self.preview_media(item.data(Qt.ItemDataRole.UserRole)))
        pl.addWidget(self.media_list)
        pl.addWidget(self.button('+ Import files', self.import_media))
        pl.addWidget(self.button('Append selected to timeline', self.append_selected, True))
        self.pool_tabs = QTabWidget()
        self.pool_tabs.addTab(pool, 'Media')
        self.pool_tabs.addTab(self.create_subtitle_panel(), 'Subtitles')
        upper.addWidget(self.pool_tabs)
        viewer = QWidget()
        vl = QVBoxLayout(viewer)
        vl.setContentsMargins(6, 0, 6, 0)
        self.viewer_label = self.section('SOURCE VIEWER')
        vl.addWidget(self.viewer_label)
        vl.addWidget(self.video, 1)
        transport = QHBoxLayout()
        transport.addStretch()
        transport.addWidget(self.button('−1', lambda: self.seek_frame(self.current_frame - 1)))
        self.preview_button = self.button('Timeline Preview', self.build_preview, True)
        transport.addWidget(self.preview_button)
        self.play_button = self.button('▶ Play', self.toggle_play)
        transport.addWidget(self.play_button)
        transport.addWidget(self.button('Stop', self.stop))
        transport.addWidget(self.button('+1', lambda: self.seek_frame(self.current_frame + 1)))
        self.tc = QLabel('00:00:00:00')
        self.tc.setObjectName('timecode')
        transport.addWidget(self.tc)
        transport.addStretch()
        vl.addLayout(transport)
        self.preview_hint = QLabel('Double-click media for source playback. Timeline Preview renders all tracks, gaps, effects and audio.')
        self.preview_hint.setWordWrap(True)
        vl.addWidget(self.preview_hint)
        upper.addWidget(viewer)
        inspector = QWidget()
        il = QVBoxLayout(inspector)
        il.setContentsMargins(4, 0, 0, 0)
        il.addWidget(self.section('INSPECTOR'))
        self.selection_label = QLabel('Select a timeline clip')
        self.selection_label.setWordWrap(True)
        il.addWidget(self.selection_label)
        form = QFormLayout()
        self.clip_start = QSpinBox()
        self.clip_in = QSpinBox()
        self.clip_out = QSpinBox()
        for widget in [self.clip_start, self.clip_in, self.clip_out]:
            widget.setRange(0, 999999999)
        for label, widget in [('Start frame', self.clip_start), ('Source in', self.clip_in), ('Source out', self.clip_out)]:
            form.addRow(label, widget)
        self.clip_speed = QDoubleSpinBox()
        self.clip_speed.setRange(-1600, 1600)
        self.clip_speed.setSingleStep(25)
        self.clip_speed.setSuffix(' %')
        self.clip_speed.setValue(100)
        self.pitch_correction = QCheckBox('Preserve pitch')
        self.pitch_correction.setChecked(True)
        self.ripple_speed = QCheckBox('Ripple following clips')
        form.addRow('Speed / reverse', self.clip_speed)
        form.addRow('', self.pitch_correction)
        form.addRow('', self.ripple_speed)
        speed_hint = QLabel('100% original · negative reverse · 0% freeze')
        speed_hint.setWordWrap(True)
        il.addWidget(speed_hint)
        self.properties = {}
        for name, label, low, high, default, step in [('volume', 'Volume', 0, 10, 1, .1), ('exposure', 'Exposure (EV)', -10, 10, 0, .1), ('contrast', 'Contrast', 0, 10, 1, .1), ('saturation', 'Saturation', 0, 10, 1, .1), ('gamma', 'Gamma', .1, 10, 1, .1), ('opacity', 'Opacity', 0, 1, 1, .05), ('scale', 'Scale', .1, 10, 1, .1), ('x', 'Position X (px)', -1000000, 1000000, 0, 1), ('y', 'Position Y (px)', -1000000, 1000000, 0, 1), ('rotation', 'Rotation (°)', -360000, 360000, 0, 1)]:
            widget = QDoubleSpinBox()
            widget.setRange(low, high)
            widget.setSingleStep(step)
            widget.setValue(default)
            self.properties[name] = widget
            form.addRow(label, widget)
        for name, label in [('fade_in_frames', 'Fade in (frames)'), ('fade_out_frames', 'Fade out (frames)')]:
            widget = QSpinBox()
            widget.setRange(0, 999999999)
            self.properties[name] = widget
            form.addRow(label, widget)
        self.property_defaults = {name: widget.value() for name, widget in self.properties.items()}
        il.addLayout(form)
        il.addWidget(self.button('Apply clip timing', self.apply_timing))
        il.addWidget(self.button('Trim start to playhead', lambda: self.trim_edge('start')))
        il.addWidget(self.button('Trim end to playhead', lambda: self.trim_edge('end')))
        il.addWidget(self.button('Apply speed / reverse / freeze', self.apply_speed))
        il.addWidget(self.button('Apply image / audio', self.apply_properties))
        il.addWidget(self.button('Detach audio to track', self.detach_audio))
        il.addWidget(self.button('Detach audio and link', lambda: self.detach_audio(linked=True)))
        il.addWidget(self.button('Unlink selected clip group', self.unlink_selected))
        il.addWidget(self.button('Delete selected clip', self.delete_clip))
        il.addWidget(self.button('Ripple delete selected clip', self.ripple_delete))
        il.addWidget(self.section('CROSS DISSOLVE'))
        transition_form = QFormLayout()
        self.transition_position = QComboBox()
        self.transition_position.addItems(['end', 'start'])
        self.transition_duration = QSpinBox()
        self.transition_duration.setRange(1, 1000000)
        self.transition_duration.setValue(12)
        self.transition_alignment = QComboBox()
        self.transition_alignment.addItems(['center', 'left', 'right'])
        transition_form.addRow('Clip edge', self.transition_position)
        transition_form.addRow('Duration (frames)', self.transition_duration)
        transition_form.addRow('Alignment', self.transition_alignment)
        il.addLayout(transition_form)
        il.addWidget(self.button('Add Cross Dissolve', self.add_transition))
        self.transition_list = QListWidget()
        self.transition_list.setMinimumHeight(70)
        self.transition_list.setMaximumHeight(115)
        self.transition_list.setWordWrap(True)
        self.transition_list.currentItemChanged.connect(lambda item, previous: self.select_transition(item.data(Qt.ItemDataRole.UserRole), seek=False) if item else None)
        il.addWidget(self.transition_list)
        self.delete_transition_button = self.button('Delete selected transition', self.delete_transition)
        il.addWidget(self.delete_transition_button)
        il.addStretch()
        inspector_panel = QWidget()
        inspector_layout = QVBoxLayout(inspector_panel)
        inspector_layout.setContentsMargins(0, 0, 0, 0)
        inspector_scroll = QScrollArea()
        self.inspector_scroll = inspector_scroll
        inspector_scroll.setWidgetResizable(True)
        inspector_scroll.setWidget(inspector)
        inspector_layout.addWidget(inspector_scroll, 1)
        inspector_layout.addWidget(self.section('DELIVER'))
        inspector_layout.addWidget(QLabel('Render MP4 / ProRes MOV / WAV'))
        inspector_layout.addWidget(self.button('Export media…', self.render, True))
        upper.addWidget(inspector_panel)
        upper.setSizes([250, 900, 280])
        vertical.addWidget(upper)
        lower = QWidget()
        self.lower_panel = lower
        ll = QVBoxLayout(lower)
        ll.setContentsMargins(0, 0, 0, 0)
        tools = QHBoxLayout()
        self.timeline_label = QLabel('TIMELINE')
        tools.addWidget(self.timeline_label)
        self.timeline_choice = QComboBox()
        self.timeline_choice.setMinimumWidth(140)
        self.timeline_choice.currentIndexChanged.connect(self.switch_timeline)
        tools.addWidget(self.timeline_choice)
        tools.addStretch()
        for label, callback in [('New timeline', self.new_timeline), ('+ Video track', lambda: self.rpc('add_track', {'kind': 'video'})), ('+ Audio track', lambda: self.rpc('add_track', {'kind': 'audio'})), ('Split at playhead', self.split_clip), ('Marker', self.marker)]:
            tools.addWidget(self.button(label, callback))
        tools.addWidget(self.button('−', lambda: self.zoom(.8)))
        tools.addWidget(self.button('+', lambda: self.zoom(1.25)))
        ll.addLayout(tools)
        track_tools = QHBoxLayout()
        track_tools.addWidget(QLabel('Track:'))
        self.track_choice = QComboBox()
        self.track_choice.setMinimumWidth(160)
        self.track_choice.currentIndexChanged.connect(self.select_track_controls)
        track_tools.addWidget(self.track_choice)
        self.track_enabled = QCheckBox('Enabled')
        self.track_locked = QCheckBox('Locked')
        track_tools.addWidget(self.track_enabled)
        track_tools.addWidget(self.track_locked)
        track_tools.addWidget(self.button('Apply track state', self.apply_track_state))
        track_tools.addStretch()
        ll.addLayout(track_tools)
        self.timeline = Timeline()
        self.timeline.selected.connect(self.select_clip)
        self.timeline.subtitle_selected.connect(self.select_subtitle)
        self.timeline.transition_selected.connect(self.select_transition)
        self.timeline.seek.connect(self.seek_frame)
        self.timeline.moved.connect(lambda c, f, t: self.rpc('move_clip', {'clip_id': c, 'start_frame': f, 'track_id': t}))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.timeline)
        ll.addWidget(scroll)
        from .fusion_ui import FusionPanel
        self.lower_pages = QStackedWidget()
        self.lower_pages.addWidget(lower)
        self.fusion_panel = FusionPanel(self.rpc, lambda clip_id: self.select_clip(clip_id, preview=False), lambda: self.current_frame)
        self.lower_pages.addWidget(self.fusion_panel)
        vertical.addWidget(self.lower_pages)
        vertical.setSizes([540, 280])
        outer.addWidget(vertical, 1)
        pages = QHBoxLayout()
        self.page_buttons = {}
        for page in ['Media', 'Photo', 'Cut', 'Edit', 'Fusion', 'Color', 'Fairlight', 'Deliver']:
            b = self.button(page, lambda checked=False, p=page: self.set_page(p))
            b.setCheckable(True)
            b.setChecked(page == 'Edit')
            self.page_buttons[page] = b
            pages.addWidget(b)
        outer.addLayout(pages)
        self.setCentralWidget(root)
        self.statusBar().showMessage('Connecting to shared editing service…')

    def rpc(self, action, params=None, callback=None):
        self.statusBar().showMessage(f'{action.replace("_", " ")}…')
        self.client.rpc(action, params, callback or (lambda result: self.statusBar().showMessage(f'{action.replace("_", " ")} completed', 5000)))

    def show_error(self, error):
        self.preview_button.setEnabled(True)
        if self.preview_button.text() == 'Rendering preview…':
            self.preview_button.setText('Timeline Preview')
        self.statusBar().showMessage(error, 15000)
        QMessageBox.warning(self, 'Operation failed', error)

    def accept_state(self, state):
        if isinstance(state, dict) and 'project' in state:
            state = state['project']
        signature = json.dumps(state, sort_keys=True)
        if signature == self.state_signature:
            return
        if self.preview_signature and self.preview_signature != signature:
            self.preview_signature = None
            if self.playback_mode == 'timeline':
                if self.follow_transport_playing and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                    self.pending_transport_play = True
                self.player.pause()
                self.play_button.setText('▶ Play')
                self.playback_mode = 'source'
                self.loaded_path = None
            self.preview_button.setText('Refresh Timeline Preview')
            self.preview_hint.setText('Timeline changed. Refresh Timeline Preview to view the latest edit.')
            self.viewer_label.setText('TIMELINE PREVIEW · out of date')
        if self.state and state and self.state.get('id') != state.get('id'):
            self.player.stop()
            self.player.setSource(QUrl())
            self.loaded_path = None
            self.selection = None
            self.current_frame = 0
            self.timeline.frame = 0
            self.tc.setText('00:00:00:00')
        self.state_signature = signature
        self.state = state
        self.project_name.setText('  ' + ((state or {}).get('name') or 'No project'))
        self.setWindowTitle(f'{(state or {}).get("name", "Untitled")} — GT Studio')
        current = self.media_list.currentItem()
        selected_id = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.media_list.clear()
        for media in values((state or {}).get('media')):
            seconds = media.get('duration_seconds', media.get('duration', 0))
            try:
                detail = f'{float(seconds):.1f}s'
            except (ValueError, TypeError):
                detail = ''
            item = QListWidgetItem(f'{media.get("name") or Path(media.get("path", "Media")).name}\n{detail}  {media.get("width", "")} × {media.get("height", "")}')
            item.setData(Qt.ItemDataRole.UserRole, media['id'])
            self.media_list.addItem(item)
            if media['id'] == selected_id:
                self.media_list.setCurrentItem(item)
        self.timeline.set_state(state)
        self.lower_panel.setMinimumHeight(320 if timeline_of(state).get('subtitles') else 260)
        tl = timeline_of(state)
        self.timeline_choice.blockSignals(True)
        self.timeline_choice.clear()
        for item in values((state or {}).get('timelines')):
            self.timeline_choice.addItem(item.get('name', 'Timeline'), item['id'])
            if item['id'] == tl.get('id'):
                self.timeline_choice.setCurrentIndex(self.timeline_choice.count() - 1)
        self.timeline_choice.blockSignals(False)
        self.timeline_label.setText(f'{tl.get("name", "TIMELINE")}  ·  {fps_of(state):g} fps')
        selected_track = self.track_choice.currentData()
        self.track_choice.blockSignals(True)
        self.track_choice.clear()
        for track in tl.get('tracks', []):
            self.track_choice.addItem(f'{track["name"]} ({track["kind"]})', track['id'])
            if track['id'] == selected_track:
                self.track_choice.setCurrentIndex(self.track_choice.count() - 1)
        self.track_choice.blockSignals(False)
        self.select_track_controls()
        self.sync_subtitles()
        self.sync_transitions()
        if self.selection:
            self.select_clip(self.selection, preview=False)
        else:
            self.selection_label.setText('Select a timeline clip')
        self.fusion_panel.set_state(self.state, self.selection)
        self.statusBar().showMessage('Shared project synchronized', 2500)
        if self.pending_transport_play and has_timeline_content(self.state):
            self.build_preview()

    def select_track_controls(self):
        track = next((t for t in timeline_of(self.state).get('tracks', []) if t['id'] == self.track_choice.currentData()), None)
        self.track_enabled.setChecked(track.get('enabled', True) if track else True)
        self.track_locked.setChecked(track.get('locked', False) if track else False)

    def apply_track_state(self):
        identity = self.track_choice.currentData()
        if identity:
            self.rpc('set_track_state', {'track_id': identity, 'enabled': self.track_enabled.isChecked(), 'locked': self.track_locked.isChecked()})

    def create_subtitle_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 5, 4, 0)
        self.subtitle_list = QListWidget()
        self.subtitle_list.setWordWrap(True)
        self.subtitle_list.setMinimumHeight(90)
        self.subtitle_list.setMaximumHeight(145)
        self.subtitle_list.currentItemChanged.connect(lambda item, previous: self.select_subtitle(item.data(Qt.ItemDataRole.UserRole), seek=False) if item else None)
        layout.addWidget(self.subtitle_list)
        editor = QWidget()
        controls = QVBoxLayout(editor)
        controls.setContentsMargins(0, 0, 2, 0)
        form = QFormLayout()
        self.subtitle_start = QSpinBox()
        self.subtitle_end = QSpinBox()
        for field in [self.subtitle_start, self.subtitle_end]:
            field.setRange(0, 999999999)
        self.subtitle_end.setValue(48)
        form.addRow('Start frame', self.subtitle_start)
        form.addRow('End frame', self.subtitle_end)
        controls.addLayout(form)
        self.subtitle_text = QTextEdit()
        self.subtitle_text.setAcceptRichText(False)
        self.subtitle_text.setPlaceholderText('Subtitle text')
        self.subtitle_text.setMinimumHeight(70)
        self.subtitle_text.setMaximumHeight(95)
        controls.addWidget(self.subtitle_text)
        actions = QHBoxLayout()
        for name, callback in [('Add', self.add_subtitle), ('Apply', self.update_subtitle), ('Delete', self.delete_subtitle)]:
            actions.addWidget(self.button(name, callback))
        controls.addLayout(actions)
        interchange = QHBoxLayout()
        interchange.addWidget(self.button('Import SRT', self.import_subtitles))
        interchange.addWidget(self.button('Export SRT', self.export_subtitles))
        controls.addLayout(interchange)
        controls.addWidget(self.section('SUBTITLE STYLE'))
        style_form = QFormLayout()
        self.subtitle_font = QLineEdit('Arial')
        self.subtitle_color = QLineEdit('#FFFFFF')
        self.subtitle_position = QComboBox()
        self.subtitle_position.addItems(['bottom', 'center', 'top'])
        self.subtitle_style_numbers = {}
        style_form.addRow('Font', self.subtitle_font)
        for key, label, lower, upper, default in [('font_size', 'Size', 1, 500, 36), ('margin_vertical', 'Margin', 0, 4000, 28), ('outline', 'Outline', 0, 20, 2)]:
            field = QSpinBox()
            field.setRange(lower, upper)
            field.setValue(default)
            self.subtitle_style_numbers[key] = field
            style_form.addRow(label, field)
        style_form.addRow('Color', self.subtitle_color)
        style_form.addRow('Position', self.subtitle_position)
        controls.addLayout(style_form)
        controls.addWidget(self.button('Apply subtitle style', self.apply_subtitle_style))
        controls.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(editor)
        layout.addWidget(scroll, 1)
        return panel

    def sync_subtitles(self):
        timeline = timeline_of(self.state)
        self.subtitle_list.blockSignals(True)
        self.subtitle_list.clear()
        for cue in timeline.get('subtitles', []):
            item = QListWidgetItem(f'{timecode(cue["start_frame"], fps_of(self.state))} → {timecode(cue["end_frame"], fps_of(self.state))}\n{cue["text"]}')
            item.setData(Qt.ItemDataRole.UserRole, cue['id'])
            self.subtitle_list.addItem(item)
            if cue['id'] == self.subtitle_id:
                self.subtitle_list.setCurrentItem(item)
        self.subtitle_list.blockSignals(False)
        if self.subtitle_id:
            self.select_subtitle(self.subtitle_id, seek=False, show_tab=False)
        style = timeline.get('subtitle_style', {})
        self.subtitle_font.setText(style.get('font', 'Arial'))
        self.subtitle_color.setText(style.get('color', '#FFFFFF'))
        self.subtitle_position.setCurrentText(style.get('position', 'bottom'))
        for key, field in self.subtitle_style_numbers.items():
            field.setValue(style.get(key, {'font_size': 36, 'margin_vertical': 28, 'outline': 2}[key]))

    def select_subtitle(self, cue_id, seek=True, show_tab=True):
        cue = next((cue for cue in timeline_of(self.state).get('subtitles', []) if cue['id'] == cue_id), None)
        if not cue:
            self.subtitle_id = None
            self.timeline.subtitle_selection = None
            self.timeline.update()
            return
        self.subtitle_id = cue_id
        self.subtitle_list.blockSignals(True)
        for index in range(self.subtitle_list.count()):
            item = self.subtitle_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == cue_id:
                self.subtitle_list.setCurrentItem(item)
                break
        self.subtitle_list.blockSignals(False)
        self.timeline.subtitle_selection = cue_id
        self.timeline.update()
        self.subtitle_start.setValue(cue['start_frame'])
        self.subtitle_end.setValue(cue['end_frame'])
        self.subtitle_text.setPlainText(cue['text'])
        if show_tab:
            self.pool_tabs.setCurrentIndex(1)
        if seek:
            self.seek_frame(cue['start_frame'])

    def add_subtitle(self):
        self.rpc('add_subtitle', {'start_frame': self.subtitle_start.value(), 'end_frame': self.subtitle_end.value(), 'text': self.subtitle_text.toPlainText()}, lambda cue: setattr(self, 'subtitle_id', cue['id']))

    def update_subtitle(self):
        if self.subtitle_id:
            self.rpc('update_subtitle', {'cue_id': self.subtitle_id, 'start_frame': self.subtitle_start.value(), 'end_frame': self.subtitle_end.value(), 'text': self.subtitle_text.toPlainText()})

    def delete_subtitle(self):
        if self.subtitle_id:
            self.rpc('delete_subtitle', {'cue_id': self.subtitle_id})
            self.subtitle_id = None

    def import_subtitles(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Import subtitles', '', 'SubRip subtitles (*.srt)')
        if path:
            self.rpc('import_subtitles', {'path': path})

    def export_subtitles(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Export subtitles', 'subtitles.srt', 'SubRip subtitles (*.srt)')
        if path:
            if Path(path).suffix.lower() != '.srt':
                path += '.srt'
            self.rpc('export_subtitles', {'path': path})

    def apply_subtitle_style(self):
        properties = {key: field.value() for key, field in self.subtitle_style_numbers.items()}
        properties.update(font=self.subtitle_font.text(), color=self.subtitle_color.text(), position=self.subtitle_position.currentText())
        self.rpc('set_subtitle_style', {'properties': properties})

    def new_project(self):
        name, ok = QInputDialog.getText(self, 'New project', 'Project name:')
        if ok and name.strip():
            self.rpc('create_project', {'name': name.strip()})

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Open GT Studio project', '', 'Project (*.json);;All files (*)')
        if path:
            self.rpc('open_project', {'path': path})

    def save_as(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save project as', '', 'GT Studio project (*.json)')
        if path:
            self.rpc('save_project', {'path': path})

    def switch_timeline(self, index):
        timeline_id = self.timeline_choice.itemData(index)
        if timeline_id:
            self.selection = None
            self.rpc('set_active_timeline', {'timeline_id': timeline_id})

    def import_media(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Import media', '', 'Media (*.mp4 *.mov *.mkv *.avi *.webm *.wav *.mp3 *.flac *.m4a *.png *.jpg *.jpeg);;All files (*)')
        for path in paths:
            self.rpc('import_media', {'path': path})

    def new_timeline(self):
        name, ok = QInputDialog.getText(self, 'New timeline', 'Timeline name:')
        if ok and name.strip():
            self.rpc('create_timeline', {'name': name.strip()})

    def append_selected(self):
        item = self.media_list.currentItem()
        if item:
            self.rpc('append_clip', {'media_id': item.data(Qt.ItemDataRole.UserRole)})

    def selected_clip(self):
        return next((c for c in clips_of(self.state) if c['id'] == self.selection), None)

    def select_clip(self, clip_id, preview=True):
        self.selection = clip_id
        self.timeline.selection = clip_id
        self.timeline.update()
        clip = self.selected_clip()
        self.fusion_panel.set_state(self.state, self.selection)
        if not clip:
            self.selection_label.setText('Select a timeline clip')
            return
        media = next((m for m in values((self.state or {}).get('media')) if m['id'] == clip.get('media_id')), {})
        self.selection_label.setText(clip.get('name') or media.get('name', clip_id))
        self.clip_start.setValue(int(clip.get('start_frame', 0)))
        self.clip_in.setValue(int(clip.get('in_frame', 0)))
        self.clip_out.setValue(int(clip.get('out_frame', 1)))
        self.clip_speed.setValue(float(clip.get('speed_percentage', 100)))
        self.pitch_correction.setChecked(bool(clip.get('pitch_correction', True)))
        props = clip.get('properties', {})
        for name, widget in self.properties.items():
            value = props.get(name, clip.get(name, self.property_defaults[name]))
            widget.setValue(int(value) if isinstance(widget, QSpinBox) else float(value))
        if preview:
            self.seek_frame(int(clip.get('start_frame', 0)))
        elif requires_timeline_preview(clip) and self.playback_mode == 'source':
            self.seek_frame(self.current_frame)

    def preview_media(self, media_id):
        media = next((m for m in values((self.state or {}).get('media')) if m['id'] == media_id), None)
        if media:
            self.pending_transport_play = False
            self.follow_transport_playing = False
            self.playback_mode = 'source'
            self.selection = None
            self.timeline.selection = None
            self.timeline.update()
            self.load_media(media.get('path', ''))
            self.player.setPosition(0)
            self.viewer_label.setText('SOURCE VIEWER · ' + media.get('name', ''))

    def load_media(self, path, pause_on_load=True):
        if path and path != self.loaded_path:
            self.loaded_path = path
            self.pause_on_load = pause_on_load
            self.player.setSource(QUrl.fromLocalFile(path))

    def media_ready(self, status):
        if status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
            if self.pending_seek_ms is not None:
                self.player.setPosition(self.pending_seek_ms)
                self.pending_seek_ms = None
            if self.pause_on_load:
                self.pause_on_load = False
                # A stopped Qt/FFmpeg player loads metadata but does not decode
                # a frame. Pausing after LoadedMedia primes a still preview
                # without briefly playing audio or advancing the playhead.
                if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                    self.player.pause()

    def seek_player(self, milliseconds):
        self.pending_seek_ms = milliseconds
        self.player.setPosition(milliseconds)
        if self.player.mediaStatus() in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
            self.pending_seek_ms = None

    def seek_frame(self, frame):
        self.current_frame = max(0, frame)
        self.timeline.frame = self.current_frame
        self.timeline.update()
        self.tc.setText(timecode(self.current_frame, fps_of(self.state)))
        if self.playback_mode == 'timeline' and self.preview_signature == self.state_signature:
            self.seek_player(round(self.current_frame / fps_of(self.state) * 1000))
            return
        if any(item['start_frame'] <= frame < item['end_frame'] for item in timeline_of(self.state).get('transitions', [])):
            if self.preview_signature == self.state_signature and self.preview_path:
                self.activate_preview(self.preview_path)
            else:
                self.player.pause()
                self.playback_mode = 'retime_wait'
                self.loaded_path = None
                self.player.setSource(QUrl())
                self.preview_hint.setText('Rendering the Cross Dissolve for timeline playback…')
                self.build_preview()
            return
        candidates = [c for c in clips_of(self.state) if int(c.get('start_frame', 0)) <= frame < int(c.get('start_frame', 0)) + duration(c)]
        clip = next((c for c in candidates if c['id'] == self.selection), candidates[-1] if candidates else None)
        if clip:
            if requires_timeline_preview(clip):
                if self.preview_signature == self.state_signature and self.preview_path:
                    self.activate_preview(self.preview_path)
                else:
                    self.player.pause()
                    self.playback_mode = 'retime_wait'
                    self.loaded_path = None
                    self.player.setSource(QUrl())
                    self.preview_hint.setText('Speed, reverse and freeze require a rendered timeline preview. Building the current edit…')
                    self.build_preview()
                return
            media = next((m for m in values((self.state or {}).get('media')) if m['id'] == clip.get('media_id')), {})
            self.load_media(media.get('path', ''))
            source_frame = frame - int(clip.get('start_frame', 0)) + int(clip.get('in_frame', 0))
            self.seek_player(round(source_frame / fps_of(self.state) * 1000))

    def position_changed(self, milliseconds):
        if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            return
        clip = self.selected_clip() if self.playback_mode == 'source' else None
        source_frame = round(milliseconds / 1000 * fps_of(self.state))
        frame = source_frame
        if clip:
            frame = int(clip.get('start_frame', 0)) + source_frame - int(clip.get('in_frame', 0))
            if source_frame >= int(clip.get('out_frame', 1)):
                self.player.pause()
                self.play_button.setText('▶ Play')
        self.current_frame = max(0, frame)
        self.timeline.frame = self.current_frame
        self.timeline.update()
        self.tc.setText(timecode(self.current_frame, fps_of(self.state)))

    def playback_state_changed(self, state):
        if hasattr(self, 'play_button'):
            self.play_button.setText('Ⅱ Pause' if state == QMediaPlayer.PlaybackState.PlayingState else '▶ Play')
            self.report_transport()

    def toggle_play(self):
        self.follow_transport_playing = False
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.play_button.setText('▶ Play')
        else:
            clip = self.selected_clip()
            if self.playback_mode == 'retime_wait' or (clip and requires_timeline_preview(clip) and self.playback_mode != 'timeline'):
                self.pending_transport_play = True
                self.seek_frame(self.current_frame)
                if self.playback_mode != 'timeline':
                    self.build_preview()
                return
            self.player.play()
            self.play_button.setText('Ⅱ Pause')

    def stop(self):
        self.follow_transport_playing = False
        self.pending_transport_play = False
        self.player.pause()
        self.play_button.setText('▶ Play')
        self.seek_frame(0)

    def apply_timing(self):
        if self.selection:
            clip = self.selected_clip()
            if clip:
                params = {'clip_id': self.selection, 'start_frame': self.clip_start.value()}
                if self.clip_in.value() != clip['in_frame']:
                    params['in_frame'] = self.clip_in.value()
                if self.clip_out.value() != clip['out_frame']:
                    params['out_frame'] = self.clip_out.value()
                self.rpc('trim_clip', params)

    def trim_edge(self, edge):
        if self.selection:
            self.rpc('trim_clip_edge', {'clip_id': self.selection, 'edge': edge,
                                        'frame': self.current_frame})

    def apply_speed(self):
        if self.selection:
            params = {
                'clip_id': self.selection, 'percentage': self.clip_speed.value(),
                'ripple': self.ripple_speed.isChecked(),
                'pitch_correction': self.pitch_correction.isChecked(),
            }
            clip = self.selected_clip()
            if params['percentage'] == 0 and clip:
                start = clip.get('start_frame', 0)
                if start <= self.current_frame < start + duration(clip):
                    params['freeze_frame'] = self.current_frame
            self.rpc('set_clip_speed', params, self.speed_applied)

    def speed_applied(self, clip):
        # An interior freeze returns a new tail; subsequent edits target that tail.
        self.select_clip(clip['id'], preview=False)

    def sync_transitions(self):
        self.transition_list.blockSignals(True)
        self.transition_list.clear()
        found = False
        for transition in timeline_of(self.state).get('transitions', []):
            item = QListWidgetItem(f'Cross Dissolve · {transition["duration_frames"]} frames\n{timecode(transition["cut_frame"], fps_of(self.state))} · {transition["alignment"]}')
            item.setData(Qt.ItemDataRole.UserRole, transition['id'])
            self.transition_list.addItem(item)
            if transition['id'] == self.transition_id:
                self.transition_list.setCurrentItem(item)
                found = True
        self.transition_list.blockSignals(False)
        if not found:
            self.transition_id = None
            self.timeline.transition_selection = None
        self.timeline.update()

    def select_transition(self, transition_id, seek=True):
        transition = next((item for item in timeline_of(self.state).get('transitions', []) if item['id'] == transition_id), None)
        if not transition:
            return
        self.transition_id = transition_id
        self.timeline.transition_selection = transition_id
        self.timeline.update()
        self.transition_duration.setValue(transition['duration_frames'])
        self.transition_alignment.setCurrentText(transition['alignment'])
        self.transition_list.blockSignals(True)
        for index in range(self.transition_list.count()):
            item = self.transition_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == transition_id:
                self.transition_list.setCurrentItem(item)
                break
        self.transition_list.blockSignals(False)
        self.inspector_scroll.ensureWidgetVisible(self.delete_transition_button)
        if seek:
            self.seek_frame(transition['cut_frame'])

    def add_transition(self):
        if self.selection:
            self.rpc('add_transition', {
                'clip_id': self.selection, 'position': self.transition_position.currentText(),
                'duration_frames': self.transition_duration.value(),
                'alignment': self.transition_alignment.currentText(), 'type': 'Cross Dissolve',
            }, lambda transition: setattr(self, 'transition_id', transition['id']))
        else:
            self.statusBar().showMessage('Select a video clip before adding a Cross Dissolve.', 6000)

    def delete_transition(self):
        if self.transition_id:
            self.rpc('delete_transition', {'transition_id': self.transition_id})
            self.transition_id = None

    def apply_properties(self):
        if self.selection:
            self.rpc('set_clip_properties', {'clip_id': self.selection, 'properties': {name: widget.value() for name, widget in self.properties.items()}})

    def split_clip(self):
        if self.selection:
            self.rpc('split_clip', {'clip_id': self.selection, 'frame': self.current_frame})

    def detach_audio(self, linked=False):
        if self.selection:
            self.rpc('detach_audio', {'clip_id': self.selection, 'linked': linked},
                     lambda result: self.select_clip(result['audio']['id'], preview=False))

    def unlink_selected(self):
        if self.selection:
            self.rpc('unlink_clips', {'clip_id': self.selection})

    def delete_clip(self):
        if self.selection:
            self.rpc('delete_clip', {'clip_id': self.selection})
            self.selection = None

    def ripple_delete(self):
        if self.selection:
            self.rpc('ripple_delete', {'clip_id': self.selection})
            self.selection = None

    def marker(self):
        label, ok = QInputDialog.getText(self, 'Add marker', 'Marker label:')
        if ok:
            self.rpc('add_marker', {'frame': self.current_frame, 'label': label})

    def render(self):
        path, selected_filter = QFileDialog.getSaveFileName(
            self, 'Export timeline', str(Path.home() / 'Movies' / 'GT Studio-export'),
            'MP4 H.264 / AAC (*.mp4);;MOV ProRes HQ / PCM (*.mov);;WAV PCM audio (*.wav)')
        if path:
            suffix = Path(path).suffix.lower().lstrip('.')
            selected_format = 'mov' if '*.mov' in selected_filter else 'wav' if '*.wav' in selected_filter else 'mp4'
            output_format = suffix if suffix in ('mp4', 'mov', 'wav') else selected_format
            if suffix not in ('mp4', 'mov', 'wav'):
                path = str(Path(path).with_suffix('.' + output_format))
            self.rpc('submit_render', {'output': path, 'format': output_format}, lambda job: self.render_submitted(job, 'export'))

    def build_preview(self):
        if not self.state or not has_timeline_content(self.state):
            self.statusBar().showMessage('Add clips or subtitles before building a preview.', 6000)
            return
        from .fusion import render_order
        incomplete = []
        for track in timeline_of(self.state).get('tracks', []):
            if track['kind'] == 'video' and track.get('enabled', True):
                for clip in track['clips']:
                    if 'fusion_graph' in clip:
                        _, errors = render_order(clip['fusion_graph'])
                        incomplete.extend(errors)
        if incomplete:
            self.player.pause()
            self.player.setSource(QUrl())
            self.loaded_path = None
            self.playback_mode = 'retime_wait'
            self.preview_hint.setText('Connect the Fusion output before previewing: ' + '; '.join(incomplete))
            self.preview_button.setText('Timeline Preview')
            return
        if self.preview_signature == self.state_signature and self.preview_path:
            self.activate_preview(self.preview_path)
            return
        if self.preview_submitting or any(job['kind'] == 'preview' for job in self.render_jobs.values()):
            self.statusBar().showMessage('Timeline preview is still rendering…', 6000)
            return
        directory = Path(__file__).resolve().parent.parent / 'workspace' / 'previews'
        path = directory / f'{self.state["id"]}-{uuid.uuid4().hex[:12]}.mp4'
        signature = self.state_signature
        # Latch before issuing HTTP: seek and play can request the same preview
        # within one transport callback, before either submit response arrives.
        self.preview_submitting = True
        self.preview_button.setEnabled(False)
        self.preview_button.setText('Rendering preview…')
        self.client.rpc('submit_render', {'output': str(path)},
                        lambda job: self.render_submitted(job, 'preview', signature),
                        on_error=self.preview_submission_failed)

    def preview_submission_failed(self, error):
        self.preview_submitting = False
        self.preview_button.setEnabled(True)
        self.preview_button.setText('Timeline Preview')

    def render_submitted(self, result, kind='export', signature=None):
        if kind == 'preview':
            self.preview_submitting = False
        self.render_jobs[result['id']] = {'kind': kind, 'signature': signature}
        self.render_timer.start()
        self.statusBar().showMessage(f'{kind.title()} rendering in background…')

    def check_render(self):
        for job_id in list(self.render_jobs):
            if job_id not in self.render_polling:
                self.render_polling.add(job_id)
                self.client.rpc('get_render_job', {'job_id': job_id}, self.render_status)

    def render_status(self, job):
        job_id = job['id']
        self.render_polling.discard(job_id)
        info = self.render_jobs.get(job_id)
        if not info:
            return
        status = job.get('status')
        if status not in ('completed', 'failed'):
            self.statusBar().showMessage(f'{info["kind"].title()} rendering in background…')
            return
        self.render_jobs.pop(job_id, None)
        if not self.render_jobs:
            self.render_timer.stop()
        if info['kind'] == 'preview':
            self.preview_button.setEnabled(True)
            self.preview_button.setText('Timeline Preview')
        if status == 'failed':
            self.show_error(job.get('error', 'Render failed'))
        elif info['kind'] == 'preview':
            if info['signature'] == self.state_signature:
                self.preview_signature = info['signature']
                self.preview_path = job['output']
                self.activate_preview(job['output'])
            else:
                self.preview_button.setText('Refresh Timeline Preview')
                self.preview_hint.setText('Timeline changed during render. Refresh the preview for the latest edit.')
                if self.pending_transport_play or self.playback_mode == 'retime_wait':
                    self.build_preview()
        else:
            QMessageBox.information(self, 'Export complete', f'Video exported to:\n{job.get("output", "")}')

    def activate_preview(self, path):
        should_play = (self.pending_transport_play or self.follow_transport_playing or
                       self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
        self.player.pause()
        self.play_button.setText('▶ Play')
        self.playback_mode = 'timeline'
        self.load_media(path, pause_on_load=not should_play)
        self.seek_frame(self.current_frame)
        self.viewer_label.setText('TIMELINE PREVIEW · all tracks / rendered snapshot')
        self.statusBar().showMessage('Timeline preview ready', 6000)
        self.preview_hint.setText('Rendered timeline preview includes gaps, track compositing, clip colors and mixed audio. Editing requires refresh.')
        if should_play:
            self.pending_transport_play = False
            self.player.play()

    def accept_transport(self, transport):
        if not isinstance(transport, dict):
            return
        session_id = transport.get('session_id')
        if session_id and session_id != self.transport_session_id:
            if self.transport_session_id is not None:
                # A new renderer may produce different pixels for the same
                # project; do not reuse a completed preview from its old session.
                self.preview_signature = None
                self.preview_path = None
                if self.playback_mode == 'timeline':
                    self.player.pause()
                    self.viewer_label.setText('TIMELINE PREVIEW · refresh required')
            self.transport_session_id = session_id
            self.transport_revision = 0
            self.pending_transport_play = False
            self.follow_transport_playing = False
        # State and transport use independent HTTP requests. A new project's
        # commands must wait until its state arrives, otherwise accept_state's
        # project reset can overwrite an already-acknowledged seek.
        if 'project_id' in transport and transport['project_id'] != (self.state or {}).get('id'):
            return
        requests = transport.get('requests') or [transport.get('requested', {})]
        consumed = False
        for request in sorted(requests, key=lambda item: item.get('revision', 0)):
            revision = request.get('revision', 0)
            if revision <= self.transport_revision:
                continue
            changed = request.get('changed')
            if changed == 'page' and request.get('page') in self.page_buttons:
                self.set_page(request['page'])
            elif changed == 'frame':
                self.seek_frame(int(request.get('frame', 0)))
            elif changed == 'playback':
                playback = request.get('playback', 'paused')
                self.follow_transport_playing = playback == 'playing'
                self.pending_transport_play = playback == 'playing'
                if playback == 'playing':
                    if self.preview_signature == self.state_signature and self.preview_path:
                        if self.playback_mode != 'timeline':
                            self.activate_preview(self.preview_path)
                        else:
                            self.pending_transport_play = False
                            self.player.play()
                    elif self.state and has_timeline_content(self.state):
                        self.build_preview()
                elif playback == 'stopped':
                    self.stop()
                else:
                    self.player.pause()
            self.transport_revision = revision
            consumed = True
        if consumed:
            self.report_transport()

    def report_transport(self):
        # Heartbeat observations are distinct from requests. Reporting never refreshes
        # /state or /transport, so it cannot recursively generate another heartbeat.
        states = {QMediaPlayer.PlaybackState.PlayingState: 'playing',
                  QMediaPlayer.PlaybackState.PausedState: 'paused',
                  QMediaPlayer.PlaybackState.StoppedState: 'stopped'}
        observation = {
            'page': self.current_page,
            'frame': int(self.current_frame),
            'playback': states.get(self.player.playbackState(), 'stopped'),
            'applied_revision': self.transport_revision,
        }
        if self.transport_session_id:
            observation['session_id'] = self.transport_session_id
        self.client.rpc('report_transport', observation, refresh=False, quiet=True)

    def zoom(self, factor):
        self.timeline.scale = max(.05, min(20, self.timeline.scale * factor))
        self.timeline.set_state(self.state)

    def set_page(self, page):
        self.current_page = page
        self.lower_pages.setCurrentIndex(1 if page == 'Fusion' else 0)
        self.fusion_panel.set_state(self.state, self.selection)
        for name, button in self.page_buttons.items():
            button.setChecked(name == page)
        descriptions = {
            'Media': 'MEDIA  /  Import and inspect source files in the media pool.',
            'Photo': 'PHOTO  /  Photo workflow is not implemented. Imported still images can be used in the timeline.',
            'Cut': 'CUT  /  Append, split, trim, move clips and add Cross Dissolve.',
            'Edit': 'EDIT  /  Source playback · timeline changes are shared live with MCP.',
            'Fusion': 'FUSION  /  MediaIn, MediaOut, Background, Transform and Merge · clip-local graph · native equivalence unverified.',
            'Color': 'COLOR  /  Basic exposure, contrast, saturation and gamma apply on export. Advanced grading is not implemented.',
            'Fairlight': 'FAIRLIGHT  /  Per-clip volume applies on export. Mixer, buses and plug-ins are not implemented.',
            'Deliver': 'DELIVER  /  Export MP4 H.264 / AAC, MOV ProRes HQ / PCM, or WAV PCM audio.',
        }
        self.notice.setText(descriptions[page])


def start_ui(url='http://127.0.0.1:18771'):
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName('GT Studio')
    app.setWindowIcon(QIcon(str(Path(__file__).parent/'assets'/'gt-studio.png')))
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    window = EditorWindow(url)
    window.show()
    return app.exec()
