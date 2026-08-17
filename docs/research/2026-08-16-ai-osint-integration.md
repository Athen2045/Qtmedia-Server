# Local AI, Reverse-Image, and OSINT Integration Research

Date: 2026-08-16  
Scope: Feasibility of integrating `HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive`, `Decimation/SmartImage`, and `Alfredredbird/tookie-osint` into this repository.  
Source policy: primary sources only (official model cards, upstream repositories, READMEs/source, and first-party runtime/API documentation).

## Executive summary

- The three candidates are complementary, not interchangeable. Qwen3.5 is a local multimodal language model; SmartImage is a reverse-image-search client; Tookie is a username/social-account OSINT scanner. None of the three is a complete replacement for the others.
- Integration is technically feasible, but none belongs in the current Python dependency set as a normal in-process library. The lowest-risk boundary is an optional external runtime/process: a localhost model server for Qwen3.5, the SmartImage.Rdx executable for reverse search, and a separate Tookie virtual environment for username scanning.
- The supplied Qwen model is Apache-2.0 on its Hugging Face card and has native text/image/video claims, but it is explicitly an uncensored community derivative. Its Q4_K_M GGUF is listed at about 2.6 GB and its separate vision projector at about 645 MB; runtime memory is higher, especially at long context. The card recommends a recent runtime and at least 128K context for its thinking behavior.
- SmartImage is the only candidate here that actually performs reverse image search. Its current cross-platform CLI accepts a URI, file path, or stdin and can emit delimited fields, but its documented local server is deprecated as of 1.2.0. It is GPLv3, so bundling or modifying it has stronger distribution obligations than treating it as an independent external executable.
- Tookie does not perform reverse image search. Its required input is one or more usernames; it probes configured sites with `requests` and can optionally use Selenium/Chrome for page scraping. It is MIT-licensed, but its README says the V4 README/wiki are still changing and the project is optimized for Python 3.12. Its runtime behavior includes remote update/header downloads and many outbound site requests.
- Recommendation: do not use the uncensored model as a safety or policy layer, and do not make any of these tools a default part of the downloader. If the product need is image provenance, use a dedicated reverse-search boundary (SmartImage for desktop use or a licensed provider API such as TinEye for a stable production API); use a standard Qwen3.5 checkpoint for image understanding; use Maigret or a similarly embeddable username tool only as an explicit, lawful OSINT feature.

## Repository context

The current project is a Python 3.11+ terminal search/download application. Its declared dependencies are HTTP, HTML, CLI, image, fuzzy-matching, and yt-dlp packages; it does not currently declare `transformers`, PyTorch, Ollama, llama.cpp, .NET, Selenium, or a browser-driver runtime. See the local [README](../../README.md) and [pyproject.toml](../../pyproject.toml).

The current application already makes network requests to configured sites, downloads media, caches thumbnails, and documents a responsible-use boundary. That means an OSINT/reverse-search feature would add materially different data flows: image uploads or browser searches, username probes across many unrelated sites, and potentially sensitive personal information. It should be treated as a separate optional capability rather than as another search adapter.

## 1. Qwen3.5-4B-Uncensored-HauhauCS-Aggressive

### What it is

The [HauhauCS model card](https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive) labels the model `qwen35`, `GGUF`, multilingual/conversational, and Apache-2.0. The card describes it as a 4B dense-parameter model derived from Qwen3.5-4B with a hybrid Gated DeltaNet/full-attention architecture, native text/image/video input, 201-language vocabulary coverage, and multi-token prediction. The card's “0/465 refusals” and “zero capability loss” statements are publisher claims, not an independent safety or quality evaluation.

