#!/usr/bin/env python3
"""
project.py -- audioguidegui Phase 2 (delivered as project_v1.py)
JSON project model: schema, load/save, and an importer that converts native
audioguide options files (.py) into project dicts.

Schema (aggui_version 0.2):
{
  "aggui_version": "0.2",
  "kind": "project" | "template",
  "name": str,
  "notes": str,                       # free text; importer stores the leading
                                      # comment banner of an options file here
  "options": {NAME: value, ...},      # flat options THAT THE FILE/USER SET
                                      # (not the full defaults set)
  "target":      {"args": [...], "kwargs": {...}} | None,   # tsf()
  "corpus":      [ {"args": [...], "kwargs": {...}}, ... ], # csf()
  "search":      [ {"args": [...], "kwargs": {...}}, ... ], # spass()
  "superimpose": {"args": [...], "kwargs": {...}} | None,   # si()
  "instruments_raw": str,             # verbatim python ("" = unset)
  "render_mode": "preview" | "wav"
}

d() objects inside spass args are encoded as:
  {"__obj__": "d", "args": ["descriptorname"], "kwargs": {...}}

## INTERPRETIVE decisions:
## - Uniform {"args","kwargs"} encoding for all object variables (the plan
##   sketch had per-object field names; args/kwargs survives every calling
##   convention found in the examples, incl. spass('parser', ...) and csf
##   segment-list first arguments).
## - "options" stores what the source file explicitly set, rather than a
##   diff against defaults.py. For hand-written examples these coincide, and
##   it preserves author intent (an explicitly-set default stays explicit).
## - render_mode is a GUI-state field derived from CSOUND_PLAY_RENDERED_FILE
##   when importing; codegen does NOT emit anything for it. The GUI writes
##   the radio choice through to options["CSOUND_PLAY_RENDERED_FILE"]
##   (wired in Phase 7).
## - Python tuples in captured values become JSON lists. audioguide treats
##   sequence options interchangeably, so this is lossless in effect.
## - Paths inside a project are resolved by audioguide relative to the
##   location of the GENERATED .py file. The GUI must generate the .py next
##   to the project file (or into a chosen run dir) so relative paths keep
##   working.
"""
import os, re, json, copy

SCHEMA_VERSION = '0.2'
STRUCTURED_NAMES = ('TARGET', 'CORPUS', 'SEARCH', 'SUPERIMPOSE', 'INSTRUMENTS')


# --------------------------------------------------------------- capture layer
class _Cap(object):
    """Stands in for tsf/csf/spass/si/d/instr/score when exec-ing an
    options file; records the call instead of doing anything."""
    def __init__(self, objname, *args, **kwargs):
        self.objname = objname
        self.args = list(args)
        self.kwargs = dict(kwargs)


def _make_capture(objname):
    def f(*args, **kwargs):
        return _Cap(objname, *args, **kwargs)
    return f


def _jsonable(v):
    """Convert a captured python value into JSON-safe structures."""
    if isinstance(v, _Cap):
        return {'__obj__': v.objname,
                'args': [_jsonable(a) for a in v.args],
                'kwargs': {k: _jsonable(x) for k, x in v.kwargs.items()}}
    if isinstance(v, tuple):
        return {'__tuple__': [_jsonable(x) for x in v]}
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        if all(isinstance(k, str) for k in v):
            return {k: _jsonable(x) for k, x in v.items()}
        # non-string keys (e.g. BACH_SLOTS_MAPPING's int keys) are stored as
        # an ordered pair list so JSON round-trips them losslessly
        return {'__dict__': [[_jsonable(k), _jsonable(x)] for k, x in v.items()]}
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    raise TypeError('cannot store value of type %s in a project: %r'
                    % (type(v).__name__, v))


def _cap_to_node(cap):
    return {'args': [_jsonable(a) for a in cap.args],
            'kwargs': {k: _jsonable(v) for k, v in cap.kwargs.items()}}


def _render_call(cap):
    """Re-render a captured instr()/score() call as python source text."""
    from gui.codegen import py_literal        # local import; no cycle at load
    parts = [py_literal(_jsonable(a)) if not isinstance(a, _Cap) else _render_call(a)
             for a in cap.args]
    parts += ['%s=%s' % (k, py_literal(_jsonable(v))) for k, v in cap.kwargs.items()]
    return '%s(%s)' % (cap.objname, ', '.join(parts))


# ------------------------------------------------------------------- importer
def import_options_py(path):
    """Parse a native audioguide options file into a project dict.
    Mirrors the exec environment of concatenativeclasses.parse_file()."""
    src = open(path, encoding='utf-8').read()
    env = {n: _make_capture(n) for n in
           ('tsf', 'csf', 'spass', 'si', 'd', 'instr', 'score')}
    captured = {}
    exec(src, env, captured)

    prj = new_project(name=os.path.splitext(os.path.basename(path))[0])

    # leading comment banner -> notes
    banner = []
    for line in src.splitlines():
        if line.strip().startswith('#'):
            banner.append(line.strip('# ').rstrip('#').strip())
        elif line.strip():
            break
    prj['notes'] = '\n'.join([b for b in banner if b])

    for name, val in captured.items():
        if name == 'TARGET':
            prj['target'] = _cap_to_node(val)
        elif name == 'SUPERIMPOSE':
            prj['superimpose'] = _cap_to_node(val)
        elif name == 'CORPUS':
            prj['corpus'] = [_cap_to_node(c) for c in val]
        elif name == 'SEARCH':
            prj['search'] = [_cap_to_node(s) for s in val]
        elif name == 'INSTRUMENTS':
            prj['instruments_raw'] = 'INSTRUMENTS = ' + _render_call(val)
        elif name.isupper():
            prj['options'][name] = _jsonable(val)
        # lowercase helper variables in an options file are ignored

    if prj['options'].get('CSOUND_PLAY_RENDERED_FILE') is False:
        prj['render_mode'] = 'wav'
    return prj


# ------------------------------------------------------------------ project io
def new_project(name='untitled'):
    return {'aggui_version': SCHEMA_VERSION, 'kind': 'project', 'name': name,
            'notes': '', 'options': {}, 'target': None, 'corpus': [],
            'search': [], 'superimpose': None, 'instruments_raw': '',
            'render_mode': 'preview'}


def load(path):
    prj = json.load(open(path, encoding='utf-8'))
    if 'aggui_version' not in prj:
        raise ValueError('%s is not an audioguidegui project file' % path)
    base = new_project()
    base.update(prj)                       # tolerate older files missing keys
    return base


def save(prj, path):
    prj = dict(prj, aggui_version=SCHEMA_VERSION)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(prj, fh, indent=1, ensure_ascii=False)
        fh.write('\n')


def new_from_template(template_prj, name):
    prj = copy.deepcopy(template_prj)
    prj['kind'] = 'project'
    prj['name'] = name
    return prj
