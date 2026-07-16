import pytest
import time
import redvypr
from redvypr import RedvyprDatadict, RedvyprAddress
# Importiere die spezifische Exception für den Fehlertest
from redvypr.redvypr_address import FilterNoMatch


def test_redvypr_datadict_lifecycle_and_filterkeys(capsys):
    """
    Test the full lifecycle of a RedvyprDatadict, including metadata updates,
    valid data queries, and ensuring incorrect queries raise FilterNoMatch.
    """
    with capsys.disabled():
        print("\n" + "=" * 50)
        print("STARTING EXPANDED REDVYPR DATADICT LIFECYCLE TEST")
        print("=" * 50)

    # -------------------------------------------------------------------------
    # 1. Setup Mock Hostinfo and Address Parameters
    # -------------------------------------------------------------------------
    hostname = 'someredvypr'
    devicename = 'somedevice'
    packetid = 'someid'
    sensor = 'tempsensor'
    sensorid = '01'
    data_payload = {'T': 10.03}

    print(f"Creating hostinfo for: {hostname}")
    hostinfo = redvypr.create_hostinfo(hostname=hostname)

    # -------------------------------------------------------------------------
    # 2. Test RedvyprAddress Compilation
    # -------------------------------------------------------------------------
    sensoraddress = RedvyprAddress(
        sensorid=sensorid,
        packetid=packetid,
        device=devicename,
        sensor=sensor,
        hostinfo=hostinfo
    )
    print(f"Generated Sensoraddress: {sensoraddress}")
    assert sensor in str(sensoraddress)

    # -------------------------------------------------------------------------
    # 3. Test RedvyprDatadict Initialization
    # -------------------------------------------------------------------------
    rdata = RedvyprDatadict(data_payload, raddress=sensoraddress)
    print(f"Initial RedvyprDatadict: {rdata}")
    print(f"Initial Datadict Address Attribute: {rdata.address}")

    # -------------------------------------------------------------------------
    # 4. Test In-Place Metadata Update via set_filterkeys()
    # -------------------------------------------------------------------------
    new_deviceid = "FE23AB42"
    new_sensor = "tempsensor_rev2"

    print(f"\nUpdating metadata filterkeys -> deviceid: {new_deviceid}, sensor: {new_sensor}")
    rdata.set_filterkeys(deviceid=new_deviceid, sensor=new_sensor)

    print(f"Updated Datadict: {rdata}")
    print(f"Updated Datadict Address Attribute: {rdata.address}")

    # -------------------------------------------------------------------------
    # 5. Test Datakey Expansion and Formatting
    # -------------------------------------------------------------------------
    print("\nRetrieving expanded datakeys...")
    datakeys, datakeys_dict = rdata.datakeys(expand=True, return_type='both')
    rdata.expand_data()

    print(f"Expanded Keys List: {datakeys}")
    print(f"Expanded Keys Dict: {datakeys_dict}")

    # -------------------------------------------------------------------------
    # 6. Test Successful Data Query (Correct Filter)
    # -------------------------------------------------------------------------
    sensordataaddress = RedvyprAddress("T@s:tempsensor_rev2")
    print(f"Querying with valid address: {sensordataaddress}")

    retrieved_value = rdata[sensordataaddress]
    print(f"rdata[sensordataaddress] = {retrieved_value}")

    # Assert that the data was correctly retrieved using the new filter
    assert retrieved_value == 10.03, f"Expected 10.03, but got {retrieved_value}"

    # -------------------------------------------------------------------------
    # 7. Test Expected Query Failure (Wrong/Old Filter)
    # -------------------------------------------------------------------------
    sensordataaddress_wrong = RedvyprAddress("T@s:tempsensor")
    print(f"Querying with invalid (old) address: {sensordataaddress_wrong}")

    # pytest.raises fängt den erwarteten Absturz sauber ab
    with pytest.raises(FilterNoMatch) as exc_info:
        _ = rdata[sensordataaddress_wrong]

    # Optional: Überprüfe, ob die Fehlermeldung den richtigen Text enthält
    assert "Packet did not match filter" in str(exc_info.value)
    print("Successfully caught expected FilterNoMatch error!")

    print("\n" + "=" * 50)
    print("ALL TESTS (INCLUDING EXPECTED FAILURES) PASSED!")
    print("=" * 50)

