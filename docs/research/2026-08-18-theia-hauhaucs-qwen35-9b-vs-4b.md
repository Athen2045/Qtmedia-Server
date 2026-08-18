# Theia model comparison: HauhauCS Qwen3.5-9B vs current 4B

Date: 2026-08-18  
Scope: Theia repository context, exact HauhauCS Hugging Face model-card/file claims, official Qwen documentation, and upstream/local llama.cpp evidence.  
Constraint: research only; no application code or runtime assets were modified.

## Recommendation

**Keep `HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive` as Theia’s default for now.** The 9B model is a reasonable opt-in experiment and should fit the 16 GB RTX 5080 Laptop GPU at Theia’s conservative 8K context more plausibly than its 17.9 GB BF16 artifact suggests, but the evidence gathered does not establish a capability or strict-JSON advantage over the current 4B model.

The 9B card repeats the same publisher claims as the 4B card—`0/465 refusals`, “zero capability loss,” and no dataset/capability changes—without publishing a 9B-versus-4B benchmark or Theia-like tool-call evaluation. Its Q4_K_M file is approximately twice the current model artifact, its matching projector is larger, and MTP is not active in Theia’s current launch command. The right next step is a text-first A/B test using the 9B Q4_K_M, with the matching projector tested separately; adoption should require equal-or-better strict JSON/tool behavior and acceptable latency/VRAM headroom.

## Theia’s actual workload and current setup

Theia is a local AI-assisted terminal for search, downloads, image description, reverse-image search, and username/email OSINT. The model is not given shell access or unrestricted tool execution. It first classifies each request into a closed action schema, then Python validates and executes the action through confirmation-gated adapters. The classifier requires exactly one JSON object containing all schema fields, uses `response_format: json_schema`, disables thinking, and allows 384 output tokens; malformed JSON is retried once and explicit tool requests fail closed if classification still fails. Ordinary conversation uses a separate free-form pass with a 4,096-token limit and optional thinking. Sources: [Theia action schema/prompts](../../src/private_search/ai/actions.py), [Theia orchestration](../../src/private_search/ai/chat.py), [Theia architecture](../architecture.md).

The checked-in runtime defaults are:

| Setting | Current value |
| --- | --- |
| Main model | `Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf` |
| Local main-model file | 2,707,513,696 bytes; SHA-256 `79E28ECACF84E75B6056CF4059636D435AA9EB67795780F7B7DBC7D32A962741` |
| Main projector | `mmproj-Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-BF16.gguf`; 675,568,768 bytes locally |
| Server | local CUDA build `llama-server` build `10451`, commit `10bf611e5` |
| Device/offload | `CUDA0`, `999` GPU layers |
| Context/generation | 8,192 / 4,096 tokens |
| Batch/ubatch | 2,048 / 512 |
| Flash Attention | on by default for the CUDA executable |
| Hardware probe | NVIDIA GeForce RTX 5080 Laptop GPU; 16,303 MiB total VRAM; driver 610.88 |

Sources: [Theia model/runtime configuration](../../src/private_search/config.py), [runtime settings and command construction](../../src/private_search/ai/runtime.py), [environment defaults](../../.env.example), and the local `nvidia-smi`/`llama-server --version` probes recorded on 2026-08-18.

## Exact HauhauCS model-card claims

### Current 4B model

The current card identifies `Qwen3.5-4B-Uncensored-HauhauCS-Aggressive` as a Qwen3.5-4B HauhauCS derivative. It claims `0/465 refusals`, full uncensoring with no capability loss, no changes to datasets or capabilities, and a stronger refusal-removal “Aggressive Variant.” The card warns that the model may still append inherited disclaimers, but says it will not refuse prompts. These are publisher claims, not an independently documented safety or capability evaluation. Source: [HauhauCS 4B model card](https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive).

