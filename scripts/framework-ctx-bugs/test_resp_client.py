"""Real loopback RESP traffic, including the unchanged Framework lock lifecycle."""
import contextlib
import io
import json
import socketserver
import threading
import time
import unittest

import ctx_bugs
import framework_lock as lock
from resp_client import RespRedis, _reply, resp


class FakeRedis(socketserver.ThreadingTCPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(('127.0.0.1', 0), Handler)
        self.values = {}
        self.sessions = []
        self.mutex = threading.Lock()
        self.renewed = threading.Event()
        self.offset = 0
        self.command_error = None

    def client(self, db=1, password='test'):
        return RespRedis('127.0.0.1', self.server_address[1], db, password, timeout=2)

    def clock(self):
        return time.monotonic() + self.offset

    def execute(self, db, args):
        op, key = args[:2]
        target = (db, key)
        found = self.values.get(target)
        if found and found[1] is not None and found[1] <= self.clock():
            del self.values[target]
        found = self.values.get(target)
        if op == b'GET':
            if found is None:
                return b'$-1\r\n'
            value = found[0]
            return b'$' + str(len(value)).encode() + b'\r\n' + value + b'\r\n'
        if op == b'SET':
            if b'NX' in args[3:] and found is not None:
                return b'$-1\r\n'
            expiry = None
            if b'EX' in args[3:]:
                ttl = int(args[args.index(b'EX') + 1])
                if ttl <= 0:
                    return b'-ERR invalid expire time\r\n'
                expiry = self.clock() + ttl
            self.values[target] = (args[2], expiry)
            return b'+OK\r\n'
        if op == b'EXPIRE':
            if found is None:
                return b':0\r\n'
            self.values[target] = (found[0], self.clock() + int(args[2]))
            self.renewed.set()
            return b':1\r\n'
        if op == b'DEL':
            if found is None:
                return b':0\r\n'
            del self.values[target]
            return b':1\r\n'
        return b'-ERR unsupported command\r\n'


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        authenticated, db = False, None
        commands = []
        with self.server.mutex:
            self.server.sessions.append(commands)
        while True:
            head = self.rfile.readline()
            if not head:
                return
            if not head.startswith(b'*'):
                return
            args = []
            for _ in range(int(head[1:])):
                size = self.rfile.readline()
                if not size.startswith(b'$'):
                    return
                data = self.rfile.read(int(size[1:]))
                if self.rfile.read(2) != b'\r\n':
                    return
                args.append(data)
            with self.server.mutex:
                commands.append(args)
                if args[0] == b'AUTH':
                    authenticated = args[1] == b'test'
                    reply = b'+OK\r\n' if authenticated else b'-WRONGPASS invalid credentials\r\n'
                elif not authenticated:
                    reply = b'-NOAUTH authentication required\r\n'
                elif args[0] == b'SELECT':
                    db = int(args[1])
                    reply = b'+OK\r\n' if 0 <= db <= 15 else b'-ERR DB index out of range\r\n'
                elif db is None:
                    reply = b'-ERR SELECT required\r\n'
                elif self.server.command_error:
                    reply = b'-' + self.server.command_error + b'\r\n'
                else:
                    reply = self.server.execute(db, args)
            self.wfile.write(reply)
            self.wfile.flush()


@contextlib.contextmanager
def fake_redis():
    server = FakeRedis()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


class RespClientTests(unittest.TestCase):
    def test_methods_binary_values_and_connection_setup(self):
        with fake_redis() as server:
            client = server.client()
            self.assertIsNone(client.get('absent'))
            value = 'needle 雪\r\n'.encode() + b'\0\xff'
            self.assertIs(client.set('key', value, nx=True, ex=10), True)
            self.assertEqual(client.get('key'), value)
            self.assertIs(client.set('key', 'replacement', nx=True, ex=10), False)
            self.assertEqual(client.get('key'), value)
            self.assertIs(client.expire('key', 30), True)
            self.assertIs(client.expire('absent', 30), False)
            self.assertIs(client.set('key', 'replacement'), True)
            self.assertEqual(client.get('key'), b'replacement')
            self.assertEqual(client.delete('key'), 1)
            self.assertEqual(client.delete('key'), 0)
            self.assertEqual(len(server.sessions), 11)
            for commands in server.sessions:
                self.assertEqual(len(commands), 3)
                self.assertEqual(commands[:2], [[b'AUTH', b'test'], [b'SELECT', b'1']])
            self.assertEqual(server.sessions[1][2], [b'SET', b'key', value, b'NX', b'EX', b'10'])

    def test_database_selection_and_ttl(self):
        with fake_redis() as server:
            client, other = server.client(1), server.client(2)
            self.assertTrue(client.set('key', 'one', ex=2))
            self.assertIsNone(other.get('key'))
            self.assertTrue(other.set('key', 'two'))
            server.offset += 3
            self.assertIsNone(client.get('key'))
            self.assertEqual(other.get('key'), b'two')
            self.assertTrue(client.set('key', 'new', nx=True, ex=10))
            self.assertTrue(client.expire('key', 2))
            server.offset += 3
            self.assertIsNone(client.get('key'))

    def test_error_replies_during_auth_select_and_command(self):
        with fake_redis() as server:
            with self.assertRaisesRegex(RuntimeError, 'WRONGPASS'):
                server.client(password='wrong').get('key')
            self.assertEqual(len(server.sessions[-1]), 1)
            with self.assertRaisesRegex(RuntimeError, 'DB index'):
                server.client(db=16).get('key')
            self.assertEqual(len(server.sessions[-1]), 2)
            server.command_error = b'ERR simulated failure'
            with self.assertRaisesRegex(RuntimeError, 'simulated failure'):
                server.client().get('key')
            self.assertEqual(len(server.sessions[-1]), 3)

    def test_parser_rejects_truncated_or_malformed_replies(self):
        for raw in (b'', b'+OK', b'$3\r\na', b'$1\r\naXX', b'$-2\r\n', b':bad\r\n', b'*0\r\n'):
            with self.subTest(reply=raw), self.assertRaises(RuntimeError):
                _reply(io.BytesIO(raw))
        self.assertEqual(_reply(io.BytesIO(b'$0\r\n\r\n')), b'')
        self.assertEqual(resp('SET', '雪', b'\x00'), b'*3\r\n$3\r\nSET\r\n$3\r\n\xe9\x9b\xaa\r\n$1\r\n\x00\r\n')

    def test_lock_acquire_renew_held_and_release(self):
        with fake_redis() as server:
            client = server.client()
            self.assertTrue(lock.acquire(client, 'job-a', 'ctx-bugs', 'ctx-bugs', max_wait=0))
            self.assertEqual(lock.holder(client)['job_id'], 'job-a')
            self.assertFalse(lock.acquire(client, 'job-b', 'other', 'other', max_wait=0))
            self.assertFalse(lock.release(client, 'job-b'))
            # Same job can reacquire without waiting.
            self.assertTrue(lock.acquire(client, 'job-a', 'ctx-bugs', 'ctx-bugs', max_wait=0))
            with lock.held(client, 'job-a', renew_every=.01):
                self.assertTrue(server.renewed.wait(2), 'held() did not renew the lease')
                self.assertEqual(lock.holder(client)['job_id'], 'job-a')
            self.assertIsNone(client.get(lock.LOCK_KEY))
            self.assertFalse(lock.release(client, 'job-a'))
            self.assertTrue(lock.acquire(client, 'job-b', 'ctx-bugs', 'ctx-bugs', max_wait=0))
            self.assertTrue(lock.release(client, 'job-b'))
            self.assertIsNone(lock.holder(client))

    def test_lock_lease_expiry_and_exception_cleanup(self):
        with fake_redis() as server:
            client = server.client()
            self.assertTrue(lock.acquire(client, 'job-a', 'ctx-bugs', 'ctx-bugs', max_wait=0))
            server.offset += lock.TTL + 1
            self.assertTrue(lock.acquire(client, 'job-b', 'ctx-bugs', 'ctx-bugs', max_wait=0))
            self.assertFalse(lock.release(client, 'job-a'))
            with self.assertRaisesRegex(ValueError, 'interrupted'):
                with lock.held(client, 'job-b'):
                    raise ValueError('interrupted')
            self.assertIsNone(lock.holder(client))

    def test_harness_lock_uses_resp_client_and_existing_config(self):
        import tempfile
        from pathlib import Path
        with fake_redis() as server, tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'password').write_text('test\n')
            ctx_bugs.write_json(root/'config.json', dict(publish=dict(host='127.0.0.1', port=server.server_address[1],
                db=2, password_file=str(root/'password'))))
            run = ctx_bugs.Run(ctx_bugs.parse_args(['--dry-run', '--run-dir', str(root/'run'),
                                                   '--redis-config', str(root/'config.json')]))
            run.args.dry_run = False
            run.manifest = dict(job_id='ctx-bugs-test')
            with run.lock():
                self.assertIsInstance(run.redis_client, RespRedis)
                self.assertEqual(lock.holder(server.client(2))['job_id'], 'ctx-bugs-test')
                self.assertIsNone(lock.holder(server.client(1)))
                run.check_lock()
            self.assertIsNone(lock.holder(server.client(2)))


if __name__ == '__main__':
    unittest.main()
