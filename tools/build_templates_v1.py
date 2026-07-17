#!/usr/bin/env python3
"""
build_templates_v1.py -- audioguidegui Phase 2
Converts the bundled examples/*.py options files into GUI template JSON files
in gui/templates/.

Run from the repo root:  python3 tools/build_templates_v1.py
"""
import os, sys, glob

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from gui import project

OUTDIR = os.path.join(REPO, 'gui', 'templates')
os.makedirs(OUTDIR, exist_ok=True)

made = 0
for path in sorted(glob.glob(os.path.join(REPO, 'examples', '*.py'))):
    base = os.path.basename(path)
    if base == 'api_example.py':          # not an options file
        continue
    prj = project.import_options_py(path)
    prj['kind'] = 'template'
    out = os.path.join(OUTDIR, os.path.splitext(base)[0] + '.agproj.json')
    project.save(prj, out)
    print('wrote', os.path.relpath(out, REPO))
    made += 1
print('%d templates' % made)
