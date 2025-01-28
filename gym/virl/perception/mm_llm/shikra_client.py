import os
import re
import base64
from io import BytesIO
from typing import Union

import torch
import requests
from PIL import Image
from torchvision.transforms import ToPILImage, PILToTensor
from torchvision.utils import draw_bounding_boxes as _draw_bounding_boxes

from virl.perception.mm_llm.mm_llm_template import MultiModalLLMTemplate


def pil_to_base64(pil_img):
    output_buffer = BytesIO()
    pil_img.save(output_buffer, format="PNG")
    byte_data = output_buffer.getvalue()
    encode_img = base64.b64encode(byte_data)
    return str(encode_img, encoding='utf-8')


def de_norm_box_xyxy(box, *, w, h):
    x1, y1, x2, y2 = box
    x1 = x1 * w
    x2 = x2 * w
    y1 = y1 * h
    y2 = y2 * h
    box = x1, y1, x2, y2
    return box


def expand2square(pil_img, background_color=(255, 255, 255)):
    width, height = pil_img.size
    if width == height:
        return pil_img
    elif width > height:
        result = Image.new(pil_img.mode, (width, width), background_color)
        result.paste(pil_img, (0, (width - height) // 2))
        return result
    else:
        result = Image.new(pil_img.mode, (height, height), background_color)
        result.paste(pil_img, ((height - width) // 2, 0))
        return result


def query(image: Union[Image.Image, str], text: str, boxes_value: list, boxes_seq: list, server_url='http://127.0.0.1:12345/shikra'):
    if isinstance(image, str):
        image = Image.open(image)
    pload = {
        "img_base64": pil_to_base64(image),
        "text": text,
        "boxes_value": boxes_value,
        "boxes_seq": boxes_seq,
    }
    resp = requests.post(server_url, json=pload)
    if resp.status_code != 200:
        raise ValueError(resp.reason)
    ret = resp.json()
    return ret


def draw_bounding_boxes(
        image,
        boxes,
        **kwargs,
):
    if isinstance(image, Image.Image):
        image = PILToTensor()(image)
    assert isinstance(image, torch.Tensor), ""

    if not isinstance(boxes, torch.Tensor):
        boxes = torch.as_tensor(boxes)
    assert isinstance(boxes, torch.Tensor)

    return _draw_bounding_boxes(image, boxes, **kwargs)


def postprocess(text, image):
    if image is None:
        return text, None
    image = expand2square(image)

    colors = ['#ed7d31', '#5b9bd5', '#70ad47', '#7030a0', '#c00000', '#ffff00', "olive", "brown", "cyan"]
    pat = re.compile(r'\[\d(?:\.\d*)?(?:,\d(?:\.\d*)?){3}(?:;\d(?:\.\d*)?(?:,\d(?:\.\d*)?){3})*\]')

    def extract_boxes(string):
        ret = []
        for bboxes_str in pat.findall(string):
            bboxes = []
            bbox_strs = bboxes_str.replace("(", "").replace(")", "").replace("[", "").replace("]", "").split(";")
            for bbox_str in bbox_strs:
                bbox = list(map(float, bbox_str.split(',')))
                bboxes.append(bbox)
            ret.append(bboxes)
        return ret

    extract_pred = extract_boxes(text)
    boxes_to_draw = []
    color_to_draw = []
    for idx, boxes in enumerate(extract_pred):
        color = colors[idx % len(colors)]
        for box in boxes:
            boxes_to_draw.append(de_norm_box_xyxy(box, w=image.width, h=image.height))
            color_to_draw.append(color)
    if not boxes_to_draw:
        return text, None
    res = draw_bounding_boxes(image=image, boxes=boxes_to_draw, colors=color_to_draw, width=8)
    res = ToPILImage()(res)

    # post process text color
    location_text = text
    edit_text = list(text)
    bboxes_str = pat.findall(text)
    for idx in range(len(bboxes_str) - 1, -1, -1):
        color = colors[idx % len(colors)]
        boxes = bboxes_str[idx]
        span = location_text.rfind(boxes), location_text.rfind(boxes) + len(boxes)
        location_text = location_text[:span[0]]
        edit_text[span[0]:span[1]] = f'<span style="color:{color}; font-weight:bold;">{boxes}</span>'
    text = "".join(edit_text)
    return text, res


class ShikraClient(MultiModalLLMTemplate):
    def __init__(self, cfg):
        super().__init__(cfg)

        self.server_url = cfg.SERVER

    def predict(self, image: Image, prompt: str) -> str:
        """
        image: PIL.Image
        question: str
        """
        boxes_value = []
        boxes_seq = []
        response = query(image, prompt, boxes_value, boxes_seq, self.server_url)
        print(response['response'])

        return response['response']


if __name__ == '__main__':
    import argparse
    import easydict
    parser = argparse.ArgumentParser()
    parser.add_argument('--image_path', type=str, default='xxxx.jpg')
    parser.add_argument('--question', type=str, default='Q: Which human intentions can be accomplished here? Choices: A. Buying furniture for home improvement. B. Participating in a yoga session for fitness. C. Having a quick meal or dining with family or friends. D. Attending a music concert.')
    args = parser.parse_args()

    cfg = argparse.Namespace()
    cfg = {
        'SERVER': 'xxxx' + "/shikra"
    }
    cfg = easydict.EasyDict(cfg)

    model = ShikraClient(cfg)

    image = Image.open(args.image_path)
    question = args.question
    output = model.predict(image, question)
    print(output)
