from redvypr_address import RedvyprAddress, FilterNoMatch

# -------------------------
# Testpakete
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
    "u": {"a": [42], "b": "Payload pkt1"},
    "t": 0.0
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
    'v': {'a': [1, 2, [3,4,5,[6,7,8,[9,10]]]], 'b': {'c': [5, 6, 7], 'd': 'Hello'},},
    '_redvypr': {
        'tag': {'176473386979093-142': 1},
        'device': 'somedevice',
        'packetid': 'somedevice',
        'host': {'hostname': 'someredvypr','tstart': 1761197984.0251052,'addr': '192.168.178.137','uuid': '176473386979093-142'},
        'localhost': {'hostname': 'someredvypr','tstart': 1761197984.0251052,'addr': '192.168.178.137','uuid': '176473386979093-142'},
        'publisher': 'somedevice',
        't': 1761197984.0252116,
        'devicemodulename': 'somedevicemodulename',
        'numpacket': 0
    },
    't': 1761197984.0252116
}

# -------------------------
# Alte Tests (LHS/RHS)
addresses_test = [
    ("data[::-1] @ i:test", pkt1, [5,4,3,2,1]),
    ("data3 @ i:test", pkt1, "KeyError"),
    ("payload['y'] @ i:42", pkt2, "KeyError"),
    ("payload['x'] @ i:42", pkt2, 1.23),
    ("data @ i:~/^te/", pkt1, [1,2,3,4,5]),
    ("data @ d?:", pkt1, [1,2,3,4,5]),
    ("data @ i:[test,foo,bar]", pkt1, [1,2,3,4,5]),
    ("data @ (i:test and p:mainhub2) or data2==10", pkt1, [1,2,3,4,5]),
    ("data @ r:location:[lab1,lab2]", pkt1, [1,2,3,4,5]),
    ("_redvypr['packetid'] @ i:[1,2,3]", pkt3, 1),
    ("@i:test", pkt1, pkt1),
    ("data[0]", pkt1, 1),
    ('v["a"][2][3][0]', pkt4, 6),
    ("@", pkt1, pkt1),
]

# Neue Tests für pkt4
addresses_test += [
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
    ("@unknown?:", pkt4, False),
]



print("=== LHS / RHS / Existenz Tests ===")
for addr_str, pkt, expected in addresses_test:
    addr = RedvyprAddress(addr_str)
    print("Address is:", str(addr))
    print(f"Testing address: {addr_str}")
    #print("Expecting", expected)

    # matches prüfen (nur, wenn expected != "KeyError")
    if expected != "KeyError":
        match_result = addr.matches_filter(pkt)
        # Für bool-Werte expected True/False prüfen, sonst match_result ignorieren
        if isinstance(expected, bool):
            assert match_result == expected, f"Expected matches={expected} for {addr_str}"

    # __call__ / LHS
    if expected == "KeyError":
        # Test, dass ein KeyError geworfen wird
        try:
            val = addr(pkt)
            assert False, f"Expected KeyError for {addr_str} but got value {val}"
        except KeyError as e:
            print(f"Passed KeyError test: {addr_str} -> {e}")
        continue  # nächsten Test
    else:
        try:
            val = addr(pkt)
            # Wenn kein LHS vorhanden, sollte das gesamte Packet zurückgegeben werden
            if addr.left_expr is None:
                assert val == pkt, f"Expected full packet, got {val}"
            else:
                assert val == expected, f"Expected {expected}, got {val} for {addr_str}"
            print(f"Passed: {addr_str} -> {val}")
        except FilterNoMatch:
            assert expected is False, f"Expected False but got FilterNoMatch"
            print(f"Passed (no-left, no-match): {addr_str} -> FilterNoMatch")

# Test paket creation
apkt1 = RedvyprAddress(pkt1)
print("Adress pkt1",apkt1)
print("Data from {}:\n{}\n".format(apkt1,apkt1(pkt1)))

