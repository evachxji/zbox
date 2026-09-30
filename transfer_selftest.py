# -*- coding: utf-8 -*-
'''transfer.py 的自动化协议自检。

不依赖 Qt、不依赖组播（单机组播不可靠，用直连 register 代替发现）。
两个 TransferServer 均用 port=0 让系统动态分配端口，避免与常驻实例冲突。
全部用例通过打印 SELFTEST OK 并 exit 0，任一失败打印详情并 exit 1。
'''

import hashlib
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request

import transfer

API = transfer.API_PREFIX


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(transfer.CHUNK_SIZE)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def post_json(url, payload, timeout=5.0):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data,
                                 headers={'Content-Type': 'application/json'})
    resp = urllib.request.urlopen(req, timeout=timeout)
    try:
        return resp.status, json.loads(resp.read().decode('utf-8'))
    finally:
        resp.close()


def http_get(url, timeout=5.0):
    resp = urllib.request.urlopen(url, timeout=timeout)
    try:
        return resp.status, json.loads(resp.read().decode('utf-8'))
    finally:
        resp.close()


def post_raw(url, data, timeout=5.0):
    req = urllib.request.Request(url, data=data)
    resp = urllib.request.urlopen(req, timeout=timeout)
    try:
        return resp.status
    finally:
        resp.close()


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


class Ctx(object):
    '''两台动态端口的接收服务端，on_receive_request 走可替换的 recv_dir_box。'''

    def __init__(self):
        self.info_a = transfer.DeviceInfo(alias='SelfTest-A', fingerprint='a' * 32)
        self.info_b = transfer.DeviceInfo(alias='SelfTest-B', fingerprint='b' * 32)
        self.found_on_a = []        # A 通过 register 看到的设备
        self.box_a = {'dir': None}  # 非 None=接受并保存到该目录，None=拒绝
        self.box_b = {'dir': None}
        self.cancelled = []
        self.srv_a = transfer.TransferServer(
            self.info_a, port=0,
            on_device_found=lambda info, ip: self.found_on_a.append((info, ip)),
            on_receive_request=lambda session: self.box_a['dir'],
            on_cancelled=lambda sid: self.cancelled.append(sid))
        self.srv_b = transfer.TransferServer(
            self.info_b, port=0,
            on_receive_request=lambda session: self.box_b['dir'])
        self.srv_a.start()
        self.srv_b.start()

    def url_a(self, route):
        return 'http://127.0.0.1:%d%s%s' % (self.srv_a.port, API, route)

    def url_b(self, route):
        return 'http://127.0.0.1:%d%s%s' % (self.srv_b.port, API, route)

    def stop(self):
        self.srv_a.stop()
        self.srv_b.stop()


def case_register(ctx):
    # 用例 1：B 直连 A 的 register，双方互见 DeviceInfo
    status, body = post_json(ctx.url_a('register'), ctx.info_b.to_dict())
    check(status == 200, 'register 应回 200，实际 %d' % status)
    check(body.get('fingerprint') == ctx.info_a.fingerprint,
          'register 响应应携带 A 的 fingerprint')
    check(body.get('alias') == 'SelfTest-A', 'register 响应应携带 A 的 alias')
    deadline = time.time() + 3.0
    while not ctx.found_on_a and time.time() < deadline:
        time.sleep(0.05)
    check(ctx.found_on_a, 'A 的 on_device_found 未被回调')
    info, ip = ctx.found_on_a[0]
    check(info.fingerprint == ctx.info_b.fingerprint, 'A 看到的应是 B 的 fingerprint')
    check(info.alias == 'SelfTest-B', 'A 看到的应是 B 的 alias')
    check(ip == '127.0.0.1', 'A 看到的来源 IP 应为 127.0.0.1，实际 %s' % ip)


