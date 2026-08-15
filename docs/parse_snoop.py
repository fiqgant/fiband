#!/usr/bin/env python3
"""
Parser for btsnoop_hci.log: extracts the band's protocol frames (ATT
writes and notifications) and shows them in order, with direction and command.

Usage: python parse_snoop.py [btsnoop_hci.log]
"""
import struct
import sys
from collections import Counter

PATH = sys.argv[1] if len(sys.argv) > 1 else "btsnoop_hci.log"

# known protocol command names (cmd = first byte of the frame)
KNOWN = {
    1: "set_time", 3: "battery", 8: "?", 13: "sleep_history",
    20: "BP_history (device doesn't respond: no BP history)",
    21: "hr_history", 22: "hr_log_settings", 42: "spo2_history?",
    55: "stress_history", 57: "hrv_history", 67: "steps",
    105: "realtime_start", 106: "realtime_stop",
}


def parse_btsnoop(path):
    with open(path, "rb") as f:
        data = f.read()
    assert data[:8] == b"btsnoop\x00", "not a btsnoop file"
    # header: 8 magic + 4 version + 4 datalink
    off = 16
    records = []
    while off + 24 <= len(data):
        olen, ilen, flags, drops, ts = struct.unpack_from(">IIIIq", data, off)
        off += 24
        pkt = data[off:off + ilen]
        off += ilen
        if len(pkt) < ilen:
            break
        direction = "RECV" if (flags & 0x01) else "SENT"  # 1 = controller->host
        records.append((ts, direction, pkt))
    return records


def extract_att(pkt):
    """From an H4 packet extracts (opcode, handle, value) if it's an ATT write/notify."""
    if not pkt:
        return None
    h4 = pkt[0]
    if h4 != 0x02:  # ACL data only
        return None
    if len(pkt) < 9:
        return None
    # ACL: handle(2) len(2)  | L2CAP: len(2) cid(2) | ATT...
    l2_len, cid = struct.unpack_from("<HH", pkt, 5)
    if cid != 0x0004:  # ATT
        return None
    att = pkt[9:]
    if not att:
        return None
    opcode = att[0]
    # write command/request, notification, indication
    if opcode in (0x52, 0x12, 0x1b, 0x1d) and len(att) >= 3:
        handle = struct.unpack_from("<H", att, 1)[0]
        value = att[3:]
        return opcode, handle, value
    return None


def main():
    records = parse_btsnoop(PATH)
    print(f"Total records in the log: {len(records)}\n")

    frames = []  # (ts, direction, opcode, handle, value)
    for ts, direction, pkt in records:
        att = extract_att(pkt)
        if att:
            opcode, handle, value = att
            frames.append((ts, direction, opcode, handle, value))

    if not frames:
        print("No ATT write/notify frame found.")
        return

    # which handles are involved (to understand the band's RX/TX)
    handles = Counter((d, h) for _, d, _, h, _ in frames)
    print("ATT handles used (direction, handle): count")
    for (d, h), n in handles.most_common():
        print(f"   {d} handle=0x{h:04x}: {n}")
    print()

    # show the 16-byte frames (band protocol), in order
    print("=== 16-byte frames (band protocol) ===")
    print("dir   cmd  name                 frame")
    cmd_seen = Counter()
    for ts, direction, opcode, handle, value in frames:
        if len(value) != 16:
            continue
        cmd = value[0]
        name = KNOWN.get(cmd, "??? UNKNOWN")
        cmd_seen[cmd] += 1
        arrow = "->band" if direction == "SENT" else "<-band"
        print(f"{arrow} {cmd:>3}  {name:<18}  {value.hex(' ')}")

    print("\n=== Commands seen (cmd: how many times) ===")
    for cmd, n in sorted(cmd_seen.items()):
        flag = "" if cmd in KNOWN and "?" not in KNOWN[cmd] else "   <-- TO INVESTIGATE"
        print(f"   cmd {cmd:>3} ({KNOWN.get(cmd, 'unknown')}): {n}{flag}")


if __name__ == "__main__":
    main()