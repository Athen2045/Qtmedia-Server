# CUDA, llama.cpp, and HauhauCS model audit

Date: 2026-08-16  
Scope: official NVIDIA CUDA/Windows documentation, the upstream `ggml-org/llama.cpp` repository, and the public Hugging Face repository/model card for `HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive`.  
Constraint: research only; no production code was edited.

## Executive summary

- NVIDIA identifies the GeForce RTX 5080 Laptop GPU as a Blackwell laptop GPU with 7,680 CUDA cores and 16 GB of GDDR7. CUDA 12.8 documents Blackwell compiler/library support and packages a Windows driver at version 570.65 or later for the CUDA 12.8 GA toolkit. NVIDIA’s generic CUDA 12.x minor-version compatibility floor is lower (`528.33` on Windows), but that floor should not be treated as the Blackwell feature-support floor.
- The public NVIDIA compute-capability table lists the desktop GeForce RTX 5080 as compute capability 12.0, but does not separately list the RTX 5080 Laptop GPU. The laptop SKU’s exact reported compute capability should therefore be obtained from the actual machine/driver before hard-coding a CUDA architecture in a build.
- Upstream llama.cpp’s documented CUDA path is CMake with `-DGGML_CUDA=ON`; runtime GPU use is controlled and verified with `--list-devices`, `--device`, and `-ngl`/`--n-gpu-layers`. The project also documents non-native builds and explicit `CMAKE_CUDA_ARCHITECTURES` overrides.
- The HauhauCS repository declares `apache-2.0` in Hugging Face metadata and describes the model as an uncensored/aggressive refusal-removal derivative of Qwen3.5-4B. Its card reports “0/465 refusals,” but does not publish the test prompts, protocol, baseline, training data, training method, safety evaluation, or a model-specific safety-training description. The main repository file listing observed on the audit date shows a README and GGUF artifacts, not a separate `LICENSE` file; the metadata declaration should be verified against the upstream Qwen license chain before redistribution.

## Evidence classification

This report uses **documented fact** for statements directly present in a primary source. **Unknown** means the consulted primary sources do not establish the point. **Inference** is an operational conclusion drawn from documented facts and is labeled as such.

## 1. NVIDIA RTX 5080 Laptop GPU, CUDA, and Windows

### Documented facts

