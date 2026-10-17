"""Read embedded generation records as bounded data, never execute workflows."""

import json
import re

LIMIT = 1024 * 1024
TEXT_LIMIT = 65536


def text(value):
    if not isinstance(value, (bytes, str)) or len(value) > LIMIT:
        return ""
    if isinstance(value, bytes):
        if value.startswith(b"ASCII\0\0\0"):
            value = value[8:].decode("utf-8", errors="replace")
        elif value.startswith(b"UNICODE\0"):
            raw = value[8:]
            codec = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-16-be"
            value = raw.decode(codec, errors="replace")
        else:
            value = value.decode("utf-8", errors="replace")
    return value.strip("\0 \r\n") if isinstance(value, str) and len(value) <= LIMIT else ""


def display(value):
    return str(value)[:TEXT_LIMIT]


def record(source, fields):
    for key in ("模型", "VAE", "LoRA"):
        fields.setdefault(key, "未记录")
    return {"source": source, "message": f"此图片为{source}生成", "fields": fields}


def parameter_parts(value):
    start, quoted, escaped, depth = 0, False, False, 0
    key_start = re.compile(r"\s*[A-Za-z][A-Za-z0-9 _/-]*:\s*")
    for i, char in enumerate(value):
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif not quoted:
            if char in "[{(":
                depth += 1
            elif char in "]})":
                depth = max(0, depth - 1)
            elif char == "," and not depth and key_start.match(value, i + 1):
                yield value[start:i]
                start = i + 1
    yield value[start:]


def stable_diffusion(value):
    # A1111/Forge-style infotext: prompt, optional negative prompt, sampling line.
    match = list(re.finditer(r"(?:^|\n)Steps:\s*\d+", value))
    if not match:
        return None
    start = match[-1].start()
    prompt, settings = value[:start].strip(), value[start:].strip()
    if not re.search(r",\s*(Seed|Sampler):", settings):
        return None
    positive, separator, negative = prompt.partition("\nNegative prompt:")
    if positive.startswith("Negative prompt:"):
        positive, negative = "", positive.removeprefix("Negative prompt:").strip()
    params = {}
    for index, part in enumerate(parameter_parts(settings)):
        if index >= 128:
            break
        key, colon, val = part.partition(":")
        if colon:
            params[key.strip()] = val.strip().strip('"')
    fields = {}
    for key, label in (
        ("Model", "模型"),
        ("Model hash", "模型哈希"),
        ("VAE", "VAE"),
        ("VAE hash", "VAE 哈希"),
    ):
        if params.get(key):
            fields[label] = display(params[key])
    fields["正面提示词"] = display(positive.strip())
    fields["负面提示词"] = display(negative.strip() if separator or negative else "")
    loras = re.findall(r"<lora:([^>]+)>", prompt, flags=re.IGNORECASE)
    if loras:
        fields["LoRA"] = display("\n".join(dict.fromkeys(loras)))
    labels = {
        "Seed": "Seed",
        "Steps": "步数",
        "Sampler": "采样器",
        "CFG scale": "CFG",
        "Size": "生成尺寸",
        "Lora hashes": "LoRA 哈希",
    }
    consumed = {"Model", "Model hash", "VAE", "VAE hash"}
    for key, val in params.items():
        if key not in consumed:
            fields[labels.get(key, key)] = display(val)
    return record("Stable Diffusion", fields)


def workflow_graph(workflow):
    """Recognize standard saved UI workflows without guessing custom widget schemas."""
    raw_nodes, links = workflow.get("nodes"), workflow.get("links")
    if (
        not isinstance(raw_nodes, list)
        or len(raw_nodes) > 4096
        or not isinstance(links, list)
        or len(links) > 8192
    ):
        return {}
    edges = {
        edge[0]: [str(edge[1]), edge[2]]
        for edge in links
        if isinstance(edge, list) and len(edge) >= 6 and isinstance(edge[0], (str, int))
    }
    schemas = {
        "CheckpointLoaderSimple": ("ckpt_name",),
        "UNETLoader": ("unet_name", "weight_dtype"),
        "VAELoader": ("vae_name",),
        "LoraLoader": ("lora_name", "strength_model", "strength_clip"),
        "CLIPTextEncode": ("text",),
        "KSampler": (
            "seed",
            "control_after_generate",
            "steps",
            "cfg",
            "sampler_name",
            "scheduler",
            "denoise",
        ),
        "KSamplerAdvanced": (
            "add_noise",
            "noise_seed",
            "control_after_generate",
            "steps",
            "cfg",
            "sampler_name",
            "scheduler",
            "start_at_step",
            "end_at_step",
            "return_with_leftover_noise",
        ),
    }
    graph = {}
    for node in raw_nodes:
        if not isinstance(node, dict) or not isinstance(node.get("type"), str):
            continue
        inputs = {}
        widgets = node.get("widgets_values", [])
        if isinstance(widgets, list):
            inputs.update(zip(schemas.get(node["type"], ()), widgets, strict=False))
        slots = node.get("inputs", [])
        if isinstance(slots, list):
            for slot in slots:
                if (
                    isinstance(slot, dict)
                    and isinstance(slot.get("name"), str)
                    and isinstance(slot.get("link"), (str, int))
                    and slot["link"] in edges
                ):
                    inputs[slot["name"]] = edges[slot["link"]]
        if isinstance(node.get("id"), (str, int)):
            graph[str(node["id"])] = {"class_type": node["type"], "inputs": inputs}
    return graph


