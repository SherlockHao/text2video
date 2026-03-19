# Jimeng (即梦) Image/Video Generation Integration

Place your Jimeng API call scripts and configuration here.

## Expected Files

- `call_example.py` -- Your Jimeng API call script
- `config.json` or `.env` -- API key and endpoint config (DO NOT commit to git)

## Usage

This provider will be integrated into:
- `app/ai/providers/jimeng.py` -- Image generation (manga style)
- `app/ai/providers/seedance2.py` -- Video generation (high quality tier)

## Role in Pipeline

- **Module 3 (Visual Design)**: Character image gacha + storyboard shot image generation
- **Module 4 (Video Gen, High Quality)**: Seedance2 for high-quality video generation
