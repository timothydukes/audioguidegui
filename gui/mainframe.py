#!/usr/bin/env python3
"""
mainframe.py -- audioguidegui Phase 4 (delivered as mainframe_v1.py)
Main window: startup chooser, File menu (New from Template / Open / Save /
Save As), placeholder notebook tabs (filled in Phases 5-6), a live "Generated
.py" preview tab, Run/Cancel, progress bars mirroring the CLI (upper label +
per-item lower label), and a scrolling log pane fed by protocol events.

## INTERPRETIVE decisions:
## - Run requires the project to be saved first: audioguide resolves relative
##   soundfile paths against the generated .py location, and the .py is
##   generated NEXT TO the project file (name + '.options.py'). Until Phase 5
##   adds path-browsing editors, projects made from bundled templates should
##   be saved into the repo's examples/ folder so 'cage.aiff' etc. resolve.
## - The gauge switches to Pulse() (indeterminate) between bars.
## - Recent files (5) are stored via wx.Config under 'audioguidegui'.
"""
import os, glob, json

import wx

from gui import project, codegen
from gui.runner import Runner, ProgressState

PROJ_WILDCARD = 'audioguidegui projects (*.agproj.json)|*.agproj.json|All files (*.*)|*.*'
PLACEHOLDER_TABS = ('Target', 'Corpus', 'Search', 'Superimpose',
                    'Instruments', 'Options', 'Output', 'Tools')


# ------------------------------------------------------------- recent files
def _config():
    return wx.Config('audioguidegui')


def get_recent():
    raw = _config().Read('recent', '')
    return [p for p in raw.split('\n') if p and os.path.exists(p)]


def push_recent(path):
    items = [path] + [p for p in get_recent() if p != path]
    _config().Write('recent', '\n'.join(items[:5]))
    _config().Flush()


