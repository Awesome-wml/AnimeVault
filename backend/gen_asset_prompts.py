import os

art_style = "Chinese fantasy epic, majestic xianxia atmosphere, glowing spiritual energy effects, golden dragon aura, cinematic composition, high detail"

# 道具：主体居中的写实特写
prop_tpl = """仿真写实风格，道具概念设定图，主体居中，纯白干净背景，柔光均匀打光，真实材质质感，浅景深，高清电影质感，中性偏冷色调。

道具：{name}（{ptype}）。{desc}。

细节刻画：
- 材质：温润白玉质地，内部透出暗红色龙血纹理，似有流光游动
- 形制：圆形玉佩，约掌心大小，边缘刻古朴云纹，中央浮雕一条盘踞的龙
- 细节：系一根深红色丝绳，玉佩表面有细微包浆与磨损，透出年代感

构图：单件道具全身清晰可见，居中构图，占比画面约70%，无遮挡，正侧角度各显

【风格指令】{art_style}

禁止：水印、logo、文字、字幕、多余物品、卡通感、塑料感、比例失调、复杂背景、人物入镜。
"""

# 场景：干净的环境参考图
scene_tpl = """仿真写实风格，场景概念设定图，环境整体清晰可见，画面干净，柔和自然光，真实空间质感，广角镜头，高清电影质感，中性偏冷色调。

场景：{name}（{stype}）。{desc}。

场景构成：
- 布局：开阔的中式演武场，青石铺地，场地四周环绕古朴廊柱与练武器械架
- 氛围：天空乌云密布，细雨绵绵，地面被雨水打湿反射微光，远处隐约可见古建筑轮廓
- 细节：场地中央有一处凸起的擂台，边缘石阶刻有纹路，雨雾笼罩营造苍茫感
- 光线：阴天自然散射光，整体冷灰调，局部有微弱金光点缀（呼应龙血之力）

构图：全景视角，展现整个演武场的空间与环境氛围，无人物或仅极远处微小背影

【风格指令】{art_style}

禁止：水印、logo、文字、字幕、人物特写、卡通感、塑料感、比例失调、过于明亮或花哨、复杂杂乱背景。
"""

prompts = []
prompts.append(prop_tpl.format(name="龙血玉佩", ptype="法宝", desc="萧尘母亲遗物，古朴玉佩，内含龙血之力", art_style=art_style))
prompts.append(scene_tpl.format(name="萧家演武场", stype="室外", desc="暴雨中的演武场，萧家习武之地", art_style=art_style))

with open('/tmp/asset_prompts.txt','w') as f:
    f.write("===== 道具：龙血玉佩 =====\n" + prompts[0] + "\n\n===== 场景：萧家演武场 =====\n" + prompts[1] + "\n")
print('道具/场景提示词生成完成')
