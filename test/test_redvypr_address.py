import pytest
from redvypr.redvypr_address import RedvyprAddress, FilterNoMatch

# -------------------------
# Beispielpakete
# -------------------------
pkt1 = {
    "_redvypr": {"packetid": "test", "publisher": "mainhub", "address": "node01", "device": "cam", "location": "lab1"},
    "data": [1, 2, 3, 4, 5],
    "payload": {"x": 42},
    "data2": 10
}

pkt2 = {
    "_redvypr": {"packetid": 42, "publisher": "ctd", "address": "node02", "device": "gps", "location": "lab2"},
    "data": [10, 20, 30],
    "payload": {"x": 1.23}
}

pkt3 = {"_redvypr": {"packetid": 1}}


pkt4 = {'x': 10, 'y': 20, 'z': [1, 2, 3, 4], 'u': {'a': [5, 6, 7], 'b': 'Hello'}, '_redvypr': {'tag': {'176473386979093-142': 1}, 'device': 'somedevice', 'packetid': 'somedevice', 'host': {'hostname': 'someredvypr', 'tstart': 1761197984.0251052, 'addr': '192.168.178.137', 'uuid': '176473386979093-142'}, 'localhost': {'hostname': 'someredvypr', 'tstart': 1761197984.0251052, 'addr': '192.168.178.137', 'uuid': '176473386979093-142'}, 'publisher': 'somedevice', 't': 1761197984.0252116, 'devicemodulename': 'somedevicemodulename', 'numpacket': 0}, 't': 1761197984.0252116}



# -------------------------
# LHS Evaluation / Basic Filters
# -------------------------
@pytest.mark.parametrize("addr_str,packet,expected", [
    ("data[::-1] @ i:test", pkt1, [5,4,3,2,1]),
    ("payload['x'] @ i:42", pkt2, 1.23),
    ("data @ i:~/^te/", pkt1, [1,2,3,4,5]),
    ("data @ d?:", pkt1, [1,2,3,4,5]),
    ("data @ i:[test,foo,bar]", pkt1, [1,2,3,4,5]),
    ("data @ (i:test and p:mainhub2) or data2==10", pkt1, [1,2,3,4,5]),
    ("data @ r:location:[lab1,lab2]", pkt1, [1,2,3,4,5]),
    ("_redvypr['packetid']@ i:[1,2,3]", pkt3, 1),
    ("@i:test", pkt1, True),
])
def test_lhs_and_rhs(addr_str, packet, expected):
    addr = RedvyprAddress(addr_str)
    # Filter matches
    assert addr.matches(packet)
    # Evaluate LHS
    val = addr(packet)
    assert val == expected

# -------------------------
# Empty initialization
# -------------------------
def test_empty_address_returns_whole_packet():
    addr = RedvyprAddress()
    assert addr.matches(pkt1)
    assert addr.matches(pkt2)
    assert addr(pkt1) == pkt1
    assert addr(pkt2) == pkt2

# -------------------------
# Copy Constructor and Roundtrip
# -------------------------
def test_copy_constructor_and_roundtrip():
    original = RedvyprAddress("@i:test and d:cam")
    # Copy constructor
    copy_addr = RedvyprAddress(original)
    assert copy_addr.left_expr == original.left_expr
    assert copy_addr.filter_expr == original.filter_expr
    assert copy_addr.filter_keys == original.filter_keys
    # Roundtrip via str
    roundtrip = RedvyprAddress(str(original))
    assert str(roundtrip) == str(original)

# -------------------------
# Dynamic filter manipulation
# -------------------------
def test_dynamic_filter_add_update_delete():
    addr = RedvyprAddress("@i:test")
    # Add filter
    addr.add_filter("device", "eq", "cam")
    assert addr.matches(pkt1)
    # Add failing filter
    addr.add_filter("publisher", "eq", "ctd")
    with pytest.raises(FilterNoMatch):
        addr(pkt1)
    # Update filter to match
    addr.update_filter("publisher", "mainhub")
    assert addr.matches(pkt1)
    # Delete filter
    addr.delete_filter("device")
    assert addr.matches(pkt1)
    assert "device" not in addr.filter_keys

# -------------------------
# Human-readable RHS string
# -------------------------
def test_human_readable_rhs():
    addr = RedvyprAddress("@i:test and d:cam")
    rhs_str = str(addr)
    assert "i:test" in rhs_str
    assert "d:cam" in rhs_str
