"""Native graph canvas editing the same clip data as HTTP/MCP clients."""
import json
from shiboken6 import isValid

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QPen, QPainterPath
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QPushButton, QComboBox, QLineEdit, QFormLayout, QDoubleSpinBox,
    QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsSimpleTextItem, QScrollArea, QLayout, QFileDialog)
from pathlib import Path

from .fusion import CATALOG, default_graph, render_order


class NodeItem(QGraphicsRectItem):
    def __init__(self, node, panel):
        super().__init__(0, 0, 180, 70)
        self.identity, self.panel = node['id'], panel
        self.setBrush(QColor('#29323d')); self.setPen(QPen(QColor('#718096')))
        self.setFlag(self.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(self.GraphicsItemFlag.ItemIsMovable, not panel.locked)
        self.setFlag(self.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setPos(node['position']['x'], node['position']['y'])
        title = QGraphicsSimpleTextItem(node['name'][:23], self)
        title.setBrush(QColor('#edf2f7')); title.setPos(10, 10)
        subtitle = QGraphicsSimpleTextItem(node['type'], self)
        subtitle.setBrush(QColor('#8cd6d0')); subtitle.setPos(10, 32)
        self.original = QPointF(self.pos())

    def itemChange(self, change, value):
        if change == self.GraphicsItemChange.ItemPositionHasChanged and not self.panel.reloading:
            self.panel.update_edges()
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self.pos() != self.original:
            self.panel.send('update_fusion_node', {'node_id': self.identity, 'position': {'x': self.x(), 'y': self.y()}})
            self.original = QPointF(self.pos())


class FusionPanel(QWidget):
    def __init__(self, rpc, select_clip, frame_provider=None):
        super().__init__()
        self.rpc, self.select_clip_callback = rpc, select_clip
        self.frame_provider = frame_provider or (lambda: 0)
        self.clip_start, self.clip_duration = 0, 1
        self.clip_id, self.selected_id, self.signature = None, None, None
        self.graph, self.items, self.edges = default_graph(), {}, []
        self.locked, self.reloading = False, False
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.clip_choice = QComboBox(); self.clip_choice.setMinimumWidth(220)
        self.clip_choice.currentIndexChanged.connect(lambda: self.select_clip_callback(self.clip_choice.currentData()) if self.clip_choice.currentData() else None)
        top.addWidget(self.clip_choice)
        self.type_choice = QComboBox(); self.type_choice.addItems(['Background', 'Transform', 'Merge', 'MediaIn'])
        top.addWidget(self.type_choice)
        self.add_button = QPushButton('Add node'); self.add_button.clicked.connect(self.add_node); top.addWidget(self.add_button)
        self.clear_button = QPushButton('Reset graph'); self.clear_button.clicked.connect(lambda: self.send('clear_fusion_graph')); top.addWidget(self.clear_button)
        top.addStretch(); layout.addLayout(top)
        self.status = QLabel('Select a video clip to edit its node graph.'); self.status.setWordWrap(True); layout.addWidget(self.status)
        split = QSplitter()
        self.scene = QGraphicsScene(self); self.view = QGraphicsView(self.scene)
        self.view.setBackgroundBrush(QColor('#151b24'))
        self.view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.scene.selectionChanged.connect(self.node_selected)
        split.addWidget(self.view)
        controls = QWidget(); form_outer = QVBoxLayout(controls)
        self.node_label = QLabel('Select a node'); form_outer.addWidget(self.node_label)
        self.name_edit = QLineEdit(); form_outer.addWidget(self.name_edit)
        self.parameters_form = QFormLayout(); form_outer.addLayout(self.parameters_form)
        self.parameters = {}
        self.apply_button = QPushButton('Apply node parameters'); self.apply_button.clicked.connect(self.apply); form_outer.addWidget(self.apply_button)
        self.input_choice = QComboBox(); self.source_choice = QComboBox()
        self.input_choice.currentIndexChanged.connect(self.sync_input_source)
        form_outer.addWidget(QLabel('Input port / image source'))
        form_outer.addWidget(self.input_choice); form_outer.addWidget(self.source_choice)
        self.connect_button = QPushButton('Connect'); self.connect_button.clicked.connect(self.connect); form_outer.addWidget(self.connect_button)
        self.disconnect_button = QPushButton('Disconnect'); self.disconnect_button.clicked.connect(lambda: self.send('connect_fusion_nodes', {'target_node_id': self.selected_id, 'input': self.input_choice.currentText()}) if self.input_choice.count() else None); form_outer.addWidget(self.disconnect_button)
        self.delete_button = QPushButton('Delete node'); self.delete_button.clicked.connect(lambda: self.send('delete_fusion_node', {'node_id': self.selected_id}) if self.selected_id else None); form_outer.addWidget(self.delete_button)
        self.save_frame_button = QPushButton('Save selected node PNG…'); self.save_frame_button.clicked.connect(self.save_node_frame); form_outer.addWidget(self.save_frame_button)
        form_outer.addStretch()
        form_outer.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        side = QScrollArea(); side.setWidgetResizable(True); side.setWidget(controls)
        side.setMinimumWidth(280)
        split.addWidget(side); split.setSizes([800, 280]); layout.addWidget(split, 1)
        hint = QLabel('Independent five-node subset · float32 node over · timeline/PNG output clamps to RGBA16 · native equivalence unverified. PNG checkpoints retain associated RGB samples. Use Timeline Preview to view the output.')
        hint.setWordWrap(True); layout.addWidget(hint)

    def send(self, action, params=None, callback=None):
        if self.clip_id and not self.locked:
            self.rpc(action, {'clip_id': self.clip_id, **(params or {})}, callback)

    def set_state(self, state, selection):
        videos = [(c, t) for tl in (state or {}).get('timelines', []) if tl['id'] == (state or {}).get('active_timeline_id') for t in tl['tracks'] if t['kind'] == 'video' for c in t['clips']]
        self.clip_choice.blockSignals(True); self.clip_choice.clear()
        self.clip_choice.addItem('Select video clip…', None)
        for clip, track in videos:
            self.clip_choice.addItem(f'{track["name"]} · {clip["start_frame"]} · {clip["id"]}', clip['id'])
        current = next(((c, t) for c, t in videos if c['id'] == selection), None)
        self.clip_id = current[0]['id'] if current else None
        if current:
            self.clip_start = current[0]['start_frame']
            self.clip_duration = current[0].get('duration_frames', current[0]['out_frame']-current[0]['in_frame'])
        self.clip_choice.setCurrentIndex(max(0, self.clip_choice.findData(self.clip_id)))
        self.clip_choice.blockSignals(False)
        graph = current[0].get('fusion_graph', default_graph()) if current else default_graph()
        locked = current[1].get('locked', False) if current else False
        signature = json.dumps([self.clip_id, graph, locked], sort_keys=True)
        if signature == self.signature:
            return
        changed_clip = self.signature is None or getattr(self, 'previous_clip', None) != self.clip_id
        self.previous_clip, self.signature = self.clip_id, signature
        self.graph, self.locked, self.reloading = graph, locked, True
        self.scene.clear(); self.items, self.edges = {}, []
        if current:
            for node in graph['nodes']:
                item = NodeItem(node, self); self.scene.addItem(item); self.items[node['id']] = item
            for node in graph['nodes']:
                for port, source in node['inputs'].items():
                    edge = self.scene.addPath(QPainterPath(), QPen(QColor('#64c7bb'), 2))
                    edge.setZValue(-1); self.edges.append((source, node['id'], port, edge))
            self.update_edges()
            _, errors = render_order(graph)
            self.status.setText(('LOCKED · ' if locked else '') + ('Output ready · independent node rendering' if not errors else 'Incomplete output: ' + '; '.join(errors)))
        else:
            self.status.setText('Select a video clip to edit its node graph.')
        self.reloading = False
        if changed_clip and self.items:
            self.view.fitInView(self.scene.itemsBoundingRect().adjusted(-40, -40, 40, 40), Qt.AspectRatioMode.KeepAspectRatio)
        for button in (self.add_button, self.clear_button): button.setEnabled(bool(current) and not locked)
        if self.selected_id in self.items:
            self.items[self.selected_id].setSelected(True)
        else:
            self.selected_id = None
        self.show_parameters()

    def update_edges(self):
        for source, target, port, item in self.edges:
            a = self.items[source].pos() + QPointF(180, 35)
            ports = CATALOG[next(n['type'] for n in self.graph['nodes'] if n['id'] == target)]['inputs']
            b = self.items[target].pos() + QPointF(0, 25 + 20*ports.index(port))
            path = QPainterPath(a); path.cubicTo(a+QPointF(75, 0), b-QPointF(75, 0), b); item.setPath(path)

    def node_selected(self):
        if self.reloading or not isValid(self) or not isValid(self.scene): return
        selected = self.scene.selectedItems()
        self.selected_id = selected[0].identity if selected else None
        self.show_parameters()

    def show_parameters(self):
        while self.parameters_form.rowCount(): self.parameters_form.removeRow(0)
        self.parameters = {}
        node = next((n for n in self.graph['nodes'] if n['id'] == self.selected_id), None)
        self.input_choice.clear(); self.source_choice.clear()
        self.node_label.setText(node['type'] if node else 'Select a node')
        self.name_edit.setText(node['name'] if node else '')
        if node:
            for key, value in node['parameters'].items():
                _, low, high = CATALOG[node['type']]['parameters'][key]
                field = QDoubleSpinBox(); field.setDecimals(4); field.setRange(low, high); field.setSingleStep(0.05); field.setValue(value)
                field.setMinimumHeight(28)
                self.parameters[key] = field; self.parameters_form.addRow(key, field)
            self.input_choice.addItems(CATALOG[node['type']]['inputs'])
            self.source_choice.addItem('Unconnected', None)
            for source in self.graph['nodes']:
                if source['type'] != 'MediaOut' and source['id'] != node['id']:
                    self.source_choice.addItem(source['name'], source['id'])
            self.sync_input_source()
        editable = bool(node and self.clip_id and not self.locked)
        for widget in (self.name_edit, self.apply_button, self.connect_button, self.disconnect_button, *self.parameters.values()): widget.setEnabled(editable)
        self.delete_button.setEnabled(editable and node['type'] != 'MediaOut')
        self.save_frame_button.setEnabled(bool(node and self.clip_id))

    def save_node_frame(self):
        if not self.clip_id or not self.selected_id: return
        path, _ = QFileDialog.getSaveFileName(self, 'Save node output with alpha', str(Path.home()/'Pictures'/'GT Studio node.png'), 'PNG image (*.png)')
        if not path: return
        if not Path(path).suffix: path += '.png'
        local = int(self.frame_provider())-self.clip_start
        if not 0 <= local < self.clip_duration: local=0
        self.rpc('render_fusion_frame', {'clip_id':self.clip_id,'node_id':self.selected_id,'frame':local,'output':path})

    def sync_input_source(self):
        node = next((n for n in self.graph['nodes'] if n['id'] == self.selected_id), None)
        if node:
            source = node['inputs'].get(self.input_choice.currentText())
            self.source_choice.setCurrentIndex(max(0, self.source_choice.findData(source)))

    def add_node(self):
        position = {'x': 100 + len(self.graph['nodes'])*40, 'y': 100}
        self.send('add_fusion_node', {'type': self.type_choice.currentText(), 'position': position}, lambda node: setattr(self, 'selected_id', node['id']))

    def apply(self):
        if self.selected_id:
            self.send('update_fusion_node', {'node_id': self.selected_id, 'name': self.name_edit.text(), 'parameters': {k: w.value() for k, w in self.parameters.items()}})

    def connect(self):
        if self.selected_id and self.input_choice.count() and self.source_choice.currentData():
            self.send('connect_fusion_nodes', {'target_node_id': self.selected_id, 'input': self.input_choice.currentText(), 'source_node_id': self.source_choice.currentData()})