print("Adding datakey:{}".format("data"))
apkt1.add_datakey("data")
print("Data from {}:\n{}\n".format(apkt1,apkt1(pkt1)))
print("Adding datakey:{}".format("data"))
apkt1.add_datakey("x")
print("Data from {}:\n{}\n".format(apkt1,apkt1(pkt1)))

apkt1.delete_datakey()
print("Data from {}:\n{}\n".format(apkt1,apkt1(pkt1)))
apkt1.add_datakey("x")
print("Adress pkt1 extract from\n{}\n->{}\n".format(apkt1,apkt1.to_address_string("d,i")))
print("Adress pkt1 extract from\n{}\n->{}\n".format(apkt1,apkt1.to_address_string("k,d,i")))

if True:
    pkt1_meta = apkt1.to_redvypr_dict()
    print('Pkt1 meta',pkt1_meta)

    print("Pure python string:{}".format(apkt1.to_address_string_pure_python()))

    print("Testing attributes")
    device = pkt1['_redvypr']['device']
    assert apkt1.device == device, f"Expected matches={device} for {apkt1.device}"
    print(f"Passed attribute test, expected matches={device} for {apkt1.device}")

    uuid = pkt1['_redvypr']['host']['uuid']
    assert apkt1.uuid == uuid, f"Expected matches={uuid} for {addr_str}"
    print(f"Passed attribute test, expected matches={uuid} for {apkt1.uuid}")


    # Test two addresses

    devaddr = RedvyprAddress("@d:cam and i:test")
    apkt1_strict = RedvyprAddress(devaddr)
    apkt1_strict.add_filter("h", op="exists")
    testaddr = RedvyprAddress("@d:test_device and p:test_device and i:blabla")
    print("dictionary devaddr",devaddr.to_redvypr_dict())
    print("dictionary testaddr",testaddr.to_redvypr_dict())
    print("1", testaddr.matches_filter(devaddr), devaddr.matches_filter(testaddr))

    print("apkt1 matches devaddr", apkt1.matches_filter(devaddr))
    print("devaddr matches apkt1", devaddr.matches_filter(apkt1))
    print("apkt1_strict:{}\n matches devaddr:{}".format(apkt1_strict, apkt1_strict.matches_filter(devaddr)))

# Test packet payload creation
for addr_str, pkt, expected in addresses_test:
    addr = RedvyprAddress(addr_str)
    print("Creating packet for address:{}".format(addr))
    if isinstance(addr.left_expr,str):
        #pkt_make = addr.create_minimal_datakey_packet()
        pkt_make = addr.to_redvypr_dict()
        print("Packet",pkt_make)
    else:
        print("Not a string")

    datakey_entries = addr.get_datakeyentries()
    print("Entries", datakey_entries)


# Test __call__ with different depths of datakeys
addrstring_test1 = RedvyprAddress("data@i:testid")
addrstring_test2 = RedvyprAddress("data['temp'][0]@i:testid")
addrstring_test3 = RedvyprAddress("data['temp']@i:testid")

print("Dictionary for {}:{}".format(addrstring_test1,addrstring_test1.to_redvypr_dict()))
print("{}({}):{}".format(addrstring_test1,addrstring_test2,addrstring_test1(addrstring_test2)))
print("{}({}):{}".format(addrstring_test2,addrstring_test1,addrstring_test2(addrstring_test1)))

# Test regex expressions
addr_regex = RedvyprAddress("temp @ i:~/^ch(\d+)SN(\d+)$/")
addr_regex_t1 = RedvyprAddress("temp @ i:ch1SN123")
addr_regex_t2 = RedvyprAddress("temp @ i:channel1SN123")
print("Testing regex")
print("Testing a1:{} with\n a2:{} = {}".format(addr_regex,addr_regex_t1,addr_regex(addr_regex_t1,strict=False)))
print("Testing a1:{} with\n a2:{} = {}".format(addr_regex,addr_regex_t2,addr_regex(addr_regex_t2,strict=False)))