def case_info(ctx):
    # 用例 2：GET /info 字段完整
    status, body = http_get(ctx.url_b('info'))
    check(status == 200, 'info 应回 200，实际 %d' % status)
    for key in ('alias', 'version', 'deviceModel', 'deviceType',
                'fingerprint', 'port', 'protocol'):
        check(key in body, 'info 缺少字段 %s' % key)
    check(body['alias'] == 'SelfTest-B', 'info.alias 不符')
    check(body['fingerprint'] == 'b' * 32, 'info.fingerprint 不符')
    check(body['port'] == ctx.srv_b.port, 'info.port 应为实际端口')
    check(body['protocol'] == 'http', 'info.protocol 应为 http')


def case_transfer(ctx):
    # 用例 3：A->B 传 3 个文件（0 字节 / 10MB 随机 / 中文文件名），校验落盘 sha256
    root = tempfile.mkdtemp(prefix='zviber_case3_')
    try:
        src = os.path.join(root, 'src')
        recv = os.path.join(root, 'recv')
        os.makedirs(src)
        os.makedirs(recv)
        paths = []
        p = os.path.join(src, 'empty.bin')
        open(p, 'wb').close()
        paths.append(p)
        p = os.path.join(src, 'big.bin')
        with open(p, 'wb') as f:
            f.write(os.urandom(10 * 1024 * 1024))
        paths.append(p)
        p = os.path.join(src, '中文 文件名.txt')
        with open(p, 'wb') as f:
            f.write('你好，局域网'.encode('utf-8'))
        paths.append(p)

        ctx.box_b['dir'] = recv
        results = []
        progress = []
        transfer.send_files('127.0.0.1', ctx.srv_b.port, paths,
                            on_progress=lambda i, d, t: progress.append((i, d, t)),
                            on_done=lambda ok, msg: results.append((ok, msg)))
        check(results == [(True, '')], '传输应成功，实际 %r' % (results,))
        check(progress, 'on_progress 应被回调')
        for src_path in paths:
            name = os.path.basename(src_path)
            saved = os.path.join(recv, name)
            check(os.path.isfile(saved), '落盘文件缺失: %s' % name)
            check(sha256_of(saved) == sha256_of(src_path),
                  '落盘 sha256 与源不一致: %s' % name)
    finally:
        ctx.box_b['dir'] = None
        shutil.rmtree(root, ignore_errors=True)


def case_reject(ctx):
    # 用例 4：on_receive_request 返回 None 时客户端收到 rejected
    root = tempfile.mkdtemp(prefix='zviber_case4_')
    try:
        p = os.path.join(root, 'x.bin')
        with open(p, 'wb') as f:
            f.write(b'1234')
        ctx.box_b['dir'] = None  # 拒绝
        results = []
        transfer.send_files('127.0.0.1', ctx.srv_b.port, [p],
                            on_done=lambda ok, msg: results.append((ok, msg)))
        check(results == [(False, 'rejected')], '应收到 rejected，实际 %r' % (results,))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_bad_token(ctx):
    # 用例 5：错误 token 的 upload 回 403
    root = tempfile.mkdtemp(prefix='zviber_case5_')
    try:
        recv = os.path.join(root, 'recv')
        os.makedirs(recv)
        ctx.box_b['dir'] = recv
        meta = {'f1': {'id': 'f1', 'fileName': 'x.bin', 'size': 4,
                       'fileType': 'application/octet-stream'}}
        status, body = post_json(ctx.url_b('prepare-upload'),
                                 {'info': ctx.info_a.to_dict(), 'files': meta})
        check(status == 200, 'prepare 应回 200，实际 %d' % status)
        sid = body['sessionId']
        url = ctx.url_b('upload?' + urllib.parse.urlencode(
            {'sessionId': sid, 'fileId': 'f1', 'token': 'wrong-token'}))
        try:
            post_raw(url, b'1234')
            check(False, '错误 token 不应成功')
        except urllib.error.HTTPError as exc:
            check(exc.code == 403, '错误 token 应回 403，实际 %d' % exc.code)
        check(not os.listdir(recv), '错误 token 不应落盘任何文件')
        # 清理服务端遗留会话
        post_raw(ctx.url_b('cancel?' + urllib.parse.urlencode({'sessionId': sid})), b'')
    finally:
        ctx.box_b['dir'] = None
        shutil.rmtree(root, ignore_errors=True)


