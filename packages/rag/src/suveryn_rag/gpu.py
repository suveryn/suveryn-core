"""Whether a failure means the GPU's memory is full (suveryn-tracker#133).

On a 24 GB card the chat model, the layout model and the embedding model share the GPU, and when it is full the
work is done again on the CPU: slower, but complete. PyTorch and CUDA say "full" in more than one way: "CUDA out
of memory" from PyTorch's allocator, "CUDA error: out of memory" from a kernel, and an ``*_ALLOC_FAILED`` status
when cuBLAS or cuDNN can't get the memory for a handle (a plain ``RuntimeError``)."""

_FULL = ("out of memory", "_alloc_failed")


def out_of_memory(message: object) -> bool:
    """True when ``message`` (an exception, or the text of one) says the GPU had no memory left."""
    text = str(message or "").lower()
    return any(sign in text for sign in _FULL)