The card lists 4B dense parameters, 32 layers, a 3:1 Gated DeltaNet/full-attention hybrid, 262K native context extendable to 1M with YaRN, text/image/video multimodality, MTP support, a 248K vocabulary, and 201 languages. It says a separate 645 MB vision encoder is required for image/video input. Its displayed quant options are BF16 7.9 GB, Q8_0 4.2 GB, Q6_K 3.3 GB, and Q4_K_M 2.6 GB; the Hugging Face model page displays the corresponding local-size figures as approximately 8.42, 4.48, 3.46, and 2.71 GB. Source: [HauhauCS 4B card, downloads and specs](https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive#downloads).

### Candidate 9B model

The candidate card identifies `Qwen3.5-9B-Uncensored-HauhauCS-Aggressive` as a Qwen3.5-9B HauhauCS derivative and the model tree records `Qwen/Qwen3.5-9B` as its fine-tuned base. It repeats the same `0/465 refusals`, zero-capability-loss, no-dataset/capability-change, and aggressive refusal-removal claims. There is no 9B-versus-4B benchmark table in the card. That absence matters: the 9B parameter increase is a plausible source of better reasoning, but it is not evidence that Theia’s classifier, tool selection, or concise response quality will improve. Sources: [HauhauCS 9B model card](https://huggingface.co/HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive), [9B model tree/base-model metadata](https://huggingface.co/HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive#model-tree-for-hauhaucsqwen35-9b-uncensored-hauhaucs-aggressive).

The 9B card lists 9B dense parameters, 32 layers, the same 3:1 hybrid architecture, 262K native context extendable to 1M with YaRN, native text/image/video multimodality, MTP support, a 248K vocabulary, and 201 languages. It lists the displayed quant options as BF16 17 GB, Q8_0 8.9 GB, Q6_K 6.9 GB, and Q4_K_M 5.3 GB; the Hugging Face file page reports approximately 17.9, 9.53, 7.36, and 5.63 GB respectively. The matching `mmproj-Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-BF16.gguf` is listed as 880 MB on the card and 922 MB in the file listing. Source: [HauhauCS 9B card, downloads and specs](https://huggingface.co/HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive#downloads), [9B GGUF/projector file listing](https://huggingface.co/HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive/tree/main).

The card’s `0/465` claim is not a reason to prefer the 9B model over the 4B for Theia: both cards make it. The model-level absence of refusals can be compatible with Theia’s intentionally direct persona, but it increases the importance of the existing application-owned validation and confirmation boundaries. Neither model card documents a Theia-style safety test, prompt set, tool-argument test, or strict structured-output rate.

## GGUF, projector, and quantization comparison

| Artifact | Current 4B | Candidate 9B | Implication |
| --- | ---: | ---: | --- |
| Dense parameters | 4B | 9B | Candidate has 2.25× the dense parameter count |
| Q4_K_M main GGUF | 2.71 GB displayed / 2.6 GB card | 5.63 GB displayed / 5.3 GB card | Candidate is about 2.08× the local main-model size |
| Q6_K main GGUF | 3.46 GB displayed / 3.3 GB card | 7.36 GB displayed / 6.9 GB card | 9B Q6_K is a poor first target on 16 GB |
| Q8_0 main GGUF | 4.48 GB displayed / 4.2 GB card | 9.53 GB displayed / 8.9 GB card | 9B Q8_0 leaves little room for cache/projector |
| BF16 main GGUF | 8.42 GB displayed / 7.9 GB card | 17.9 GB displayed / 17 GB card | 9B BF16 cannot fit entirely in 16 GB VRAM |
| Vision projector | 676 MB local / 645 MB card | 922 MB file listing / 880 MB card | Projectors are model-specific; do not reuse the 4B projector |
| MTP | Card says supported | Card says supported | Requires MTP tensors plus runtime configuration; not enabled by Theia today |

The rounded card values and Hugging Face file-page values differ because the card and file UI present different rounded representations. The local 4B file size is the stronger fact for Theia’s current installation; the 9B file-page values are the relevant download planning figures. The candidate 9B Q4_K_M plus projector is about 6.55 GB of model artifacts before llama.cpp runtime buffers and KV cache, versus about 3.38 GB for the locally installed 4B pair.

## llama.cpp and MTP compatibility

The HauhauCS cards recommend llama.cpp usage through the `-hf ...:Q4_K_M` path and say Qwen3.5 support landed recently, so a current build is recommended. Upstream llama.cpp’s server supports quantized GPU/CPU inference, OpenAI-compatible chat completions, multimodal input, schema-constrained JSON, function/tool use, and speculative decoding. Its multimodal documentation requires either `-hf` model discovery or an explicit `-m model.gguf --mmproj file.gguf` pair; projector offload is enabled by default. Sources: [HauhauCS 9B llama.cpp usage](https://huggingface.co/HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive#usage), [llama.cpp server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md), [llama.cpp multimodal documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md).

Upstream `qwen35.cpp` contains a dedicated Qwen3.5/3.6 MTP graph and loader path. It asserts that Qwen3.5 MTP has a next-token layer and currently supports one MTP block. The current local `llama-server` build `10451` explicitly exposes `--spec-type ... draft-mtp`, `--mmproj`, `--device`, `--gpu-layers`, and `--jinja` in its help output. Therefore the runtime is feature-compatible at the command-line level with Qwen3.5 MTP, but this is not a model-load proof: the candidate GGUF was not downloaded in this research pass, and the candidate card does not expose a separate MTP filename or tensor manifest. Sources: [llama.cpp Qwen3.5 loader/MTP source](https://github.com/ggml-org/llama.cpp/blob/master/src/models/qwen35.cpp), [llama.cpp speculative-decoding documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md), local `var/runtime/llama.cpp/b10451-cuda13/llama-server.exe --help` probe.

Theia’s `LlamaServer.build_command()` does not pass `--spec-type draft-mtp`, `--spec-draft-n-max`, or any other MTP option. Consequently, even if the 9B GGUF contains the advertised MTP tensors, Theia will not receive an MTP speculative-decoding benefit under its current launch contract. The candidate should first be tested as a normal Q4_K_M model. MTP can be a later measured optimization, not a reason to choose the 9B by default. Source: [Theia runtime command construction](../../src/private_search/ai/runtime.py).

## Implications for Theia’s strict JSON/tool workflow

The candidate’s larger 9B capacity may help on ambiguous natural-language requests, query refinement, coding, or multi-step explanations. That is an inference from parameter count and the shared Qwen3.5 base, not a card-proven result. The evidence is weaker for Theia’s highest-risk interface: strict action JSON. Both model cards advertise the same uncensoring outcome, and neither reports JSON-schema validity, tool-selection accuracy, false-positive tool calls, URL/username/email extraction, or behavior under Theia’s system prompt.

The existing action lane deliberately runs non-thinking classification at temperature 0 and constrains the output with a JSON schema. This reduces the value of the candidate’s advertised thinking capability in the exact path that decides whether a network or filesystem side effect is proposed. The 9B may still improve classification, but it could also increase latency and make malformed or over-elaborated outputs more expensive. The application validator and confirmation gate remain the source of safety; model size does not change that boundary.

For free-form answers, the 9B is more likely to be an improvement than for the tiny action envelope, but Theia still caps generation at 4,096 tokens and normally runs one local user. The larger model’s cost is therefore paid mostly in load time, decode speed, and VRAM rather than in a larger usable context window.

## 16 GB RTX 5080 Laptop GPU fit

The actual local probe reported an RTX 5080 Laptop GPU with 16,303 MiB total VRAM. The candidate’s Q4_K_M main file plus matching projector is approximately 6.55 GB by the Hugging Face file-page figures, leaving a large nominal remainder for buffers and an 8K KV cache. That makes Q4_K_M a plausible fit at Theia’s current context, but not a guarantee: llama.cpp’s allocation depends on model tensors, KV-cache types, projector offload, batch/ubatch settings, and backend behavior. The Q6_K and Q8_0 options consume substantially more of the budget; BF16 is not a full-VRAM option.

The model cards advertise 262K context and recommend at least 128K to preserve thinking capability. That recommendation is not compatible with Theia’s current 16 GB/interactive-latency target without a separate memory and quality study. Theia should retain 8K for the first A/B run. The 9B’s larger projector also matters for `describe_image`; loading both the candidate model and its projector is required, and the 4B projector is not a substitute. Sources: [HauhauCS 4B card](https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive), [HauhauCS 9B card](https://huggingface.co/HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive), [llama.cpp multimodal documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md), [Theia runtime defaults](../../.env.example).

## Decision matrix

| Criterion | 4B current | 9B candidate | Decision |
| --- | --- | --- | --- |
| Publisher evidence | Same uncensoring claims | Same uncensoring claims | No card-based quality winner |
| General reasoning/coding | Smaller baseline | Plausibly stronger from scale | Candidate gets an experimental edge |
| Strict JSON action validity | Existing working baseline | Unmeasured | Keep 4B until A/B evidence |
| Tool selection/query extraction | Existing working baseline | Unmeasured | Keep 4B until A/B evidence |
| Q4_K_M artifact | 2.71 GB local | 5.63 GB page figure | 9B costs about 2× the model storage |
| Vision pair | 676 MB local projector | 922 MB page figure | Candidate needs its own projector |
| MTP | Card-supported, not enabled | Card-supported, not enabled | No current speed advantage for either |
| 16 GB fit | Current installation | Q4 plausible at 8K; unverified | Candidate requires load/OOM measurement |
| Latency/throughput | Known baseline | Expected slower before MTP | 4B wins operational predictability |

## Safe evaluation gate before switching

Run both models with the same build, `CUDA0`, 8,192 context, 4,096 generation, batch/ubatch, Flash Attention, system prompts, and temperature settings. Test the candidate’s regular Q4_K_M first. Measure:

- first-pass and retry-success JSON validity;
- correct action choice for each supported action;
- false tool calls on ordinary conversation/coding prompts;
- query, URL, image-path, username, and email extraction accuracy;
- free-form answer quality and concise style adherence;
- startup time, first-token latency, tokens/second, peak VRAM, OOM/crash rate, and context usage;
- image-description quality with the matching 9B projector;
- MTP only in a separate run using the explicit `draft-mtp` flags, with acceptance rate and latency compared to regular Q4_K_M.

No application code should change as part of this comparison. The current evidence supports an opt-in benchmark, not a default model replacement.

## Primary sources

- [Theia model/runtime configuration](../../src/private_search/config.py)
- [Theia llama.cpp runtime](../../src/private_search/ai/runtime.py)
- [Theia action schema and prompts](../../src/private_search/ai/actions.py)
- [Theia architecture](../architecture.md)
- [HauhauCS Qwen3.5-4B model card](https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive)
- [HauhauCS Qwen3.5-9B model card](https://huggingface.co/HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive)
- [HauhauCS Qwen3.5-9B GGUF/projector file listing](https://huggingface.co/HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive/tree/main)
- [Official Qwen3.5-9B model card](https://huggingface.co/Qwen/Qwen3.5-9B)
- [Official Qwen3.5 Transformers documentation](https://huggingface.co/docs/transformers/model_doc/qwen3_5)
- [llama.cpp server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [llama.cpp multimodal documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md)
- [llama.cpp speculative decoding documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md)
- [llama.cpp Qwen3.5 model/MTP source](https://github.com/ggml-org/llama.cpp/blob/master/src/models/qwen35.cpp)