def case_cancel(ctx):
    # 用例 6：cancel 只删正在传输的半成品，已完整落盘的文件保留
    root = tempfile.mkdtemp(prefix='zviber_case6_')
    sock = None
    try:
        recv = os.path.join(root, 'recv')
        os.makedirs(recv)
        ctx.box_a['dir'] = recv
        meta = {
            'f1': {'id': 'f1', 'fileName': 'part1.bin', 'size': 4,
                   'fileType': 'application/octet-stream'},
            'f2': {'id': 'f2', 'fileName': 'part2.bin', 'size': 1000000,
                   'fileType': 'application/octet-stream'},
        }
        status, body = post_json(ctx.url_a('prepare-upload'),
                                 {'info': ctx.info_b.to_dict(), 'files': meta})
        check(status == 200, 'prepare 应回 200，实际 %d' % status)
        sid = body['sessionId']

        # f1 完整上传
        status = post_raw(ctx.url_a('upload?' + urllib.parse.urlencode(
            {'sessionId': sid, 'fileId': 'f1', 'token': body['files']['f1']})),
            b'1234')
        check(status == 200, 'upload f1 应回 200，实际 %d' % status)
        saved = os.path.join(recv, 'part1.bin')
        check(os.path.isfile(saved), 'f1 应已落盘')

        # f2 用裸 socket 挂起一个只发了 4 字节的上传，制造半成品
        sock = socket.create_connection(('127.0.0.1', ctx.srv_a.port), timeout=5)
        head = ('POST %supload?%s HTTP/1.1\r\nHost: 127.0.0.1\r\n'
                'Content-Length: 1000000\r\n\r\n' % (
                    API, urllib.parse.urlencode(
                        {'sessionId': sid, 'fileId': 'f2',
                         'token': body['files']['f2']})))
        sock.sendall(head.encode('utf-8') + b'1234')
        partial = os.path.join(recv, 'part2.bin')
        deadline = time.time() + 3.0
        while not os.path.isfile(partial) and time.time() < deadline:
            time.sleep(0.05)
        check(os.path.isfile(partial), 'f2 半成品应已出现')

        status = post_raw(ctx.url_a('cancel?' + urllib.parse.urlencode(
            {'sessionId': sid})), b'')
        check(status == 200, 'cancel 应回 200，实际 %d' % status)
        check(sid in ctx.cancelled, 'on_cancelled 未被回调')
        # Windows 上半成品正被上传线程占用，cancel 当场删不动；
        # 断开客户端 socket 触发上传线程中断，由其清理路径删除
        sock.close()
        sock = None
        deadline = time.time() + 3.0
        while os.path.exists(partial) and time.time() < deadline:
            time.sleep(0.05)
        check(not os.path.exists(partial), 'cancel 后半成品应被删除')
        check(os.path.isfile(saved), 'cancel 后已完整落盘的 f1 应保留')
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        ctx.box_a['dir'] = None
        shutil.rmtree(root, ignore_errors=True)


def case_conflict_rename(ctx):
    # 用例 7：同名文件二次接收自动加 " (2)" 后缀，不覆盖旧文件
    root = tempfile.mkdtemp(prefix='zviber_case7_')
    try:
        src = os.path.join(root, 'src')
        recv = os.path.join(root, 'recv')
        os.makedirs(src)
        os.makedirs(recv)
        p = os.path.join(src, 'dup.txt')
        with open(p, 'wb') as f:
            f.write(b'first')
        ctx.box_b['dir'] = recv
        results = []
        transfer.send_files('127.0.0.1', ctx.srv_b.port, [p],
                            on_done=lambda ok, msg: results.append((ok, msg)))
        with open(p, 'wb') as f:
            f.write(b'second-content')
        transfer.send_files('127.0.0.1', ctx.srv_b.port, [p],
                            on_done=lambda ok, msg: results.append((ok, msg)))
        check(results == [(True, ''), (True, '')], '两次传输都应成功，实际 %r' % (results,))
        first = os.path.join(recv, 'dup.txt')
        second = os.path.join(recv, 'dup (2).txt')
        check(os.path.isfile(first), '首个 dup.txt 应存在')
        check(os.path.isfile(second), '第二个应命名为 "dup (2).txt"')
        with open(first, 'rb') as f:
            check(f.read() == b'first', '首个文件不应被覆盖')
        with open(second, 'rb') as f:
            check(f.read() == b'second-content', '第二个文件内容应为第二次发送的内容')
    finally:
        ctx.box_b['dir'] = None
        shutil.rmtree(root, ignore_errors=True)


