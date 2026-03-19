# Qwen 3.5-Plus LLM Integration

Place your Qwen API call scripts and API key configuration here.

## Expected Files

- `call_example.py` -- Your Qwen API call script
- `config.json` or `.env` -- API key and endpoint config (DO NOT commit to git)

## Usage

This provider will be integrated into `app/ai/providers/qwen.py` as the primary LLM for script breakdown (storyboard generation).

## Role in Pipeline

- **Module 2 (Script Breakdown)**: Parse novel text into storyboard JSON with scene descriptions, image prompts, and narration text
- Shot count formula: Normal quality 8-12 shots/min, High quality 15-20 shots/min
