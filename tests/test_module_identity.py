import ald_media_controller as controller


def test_public_media_controller_uses_implementation_monkeypatch_namespace():
    assert controller.publish_reports.__globals__ is controller.__dict__
    assert controller.replace_output_directory.__globals__ is controller.__dict__
    assert controller._run_simulate.__globals__ is controller.__dict__