def case_path_sanitize(ctx):
    # 用例 8：fileName 目录穿越净化为纯文件名，落盘不越出保存目录
    root = tempfile.mkdtemp(prefix='zviber_case8_')
    try:
        recv = os.path.join(root, 'recv')
        os.makedirs(recv)
        ctx.box_b['dir'] = recv
        meta = {
            'f1': {'id': 'f1', 'fileName': '../../evil.txt', 'size': 3,
                   'fileType': 'text/plain'},
            'f2': {'id': 'f2', 'fileName': '..\\..\\evil.txt', 'size': 3,
                   'fileType': 'text/plain'},
        }
        status, body = post_json(ctx.url_b('prepare-upload'),
                                 {'info': ctx.info_a.to_dict(), 'files': meta})
        check(status == 200, 'prepare 应回 200，实际 %d' % status)
        sid = body['sessionId']
        for fid in ('f1', 'f2'):
            status = post_raw(ctx.url_b('upload?' + urllib.parse.urlencode(
                {'sessionId': sid, 'fileId': fid,
                 'token': body['files'][fid]})), b'abc')
            check(status == 200, 'upload %s 应回 200，实际 %d' % (fid, status))
        names = sorted(os.listdir(recv))
        check(names == ['evil (2).txt', 'evil.txt'],
              '穿越文件名应净化落盘为 evil.txt / evil (2).txt，实际 %r' % (names,))
        check(not os.path.exists(os.path.join(root, 'evil.txt')),
              '不应在保存目录之外落盘')
    finally:
        ctx.box_b['dir'] = None
        shutil.rmtree(root, ignore_errors=True)


def case_bad_port(ctx):
    # 用例 9：坏 port（"abc"）的 register 回 400；from_dict 安全回退保证监听线程不死
    bad = ctx.info_b.to_dict()
    bad['port'] = 'abc'
    try:
        post_json(ctx.url_a('register'), bad)
        check(False, '坏 port 的 register 不应成功')
    except urllib.error.HTTPError as exc:
        check(exc.code == 400, '坏 port 应回 400，实际 %d' % exc.code)
    # 监听线程解析同款坏包不应崩溃：from_dict 回退默认端口
    info = transfer.DeviceInfo.from_dict(bad)
    check(info.port == transfer.PORT, '坏 port 应回退默认端口，实际 %r' % info.port)
    check(info.fingerprint == ctx.info_b.fingerprint, '其余字段应正常解析')
    # 再发正常 register 仍能登记（处理路径未被坏包破坏）
    before = len(ctx.found_on_a)
    status, _ = post_json(ctx.url_a('register'), ctx.info_b.to_dict())
    check(status == 200, '正常 register 应回 200，实际 %d' % status)
    deadline = time.time() + 3.0
    while len(ctx.found_on_a) <= before and time.time() < deadline:
        time.sleep(0.05)
    check(len(ctx.found_on_a) > before, '坏包之后正常包应仍能登记')


