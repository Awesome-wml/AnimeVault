"""直接发给文生图模型的模板不能带敏感词：智谱过滤只看关键词不看否定，“不裸露”也会被拦（1301）。"""
import pytest

from core import prompt_tpl

IMAGE_TEMPLATES = ["CHARACTER_SHEET_PROMPT", "PROP_REF_PROMPT", "SCENE_REF_PROMPT"]
BANNED = ["裸露", "内衣", "走光", "暴露", "性暗示", "色情", "低俗", "血腥", "尸体", "自杀", "自残", "断肢"]


@pytest.mark.parametrize("name", IMAGE_TEMPLATES)
def test_image_templates_have_no_sensitive_words(name):
    tpl = getattr(prompt_tpl, name)
    hits = [w for w in BANNED if w in tpl]
    assert not hits, f"{name} 含会触发出图过滤的词：{hits}"
