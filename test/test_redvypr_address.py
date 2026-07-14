import pytest
from datetime import datetime, timezone
from redvypr.redvypr_address import RedvyprAddress, FilterNoMatch

# ==============================================================================
# Test-Daten (Pakete)
# ==============================================================================

pkt1 = {
    "_redvypr": {
        "packetid": "test",
        "publisher": "mainhub",
        "device": "cam",
        "host": {"hostname": "node01-host", "addr": "10.0.0.1", "uuid": "uuid-pkt1-host"},
        "localhost": {"hostname": "node01-local", "addr": "10.0.0.2", "uuid": "uuid-pkt1-local"},
        "location": "lab1"
    },
    "x": 1,
    "y": 2,
    "data2": 10,
    "data": [1, 2, 3, 4, 5],
    "u": {"a": [42], "b": "Payload pkt1", "test@i:test": 3},
    "t": 0.0,
    "td": datetime(2000, 1, 1),
    "td_utc": datetime(2000, 1, 1, tzinfo=timezone.utc),
    "test@i:test": 3
}

pkt_empty = {
    "_redvypr": {
        "packetid": "test",
        "publisher": "mainhub",
        "device": "cam",
        "host": {"hostname": "node01-host", "addr": "10.0.0.1", "uuid": "uuid-pkt1-host"},
        "localhost": {"hostname": "node01-local", "addr": "10.0.0.2", "uuid": "uuid-pkt1-local"},
        "location": "lab1"
    },
}

pkt2 = {
    "_redvypr": {
        "packetid": 42,
        "publisher": "ctd",
        "device": "gps",
        "host": {"hostname": "node02-host", "addr": "10.0.1.1", "uuid": "uuid-pkt2-host"},
        "localhost": {"hostname": "node02-local", "addr": "10.0.1.2", "uuid": "uuid-pkt2-local"},
        "location": "lab2"
    },
    "x": 10,
    "y": 20,
    "z": [10, 20, 30],
    "u": {"a": [1, 2, 3], "b": "Payload pkt2"},
    "payload": {"x": 1.23},
    "t": 0.0
}

pkt3 = {
    "_redvypr": {
        "packetid": 1,
        "host": {"hostname": "pkt3-host", "addr": "10.0.2.1", "uuid": "uuid-pkt3-host"},
        "localhost": {"hostname": "pkt3-local", "addr": "10.0.2.2", "uuid": "uuid-pkt3-local"}
    },
    "x": 100,
    "y": 200,
    "z": [1],
    "u": {"a": [5], "b": "Payload pkt3"},
    "t": 0.0
}

pkt4 = {
    'x': 10, 'y': 20, 'z': [1, 2, 3, 4],
    'u': {'a': [5, 6, 7], 'b': 'Hello'},
    'v': {'a': [1, 2, [3, 4, 5, [6, 7, 8, [9, 10]]]], 'b': {'c': [5, 6, 7], 'd': 'Hello'}},
    '_redvypr': {
        'tag': {'176473386979093-142': 1},
        'device': 'somedevice',
        'packetid': 'somedevice',
        'host': {'hostname': 'someredvypr', 'tstart': 1761197984.0251052, 'addr': '192.168.178.137',
                 'uuid': '176473386979093-142'},
        'localhost': {'hostname': 'someredvypr', 'tstart': 1761197984.0251052, 'addr': '192.168.178.137',
                      'uuid': '176473386979093-142'},
        'publisher': 'somedevice',
        't': 1761197984.0252116,
        'devicemodulename': 'somedevicemodulename',
        'numpacket': 0
    },
    't': 1761197984.0252116
}

pkt5 = {
    "_redvypr": {
        "packetid": 'test@i:test',
        "publisher": "mainhub",
        "device": "cam",
        "host": {"hostname": "node01-host", "addr": "10.0.0.1", "uuid": "uuid-pkt1-host"},
        "localhost": {"hostname": "node01-local", "addr": "10.0.0.2", "uuid": "uuid-pkt1-local"},
        "location": "lab1"
    },
    "x": 1,
    "y": 2,
    "data2": 10,
    "data": [1, 2, 3, 4, 5],
    "u": {"a": [42], "b": "Payload pkt1", "test@i:test": 3},
    "t": 0.0,
    "td": datetime(2000, 1, 1),
    "test@i:test": 3
}


