# -*- coding: utf-8 -*-
"""BGE-M3 ONNX 嵌入器：官方 onnx 导出（含 sentence_embedding 池化输出），无需 torch。"""
import os

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer


class BgeM3Embedder:
    def __init__(self, model_dir, max_len=2048, batch_size=4):
        self.model_dir = model_dir
        self.max_len = max_len
        self.batch_size = batch_size
        self.tok = Tokenizer.from_file(os.path.join(model_dir, "tokenizer.json"))
        # 优先 int8 量化版（更快更省内存），否则用 fp32 原版
        model_file = "model_int8.onnx" if os.path.isfile(os.path.join(model_dir, "model_int8.onnx")) else "model.onnx"
        self.sess = ort.InferenceSession(
            os.path.join(model_dir, model_file),
            providers=["CPUExecutionProvider"],
            sess_options=ort.SessionOptions(),
        )

    def embed(self, texts):
        if isinstance(texts, str):
            texts = [texts]
        outs = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            enc = self.tok.encode_batch(batch)
            # 动态长度：只算到本批最长序列（含少量重叠，避免重复 pad 浪费算力）
            maxl = min(max(len(e.ids) for e in enc), self.max_len)
            ids = np.zeros((len(batch), maxl), dtype=np.int64)
            mask = np.zeros((len(batch), maxl), dtype=np.int64)
            for j, e in enumerate(enc):
                t = e.ids[:maxl]
                ids[j, :len(t)] = t
                mask[j, :len(t)] = 1
            vec = self.sess.run(["sentence_embedding"], {"input_ids": ids, "attention_mask": mask})[0]
            outs.append(np.asarray(vec, dtype=np.float32))
        arr = np.vstack(outs)
        arr /= np.linalg.norm(arr, axis=1, keepdims=True) + 1e-9
        return arr if arr.shape[0] > 1 else arr[0]
