# -*- coding: utf-8 -*-
import os
from pymongo import MongoClient
c=MongoClient(os.environ['MONGODB_URL'],serverSelectionTimeoutMS=8000)
db=c['dongai']
PID='6ae961350ffbfadd633dc6b2'
user_id='6ae8da368672b0f0642f42e5'
NEG = "watermark, logo, text, subtitle, extra people, cartoon style, plastic look, distorted proportions, blurry, low quality, oversaturated, modern elements"
# 每个15s镜头=一个完整连贯的戏剧动作单元
shots=[
 (1,"旁白","暴雨如注，萧家演武场内，灰衣少年萧尘正艰难擦拭积水，锦衣青年赵虎带家丁闯入嘲讽。",
  "heavy rain pouring, thunder, a 16-year-old grey-cloth boy wiping rain on an ancient Chinese clan training ground, a brocade-robed arrogant young man striding in with servants to mock him, wide cinematic establishing shot, rain streaks, dark stormy sky, Chinese fantasy epic",
  "全景缓移，俯拍拉近"),
 (2,"赵虎","赵虎冷笑踹断萧尘手中扫帚，出言羞辱他是连一重气海都打不开的废物。",
  "the arrogant young man kicks and snaps the boy's broom into pieces, splinters flying, cruelly mocking him as a worthless waste, close-up on the boy's suppressed anger, medium shot, dramatic rain",
  "中景推进，特写对切"),
 (3,"萧尘","萧尘忍辱回应‘今日的事我记下了’，赵虎大怒一掌拍向他面门。",
  "the boy clenches his fists and coldly vows to remember today, the arrogant man erupts in anger and throws a powerful palm strike at the boy's face, slow motion palm approaching, dramatic confrontation",
  "近景对切，特写快慢镜"),
 (4,"萧尘","萧尘胸口玉佩灼热爆发，血色光芒与巨龙虚影浮现，气浪将赵虎震退。",
  "suddenly the boy's chest glows blood-red, an ancient jade pendant erupts with light, a giant dragon phantom appears above him, a shockwave blasts the attacker backward, epic cinematic, glowing golden dragon aura",
  "全景拉升，环绕运镜"),
 (5,"萧天","族长萧天苍老声音喝止赵虎，赵虎撂狠话后带家丁离去，萧尘独坐喘息。",
  "a majestic old clan leader in grey robe with white beard steps forward to stop the fight, the arrogant young man curses and leaves with servants, the exhausted boy collapses on the wet ground, medium shot",
  "中景反打，推移"),
 (6,"萧尘","萧尘抚摸母亲遗物玉佩，玉佩感应情绪光芒大盛，滚烫热流涌入体内，龙鳞浮现，经脉冲开。",
  "the boy sits alone touching an ancient jade pendant, it suddenly flares golden-red sensing his emotion, burning heat surges in, golden dragon-scale patterns appear on his skin, blocked meridians burst open, eyes burn with new power, dramatic lighting",
  "近景固定，微距+环绕"),
 (7,"旁白","次日家族大比，演武场人声鼎沸，萧尘穿着洗旧旧衣走上擂台，众人嘲笑他废物。",
  "next day the clan training ground is crowded for the family tournament, the boy in washed-out old clothes steps onto the stone platform while the crowd mocks him, wide establishing shot, gossipy atmosphere",
  "全景推移，俯拍"),
 (8,"萧尘","赵虎坐太师椅嘲讽，长老宣布认输可保命，萧尘坚定回应‘我从不认输’。",
  "the arrogant young man sits in a grand chair taunting the boy, an elder coldly offers surrender to save his life, the boy raises his head and firmly declares he never surrenders, medium close-up, solemn confrontation",
  "中景对切"),
 (9,"萧尘","赵虎暴起一掌拍来，萧尘双拳轰出，龙血力量爆发，硬撼赵虎，一巴掌扇飞赵虎。",
  "the arrogant man unleashes a full-power palm strike, the boy's fists glow golden with dragon power, he meets it head-on with a huge shockwave and slaps the attacker across the face, sending him stumbling to the ground, epic slow motion",
  "慢动作全景，环绕"),
 (10,"萧天","族长萧天登台，问萧尘力量来源，宣布他直接晋级决赛，对手是家族第一天才萧云。",
  "the old clan leader ascends the platform, impressed by the boy's power, announces he advances directly to the final against the family's top genius Xiao Yun, solemn ceremony, impressed crowd",
  "中景庄重推移"),
 (11,"萧云","决赛开始，白衣天才萧云执剑登场，剑气纵横刺向萧尘，萧尘双拳迎上，金铁交鸣。",
  "the final begins, a white-robed sword genius stands ethereal on the platform, unleashes a flurry of sword qi, the boy meets it with golden-dragon fists, sparks of metal clashing, intense dynamic exchange",
  "全景拉升，高速跟拍环绕"),
 (12,"萧尘","萧尘龙血爆发，‘龙战于野’，威压震飞萧云，金色光柱冲天，他宣告逆天之路，阳光洒落。",
  "the boy roars and erupts with overwhelming dragon-blood power, a golden aura blasts the genius across the platform, a golden pillar of light shoots into the sky, the storm stops and sunlight breaks through onto the triumphant hero, epic finale",
  "仰拍大全景，光柱拉升"),
]
docs=[]
for i,(no,ch,text,prompt,camera) in enumerate(shots,1):
    docs.append({"user_id":user_id,"project_id":PID,"shot_no":no,"text":text,"prompt":prompt,
        "neg_prompt":NEG,"duration":15.0,"camera":camera,"character_name":ch,"img_path":None,"audio_path":None})
db.shots.delete_many({"project_id":PID})
r=db.shots.insert_many(docs)
open('/tmp/rebuild_ok.txt','w').write("写入 "+str(len(docs))+" 个")
print('ok', len(docs))