def case_size_mismatch(ctx):
    # 用例 10：upload 的 Content-Length 与 prepare 声明的 size 不符 → 400
    root = tempfile.mkdtemp(prefix='zviber_case10_')
    try:
        recv = os.path.join(root, 'recv')
        os.makedirs(recv)
        ctx.box_b['dir'] = recv
        meta = {'f1': {'id': 'f1', 'fileName': 'm.bin', 'size': 100,
                       'fileType': 'application/octet-stream'}}
        status, body = post_json(ctx.url_b('prepare-upload'),
                                 {'info': ctx.info_a.to_dict(), 'files': meta})
        check(status == 200, 'prepare 应回 200，实际 %d' % status)
        sid = body['sessionId']
        try:
            post_raw(ctx.url_b('upload?' + urllib.parse.urlencode(
                {'sessionId': sid, 'fileId': 'f1',
                 'token': body['files']['f1']})), b'1234')  # 实际 4 字节 != 声明 100
            check(False, 'size 不符不应成功')
        except urllib.error.HTTPError as exc:
            check(exc.code == 400, 'size 不符应回 400，实际 %d' % exc.code)
        check(not os.listdir(recv), 'size 不符不应落盘任何文件')
        post_raw(ctx.url_b('cancel?' + urllib.parse.urlencode({'sessionId': sid})), b'')
    finally:
        ctx.box_b['dir'] = None
        shutil.rmtree(root, ignore_errors=True)


def case_ip_mismatch(ctx):
    # 用例 11：来源 IP 与 prepare 不一致的 upload → 403
    # 本机只有一个回环地址，直接篡改服务端登记的来源 IP 模拟异机抢传
    root = tempfile.mkdtemp(prefix='zviber_case11_')
    try:
        recv = os.path.join(root, 'recv')
        os.makedirs(recv)
        ctx.box_b['dir'] = recv
        meta = {'f1': {'id': 'f1', 'fileName': 'ip.bin', 'size': 4,
                       'fileType': 'application/octet-stream'}}
        status, body = post_json(ctx.url_b('prepare-upload'),
                                 {'info': ctx.info_a.to_dict(), 'files': meta})
        check(status == 200, 'prepare 应回 200，实际 %d' % status)
        sid = body['sessionId']
        with ctx.srv_b.sessions_lock:
            ctx.srv_b.sessions[sid]['ip'] = '10.9.8.7'
        try:
            post_raw(ctx.url_b('upload?' + urllib.parse.urlencode(
                {'sessionId': sid, 'fileId': 'f1',
                 'token': body['files']['f1']})), b'1234')
            check(False, 'IP 不符不应成功')
        except urllib.error.HTTPError as exc:
            check(exc.code == 403, 'IP 不符应回 403，实际 %d' % exc.code)
        check(not os.listdir(recv), 'IP 不符不应落盘任何文件')
        post_raw(ctx.url_b('cancel?' + urllib.parse.urlencode({'sessionId': sid})), b'')
    finally:
        ctx.box_b['dir'] = None
        shutil.rmtree(root, ignore_errors=True)


def case_bad_size_meta(ctx):
    # 用例 12：prepare 元数据缺 size 或 size 非非负整数 → 400（回调不应被触发）
    bad_files = [
        {'f1': {'id': 'f1', 'fileName': 'a.bin',
                'fileType': 'application/octet-stream'}},               # 缺 size
        {'f1': {'id': 'f1', 'fileName': 'a.bin', 'size': -5,
                'fileType': 'application/octet-stream'}},               # 负数
        {'f1': {'id': 'f1', 'fileName': 'a.bin', 'size': 'abc',
                'fileType': 'application/octet-stream'}},               # 非整数
    ]
    for files in bad_files:
        try:
            post_json(ctx.url_b('prepare-upload'),
                      {'info': ctx.info_a.to_dict(), 'files': files})
            check(False, '坏 size 元数据不应成功: %r' % (files,))
        except urllib.error.HTTPError as exc:
            check(exc.code == 400,
                  '坏 size 应回 400，实际 %d（%r）' % (exc.code, files))
    # 合法 prepare 仍可用（校验没有误伤）
    root = tempfile.mkdtemp(prefix='zviber_case12_')
    try:
        ctx.box_b['dir'] = root
        meta = {'f1': {'id': 'f1', 'fileName': 'ok.bin', 'size': 0,
                       'fileType': 'application/octet-stream'}}
        status, body = post_json(ctx.url_b('prepare-upload'),
                                 {'info': ctx.info_a.to_dict(), 'files': meta})
        check(status == 200, 'size=0 的合法 prepare 应回 200，实际 %d' % status)
        post_raw(ctx.url_b('cancel?' + urllib.parse.urlencode(
            {'sessionId': body['sessionId']})), b'')
    finally:
        ctx.box_b['dir'] = None
        shutil.rmtree(root, ignore_errors=True)


