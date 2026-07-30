from typer.testing import CliRunner

from private_search import cli
from private_search.search import VideoResult

runner = CliRunner()


def _make_result(title="Sample Title", url="https://example.test/1", views=42, height=1080):
    return VideoResult(
        title=title, url=url, site="ExampleSite", view_count=views, max_height=height, max_tbr=0.0
    )


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


def test_search_command_renders_table_and_downloads_chosen_result(monkeypatch):
    results = [_make_result(title="First"), _make_result(title="Second", url="https://example.test/2")]

    def fake_search(query, filters, excludes, min_views):
        assert query == "some title"
        assert filters == ["hd"]
        assert excludes == ["vr"]
        assert min_views == 10
        return results

    downloaded = []
    monkeypatch.setattr(cli.search, "search", fake_search)
    monkeypatch.setattr(cli, "_run_download", downloaded.append)

    result = runner.invoke(
        cli.app,
        ["search", "some title", "--filter", "hd", "--exclude", "vr", "--min-views", "10"],
        input="2\n",
    )

    assert result.exit_code == 0
    assert "First" in result.stdout
    assert "Second" in result.stdout
    assert downloaded == ["https://example.test/2"]


def test_search_command_blank_answer_skips_download(monkeypatch):
    monkeypatch.setattr(cli.search, "search", lambda *a, **k: [_make_result()])
    downloaded = []
    monkeypatch.setattr(cli, "_run_download", downloaded.append)

    result = runner.invoke(cli.app, ["search", "some title"], input="\n")

    assert result.exit_code == 0
    assert downloaded == []


def test_search_command_invalid_number_does_not_crash(monkeypatch):
    monkeypatch.setattr(cli.search, "search", lambda *a, **k: [_make_result()])
    downloaded = []
    monkeypatch.setattr(cli, "_run_download", downloaded.append)

    result = runner.invoke(cli.app, ["search", "some title"], input="99\n")

    assert result.exit_code == 0
    assert downloaded == []


def test_search_command_direct_url_inspects_instead_of_searching(monkeypatch):
    inspected = _make_result(title="Direct hit")
    calls = []

    def fake_inspect(url):
        calls.append(url)
        return inspected

    def fake_search(*args, **kwargs):
        raise AssertionError("search.search should not be called in --direct-url mode")

    monkeypatch.setattr(cli.search, "inspect_direct_url", fake_inspect)
    monkeypatch.setattr(cli.search, "search", fake_search)
    downloaded = []
    monkeypatch.setattr(cli, "_run_download", downloaded.append)

    result = runner.invoke(
        cli.app,
        ["search", "unused", "--direct-url", "https://example.test/direct"],
        input="1\n",
    )

    assert result.exit_code == 0
    assert calls == ["https://example.test/direct"]
    assert "Direct hit" in result.stdout
    assert downloaded == [inspected.url]
