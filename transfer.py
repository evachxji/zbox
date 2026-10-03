# -*- coding: utf-8 -*-
'''局域网文件传输协议核心（LocalSend Protocol v2.2 HTTP 模式的私有实例）。

纯标准库实现，不依赖 Qt，可独立测试。组播地址与端口为自定义值，
与官方 LocalSend 完全隔离：

- UDP 组播 224.0.0.168，TCP HTTP 与 UDP 同端口 53327
- API 前缀 /api/localsend/v2/

组件：
- DeviceInfo      设备信息（发现与握手）
- TransferServer  HTTP 服务端：register / info / prepare-upload / upload / cancel
- Discovery       UDP 组播发现 + /24 子网回退扫描
- send_files      发送方客户端
'''

import hashlib
import http.client
import json
import mimetypes
import os
import platform
import socket
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MULTICAST_GROUP = '224.0.0.168'          # UDP 组播地址（自定义，与官方隔离）
PORT = 53327                             # TCP HTTP 与 UDP 组播同端口
API_PREFIX = '/api/localsend/v2/'
CHUNK_SIZE = 65536                       # 流式读写块大小 64KB
SCAN_TIMEOUT = 0.5                       # 子网扫描单 IP 超时
SCAN_WORKERS = 64                        # 子网扫描并发数
NET_TIMEOUT = 10.0                       # 普通网络请求超时上限
MAX_JSON_BODY = 1048576                    # JSON 请求体上限 1MB
PREPARE_TIMEOUT = 180.0                    # prepare-upload 专用：等待对端用户手动确认
SESSION_TTL = 600.0                        # 会话超过 10 分钟未完成视为陈旧


def _safe_call(callback, *args):
    # 回调由 UI 层注入，异常不能拖垮网络线程
    if callback is None:
        return None
    try:
        return callback(*args)
    except Exception:
        return None


