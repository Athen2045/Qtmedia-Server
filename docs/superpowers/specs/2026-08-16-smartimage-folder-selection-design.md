# SmartImage Folder Selection Design

## Goal

Make reverse-image search work from the project `image` folder by default. A
user asking Theia for a reverse search should not need to provide a file path.
The existing `/image PATH` command is removed because folder discovery and
selection replace it.

## Interaction contract

When the user requests a reverse image search, the application resolves the
image before requesting confirmation:

1. Recursively scan `<project-root>/image`.
2. Include only `.jpg`, `.jpeg`, `.png`, `.webp`, `.gif`, `.bmp`, and `.tiff`
   files, case-insensitively.
3. If there are no matches, explain that the image folder contains no supported
   images and do not request confirmation.
4. If there is one match, select it automatically.
5. If there are multiple matches, show a numbered Rich selection prompt. The
   prompt displays the relative path and file metadata needed to distinguish
   files. The user may cancel without submitting an image.
6. After selection, show the existing confirmation request with the exact
   selected path.
7. Invoke SmartImage only after confirmation.

The phrase detector is application-side and case-insensitive: a request must
contain both `reverse` and `search`. The model remains responsible for
producing the validated `reverse_image_search` action, while the application
supplies the resolved image path. An explicit active-image path is removed from
the chat interface and action context.

## Kitty preview

When Kitty graphics support is available, preview the selected candidates
using the existing terminal preview capability before the selection prompt.
When Kitty is unavailable, continue with a text-only numbered list. Preview
failure is non-fatal and must never prevent selection or SmartImage execution.

## Architecture

- Add a small image-folder resolver responsible only for recursive discovery,
  stable ordering, supported-extension filtering, and selection metadata.
- Keep SmartImage subprocess execution unchanged except that its validated
  `image_path` comes from the resolver.
- Move reverse-search selection into the chat UI/tool boundary so confirmation
  occurs after selection and before external upload.
- Remove `/image` and `/clear-image` command handling, help text, active-image
  state, and tests that depend on them.
- Preserve the existing confirmation service, SmartImage upload-provider
  configuration, timeout handling, and delimited result rendering.

## Failure and privacy behavior

- No image is uploaded when the folder is empty or the user cancels selection.
- The selected local path is shown before confirmation.
- The resolver does not inspect image contents or ask the model to choose a
  file.
- Kitty is optional; absence or failure falls back to text.
- SmartImage remains confirmation-gated because it uploads the selected image
  to an external upload service.

## Testing

Add tests for:

- recursive discovery and extension filtering;
- deterministic ordering;
- zero, one, and multiple image outcomes;
- cancellation before confirmation;
- Kitty-unavailable fallback;
- confirmation receiving the selected exact path;
- removal of `/image` and `/clear-image` commands;
- existing SmartImage subprocess behavior and full-suite regression checks.

## Out of scope

- Changing SmartImage search engines or result ranking;
- silently switching upload providers;
- image content classification or model-based file selection;
- GUI image browsing.
