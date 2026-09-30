# -*- coding: utf-8 -*-
'''传输页 UI：本机别名、附近设备列表、文件发送、传输记录与接收确认层。

线程模型：TransferServer / Discovery / send_files 的回调全部发生在后台线程，
本模块只经 pyqtSignal 把事件送回主线程再动 UI（PyQt5 槽里未捕获异常会让进程
abort，故所有槽函数 try/except 兜底）。on_receive_request 是 HTTP 线程里的
阻塞调用：发信号给主线程弹确认层，结果经 threading.Event 回传，超时按拒绝。
'''

import os
import threading
import time
import uuid

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (QWidget, QFrame, QLabel, QToolButton, QPushButton,
                             QVBoxLayout, QHBoxLayout, QLineEdit, QProgressBar,
                             QScrollArea, QFileDialog, QSizePolicy)

import app as ui            # 仅运行期用 ui.sc()，import 期无依赖（app 也 import 本模块）
from transfer import send_files, DEVICE_TTL

RECV_CONFIRM_TIMEOUT = 170   # 接收确认等待秒数：须小于协议端 prepare-upload 的 180s
MAX_RECORDS = 50             # 传输记录条数上限，超出丢弃最旧


def _fmt_size(n):
    '''字节数转可读大小（1024 进制）。'''
    try:
        n = float(n)
    except (TypeError, ValueError):
        return '?'
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return ('%.0f' if unit == 'B' else '%.1f') % n + ' ' + unit
        n /= 1024.0
    return '%.1f GB' % n


def _default_save_dir(cfg):
    '''接收保存目录：配置优先，缺省 ~/Downloads/Zviber。'''
    d = cfg.transfer_dir
    if isinstance(d, str) and d:
        return d
    return os.path.join(os.path.expanduser('~'), 'Downloads', 'Zviber')


class _ClickRow(QFrame):
    '''可整行点击的容器（设备选择用）。'''
    clicked = pyqtSignal()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        super(_ClickRow, self).mouseReleaseEvent(e)


