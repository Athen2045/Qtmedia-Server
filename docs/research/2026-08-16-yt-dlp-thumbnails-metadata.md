# yt-dlp Thumbnail and View Metadata Research

Date: 2026-08-16

## Findings

- yt-dlp documents `thumbnail` and `view_count` as standard result fields, but metadata is extractor-dependent and either field may be absent. See the [official yt-dlp README](https://github.com/yt-dlp/yt-dlp/blob/master/README.md).
- yt-dlp's common extractor contract describes `thumbnail` as a full image URL and `view_count` as optional numeric metadata. See the [common extractor info fields](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/common.py).
- The current [XVideos extractor](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/xvideos.py) exposes a thumbnail list but does not populate `view_count`.

## Project impact

For the XVideos URL supplied during testing, yt-dlp returned a normalized thumbnail and a `thumbnails` list, but no `view_count`. The page itself contained a visible count of `485,165`. The search tool now:

1. Uses yt-dlp's normalized thumbnail, then falls back to the extractor's `thumbnails` list.
2. Re-inspects cached records created before thumbnail metadata was stored.
3. Performs a bounded XVideos page lookup only when yt-dlp did not provide `view_count`.

This preserves yt-dlp as the primary metadata source while handling extractor-specific omissions without scraping every provider or making unbounded requests.
