from ridewise import stt


def test_id_normalisation():
    assert stt._normalise("refund for booking B 1709") == "refund for booking B-1709"
    assert stt._normalise("customer cust 13") == "customer CUST0013"
    assert stt._normalise("pay 1 and veh 7") == "PAY00001 and VEH007"


def test_native_digits_to_ascii():
    assert stt._normalise("B १२३४") == "B-1234"      # Devanagari
    assert stt._normalise("೧೨೩") == "123"             # Kannada


def test_disabled_returns_error():
    text, err = stt.transcribe(b"somebytes", "en")
    assert text == "" and err == "voice input is disabled"


def test_empty_audio():
    # even if "enabled", empty audio is rejected before any network call
    import ridewise.config as c
    c.settings.stt_enabled = True
    c.settings.groq_api_key = "x"
    try:
        text, err = stt.transcribe(b"", "en")
        assert text == "" and err == "no audio received"
    finally:
        c.settings.stt_enabled = False
        c.settings.groq_api_key = ""
