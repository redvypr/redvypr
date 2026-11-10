"""
Git of the item libraries (redvypr.item_git): repositories of the item files with
their changes, commit, pull and push. Opened from the Items window ("Git ...").
"""

import logging
import os
import typing

from PyQt6 import QtCore, QtGui, QtWidgets

import redvypr.item_git as ritem_git

logger = logging.getLogger('redvypr.widgets.item_git')

ROLE_ROOT = QtCore.Qt.ItemDataRole.UserRole + 1


class CredentialsDialog(QtWidgets.QDialog):
    """User name and personal access token of a git server (HTTPS)."""

    def __init__(self, host: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'Access to {host}')
        lay = QtWidgets.QFormLayout(self)
        info = QtWidgets.QLabel(
            f'{host} needs a user name and a personal access token (GitLab: Preferences, Access tokens, '
            'scope write_repository). It is kept in the key store of the system once it was accepted.')
        info.setWordWrap(True)
        self.user = QtWidgets.QLineEdit()
        self.token = QtWidgets.QLineEdit()
        self.token.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        lay.addRow(info)
        lay.addRow('User name', self.user)
        lay.addRow('Access token', self.token)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                             QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addRow(buttons)

    @classmethod
    def ask(cls, host: str, parent=None) -> typing.Optional[typing.Tuple[str, str]]:
        dlg = cls(host, parent)
        if dlg.exec() and dlg.user.text().strip() and dlg.token.text():
            return dlg.user.text().strip(), dlg.token.text()
        return None