def comfyui(value):
    try:
        graph = json.loads(value)
    except (ValueError, RecursionError):
        return None
    if not isinstance(graph, dict) or not 0 < len(graph) <= 4096:
        return None
    if "nodes" in graph:
        graph = workflow_graph(graph)
    nodes = {
        str(key): node
        for key, node in graph.items()
        if isinstance(node, dict)
        and isinstance(node.get("class_type"), str)
        and isinstance(node.get("inputs"), dict)
    }
    if not nodes:
        return None

    def linked(value):
        return (
            isinstance(value, list)
            and len(value) == 2
            and isinstance(value[0], (str, int))
            and type(value[1]) is int
            and str(value[0]) in nodes
        )

    def upstream(starts, skip=()):
        pending, visited = list(starts), set()
        while pending and len(visited) < 1024:
            key = str(pending.pop())
            if key in visited or key not in nodes:
                continue
            visited.add(key)
            node = nodes[key]
            yield key, node
            pending.extend(
                str(v[0]) for k, v in node["inputs"].items() if k not in skip and linked(v)
            )

    outputs = [
        key
        for key, node in nodes.items()
        if node["class_type"]
        in ("SaveImage", "PreviewImage", "SaveAnimatedWEBP", "SaveAnimatedPNG")
    ]
    active = dict(upstream(outputs or list(nodes)))
    samplers = [
        (key, n)
        for key, n in active.items()
        if "sampler" in n["class_type"].lower()
        and (
            n["class_type"] in ("SamplerCustom", "SamplerCustomAdvanced")
            or "positive" in n["inputs"]
            or "noise_seed" in n["inputs"]
            or "seed" in n["inputs"]
        )
    ]
    if not samplers:
        return None
    fields = {}

    def add(label, value):
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            rendered = display(value)
            if rendered and rendered not in fields.get(label, "").split("\n"):
                fields[label] = (
                    display(fields[label] + "\n" + rendered) if label in fields else rendered
                )

    for node in active.values():
        inputs = node["inputs"]
        for key in ("ckpt_name", "unet_name", "model_name"):
            add("模型", inputs.get(key))
        add("VAE", inputs.get("vae_name"))
        if isinstance(inputs.get("lora_name"), str):
            add(
                "LoRA",
                f"{inputs['lora_name']} · model {inputs.get('strength_model', '未记录')}"
                f" · clip {inputs.get('strength_clip', '未记录')}",
            )
    for index, (_, node) in enumerate(samplers[:32], 1):
        prefix = f"采样 {index} · " if len(samplers) > 1 else ""
        inputs = node["inputs"]
        conditioning = [inputs]
        if linked(inputs.get("guider")):
            conditioning.extend(
                n["inputs"] for _, n in upstream([inputs["guider"][0]], skip=("model", "clip"))
            )
        for key, label in (("positive", "正面提示词"), ("negative", "负面提示词")):
            source = next((n[key] for n in conditioning if key in n), None)
            if isinstance(source, str):
                add(prefix + label, source)
            elif linked(source):
                for _, upstream_node in upstream([source[0]], skip=("clip", "model", "vae")):
                    for name, val in upstream_node["inputs"].items():
                        if name in ("text", "text_g", "text_l", "string", "prompt"):
                            add(prefix + label, val)
        for key, label in (
            ("seed", "Seed"),
            ("noise_seed", "Seed"),
            ("steps", "步数"),
            ("cfg", "CFG"),
            ("sampler_name", "采样器"),
            ("scheduler", "调度器"),
            ("denoise", "降噪强度"),
        ):
            add(prefix + label, inputs.get(key))
        for name in ("noise", "sigmas", "guider", "sampler"):
            if linked(inputs.get(name)):
                for _, linked_node in upstream(
                    [inputs[name][0]], skip=("model", "positive", "negative", "clip")
                ):
                    for key, label in (
                        ("noise_seed", "Seed"),
                        ("seed", "Seed"),
                        ("steps", "步数"),
                        ("cfg", "CFG"),
                        ("sampler_name", "采样器"),
                        ("scheduler", "调度器"),
                        ("denoise", "降噪强度"),
                    ):
                        add(prefix + label, linked_node["inputs"].get(key))
    return record("ComfyUI", fields)


def generation_info(info, exif=None):
    """PNG text, WebP/JPEG EXIF UserComment and ImageDescription records."""
    info = {str(k).lower(): v for k, v in info.items()}
    for key in ("prompt", "workflow"):
        prompt = text(info.get(key))
        if prompt:
            result = comfyui(prompt)
            if result:
                return result
    for value in (
        info.get("parameters"),
        (exif or {}).get("UserComment"),
        (exif or {}).get("ImageDescription"),
        info.get("comment"),
        info.get("description"),
    ):
        value = text(value)
        if value:
            result = stable_diffusion(value)
            if result:
                return result
    return None
