# Theia Personality and Safeguard Audit

Date: 2026-08-16

## Scope

This audit separates the downloaded model's documented behavior from the
application-level persona, action validation, confirmation, and runtime
controls.

## Model-level findings

The model card labels `HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive` as
uncensored and claims `0/465 refusals`. It says the aggressive variant has
stronger refusal removal and “will not refuse prompts,” while noting that it
may still append short disclaimers. The card does not provide an independent
or reproducible safety-evaluation methodology for those claims, so they should
be treated as publisher claims rather than a guarantee.

Source: [HauhauCS model card](https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive#about)

The model card lists Apache-2.0 metadata and describes the GGUF quantizations,
including the Q4_K_M model currently configured by this project. The local
application adds its own system prompt and tool boundary; those changes do
not retrain or alter the model weights.

Source: [HauhauCS model card](https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive#downloads)

## Theia persona currently applied

The application prompt defines Theia as:

- sharp, cheeky, and economical with words;
- a guide rather than a companion, focused on helping the user think and act faster;
- dryly witty and confident without flirtation;
- concise, plain, and free of emojis or filler acknowledgments;
- guided by a hacker/security-analyst mindset focused on attack surfaces,
  failure modes, weak links, and uncertainty;
- open to unconventional approaches when they are workable;
- explicitly non-flirtatious, non-romantic, non-intimate, and non-adult-coded;
- prohibited from sexualizing minors, coercion, exploitation, or non-consensual activity;
- prohibited from revealing hidden chain-of-thought.

The prompt also requires a JSON action object, forbids Markdown and shell
commands, and tells the model to use `respond` for ordinary conversation and
the defined tool actions for external work.

Source: [`src/private_search/ai/actions.py`](../../src/private_search/ai/actions.py)

## Application-enforced restrictions

These controls are enforced outside the model's prose generation:

1. The action schema rejects unknown fields and allows only the fixed action
   names: respond, refine_search, download_media, reverse_image_search,
   username_osint, and describe_image.
2. Action-specific fields are validated. Downloads must use HTTP(S) URLs;
   search, image, and username actions must provide their required values.
3. Every external search, download, reverse-image, or username action passes
   through a confirmation service before execution.
4. Tool execution uses fixed Python adapters. The model cannot choose an
   executable, construct a shell command, or directly call arbitrary Python.
5. The local model client accepts only loopback llama.cpp endpoints, and the
   server validates a loopback host, starts with `shell=False`, waits for a
   health check, and stops its child process when the session ends.
6. Search source routing is derived from the user's original wording. The
   model no longer controls include filters, exclusions, or minimum-view
   thresholds.

Sources: [`actions.py`](../../src/private_search/ai/actions.py),
[`client.py`](../../src/private_search/ai/client.py),
[`runtime.py`](../../src/private_search/ai/runtime.py), and
[`tools.py`](../../src/private_search/ai/tools.py)

## What is not enforced

- The app does not provide a guaranteed text-content moderation layer for
  ordinary assistant replies.
- The persona prompt is instruction-level guidance and can be ignored or
  inconsistently followed by the model.
- “Uncensored” does not mean unrestricted tool access; tools remain bounded by
  the application. It also does not guarantee factual, legal, ethical, or
  safe output.
- Reverse image search, username OSINT, and image-description adapters are
  unavailable until their configured integrations pass preflight; the action
  names alone do not grant access.

## Operational conclusion

Theia can express dry, cheeky, security-minded conversation within the
application's persona prompt, but her practical capabilities are determined
by the fixed tool registry and confirmation layer. The model card supports the
conclusion that this derivative is intentionally refusal-reduced; it does not
support a claim that the model is safe or intrinsically restricted.