class DeviceInfo(object):
    '''设备信息：发现组播与 register 握手的载体。'''

    def __init__(self, alias, fingerprint, port=PORT, device_model=None,
                 device_type='desktop', version='2.0', protocol='http'):
        self.alias = alias
        self.version = version
        self.device_model = device_model or ''
        self.device_type = device_type
        self.fingerprint = fingerprint
        self.port = int(port)
        self.protocol = protocol

    def to_dict(self):
        return {
            'alias': self.alias,
            'version': self.version,
            'deviceModel': self.device_model,
            'deviceType': self.device_type,
            'fingerprint': self.fingerprint,
            'port': self.port,
            'protocol': self.protocol,
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            data = {}
        try:
            port = int(data.get('port') or PORT)
        except (TypeError, ValueError):
            port = PORT  # 伪造的坏端口（如 "abc"）安全回退，不杀死调用线程
        return cls(
            alias=data.get('alias') or '',
            fingerprint=data.get('fingerprint') or '',
            port=port,
            device_model=data.get('deviceModel') or '',
            device_type=data.get('deviceType') or 'desktop',
            version=data.get('version') or '2.0',
            protocol=data.get('protocol') or 'http',
        )

    @classmethod
    def local(cls, alias, fingerprint):
        '''构造本机信息，deviceModel 取 Windows 版本（如 "Windows 10"）。'''
        return cls(alias=alias, fingerprint=fingerprint,
                   device_model='Windows %s' % platform.release())


def load_or_create_fingerprint(cfg_path):
    '''从 cfg_path 的 JSON 里读 transfer_fingerprint，没有则生成并写回。

    只操作调用方传入的路径，其它配置键原样保留。
    '''
    cfg = {}
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
        except (ValueError, OSError):
            cfg = {}
    fp = cfg.get('transfer_fingerprint')
    if isinstance(fp, str) and fp:
        return fp
    fp = uuid.uuid4().hex
    cfg['transfer_fingerprint'] = fp
    parent = os.path.dirname(os.path.abspath(cfg_path))
    if not os.path.isdir(parent):
        os.makedirs(parent)
    with open(cfg_path, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return fp


def _create_unique(directory, name):
    '''原子占位创建（O_EXCL），冲突时自动加 " (2)" / " (3)" 后缀。

    返回 (fd, 路径)；并发上传同名文件也不会互相覆盖。'''
    base, ext = os.path.splitext(name)
    n = 1
    while True:
        candidate = os.path.join(
            directory, name if n == 1 else '%s (%d)%s' % (base, n, ext))
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            return fd, candidate
        except FileExistsError:
            n += 1


class _BodyTooLarge(Exception):
    '''JSON 请求体超过 MAX_JSON_BODY。'''


class _ApiHandler(BaseHTTPRequestHandler):
    '''TransferServer 的请求分发器，只认 API_PREFIX 下的五个路由。'''

    protocol_version = 'HTTP/1.1'
    server_version = 'ZboxTransfer/1.0'

    def setup(self):
        BaseHTTPRequestHandler.setup(self)
        # 默认连接超时：慢速/僵死连接不能无限挂住 handler 线程
        self.connection.settimeout(NET_TIMEOUT)

    def log_message(self, fmt, *args):
        pass  # 静默，不写 stderr

    def do_GET(self):
        self._dispatch('GET')

    def do_POST(self):
        self._dispatch('POST')

    # ---- 基础工具 ----

    def _send_json(self, code, obj):
        body = json.dumps(obj).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get('Content-Length') or 0)
        if length > MAX_JSON_BODY:
            raise _BodyTooLarge()
        raw = self.rfile.read(length) if length > 0 else b''
        return json.loads(raw.decode('utf-8'))

    def _drain_body(self):
        '''丢弃未读的请求体。拒绝类响应若不先排空，Windows 关连接时的
        RST 可能把已发出的响应一起冲掉（客户端表现为连接中断而非状态码）。'''
        try:
            length = int(self.headers.get('Content-Length') or 0)
            while length > 0:
                chunk = self.rfile.read(min(CHUNK_SIZE, length))
                if not chunk:
                    break
                length -= len(chunk)
        except Exception:
            pass

    @staticmethod
    def _query_first(query, key):
        values = query.get(key)
        return values[0] if values else None

    # ---- 路由分发 ----

    def _dispatch(self, method):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)
            if not path.startswith(API_PREFIX):
                self._send_json(404, {'message': 'not found'})
                return
            route = path[len(API_PREFIX):]
            if method == 'GET' and route == 'info':
                self._send_json(200, self.server.device_info.to_dict())
            elif method == 'POST' and route == 'register':
                self._handle_register()
            elif method == 'POST' and route == 'prepare-upload':
                self._handle_prepare()
            elif method == 'POST' and route == 'upload':
                self._handle_upload(query)
            elif method == 'POST' and route == 'cancel':
                self._handle_cancel(query)
            else:
                self._send_json(404, {'message': 'not found'})
        except _BodyTooLarge:
            self._drain_body()  # 与其它拒绝路径一致，先排空再响应
            self._send_json(413, {'message': 'payload too large'})
        except ValueError:
            self._send_json(400, {'message': 'bad request'})
        except Exception:
            # 未知异常统一 500；响应已发出则只能断开连接
            try:
                self._send_json(500, {'message': 'internal error'})
            except Exception:
                pass

    # ---- 五个路由 ----

    def _handle_register(self):
        raw = self._read_json()
        raw_port = raw.get('port') if isinstance(raw, dict) else None
        if raw_port is not None:
            try:
                int(raw_port)
            except (TypeError, ValueError):
                self._send_json(400, {'message': 'invalid port'})
                return
        info = DeviceInfo.from_dict(raw)
        ip = self.client_address[0]
        own = self.server.device_info
        if info.fingerprint and info.fingerprint != own.fingerprint:
            _safe_call(self.server.on_device_found, info, ip)
        self._send_json(200, own.to_dict())

    def _handle_prepare(self):
        body = self._read_json()
        info_dict = body.get('info') if isinstance(body, dict) else None
        files = body.get('files') if isinstance(body, dict) else None
        if not isinstance(info_dict, dict) or not isinstance(files, dict) or not files:
            self._send_json(400, {'message': 'missing info or files'})
            return
        for meta in files.values():
            size = meta.get('size') if isinstance(meta, dict) else None
            if not isinstance(size, int) or size < 0:
                self._send_json(400, {'message': 'invalid file size'})
                return
        session_id = uuid.uuid4().hex
        session = {
            'id': session_id,
            'info': DeviceInfo.from_dict(info_dict),
            'ip': self.client_address[0],
            'files': files,                              # {fileId: 元数据}
            'tokens': {fid: uuid.uuid4().hex for fid in files},
            'state': 'pending',
            'save_dir': None,
            'saved': {},                                 # {fileId: 已落盘路径}
            'partial': {},                               # {fileId: 半成品路径}
            'created_at': time.time(),                   # 最后活跃时间（prepare 时初始化）
            'lock': threading.Lock(),
        }
        # 回调由 UI 层注入并阻塞弹窗，核心层只管调用
        save_dir = _safe_call(self.server.on_receive_request, session)
        if not isinstance(save_dir, str) or not save_dir:
            session['state'] = 'rejected'
            self._send_json(403, {'message': 'rejected'})
            return
        session['state'] = 'accepted'
        session['save_dir'] = save_dir
        with self.server.sessions_lock:
            self.server.sessions[session_id] = session
        self._send_json(200, {'sessionId': session_id, 'files': session['tokens']})

    def _handle_upload(self, query):
        session_id = self._query_first(query, 'sessionId')
        file_id = self._query_first(query, 'fileId')
        token = self._query_first(query, 'token')

        def reject(code, message):
            self._drain_body()  # 先排空请求体再拒绝，避免 RST 冲掉响应
            self._send_json(code, {'message': message})

        if not session_id or not file_id or token is None:
            reject(400, 'missing sessionId/fileId/token')
            return
        self.server.sweep_sessions()
        with self.server.sessions_lock:
            session = self.server.sessions.get(session_id)
        if session is None or session['state'] in ('rejected', 'cancelled'):
            reject(403, 'invalid session')
            return
        if session['state'] not in ('accepted', 'transferring'):
            reject(409, 'session conflict')
            return
        if file_id not in session['files']:
            reject(400, 'unknown fileId')
            return
        if session['tokens'].get(file_id) != token:
            reject(403, 'invalid token')
            return
        if self.client_address[0] != session['ip']:
            reject(403, 'ip mismatch')
            return
        # 刷新最后活跃时间：批量长传输总时长超 TTL 也不能误杀自己的会话
        session['created_at'] = time.time()

        meta = session['files'][file_id]
        session['state'] = 'transferring'
        # 防目录穿越：只取文件名部分
        file_name = os.path.basename(meta.get('fileName') or '') or file_id
        with session['lock']:
            fd, target = _create_unique(session['save_dir'], file_name)
            session['partial'][file_id] = target

        # Content-Length 非法或与 prepare 声明的 size 不符：清占位回 400
        length_header = self.headers.get('Content-Length')
        try:
            total = int(length_header or meta.get('size') or 0)
            declared = int(meta['size']) if meta.get('size') is not None else None
        except (TypeError, ValueError):
            total, declared = None, None
        if total is None or (length_header is not None
                             and declared is not None and declared != total):
            with session['lock']:
                session['partial'].pop(file_id, None)
            os.close(fd)  # 占位 fd 尚未 fdopen，先关掉才能删（Windows 占用锁）
            try:
                os.remove(target)
            except OSError:
                pass
            reject(400, 'bad or mismatched content-length')
            return

        sha = hashlib.sha256()
        done = 0
        ok = False
        # 慢速/断连客户端不能让 handler 线程无限挂住；超时按传输中断处理
        self.connection.settimeout(NET_TIMEOUT)
        try:
            # 客户端总会带 Content-Length，按长度精确读取
            remaining = total
            with os.fdopen(fd, 'wb') as f:
                while remaining > 0:
                    if session['state'] == 'cancelled':
                        break  # 对端已取消，走下方中断清理
                    chunk = self.rfile.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        break
                    f.write(chunk)
                    sha.update(chunk)
                    done += len(chunk)
                    remaining -= len(chunk)
                    _safe_call(self.server.on_progress, session_id, file_id, done, total)
            ok = (done >= total)
        except Exception:
            ok = False
        try:
            self.connection.settimeout(NET_TIMEOUT)  # 恢复默认超时
        except OSError:
            pass
        if not ok:
            # 传输中断：删半成品
            with session['lock']:
                session['partial'].pop(file_id, None)
            try:
                os.remove(target)
            except OSError:
                pass
            self._send_json(500, {'message': 'transfer failed'})
            return

        expected = meta.get('sha256')
        if expected and sha.hexdigest() != expected:
            with session['lock']:
                session['partial'].pop(file_id, None)
            try:
                os.remove(target)
            except OSError:
                pass
            self._send_json(422, {'message': 'sha256 mismatch'})
            return

        with session['lock']:
            session['partial'].pop(file_id, None)
            session['saved'][file_id] = target
        _safe_call(self.server.on_file_done, session_id, file_id, target)
        self._send_json(200, {'message': 'ok'})

        with session['lock']:
            finished = all(fid in session['saved'] for fid in session['files'])
        if finished:
            session['state'] = 'done'
            with self.server.sessions_lock:
                self.server.sessions.pop(session_id, None)
            _safe_call(self.server.on_session_done, session_id)

    def _handle_cancel(self, query):
        session_id = self._query_first(query, 'sessionId')
        if not session_id:
            self._send_json(400, {'message': 'missing sessionId'})
            return
        self.server.sweep_sessions()
        with self.server.sessions_lock:
            session = self.server.sessions.pop(session_id, None)
        if session is not None:
            session['state'] = 'cancelled'
            # 只删正在传输的半成品，已完整落盘的文件保留；
            # 若半成品正被上传线程占用（Windows 删不动），由其中断清理路径兜底删除
            for partial in list(session['partial'].values()):
                try:
                    os.remove(partial)
                except OSError:
                    pass
            _safe_call(self.server.on_cancelled, session_id)
        self._send_json(200, {'message': 'cancelled'})


