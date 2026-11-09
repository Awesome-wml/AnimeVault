import os, json
from pymongo import MongoClient
from core.prompt_tpl import CHARACTER_SHEET_PROMPT
from core.style_library import build_style_art_prompt

c=MongoClient(os.environ['MONGODB_URL'],serverSelectionTimeoutMS=8000)
db=c['dongai']
chars=list(db.characters.find({}))
art_style = build_style_art_prompt('xuanhuan') or ''

out=[]
for d in chars:
    name=d['name']
    desc=d.get('description','')
    p = CHARACTER_SHEET_PROMPT.format(
        character_name=name,
        character_description=desc,
        gender={'male': '男性', 'female': '女性'}.get(d.get('gender') or '', '性别按人物设定'),
        age_group=d.get('age_group') or '按人物设定',
        art_style=art_style
    )
    out.append({'name':name,'prompt':p})

with open('/tmp/three_view_prompts.txt','w') as f:
    for o in out:
        f.write(f"===== {o['name']} =====\n{o['prompt']}\n\n")
print('生成4个提示词完成')
