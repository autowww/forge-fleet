#!/usr/bin/env python3
"""Loopback edge: proxy Fleet HTTP, bridge /ssh websocket to sshd.

SSH is a single-threaded select relay. A second thread calling
settimeout() on the same socket as the reader was closing live sessions
a few seconds after login.
"""
import base64
import hashlib
import select
import socket
import threading

LISTEN = ("127.0.0.1", 18765)
FLEET = ("127.0.0.1", 18766)
SSH_ADDR = ("127.0.0.1", 22)
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_WS_IDLE = 60
_WS_OUT_LIMIT = 1024 * 1024


def _read_head(conn):
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = conn.recv(4096)
        if not chunk:
            return None, b""
        buf += chunk
        if len(buf) > 65536:
            return None, buf
    head, rest = buf.split(b"\r\n\r\n", 1)
    return head.decode("iso-8859-1", "replace"), rest


def _encode_ws(payload, opcode=0x2):
    header = bytearray([0x80 | opcode])
    length = len(payload)
    if length < 126:
        header.append(length)
    elif length < 65536:
        header.append(126)
        header.extend(length.to_bytes(2, "big"))
    else:
        header.append(127)
        header.extend(length.to_bytes(8, "big"))
    return bytes(header) + payload


def _send_ws(conn, payload, opcode=0x2):
    conn.sendall(_encode_ws(payload, opcode))


def _take_frames(buf):
    frames = []
    while len(buf) >= 2:
        opcode = buf[0] & 0x0F
        masked = bool(buf[1] & 0x80)
        length = buf[1] & 0x7F
        offset = 2
        if length == 126:
            if len(buf) < 4:
                break
            length = int.from_bytes(buf[2:4], "big")
            offset = 4
        elif length == 127:
            if len(buf) < 10:
                break
            length = int.from_bytes(buf[2:10], "big")
            offset = 10
        mask_len = 4 if masked else 0
        end = offset + mask_len + length
        if len(buf) < end:
            break
        data = buf[offset + mask_len : end]
        if masked:
            mask = buf[offset : offset + 4]
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        frames.append((opcode, data))
        buf = buf[end:]
    return frames, buf


def _flush(conn, pending):
    if not pending:
        return True
    try:
        sent = conn.send(pending)
    except BlockingIOError:
        return True
    if sent <= 0:
        return False
    del pending[:sent]
    return True


def _bridge_ssh(client, rest):
    ssh = socket.create_connection(SSH_ADDR, 5)
    for conn in (client, ssh):
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        if hasattr(socket, "TCP_KEEPIDLE"):
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
        conn.setblocking(False)
    to_ssh = bytearray()
    to_ws = bytearray()
    buf = bytearray(rest)
    try:
        while True:
            frames, leftover = _take_frames(bytes(buf))
            buf = bytearray(leftover)
            for opcode, data in frames:
                if opcode == 0x8:
                    return
                if opcode == 0x9:
                    to_ws.extend(_encode_ws(data, 0xA))
                    continue
                if opcode == 0xA:
                    continue
                if opcode in (0x0, 0x1, 0x2) and data:
                    to_ssh.extend(data)
            readers = []
            if len(to_ssh) < _WS_OUT_LIMIT:
                readers.append(client)
            if len(to_ws) < _WS_OUT_LIMIT:
                readers.append(ssh)
            writers = []
            if to_ssh:
                writers.append(ssh)
            if to_ws:
                writers.append(client)
            readable, writable, _ = select.select(readers, writers, [], _WS_IDLE)
            if not readable and not writable:
                to_ws.extend(_encode_ws(b"ping", 0x9))
                continue
            if client in writable and not _flush(client, to_ws):
                return
            if ssh in writable and not _flush(ssh, to_ssh):
                return
            if client in readable:
                try:
                    chunk = client.recv(65536)
                except BlockingIOError:
                    chunk = None
                if chunk == b"":
                    return
                if chunk:
                    buf.extend(chunk)
            if ssh in readable:
                try:
                    data = ssh.recv(32768)
                except BlockingIOError:
                    data = None
                if data == b"":
                    return
                if data:
                    to_ws.extend(_encode_ws(data, 0x2))
    except OSError:
        return
    finally:
        for conn in (ssh, client):
            try:
                conn.close()
            except OSError:
                pass


def _splice(client, upstream, initial):
    if initial:
        upstream.sendall(initial)
    pair = [client, upstream]
    try:
        while True:
            ready, _, _ = select.select(pair, [], [], 300)
            if not ready:
                return
            for sock in ready:
                data = sock.recv(65536)
                if not data:
                    return
                other = upstream if sock is client else client
                other.sendall(data)
    except OSError:
        return
    finally:
        for sock in pair:
            try:
                sock.close()
            except OSError:
                pass


def _handle(client):
    try:
        head, rest = _read_head(client)
        if not head:
            client.close()
            return
        line = head.split("\r\n", 1)[0]
        parts = line.split(" ")
        path = parts[1] if len(parts) > 1 else "/"
        path_only = path.split("?", 1)[0]
        headers = {
            k.lower(): v.strip()
            for k, _, v in (
                ln.partition(":") for ln in head.split("\r\n")[1:] if ":" in ln
            )
        }
        upgrade = "websocket" in headers.get("upgrade", "").lower()
        if path_only == "/ssh" or path_only.startswith("/ssh/"):
            if not upgrade:
                client.sendall(
                    b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                )
                client.close()
                return
            key = headers.get("sec-websocket-key", "")
            accept = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
            client.sendall(
                (
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept}\r\n"
                    "\r\n"
                ).encode()
            )
            _bridge_ssh(client, rest)
            return
        upstream = socket.create_connection(FLEET, 5)
        upstream.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        _splice(client, upstream, head.encode("iso-8859-1") + b"\r\n\r\n" + rest)
    except OSError:
        try:
            client.close()
        except OSError:
            pass


def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(LISTEN)
    server.listen(64)
    while True:
        client, _ = server.accept()
        client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        threading.Thread(target=_handle, args=(client,), daemon=True).start()


if __name__ == "__main__":
    main()
