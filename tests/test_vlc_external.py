from nihongo_quest.core.immersion.vlc_external import ExternalVlc, find_vlc_exe


def test_find_vlc_exe_type():
    exe = find_vlc_exe()
    assert exe is None or exe.name.lower() == "vlc.exe"


def test_external_vlc_not_running_by_default():
    v = ExternalVlc()
    assert not v.running
