# Firecrawl and Theia evaluation

Date: 2026-08-17

## Question

Would integrating `firecrawl/firecrawl` materially improve Theia's reverse-image
search and username OSINT capabilities?

## Findings

Firecrawl is a web-context API for search, scraping, interaction, crawling, and
structured extraction. It can return clean Markdown or JSON from JavaScript-heavy
pages and can optionally scrape search results. It does not provide visual
similarity search, face detection, face embeddings, or a reverse-image index.

### Reverse-image search

Firecrawl would not improve the visual matching accuracy of SmartImage. The
current pipeline should remain:

1. InsightFace detects, aligns, indexes, and optionally crops faces locally.
2. SmartImage performs the external reverse-image lookup.
3. Firecrawl could optionally scrape selected result URLs to extract titles,
   descriptions, links, and other page metadata for ranking or display.

That makes Firecrawl an enrichment step after reverse search, not a replacement
for SmartImage or a new image-search backend.

### Username search

Firecrawl could improve extraction from a known public profile URL or a small set
of selected candidate URLs, especially when a site is JavaScript-heavy. It should
not replace Blackbird's site enumeration. Blackbird already probes a packaged
list of sites; Firecrawl has no equivalent identity-verification database and a
broad crawl for every username would be slower, noisier, more expensive, and
more likely to trigger site protections.

The useful design is a confirmation-gated second stage:

`Blackbird candidates -> user selects URLs -> Firecrawl enriches selected pages -> local cache/ranking`

Firecrawl Search could also be offered as an optional web-search source, but its
results should be clearly separated from verified Blackbird hits.

## Operational and privacy trade-offs

- The hosted API sends requested URLs/content through Firecrawl and needs an API
  key and quota. This conflicts with Theia's local-first privacy goal unless the
  user explicitly enables it.
- Self-hosting is possible, but the official guide uses Docker and supporting
  services. Self-hosted deployments do not have Fire-engine's advanced handling
  for IP blocks and robot detection, so they may be less effective against
  difficult sites.
- Scraping must remain confirmation-gated, rate-limited, cached, and subject to
  each site's terms, privacy rules, and robots policy.
- Firecrawl is AGPL-3.0. Any direct integration or redistribution needs a license
  review; using a separately deployed service has different obligations than
  copying or modifying Firecrawl code inside Theia.

## Recommendation

Do not add Firecrawl as a core replacement now. Add it later as an optional
`web_enrich` capability with cloud and self-hosted endpoints, disabled by
default. Feed it only user-approved URLs returned by Blackbird or SmartImage,
store normalized results in the existing local cache, and show the source and
whether the result was enumerated or merely discovered by web search.

This is likely to improve result detail and page coverage, not the underlying
reverse-image or username-match accuracy. The current priority remains making
Blackbird's live site probes reliable and keeping SmartImage's upload/search
engines healthy.

## Primary sources

- [Firecrawl repository](https://github.com/firecrawl/firecrawl)
- [Firecrawl self-hosting guide](https://github.com/firecrawl/firecrawl/blob/main/SELF_HOST.md)
- [Firecrawl Search API reference](https://docs.firecrawl.dev/api-reference/endpoint/search)
