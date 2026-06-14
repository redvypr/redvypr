import redvypr
import time
import redvypr.metadata
import datetime

redvypr.logger.setLevel('DEBUG')

r = redvypr.Redvypr(hostname='metadatatest',loglevel='DEBUG')


def test_metadata_constraints_and_modes():
    # Setup: Initialize your class instance here
    # r = Redvypr()

    print("\n" + "=" * 50)
    print("STARTING METADATA CONSTRAINTS AND MODES TEST")
    print("=" * 50)

    # --- 1. Adding old metadata (Deep in the past) ---
    print("\n[Step 1] Adding an expired comment (100h ago to 9h ago)...")
    metadata1 = {"comment": "Old comment"}
    t1 = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=100)
    t2 = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=9)
    r.add_metadata(address="@i:test", metadata=metadata1, valid_from=t1, valid_until=t2)

    m = r.get_metadata(address="@i:test", mode="merge")
    print(f" -> Current active metadata (expected {{}}): {m}")
    assert m == {}, f"Expected empty dict due to expiration, but got: {m}"

    # --- 2. Adding a newer, but still expired metadata ---
    print("\n[Step 2] Adding a newer but still expired comment (10h ago to 1h ago)...")
    metadata1 = {"comment": "This is a newer comment"}
    t1 = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=10)
    t2 = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
    r.add_metadata(address="@i:test", metadata=metadata1, valid_from=t1, valid_until=t2)

    m = r.get_metadata(address="@i:test", mode="merge")
    print(f" -> Current active metadata (expected {{}}): {m}")
    assert m == {}, f"Expected empty dict since this is also expired, but got: {m}"

    # --- 3. Adding metadata that is currently valid ---
    print("\n[Step 3] Adding a currently valid comment (-1h to +1h)...")
    metadata1 = {"comment": "Super new comment"}
    t1 = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
    t2 = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
    r.add_metadata(address="@i:test", metadata=metadata1, valid_from=t1, valid_until=t2)

    m = r.get_metadata(address="@i:test", mode="merge")
    print(f" -> Current active metadata (expected 'Super new comment'): {m}")
    assert m == {"comment": "Super new comment"}

    # --- 4. Adding currently valid metadata with a logical constraint (John) ---
    print(
        "\n[Step 4] Adding a currently valid comment with an operator='John' constraint...")
    metadata1 = {"comment": "Johns comment"}
    t1 = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
    t2 = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
    constraint = {'operator': 'John'}
    r.add_metadata(address="@i:test", metadata=metadata1, valid_from=t1, valid_until=t2,
                   constraints=constraint)

    print("\n >> Testing logical context filtering:")

    # Query for Frank: John's comment is filtered out, "Super new comment" remains
    m_frank = r.get_metadata(address="@i:test", mode="merge",
                             context={'operator': 'Frank'})
    print(
        f"    - Metadata for operator='Frank' (expected 'Super new comment'): {m_frank}")
    assert m_frank == {"comment": "Super new comment"}

    # Query for John: John's comment matches perfectly and overwrites "Super new comment"
    m_john = r.get_metadata(address="@i:test", mode="merge",
                            context={'operator': 'John'})
    print(f"    - Metadata for operator='John' (expected 'Johns comment'): {m_john}")
    assert m_john == {"comment": "Johns comment"}

    # Query without context: No logical filter is applied, the last chronologically inserted item wins the merge
    m_no_context = r.get_metadata(address="@i:test", mode="merge")
    print(
        f"    - Metadata without context filter (expected 'Johns comment' to win merge): {m_no_context}")
    assert m_no_context == {"comment": "Johns comment"}

    # --- 5. Testing the new 'all' mode (Full history ignoring time filters) ---
    print("\n[Step 5] Fetching full historical raw timeline via mode='all'...")
    m_all = r.get_metadata(mode="all")

    print(f" -> Received a list containing {len(m_all)} total historical entries:")
    for idx, entry in enumerate(m_all, 1):
        print(
            f"    Entry {idx}: Key='{entry.get('key')}', Value='{entry.get('value')}', Constraints={entry.get('constraints')}")

    # Ensure all 4 historical entries are present
    assert isinstance(m_all, list)
    assert len(m_all) == 4

    # Deep check to verify every individual comment made it into the raw history dump
    comments_in_history = [entry['value'] for entry in m_all if
                           entry.get('key') == 'comment']
    assert "Old comment" in comments_in_history
    assert "This is a newer comment" in comments_in_history
    assert "Super new comment" in comments_in_history
    assert "Johns comment" in comments_in_history

    print("\n" + "=" * 50)
    print("ALL ASSERTIONS PASSED SUCCESSFULLY!")
    print("=" * 50)

