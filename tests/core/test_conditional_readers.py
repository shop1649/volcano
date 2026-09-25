"""CONDITIONAL_READERS links are verified, not trusted: each named reader must really read its key."""
from shortkit import config


def test_loop_xfade_reader():
    from shortkit.edit import audio as edit_audio

    spec = config.CONDITIONAL_READERS["audio.bgm.loop_xfade_s"]
    pr = config.load_preset("joshuamagazine")
    v = edit_audio.bgm_loop_xfade_s(pr)
    assert v is not None and v > 0
    reads = pr.log.to_dict()
    assert "audio.bgm.loop_xfade_s" in reads
    assert any(c == spec["reader"] for c in reads["audio.bgm.loop_xfade_s"]), reads


def test_every_conditional_reader_names_an_existing_test():
    for key, spec in config.CONDITIONAL_READERS.items():
        path, _, name = spec["test"].partition("::")
        assert name in (config.paths.project_root() / path).read_text(encoding="utf-8"), key