# ------------------------------------------------------------ startup dialog
class StartupDialog(wx.Dialog):
    """Returns ('template', path) | ('open', path) | ('blank', None) | None."""

    def __init__(self, parent, repo_root):
        wx.Dialog.__init__(self, parent, title='audioguidegui',
                           size=(560, 460),
                           style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.repo_root = repo_root
        self.result = None
        s = wx.BoxSizer(wx.VERTICAL)

        s.Add(wx.StaticText(self, label='Start from a template:'), 0, wx.ALL, 8)
        self.tpl_list = wx.ListBox(self, style=wx.LB_SINGLE)
        self.templates = sorted(glob.glob(os.path.join(
            repo_root, 'gui', 'templates', '*.agproj.json')))
        for t in self.templates:
            label = os.path.basename(t).replace('.agproj.json', '')
            try:
                notes = json.load(open(t)).get('notes', '')
                first = notes.split('\n')[0][:70]
                if first:
                    label += '  --  ' + first
            except Exception:
                pass
            self.tpl_list.Append(label)
        s.Add(self.tpl_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        self.recent = get_recent()
        if self.recent:
            s.Add(wx.StaticText(self, label='Recent projects:'), 0, wx.ALL, 8)
            self.rec_list = wx.ListBox(self, style=wx.LB_SINGLE,
                                       choices=self.recent)
            s.Add(self.rec_list, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
            self.rec_list.Bind(wx.EVT_LISTBOX_DCLICK, self.on_recent)
        self.tpl_list.Bind(wx.EVT_LISTBOX_DCLICK, self.on_template)

        row = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in (('New from Template', self.on_template),
                               ('Open Project...', self.on_open),
                               ('Blank Project', self.on_blank)):
            b = wx.Button(self, label=label)
            b.Bind(wx.EVT_BUTTON, handler)
            row.Add(b, 0, wx.ALL, 4)
        s.Add(row, 0, wx.ALIGN_CENTER | wx.ALL, 8)
        self.SetSizer(s)

    def on_template(self, _evt):
        i = self.tpl_list.GetSelection()
        if i == wx.NOT_FOUND:
            wx.MessageBox('Select a template first.', 'audioguidegui')
            return
        self.result = ('template', self.templates[i])
        self.EndModal(wx.ID_OK)

    def on_recent(self, _evt):
        i = self.rec_list.GetSelection()
        if i != wx.NOT_FOUND:
            self.result = ('open', self.recent[i])
            self.EndModal(wx.ID_OK)

    def on_open(self, _evt):
        dlg = wx.FileDialog(self, 'Open project', wildcard=PROJ_WILDCARD,
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            self.result = ('open', dlg.GetPath())
            self.EndModal(wx.ID_OK)

    def on_blank(self, _evt):
        self.result = ('blank', None)
        self.EndModal(wx.ID_OK)

    def run(self):
        if self.ShowModal() == wx.ID_OK:
            return self.result
        return None


# ---------------------------------------------------------------- main frame
class MainFrame(wx.Frame):
    def __init__(self, repo_root):
        wx.Frame.__init__(self, None, title='audioguidegui', size=(900, 700))
        self.repo_root = repo_root
        self.prj = project.new_project()
        self.prj_path = None
        self.dirty = False
        self.runner = None
        self.pstate = None
        self._build_menu()
        self._build_body()
        self.CreateStatusBar()
        self._refresh_title()
        self.Bind(wx.EVT_CLOSE, self.on_close)

    # ------------------------------------------------------------------ ui
    def _build_menu(self):
        mb = wx.MenuBar()
        m = wx.Menu()
        for iid, label, handler in (
                (wx.ID_NEW, 'New from Template...\tCtrl+N', self.on_new_tpl),
                (wx.ID_OPEN, 'Open...\tCtrl+O', self.on_open),
                (wx.ID_SAVE, 'Save\tCtrl+S', self.on_save),
                (wx.ID_SAVEAS, 'Save As...\tShift+Ctrl+S', self.on_saveas),
                (wx.ID_EXIT, 'Quit', self.on_quit)):
            m.Append(iid, label)
            self.Bind(wx.EVT_MENU, handler, id=iid)
        mb.Append(m, '&File')
        r = wx.Menu()
        self._mi_run = r.Append(wx.ID_ANY, 'Run\tCtrl+R')
        self._mi_cancel = r.Append(wx.ID_ANY, 'Cancel\tCtrl+.')
        self.Bind(wx.EVT_MENU, self.on_run, self._mi_run)
        self.Bind(wx.EVT_MENU, self.on_cancel, self._mi_cancel)
        mb.Append(r, '&Run')
        self.SetMenuBar(mb)

    def _build_body(self):
        panel = wx.Panel(self)
        v = wx.BoxSizer(wx.VERTICAL)

        self.nb = wx.Notebook(panel)
        for name in PLACEHOLDER_TABS:
            page = wx.Panel(self.nb)
            ps = wx.BoxSizer(wx.VERTICAL)
            ps.AddStretchSpacer()
            ps.Add(wx.StaticText(
                page, label='%s editor arrives in Phase 5/6.' % name),
                0, wx.ALIGN_CENTER)
            ps.AddStretchSpacer()
            page.SetSizer(ps)
            self.nb.AddPage(page, name)
        gen_page = wx.Panel(self.nb)
        gs = wx.BoxSizer(wx.VERTICAL)
        self.gen_view = wx.TextCtrl(gen_page,
                                    style=wx.TE_MULTILINE | wx.TE_READONLY)
        self.gen_view.SetFont(wx.Font(wx.FontInfo(11).Family(wx.FONTFAMILY_TELETYPE)))
        gs.Add(self.gen_view, 1, wx.EXPAND)
        gen_page.SetSizer(gs)
        self.nb.AddPage(gen_page, 'Generated .py')
        self.nb.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.on_page_changed)
        v.Add(self.nb, 1, wx.EXPAND | wx.ALL, 4)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_run = wx.Button(panel, label='Run')
        self.btn_cancel = wx.Button(panel, label='Cancel')
        self.btn_cancel.Disable()
        self.btn_run.Bind(wx.EVT_BUTTON, self.on_run)
        self.btn_cancel.Bind(wx.EVT_BUTTON, self.on_cancel)
        row.Add(self.btn_run, 0, wx.RIGHT, 6)
        row.Add(self.btn_cancel, 0)
        v.Add(row, 0, wx.LEFT | wx.BOTTOM, 6)

        self.lbl_upper = wx.StaticText(panel, label=' ')
        self.gauge = wx.Gauge(panel, range=1000)
        self.lbl_lower = wx.StaticText(panel, label=' ')
        v.Add(self.lbl_upper, 0, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)
        v.Add(self.gauge, 0, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)
        v.Add(self.lbl_lower, 0, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)

        self.log = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY)
        self.log.SetFont(wx.Font(wx.FontInfo(10).Family(wx.FONTFAMILY_TELETYPE)))
        v.Add(self.log, 1, wx.EXPAND | wx.ALL, 4)
        panel.SetSizer(v)

    def _refresh_title(self):
        name = self.prj_path or '(unsaved: %s)' % self.prj.get('name', 'untitled')
        self.SetTitle('audioguidegui -- %s%s' % (name, ' *' if self.dirty else ''))
        if self.GetStatusBar():
            self.SetStatusText(name)

    def _refresh_genview(self):
        try:
            self.gen_view.SetValue(codegen.generate(self.prj))
        except Exception as e:
            self.gen_view.SetValue('# codegen error: %r' % e)

    def on_page_changed(self, evt):
        if self.nb.GetPageText(evt.GetSelection()) == 'Generated .py':
            self._refresh_genview()
        evt.Skip()

    # -------------------------------------------------------------- project
    def new_from_template(self, tpl_path):
        tpl = project.load(tpl_path)
        name = os.path.basename(tpl_path).replace('.agproj.json', '')
        self.prj = project.new_from_template(tpl, name)
        self.prj_path = None
        self.dirty = True
        self._refresh_title()

    def open_project(self, path):
        try:
            self.prj = project.load(path)
        except Exception as e:
            wx.MessageBox('Could not open %s:\n%r' % (path, e), 'Open failed',
                          wx.ICON_ERROR)
            return
        self.prj_path = path
        self.dirty = False
        push_recent(path)
        self._refresh_title()

    def on_new_tpl(self, _evt):
        if not self._confirm_discard():
            return
        dlg = StartupDialog(self, self.repo_root)
        choice = dlg.run()
        if choice and choice[0] == 'template':
            self.new_from_template(choice[1])
        elif choice and choice[0] == 'open':
            self.open_project(choice[1])

    def on_open(self, _evt):
        if not self._confirm_discard():
            return
        dlg = wx.FileDialog(self, 'Open project', wildcard=PROJ_WILDCARD,
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            self.open_project(dlg.GetPath())

    def on_save(self, _evt=None):
        if self.prj_path is None:
            return self.on_saveas()
        project.save(self.prj, self.prj_path)
        self.dirty = False
        push_recent(self.prj_path)
        self._refresh_title()
        return True

    def on_saveas(self, _evt=None):
        dlg = wx.FileDialog(
            self, 'Save project as', wildcard=PROJ_WILDCARD,
            defaultDir=os.path.join(self.repo_root, 'examples'),
            defaultFile=self.prj.get('name', 'untitled') + '.agproj.json',
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
        if dlg.ShowModal() != wx.ID_OK:
            return False
        path = dlg.GetPath()
        if not path.endswith('.agproj.json'):
            path += '.agproj.json'
        self.prj['name'] = os.path.basename(path).replace('.agproj.json', '')
        self.prj_path = path
        return self.on_save()

    def _confirm_discard(self):
        if not self.dirty:
            return True
        r = wx.MessageBox('Save changes to the current project?',
                          'Unsaved changes',
                          wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION)
        if r == wx.YES:
            return bool(self.on_save())
        return r == wx.NO

    # ------------------------------------------------------------------ run
    def on_run(self, _evt=None):
        if self.runner is not None and self.runner.poll() is None:
            return
        if self.prj_path is None or self.dirty:
            wx.MessageBox('The project must be saved before running (relative '
                          'soundfile paths resolve against the generated .py, '
                          'which is written next to the project file).',
                          'Save first')
            if not self.on_save():
                return
        genpath = os.path.splitext(os.path.splitext(self.prj_path)[0])[0] + '.options.py'
        try:
            codegen.write(self.prj, genpath)
        except Exception as e:
            wx.MessageBox('Code generation failed:\n%r' % e, 'Error',
                          wx.ICON_ERROR)
            return
        self.log.Clear()
        self._append_log('generated %s' % genpath)
        self.pstate = ProgressState()
        self.runner = Runner(self.repo_root)
        self.btn_run.Disable()
        self.btn_cancel.Enable()
        self.runner.run('agConcatenate.py', [genpath],
                        lambda ev: wx.CallAfter(self._on_event, ev))

    def on_cancel(self, _evt=None):
        if self.runner is not None:
            self.runner.cancel()

    def _append_log(self, text):
        self.log.AppendText(text + '\n')

    def _on_event(self, ev):
        st = self.pstate
        if st is None:
            return
        st.feed(ev)
        e = ev.get('ev')
        if e in ('bar_start', 'section'):
            self.lbl_upper.SetLabel(st.upper)
            self.lbl_lower.SetLabel('')
            if e == 'section':
                self._append_log('== %s ==' % st.upper)
        elif e == 'bar_incr':
            self.lbl_lower.SetLabel(st.lower)
        elif e == 'bar_close':
            self.lbl_lower.SetLabel(st.lower)
            self._append_log('%s: %s' % (st.upper, st.lower))
        elif e in ('log', 'stdout', 'stderr'):
            self._append_log(ev.get('text', ''))
        elif e == 'error':
            self._append_log('ERROR ' + st.error)
        elif e == 'exit':
            code = ev.get('code')
            self._append_log('process finished with exit code %s' % code)
            if st.error:
                wx.MessageBox(st.error, 'audioguide error', wx.ICON_ERROR)
            self.btn_run.Enable()
            self.btn_cancel.Disable()
            self.gauge.SetValue(0)
            self.lbl_upper.SetLabel('done (exit %s)' % code)
            self.runner = None
            return
        frac = st.fraction
        if frac is None:
            self.gauge.Pulse()
        else:
            self.gauge.SetValue(int(frac * 1000))

    # ---------------------------------------------------------------- close
    def on_quit(self, _evt=None):
        self.Close()

    def on_close(self, evt):
        if self.runner is not None and self.runner.poll() is None:
            self.runner.cancel()
        if self._confirm_discard():
            evt.Skip()
        else:
            evt.Veto()