class TransferServer(ThreadingHTTPServer):
    '''HTTP 接收服务端，守护线程运行 serve_forever。'''

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, device_info, port=PORT, host='',
                 on_device_found=None, on_receive_request=None,
                 on_progress=None, on_file_done=None,
                 on_session_done=None, on_cancelled=None):
        self.device_info = device_info
        self.on_device_found = on_device_found          # (info, ip)
        self.on_receive_request = on_receive_request    # (session) -> 保存目录 | None
        self.on_progress = on_progress                  # (session_id, file_id, done, total)
        self.on_file_done = on_file_done                # (session_id, file_id, saved_path)
        self.on_session_done = on_session_done          # (session_id)
        self.on_cancelled = on_cancelled                # (session_id)
        self.sessions = {}
        self.sessions_lock = threading.Lock()
        ThreadingHTTPServer.__init__(self, (host, port), _ApiHandler)
        self.port = self.server_address[1]              # port=0 时读系统分配的实际端口
        self.device_info.port = self.port
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self.serve_forever,
                                        name='transfer-server')
        self._thread.daemon = True
        self._thread.start()

    def stop(self):
        self.shutdown()
        self.server_close()

    def sweep_sessions(self):
        '''清理超过 SESSION_TTL 未活跃的陈旧会话，并删除其半成品文件。

        created_at 语义为最后活跃时间；传输中的会话跳过（双保险，
        其自身有 socket 超时兜底，不会真成孤儿）。'''
        now = time.time()
        with self.sessions_lock:
            stale = [s for s in self.sessions.values()
                     if now - s['created_at'] > SESSION_TTL
                     and s['state'] != 'transferring']
            for s in stale:
                self.sessions.pop(s['id'], None)
        for s in stale:
            s['state'] = 'cancelled'
            for p in list(s['partial'].values()):
                try:
                    os.remove(p)
                except OSError:
                    pass

    def handle_error(self, request, client_address):
        # 客户端中途断连（cancel / 超时）属常态，不打堆栈；业务异常已在分发层兜底
        pass