class RedvyprItemGitWidget(QtWidgets.QWidget):
    """Repositories of the item files: changes, commit, pull, push."""

    libraries_changed = QtCore.pyqtSignal()

    def __init__(self, redvypr_instance, parent=None, prefer: typing.Optional[str] = None):
        super().__init__(parent)
        self.redvypr = redvypr_instance
        self.prefer = prefer
        self.setWindowTitle('Items: git')
        # callback (host) -> (user, token) or None; tests replace it
        self.ask_credentials = lambda host: CredentialsDialog.ask(host, self)
        self._state = {}            # root -> (backend, [FileChange])

        self.repos = QtWidgets.QTableWidget(0, 6)
        self.repos.setHorizontalHeaderLabels(['Repository', 'Branch', 'Uses', 'Changes', 'To push', 'To pull'])
        self.repos.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.repos.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.repos.horizontalHeader().setStretchLastSection(True)
        self.repos.setToolTip('"To push"/"To pull": commits not on the server / new on the server, '
                              'as of the last fetch ("Fetch")')
        self.repos.itemSelectionChanged.connect(self.show_files)
        self.files = QtWidgets.QTableWidget(0, 2)
        self.files.setHorizontalHeaderLabels(['State', 'File'])
        self.files.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.files.horizontalHeader().setStretchLastSection(True)
        self.message = QtWidgets.QLineEdit()
        self.message.setPlaceholderText('commit message, e.g. "breakout BO-001 moved to norlog sn 003"')
        self.message.returnPressed.connect(lambda: self.commit())
        self.btn_commit = QtWidgets.QPushButton('Commit')
        self.btn_commit.setToolTip('Save the libraries and commit the changed item files of every repository')
        self.btn_refresh = QtWidgets.QPushButton('Refresh')
        self.btn_fetch = QtWidgets.QPushButton('Fetch')
        self.btn_fetch.setToolTip('Ask the servers for new commits (network)')
        self.btn_pull = QtWidgets.QPushButton('Pull')
        self.btn_pull.setToolTip('Get the new commits of the servers; the libraries are loaded again')
        self.btn_push = QtWidgets.QPushButton('Push')
        self.btn_commit.clicked.connect(lambda: self.commit())
        self.btn_refresh.clicked.connect(lambda: self.refresh())
        self.btn_fetch.clicked.connect(lambda: self.refresh(fetch=True))
        self.btn_pull.clicked.connect(lambda: self.pull())
        self.btn_push.clicked.connect(lambda: self.push())
        self.status = QtWidgets.QLabel('')
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(self.repos, 1)
        lay.addWidget(QtWidgets.QLabel('Changed item files of the selected repository'))
        lay.addWidget(self.files, 2)
        cl = QtWidgets.QHBoxLayout()
        cl.addWidget(self.message, 1)
        cl.addWidget(self.btn_commit)
        lay.addLayout(cl)
        bl = QtWidgets.QHBoxLayout()
        for b in (self.btn_refresh, self.btn_fetch, self.btn_pull, self.btn_push):
            bl.addWidget(b)
        bl.addStretch(1)
        lay.addLayout(bl)
        lay.addWidget(self.status)
        self.refresh()

    # --- helpers ---
    def set_status(self, text, error=False):
        self.status.setText(text)
        self.status.setStyleSheet('color: red' if error else '')

    def _busy(self, on: bool):
        app = QtWidgets.QApplication.instance()
        if app is None:
            return
        if on:
            app.setOverrideCursor(QtGui.QCursor(QtCore.Qt.CursorShape.WaitCursor))
        else:
            app.restoreOverrideCursor()

    def selected_root(self) -> typing.Optional[str]:
        row = self.repos.currentRow()
        cell = self.repos.item(row, 0) if row >= 0 else None
        return cell.data(ROLE_ROOT) if cell is not None else None

    # --- view ---
    def refresh(self, fetch: bool = False):
        """Status of the repositories (fetch: ask the servers for new commits as well)."""
        current = self.selected_root()
        self._busy(True)
        problems = []
        try:
            self._state = self.redvypr.item_git_status(prefer=self.prefer)
            rows = []
            for root, (backend, changes) in self._state.items():
                ahead = behind = ''
                try:
                    a, b = backend.ahead_behind(fetch=fetch, ask_credentials=self.ask_credentials) if fetch \
                        else backend._ahead_behind()
                    ahead, behind = str(a), str(b)
                except Exception as e:
                    problems.append(f'{os.path.basename(root)}: {e}')
                rows.append((root, backend, changes, ahead, behind))
        finally:
            self._busy(False)
        self.repos.setRowCount(len(rows))
        for r, (root, backend, changes, ahead, behind) in enumerate(rows):
            for c, text in enumerate((os.path.basename(root), backend.branch(), backend.name, str(len(changes)),
                                      ahead, behind)):
                cell = QtWidgets.QTableWidgetItem(text)
                cell.setData(ROLE_ROOT, root)
                cell.setToolTip(f'{root}\n{backend.remote_url() or "no remote"}')
                self.repos.setItem(r, c, cell)
            if root == current or (current is None and r == 0):
                self.repos.selectRow(r)
        self.repos.resizeColumnsToContents()
        if not rows:
            self.set_status('the item libraries are not in a git repository', error=False)
        elif problems:
            self.set_status('; '.join(problems), error=True)
        else:
            n = sum(len(ch) for _b, ch in self._state.values())
            self.set_status(f'{n} changed item file(s)' + (' (fetched)' if fetch else ''))
        self.show_files()
        return self._state

    def show_files(self):
        root = self.selected_root()
        changes = self._state.get(root, (None, []))[1] if root else []
        self.files.setRowCount(len(changes))
        for r, ch in enumerate(changes):
            self.files.setItem(r, 0, QtWidgets.QTableWidgetItem(ch.state))
            self.files.setItem(r, 1, QtWidgets.QTableWidgetItem(ch.path))
        self.files.resizeColumnToContents(0)

    # --- actions ---
    def commit(self, message: typing.Optional[str] = None):
        message = (message if message is not None else self.message.text()).strip()
        if not message:
            self.set_status('a commit needs a message', error=True)
            return None
        self._busy(True)
        try:
            res = self.redvypr.item_git_commit(message, prefer=self.prefer)
        except ritem_git.GitError as e:
            self.set_status(f'not committed: {e}', error=True)
            return None
        finally:
            self._busy(False)
        done = {os.path.basename(r): sha[:7] for r, sha in res.items() if sha}
        self.message.clear()
        self.refresh()
        self.set_status('committed: ' + ', '.join(f'{k} {v}' for k, v in done.items()) if done
                        else 'nothing to commit')
        return res

    def _sync(self, what: str):
        func = self.redvypr.item_git_pull if what == 'pull' else self.redvypr.item_git_push
        self._busy(True)
        try:
            res = func(ask_credentials=self.ask_credentials, prefer=self.prefer)
        finally:
            self._busy(False)
        texts, error, changed = [], False, False
        for root, r in res.items():
            name = os.path.basename(root)
            if isinstance(r, Exception):
                texts.append(f'{name}: {r}')
                error = True
            else:
                texts.append(f'{name}: {r.action}')
                changed = changed or r.changed
        self.refresh()
        self.set_status(f'{what}: ' + '; '.join(texts) if texts else f'{what}: no repository', error=error)
        if changed:
            self.libraries_changed.emit()
        return res

    def pull(self):
        return self._sync('pull')

    def push(self):
        return self._sync('push')
