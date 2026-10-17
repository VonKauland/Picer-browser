"""Real embedded AI records and codec-backed static video previews."""

import json

import pytest
from PIL import Image, PngImagePlugin

from picer.ai_metadata import LIMIT, generation_info
from picer.imaging import read_image, supported_suffixes
from picer.metadata import inspect_image
from picer.smoke_samples import make_video
from picer.video import VIDEO_SUFFIXES

PARAMETERS = (
    "sunset, <lora:lighting:0.7>\nNegative prompt: blur, text\n"
    "Steps: 24, Sampler: Euler a, CFG scale: 7, Seed: 123456789, "
    'Model: photo_v1, VAE: custom_vae, Lora hashes: "lighting: abc, detail: def"'
)


def graph():
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "model.safetensors"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "清晨的山", "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "bad hands", "clip": ["1", 1]}},
        "4": {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["1", 0],
                "lora_name": "light.safetensors",
                "strength_model": 0.7,
                "strength_clip": 0.5,
            },
        },
        "5": {"class_type": "VAELoader", "inputs": {"vae_name": "vae.safetensors"}},
        "6": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["4", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "seed": 9007199254740993,
                "steps": 20,
                "cfg": 6,
            },
        },
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["5", 0]}},
        "8": {"class_type": "SaveImage", "inputs": {"images": ["7", 0]}},
        "99": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "unused.safetensors"},
        },
    }


def test_sd_png_metadata_and_quoted_lora_values(tmp_path):
    path = tmp_path / "sd.png"
    info = PngImagePlugin.PngInfo()
    info.add_text("parameters", PARAMETERS)
    Image.new("RGB", (32, 24)).save(path, pnginfo=info)
    result = inspect_image(path)["ai_generation"]
    assert result["message"] == "此图片为Stable Diffusion生成"
    fields = result["fields"]
    assert fields["模型"] == "photo_v1" and fields["VAE"] == "custom_vae"
    assert fields["负面提示词"] == "blur, text" and fields["LoRA"] == "lighting:0.7"
    assert fields["LoRA 哈希"] == "lighting: abc, detail: def"
    assert fields["Seed"] == "123456789"


@pytest.mark.parametrize("extension", ["jpg", "webp"])
def test_ai_exif_unicode_user_comment(tmp_path, extension):
    exif = Image.Exif()
    exif[34665] = {37510: b"UNICODE\0" + PARAMETERS.encode("utf-16-be")}
    path = tmp_path / f"ai.{extension}"
    Image.new("RGB", (32, 24)).save(path, exif=exif)
    assert inspect_image(path)["ai_generation"]["fields"]["模型"] == "photo_v1"


def test_comfy_connected_graph_and_exact_seed(tmp_path):
    path = tmp_path / "comfy.png"
    info = PngImagePlugin.PngInfo()
    info.add_text("prompt", json.dumps(graph()))
    Image.new("RGB", (32, 24)).save(path, pnginfo=info)
    result = inspect_image(path)["ai_generation"]
    assert result["source"] == "ComfyUI"
    fields = result["fields"]
    assert fields["模型"] == "model.safetensors"
    assert fields["正面提示词"] == "清晨的山" and fields["负面提示词"] == "bad hands"
    assert fields["Seed"] == "9007199254740993"
    assert fields["VAE"] == "vae.safetensors" and "light.safetensors" in fields["LoRA"]


def test_comfy_custom_sampler_and_malformed_records():
    nodes = graph()
    nodes["9"] = {
        "class_type": "CFGGuider",
        "inputs": {
            key: nodes["6"]["inputs"][key] for key in ("model", "positive", "negative", "cfg")
        },
    }
    nodes["10"] = {"class_type": "RandomNoise", "inputs": {"noise_seed": 42}}
    nodes["6"] = {
        "class_type": "SamplerCustomAdvanced",
        "inputs": {"guider": ["9", 0], "noise": ["10", 0]},
    }
    result = generation_info({"prompt": json.dumps(nodes)})
    assert result["fields"]["正面提示词"] == "清晨的山"
    assert result["fields"]["Seed"] == "42"
    assert generation_info({"prompt": "[broken", "parameters": "just a photo"}) is None
    assert generation_info({"prompt": "[" * 2000}) is None
    assert generation_info({"parameters": "a" * (LIMIT + 1)}) is None
    assert generation_info({"parameters": "Stable Diffusion picture"}) is None


def test_comfy_standard_ui_workflow_and_cycles():
    workflow = {
        "nodes": [
            {"id": 1, "type": "CheckpointLoaderSimple", "widgets_values": ["camera.safetensors"]},
            {"id": 2, "type": "CLIPTextEncode", "widgets_values": ["sunrise"]},
            {
                "id": 3,
                "type": "KSampler",
                "widgets_values": [42, "fixed", 20, 7, "euler", "normal", 1],
                "inputs": [{"name": "positive", "link": 1}, {"name": "model", "link": 2}],
            },
        ],
        "links": [[1, 2, 0, 3, 0, "CONDITIONING"], [2, 1, 0, 3, 1, "MODEL"]],
    }
    result = generation_info({"workflow": json.dumps(workflow)})
    assert result["fields"]["Seed"] == "42" and result["fields"]["正面提示词"] == "sunrise"
    assert result["fields"]["模型"] == "camera.safetensors"
    cyclic = graph()
    cyclic["2"]["inputs"]["loop"] = ["2", 0]
    assert generation_info({"prompt": json.dumps(cyclic)})["source"] == "ComfyUI"


@pytest.mark.parametrize(
    "extension,codec",
    [
        ("mp4", "mpeg4"),
        ("mov", "mpeg4"),
        ("mkv", "mpeg4"),
        ("avi", "mpeg4"),
        ("webm", "libvpx-vp9"),
        ("wmv", "wmv2"),
    ],
)
def test_real_static_video_codecs_and_glass_frame(tmp_path, qapp, extension, codec):
    path = make_video(tmp_path / f"clip.{extension}", codec)
    image = read_image(path)
    assert image.text("picer.video_preview") == "1"
    assert image.width() > 160 and image.height() > 96
    assert image.pixelColor(0, 0).alpha() == 0
    # Preview center retains the first frame; the side rail has transparent film holes.
    assert image.pixelColor(image.width() // 2, image.height() // 2).blue() > 140
    assert any(image.pixelColor(4, y).alpha() == 0 for y in range(5, image.height() - 5))
    metadata = inspect_image(path)
    assert metadata["dimensions"]["宽度"] == "160"
    assert metadata["dimensions"]["预览类型"] == "视频静态封面"
    assert not metadata["warnings"]
    assert VIDEO_SUFFIXES <= supported_suffixes()
