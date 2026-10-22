import copy
import json

import pytest

from frameforge.control import validate
from frameforge.engine import Engine
from frameforge.fusion_settings import Parser, inspect_fusion_settings, literal


GRAPH = '''Composition {
 Tools = ordered() {
  Image = Background { Inputs = { Red = Input { Value = 0.25 } } },
  Macro = MacroOperator {
   CustomData = { Settings = { Tools = { Historic = Blur {} } } },
   Inputs = { Strength = InstanceInput { SourceOp = "Image", Source = "Gain" } },
   Outputs = { Main = InstanceOutput { SourceOp = "Out", Source = "Output" } },
   Tools = ordered() {
    Image = BrightnessContrast { Inputs = {
     Gain = Input { Value = 1 },
     Input = Input { SourceOp = "External", Source = "Output" },
     Animated = Input { Expression = "time / 24" }
    } },
    Out = Transform { Inputs = { Input = Input { SourceOp = "Image", Source = "Output" } } },
    Curve = BezierSpline { KeyFrames = { [0] = { 0, RH = { 8, 0.5 } }, [24] = { 1 } } }
   }
  },
  Output = MediaOut { Inputs = { Input = Input { SourceOp = "Macro", Source = "Main" } } }
 }
}'''


def write_graph(tmp_path, text=GRAPH):
    path = tmp_path / 'graph.setting'
    path.write_text(text)
    return path


def test_nested_scopes_ports_keyframes_and_history(tmp_path):
    path = write_graph(tmp_path)
    report = inspect_fusion_settings(path, 'nodes', limit=100)
    assert report['node_count'] == 6
    assert report['connection_count'] == 5
    assert report['unresolved_connection_count'] == 1
    assert report['expression_count'] == 1
    assert report['root_constructor'] == 'Composition'
    assert report['execution_performed'] is report['render_supported'] is False
    nodes = {n['id']: n for n in report['nodes']}
    assert '/Macro/Historic' not in nodes
    assert nodes['/Macro']['custom_data_present']
    edges = {(c['node_id'], c['port']): c for c in report['connections']}
    assert edges['/Macro', 'Strength']['source_node_id'] == '/Macro/Image'
    assert edges['/Macro/Out', 'Input']['source_node_id'] == '/Macro/Image'
    assert edges['/Output', 'Input']['source_node_id'] == '/Macro'
    assert edges['/Macro/Image', 'Input']['source_node_id'] is None
    keys = nodes['/Macro/Curve']['attributes']['KeyFrames']['entries']
    assert [v['key'] for v in keys] == [0, 24]
    assert report['expressions'][0]['expression'] == 'time / 24'
    assert report['expressions'][0]['evaluated'] is False
    json.dumps(report, allow_nan=False)
    path.write_text(GRAPH.replace('SourceOp = "External"', 'SourceOp = "Output"'))
    cross_scope = inspect_fusion_settings(path, 'nodes', limit=100)
    edge = next(c for c in cross_scope['connections'] if c['node_id'] == '/Macro/Image')
    assert edge['resolved'] is False and edge['source_node_id'] is None
    assert edge['candidate_source_node_ids'] == ['/Output']


def test_pagination_is_stable_and_summary_does_not_expand_graph(tmp_path):
    path = write_graph(tmp_path)
    summary = inspect_fusion_settings(path)
    assert 'nodes' not in summary and 'connections' not in summary
    nodes = []
    offset = 0
    while offset is not None:
        page = inspect_fusion_settings(path, 'nodes', offset, 2)
        nodes.extend(page['nodes'])
        assert all(c['node_id'] in {n['id'] for n in page['nodes']} for c in page['connections'])
        offset = page['coverage']['next_offset']
    assert len(nodes) == len({n['id'] for n in nodes}) == 6
    assert inspect_fusion_settings(path, 'nodes', 100)['coverage']['next_offset'] is None


def test_lua_strings_comments_types_and_constructor_data():
    text = r'''-- heading
    { --[=[ ignored { " arbitrary ]=]
      ["long.key"] = FuID { "Gradient" },
      Escape = "a\n\065\x42\\\"", Block = [=[
multiline
text]=], Dec = -1.5e-2, Hex = 0xFF, Missing = nil, Enabled = false,
      [0] = { true }, [false] = 8
    }'''
    table = Parser(text).parse()
    assert table.get('Escape') == 'a\nAB\\"'
    assert table.get('Block') == 'multiline\ntext'
    assert table.get('Dec') == -0.015 and table.get('Hex') == 255
    assert table.get('Missing') is None and table.get('Enabled') is False
    assert table.get(0).get(1) is True
    assert table.get(False) == 8
    assert table.get('long.key').tag == 'FuID'
    assert literal(table)['constructor'] is None


@pytest.mark.parametrize('text', [
    '{ Value = os.execute("touch /tmp/not-allowed") }',
    '{}; os.execute("x")', '{ Value = 1 + 2 }', '{ Value = function() end }',
    '{ A = 1, A = 2 }', '{ [1] = 1, [1.0] = 2 }', '{ S = "\\999" }',
    '{ S = "\\q" }', '{ X = 1e9999 }', '{ A = [=[unterminated }',
    '{ X = ordered(1) {} }', '{ X = "unterminated }',
])
def test_executable_unsupported_and_ambiguous_syntax_is_rejected(text):
    with pytest.raises(ValueError, match='Fusion settings line'):
        Parser(text).parse()


def test_resource_limits_and_pagination_validation(tmp_path, monkeypatch):
    from frameforge import fusion_settings as fs
    path = write_graph(tmp_path)
    monkeypatch.setattr(fs, 'MAX_BYTES', 10)
    with pytest.raises(ValueError, match='8 MiB'):
        inspect_fusion_settings(path)
    monkeypatch.setattr(fs, 'MAX_DEPTH', 3)
    with pytest.raises(ValueError, match='nesting limit'):
        Parser('{ A = { B = { C = { D = {} } } } }').parse()
    monkeypatch.setattr(fs, 'MAX_ENTRIES', 2)
    with pytest.raises(ValueError, match='entry limit'):
        Parser('{ 1, 2, 3 }').parse()
    for params in ({'limit': 0}, {'offset': -1}, {'detail': 'execute'}, {'limit': True}):
        with pytest.raises(ValueError):
            inspect_fusion_settings(path, **params)
        with pytest.raises(ValueError):
            validate('inspect_fusion_settings', {'path': str(path), **params})


def test_inspection_needs_no_project_and_never_changes_history(tmp_path):
    engine = Engine(tmp_path)
    path = write_graph(tmp_path)
    assert engine.dispatch('inspect_fusion_settings', {'path': str(path)})['node_count'] == 6
    assert engine.project is None and engine._undo == []
    engine.dispatch('create_project', {'name': 'Keep'})
    engine.dispatch('add_marker', {'frame': 1, 'label': 'Keep marker'})
    before = copy.deepcopy((engine.project, engine._undo, engine._redo))
    engine.dispatch('inspect_fusion_settings', {'path': str(path), 'detail': 'nodes'})
    path.write_text('{ Value = dofile("untrusted.lua") }')
    with pytest.raises(ValueError):
        engine.dispatch('inspect_fusion_settings', {'path': str(path)})
    assert (engine.project, engine._undo, engine._redo) == before
