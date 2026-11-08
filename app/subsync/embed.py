"""Multilingual sentence embeddings (paraphrase-multilingual-MiniLM, ONNX, CPU).
Lets an English subtitle line be matched to speech in another language."""
from __future__ import annotations

import os

import numpy as np


class Embedder:
    def __init__(self, model_dir: str):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        so = ort.SessionOptions()
        so.intra_op_num_threads = max(1, (os.cpu_count() or 4) - 1)
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.sess = ort.InferenceSession(os.path.join(model_dir, "model.onnx"), so,
                                         providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.sess.get_inputs()}
        self.tok = Tokenizer.from_file(os.path.join(model_dir, "tokenizer.json"))
        self.tok.enable_truncation(128)
        pad = self.tok.token_to_id("<pad>")
        self.tok.enable_padding(pad_id=pad if pad is not None else 0, pad_token="<pad>")
        self._cache: dict[str, np.ndarray] = {}

    def __call__(self, texts: list[str], batch: int = 64) -> np.ndarray:
        out = np.zeros((len(texts), 0), dtype=np.float32)
        todo = sorted({t for t in texts if t not in self._cache}, key=len)
        for k in range(0, len(todo), batch):
            chunk = todo[k:k + batch]
            enc = self.tok.encode_batch(chunk)
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            hidden = self.sess.run(None, feed)[0]
            if hidden.ndim == 3:  # mean pooling over real tokens
                m = mask[..., None].astype(np.float32)
                vec = (hidden * m).sum(1) / np.maximum(m.sum(1), 1e-6)
            else:
                vec = hidden
            vec = vec / np.maximum(np.linalg.norm(vec, axis=1, keepdims=True), 1e-6)
            for t, v in zip(chunk, vec.astype(np.float32)):
                self._cache[t] = v
        if len(self._cache) > 200_000:
            self._cache.clear()
            return self(texts, batch)
        return np.stack([self._cache[t] for t in texts]) if texts else out
