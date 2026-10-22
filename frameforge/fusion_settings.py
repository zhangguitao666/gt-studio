"""Read Fusion table literals as data, without a Lua interpreter or evaluation.

This is an interchange inspector, not a Fusion renderer. Constructors and
expressions are preserved; unknown syntax fails rather than executing code.
"""
from collections import Counter
from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import re


MAX_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 200_000
MAX_DEPTH = 128
LONG_START = re.compile(r'\[(=*)\[')
IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*')
NUMBER = re.compile(r'[+-]?(?:0[xX][0-9a-fA-F]+|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)')
DECIMAL_ESCAPE = re.compile(r'[0-9]{0,2}')


@dataclass
class Table:
    tag: str | None
    entries: list

    def get(self, key, default=None):
        return next((v for k, v in self.entries if type(k) is type(key) and k == key), default)


class Parser:
    def __init__(self, text):
        self.text, self.pos, self.entries = text, 0, 0

    def error(self, message):
        line = self.text.count('\n', 0, self.pos) + 1
        column = self.pos - self.text.rfind('\n', 0, self.pos)
        raise ValueError(f'Fusion settings line {line}, column {column}: {message}')

    def long_string(self):
        m = LONG_START.match(self.text, self.pos)
        if not m:
            return None
        start = self.pos + len(m[0])
        end_token = ']' + m[1] + ']'
        end = self.text.find(end_token, start)
        if end < 0:
            self.error('unterminated long string/comment')
        self.pos = end + len(end_token)
        value = self.text[start:end]
        return value[2:] if value.startswith('\r\n') else value[1:] if value.startswith(('\n', '\r')) else value

    def skip(self):
        while self.pos < len(self.text):
            if self.text[self.pos].isspace():
                self.pos += 1
            elif self.text.startswith('--', self.pos):
                self.pos += 2
                if self.long_string() is None:
                    end = self.text.find('\n', self.pos)
                    self.pos = len(self.text) if end < 0 else end
            else:
                break

    def accept(self, token):
        self.skip()
        if self.text.startswith(token, self.pos):
            self.pos += len(token)
            return True
        return False

    def expect(self, token):
        if not self.accept(token):
            self.error(f'expected {token!r}')

    def identifier(self):
        self.skip()
        m = IDENTIFIER.match(self.text, self.pos)
        if m:
            self.pos += len(m[0])
            return m[0]
        return None

    def quoted_string(self):
        quote = self.text[self.pos]
        self.pos += 1
        output = []
        escapes = {'a': '\a', 'b': '\b', 'f': '\f', 'n': '\n', 'r': '\r', 't': '\t', 'v': '\v', '\\': '\\', '"': '"', "'": "'"}
        while self.pos < len(self.text):
            char = self.text[self.pos]
            self.pos += 1
            if char == quote:
                return ''.join(output)
            if char in '\r\n':
                self.error('unescaped newline in quoted string')
            if char != '\\':
                output.append(char)
                continue
            if self.pos >= len(self.text):
                self.error('unterminated escape')
            char = self.text[self.pos]
            self.pos += 1
            if char in escapes:
                output.append(escapes[char])
            elif char in '\r\n':
                if char == '\r' and self.text[self.pos:self.pos+1] == '\n':
                    self.pos += 1
                output.append('\n')
            elif char == 'z':
                while self.pos < len(self.text) and self.text[self.pos].isspace():
                    self.pos += 1
            elif char.isascii() and char.isdigit():
                m = DECIMAL_ESCAPE.match(self.text, self.pos)
                number = int(char + m[0]); self.pos += len(m[0])
                if number > 255:
                    self.error('decimal escape exceeds 255')
                output.append(chr(number))
            elif char == 'x':
                digits = self.text[self.pos:self.pos+2]
                if not re.fullmatch('[0-9a-fA-F]{2}', digits):
                    self.error('invalid hex escape')
                output.append(chr(int(digits, 16))); self.pos += 2
            else:
                self.error(f'unsupported string escape {char!r}')
        self.error('unterminated string')

    def value(self, depth=0):
        if depth > MAX_DEPTH:
            self.error('nesting limit exceeded')
        self.skip()
        if self.pos >= len(self.text):
            self.error('expected value')
        char = self.text[self.pos]
        if char in '\"\'':
            return self.quoted_string()
        long = self.long_string()
        if long is not None:
            return long
        if char == '{':
            return self.table(None, depth)
        m = NUMBER.match(self.text, self.pos)
        if m:
            raw = m[0]; self.pos += len(raw)
            number = int(raw, 16) if 'x' in raw.lower() else float(raw) if any(c in raw for c in '.eE') else int(raw)
            if isinstance(number, float) and not math.isfinite(number):
                self.error('non-finite number')
            return number
        tag = self.identifier()
        if tag in {'true', 'false', 'nil'}:
            return {'true': True, 'false': False, 'nil': None}[tag]
        if tag:
            if tag == 'ordered' and self.accept('('):
                self.expect(')')
                tag = 'ordered'
            self.skip()
            if self.text[self.pos:self.pos+1] == '{':
                return self.table(tag, depth)
        self.error('only literal tables, constructors and scalar data are supported')

    def table(self, tag, depth):
        self.expect('{')
        entries, seen, index = [], set(), 1
        while not self.accept('}'):
            self.skip()
            saved = self.pos
            # A long bracket string is a positional value, not an indexed key.
            if self.text[self.pos:self.pos+1] == '[' and not LONG_START.match(self.text, self.pos):
                self.pos += 1
                key = self.value(depth + 1)
                if not isinstance(key, (str, int, float, bool)):
                    self.error('table key must be scalar')
                self.expect(']'); self.expect('=')
                value = self.value(depth + 1)
            else:
                key = self.identifier()
                if key is not None and self.accept('='):
                    value = self.value(depth + 1)
                else:
                    self.pos = saved
                    key, value = index, self.value(depth + 1)
                    index += 1
            identity = ('boolean' if isinstance(key, bool) else 'number' if isinstance(key, (int, float)) else 'string', key)
            if identity in seen:
                self.error(f'duplicate table key {key!r}')
            seen.add(identity)
            entries.append((key, value)); self.entries += 1
            if self.entries > MAX_ENTRIES:
                self.error('table entry limit exceeded')
            if not self.accept(',') and not self.accept(';'):
                self.expect('}')
                break
        return Table(tag, entries)

    def parse(self):
        result = self.value()
        self.skip()
        if self.pos != len(self.text):
            self.error('trailing code is not supported')
        if not isinstance(result, Table):
            self.error('root must be a table')
        return result


