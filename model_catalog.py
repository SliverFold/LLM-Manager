"""Curated model download catalog for the vLLM and LM Studio installer cards.

Each entry is a model the user can download with one click:
  - vLLM: safetensors from a Hugging Face repo (served by `vllm serve`).
  - LM Studio: GGUF from a Hugging Face repo (loaded by `lms load`).

`repo` is the HF repo name. For LM Studio, `file` is the specific GGUF file
inside the repo (quantization). For vLLM, `file` is optional (downloads the
whole repo). `size` is the approximate download size. `vram` is the VRAM the
model fits in (16/24/32 GB) — used to group the 16/24/32 GB versions of a model.
"""

# vLLM models (safetensors). The Qwen3 32B family has 16/24/32 GB versions.
VLLM_MODELS = [
    {'slug': 'qwen3-8b',        'name': 'Qwen3 8B',            'repo': 'Qwen/Qwen3-8B',            'size': '~16 GB',  'vram': None},
    {'slug': 'qwen3-14b',       'name': 'Qwen3 14B',           'repo': 'Qwen/Qwen3-14B',           'size': '~28 GB',  'vram': None},
    {'slug': 'qwen3-32b-16',    'name': 'Qwen3 32B (16 GB)',   'repo': 'Qwen/Qwen3-32B-GPTQ-Int3',  'size': '~12 GB',  'vram': 16},
    {'slug': 'qwen3-32b-24',    'name': 'Qwen3 32B (24 GB)',   'repo': 'Qwen/Qwen3-32B-AWQ-Int4',   'size': '~18 GB',  'vram': 24},
    {'slug': 'qwen3-32b-32',    'name': 'Qwen3 32B (32 GB)',   'repo': 'Qwen/Qwen3-32B-GPTQ-Int8',  'size': '~32 GB',  'vram': 32},
    {'slug': 'qwen3-30b-a3b',   'name': 'Qwen3 30B-A3B (MoE)', 'repo': 'Qwen/Qwen3-30B-A3B',        'size': '~60 GB',  'vram': None},
    {'slug': 'llama31-8b',      'name': 'Llama 3.1 8B',        'repo': 'meta-llama/Meta-Llama-3.1-8B-Instruct', 'size': '~17 GB', 'vram': None},
    {'slug': 'llama31-70b',     'name': 'Llama 3.1 70B',       'repo': 'meta-llama/Meta-Llama-3.1-70B-Instruct', 'size': '~140 GB', 'vram': None},
    {'slug': 'mistral-7b',      'name': 'Mistral 7B',          'repo': 'mistralai/Mistral-7B-v0.1', 'size': '~14 GB',  'vram': None},
    {'slug': 'gemma2-27b',      'name': 'Gemma 2 27B',         'repo': 'google/gemma-2-27b-it',      'size': '~54 GB',  'vram': None},
]

# LM Studio models (GGUF). The Qwen3 32B family has 16/24/32 GB versions.
LMSTUDIO_MODELS = [
    {'slug': 'qwen3-8b',        'name': 'Qwen3 8B',            'repo': 'Qwen/Qwen3-8B-GGUF',        'file': 'Qwen3-8B-Q4_K_M.gguf',        'size': '~5.5 GB',  'vram': None},
    {'slug': 'qwen3-14b',       'name': 'Qwen3 14B',           'repo': 'Qwen/Qwen3-14B-GGUF',       'file': 'Qwen3-14B-Q4_K_M.gguf',       'size': '~10 GB',   'vram': None},
    {'slug': 'qwen3-32b-16',    'name': 'Qwen3 32B (16 GB)',   'repo': 'Qwen/Qwen3-32B-GGUF',       'file': 'Qwen3-32B-Q3_K_M.gguf',       'size': '~16 GB',   'vram': 16},
    {'slug': 'qwen3-32b-24',    'name': 'Qwen3 32B (24 GB)',   'repo': 'Qwen/Qwen3-32B-GGUF',       'file': 'Qwen3-32B-Q4_K_M.gguf',       'size': '~20 GB',   'vram': 24},
    {'slug': 'qwen3-32b-32',    'name': 'Qwen3 32B (32 GB)',   'repo': 'Qwen/Qwen3-32B-GGUF',       'file': 'Qwen3-32B-Q8_0.gguf',         'size': '~32 GB',   'vram': 32},
    {'slug': 'qwen3-30b-a3b',   'name': 'Qwen3 30B-A3B (MoE)', 'repo': 'Qwen/Qwen3-30B-A3B-GGUF',    'file': 'Qwen3-30B-A3B-Q4_K_M.gguf',   'size': '~19 GB',   'vram': None},
    {'slug': 'llama31-8b',      'name': 'Llama 3.1 8B',        'repo': 'bartowski/Meta-Llama-3.1-8B-Instruct-GGUF', 'file': 'Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf', 'size': '~5.5 GB', 'vram': None},
    {'slug': 'llama31-70b',     'name': 'Llama 3.1 70B',       'repo': 'bartowski/Meta-Llama-3.1-70B-Instruct-GGUF', 'file': 'Meta-Llama-3.1-70B-Instruct-Q4_K_M.gguf', 'size': '~43 GB', 'vram': None},
    {'slug': 'mistral-7b',      'name': 'Mistral 7B',          'repo': 'TheBloke/Mistral-7B-GGUF',   'file': 'Mistral-7B-v0.1-Q4_K_M.gguf', 'size': '~4.5 GB',  'vram': None},
    {'slug': 'gemma2-27b',      'name': 'Gemma 2 27B',         'repo': 'TheBloke/gemma-2-27b-it-GGUF', 'file': 'gemma-2-27b-it-Q4_K_M.gguf', 'size': '~16 GB',  'vram': None},
]