The upstream [Qwen/Qwen3.5-4B model card](https://huggingface.co/Qwen/Qwen3.5-4B) also identifies the base checkpoint as Apache-2.0 and describes a causal language model with a vision encoder. It documents image-text-to-text use through `transformers`, including `AutoProcessor` and `AutoModelForMultimodalLM`.

### Modality, context, and resource requirements

The HauhauCS card lists:

| Item | Finding |
| --- | --- |
| Modality | Native text, image, and video input according to the card; this is not a text-only model. |
| GGUF choices | BF16 about 7.9 GB; Q8_0 about 4.2 GB; Q6_K about 3.3 GB; Q4_K_M about 2.6 GB. |
| Vision component | `mmproj-...-BF16.gguf`, listed at about 645 MB, must accompany the main GGUF for image/video input in compatible runtimes. |
| Context | 262,144 native tokens; the card says it is extendable to about 1M with YaRN. It also says to maintain at least 128K context to preserve thinking capabilities. |
| Suggested sampling | Thinking: temperature 0.6, top-p 0.95, top-k 20. Non-thinking: temperature 0.7, top-p 0.8, top-k 20. |
| Runtime maturity | The card calls the architecture new and says to use a recent llama.cpp build; it lists llama.cpp, LM Studio, Jan, koboldcpp, and other compatible runtimes. |

The file sizes are not RAM requirements. The runtime also needs model state, KV cache, image/video preprocessing, and possibly GPU memory. A 262K context is particularly expensive; a practical deployment should choose a bounded context based on measured hardware rather than blindly enabling the model's maximum. This is an inference from the published model size/context facts, not a hardware guarantee from the card.

### Runtime paths

- **llama.cpp:** The card gives `llama-server`/`llama-cli -hf ...:Q4_K_M` examples. The upstream [llama.cpp multimodal documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md) says multimodal serving uses `libmtmd`, supports image/audio/video input, and can load a model with `-m model.gguf --mmproj file.gguf` or a supported Hugging Face model with `-hf`. The [server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) documents an OpenAI-compatible `/v1/chat/completions` endpoint.
- **Ollama:** The HauhauCS card provides `ollama run hf.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive:Q4_K_M`. Ollama's [vision documentation](https://github.com/ollama/ollama/blob/main/docs/capabilities/vision.mdx) specifies an `images` array for multimodal chat and says the REST API expects base64 image data. Ollama's [model-import documentation](https://github.com/ollama/ollama/blob/main/docs/import.mdx) documents importing local GGUF files with a `FROM` line, but the exact multimodal behavior of a community GGUF should be validated on the target Ollama version rather than assumed from text-model import support.
- **Transformers:** The official [Qwen3.5 Transformers documentation](https://huggingface.co/docs/transformers/en/model_doc/qwen3_5) documents the Qwen3.5 architecture and notes that optional `causal_conv1d` and `fla` packages provide fast kernels; without them, PyTorch falls back to slower, more memory-hungry operations. The supplied HauhauCS artifact is a GGUF release, so direct native-Transformers loading is not the natural first path. A verified Transformers-format conversion would be a separate artifact with its own provenance and compatibility checks.

### What it can and cannot do for this project

It can caption or describe an image, extract visual clues, classify visible content, and help turn an image into candidate search terms. It does not itself query SauceNAO, TinEye, Google Images, Yandex, or an equivalent index. A multimodal model's answer is generated inference, not a reverse-search match, and should never be presented as proof of an image's source or identity.

The uncensored variant is not needed for image understanding or reverse search. Its refusal-removal objective removes a useful safety control and makes prompt injection, illegal-content requests, harassment, and unsafe procedural advice more likely to be returned. If a model is used, the application must enforce its own input/output policy and must not treat the model's lack of refusals as a feature that authorizes a use case.

## 2. Decimation/SmartImage

### What it actually does

The official [SmartImage README](https://github.com/Decimation/SmartImage/blob/master/README.md) describes SmartImage as a Windows reverse image search tool that searches multiple engines and opens the best returned match in a browser. It lists engines including SauceNAO, ImgOps, Google Images, TinEye, IQDB, trace.moe, Karma Decay, Yandex, Bing, Tidder, and Ascii2D. This is genuine reverse-image search, not merely resizing, hashing, EXIF inspection, captioning, or generic image processing.

The [SmartImage.Rdx usage documentation](https://github.com/Decimation/SmartImage/wiki/%28Rdx%29-Usage) describes the cross-platform CLI. It accepts a direct image URI, a file path, or piped file path/binary data; supports engine and upload-engine selection; and can write delimited output with fields such as name, URL, similarity, artist, and site. It also has options for reading Firefox cookies on Windows and using FlareSolverr. Those options are important security and terms-of-service decisions, not harmless implementation details.

### Dependencies, license, and status

- The README says to ensure [.NET 6](https://github.com/Decimation/SmartImage/blob/master/README.md) is installed. The repository contains separate GUI, library, and Rdx projects, so the Python application should not assume it can import SmartImage as a Python package.
- The repository's [LICENSE](https://github.com/Decimation/SmartImage/blob/master/LICENSE) is GNU GPLv3. Running a separately installed executable is a different distribution shape from copying or linking its code into this repository, but the exact legal result depends on how a future release bundles, modifies, or conveys it. Treat this as a legal review item before redistribution.
- The Rdx wiki records `v1.2.1` and a last update of 2026-03-07. The [Rdx server page](https://github.com/Decimation/SmartImage/wiki/%28Rdx%29-Server) explicitly says the server is deprecated as of 1.2.0. The current integration surface should therefore be the CLI, not the deprecated local HTTP server.

### Integration boundary

SmartImage is a good optional child-process integration for this Windows-oriented project:

1. Accept a user-selected local image or an already-public image URL.
2. Invoke a pinned SmartImage.Rdx executable with an allowlisted engine set.
3. Prefer delimited output to interactive browser launching and parse it as untrusted data.
4. Keep cookies, FlareSolverr, and context-menu installation disabled by default.
5. Display results as “external reverse-search results,” with engine/source and timestamp, not as verified identity or ownership.

Do not make a model call a prerequisite for SmartImage. The direct image-to-engine path is both more accurate for reverse search and easier to explain to users.

## 3. Alfredredbird/tookie-osint

### What it actually does

The official [Tookie README](https://github.com/Alfredredbird/tookie-osint/blob/main/README.md) says its purpose is to discover social-media accounts from usernames, similar to Sherlock. Its CLI requires either `-u/--user` or `-U/--userfile`; the [main script](https://github.com/Alfredredbird/tookie-osint/blob/main/brib.py) runs concurrent site checks and writes text, CSV, or JSON results. There is no image input, image embedding, reverse-image engine, or image-match output in the documented interface or the inspected entry point. Tookie is username/account OSINT, not reverse image search.

The source confirms a broad network boundary: [`modules.py`](https://github.com/Alfredredbird/tookie-osint/blob/main/modules/modules.py) builds URLs by appending a username, performs `requests.get` calls, optionally downloads a remote user-agent list, and checks the remote repository for updates. The optional [`webscraper.py`](https://github.com/Alfredredbird/tookie-osint/blob/main/modules/webscraper.py) starts a headless Chrome Selenium driver and can inspect configured pages and fields.

### Dependencies, license, and status

- The official [requirements.txt](https://github.com/Alfredredbird/tookie-osint/blob/main/requirements.txt) lists `colorama`, `requests`, `argparse`, `selenium`, and `webdriver-manager`. `argparse` is part of Python's standard library; the others still need environment and license review.
- The README says the V4 rewrite is still going through README/wiki changes and is optimized for Python 3.12. This repository supports Python 3.11+, so adding Tookie directly would create a version and dependency boundary. Its installer also performs system-level installation and creates its own virtual environment; that is inappropriate for the main app's normal install path.
- Tookie is [MIT-licensed](https://github.com/Alfredredbird/tookie-osint/blob/main/LICENSE). Its [security policy](https://github.com/Alfredredbird/tookie-osint/blob/main/SECURITY.md) asks users to obtain an official copy because other repositories cannot be checked for malware. That is a useful supply-chain warning even though the license is permissive.

### Integration boundary

If username OSINT is genuinely required, run Tookie as an explicitly selected external tool in a separate virtual environment. Pass only a user-confirmed username or file, cap threads and timeouts, store results in a user-selected report directory, and clearly label “not found” as an uncertain negative rather than proof that an account does not exist. Do not connect it automatically to every downloaded image or to model-generated names: that would create a high-risk identity-inference pipeline from uncertain model output into many third-party site requests.

## 4. Capability and boundary map

| Need | Qwen3.5 HauhauCS | SmartImage | Tookie | Fit for current project |
| --- | --- | --- | --- | --- |
| Describe/classify an image | Yes, via multimodal runtime and the vision component | No | No | Optional localhost model service |
| Find web pages containing/matching an image | No built-in search index or search-engine connector | Yes | No | SmartImage CLI or licensed provider API |
| Find accounts for a supplied username | No | No | Yes | Separate opt-in OSINT process |
| Keep inference local | Yes if served locally | The wrapper can be local, but search engines receive the query through their own network paths | No; it probes remote sites | Privacy depends on the boundary, not only on local execution |
| Natural Python in-process dependency | No for the GGUF/runtime | No; executable/CLI | No; script plus browser/runtime | Use subprocess or localhost HTTP |

## 5. Privacy, security, and legal concerns

### Privacy and data egress

- A local Qwen runtime can keep the image bytes and prompt local, but sending a public URL to a model server or engine still exposes that URL to the receiving service. Ollama's API uses base64 image payloads, while llama.cpp's multimodal server accepts image inputs through its API; enforce request-size limits and bind local services to loopback unless remote access is intentional.
- SmartImage's purpose is to submit an image URI or file to external search engines. Do not use it on confidential, intimate, proprietary, or identifying images without a documented legal and privacy basis. `--read-cookies` can expose browser-session context to the search flow; leave it off by default. FlareSolverr adds another service and may cross site anti-bot boundaries.
- Tookie sends usernames and request metadata to many sites. Its remote user-agent/update/MOTD behavior means a “local” run still has additional outbound GitHub and target-site traffic. Use a network policy, proxy policy, timeout/rate limit, and an auditable report directory.
- Treat downloaded media, thumbnails, search results, usernames, and model prompts as potentially sensitive. Do not place them in logs, Git, crash reports, or telemetry by default.

### Security and supply chain

- Pin and verify external executable versions and model file hashes before use. Do not execute arbitrary paths supplied by a model or user without validation.
- Run the model, SmartImage, and Tookie with least privilege. Use temporary directories, bounded subprocess timeouts, no inherited secrets, and no automatic browser-cookie access.
- Parse all CLI/HTTP output as untrusted. Reverse-search titles, URLs, page text, and OSINT results can contain prompt-injection text or malicious URLs; never feed them back to a model as trusted instructions, and do not auto-open them without a user action.
- Keep the model as an analyzer, not an autonomous agent. It has no authority to perform web searches, download files, contact sites, or identify people unless a separately controlled feature invokes those actions.

### Licensing and terms

The relevant licenses are Apache-2.0 for the supplied model card, GPLv3 for SmartImage, and MIT for Tookie. These licenses govern code/weights, not permission to scrape websites, upload images, download copyrighted media, or infer a person's identity. Provider terms, copyright, privacy/data-protection law, biometric/privacy rules where applicable, age restrictions, and site rate limits still apply. This is not legal advice; obtain a specific review before distributing SmartImage or operating OSINT/reverse-search features for third parties.

## 6. Better alternatives and recommendation

| Goal | Better fit | Why |
| --- | --- | --- |
| Local image understanding | [Qwen/Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B), the official base checkpoint | Same family-level multimodal shape and Apache-2.0 card, without choosing a refusal-removed derivative solely for captioning or visual analysis. Use its official Transformers path or a verified llama.cpp/Ollama-compatible build. |
| Production reverse-image search | A licensed provider API such as the official [TinEye API](https://services.tineye.com/TinEyeAPI) | It exposes a documented HTTPS/JSON integration and explicit commercial terms. This is easier to version and audit than screen-scraping several public engines, though it introduces cost and third-party image transfer. |
| Desktop/multi-engine reverse search | SmartImage.Rdx, isolated as an optional executable | It already provides the required engine fan-out and structured output; use its CLI, not the deprecated server, and honor GPLv3 and provider terms. |
| Embeddable username OSINT | [Maigret](https://github.com/soxoj/maigret) | Its official README documents Python embedding, a maintained site database, 3,000+ sites, MIT licensing, and report modes. It still performs network reconnaissance and is not automatically safe or lawful; the same consent/rate-limit controls remain necessary. |

Recommended architecture if the feature is later approved:

```text
local image
   ├── optional Qwen3.5 localhost call -> description / candidate clues only
   └── explicit reverse-search action -> SmartImage.Rdx or licensed image-search API

explicit username input
   └── separate OSINT process -> report with source URLs, timestamps, and uncertainty
```

No application code was changed for this research. The next implementation decision should be whether the product actually needs image understanding, reverse-image provenance, username discovery, or some combination; the sources show that they should not be presented as one “AI OSINT” capability.

## Primary sources consulted

- [HauhauCS Qwen3.5-4B-Uncensored-HauhauCS-Aggressive model card](https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive)
- [Official Qwen/Qwen3.5-4B model card](https://huggingface.co/Qwen/Qwen3.5-4B)
- [Hugging Face Transformers Qwen3.5 documentation](https://huggingface.co/docs/transformers/en/model_doc/qwen3_5)
- [llama.cpp multimodal documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md)
- [llama.cpp server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [Ollama vision documentation](https://github.com/ollama/ollama/blob/main/docs/capabilities/vision.mdx)
- [Ollama model import documentation](https://github.com/ollama/ollama/blob/main/docs/import.mdx)
- [SmartImage README](https://github.com/Decimation/SmartImage/blob/master/README.md)
- [SmartImage GPLv3 license](https://github.com/Decimation/SmartImage/blob/master/LICENSE)
- [SmartImage.Rdx usage wiki](https://github.com/Decimation/SmartImage/wiki/%28Rdx%29-Usage)
- [SmartImage.Rdx integration wiki](https://github.com/Decimation/SmartImage/wiki/%28Rdx%29-Integration)
- [SmartImage.Rdx server wiki](https://github.com/Decimation/SmartImage/wiki/%28Rdx%29-Server)
- [Tookie README](https://github.com/Alfredredbird/tookie-osint/blob/main/README.md)
- [Tookie entry point](https://github.com/Alfredredbird/tookie-osint/blob/main/brib.py)
- [Tookie dependencies](https://github.com/Alfredredbird/tookie-osint/blob/main/requirements.txt)
- [Tookie network/site-check source](https://github.com/Alfredredbird/tookie-osint/blob/main/modules/modules.py)
- [Tookie Selenium source](https://github.com/Alfredredbird/tookie-osint/blob/main/modules/webscraper.py)
- [Tookie MIT license](https://github.com/Alfredredbird/tookie-osint/blob/main/LICENSE)
- [Tookie security policy](https://github.com/Alfredredbird/tookie-osint/blob/main/SECURITY.md)
- [TinEye API](https://services.tineye.com/TinEyeAPI)
- [Maigret README](https://github.com/soxoj/maigret)