def literal(value):
    """JSON-safe ordered representation preserving constructors and key types."""
    if isinstance(value, Table):
        return {'constructor': value.tag, 'entries': [{'key': k, 'value': literal(v)} for k, v in value.entries]}
    return value


def inspect_fusion_settings(path, detail='summary', offset=0, limit=25):
    if detail not in {'summary', 'nodes'} or type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Expected detail=summary/nodes, offset>=0 and limit=1..100')
    source = Path(path).expanduser().resolve()
    if source.suffix.lower() not in {'.setting', '.comp'}:
        raise ValueError('Expected a .setting or .comp file')
    with source.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Fusion settings exceeds 8 MiB limit')
    root = Parser(raw.decode('utf-8-sig')).parse()
    nodes, connections, expressions = [], [], []

    def pointer(parent, name):
        return parent + '/' + str(name).replace('~', '~0').replace('/', '~1')

    def visit(container, parent=''):
        tools = container.get('Tools')
        if not isinstance(tools, Table):
            return
        sibling_ids = {name: pointer(parent, name) for name, tool in tools.entries if isinstance(tool, Table)}
        for name, tool in tools.entries:
            if not isinstance(tool, Table):
                continue
            node_id = sibling_ids[name]
            children = tool.get('Tools')
            child_ids = {n: pointer(node_id, n) for n, v in children.entries if isinstance(v, Table)} if isinstance(children, Table) else {}
            ports = []
            for field in ('Inputs', 'Outputs'):
                block = tool.get(field)
                if not isinstance(block, Table):
                    continue
                for port_name, port in block.entries:
                    if not isinstance(port, Table):
                        continue
                    ports.append({'name': port_name, 'direction': field, 'constructor': port.tag, 'data': literal(port)})
                    op = port.get('SourceOp')
                    if isinstance(op, str):
                        # Macro interfaces refer to children; ordinary Inputs refer to siblings.
                        scope = child_ids if port.tag in {'InstanceInput', 'InstanceOutput'} else sibling_ids
                        target = scope.get(op)
                        connections.append({'node_id': node_id, 'port': port_name, 'direction': field,
                                            'source_op': op, 'source_port': port.get('Source'),
                                            'source_node_id': target, 'resolved': target is not None})
                    expression = port.get('Expression')
                    if isinstance(expression, str):
                        expressions.append({'node_id': node_id, 'port': port_name, 'expression': expression, 'evaluated': False})
            nodes.append({'id': node_id, 'name': name, 'class': tool.tag, 'parent_id': parent or None,
                          'ports': ports, 'attributes': {str(k): literal(v) for k, v in tool.entries if k not in {'Inputs', 'Outputs', 'Tools', 'CustomData'}},
                          'custom_data_present': tool.get('CustomData') is not None})
            visit(tool, node_id)

    visit(root)
    names = {}
    for node in nodes:
        names.setdefault(node['name'], []).append(node['id'])
    for edge in connections:
        edge['candidate_source_node_ids'] = [] if edge['resolved'] else names.get(edge['source_op'], [])
    result = {'path': str(source), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
              'root_constructor': root.tag, 'node_count': len(nodes), 'connection_count': len(connections),
              'document_attributes': {str(k): literal(v) for k, v in root.entries if k not in {'Tools', 'CustomData'}},
              'classes': dict(sorted(Counter(node['class'] or '(untyped)' for node in nodes).items())),
              'unresolved_connection_count': sum(not c['resolved'] for c in connections),
              'expression_count': len(expressions), 'execution_performed': False, 'render_supported': False,
              'limitations': ['Literal table syntax only; no Lua execution, expression evaluation or node rendering.',
                              'CustomData historical settings are not traversed as active nodes.',
                              'Resolved means same-scope or explicit macro-child declaration; cross-scope name matches are candidates only, without native binding verification.',
                              'Connections cover Inputs/Outputs SourceOp declarations only; external or implicit dependencies remain unknown.']}
    if detail == 'nodes':
        page = nodes[offset:offset+limit]
        ids = {node['id'] for node in page}
        result.update(nodes=page, connections=[c for c in connections if c['node_id'] in ids],
                      expressions=[e for e in expressions if e['node_id'] in ids],
                      coverage={'offset': offset, 'returned': len(page), 'total': len(nodes),
                                'next_offset': offset + len(page) if offset + len(page) < len(nodes) else None})
    return result