def case_send_cancel(ctx):
    # 用例 13：发送方 cancel_event 中断 64MB 上传 → on_done(False, 'cancelled')、
    # 接收端半成品删除、on_cancelled 触发（发给 A，用其 on_cancelled 钩子）
    root = tempfile.mkdtemp(prefix='zviber_case13_')
    try:
        src_dir = os.path.join(root, 'src')
        recv = os.path.join(root, 'recv')
        os.makedirs(src_dir)
        os.makedirs(recv)
        ctx.box_a['dir'] = recv
        big = os.path.join(src_dir, 'big.bin')
        with open(big, 'wb') as f:
            f.write(os.urandom(64 * 1024 * 1024))

        cancel_event = threading.Event()
        done_flag = threading.Event()
        result = {}

        def on_progress(index, done, total):
            # 传到 4MB 时置位取消：替代固定 0.2s 延时，与回环速度无关，
            # 保证必然在传输中触发（64MB 回环传输可能快于 0.2s）
            if done >= 4 * 1024 * 1024:
                cancel_event.set()

        def on_done(ok, err):
            result['ok'] = ok
            result['err'] = err
            done_flag.set()

        t = threading.Thread(
            target=transfer.send_files,
            args=('127.0.0.1', ctx.srv_a.port, [big]),
            kwargs={'on_progress': on_progress, 'on_done': on_done,
                    'device_info': ctx.info_b, 'cancel_event': cancel_event})
        t.daemon = True
        t.start()
        check(done_flag.wait(15.0), 'on_done 未在 15s 内返回')
        t.join(15.0)
        check(result.get('ok') is False,
              '取消后 ok 应为 False，实际 %r' % result.get('ok'))
        check(result.get('err') == 'cancelled',
              "取消后 err 应为 'cancelled'，实际 %r" % result.get('err'))
        # 半成品删除与 on_cancelled 在服务端异步完成，轮询等待
        deadline = time.time() + 5.0
        while time.time() < deadline:
            if not os.listdir(recv) and ctx.cancelled:
                break
            time.sleep(0.05)
        check(not os.listdir(recv),
              '取消后接收端不应有残留文件: %r' % os.listdir(recv))
        check(ctx.cancelled, '接收端 on_cancelled 未触发')
    finally:
        ctx.box_a['dir'] = None
        ctx.cancelled[:] = []
        shutil.rmtree(root, ignore_errors=True)


CASES = [
    ('register 互见设备', case_register),
    ('GET /info 字段完整', case_info),
    ('A->B 传 3 个文件并校验 sha256', case_transfer),
    ('拒绝时客户端收到 rejected', case_reject),
    ('错误 token 回 403', case_bad_token),
    ('cancel 删除半成品', case_cancel),
    ('同名文件自动加 " (2)" 后缀', case_conflict_rename),
    ('fileName 目录穿越净化', case_path_sanitize),
    ('坏 port register 回 400 且不影响后续登记', case_bad_port),
    ('Content-Length 与声明 size 不符回 400', case_size_mismatch),
    ('来源 IP 不符回 403', case_ip_mismatch),
    ('坏 size 元数据 prepare 回 400', case_bad_size_meta),
    ('发送方 cancel_event 中断上传', case_send_cancel),
]


def main():
    ctx = Ctx()
    print('SelfTest: A 端口 %d, B 端口 %d' % (ctx.srv_a.port, ctx.srv_b.port))
    failed = 0
    try:
        for name, fn in CASES:
            try:
                fn(ctx)
                print('[OK] %s' % name)
            except Exception:
                failed += 1
                print('[FAIL] %s' % name)
                traceback.print_exc()
    finally:
        ctx.stop()
    if failed:
        print('SELFTEST FAILED: %d 个用例未通过' % failed)
        return 1
    print('SELFTEST OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
