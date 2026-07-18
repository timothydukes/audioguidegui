#!/usr/bin/env python3
"""
app.py -- audioguidegui Phase 4 (delivered as app_v1.py)
Entry point. Run from the repo root:
    python3 gui/app.py
or
    python3 -m gui.app
"""
import os, sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

import wx                                    # noqa: E402
from gui.mainframe import MainFrame, StartupDialog   # noqa: E402


def main():
    app = wx.App(False)
    frame = MainFrame(repo_root=_REPO)
    dlg = StartupDialog(frame, repo_root=_REPO)
    choice = dlg.run()
    if choice is None:
        frame.Destroy()
        return
    kind, payload = choice
    if kind == 'template':
        frame.new_from_template(payload)
    elif kind == 'open':
        frame.open_project(payload)
    # kind == 'blank': frame already holds an empty project
    frame.Show()
    app.MainLoop()


if __name__ == '__main__':
    main()
