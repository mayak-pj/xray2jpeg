"""Минимальный писатель несжатых TIFF для тестов.

Нужен, чтобы получать файлы с точно заданными тегами (MinIsWhite,
порядок байт, многостраничность, BigTIFF) независимо от libvips.
"""

import struct

SHORT, LONG, RATIONAL, ASCII, LONG8 = 3, 4, 5, 2, 16
_FORMATS = {1: "B", ASCII: "B", SHORT: "H", LONG: "I", LONG8: "Q"}


def build_tiff(width, height, samples, bits=16, samples_per_pixel=1, photometric=1,
               byte_order="<", bigtiff=False, pages=1, rows_per_strip=None, extra_tags=(),
               strip_offset_delta=0):
    """samples — плоская последовательность значений (одна страница).

    strip_offset_delta сдвигает StripOffsets — имитация файла, у которого
    заголовок цел, а данные пикселей недоступны (обрезанный файл).
    """
    order = byte_order
    sample_format = "H" if bits == 16 else "B"
    expected = width * height * samples_per_pixel
    if len(samples) != expected:
        raise ValueError("ожидалось {} значений, получено {}".format(expected, len(samples)))
    pixel_data = struct.pack(order + sample_format * expected, *samples)
    rows_per_strip = rows_per_strip or height
    row_bytes = width * samples_per_pixel * (bits // 8)

    if bigtiff:
        buf = bytearray(b"II" if order == "<" else b"MM")
        buf += struct.pack(order + "HHHQ", 43, 8, 0, 0)
        first_ifd_pos, count_fmt, entry_size, inline, offset_fmt = 8, "Q", 20, 8, "Q"
    else:
        buf = bytearray(b"II" if order == "<" else b"MM")
        buf += struct.pack(order + "HI", 42, 0)
        first_ifd_pos, count_fmt, entry_size, inline, offset_fmt = 4, "H", 12, 4, "I"

    next_pointer_pos = first_ifd_pos
    for _ in range(pages):
        _align(buf)
        data_offset = len(buf)
        buf += pixel_data
        strip_offsets, strip_counts = [], []
        for top in range(0, height, rows_per_strip):
            rows = min(rows_per_strip, height - top)
            strip_offsets.append(data_offset + top * row_bytes + strip_offset_delta)
            strip_counts.append(rows * row_bytes)

        tags = {
            256: (LONG, [width]),
            257: (LONG, [height]),
            258: (SHORT, [bits] * samples_per_pixel),
            259: (SHORT, [1]),
            262: (SHORT, [photometric]),
            273: (LONG, strip_offsets),
            277: (SHORT, [samples_per_pixel]),
            278: (LONG, [rows_per_strip]),
            279: (LONG, strip_counts),
            284: (SHORT, [1]),
            339: (SHORT, [1]),
        }
        for code, type_id, values in extra_tags:
            tags[code] = (type_id, values)

        entries = []
        for code in sorted(tags):
            type_id, values = tags[code]
            count, data = _encode(order, type_id, values)
            if len(data) <= inline:
                field = data + b"\x00" * (inline - len(data))
            else:
                _align(buf)
                field = struct.pack(order + offset_fmt, len(buf))
                buf += data
            if bigtiff:
                entries.append(struct.pack(order + "HHQ", code, type_id, count) + field)
            else:
                entries.append(struct.pack(order + "HHI", code, type_id, count) + field)

        _align(buf)
        ifd_offset = len(buf)
        struct.pack_into(order + offset_fmt, buf, next_pointer_pos, ifd_offset)
        buf += struct.pack(order + count_fmt, len(entries))
        for entry in entries:
            assert len(entry) == entry_size
            buf += entry
        next_pointer_pos = len(buf)
        buf += struct.pack(order + offset_fmt, 0)
    return bytes(buf)


def write_tiff(path, *args, **kwargs):
    with open(str(path), "wb") as stream:
        stream.write(build_tiff(*args, **kwargs))
    return str(path)


def _encode(order, type_id, values):
    if type_id == ASCII:
        data = values.encode("utf-8") + b"\x00"
        return len(data), data
    if type_id == RATIONAL:
        data = b"".join(struct.pack(order + "II", num, den) for num, den in values)
        return len(values), data
    return len(values), struct.pack(order + _FORMATS[type_id] * len(values), *values)


def _align(buf):
    if len(buf) % 2:
        buf += b"\x00"
