"""UDP (pose) + TCP (control / frames) server running in background threads. No bpy here."""
import collections
import socket
import sys
import threading
import time

from . import protocol

HELLO_TIMEOUT = 3.0
_IS_WIN = sys.platform.startswith("win")


def _set_reuse(sock):
    if not _IS_WIN:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)


def _abort_close(sock):
    """Close without TIME_WAIT so the port can be bound again right away."""
    try:
        import struct
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


class _Client:
    def __init__(self, sock, addr):
        self.sock = sock
        self.addr = addr
        self.buf = b""
        self.since = time.monotonic()
        self.device = None


class Server:
    def __init__(self, port: int = protocol.DEFAULT_PORT, token: str = "", host: str = "0.0.0.0"):
        self.host = host
        self.port = int(port)
        self.token = token
        self.client_name = None
        self.client_addr = None
        self._udp = None
        self._tcp = None
        self._client = None          # authenticated _Client
        self._pending = []           # connected, waiting for hello
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._send_cv = threading.Condition(self._send_lock)
        self._out_msgs = collections.deque()
        self._out_frame = None
        self._controls = collections.deque()
        self._poses = collections.deque(maxlen=4096)
        self._latest = None
        self._filter = protocol.PoseFilter()
        self._stop = threading.Event()
        self._threads = []
        self._last_packet = None
        self._times = collections.deque()
        self._rejected = 0
        self._accepted = 0
        self._last_addr = None
        self.frames_sent = 0
        self.frames_skipped = 0
        self.running = False

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        if self.running:
            return
        self._stop.clear()
        tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _set_reuse(tcp)
        try:
            tcp.bind((self.host, self.port))
            self.port = tcp.getsockname()[1]
            udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            _set_reuse(udp)
            udp.bind((self.host, self.port))
        except OSError:
            tcp.close()
            raise
        tcp.listen(4)
        tcp.settimeout(0.05)
        udp.settimeout(0.05)
        self._tcp, self._udp = tcp, udp
        self._filter.reset()
        self.running = True
        for target in (self._udp_loop, self._tcp_loop, self._send_loop):
            th = threading.Thread(target=target, daemon=True, name="blendcam-" + target.__name__)
            th.start()
            self._threads.append(th)

    def stop(self):
        if not self.running:
            return
        self._stop.set()
        with self._send_cv:
            self._send_cv.notify_all()
        for th in self._threads:
            th.join(timeout=1.0)
        self._threads = []
        for s in (self._udp, self._tcp):
            try:
                s.close()
            except OSError:
                pass
        with self._lock:
            for c in self._pending:
                _abort_close(c.sock)
            self._pending = []
            if self._client:
                _abort_close(self._client.sock)
            self._client = None
            self.client_name = None
            self.client_addr = None
        self._udp = self._tcp = None
        self.running = False

    # ------------------------------------------------------------------ public API
    def latest_pose(self):
        return self._latest

    def drain_poses(self):
        out = []
        while True:
            try:
                out.append(self._poses.popleft())
            except IndexError:
                return out

    def poll_controls(self):
        out = []
        while True:
            try:
                out.append(self._controls.popleft())
            except IndexError:
                return out

    def send(self, msg: dict):
        if self._client is None:
            return False
        with self._send_cv:
            self._out_msgs.append(protocol.encode_control(msg))
            while len(self._out_msgs) > 64:
                self._out_msgs.popleft()
            self._send_cv.notify()
        return True

    def frame_busy(self) -> bool:
        return self._out_frame is not None

    def send_frame(self, jpeg: bytes, ts: float = None) -> bool:
        """Queue one JPEG frame. If the previous one has not gone out yet it is replaced (never piles up)."""
        if self._client is None:
            return False
        with self._send_cv:
            if self._out_frame is not None:
                self.frames_skipped += 1
            self._out_frame = protocol.encode_frame_header(len(jpeg), ts) + jpeg
            self._send_cv.notify()
        return True

    def has_client(self) -> bool:
        return self._client is not None

    def last_packet_age(self) -> float:
        if self._last_packet is None:
            return float("inf")
        return time.monotonic() - self._last_packet

    def stats(self) -> dict:
        now = time.monotonic()
        while self._times and now - self._times[0] > 1.0:
            self._times.popleft()
        return {
            "listening": self.running,
            "port": self.port,
            "pps": len(self._times),
            "addr": self._last_addr,
            "rejected": self._rejected,
            "accepted": self._accepted,
            "client": self.client_name,
            "client_addr": self.client_addr,
            "age": self.last_packet_age(),
        }

    # ------------------------------------------------------------------ threads
    def _udp_loop(self):
        udp = self._udp
        while not self._stop.is_set():
            try:
                data, addr = udp.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                if self._stop.is_set():
                    return
                time.sleep(0.01)  # Windows: ICMP port unreachable resets; keep listening
                continue
            p = protocol.parse_pose(data, self.token)
            if p is None:
                self._rejected += 1
                continue
            self._last_addr = addr[0]
            now = time.monotonic()
            self._last_packet = now
            self._times.append(now)
            if self._filter.accept(p):
                self._accepted += 1
                self._latest = p
                self._poses.append(p)

    def _tcp_loop(self):
        import select

        while not self._stop.is_set():
            socks = [self._tcp]
            with self._lock:
                pend = list(self._pending)
                cl = self._client
            socks += [c.sock for c in pend]
            if cl:
                socks.append(cl.sock)
            try:
                readable, _, _ = select.select(socks, [], [], 0.05)
            except (OSError, ValueError):
                readable = []
                self._drop_dead()
            now = time.monotonic()
            for s in readable:
                if s is self._tcp:
                    try:
                        cs, addr = self._tcp.accept()
                    except (socket.timeout, OSError):
                        continue
                    cs.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    cs.setblocking(False)
                    with self._lock:
                        self._pending.append(_Client(cs, addr))
                    continue
                c = cl if (cl and s is cl.sock) else next((p for p in pend if p.sock is s), None)
                if c is None:
                    continue
                try:
                    chunk = s.recv(65536)
                except (BlockingIOError, InterruptedError):
                    continue
                except OSError:
                    chunk = b""
                if not chunk:
                    self._close(c)
                    continue
                c.buf += chunk
                if len(c.buf) > 1 << 20:
                    self._close(c)
                    continue
                while b"\n" in c.buf:
                    line, c.buf = c.buf.split(b"\n", 1)
                    self._handle_line(c, line)
            # hello timeout for pending clients
            with self._lock:
                late = [p for p in self._pending if now - p.since > HELLO_TIMEOUT]
            for p in late:
                self._close(p)

    def _drop_dead(self):
        with self._lock:
            alive = []
            for p in self._pending:
                if p.sock.fileno() >= 0:
                    alive.append(p)
            self._pending = alive

    def _handle_line(self, c, line):
        msg = protocol.parse_control(line.strip())
        if msg is None:
            return
        if c is not self._client:
            if msg.get("type") == "hello" and msg.get("token") == self.token:
                old = None
                with self._lock:
                    if c in self._pending:
                        self._pending.remove(c)
                    old, self._client = self._client, c
                    c.device = str(msg.get("device") or "iPhone")[:64]
                    self.client_name = c.device
                    self.client_addr = c.addr[0]
                self._filter.reset()  # a new phone session starts counting from 0
                if old is not None:
                    _abort_close(old.sock)
                with self._send_cv:
                    self._out_msgs.clear()
                    self._out_frame = None
                self._controls.append({"type": "hello", "device": c.device})
            elif msg.get("type") == "hello":
                self._rejected += 1
                self._close(c)
            return
        if msg.get("type") == "hello":
            return
        self._controls.append(msg)

    def _close(self, c):
        was_client = False
        with self._lock:
            if c in self._pending:
                self._pending.remove(c)
            if c is self._client:
                self._client = None
                self.client_name = None
                self.client_addr = None
                was_client = True
        _abort_close(c.sock)
        if was_client:
            self._controls.append({"type": "_bye"})

    def _send_loop(self):
        while not self._stop.is_set():
            with self._send_cv:
                while not self._out_msgs and self._out_frame is None and not self._stop.is_set():
                    self._send_cv.wait(0.2)
                if self._stop.is_set():
                    return
                if self._out_msgs:
                    data = self._out_msgs.popleft()
                    is_frame = False
                else:
                    data = self._out_frame
                    is_frame = True
                c = self._client
            if c is None:
                with self._send_cv:
                    if is_frame:
                        self._out_frame = None
                continue
            ok = self._sendall(c, data)
            with self._send_cv:
                if is_frame:
                    if self._out_frame is data:
                        self._out_frame = None
                    if ok:
                        self.frames_sent += 1
            if not ok:
                self._close(c)

    def _sendall(self, c, data) -> bool:
        import select

        view = memoryview(data)
        deadline = time.monotonic() + 2.0
        while view:
            if self._stop.is_set() or c is not self._client:
                return True
            try:
                n = c.sock.send(view)
                view = view[n:]
            except (BlockingIOError, InterruptedError):
                try:
                    select.select([], [c.sock], [], 0.05)
                except (OSError, ValueError):
                    return False
                if time.monotonic() > deadline:
                    return False
            except OSError:
                return False
        return True


def local_ipv4s():
    """All IPv4 addresses of this computer on local networks (no packets are sent)."""
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))  # no traffic: UDP connect only picks a route
            ips.append(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    ips = [ip for ip in ips if not ip.startswith("127.") and not ip.startswith("0.")]

    def rank(ip):
        if ip.startswith("192.168."):
            return 0
        if ip.startswith("10."):
            return 1
        if ip.startswith("172."):
            return 2
        if ip.startswith("169.254."):
            return 9
        return 5

    primary = ips[:1]
    rest = sorted(ips[1:], key=rank)
    return primary + rest if ips else ["127.0.0.1"]
