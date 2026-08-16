# Architecture

The repository has one interactive menu, two scriptable console commands, and
small modules organized by responsibility.

```text
main.bat / main.py / python -m private_search
        |
        v
src/private_search/
  app/
    cli.py       interactive menu and Typer commands
  search/
    engine.py    concurrent retrieval, inspection, filters and ranking
    quality.py   tokenization and relevance scoring
    preview.py   bounded Kitty thumbnail cache and renderer
  download/
    engine.py    direct URL validation and yt-dlp downloads
    control.py   cancellation primitives
    transfer.py  shared transfer settings
  sources/
    lustpress.py / pmvhaven.py  site-specific adapters
  net/
    http_client.py              bounded HTTP transport
  config.py                     stable runtime paths
        |
        v
var/
  downloads/     downloaded media
  cache/         SQLite inspection cache
```

`main.bat` is the normal Windows entry point. New code should import the
package modules or use the `private-search` and `private-download` console
commands. The application layer depends on search and download engines, while
site adapters and HTTP transport remain behind focused interfaces.
Site-specific scraping remains behind the `SiteAdapter` interface, allowing an
adapter to change without changing the search pipeline.

Runtime data is excluded from version control. This keeps repository locality
focused on implementation and prevents media or cache state from entering a
private GitHub repository accidentally.