class TransferWidget(QWidget):
    '''传输 tab。server 为 None 时（端口被占）只显示「传输服务不可用」空态。'''

    notify = pyqtSignal(str, str)                       # 托盘气泡（标题, 内容）
    sig_devices = pyqtSignal()                          # 设备列表需刷新
    sig_scan_done = pyqtSignal()                        # 子网扫描结束
    sig_progress = pyqtSignal(str, str, object, object)       # 接收进度 session_id, file_id, done, total
    sig_file_done = pyqtSignal(str, str, str)           # session_id, file_id, saved_path
    sig_session_done = pyqtSignal(str)                  # session_id
    sig_cancelled = pyqtSignal(str)                     # session_id
    sig_recv_request = pyqtSignal(object, object, object)   # view, result, event
    sig_recv_timeout = pyqtSignal(str)                  # 确认超时 session_id
    sig_send_progress = pyqtSignal(str, object, object)       # 记录 key, done, total
    sig_send_done = pyqtSignal(str, bool, str)          # 记录 key, ok, err

    def __init__(self, cfg, server, discovery, device_info, parent=None):
        super(TransferWidget, self).__init__(parent)
        self.cfg = cfg
        self.server = server
        self.discovery = discovery
        self.device_info = device_info
        self.theme_key = 'nocturne'
        self._files = []             # 待发送的本地路径
        self._selected_fp = None     # 选中设备的 fingerprint
        self._devices = {}           # 主动注册来的设备 {fp: (DeviceInfo, ip, last_seen)}
        self._dev_sig = None         # 设备行渲染签名（没变不重建，防闪烁）
        self._records = {}           # 记录 key -> dict
        self._rec_keys = []          # 记录顺序（新的在前）
        self._pending = None         # 待确认的接收请求 (session_id, key, result, event)
        self._scanning = False
        self._save_dir = _default_save_dir(cfg)
        self.setAcceptDrops(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.pane = QFrame()
        self.pane.setObjectName('transferRoot')
        pl = QVBoxLayout(self.pane)
        pl.setContentsMargins(ui.sc(8), ui.sc(8), ui.sc(8), ui.sc(8))
        pl.setSpacing(ui.sc(6))
        root.addWidget(self.pane)

        if server is None:
            empty = QLabel('传输服务不可用\n（端口 53327 被占用？）')
            empty.setObjectName('transferHint')
            empty.setAlignment(Qt.AlignCenter)
            pl.addStretch(1)
            pl.addWidget(empty)
            pl.addStretch(1)
            return

        # ---- 本机别名 ----
        alias_row = QHBoxLayout()
        alias_row.setContentsMargins(ui.sc(10), 0, ui.sc(10), 0)
        alias_row.setSpacing(ui.sc(8))
        lab = QLabel('本机别名')
        lab.setObjectName('transferLabel')
        self.alias_edit = QLineEdit(device_info.alias if device_info else '')
        self.alias_edit.setObjectName('aliasEdit')
        self.alias_edit.setMaxLength(32)
        self.alias_edit.editingFinished.connect(self._alias_commit)
        alias_row.addWidget(lab)
        alias_row.addWidget(self.alias_edit, 1)
        pl.addLayout(alias_row)

        # ---- 设备列表 ----
        dev_head = QHBoxLayout()
        dev_head.setContentsMargins(ui.sc(10), 0, ui.sc(10), 0)
        t = QLabel('附近的设备')
        t.setObjectName('transferTitle')
        self.refresh_btn = QToolButton()
        self.refresh_btn.setObjectName('refreshBtn')
        self.refresh_btn.setText('刷新')
        self.refresh_btn.clicked.connect(self._refresh_clicked)
        dev_head.addWidget(t)
        dev_head.addStretch(1)
        dev_head.addWidget(self.refresh_btn)
        pl.addLayout(dev_head)

        self.dev_scroll = QScrollArea()
        self.dev_scroll.setObjectName('transferScroll')
        self.dev_scroll.setWidgetResizable(True)
        self.dev_scroll.setFrameShape(QFrame.NoFrame)
        self.dev_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.dev_scroll.setFixedHeight(ui.sc(96))
        self.dev_box = QWidget()
        self.dev_box.setObjectName('transferBox')
        self.dev_lay = QVBoxLayout(self.dev_box)
        self.dev_lay.setContentsMargins(ui.sc(4), 0, ui.sc(4), 0)
        self.dev_lay.setSpacing(ui.sc(2))
        self.dev_lay.addStretch(1)
        self.dev_scroll.setWidget(self.dev_box)
        pl.addWidget(self.dev_scroll)

        # ---- 发送区 ----
        send_row = QHBoxLayout()
        send_row.setContentsMargins(ui.sc(10), 0, ui.sc(10), 0)
        send_row.setSpacing(ui.sc(8))
        self.pick_btn = QToolButton()
        self.pick_btn.setObjectName('pickBtn')
        self.pick_btn.setText('选择文件发送')
        self.pick_btn.clicked.connect(self._pick_files)
        self.file_lab = QLabel('未选文件（可拖入）')
        self.file_lab.setObjectName('transferHint')
        self.file_lab.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.send_btn = QPushButton('发送')
        self.send_btn.setObjectName('sendBtn')
        self.send_btn.setEnabled(False)
        self.send_btn.clicked.connect(self._send_clicked)
        send_row.addWidget(self.pick_btn)
        send_row.addWidget(self.file_lab, 1)
        send_row.addWidget(self.send_btn)
        pl.addLayout(send_row)

        # ---- 传输记录 ----
        rec_head = QHBoxLayout()
        rec_head.setContentsMargins(ui.sc(10), 0, ui.sc(10), 0)
        rt = QLabel('传输记录')
        rt.setObjectName('transferTitle')
        rec_head.addWidget(rt)
        rec_head.addStretch(1)
        pl.addLayout(rec_head)

        self.rec_scroll = QScrollArea()
        self.rec_scroll.setObjectName('transferScroll')
        self.rec_scroll.setWidgetResizable(True)
        self.rec_scroll.setFrameShape(QFrame.NoFrame)
        self.rec_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.rec_box = QWidget()
        self.rec_box.setObjectName('transferBox')
        self.rec_lay = QVBoxLayout(self.rec_box)
        self.rec_lay.setContentsMargins(ui.sc(4), 0, ui.sc(4), 0)
        self.rec_lay.setSpacing(ui.sc(4))
        self.rec_lay.addStretch(1)
        self.rec_scroll.setWidget(self.rec_box)
        pl.addWidget(self.rec_scroll, 1)

        self.rec_empty = QLabel('暂无传输记录')
        self.rec_empty.setObjectName('transferHint')
        self.rec_empty.setAlignment(Qt.AlignCenter)
        self.rec_lay.insertWidget(0, self.rec_empty)

        # ---- 接收确认层：盖住整个传输页的面板内遮罩 ----
        self.recv = QFrame(self)
        self.recv.setObjectName('recvDialog')
        rl = QVBoxLayout(self.recv)
        rl.setContentsMargins(ui.sc(18), ui.sc(16), ui.sc(18), ui.sc(16))
        rl.setSpacing(ui.sc(8))
        title = QLabel('收到文件')
        title.setObjectName('transferTitle')
        self.recv_from = QLabel()
        self.recv_from.setObjectName('recvFrom')
        self.recv_files = QLabel()
        self.recv_files.setObjectName('recvFiles')
        self.recv_files.setWordWrap(True)
        dir_row = QHBoxLayout()
        dir_row.setSpacing(ui.sc(6))
        self.recv_dir = QLabel()
        self.recv_dir.setObjectName('recvDir')
        self.recv_dir.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        chg = QToolButton()
        chg.setObjectName('refreshBtn')     # 复用次级按钮样式
        chg.setText('更改…')
        chg.clicked.connect(self._recv_change_dir)
        dir_row.addWidget(self.recv_dir, 1)
        dir_row.addWidget(chg)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(ui.sc(10))
        no = QPushButton('拒绝')
        no.setObjectName('setBtn')          # 复用设置窗按钮样式
        yes = QPushButton('接受')
        yes.setObjectName('setSave')
        no.clicked.connect(self._recv_reject)
        yes.clicked.connect(self._recv_accept)
        btn_row.addStretch(1)
        btn_row.addWidget(no)
        btn_row.addWidget(yes)
        rl.addWidget(title)
        rl.addWidget(self.recv_from)
        rl.addWidget(self.recv_files, 1)
        rl.addLayout(dir_row)
        rl.addLayout(btn_row)
        self.recv.hide()

        # ---- 信号接线（全部在主线程执行） ----
        self.sig_devices.connect(self._refresh_devices)
        self.sig_scan_done.connect(self._scan_done)
        self.sig_progress.connect(self._on_progress)
        self.sig_file_done.connect(self._on_file_done)
        self.sig_session_done.connect(self._on_session_done)
        self.sig_cancelled.connect(self._on_cancelled)
        self.sig_recv_request.connect(self._show_recv)
        self.sig_recv_timeout.connect(self._on_recv_timeout)
        self.sig_send_progress.connect(self._on_send_progress)
        self.sig_send_done.connect(self._on_send_done)

        # ---- 网络回调接线：后台线程里只发信号，不碰 UI ----
        server.on_device_found = self._cb_device_found
        server.on_receive_request = self._cb_receive_request
        server.on_progress = self.sig_progress.emit
        server.on_file_done = self.sig_file_done.emit
        server.on_session_done = self.sig_session_done.emit
        server.on_cancelled = self.sig_cancelled.emit
        if discovery is not None:
            discovery.on_device_found = self._cb_device_found

        self._dev_timer = QTimer(self)
        self._dev_timer.timeout.connect(self._refresh_devices)
        self._dev_timer.start(5000)   # 5 秒刷一次：DEVICE_TTL 剔除离线设备
        self._refresh_devices()

    # ---------------- 通用 ----------------

    def set_theme(self, key):
        '''主题切换：颜色全走 QSS，这里只记住键（与 TodoWidget 接口一致）。'''
        self.theme_key = key

    def resizeEvent(self, e):
        super(TransferWidget, self).resizeEvent(e)
        try:
            if hasattr(self, 'recv'):
                self.recv.setGeometry(self.rect())
        except Exception:
            pass

    def dragEnterEvent(self, e):
        try:
            if self.server is not None and e.mimeData().hasUrls() and \
                    any(u.isLocalFile() for u in e.mimeData().urls()):
                e.acceptProposedAction()
        except Exception:
            pass

    def dropEvent(self, e):
        try:
            paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
            self._set_files(self._files + [p for p in paths if p and os.path.isfile(p)])
        except Exception:
            pass

    # ---------------- 本机别名 ----------------

    def _alias_commit(self):
        try:
            alias = self.alias_edit.text().strip()
            if not alias or self.device_info is None or alias == self.device_info.alias:
                return
            self.device_info.alias = alias
            self.cfg.set('transfer_alias', alias)
        except Exception:
            pass

    # ---------------- 设备列表 ----------------

    def _cb_device_found(self, info, ip):
        '''发现/注册回调（网络线程）：登记主动注册来的设备，发信号让主线程刷新。'''
        try:
            self._devices[info.fingerprint] = (info, ip, time.time())
            self.sig_devices.emit()
        except Exception:
            pass

    def _refresh_devices(self):
        '''主线程：合并组播/扫描（discovery，自带 TTL）与主动注册的设备，重建行。'''
        try:
            merged = {}
            if self.discovery is not None:
                got = self.discovery.get_devices()
                for info, ip in (got.values() if isinstance(got, dict) else got):
                    merged[info.fingerprint] = (info, ip)
            now = time.time()
            for fp, (info, ip, seen) in list(self._devices.items()):
                if now - seen > DEVICE_TTL:
                    del self._devices[fp]
                elif fp not in merged:
                    merged[fp] = (info, ip)
            self._render_devices(merged)
        except Exception:
            pass

    def _render_devices(self, merged):
        if self._selected_fp not in merged:
            self._selected_fp = next(iter(merged), None)   # 默认选中第一台
        sig = sorted((fp, info.alias, ip, fp == self._selected_fp)
                     for fp, (info, ip) in merged.items())
        if sig == self._dev_sig:
            self._sync_send_enabled()
            return
        self._dev_sig = sig
        while self.dev_lay.count() > 1:   # 末尾是 stretch
            item = self.dev_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if not merged:
            hint = QLabel('未发现设备——确认手机与电脑在同一 WiFi')
            hint.setObjectName('transferHint')
            hint.setAlignment(Qt.AlignCenter)
            self.dev_lay.insertWidget(0, hint)
        else:
            for fp, (info, ip) in sorted(merged.items(),
                                         key=lambda kv: kv[1][0].alias.lower()):
                row = _ClickRow()
                row.setObjectName('deviceRow')
                row.setProperty('sel', 'true' if fp == self._selected_fp else 'false')
                row.setCursor(Qt.PointingHandCursor)
                lay = QHBoxLayout(row)
                lay.setContentsMargins(ui.sc(8), ui.sc(5), ui.sc(8), ui.sc(5))
                lay.setSpacing(ui.sc(8))
                chip = QLabel({'mobile': '手机', 'desktop': '电脑'}.get(info.device_type, '设备'))
                chip.setObjectName('deviceType')
                name = QLabel(info.alias or ip)
                name.setObjectName('deviceAlias')
                name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
                addr = QLabel(ip)
                addr.setObjectName('deviceIp')
                lay.addWidget(chip)
                lay.addWidget(name, 1)
                lay.addWidget(addr)
                row.clicked.connect(lambda fp=fp: self._select_device(fp))
                self.dev_lay.insertWidget(self.dev_lay.count() - 1, row)
        self._sync_send_enabled()

    def _select_device(self, fp):
        try:
            self._selected_fp = fp
            self._refresh_devices()
        except Exception:
            pass

    def _refresh_clicked(self):
        '''「刷新」：工作线程跑子网扫描（约数秒），结束后回主线程刷新列表。'''
        try:
            if self.discovery is None or self._scanning:
                return
            self._scanning = True
            self.refresh_btn.setEnabled(False)
            threading.Thread(target=self._scan_worker,
                             name='transfer-scan', daemon=True).start()
        except Exception:
            pass

    def _scan_worker(self):
        try:
            self.discovery.scan_subnet()
        except Exception:
            pass
        self.sig_scan_done.emit()

    def _scan_done(self):
        try:
            self._scanning = False
            self.refresh_btn.setEnabled(True)
            self._refresh_devices()
        except Exception:
            pass

    # ---------------- 发送 ----------------

    def _pick_files(self):
        try:
            paths, _ = QFileDialog.getOpenFileNames(self, '选择要发送的文件')
            if paths:
                self._set_files(self._files + [p for p in paths if os.path.isfile(p)])
        except Exception:
            pass

    def _set_files(self, files):
        try:
            seen = set()
            self._files = [p for p in files if not (p in seen or seen.add(p))]
            if self._files:
                total = 0
                for p in self._files:
                    try:
                        total += os.path.getsize(p)
                    except OSError:
                        pass
                self.file_lab.setText('已选 %d 个文件（%s）' % (len(self._files), _fmt_size(total)))
                self.file_lab.setToolTip('\n'.join(self._files))
            else:
                self.file_lab.setText('未选文件（可拖入）')
                self.file_lab.setToolTip('')
            self._sync_send_enabled()
        except Exception:
            pass

    def _sync_send_enabled(self):
        try:
            self.send_btn.setEnabled(bool(self._selected_fp) and bool(self._files))
        except Exception:
            pass

    def _send_clicked(self):
        try:
            fp = self._selected_fp
            if not fp or not self._files:
                return
            merged = self._devices_merged()
            if fp not in merged:      # 刚离线：刷新列表后放弃本次发送
                self._refresh_devices()
                return
            info, ip = merged[fp]
            files = list(self._files)
            names = [os.path.basename(p) for p in files]
            total = 0
            for p in files:
                try:
                    total += os.path.getsize(p)
                except OSError:
                    pass
            key = self._add_record('up', names, total)
            self._set_files([])
            threading.Thread(target=self._send_worker,
                             args=(key, ip, info.port, files),
                             name='transfer-send', daemon=True).start()
        except Exception:
            pass

    def _devices_merged(self):
        '''当前可见设备 {fp: (DeviceInfo, ip)}（与 _refresh_devices 同一口径）。'''
        merged = {}
        if self.discovery is not None:
            got = self.discovery.get_devices()
            for info, ip in (got.values() if isinstance(got, dict) else got):
                merged[info.fingerprint] = (info, ip)
        now = time.time()
        for fp, (info, ip, seen) in list(self._devices.items()):
            if now - seen <= DEVICE_TTL and fp not in merged:
                merged[fp] = (info, ip)
        return merged

    def _send_worker(self, key, ip, port, files):
        '''工作线程：send_files 阻塞调用，进度/结果经信号回主线程。'''
        sizes = []
        for p in files:
            try:
                sizes.append(os.path.getsize(p))
            except OSError:
                sizes.append(0)
        total_all = sum(sizes)

        def on_progress(index, done, _total):
            self.sig_send_progress.emit(key, sum(sizes[:index]) + done, total_all)

        def on_done(ok, err):
            self.sig_send_done.emit(key, bool(ok), '%s' % (err or ''))

        try:
            send_files(ip, port, files, on_progress=on_progress, on_done=on_done,
                       device_info=self.device_info)
        except Exception as exc:
            # 核心层已兜底，理论不可达；双保险防线程静默死
            self.sig_send_done.emit(key, False, '%s' % exc)

    def _on_send_progress(self, key, done, total):
        try:
            rec = self._records.get(key)
            if rec is None or rec['state'] not in ('wait', 'busy'):
                return
            rec['state'] = 'busy'
            rec['done'] = done
            if total:
                rec['total'] = total
            self._update_record(rec)
        except Exception:
            pass

    def _on_send_done(self, key, ok, err):
        try:
            rec = self._records.get(key)
            if rec is None:
                return
            if ok:
                rec['state'] = 'done'
                rec['done'] = rec['total']
            elif err == 'rejected':
                rec['state'] = 'rejected'
            else:
                rec['state'] = 'fail'
                rec['err'] = err
            self._update_record(rec)
        except Exception:
            pass

    # ---------------- 接收 ----------------

    def _cb_receive_request(self, session):
        '''HTTP 线程阻塞调用：把请求转给主线程弹确认层，等用户决定（超时按拒绝）。

        返回保存目录 str（接受）或 None（拒绝/超时）。'''
        try:
            info = session.get('info')
            files = session.get('files') or {}
            names = []
            total = 0
            for fid, meta in files.items():
                meta = meta if isinstance(meta, dict) else {}
                names.append(os.path.basename(str(meta.get('fileName') or '')) or fid)
                try:
                    total += int(meta.get('size') or 0)
                except (TypeError, ValueError):
                    pass
            view = {'session_id': session.get('id'),
                    'alias': getattr(info, 'alias', '') or session.get('ip') or '',
                    'names': names, 'total': total}
            result = {'dir': None}
            event = threading.Event()
            self.sig_recv_request.emit(view, result, event)
            if event.wait(RECV_CONFIRM_TIMEOUT):
                return result['dir']
            self.sig_recv_timeout.emit(view['session_id'])
        except Exception:
            pass
        return None

    def _show_recv(self, view, result, event):
        '''主线程：弹面板内接收确认层。一次只确认一个，并发的直接拒。'''
        try:
            if self._pending is not None:
                event.set()   # result['dir'] 仍为 None → 协议端按拒绝
                return
            key = self._add_record('down', view['names'], view['total'])
            rec = self._records.get(key)
            if rec is not None:
                rec['session_id'] = view['session_id']
            self._pending = (view['session_id'], key, result, event)
            self._save_dir = _default_save_dir(self.cfg)
            self.recv_from.setText('来自 %s · 共 %s' % (view['alias'], _fmt_size(view['total'])))
            shown = view['names'][:8]
            text = '\n'.join(shown)
            if len(view['names']) > len(shown):
                text += '\n…等共 %d 个文件' % len(view['names'])
            self.recv_files.setText(text)
            self.recv_dir.setText('保存到：%s' % self._save_dir)
            self.recv_dir.setToolTip(self._save_dir)
            self.recv.setGeometry(self.rect())
            self.recv.show()
            self.recv.raise_()
            self.notify.emit('收到文件', '%s 想发送 %d 个文件' % (view['alias'], len(view['names'])))
        except Exception:
            event.set()

    def _close_recv(self):
        '''关掉确认层并唤醒 HTTP 线程（无论接受/拒绝/超时都只走这里）。'''
        pending = self._pending
        self._pending = None
        try:
            self.recv.hide()
        except Exception:
            pass
        if pending is not None:
            pending[3].set()

    def _recv_accept(self):
        try:
            if self._pending is None:
                return
            session_id, key, result, event = self._pending
            d = self._save_dir
            try:
                os.makedirs(d, exist_ok=True)
            except OSError:
                try:
                    d = os.path.join(os.path.expanduser('~'), 'Downloads', 'Zviber')
                    os.makedirs(d, exist_ok=True)
                except OSError:
                    d = None   # 目录不可用：result 保持 None，协议端按拒绝
            rec = self._records.get(key)
            if rec is not None:
                rec['state'] = 'busy' if d else 'rejected'
                self._update_record(rec)
            if d:
                result['dir'] = d
        except Exception:
            pass
        finally:
            self._close_recv()

    def _recv_reject(self):
        try:
            if self._pending is not None:
                rec = self._records.get(self._pending[1])
                if rec is not None:
                    rec['state'] = 'rejected'
                    self._update_record(rec)
        except Exception:
            pass
        finally:
            self._close_recv()

    def _recv_change_dir(self):
        try:
            d = QFileDialog.getExistingDirectory(self, '选择保存目录', self._save_dir)
            if d:
                self._save_dir = d
                self.cfg.set('transfer_dir', d)
                self.recv_dir.setText('保存到：%s' % d)
                self.recv_dir.setToolTip(d)
        except Exception:
            pass

    def _on_recv_timeout(self, session_id):
        '''确认超时（HTTP 线程已按拒绝返回）：关掉还挂着的确认层并记「已拒绝」。'''
        try:
            if self._pending is not None and self._pending[0] == session_id:
                rec = self._records.get(self._pending[1])
                if rec is not None:
                    rec['state'] = 'rejected'
                    self._update_record(rec)
                self._close_recv()   # event.set() 无害：HTTP 线程已超时返回
        except Exception:
            pass

    def _find_recv_record(self, session_id):
        for rec in self._records.values():
            if rec.get('session_id') == session_id:
                return rec
        return None

    def _on_progress(self, session_id, file_id, done, total):
        try:
            rec = self._find_recv_record(session_id)
            if rec is None or rec['state'] not in ('wait', 'busy'):
                return
            rec['files'][file_id] = done
            rec['done'] = sum(rec['files'].values())
            rec['state'] = 'busy'
            self._update_record(rec)
        except Exception:
            pass

    def _on_file_done(self, session_id, file_id, saved_path):
        try:
            rec = self._find_recv_record(session_id)
            if rec is None:
                return
            rec['saved'].append(saved_path)
            rec['row'].setToolTip('\n'.join(rec['saved']))
        except Exception:
            pass

    def _on_session_done(self, session_id):
        try:
            rec = self._find_recv_record(session_id)
            if rec is None:
                return
            rec['state'] = 'done'
            rec['done'] = rec['total']
            self._update_record(rec)
            self.notify.emit('传输完成', '%s 已保存' % rec['name'])
        except Exception:
            pass

    def _on_cancelled(self, session_id):
        try:
            rec = self._find_recv_record(session_id)
            if rec is None:
                return
            rec['state'] = 'cancelled'
            self._update_record(rec)
        except Exception:
            pass

    # ---------------- 传输记录 ----------------

    def _add_record(self, direction, names, total):
        '''新建一条记录并插到记录区顶部，返回 key。direction: 'up' 发 / 'down' 收。'''
        key = uuid.uuid4().hex
        display = names[0] if len(names) == 1 else '%d 个文件' % len(names)
        row = QFrame()
        row.setObjectName('transferRow')
        lay = QVBoxLayout(row)
        lay.setContentsMargins(ui.sc(8), ui.sc(5), ui.sc(8), ui.sc(6))
        lay.setSpacing(ui.sc(3))
        top = QHBoxLayout()
        top.setSpacing(ui.sc(6))
        arrow = QLabel('↑' if direction == 'up' else '↓')
        arrow.setObjectName('transferDir')
        name = QLabel(display)
        name.setObjectName('transferName')
        name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        name.setToolTip('\n'.join(names))
        state = QLabel()
        state.setObjectName('transferState')
        top.addWidget(arrow)
        top.addWidget(name, 1)
        top.addWidget(state)
        bar = QProgressBar()
        bar.setRange(0, 1000)
        bar.setValue(0)
        bar.setTextVisible(False)
        bar.setFixedHeight(ui.sc(5))
        lay.addLayout(top)
        lay.addWidget(bar)
        self.rec_empty.hide()
        self.rec_lay.insertWidget(0, row)
        rec = {'key': key, 'direction': direction, 'name': display, 'total': total,
               'done': 0, 'files': {}, 'saved': [], 'state': 'wait', 'err': '',
               'session_id': None, 'row': row, 'bar': bar, 'state_lab': state}
        self._records[key] = rec
        self._rec_keys.insert(0, key)
        self._update_record(rec)
        while len(self._rec_keys) > MAX_RECORDS:
            old = self._rec_keys.pop()
            old_rec = self._records.pop(old, None)
            if old_rec is not None:
                self.rec_lay.removeWidget(old_rec['row'])
                old_rec['row'].deleteLater()
        return key

    def _update_record(self, rec):
        '''按 rec 的状态刷新状态文字与进度条（主线程）。'''
        state = rec['state']
        total = rec['total'] or 0
        if state == 'wait':
            text = '等待对方确认'
        elif state == 'busy':
            text = '传输中 %d%%' % (int(rec['done'] * 100 / total) if total else 0)
        elif state == 'done':
            text = '完成'
        elif state == 'rejected':
            text = '被拒绝'
        elif state == 'cancelled':
            text = '已取消'
        else:
            text = '失败'
            if rec.get('err'):
                text = '失败：%s' % rec['err'][:24]
        rec['state_lab'].setText(text)
        if rec['state_lab'].property('state') != state:
            rec['state_lab'].setProperty('state', state)
            rec['state_lab'].style().unpolish(rec['state_lab'])
            rec['state_lab'].style().polish(rec['state_lab'])
        if state == 'done':
            rec['bar'].setValue(1000)
        else:
            rec['bar'].setValue(int(rec['done'] * 1000 / total) if total else 0)
