from typer.testing import CliRunner

from private_search import cli

runner = CliRunner()


def test_download_command_invokes_download_video_with_progress_callback(monkeypatch):
    calls = []

    def fake_download_video(url, progress=None):
        calls.append(url)
        assert callable(progress)
        progress({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 4})
        progress({"status": "finished"})

    monkeypatch.setattr(cli.downloader, "download_video", fake_download_video)

    result = runner.invoke(cli.app, ["download", "https://example.test/video"])

    assert result.exit_code == 0
    assert calls == ["https://example.test/video"]
