# Yayceslav Telegram stickers

This folder contains the preparation workflow for static Telegram stickers.

## What the tool does

`prepare_sticker.py` converts finished artwork to a Telegram-ready static sticker:

- output canvas: exactly `512 x 512` px;
- transparent background is preserved;
- fully transparent outer margins are trimmed before fitting;
- artwork is centered without changing aspect ratio;
- default artwork box is `480 x 480` px, leaving a small transparent safety margin;
- default output is WEBP;
- output size is checked against the 512 KB static-sticker limit;
- if a WEBP is too large, the script reduces WEBP quality until it fits the limit.

The script accepts PNG, WEBP, JPG, and JPEG as source images. For the actual sticker artwork, transparent PNG/WEBP sources are preferred.

## Folder layout

Put finished source artwork in:

```text
stickers/source/
```

Generated Telegram-ready files go to:

```text
stickers/output/
```

Do not edit generated files by hand; regenerate them from the sources.

## Install

From the repository root:

```bash
python -m pip install -r stickers/requirements.txt
```

## Prepare all stickers

```bash
python stickers/prepare_sticker.py stickers/source
```

The default result is WEBP in `stickers/output/`.

## Prepare one sticker

```bash
python stickers/prepare_sticker.py stickers/source/yayceslav_approves.png
```

## PNG output instead

```bash
python stickers/prepare_sticker.py stickers/source --format png
```

## Change artwork size on the canvas

Normally keep the default 480 px. If a particular design needs more or less breathing room:

```bash
python stickers/prepare_sticker.py stickers/source --content-size 470
```

Valid range is 1..512.

## Before uploading to Telegram

For every generated sticker, check visually that:

1. no text or outline is cut off;
2. the artwork is readable at chat size;
3. transparency looks correct;
4. the generated file is 512 x 512;
5. the file is no larger than 512 KB.

Emoji mapping and upload to the Telegram sticker pack are the next step after the artwork set is ready.
