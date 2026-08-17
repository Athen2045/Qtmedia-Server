# Theia capability and performance research — 2026-08-17

## Scope

This review covers Theia's local Qwen/llama.cpp runtime, the search and download
paths, Blackbird, InsightFace, and SmartImage. The goal is to improve tool
selection and responsiveness without replacing working site adapters with a
large new crawler stack.

## Findings

### Local model

The installed runtime is a CUDA build of `llama-server` and the model is a local
Q4 GGUF. The server supports GPU offload, Flash Attention, logical and physical
batch limits, continuous batching, and metrics. The current application already
uses CUDA device selection, full GPU-layer offload, an 8192-token context, and a
4096-token generation limit. The server's documented defaults for batch size
(`2048`) and physical batch size (`512`) are already appropriate starting points
for a single local user; increasing them blindly can trade VRAM headroom for
little benefit.

Source: [llama.cpp server options](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).

Decision: expose the performance switches through validated environment-backed
settings, and enable Flash Attention only when explicitly configured or when
the CUDA runtime is selected. Keep batch sizes conservative and measurable.

### Search

Theia fans out to the configured site adapters concurrently, then performs a
second `yt-dlp` inspection pass over candidate links to obtain canonical title,
view, and quality metadata. This second pass is the dominant latency source:
seven sites can produce roughly 140 candidate inspections at the current cap.
The adapter layer already has bounded response reads, browser impersonation,
SQLite caching, retries, and a bounded thread pool. Replacing it with an
asynchronous crawler would not automatically improve reliability because the
site adapters depend on browser-like TLS and site-specific HTML rules.

Decision: retain the adapter model, make inspection concurrency and candidate
caps tunable, and improve retry behavior. A browser/crawler fallback should be
an optional provider for pages that require JavaScript, not the default path.

### Downloading

The downloader uses yt-dlp with resume support, fragment retries, cancellation,
and bounded concurrent HLS fragment downloads. yt-dlp documents concurrent
fragment downloads and separate HTTP/fragment retry controls. More connections
are not universally faster: CDNs may throttle or reset aggressive clients.

Source: [yt-dlp options and download behavior](https://github.com/yt-dlp/yt-dlp/blob/master/README.md).

Decision: keep a conservative default and expose the concurrency cap. Use
resume and retry-after-aware backoff rather than forcing high concurrency.

### Blackbird, InsightFace, and SmartImage

The three capabilities are correctly isolated as subprocess/worker boundaries.
That is the right failure boundary for incompatible dependency trees and GPU
libraries. Theia should treat their output as typed evidence with provenance,
confidence, timing, and partial-failure status. SmartImage remains networked and
engine-dependent; InsightFace can improve local face matching but cannot prove
that a web reverse-search result is the same person. A local face index should
remain private by default, and uploaded reverse-search images require explicit
confirmation.

Decision: improve orchestration, progress, caching, and result normalization
before attempting model training or a full crawler rewrite.

### Training and model upgrades

There is not yet a labeled, consented, evaluated Theia dataset in the project,
so an automatic fine-tune would be premature. The safest upgrade path is to
collect private tool traces and preference pairs, validate them, and fine-tune
a small LoRA/SFT adapter only after defining held-out evaluations for intent
classification, argument extraction, tool choice, and concise result
summaries. Keep raw OSINT traces, image data, usernames, and URLs private.

Sources: [TRL SFT Trainer](https://huggingface.co/docs/trl/sft_trainer),
[Hugging Face Jobs](https://huggingface.co/docs/huggingface_hub/guides/jobs),
[Hugging Face Datasets Viewer API](https://huggingface.co/docs/datasets-server).

Hugging Face model selection should be benchmark-driven. A larger model may
improve tool reasoning but can reduce local speed and context headroom. The
current 4B quantized model is a reasonable latency-first baseline; compare
candidate GGUFs on the same Theia evaluation set before changing it.

## Recommended implementation order

1. Make llama.cpp Flash Attention, batch sizes, and generation settings visible
   and validated through environment variables.
2. Make HTTP retries respect `Retry-After`, use exponential jitter, and keep
   response bodies bounded.
3. Make search inspection workers and per-site candidate caps configurable,
   with safe defaults and telemetry so quality/latency can be compared.
4. Keep yt-dlp concurrency configurable; benchmark per host before raising it.
5. Add tool capability metadata and provenance to the model-facing contract so
   Theia chooses Blackbird, InsightFace, SmartImage, search, and download based
   on capability rather than brittle keyword habits.
6. Add a private evaluation/training trace format. Only then consider LoRA/SFT
   or a model replacement.

## Explicit non-goals for this pass

- No automatic cloud training job: no dataset, evaluation set, or HF token was
  supplied.
- No mandatory Playwright/Firecrawl dependency: it would increase installation
  size and operational failure modes before a JavaScript-only site requires it.
- No claim that a reverse-image or face result is an identity confirmation.