# ==============================================================================
# 1. LHS / RHS / Filter-Auswertungs-Tests
# ==============================================================================

@pytest.mark.parametrize("addr_str, pkt, expected", [
    ("u['test@i:test'] @ i:test", pkt1, 3),
    ("data[0]", pkt1, 1),
    ("'test@i:test' @ i:test", pkt1, 3),
    ("'test@i:test' @ i:'test@i:test'", pkt5, 3),
    ("! @ i:test", pkt1, KeyError),  # Wir erwarten hier die Exception-Klasse direkt!
    ("! @ i:test", pkt_empty, pkt_empty),
    ("data[::-1] @ i:test", pkt1, [5, 4, 3, 2, 1]),
    ("data3 @ i:test", pkt1, KeyError),
    ("data[0] @ td==dt(2000-01-01)", pkt1, 1),
    ("data[0]@td_utc>=dt('1999-12-05T10:48:04.762994Z')", pkt1, 1),
    ("data[0]@td_utc>=dt('1999-12-05T10:48:04.762994+00:00')", pkt1, 1),
    ("payload['y'] @ i:42", pkt2, KeyError),
    ("payload['x'] @ i:42", pkt2, 1.23),
    ("data @ d?:", pkt1, [1, 2, 3, 4, 5]),
    ("data @ i:[test,foo,bar]", pkt1, [1, 2, 3, 4, 5]),
    ("data @ (i:test and p:mainhub2) or data2==10", pkt1, [1, 2, 3, 4, 5]),
    ("_redvypr['packetid'] @ i:[1,2,3]", pkt3, 1),
    ("@i:test", pkt1, pkt1),
    ("data[0]", pkt1, 1),
    ('v["a"][2][3][0]', pkt4, 6),
    ("@", pkt1, pkt1),
    # Neue Tests für pkt4
    ("@u:176473386979093-142", pkt4, True),
    ("@a:192.168.178.137", pkt4, True),
    ("@ul:176473386979093-142", pkt4, True),
    ("@al:192.168.178.137", pkt4, True),
    ("z[::-1] @ ul:176473386979093-142", pkt4, [4, 3, 2, 1]),
    ("x @ a:192.168.178.137", pkt4, 10),
    ("x @ (u:176473386979093-142 and p:somedevice)", pkt4, 10),
    ("x @ h:someredvypr", pkt4, 10),
    ("x @ hl:someredvypr", pkt4, 10),
    ("@u?:", pkt4, True),
    ("@unknown?:", pkt4, FilterNoMatch),
])
def test_address_evaluation(addr_str, pkt, expected):
    addr = RedvyprAddress(addr_str)

    # Erwartete Exceptions abfangen
    if expected is KeyError:
        with pytest.raises(KeyError):
            addr(pkt)
    elif expected is FilterNoMatch:
        with pytest.raises(FilterNoMatch):
            addr(pkt)
    else:
        # Auswertungs-Test
        val = addr(pkt)
        if addr.left_expr is None:
            assert val == pkt
        else:
            assert val == expected

        # Übereinstimmungs-Test für Boolean-Rückgaben
        if isinstance(expected, bool):
            assert addr.matches_packetfilter(pkt) == expected


# ==============================================================================
# 2. Datakey Manipulations-Tests
# ==============================================================================

def test_datakey_manipulation():
    apkt1 = RedvyprAddress(pkt1)
    assert apkt1(pkt1) == pkt1

    # Datakey hinzufügen
    apkt1.add_datakey("data")
    assert apkt1(pkt1) == [1, 2, 3, 4, 5]

    # Neuen Datakey hinzufügen
    apkt1.add_datakey("x")
    assert apkt1(pkt1) == 1

    # Löschen
    apkt1.delete_datakey()
    assert apkt1(pkt1) == pkt1

    # String-Generierung prüfen
    apkt1.add_datakey("x")
    assert apkt1.to_address_string("d,i") == "@i:'test' and d:'cam'"
    assert apkt1.to_address_string("k,d,i") == "x @ i:'test' and d:'cam'"


