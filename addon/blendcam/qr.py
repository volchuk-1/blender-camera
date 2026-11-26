"""Minimal QR code generator (byte mode, versions 1-10, ECC level M). Pure Python, no dependencies.

Follows the QR Code Model 2 specification (ISO/IEC 18004); structure after Project Nayuki's
reference implementation (MIT). Returns a square matrix of booleans, True = dark.
"""

# ECC level M, index = version (0 unused)
_ECC_PER_BLOCK_M = (-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26)
_NUM_BLOCKS_M = (-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5)
_FORMAT_BITS_M = 0
MAX_VERSION = 10


def _raw_data_modules(ver):
    result = (16 * ver + 128) * ver + 64
    if ver >= 2:
        numalign = ver // 7 + 2
        result -= (25 * numalign - 10) * numalign - 55
        if ver >= 7:
            result -= 36
    return result


def _data_codewords(ver):
    return _raw_data_modules(ver) // 8 - _ECC_PER_BLOCK_M[ver] * _NUM_BLOCKS_M[ver]


def _rs_mul(x, y):
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree):
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _rs_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _rs_mul(root, 0x02)
    return result


def _rs_remainder(data, divisor):
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _rs_mul(coef, factor)
    return result


def _bit(x, i):
    return (x >> i) & 1 != 0