class Discovery(object):
    '''UDP 组播发现 + /24 子网回退扫描，守护线程运行。

    组播不可用（AP 隔离等）时不崩溃，降级为仅扫描。
    '''

    def __init__(self, device_info, on_device_found=None):
        self.device_info = device_info
        self.on_device_found = on_device_found
        self.devices = {}            # {fingerprint: (DeviceInfo, ip, last_seen)}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._threads = []

    def start(self):
        t = threading.Thread(target=self._listen_loop, name='discovery')
        t.daemon = True
        t.start()
        self._threads.append(t)
        self.announce()              # LocalSend 语义：只在启动时宣告一次

    def stop(self):
        self._stop.set()

    def get_devices(self):
        '''返回当前已知设备 {fingerprint: (DeviceInfo, ip)}。
        LocalSend 语义：不做 TTL 过期剔除，离线设备靠「刷新=清空重建」清理。'''
        with self._lock:
            return {fp: (info, ip) for fp, (info, ip, _) in self.devices.items()}

    def clear_devices(self):
        '''清空已知设备（刷新按钮的清空重建语义）。'''
        with self._lock:
            self.devices.clear()

    def _register_seen(self, info, ip):
        with self._lock:
            self.devices[info.fingerprint] = (info, ip, time.time())

    def announce(self):
        '''向组播组发一次宣告（LocalSend 语义：不周期重发）。
        逐网卡发送：多网卡 / VPN TUN 接管默认路由时，不显式指定出口，
        组播报文会发进隧道而不是真实局域网（对端永远收不到 announce）。'''
        payload = self.device_info.to_dict()
        payload['announce'] = True
        data = json.dumps(payload).encode('utf-8')
        for iface in (_local_ipv4() or {None}):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM,
                                     socket.IPPROTO_UDP)
                try:
                    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
                    if iface:
                        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                                        socket.inet_aton(iface))
                    sock.sendto(data, (MULTICAST_GROUP, PORT))
                finally:
                    sock.close()
            except socket.error:
                pass  # 组播发送失败不崩溃，降级为仅扫描

    def _listen_loop(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM,
                                 socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('', PORT))
            # 逐网卡组加入：0.0.0.0 只落在默认网卡上，VPN/虚拟网卡在场时会漏收 LAN 组播
            joined = False
            for iface in (_local_ipv4() or {'0.0.0.0'}):
                try:
                    mreq = struct.pack('4s4s', socket.inet_aton(MULTICAST_GROUP),
                                       socket.inet_aton(iface))
                    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                    joined = True
                except socket.error:
                    pass
            if not joined:
                sock.close()
                return  # 组播监听不可用，降级为仅扫描
            sock.settimeout(1.0)
        except socket.error:
            return  # 组播监听失败不崩溃，降级为仅扫描
        while not self._stop.is_set():
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except socket.error:
                break
            try:
                msg = json.loads(data.decode('utf-8'))
            except ValueError:
                continue
            info = DeviceInfo.from_dict(msg)
            if not info.fingerprint or info.fingerprint == self.device_info.fingerprint:
                continue
            ip = addr[0]
            self._register_seen(info, ip)
            if msg.get('announce'):
                _safe_call(self.on_device_found, info, ip)
                threading.Thread(target=self._reply_register, args=(ip, info.port),
                                 name='discovery-reply', daemon=True).start()

    def _reply_register(self, ip, port):
        # 对 announce 的来源回一个 register，让对端也能看到本机
        url = 'http://%s:%d%sregister' % (ip, port, API_PREFIX)
        try:
            _post_json(url, self.device_info.to_dict(), timeout=5.0)
        except Exception:
            pass

    def scan_subnet(self, on_device_found=None):
        '''对本机各 IPv4 的 /24 子网逐 IP POST /register（并发 SCAN_WORKERS）。'''
        callback = on_device_found or self.on_device_found
        local_ips = _local_ipv4()
        targets = set()
        for ip in local_ips:
            base = ip.rsplit('.', 1)[0]
            for i in range(1, 255):
                candidate = '%s.%d' % (base, i)
                if candidate not in local_ips:
                    targets.add(candidate)

        def probe(ip):
            url = 'http://%s:%d%sregister' % (ip, self.device_info.port, API_PREFIX)
            try:
                _, body = _post_json(url, self.device_info.to_dict(),
                                     timeout=SCAN_TIMEOUT)
                info = DeviceInfo.from_dict(body)
                if info.fingerprint and info.fingerprint != self.device_info.fingerprint:
                    self._register_seen(info, ip)
                    _safe_call(callback, info, ip)
            except Exception:
                pass  # 单 IP 失败属常态（无设备 / 超时），静默跳过

        with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as pool:
            list(pool.map(probe, targets))