NVIDIA’s GeForce RTX 50 Series laptop page identifies the laptop family as powered by the Blackwell architecture. Its specification table lists the GeForce RTX 5080 Laptop GPU with 7,680 NVIDIA CUDA cores, 16 GB GDDR7 memory, and 896 GB/s memory bandwidth. NVIDIA’s launch announcement repeats the 7,680-CUDA-core and 16-GB figures. Sources: [GeForce RTX 50 Series laptops](https://www.nvidia.com/en-us/geforce/laptops/50-series/), [NVIDIA laptop announcement](https://www.nvidia.com/en-us/geforce/news/rtx-50-series-graphics-cards-gpu-laptop-announcements/).

NVIDIA’s CUDA compute-capability table lists the **desktop** GeForce RTX 5080 under compute capability 12.0, alongside other consumer Blackwell cards. That table does not contain a separate row for “GeForce RTX 5080 Laptop GPU.” Source: [NVIDIA CUDA GPU Compute Capability](https://developer.nvidia.com/cuda/gpus).

CUDA 12.8 release notes document compiler support for Blackwell targets `SM_100`, `SM_101`, and `SM_120`. The same release notes say that CUDA 12.8’s cuBLAS supports Blackwell and describe Blackwell GeForce GPUs as compute capability 12.x. They also document initial CUDA-in-Graphics support on Windows x64 for Blackwell GeForce-class GPUs. Source: [CUDA 12.8 release notes](https://docs.nvidia.com/cuda/archive/12.8.0/cuda-toolkit-release-notes/index.html), especially the driver table and Blackwell/cuBLAS notes.

For CUDA 12.8 GA, NVIDIA’s toolkit-driver table lists a packaged minimum Windows x86_64 driver of `570.65` (Linux is listed separately as `570.26`). NVIDIA also states that later drivers remain backward compatible with applications built against the toolkit. The broader CUDA 12.x minor-version compatibility table lists a Windows floor of `528.33`, with a warning that compatibility mode can have feature limitations. Sources: [CUDA 12.8 release notes](https://docs.nvidia.com/cuda/archive/12.8.0/cuda-toolkit-release-notes/index.html), [CUDA minor-version compatibility](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html).

NVIDIA’s CUDA 12.8 Windows installation guide lists these supported Microsoft operating systems: Windows 11 24H2, Windows 11 22H2-SV2, Windows 11 23H2, Windows 10 22H2, Windows Server 2022, and Windows Server 2025. It lists Visual Studio 2022 17.x/MSVC 193x and Visual Studio 2019 16.x/MSVC 192x as supported native x86_64 compiler combinations. The guide says both the NVIDIA driver and toolkit must be installed for CUDA to function. Source: [CUDA 12.8 Installation Guide for Microsoft Windows](https://docs.nvidia.com/cuda/archive/12.8.0/cuda-installation-guide-microsoft-windows/index.html).

NVIDIA’s Blackwell compatibility guide says applications built with CUDA Toolkit 12.8 or earlier can run on Blackwell when they include compatible PTX, and that CUDA 12.8 builds can include native cubin or PTX. It recommends testing an existing binary with `CUDA_FORCE_PTX_JIT=1`; the variable must be unset after the test. Source: [Blackwell Architecture Compatibility Guide](https://docs.nvidia.com/cuda/archive/12.8.0/blackwell-compatibility-guide/index.html).

### Operational inference

For a Windows RTX 5080 Laptop GPU, a conservative documented baseline is:

1. Use a Windows release listed by the CUDA 12.8 Windows guide.
2. Use an NVIDIA Windows driver at least `570.65` when targeting CUDA 12.8 GA and Blackwell features; a later compatible driver is preferable.
3. Install the CUDA Toolkit and a supported MSVC/CMake build environment if compiling CUDA software.
4. Query the actual GPU’s reported compute capability before selecting a fixed `CMAKE_CUDA_ARCHITECTURES` value.

The `570.65` recommendation is an inference from NVIDIA’s CUDA 12.8 toolkit-driver table plus its Blackwell support notes. It is stronger and more relevant for Blackwell than relying only on the generic `528.33` CUDA 12.x minor-compatibility floor.

### Unknowns and limits

- NVIDIA’s public compute-capability table does not separately identify the RTX 5080 Laptop GPU. The desktop RTX 5080’s `12.0` entry is not, by itself, a formal laptop-SKU entry.
- The consulted NVIDIA pages do not provide a laptop-specific minimum driver number tied to every OEM BIOS, TGP configuration, or Windows driver packaging choice.
- This report does not inspect the target machine’s installed driver, Windows build, `nvidia-smi` output, CUDA Toolkit version, or actual runtime capability.

## 2. Official llama.cpp CUDA build and runtime guidance

### Documented build guidance

Upstream llama.cpp says its CUDA backend provides GPU acceleration using an NVIDIA GPU and requires the CUDA Toolkit. Its basic CMake build is:

```powershell
cmake -B build -DGGML_CUDA=ON
cmake --build build --config Release
```

Source: [llama.cpp build documentation, CUDA section](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md#cuda).

For Windows generally, the same build document recommends Visual Studio 2022 with Desktop development with C++, CMake tools, Git for Windows, and a Developer Command Prompt or PowerShell for Visual Studio. Source: [llama.cpp build documentation, Windows notes](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md#cpu-build).

The default build targets hardware connected at build time. For a binary intended to cover all CUDA GPUs, llama.cpp documents disabling native CPU/GPU detection with:

```powershell
cmake -B build -DGGML_CUDA=ON -DGGML_NATIVE=OFF
```

The project warns that this can require JIT compilation. If automatic GPU detection fails, it documents supplying an explicit semicolon-separated `CMAKE_CUDA_ARCHITECTURES` list, after obtaining the device’s compute capability from NVIDIA’s table. Source: [llama.cpp non-native and architecture override guidance](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md#non-native-builds).

### Documented runtime guidance

llama.cpp documents these runtime controls:

- `--list-devices` lists backend devices.
- `--device` selects the runtime backend/device; `--device none` can disable GPU acceleration.
- `-ngl N` / `--n-gpu-layers N` requests GPU layer offload. The performance guide says a very large value can be used to offload the maximum possible number of layers, even if fewer fit.
- `CUDA_VISIBLE_DEVICES` can restrict which CUDA device is visible.
- CUDA runtime environment variables can be set before launching the server or CLI.

Sources: [llama.cpp backend/runtime notes](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md#notes-about-gpu-accelerated-backends), [llama.cpp CUDA build/runtime environment notes](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md#runtime-cuda-environmental-variables), [llama.cpp GPU verification guide](https://github.com/ggml-org/llama.cpp/blob/master/docs/development/token_generation_performance_tips.md#verifying-that-the-model-is-running-on-the-gpu-with-cuda).

The official GPU verification guide says to look for diagnostic lines showing CUDA/cuBLAS layer offload and total VRAM usage, such as “offloading ... layers to GPU.” Seeing those lines is the project’s documented indication that the GPU is being used. Source: [llama.cpp token-generation performance tips](https://github.com/ggml-org/llama.cpp/blob/master/docs/development/token_generation_performance_tips.md).

### Practical verification sequence (inference)

After installing the NVIDIA driver, CUDA Toolkit, and a CUDA-enabled llama.cpp build, a low-risk validation sequence is:

```powershell
llama-cli.exe --list-devices
llama-cli.exe -m path\to\model.gguf -ngl 200000 -p "Reply with one short sentence." -n 32
```

The first command follows llama.cpp’s documented device-listing control. The second uses the project’s documented large `-ngl` verification pattern; the resulting startup diagnostics should be inspected for CUDA/cuBLAS offload and VRAM use. This does not establish performance, stability, or safe context limits.

### Unknowns and limits

- llama.cpp does not promise that every current commit supports every newly released model architecture; the HauhauCS card itself says llama.cpp support for this architecture landed recently and recommends a recent build.
- The upstream build guide does not give a single RTX 5080 Laptop-specific `CMAKE_CUDA_ARCHITECTURES` value. Use the actual device query rather than assuming the desktop table applies.
- The official llama.cpp documents do not provide a benchmark or a guaranteed context length for this model on an RTX 5080 Laptop GPU.
- A CUDA-enabled build alone does not prove that a given invocation offloads layers; the project requires runtime diagnostics to verify actual use.

## 3. HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive

### Documented repository and model-card facts

The public Hugging Face repository is a GGUF model repository. Its model card identifies the model as “Qwen3.5-4B uncensored by HauhauCS,” says it is based on Qwen3.5-4B, and describes an “Aggressive Variant” with more thorough refusal removal. The card lists 4B dense parameters, 32 layers, a hybrid Gated DeltaNet/full-attention architecture, a native 262K context, multimodal text/image/video support, and MTP support. Source: [HauhauCS model card](https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive).

The repository lists these main artifacts and approximate sizes: BF16 GGUF 7.9 GB, Q8_0 4.2 GB, Q6_K 3.3 GB, Q4_K_M 2.6 GB, and a 645 MB BF16 vision encoder (`mmproj`). The card says the projector is required alongside the main GGUF for image/video inputs. Source: [HauhauCS model-card downloads and repository file listing](https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive/tree/main).

The card provides llama.cpp usage through Hugging Face model identifiers, including Windows `winget install llama.cpp`, pre-built binaries, and building llama.cpp from source. Those examples do not themselves specify a CUDA build; GPU acceleration still depends on obtaining a CUDA-enabled binary or compiling with llama.cpp’s `GGML_CUDA=ON` option. Sources: [HauhauCS llama.cpp usage instructions](https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive/blob/main/README.md), [llama.cpp CUDA build instructions](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md#cuda).

### Safety and alignment documentation

The model card claims “0/465 refusals,” calls the model fully uncensored, says there were no changes to datasets or capabilities, and describes stronger refusal removal in the aggressive variant. It also says the model will not refuse prompts, while noting that it may append disclaimers inherited from the base model. These are claims made by the publisher; they are not an independently reproducible safety evaluation in the repository. Source: [HauhauCS model card, About and Aggressive Variant](https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive#aggressive-variant).

The HauhauCS card does **not** document a safety-training method, safety dataset, preference/alignment procedure, refusal-removal algorithm, evaluation prompt set, evaluator, baseline comparison, harmful-content taxonomy, or mitigation guidance. The public card has no dedicated safety section. This is an absence-of-documentation finding, not proof that no such work occurred.

The upstream Qwen3.5-4B card documents the base model’s “Pre-training & Post-training” stages and describes scaled reinforcement learning, but that is documentation for the upstream model, not evidence that the HauhauCS derivative retained, changed, or replaced any particular safety stage. Source: [official Qwen3.5-4B model card](https://huggingface.co/Qwen/Qwen3.5-4B).

### License and provenance

The HauhauCS Hugging Face metadata declares `apache-2.0`, both in the repository page and in the README front matter. Source: [HauhauCS repository metadata and README](https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive/blob/main/README.md).

The repository’s main-branch file listing observed on 2026-08-16 shows `.gitattributes`, the README, and GGUF artifacts; it does not show a separate `LICENSE` file. The upstream Qwen3.5-4B repository separately declares Apache-2.0 and includes a `LICENSE` file in its own repository listing. Sources: [HauhauCS file listing](https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive/tree/main), [Qwen3.5-4B file listing](https://huggingface.co/Qwen/Qwen3.5-4B/tree/main).

The documented fact is therefore: **the derivative repository declares Apache-2.0 metadata**. The following remain unknown without a legal/provenance review: whether the derivative’s distribution includes all required notices, whether the GGUF conversion preserves all upstream obligations, and whether any additional data/model components have separate terms. This report is not a legal opinion.

### Operational inference for this project

The Q4_K_M artifact is listed at about 2.71 GB in the repository UI, while the laptop GPU is documented at 16 GB. It is plausible that the quantized weights can fit in VRAM, but full-context memory, KV cache, multimodal projector memory, CUDA workspace, and other runtime allocations are not specified by these facts. Do not infer that 128K context is practical merely because the model card recommends maintaining at least 128K context for thinking capabilities; measure it with the exact llama.cpp build and prompt shape.

Because the publisher explicitly describes refusal removal and does not publish a safety methodology, any application integration should treat the model as an untrusted text generator. Model output should not directly authorize network access, filesystem writes, subprocesses, or external OSINT actions. That is an engineering control recommendation based on the documented model-card behavior, not a claim about the model’s intrinsic capabilities.

## Consolidated unknowns requiring validation

| Question | Status from primary sources | Required validation |
|---|---|---|
| Exact RTX 5080 Laptop compute capability | Not separately listed by NVIDIA’s public table | Query the actual device/driver and record the result |
| Installed Windows/NVIDIA/CUDA versions | Not inspected in this research | Record Windows build, `nvidia-smi`, `nvcc --version`, and driver branch |
| CUDA-enabled llama.cpp binary | Not established by the model card | Build or obtain a pinned binary and run `--list-devices` |
| Actual GPU offload | Not established by build flags alone | Inspect llama.cpp startup diagnostics for CUDA/cuBLAS offload |
| Model safety training/evaluation | Not documented in the HauhauCS card | Obtain publisher methodology or treat safety claims as unverified |
| Complete license notices/provenance | Metadata says Apache-2.0; separate derivative LICENSE not listed | Preserve upstream notices and review the full artifact/license chain |

## Primary sources consulted

- [NVIDIA GeForce RTX 50 Series Gaming Laptops](https://www.nvidia.com/en-us/geforce/laptops/50-series/)
- [NVIDIA CUDA GPU Compute Capability](https://developer.nvidia.com/cuda/gpus)
- [CUDA 12.8 Toolkit Release Notes](https://docs.nvidia.com/cuda/archive/12.8.0/cuda-toolkit-release-notes/index.html)
- [CUDA 12.8 Installation Guide for Microsoft Windows](https://docs.nvidia.com/cuda/archive/12.8.0/cuda-installation-guide-microsoft-windows/index.html)
- [CUDA Minor-Version Compatibility](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html)
- [Blackwell Architecture Compatibility Guide](https://docs.nvidia.com/cuda/archive/12.8.0/blackwell-compatibility-guide/index.html)
- [llama.cpp build documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md)
- [llama.cpp CUDA GPU verification guidance](https://github.com/ggml-org/llama.cpp/blob/master/docs/development/token_generation_performance_tips.md)
- [HauhauCS model card](https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive)
- [HauhauCS README and metadata](https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive/blob/main/README.md)
- [HauhauCS repository file listing](https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive/tree/main)
- [Official Qwen3.5-4B model card and repository](https://huggingface.co/Qwen/Qwen3.5-4B)
