import sys

import pytest
from typer.testing import CliRunner

from private_search.app import cli
from private_search.search.engine import VideoResult

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


def test_download_command_returns_nonzero_when_download_fails(monkeypatch):
    monkeypatch.setattr(cli.downloader, "download_video", lambda url, progress=None: False)

    result = runner.invoke(cli.app, ["download", "https://example.test/video"])

    assert result.exit_code != 0


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
        input="2\ny\n",
    )

    assert result.exit_code == 0
    assert "First" in result.stdout
    assert "Second" in result.stdout
    assert downloaded == ["https://example.test/2"]


def test_search_selection_can_reselect_after_preview(monkeypatch):
    results = [
        _make_result(title="First", url="https://example.test/1"),
        _make_result(title="Second", url="https://example.test/2"),
    ]
    search_calls = []
    previews = []
    downloaded = []

    def fake_search(*args, **kwargs):
        search_calls.append(True)
        return results

    monkeypatch.setattr(cli.search, "search", fake_search)
    monkeypatch.setattr(cli, "_render_selected_result", lambda result: previews.append(result.title))
    monkeypatch.setattr(cli, "_run_download", downloaded.append)

    result = runner.invoke(cli.app, ["search", "some title"], input="1\nr\n2\ny\n")

    assert result.exit_code == 0
    assert search_calls == [True]
    assert previews == ["First", "Second"]
    assert downloaded == ["https://example.test/2"]


def test_search_command_blank_answer_skips_download(monkeypatch):
    monkeypatch.setattr(cli.search, "search", lambda *a, **k: [_make_result()])
    downloaded = []
    monkeypatch.setattr(cli, "_run_download", downloaded.append)

    result = runner.invoke(cli.app, ["search", "some title"], input="\n")

    assert result.exit_code == 0
    assert downloaded == []


def test_search_command_invalid_number_returns_an_error(monkeypatch):
    monkeypatch.setattr(cli.search, "search", lambda *a, **k: [_make_result()])
    downloaded = []
    monkeypatch.setattr(cli, "_run_download", downloaded.append)

    result = runner.invoke(cli.app, ["search", "some title"], input="99\n")

    assert result.exit_code != 0
    assert downloaded == []


def test_search_command_zero_returns_an_error(monkeypatch):
    monkeypatch.setattr(cli.search, "search", lambda *a, **k: [_make_result()])
    downloaded = []
    monkeypatch.setattr(cli, "_run_download", downloaded.append)

    result = runner.invoke(cli.app, ["search", "some title"], input="0\n")

    assert result.exit_code != 0
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
    )

    assert result.exit_code == 0
    assert calls == ["https://example.test/direct"]
    assert "Direct hit" in result.stdout
    assert downloaded == []


def test_direct_url_does_not_require_query_or_prompt(monkeypatch):
    inspected = _make_result(title="Direct hit")
    monkeypatch.setattr(cli.search, "inspect_direct_url", lambda url: inspected)
    monkeypatch.setattr(cli, "_run_download", lambda url: (_ for _ in ()).throw(AssertionError(url)))

    result = runner.invoke(cli.app, ["search", "--direct-url", "https://example.test/direct"])

    assert result.exit_code == 0
    assert "Direct hit" in result.stdout


def test_direct_url_rejects_malformed_url(monkeypatch):
    result = runner.invoke(cli.app, ["search", "--direct-url", "not-a-url"])

    assert result.exit_code != 0


def test_q_skips_download(monkeypatch):
    monkeypatch.setattr(cli.search, "search", lambda *args, **kwargs: [_make_result()])
    downloaded = []
    monkeypatch.setattr(cli, "_run_download", downloaded.append)

    result = runner.invoke(cli.app, ["search", "some title"], input="q\n")

    assert result.exit_code == 0
    assert downloaded == []


def test_invalid_selection_returns_nonzero(monkeypatch):
    monkeypatch.setattr(cli.search, "search", lambda *args, **kwargs: [_make_result()])

    result = runner.invoke(cli.app, ["search", "some title"], input="99\n")

    assert result.exit_code != 0


def test_no_prompt_skips_stdin(monkeypatch):
    monkeypatch.setattr(cli.search, "search", lambda *args, **kwargs: [_make_result()])
    monkeypatch.setattr(cli, "_prompt_and_download", lambda results: (_ for _ in ()).throw(AssertionError()))

    result = runner.invoke(cli.app, ["search", "some title", "--no-prompt"])

    assert result.exit_code == 0


def test_run_search_alias_forwards_argv_to_search_command(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["private-search", "some title", "--min-views", "5"])
    calls = []

    def fake_search(query, filters, excludes, min_views):
        calls.append((query, filters, excludes, min_views))
        return []

    monkeypatch.setattr(cli.search, "search", fake_search)

    with pytest.raises(SystemExit) as exc_info:
        cli.run_search_alias()

    assert exc_info.value.code in (0, None)
    assert calls == [("some title", [], list(cli.search.DEFAULT_EXCLUDES), 5)]


def test_run_download_alias_forwards_argv_to_download_command(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["private-download", "https://example.test/video"])
    calls = []
    monkeypatch.setattr(cli.downloader, "download_video", lambda url, progress=None: calls.append(url))

    with pytest.raises(SystemExit) as exc_info:
        cli.run_download_alias()

    assert exc_info.value.code in (0, None)
    assert calls == ["https://example.test/video"]
