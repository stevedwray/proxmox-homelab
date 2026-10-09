#!/usr/bin/env python3
# Usage (on framework): python3 gguf-strip-vision.py <ollama-style.gguf> <text-only.gguf>
# Used 2026-10-09 for Gemma4-26B-A4B-QAT-Q4_0 (docs/llama-swap/plan.md, phase 4).
"""Write a text-only copy of an Ollama-style GGUF that bundles a vision
tower (v.* / mm.* tensors, <arch>.vision.* keys), which llama.cpp refuses
("wrong number of tensors"). Same metadata otherwise, same text tensors,
byte for byte. Follows gguf-py's gguf_new_metadata.copy_with_new_metadata."""
import os
import sys

sys.path.insert(0, "/storage/llama-builds/src/gguf-py")
import gguf  # noqa: E402

src, dst = sys.argv[1], sys.argv[2]
if os.path.exists(dst):
    sys.exit(f"{dst} exists")
reader = gguf.GGUFReader(src)
arch = reader.fields[gguf.Keys.General.ARCHITECTURE].contents()


def vision_tensor(name):
    return name.startswith(("v.", "mm.", "a.", "mm_a."))


def vision_key(name):
    return name.startswith((f"{arch}.vision.", f"{arch}.audio.", "clip."))


align = reader.fields.get("general.alignment")
writer = gguf.GGUFWriter(dst + ".part", arch=arch, endianess=reader.endianess)
if align is not None:
    writer.data_alignment = int(align.contents())
dropped_keys = []
for field in reader.fields.values():
    if field.name == gguf.Keys.General.ARCHITECTURE or field.name.startswith("GGUF."):
        continue
    if vision_key(field.name):
        dropped_keys.append(field.name)
        continue
    val_type = field.types[0]
    sub_type = field.types[-1] if val_type == gguf.GGUFValueType.ARRAY else None
    writer.add_key_value(field.name, field.contents(), val_type, sub_type=sub_type)
kept = [t for t in reader.tensors if not vision_tensor(t.name)]
for t in kept:
    writer.add_tensor_info(t.name, t.data.shape, t.data.dtype, t.data.nbytes, t.tensor_type)
writer.write_header_to_file()
writer.write_kv_data_to_file()
writer.write_ti_data_to_file()
for t in kept:
    writer.write_tensor_data(t.data, tensor_endianess=reader.endianess)
writer.close()
os.replace(dst + ".part", dst)
print(f"kept {len(kept)} of {len(reader.tensors)} tensors; dropped keys: {dropped_keys}")
check = gguf.GGUFReader(dst)
assert len(check.tensors) == len(kept)
print(f"wrote {dst}: {os.path.getsize(dst) / 2**30:.1f} GiB, re-read OK")
