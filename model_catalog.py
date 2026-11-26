"""Curated model download catalog for the vLLM and LM Studio installer cards.

Each entry is a model the user can download with one click:
  - vLLM: safetensors from a Hugging Face repo (served by `vllm serve`).
  - LM Studio: GGUF from a Hugging Face repo (loaded by `lms load`).

`repo` is the HF repo name. For LM Studio, `file` is the specific GGUF file
inside the repo (quantization) — it may be a glob (e.g. `Qwen3.8-Flash-Next-Q4_0*`
for a multi-part GGUF). For vLLM, `file` is optional (downloads the whole repo).
`size` is the approximate download size. `vram` is the VRAM the model fits in
(16/24/32 GB) — used to group the 16/24/32 GB versions of a model.

All models are the newest releases (Qwen 3.5 / 3.8, Gemma 4), aiming for the
Q4 / 4-bit variants (AWQ-4bit / INT4 / NVFP4 / MXFP4 for vLLM; Q4_K_M / Q4_0
for LM Studio). The Qwen3.8-27B family has 16/24/32 GB versions.
"""

# vLLM models (safetensors). The Qwen3.8-27B family has 16/24/32 GB versions.
VLLM_MODELS = [
    {'slug': 'qwen35-9b',        'name': 'Qwen3.5 9B (BF16)',            'repo': 'Qwen/Qwen3.5-9B',                'size': '~10 GB',  'vram': None},
    {'slug': 'qwen35-27b',       'name': 'Qwen3.5 27B (AWQ 4-bit)', 'repo': 'cyankiwi/Qwen3.5-27B-AWQ-4bit',  'size': '~16 GB',  'vram': None},
    {'slug': 'qwen38-27b-16',    'name': 'Qwen3.8 27B (16 GB, INT4)',   'repo': 'RedHatAI/Qwen3.8-27B-INT4',        'size': '~14 GB',  'vram': 16},
    {'slug': 'qwen38-27b-24',    'name': 'Qwen3.8 27B (24 GB, NVFP4)',   'repo': 'nvidia/Qwen3.8-27B-NVFP4-QAD',     'size': '~16 GB',  'vram': 24},
    {'slug': 'qwen38-27b-32',    'name': 'Qwen3.8 27B (32 GB, FP8)',   'repo': 'Qwen/Qwen3.8-27B-FP8',            'size': '~27 GB',  'vram': 32},
    {'slug': 'qwen38-flashnext', 'name': 'Qwen3.8 Flash-Next (MXFP4)', 'repo': 'amd/Qwen3.8-Flash-Next-Quark-MXFP4', 'size': '~20 GB', 'vram': None},
    {'slug': 'qwen35-35b-a3b',   'name': 'Qwen3.5 35B-A3B (MoE, AWQ 4-bit)', 'repo': 'cyankiwi/Qwen3.5-35B-A3B-AWQ-4bit', 'size': '~20 GB', 'vram': None},
    {'slug': 'gemma4-12b',       'name': 'Gemma 4 12B (W4A16)',   'repo': 'google/gemma-4-12B-it-qat-w4a16-ct', 'size': '~8 GB',  'vram': None},
    {'slug': 'gemma4-26b-a4b',   'name': 'Gemma 4 26B-A4B (MoE, NVFP4)', 'repo': 'nvidia/Gemma-4-26B-A4B-NVFP4', 'size': '~16 GB', 'vram': None},
    {'slug': 'gemma4-31b',       'name': 'Gemma 4 31B (NVFP4)',   'repo': 'nvidia/Gemma-4-31B-IT-NVFP4',      'size': '~20 GB',  'vram': None},
]

# LM Studio models (GGUF). The Qwen3.8-27B family has 16/24/32 GB versions.
LMSTUDIO_MODELS = [
    {'slug': 'qwen35-9b',        'name': 'Qwen3.5 9B (Q4_K_M)',            'repo': 'unsloth/Qwen3.5-9B-GGUF',         'file': 'Qwen3.5-9B-Q4_K_M.gguf',         'size': '~5.5 GB',  'vram': None},
    {'slug': 'qwen35-27b',       'name': 'Qwen3.5 27B (Q4_K_M)',           'repo': 'unsloth/Qwen3.5-27B-GGUF',        'file': 'Qwen3.5-27B-Q4_K_M.gguf',        'size': '~16 GB',   'vram': None},
    {'slug': 'qwen38-27b-16',    'name': 'Qwen3.8 27B (16 GB, Q3_K_M)',   'repo': 'bartowski/Qwen3.8-27B-GGUF',      'file': 'Qwen3.8-27B-Q3_K_M.gguf',        'size': '~16 GB',   'vram': 16},
    {'slug': 'qwen38-27b-24',    'name': 'Qwen3.8 27B (24 GB, Q4_K_M)',   'repo': 'bartowski/Qwen3.8-27B-GGUF',      'file': 'Qwen3.8-27B-Q4_K_M.gguf',        'size': '~20 GB',   'vram': 24},
    {'slug': 'qwen38-27b-32',    'name': 'Qwen3.8 27B (32 GB, Q8_0)',   'repo': 'bartowski/Qwen3.8-27B-GGUF',      'file': 'Qwen3.8-27B-Q8_0.gguf',          'size': '~32 GB',   'vram': 32},
    {'slug': 'qwen38-flashnext', 'name': 'Qwen3.8 Flash-Next (Q4_0)',    'repo': 'bartowski/Qwen3.8-Flash-Next-GGUF', 'file': 'Qwen3.8-Flash-Next-Q4_0*',      'size': '~12 GB',   'vram': None},
    {'slug': 'qwen35-35b-a3b',   'name': 'Qwen3.5 35B-A3B (MoE, Q4_K_M)', 'repo': 'bartowski/Qwen_Qwen3.5-35B-A3B-GGUF', 'file': 'Qwen_Qwen3.5-35B-A3B-Q4_K_M.gguf',   'size': '~20 GB',   'vram': None},
    {'slug': 'gemma4-12b',       'name': 'Gemma 4 12B (Q4_0)',           'repo': 'google/gemma-4-12B-it-qat-q4_0-gguf', 'file': 'gemma-4-12b-it-qat-q4_0.gguf',  'size': '~8 GB',    'vram': None},
    {'slug': 'gemma4-26b-a4b',   'name': 'Gemma 4 26B-A4B (MoE, Q4_0)', 'repo': 'google/gemma-4-26B-A4B-it-qat-q4_0-gguf', 'file': 'gemma-4-26B_q4_0-it.gguf',  'size': '~16 GB',   'vram': None},
    {'slug': 'gemma4-31b',       'name': 'Gemma 4 31B (Q4_0)',           'repo': 'google/gemma-4-31B-it-qat-q4_0-gguf', 'file': 'gemma-4-31B_q4_0-it.gguf',     'size': '~20 GB',   'vram': None},
]