def _is_lan_ipv4(ip):
    '''是否 RFC1918 局域网地址。排除 127 回环 / 169.254 链路本地 / 198.18.0.0/15
    基准测试段——Clash 等代理的 TUN 虚拟网卡用 198.18 段做 fake-ip，组播会被它吞掉。'''
    if ip.startswith('192.168.') or ip.startswith('10.'):
        return True
    if ip.startswith('172.'):
        try:
            return 16 <= int(ip.split('.')[1]) <= 31
        except (ValueError, IndexError):
            return False
    return False


def _local_ipv4():
    '''本机局域网 IPv4（仅 RFC1918）；一个都没有时退化为所有非回环地址。'''
    ips = set()
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = item[4][0]
            if not ip.startswith('127.'):
                ips.add(ip)
    except socket.error:
        pass
    if not ips:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.connect(('8.8.8.8', 80))
                ip = sock.getsockname()[0]
            finally:
                sock.close()
            if not ip.startswith('127.'):
                ips.add(ip)
        except socket.error:
            pass
    lan = set(ip for ip in ips if _is_lan_ipv4(ip))
    return lan or ips


def _post_json(url, payload, timeout):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data,
                                 headers={'Content-Type': 'application/json'})
    resp = urllib.request.urlopen(req, timeout=timeout)
    try:
        raw = resp.read()
        return resp.status, json.loads(raw.decode('utf-8'))
    finally:
        resp.close()


