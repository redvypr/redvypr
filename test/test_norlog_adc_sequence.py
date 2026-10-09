"""
Configuration text of the norlog ADC measurement sequence, redvypr.devices.norlog.adc_sequence.
The canonical texts below are what the firmware (0.4.15) prints for the same configuration.
"""
import pytest

from redvypr.devices.norlog import adc_sequence as aseq


def test_device_text_roundtrip():
    # Answer of the device in the hardware test (norlog adc cfg)
    text = "on=0,sps=20,filter=sinc3,interval=10000;temp,TEMP,-;avdd,AVDD,-;dvdd,DVDD,-;ofs,OFS,-"
    seq = aseq.parse(text)
    assert not seq.on and seq.sps == "20" and seq.filter == "sinc3" and seq.interval_ms == 10000
    assert [s.p for s in seq.steps] == ["TEMP", "AVDD", "DVDD", "OFS"]
    assert seq.to_text() == text
    assert seq.duration_ms() == 768     # firmware: "Dauer ca. 768 ms"


def test_canonical_text_and_units():
    seq = aseq.parse("on=1,interval=5000;u0,AIN0,aincom,off;temp,TEMP;pt,4,5,1,ref1,250,ain4,-,10;b,2,3,16")
    assert seq.to_text() == ("on=1,sps=20,filter=sinc3,interval=5000;u0,0,COM,off;temp,TEMP,-;"
                             "pt,4,5,1,REF1,250,4,-,10;b,2,3,16")
    assert [s.unit() for s in seq.steps] == ["V", "degC", "1", "V"]
    assert aseq.parse(seq.to_text()) == seq


def test_idac_without_current_drops_pins():
    seq = aseq.parse("on=0;x,0,1,1,INT,0,3,4")
    assert seq.steps[0].i1 == "-" and seq.to_text().endswith(";x,0,1")


def test_base_keeps_missing_globals():
    base = aseq.AdcSequence(on=True, sps="90", filter="ll", interval_ms=2000)
    seq = aseq.parse("interval=3000;a,0,COM", base=base)
    assert seq.on and seq.sps == "90" and seq.filter == "ll" and seq.interval_ms == 3000


@pytest.mark.parametrize("text, msg", [
    ("", "empty"),
    ("on=2", "on:"),
    ("sps=30", "sps:"),
    ("filter=x", "filter"),
    ("interval=50", "interval"),
    ("on=0;a,0,0", "same"),
    ("on=0;a,12,COM", "p ="),
    ("on=0;a,0", "n ="),
    ("on=0;a,0,COM,3", "gain"),
    ("on=0;a,0,COM,1,REF2", "ref"),
    ("on=0;a,0,COM,1,INT,20,1", "idac_ua"),
    ("on=0;a,0,COM,1,INT,250", "without output"),
    ("on=0;a,0,COM,1,INT,0,-,-,3000", "delay"),
    ("on=0;a-b,0,COM", "name only"),
    ("on=0;abcdefghijkl,0,COM", "name 1-11"),
    ("on=0;a,0,COM;a,1,COM", "twice"),
    ("on=0;" + ";".join(f"s{i},0,COM" for i in range(17)), "at most 16"),
])
def test_errors(text, msg):
    with pytest.raises(aseq.SequenceError, match=msg):
        aseq.parse(text)


def test_too_long():
    steps = ";".join(f"chan{i:07d},{i % 12},COM,128,REF1,2000,{i % 12},COM,2000" for i in range(16))
    with pytest.raises(aseq.SequenceError, match="too long"):
        aseq.parse("on=1;" + steps)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main(["-v", __file__]))
