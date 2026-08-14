# -*- coding: utf-8 -*-
"""BGE-M3 ONNX 动态 int8 量化（权重 2.2GB -> ~550MB，CPU 推理快 3~4 倍）。
用法：python scripts/quantize_m3.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import MODEL_CACHE  # noqa: E402

SRC_DIR = os.path.join(str(MODEL_CACHE), "bge-m3-onnx")
SRC = os.path.join(SRC_DIR, "model.onnx")
DST = os.path.join(SRC_DIR, "model_int8.onnx")


def main():
    if not os.path.isfile(SRC):
        print("缺少 model.onnx，请先下载 BGE-M3 ONNX 模型")
        sys.exit(1)
    from onnxruntime.quantization import QuantType, quantize_dynamic
    print("quantizing... (需要几分钟)")
    quantize_dynamic(
        model_input=SRC,
        model_output=DST,
        weight_type=QuantType.QInt8,
        op_types_to_quantize=["MatMul"],
    )
    size = os.path.getsize(DST)
    for f in os.listdir(SRC_DIR):
        if f.startswith("model_int8.onnx_data"):
            size += os.path.getsize(os.path.join(SRC_DIR, f))
    print(f"done -> {DST}  ({size/1e6:.0f} MB)")


if __name__ == "__main__":
    main()
