# Architecture

The repository has two user-facing interfaces and a small shared runtime
configuration module.

```text
root launchers (search.py, download.py)
        |
        v
src/private_search/
  downloader.py  direct URL validation and yt-dlp downloads
  search.py      site adapters, concurrent inspection, filters and CLI
  config.py      stable runtime paths
        |
        v
var/
  downloads/     downloaded media
  cache/         SQLite inspection cache
```

The root launchers are compatibility seams. New code should import the package
modules or use the `private-search` and `private-download` console commands.
Site-specific scraping remains behind the `SiteAdapter` interface, allowing an
adapter to change without changing the search pipeline.

Runtime data is excluded from version control. This keeps repository locality
focused on implementation and prevents media or cache state from entering a
private GitHub repository accidentally.