def send_files(host, port, files, on_progress=None, on_done=None, device_info=None,
               cancel_event=None):
    '''发送方客户端：prepare-upload -> 逐文件 upload -> 失败 cancel。

    files 为本地路径列表。on_progress(file_index, done_bytes, total_bytes)，
    on_done(ok, message)：被拒时 message 为 'rejected'，主动取消为 'cancelled'。
    cancel_event（threading.Event）置位后中断上传并通知对端 cancel；prepare
    等待确认期间无法打断阻塞 IO，在 prepare 返回后检查。同步阻塞，调用方自行放线程。
    '''
    if device_info is None:
        device_info = DeviceInfo.local(socket.gethostname(), uuid.uuid4().hex)
    base = 'http://%s:%d%s' % (host, port, API_PREFIX)

    file_meta = {}
    order = []
    try:
        for path in files:
            file_id = uuid.uuid4().hex
            mime = mimetypes.guess_type(path)[0] or 'application/octet-stream'
            file_meta[file_id] = {
                'id': file_id,
                'fileName': os.path.basename(path),
                'size': os.path.getsize(path),
                'fileType': mime,
                # 发送端不预计算大文件哈希，协议允许 sha256 为 null
            }
            order.append((file_id, path))
    except OSError as exc:
        _safe_call(on_done, False, '%s' % exc)
        return

    try:
        _, body = _post_json(base + 'prepare-upload',
                             {'info': device_info.to_dict(), 'files': file_meta},
                             timeout=PREPARE_TIMEOUT)
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            _safe_call(on_done, False, 'rejected')
        else:
            _safe_call(on_done, False, 'prepare-upload HTTP %d' % exc.code)
        return
    except (socket.timeout, TimeoutError):
        # 对方还在确认弹窗上犹豫，与网络失败区分开
        _safe_call(on_done, False, '对方未及时确认')
        return
    except Exception as exc:
        _safe_call(on_done, False, 'prepare-upload: %s' % exc)
        return

    session_id = body.get('sessionId')
    tokens = body.get('files') or {}
    if not session_id:
        _safe_call(on_done, False, 'prepare-upload: no sessionId')
        return

    for index, (file_id, path) in enumerate(order):
        # prepare 等待确认期间点下的取消在此生效；每个文件上传前也检查一次
        if cancel_event is not None and cancel_event.is_set():
            err = 'cancelled'
        else:
            err = _upload_one(host, port, session_id, file_id,
                              tokens.get(file_id) or '', path, index,
                              on_progress, cancel_event)
        if err is not None:
            try:
                req = urllib.request.Request(
                    base + 'cancel?' + urllib.parse.urlencode({'sessionId': session_id}),
                    data=b'')
                urllib.request.urlopen(req, timeout=NET_TIMEOUT).close()
            except Exception:
                pass
            _safe_call(on_done, False, err)
            return
    _safe_call(on_done, True, '')


def _upload_one(host, port, session_id, file_id, token, path, index, on_progress,
                cancel_event=None):
    '''分块 POST 单个文件，每块回调进度；返回 None 表示成功，否则为错误描述。

    cancel_event 置位时中断发送并返回 'cancelled'；连接由 finally 关闭，
    对端按传输中断清理半成品。'''
    size = os.path.getsize(path)
    conn = http.client.HTTPConnection(host, port, timeout=NET_TIMEOUT)
    try:
        query = urllib.parse.urlencode({'sessionId': session_id,
                                        'fileId': file_id, 'token': token})
        conn.putrequest('POST', '%supload?%s' % (API_PREFIX, query))
        conn.putheader('Content-Length', str(size))
        conn.putheader('Content-Type', 'application/octet-stream')
        conn.endheaders()
        done = 0
        with open(path, 'rb') as f:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    return 'cancelled'
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                conn.send(chunk)
                done += len(chunk)
                _safe_call(on_progress, index, done, size)
        resp = conn.getresponse()
        body = resp.read()
        if resp.status != 200:
            return 'upload HTTP %d: %s' % (
                resp.status, body[:200].decode('utf-8', 'replace'))
        return None
    except (socket.error, http.client.HTTPException, OSError) as exc:
        return '%s' % exc
    finally:
        conn.close()

