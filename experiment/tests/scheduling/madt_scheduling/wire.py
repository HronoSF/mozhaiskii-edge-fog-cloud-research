"""Bounded length-prefixed JSON control frames; input payloads remain binary."""
import asyncio
import json
import struct

MAX_FRAME=131072

async def read(reader):
    size=struct.unpack('!I',await reader.readexactly(4))[0]
    if not 0 < size <= MAX_FRAME:
        raise ValueError('Invalid control-frame length')
    def invalid_constant(value):raise ValueError('Nonfinite JSON constant: '+value)
    value=json.loads(await reader.readexactly(size),parse_constant=invalid_constant)
    if not isinstance(value,dict):
        raise ValueError('Control frame must be an object')
    return value

async def write(writer,value):
    body=json.dumps(value,separators=(',',':'),allow_nan=False).encode()
    if not 0<len(body)<=MAX_FRAME:
        raise ValueError('Control frame too large')
    writer.write(struct.pack('!I',len(body))+body)
    await writer.drain()
    return len(body)+4

async def close(writer):
    writer.close()
    try:await writer.wait_closed()
    except (ConnectionError,OSError):pass
