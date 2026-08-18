# Theia model-fit findings: DavidAU Qwen3.5-9B vs current model

Date: 2026-08-18  
Scope: repository configuration and source, the candidate and current Hugging Face model cards, official Qwen documentation, and upstream llama.cpp documentation/source.  
Constraint: research only; no application code or runtime assets were modified.

## Conclusion

**Do not replace Theia’s default model yet.** `DavidAU/Qwen3.5-9B-The-Defiant-Fable-Uncensored-Heretic-NEO-IMATRIX-MAX-MTP-GGUF` is a credible **capability-first challenger**: it keeps the same Qwen3.5 multimodal family and increases the dense model size from 4B to 9B, which could improve Theia’s free-form reasoning, coding, and borderline intent classification. However, the available evidence does not show that it improves Theia’s actual tool-selection or schema-validity workload, and its operational cost is materially higher.

For Theia as currently configured, the 4B model remains the better-known operational fit: its local GGUF is 2.71 GB, the app already points at it, the runtime already uses the Qwen3.5 architecture, and the app’s 8,192-token / 4,096-generation settings were chosen around it. The candidate’s regular Q4_K_M file is listed at 6.83 GB and its MTP Q4_K_M file at 6.98 GB—roughly 2.5–2.6× the current model file size—before KV cache, batching, and a model-specific vision projector are counted. Sources: [Theia configuration](../../src/private_search/config.py), [Theia runtime](../../src/private_search/ai/runtime.py), [current model card](https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive), [candidate file listing](https://huggingface.co/DavidAU/Qwen3.5-9B-The-Defiant-Fable-Uncensored-Heretic-NEO-IMATRIX-MAX-MTP-GGUF/tree/main).

The best decision is therefore: **keep the 4B default; benchmark the candidate as an opt-in replacement using the regular Q4_K_M first; only adopt it if it wins a Theia-specific evaluation set without unacceptable startup, VRAM, latency, or schema-validity regressions.**

## What Theia needs

Theia is a local AI-assisted terminal for search, media inspection, downloads, and OSINT. The model has two distinct jobs:

1. classify a request into a small, strict JSON action schema (`respond`, search, download, reverse-image, OSINT, or image description); and
2. produce concise free-form answers for conversation, coding, debugging, planning, writing, and technical analysis.

Python—not the model—owns URL/path validation, executable selection, confirmations, subprocess arguments, timeouts, and result parsing. The application retries malformed classifier JSON once and fails closed for explicit tool requests. This makes schema reliability, correct tool choice, concise responses, startup time, and predictable local resource use more important than a model-card benchmark score alone. Sources: [Theia action contract](../../src/private_search/ai/actions.py), [Theia orchestration](../../src/private_search/ai/chat.py), [Theia architecture](../architecture.md), [capability/performance research](2026-08-17-theia-capability-performance-research.md).

## Current model and runtime

The checked-in defaults are:

| Item | Current Theia setting |
| --- | --- |
| Model | `Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf` |
| Local model size observed | 2,707,513,696 bytes; SHA-256 `79E28ECACF84E75B6056CF4059636D435AA9EB67795780F7B7DBC7D32A962741` |
| Vision projector | 4B-specific `mmproj-...BF16.gguf`; local file observed at 675,568,768 bytes |
| Server | bundled `var/runtime/llama.cpp/b10451-cuda13/llama-server.exe` when present |
| Device | `CUDA0`, with `999` GPU layers by default |
| Context / generation | 8,192 / 4,096 tokens |
| Batch / physical batch | 2,048 / 512 |
| Flash Attention | on for the CUDA executable by default |
| Hardware observed | NVIDIA GeForce RTX 5080 Laptop GPU; 16,303 MiB total VRAM; 610.88 driver |

The 4B model card describes the same Qwen3.5 family traits as the candidate: 3:1 hybrid linear/full attention, native multimodality, MTP, and 262K native context. It also explicitly says that a separate `mmproj` is required for image/video input and that llama.cpp support is recent, so “it is Qwen3.5” is not enough to establish compatibility with every old binary. Sources: [configuration](../../src/private_search/config.py), [runtime settings and command construction](../../src/private_search/ai/runtime.py), [`.env.example`](../../.env.example), [current model card](https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive).

The repository’s prior hardware audit identifies the target as a Windows RTX 5080 Laptop GPU with 16 GB VRAM. A fresh local `nvidia-smi` probe also reported an NVIDIA GeForce RTX 5080 Laptop GPU with 16,303 MiB total VRAM, 15,841 MiB free, and driver 610.88 at inspection time. Source: [CUDA/Theia model audit](2026-08-16-cuda-theia-model-audit.md); local `nvidia-smi` probe on 2026-08-18.

## Candidate model evidence

The candidate is a publisher-created multi-stage fine-tune/merge of Qwen3.5-9B, distributed as Apache-2.0 metadata on Hugging Face. Its card claims improved general intelligence and instruction following, “fully uncensored” behavior, 256K context, vision support through one separate `mmproj`, and regular plus MTP GGUFs. The repository lists regular Q4_K_M at 6.83 GB, MTP Q4_K_M at 6.98 GB, Q5_K_M at 7.67–7.84 GB, Q8_0 at 10.5–10.7 GB, and a separate `mmproj-BF16.gguf` at 922 MB. Vision still requires obtaining and verifying that matching projector locally. Sources: [candidate model card](https://huggingface.co/DavidAU/Qwen3.5-9B-The-Defiant-Fable-Uncensored-Heretic-NEO-IMATRIX-MAX-MTP-GGUF), [candidate file listing](https://huggingface.co/DavidAU/Qwen3.5-9B-The-Defiant-Fable-Uncensored-Heretic-NEO-IMATRIX-MAX-MTP-GGUF/tree/main), [candidate projector](https://huggingface.co/DavidAU/Qwen3.5-9B-The-Defiant-Fable-Uncensored-Heretic-NEO-IMATRIX-MAX-MTP-GGUF/blob/main/mmproj-BF16.gguf).

The candidate card reports higher scores than its cited Qwen3.5-9B baseline on ARC-C, ARC-E, HellaSwag, OpenBookQA, PIQA, and Winogrande for the publisher’s listed tests. It also reports 6/100 refusals versus 100/100 for the original model. These are publisher claims: the card does not provide enough protocol detail to treat them as an independent, reproducible Theia evaluation, and they do not measure Theia’s strict action JSON, false-tool rate, confirmation behavior, or image-description quality. The uncensored behavior may suit an intentionally unfiltered assistant, but it also removes a layer of model-level friction; Theia’s actual safety boundary must remain the application validator and confirmation gate. Source: [candidate model card, benchmarks and de-censoring notes](https://huggingface.co/DavidAU/Qwen3.5-9B-The-Defiant-Fable-Uncensored-Heretic-NEO-IMATRIX-MAX-MTP-GGUF#performance).

Official Qwen documentation supports the underlying capability argument: Qwen3.5 is natively multimodal, uses a 3:1 hybrid attention stack, and has a vision tower reused from Qwen3-VL. The official 9B card demonstrates image-text input and documents MTP and tool-use serving paths in its serving guide. Those facts support family-level capability, but they do not validate this particular uncensored derivative or the old bundled llama.cpp build. Sources: [official Qwen3.5 Transformers documentation](https://huggingface.co/docs/transformers/model_doc/qwen3_5), [official Qwen3.5-9B card](https://huggingface.co/Qwen/Qwen3.5-9B).

## Runtime and hardware fit

### Compatibility

The candidate is plausible for the existing runtime because it is a Qwen3.5 GGUF and the current model already uses the Qwen3.5 architecture. That is an inference, not a verified load test. The candidate card itself recommends a current llama.cpp build, and the current bundled runtime is pinned to build `b10451`; the repository contains no checked-in compatibility test for this specific 9B file. A successful 4B load should not be treated as proof that 9B MTP tensors, the candidate chat template, and the candidate projector all work in that binary.

Upstream llama.cpp documents GGUF loading, OpenAI-compatible chat completions, schema-constrained JSON, multimodal `--mmproj`, and tool use. Its speculative-decoding documentation separately describes `draft-mtp`. Theia currently passes `--model`, optional `--mmproj`, `--device`, `--gpu-layers`, context, batch, and Flash Attention flags, but it does **not** pass `--spec-type draft-mtp` or any MTP-specific setting. Therefore the candidate’s MTP file is not an automatic speed upgrade in the current launch contract; its MTP head would need a recent compatible runtime and an explicit measured configuration. Sources: [llama-server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md), [llama.cpp multimodal documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md), [llama.cpp speculative decoding](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md), [Theia runtime command](../../src/private_search/ai/runtime.py).

### VRAM and latency

The candidate’s 6.83–6.98 GB model file is substantially larger than the current 2.71 GB file. A 16 GB GPU is likely to have enough room for the candidate at Theia’s current 8K context in some configurations, but that cannot be concluded from file size: llama.cpp also needs runtime buffers, KV cache, batch/ubatch workspace, and the vision projector when image input is enabled. The candidate’s advertised 256K context is not a realistic default for this 16 GB single-GPU target without a separate memory test; Theia should retain a conservative context until measurement proves otherwise.

The 9B model also has about 2.25× the dense parameter count of the current 4B model, so lower throughput and higher load time are the default expectation. The candidate publisher reports faster MTP results on an RTX 5090 under LM Studio, but also says performance varies by hardware/app and that regular GGUFs can be faster when MTP token acceptance is low or sampling temperature is high. That result should not be transplanted to Theia’s Windows CUDA build. Sources: [candidate MTP performance notes](https://huggingface.co/DavidAU/Qwen3.5-9B-The-Defiant-Fable-Uncensored-Heretic-NEO-IMATRIX-MAX-MTP-GGUF#speed), [llama.cpp GPU verification guidance](https://github.com/ggml-org/llama.cpp/blob/master/docs/development/token_generation_performance_tips.md), [Theia runtime defaults](../../.env.example).

### Vision fit

The candidate can preserve Theia’s image-description capability only with its matching 9B projector. The current 4B projector should not be assumed interchangeable: the model card describes the projector as a model-side vision encoder, and llama.cpp’s multimodal path expects the main GGUF and projector to be loaded together. The matching projector is published, but it still must be downloaded, paired, and load-tested. A text-only A/B test remains easier and lower risk than a full multimodal swap. Sources: [candidate vision notes](https://huggingface.co/DavidAU/Qwen3.5-9B-The-Defiant-Fable-Uncensored-Heretic-NEO-IMATRIX-MAX-MTP-GGUF#vision), [candidate projector](https://huggingface.co/DavidAU/Qwen3.5-9B-The-Defiant-Fable-Uncensored-Heretic-NEO-IMATRIX-MAX-MTP-GGUF/blob/main/mmproj-BF16.gguf), [llama.cpp multimodal documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md).

## Decision matrix

| Criterion | Candidate 9B | Current 4B | Finding |
| --- | --- | --- | --- |
| Free-form reasoning/coding | Likely better from scale and fine-tune claims | Lower-capacity baseline | Candidate advantage is plausible, not Theia-measured |
| Strict action JSON | Unknown | Existing working baseline | Benchmark first; model-card scores do not answer this |
| Tool choice / query extraction | Unknown | Existing working baseline | Candidate may help, but no direct evidence |
| Text-only llama.cpp integration | Plausible with a recent build | Already configured | Candidate needs a compatibility/load test |
| MTP speed | Potentially better | MTP not currently exploited either | Current launch command gives no automatic MTP benefit |
| Model footprint | 6.83–6.98 GB for Q4 variants | 2.71 GB local Q4 file | Candidate costs substantially more VRAM/storage |
| 16 GB target | Probably workable at conservative 8K, unproven | Documented target fit | Candidate needs OOM and latency measurement |
| Vision | Requires a separate matching 9B projector | 4B projector already configured | Candidate is not a drop-in multimodal replacement |
| Safety/friction | More explicitly uncensored | Also uncensored | Application gates remain mandatory; candidate has less model-level refusal friction |

## Recommended evaluation before any default change

Use the same Windows CUDA llama.cpp executable, `CUDA0`, Flash Attention setting, 8K context, batch/ubatch sizes, temperature, and Theia prompts for both models. Start with the candidate’s **regular Q4_K_M**, not MTP, because the current application does not enable MTP. Record:

- first-pass valid JSON rate and valid-after-retry rate;
- correct action selection, false tool calls, and query/field extraction;
- concise free-form answer quality on coding, debugging, planning, and research prompts;
- image-description quality only after obtaining and verifying the candidate’s matching projector;
- server startup time, first-token latency, steady decode tokens/second, peak VRAM, OOM/crash rate, and context usage;
- behavior with Theia’s actual system prompts, not a generic chat benchmark.

The existing research notes correctly recommend benchmark-driven model selection because a larger local model can improve reasoning while reducing speed and context headroom. No labeled Theia evaluation set is currently checked into the repository, so the first useful artifact should be a private held-out prompt set and a repeatable measurement script—not an automatic default swap. Source: [capability/performance research](2026-08-17-theia-capability-performance-research.md).

## Primary sources

- [Theia README](../../README.md)
- [Theia model/runtime configuration](../../src/private_search/config.py)
- [Theia llama.cpp runtime](../../src/private_search/ai/runtime.py)
- [Theia action schema and prompts](../../src/private_search/ai/actions.py)
- [DavidAU candidate model card](https://huggingface.co/DavidAU/Qwen3.5-9B-The-Defiant-Fable-Uncensored-Heretic-NEO-IMATRIX-MAX-MTP-GGUF)
- [DavidAU candidate GGUF file listing](https://huggingface.co/DavidAU/Qwen3.5-9B-The-Defiant-Fable-Uncensored-Heretic-NEO-IMATRIX-MAX-MTP-GGUF/tree/main)
- [HauhauCS current model card](https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive)
- [Official Qwen3.5-9B model card](https://huggingface.co/Qwen/Qwen3.5-9B)
- [Official Qwen3.5 Transformers documentation](https://huggingface.co/docs/transformers/model_doc/qwen3_5)
- [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [llama.cpp multimodal documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md)
- [llama.cpp speculative decoding documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md)
- [llama.cpp GPU verification guidance](https://github.com/ggml-org/llama.cpp/blob/master/docs/development/token_generation_performance_tips.md)
