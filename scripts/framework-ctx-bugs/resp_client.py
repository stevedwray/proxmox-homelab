"""The small RESP2 client needed by framework_lock, using only stdlib."""
import socket


def resp(*args):
    """A Redis command in RESP. Copied from the llama-builds encoder."""
    out = [f"*{len(args)}\r\n".encode()]
    for arg in args:
        data = arg if isinstance(arg, bytes) else str(arg).encode()
        out.append(f"${len(data)}\r\n".encode() + data + b"\r\n")
    return b"".join(out)


def _reply(reader):
    line = reader.readline()
    if not line.endswith(b'\r\n'):
        raise RuntimeError('truncated Redis reply')
    kind, value = line[:1], line[1:-2]
    if kind == b'-':
        raise RuntimeError(value.decode('utf-8', 'replace'))
    if kind == b'+':
        return value
    if kind in (b':', b'$'):
        try:
            number = int(value)
        except ValueError as exc:
            raise RuntimeError('invalid Redis reply length/integer') from exc
        if kind == b':':
            return number
        if number == -1:
            return None
        if number < 0:
            raise RuntimeError('invalid Redis bulk length')
        body = reader.read(number + 2)
        if len(body) != number + 2 or not body.endswith(b'\r\n'):
            raise RuntimeError('truncated Redis bulk reply')
        return body[:-2]
    raise RuntimeError('unsupported Redis reply type')


class RespRedis:
    def __init__(self, host, port, db, password, timeout=10):
        self.host, self.port, self.db = host, int(port), int(db)
        self.password, self.timeout = password, timeout

    def _call(self, *args):
        # Each call has its own connection, including lock-renewal thread calls.
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
            with sock.makefile('rb') as reader:
                for setup in (('AUTH', self.password), ('SELECT', self.db)):
                    sock.sendall(resp(*setup))
                    if _reply(reader) != b'OK':
                        raise RuntimeError(f'Redis {setup[0]} did not return OK')
                sock.sendall(resp(*args))
                return _reply(reader)

    def get(self, key):
        value = self._call('GET', key)
        if value is not None and not isinstance(value, bytes):
            raise RuntimeError('Redis GET did not return bulk bytes or nil')
        return value

    def set(self, key, value, nx=False, ex=None):
        args = ['SET', key, value]
        if nx:
            args.append('NX')
        if ex is not None:
            args.extend(('EX', ex))
        reply = self._call(*args)
        if reply is None:
            return False
        if reply != b'OK':
            raise RuntimeError('Redis SET did not return OK or nil')
        return True

    def expire(self, key, seconds):
        reply = self._call('EXPIRE', key, seconds)
        if not isinstance(reply, int):
            raise RuntimeError('Redis EXPIRE did not return an integer')
        return bool(reply)

    def delete(self, key):
        reply = self._call('DEL', key)
        if not isinstance(reply, int):
            raise RuntimeError('Redis DEL did not return an integer')
        return reply
