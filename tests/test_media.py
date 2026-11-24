import subprocess

from controllercontroller import media


def fake_run(calls, rc=0, listing="", status='s "Playing"\n'):
    def run(cmd, **kw):
        calls.append(cmd)
        out = listing if "list" in cmd else status if "get-property" in cmd else ""
        return subprocess.CompletedProcess(cmd, rc if "call" in cmd else 0, stdout=out, stderr="")
    return run


def test_negative_seek_passes_double_dash_so_busctl_does_not_parse_an_option(monkeypatch):
    calls = []
    monkeypatch.setattr(media.subprocess, "run",
                        fake_run(calls, listing="org.mpris.MediaPlayer2.firefox.instance_1 123 firefox\n"))
    assert media.seek(-10) is True
    seek = [c for c in calls if "Seek" in c][0]
    assert seek[-3:] == ["x", "--", "-10000000"]


def test_failed_call_returns_false_so_key_fallback_runs(monkeypatch):
    calls = []
    monkeypatch.setattr(media.subprocess, "run",
                        fake_run(calls, rc=1, listing="org.mpris.MediaPlayer2.chrome 1 chrome\n"))
    assert media.seek(10) is False and media.play_pause() is False


def test_no_player_or_missing_busctl(monkeypatch):
    monkeypatch.setattr(media.subprocess, "run", fake_run([], listing=""))
    assert media.seek(10) is False

    def boom(*a, **k):
        raise FileNotFoundError("busctl")
    monkeypatch.setattr(media.subprocess, "run", boom)
    assert media.play_pause() is False