# ==============================================================================
# 3. Attribut- und Metadaten-Tests
# ==============================================================================

def test_attributes_and_meta():
    apkt1 = RedvyprAddress(pkt1)

    # Redvypr Dict & Python Representation
    assert "packetid" in apkt1.to_redvypr_dict()["_redvypr"]
    assert "__packetid__" in apkt1.to_address_string_pure_python()

    # Attributeauslesung
    assert apkt1.device == pkt1['_redvypr']['device']
    assert apkt1.uuid == pkt1['_redvypr']['host']['uuid']


# ==============================================================================
# 4. Adressvergleichs-Tests
# ==============================================================================

def test_address_matching():
    devaddr = RedvyprAddress("@d:cam and i:test")
    testaddr = RedvyprAddress("@d:test_device and p:test_device and i:blabla")

    assert not testaddr.matches_packetfilter(devaddr)
    assert not devaddr.matches_packetfilter(testaddr)

    apkt1 = RedvyprAddress(pkt1)
    assert apkt1.matches_packetfilter(devaddr)
    assert devaddr.matches_packetfilter(apkt1)

    # Strenger Filter
    apkt1_strict = RedvyprAddress(devaddr)
    apkt1_strict.add_filter("h", op="exists")
    assert apkt1_strict.matches_packetfilter(devaddr)


# ==============================================================================
# 5. Regex-Tests (mit r-String behoben!)
# ==============================================================================

def test_regex_matching():
    # raw string befreit uns vom SyntaxWarning!
    addr_regex = RedvyprAddress(r"temp @ i:~/^ch(\d+)SN(\d+)$/")
    addr_regex_t1 = RedvyprAddress("temp @ i:ch1SN123")
    addr_regex_t2 = RedvyprAddress("temp @ i:channel1SN123")

    assert addr_regex(addr_regex_t1, strict=False) is True
    assert addr_regex(addr_regex_t2, strict=False) is None


# ==============================================================================
# 6. Tests für die Paket- und Payload-Generierung
# ==============================================================================

@pytest.mark.parametrize("addr_str, expected_entries, expected_dict", [
    ("u['test@i:test'] @ i:test", ["u", "test@i:test"], {"u": {"test@i:test": True}, "_redvypr": {"packetid": "test"}}),
    ("data[0]", ["data", 0], {"data": {0: True}, "_redvypr": {}}),
    ("'test@i:test' @ i:test", ["test@i:test"], {"_redvypr": {"packetid": "test"}}),
    ("data[::-1] @ i:test", ["data"], {"data": True, "_redvypr": {"packetid": "test"}}),
    ("data3 @ i:test", ["data3"], {"data3": True, "_redvypr": {"packetid": "test"}}),
    ("payload['y'] @ i:42", ["payload", "y"], {"payload": {"y": True}, "_redvypr": {"packetid": 42}}),
    ("data @ d?:", ["data"], {"data": True, "_redvypr": {"device": True}}),
    ("z[::-1] @ ul:176473386979093-142", ["z"],
     {"z": True, "_redvypr": {"localhost": {"uuid": "176473386979093-142"}}}),
    ("x @ a:192.168.178.137", ["x"], {"x": True, "_redvypr": {"host": {"addr": "192.168.178.137"}}}),
])
def test_payload_and_entry_creation(addr_str, expected_entries, expected_dict):
    addr = RedvyprAddress(addr_str)

    # 1. Teste die extrahierten Datakey-Einträge
    assert addr.get_datakeyentries() == expected_entries

    # 2. Teste die Erstellung des minimalen Redvypr-Dictionaries
    if isinstance(addr.left_expr, str):
        assert addr.to_redvypr_dict() == expected_dict


def test_nested_datakey_depths():
    addr1 = RedvyprAddress("data@i:testid")
    addr2 = RedvyprAddress("data['temp'][0]@i:testid")

    # Teste to_redvypr_dict() für verschiedene Tiefen
    assert addr1.to_redvypr_dict() == {"data": True, "_redvypr": {"packetid": "testid"}}

    # Teste die verschachtelte Auswertung (LHS-Aufruf mit einer anderen Adresse)
    assert addr1(addr2) == {"temp": {0: True}}