if False:
    # Adding old comment
    metadata1 = {"comment":"Old comment"}
    t1 = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=100)
    t2 = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=9)
    r.add_metadata(address="@i:test",metadata=metadata1,valid_from=t1,valid_until=t2)


    m = r.get_metadata(address="@i:test",mode="merge")
    print(f"metadata 1 :{m}") # Should be an empty dict

    if True:
        # Adding newer comment
        metadata1 = {"comment":"This is a newer comment"}
        t1 = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=10)
        t2 = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
        r.add_metadata(address="@i:test",metadata=metadata1,valid_from=t1,valid_until=t2)
        m = r.get_metadata(address="@i:test",mode="merge")
        print(f"metadata:{m}") # Should be still an empty dict

    if True:
        print("Testing time constraint")
        # Adding comment that is valid now
        metadata1 = {"comment":"Super new comment"}
        t1 = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
        t2 = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
        r.add_metadata(address="@i:test",metadata=metadata1,valid_from=t1,valid_until=t2)
        m = r.get_metadata(address="@i:test",mode="merge")
        print(f"metadata:{m}") # Should be dict with a comment

    if True:
        print("Testing generic constraint")
        # Adding comment that is valid now but with a constraint
        metadata1 = {"comment":"Johns comment"}
        t1 = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
        t2 = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
        constraint = {'operator':'John'}
        r.add_metadata(address="@i:test",metadata=metadata1,valid_from=t1,valid_until=t2, constraints=constraint)
        print("\nChecking metadata for operator Frank")
        m = r.get_metadata(address="@i:test",mode="merge",context={'operator':'Frank'})
        print(f"metadata:{m}") # Should be dict with a comment
        print("\nChecking metadata for operator John")
        m = r.get_metadata(address="@i:test", mode="merge", context={'operator': 'John'})
        print(f"metadata:{m}")  # Should be dict with a comment
        print("\nChecking metadata without constraint")
        m = r.get_metadata(address="@i:test", mode="merge")
        print(f"metadata:{m}")  # Should be dict with a comment

    m_all = r.get_metadata(mode="all")
    print(f"get_metadata:{m_all}") # Should return a list with the two entries
if False:
    devicemodulename = r.get_devicemodulename_from_str('test_device')
    dev = r.add_device(devicemodulename=devicemodulename)

    print('Device',dev)
    dev.thread_start()
    time.sleep(2)
    dev.thread_stop()
    time.sleep(0.5)

    print('----------------------')
    print('Device metadata')
    print(dev.statistics['metadata'])
    print('Device metadata done')
    print('----------------------')

    raddrs = []
    raddrs.append(redvypr.RedvyprAddress('@'))
    raddrs.append(redvypr.RedvyprAddress('data_list_list'))
    raddrs.append(redvypr.RedvyprAddress("data_list_list[0]"))
    raddrs.append(redvypr.RedvyprAddress("data_list_list[1]"))
    raddrs.append(redvypr.RedvyprAddress('data_list_poly[0]'))
    raddrs.append(redvypr.RedvyprAddress('data_dict_list["temp"]'))
    raddrs.append(redvypr.RedvyprAddress("data_dict_list['temp'][0]"))
    raddrs.append(redvypr.RedvyprAddress('data_dict_list["pressure"][0]'))
    raddrs.append(redvypr.RedvyprAddress('sine'))
    raddrs.append(redvypr.RedvyprAddress('sine_rand@i:test_device'))

    #print('Raddr1',raddr1.datakeyeval)
    for raddr in raddrs:
        meta = redvypr.get_metadata(raddr)
        print('-----------------------')
        print('Metadata for address {}: {}'.format(raddr,meta))
        print('-----------------------\n\n')

