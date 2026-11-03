# -*- coding: utf-8 -*-
import os, json
from pymongo import MongoClient
import bson

c=MongoClient(os.environ['MONGODB_URL'],serverSelectionTimeoutMS=8000)
db=c['dongai']
PID='6ae961350ffbfadd633dc6b2'
user_id='6ae8da368672b0f0642f42e5'

# 风格指令（玄幻·仙气·金芒龙气）
STYLE = "Chinese fantasy epic, majestic xianxia atmosphere, glowing spiritual energy effects, golden dragon aura, ancient oriental architecture, dramatic godly lighting, cinematic composition, high detail, realistic textures"
NEG = "watermark, logo, text, subtitle, extra people, cartoon style, plastic look, distorted proportions, blurry, low quality, oversaturated, modern elements"

# 15s分镜数据：no, character_name, text, prompt(英文连贯动作), camera
shots = [
 # === 第一幕：暴雨演武场，萧尘受辱 ===
 (1,"旁白","暴雨如注，雷声轰鸣，萧家演武场内，灰衣少年萧尘艰难地擦拭积水。",
  "Heavy rain pouring, thunder roaring, a 16-year-old boy in grey cloth wiping rain water on the stone training ground of an ancient Chinese clan, cinematic wide shot, rain streaks, dark stormy sky",
  "全景缓移，俯拍拉近"),
 (2,"赵虎","锦衣青年赵虎带家丁闯入，嚣张地嘲讽萧尘扫不干净水。",
  "A young man in luxurious brocade robe with arrogant sneer strides into the training ground followed by two servants, mocking the poor boy holding a broom, medium shot, dramatic rain",
  "中景推进，侧面跟拍"),
 (3,"萧尘","萧尘忍辱应答，赵虎冷笑踹断扫帚，出言羞辱他是废物。",
  "The grey-clad boy clenches his broom, humble reply, then the arrogant young man kicks and snaps the broom into pieces, splinters flying, close-up on the boy's eyes suppressing anger",
  "近景对切，特写摇移"),
 # === 第二幕：玉佩觉醒，震退赵虎 ===
 (4,"赵虎","赵虎一掌拍向萧尘面门，掌风刚猛。",
  "The arrogant young man throws a powerful palm strike toward the boy's face, strong wind, slow motion palm approaching, boy frozen unable to dodge, medium close-up",
  "特写推进，快慢镜结合"),
 (5,"萧尘","萧尘胸口玉佩灼热爆发，血色光芒与巨龙虚影浮现，气浪震退赵虎。",
  "Suddenly the boy's chest glows blood-red, an ancient jade pendant erupts with light, a giant dragon phantom appears above him, shockwave blasts the attacker backward, epic cinematic",
  "全景拉升，环绕运镜"),
 (6,"萧天","族长萧天苍老声音传来，喝止赵虎；赵虎撂狠话后带家丁离去。",
  "A majestic old voice from off-screen stops the fight, an old clan leader in grey robe with white beard appears, the arrogant young man curses and leaves with servants, the boy collapses on ground",
  "中景，反打镜头"),
 # === 第三幕：萧尘独坐，玉佩异动，龙血觉醒 ===
 (7,"萧尘","萧尘独坐，抚摸母亲遗物玉佩，喃喃询问母亲与玉佩的秘密。",
  "The boy sits alone on the wet ground, gasping, gently touching an ancient jade pendant on his chest, whispering to it under the rain, sad lonely atmosphere, close-up on the pendant",
  "近景固定，微距特写"),
 (8,"萧尘","玉佩感应情绪光芒大盛，滚烫热流涌入体内，萧尘痛苦嘶吼。",
  "The jade pendant suddenly flares with intense golden-red light sensing the boy's emotion, burning heat surges into his body, he screams in agony, body convulsing, dramatic lighting",
  "特写拉远，快切"),
 (9,"萧尘","金色龙鳞纹路浮现皮肤，经脉被霸道力量冲开，萧尘重获力量。",
  "Golden dragon-scale patterns appear on the boy's skin, surging ancient power rips through his blocked meridians, he sees golden light in his hands, eyes burning with newfound strength, epic glow",
  "环绕运镜，微距+全景"),
 # === 第四幕：家族大比，萧尘登场 ===
 (10,"旁白","次日家族大比，演武场人声鼎沸，众人嘲笑萧尘废物。",
  "Next day the clan training ground is crowded for the family tournament, people gossip and laugh at the boy in washed-out old clothes as he steps onto the stone platform, wide establishing shot",
  "全景推移，俯拍"),
 (11,"赵虎","赵虎坐太师椅把玩玉佩，嘲讽萧尘；长老宣布认输可保命。",
  "The arrogant young man sits in a grand chair playing with a jade, taunting the boy; an elder coldly announces the boy may surrender to live, the boy stands silently, medium shot",
  "中景对切"),
 (12,"萧尘","萧尘坚定回应绝不认输，赵虎暴起一掌拍来。",
  "The boy raises his head and firmly declares he will never surrender, the arrogant man erupts with anger and unleashes a full-power palm strike, wind howling, dramatic confrontation",
  "特写+全景，快切"),
 # === 第五幕：击败赵虎，晋级决赛 ===
 (13,"萧尘","萧尘双拳轰出，龙血力量爆发，硬撼赵虎，一拳扇飞赵虎。",
  "The boy's fists glow with golden dragon power, he meets the palm strike head-on with a huge shockwave, then slaps the arrogant young man across the face, sending him stumbling to the ground, epic slow motion",
  "慢动作全景，环绕"),
 (14,"萧天","族长萧天登台，问萧尘力量来源，宣布其直接晋级决赛，对手是萧云。",
  "The old clan leader ascends the platform, impressed by the boy's power, announces the boy advances directly to the final against the family's top genius Xiao Yun, solemn ceremony",
  "中景，庄重推移"),
 # === 第六幕：决赛，对决萧云 ===
 (15,"旁白","三日苦修后决赛开始，白衣天才萧云执剑登场，宛如谪仙。",
  "After three days of cultivation the final begins, the crowd roars, a white-robed genius with a sword stands on the platform, ethereal and calm, wide establishing shot",
  "全景拉升"),
 (16,"萧云","萧云剑气纵横刺向萧尘，萧尘双拳迎上，金铁交鸣。",
  "The white-robed genius unleashes a flurry of sword qi, the boy meets it with golden-dragon fists, sparks of metal clashing, intense exchange, dynamic action shots",
  "高速跟拍，环绕"),
 (17,"萧尘","萧尘龙血爆发，‘龙战于野’，威压震飞萧云，全场死寂。",
  "The boy roars and erupts with overwhelming dragon-blood power, a golden aura explodes, the genius is blasted across the platform, the crowd falls into stunned silence, epic finale",
  "全景，仰拍拉升"),
 # === 第七幕：龙血战尊宣言 ===
 (18,"萧尘","萧尘立于擂台宣告逆天之路，金色光柱冲天，暴雨骤停阳光洒落。",
  "The boy stands triumphant on the platform, declares he will shake the entire dynasty, a golden pillar of light shoots into the sky, the storm suddenly stops and sunlight breaks through clouds onto him, heroic finale",
  "仰拍大全景，光柱拉升"),
]

docs=[]
for i,(no,ch,text,prompt,camera) in enumerate(shots,1):
    docs.append({
        "user_id": user_id,
        "project_id": PID,
        "shot_no": no,
        "text": text,
        "prompt": prompt,
        "neg_prompt": NEG,
        "duration": 15.0,
        "camera": camera,
        "character_name": ch,
        "img_path": None,
        "audio_path": None
    })

# 写入（先清空该项目的旧分镜）
db.shots.delete_many({"project_id": PID})
r=db.shots.insert_many(docs)
open('/tmp/shots_written.txt','w').write(f"写入分镜 {len(docs)} 个, inserted {len(r.inserted_ids)}")
print('写入完成', len(docs))