class _Builder:
    def __init__(self, ver):
        self.ver = ver
        self.size = ver * 4 + 17
        n = self.size
        self.mod = [[False] * n for _ in range(n)]
        self.func = [[False] * n for _ in range(n)]

    def setf(self, x, y, dark):
        self.mod[y][x] = dark
        self.func[y][x] = True

    def alignment_positions(self):
        if self.ver == 1:
            return []
        numalign = self.ver // 7 + 2
        step = (self.ver * 8 + numalign * 3 + 5) // (numalign * 4 - 4) * 2
        result = [self.size - 7 - i * step for i in range(numalign - 1)] + [6]
        return list(reversed(result))

    def draw_function_patterns(self):
        n = self.size
        for i in range(n):
            self.setf(6, i, i % 2 == 0)
            self.setf(i, 6, i % 2 == 0)
        for (cx, cy) in ((3, 3), (n - 4, 3), (3, n - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < n and 0 <= y < n:
                        self.setf(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        pos = self.alignment_positions()
        last = len(pos) - 1
        for i, ax in enumerate(pos):
            for j, ay in enumerate(pos):
                if (i == 0 and j == 0) or (i == 0 and j == last) or (i == last and j == 0):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.setf(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)
        self.draw_format(0)
        if self.ver >= 7:
            rem = self.ver
            for _ in range(12):
                rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
            bits = self.ver << 12 | rem
            for i in range(18):
                b = _bit(bits, i)
                a = n - 11 + i % 3
                c = i // 3
                self.setf(a, c, b)
                self.setf(c, a, b)

    def draw_format(self, mask):
        n = self.size
        data = _FORMAT_BITS_M << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        for i in range(0, 6):
            self.setf(8, i, _bit(bits, i))
        self.setf(8, 7, _bit(bits, 6))
        self.setf(8, 8, _bit(bits, 7))
        self.setf(7, 8, _bit(bits, 8))
        for i in range(9, 15):
            self.setf(14 - i, 8, _bit(bits, i))
        for i in range(0, 8):
            self.setf(n - 1 - i, 8, _bit(bits, i))
        for i in range(8, 15):
            self.setf(8, n - 15 + i, _bit(bits, i))
        self.setf(8, n - 8, True)

    def draw_codewords(self, data):
        n = self.size
        i = 0
        total = len(data) * 8
        right = n - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(n):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = (n - 1 - vert) if upward else vert
                    if not self.func[y][x] and i < total:
                        self.mod[y][x] = _bit(data[i >> 3], 7 - (i & 7))
                        i += 1
            right -= 2

    def apply_mask(self, mask):
        n = self.size
        for y in range(n):
            for x in range(n):
                if self.func[y][x]:
                    continue
                if mask == 0:
                    inv = (x + y) % 2 == 0
                elif mask == 1:
                    inv = y % 2 == 0
                elif mask == 2:
                    inv = x % 3 == 0
                elif mask == 3:
                    inv = (x + y) % 3 == 0
                elif mask == 4:
                    inv = (x // 3 + y // 2) % 2 == 0
                elif mask == 5:
                    inv = x * y % 2 + x * y % 3 == 0
                elif mask == 6:
                    inv = (x * y % 2 + x * y % 3) % 2 == 0
                else:
                    inv = ((x + y) % 2 + x * y % 3) % 2 == 0
                if inv:
                    self.mod[y][x] = not self.mod[y][x]

    def penalty(self):
        """Rules 1, 2 and 4 of the spec (rule 3 omitted: any mask is valid, this only picks a good one)."""
        n = self.size
        m = self.mod
        score = 0
        for line in list(m) + [[m[y][x] for y in range(n)] for x in range(n)]:
            run = 1
            for k in range(1, n):
                if line[k] == line[k - 1]:
                    run += 1
                else:
                    if run >= 5:
                        score += run - 2
                    run = 1
            if run >= 5:
                score += run - 2
        for y in range(n - 1):
            for x in range(n - 1):
                c = m[y][x]
                if c == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    score += 3
        dark = sum(sum(1 for v in row if v) for row in m)
        total = n * n
        k = (abs(dark * 20 - total * 10) + total - 1) // total - 1
        score += max(0, k) * 10
        return score


def _encode_data(payload: bytes, ver: int):
    cap = _data_codewords(ver)
    cc_bits = 8 if ver <= 9 else 16
    bits = []

    def put(val, n):
        for i in reversed(range(n)):
            bits.append((val >> i) & 1)

    put(0b0100, 4)
    put(len(payload), cc_bits)
    for b in payload:
        put(b, 8)
    capacity = cap * 8
    put(0, min(4, capacity - len(bits)))
    put(0, (8 - len(bits) % 8) % 8)
    pad = 0xEC
    while len(bits) < capacity:
        put(pad, 8)
        pad ^= 0xEC ^ 0x11
    data = []
    for i in range(0, len(bits), 8):
        v = 0
        for b in bits[i:i + 8]:
            v = (v << 1) | b
        data.append(v)
    return data


def _add_ecc(data, ver):
    numblocks = _NUM_BLOCKS_M[ver]
    blockecclen = _ECC_PER_BLOCK_M[ver]
    rawcodewords = _raw_data_modules(ver) // 8
    numshort = numblocks - rawcodewords % numblocks
    shortlen = rawcodewords // numblocks
    div = _rs_divisor(blockecclen)
    blocks = []
    k = 0
    for i in range(numblocks):
        dat = data[k:k + shortlen - blockecclen + (0 if i < numshort else 1)]
        k += len(dat)
        ecc = _rs_remainder(dat, div)
        if i < numshort:
            dat = dat + [0]
        blocks.append(dat + ecc)
    result = []
    for i in range(len(blocks[0])):
        for j, blk in enumerate(blocks):
            if i != shortlen - blockecclen or j >= numshort:
                result.append(blk[i])
    return result


def encode(text: str):
    """Return the QR matrix (list of rows of bools) for `text` (UTF-8 byte mode, ECC M)."""
    payload = text.encode("utf-8")
    ver = None
    for v in range(1, MAX_VERSION + 1):
        cc_bits = 8 if v <= 9 else 16
        if 4 + cc_bits + 8 * len(payload) <= _data_codewords(v) * 8:
            ver = v
            break
    if ver is None:
        raise ValueError("text too long for a QR code here")
    codewords = _add_ecc(_encode_data(payload, ver), ver)
    best = None
    for mask in range(8):
        b = _Builder(ver)
        b.draw_function_patterns()
        b.draw_codewords(codewords)
        b.apply_mask(mask)
        b.draw_format(mask)
        p = b.penalty()
        if best is None or p < best[0]:
            best = (p, b)
    return best[1].mod


def runs(matrix):
    """Dark modules merged into horizontal runs: list of (x, y, length). Handy for drawing."""
    out = []
    for y, row in enumerate(matrix):
        x = 0
        n = len(row)
        while x < n:
            if row[x]:
                start = x
                while x < n and row[x]:
                    x += 1
                out.append((start, y, x - start))
            else:
                x += 1
    return out
