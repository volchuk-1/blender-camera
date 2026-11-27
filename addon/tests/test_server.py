import json
import os
import socket
import subprocess
import sys
import time
import unittest

from blendcam import server as srv

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FAKE = os.path.join(ROOT, "tools", "fake_phone.py")
TOKEN = "tok123"


def python_exe():
    return sys.executable


def fake_phone(port, *extra, wait=True, timeout=30):
    cmd = [python_exe(), FAKE, "--host", "127.0.0.1", "--port", str(port), "--token", TOKEN] + list(extra)
    if wait:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8")
    import tempfile

    log = tempfile.TemporaryFile()
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
    proc.log = log
    return proc


def wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.s = srv.Server(0, TOKEN, host="127.0.0.1")
        self.s.start()

    def tearDown(self):
        self.s.stop()

    def test_receives_poses_and_hello(self):
        p = fake_phone(self.s.port, "--path", "circle", "--seconds", "1", "--wait", "0.1")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIsNotNone(self.s.latest_pose())
        ctl = self.s.poll_controls()
        self.assertEqual(ctl[0]["type"], "hello")
        self.assertEqual(ctl[0]["device"], "FakePhone")
        st = self.s.stats()
        self.assertGreater(st["accepted"], 30)
        self.assertEqual(st["addr"], "127.0.0.1")

    def test_foreign_token_rejected(self):
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        pkt = {"v": 1, "seq": 1, "t": 0.0, "token": "WRONG", "m": [0.0] * 16, "trk": "normal",
               "joy": [0, 0], "lift": 0, "focal": 35}
        for _ in range(5):
            u.sendto(json.dumps(pkt).encode(), ("127.0.0.1", self.s.port))
        u.close()
        self.assertTrue(wait_for(lambda: self.s.stats()["rejected"] >= 5))
        self.assertIsNone(self.s.latest_pose())

    def test_shuffled_packets_monotonic(self):
        p = fake_phone(self.s.port, "--path", "line", "--seconds", "2", "--shuffle", "0.3",
                       "--drop", "0.05", "--wait", "0.1")
        self.assertEqual(p.returncode, 0, p.stderr)
        seqs = [x.seq for x in self.s.drain_poses()]
        self.assertGreater(len(seqs), 50)
        self.assertEqual(seqs, sorted(set(seqs)))

    def test_send_state_reaches_phone(self):
        proc = fake_phone(self.s.port, "--path", "still", "--seconds", "2", "--wait", "0.3", wait=False)
        try:
            self.assertTrue(wait_for(lambda: self.s.client_name == "FakePhone"))
            self.s.send({"type": "state", "recording": False, "frame": 7})
            self.s.send({"type": "toast", "text": "Привіт"})
            proc.wait(timeout=20)
        finally:
            if proc.poll() is None:
                proc.kill()
        proc.log.seek(0)
        out = proc.log.read().decode("utf-8")
        proc.log.close()
        lines = [json.loads(l[5:]) for l in out.splitlines() if l.startswith("RECV ")]
        self.assertIn({"type": "state", "recording": False, "frame": 7}, lines)
        self.assertIn({"type": "toast", "text": "Привіт"}, lines)

    def test_hello_wrong_token_disconnects(self):
        c = socket.create_connection(("127.0.0.1", self.s.port), timeout=3)
        c.sendall(b'{"type":"hello","token":"nope","device":"x"}\n')
        c.settimeout(3)
        try:
            self.assertEqual(c.recv(10), b"")
        except ConnectionResetError:
            pass
        c.close()
        self.assertIsNone(self.s.client_name)

    def test_no_hello_timeout(self):
        c = socket.create_connection(("127.0.0.1", self.s.port), timeout=5)
        c.settimeout(5)
        t = time.monotonic()
        try:
            data = c.recv(10)
        except OSError:
            data = b""
        self.assertEqual(data, b"")
        self.assertLess(time.monotonic() - t, 4.5)
        c.close()

    def test_new_hello_replaces_client(self):
        a = socket.create_connection(("127.0.0.1", self.s.port), timeout=3)
        a.sendall(('{"type":"hello","token":"%s","device":"A"}\n' % TOKEN).encode())
        self.assertTrue(wait_for(lambda: self.s.client_name == "A"))
        b = socket.create_connection(("127.0.0.1", self.s.port), timeout=3)
        b.sendall(('{"type":"hello","token":"%s","device":"B"}\n' % TOKEN).encode())
        self.assertTrue(wait_for(lambda: self.s.client_name == "B"))
        a.settimeout(3)
        try:
            self.assertEqual(a.recv(10), b"")
        except ConnectionResetError:
            pass
        a.close()
        b.close()

    def test_stop_frees_port_and_restart(self):
        p = fake_phone(self.s.port, "--path", "still", "--seconds", "0.5", "--wait", "0.1")
        self.assertEqual(p.returncode, 0, p.stderr)
        port = self.s.port
        t = time.monotonic()
        self.s.stop()
        self.assertLess(time.monotonic() - t, 1.5)
        s2 = srv.Server(port, TOKEN, host="127.0.0.1")
        s2.start()
        try:
            self.assertEqual(s2.port, port)
            p = fake_phone(port, "--path", "still", "--seconds", "0.5", "--wait", "0.1")
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIsNotNone(s2.latest_pose())
        finally:
            s2.stop()

    def test_packet_age_grows(self):
        p = fake_phone(self.s.port, "--path", "still", "--seconds", "0.5", "--wait", "0.0")
        self.assertEqual(p.returncode, 0, p.stderr)
        a1 = self.s.last_packet_age()
        time.sleep(0.3)
        self.assertGreater(self.s.last_packet_age(), a1 + 0.2)

    def test_local_ipv4s(self):
        ips = srv.local_ipv4s()
        self.assertTrue(ips)
        for ip in ips:
            self.assertEqual(len(ip.split(".")), 4)
