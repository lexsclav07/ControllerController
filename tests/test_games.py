from controllercontroller.games import running_game, steam_app_id


def proc(root, pid, *argv):
    (root / str(pid)).mkdir()
    (root / str(pid) / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")


def test_steam_reaper_is_a_game():
    argv = [b"/home/u/.local/share/Steam/steamrt64/reaper", b"SteamLaunch", b"AppId=400", b"--", b"hl2.sh"]
    assert steam_app_id(argv) == "400"


def test_steam_client_alone_is_not_a_game(tmp_path):
    proc(tmp_path, 1, "/home/u/.local/share/Steam/steamrt64/steam", "-srt-logger-opened")
    proc(tmp_path, 2, "grep", "reaper SteamLaunch AppId=400")
    (tmp_path / "3").mkdir()   # exited between listing and reading
    (tmp_path / "self").mkdir()
    assert running_game(str(tmp_path)) is None
    proc(tmp_path, 4, "/x/reaper", "SteamLaunch", "AppId=620", "--", "portal2")
    assert running_game(str(tmp_path)) == "620"
