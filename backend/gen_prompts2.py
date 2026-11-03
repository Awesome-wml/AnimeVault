import os
# 直接按角色人设手写精修提示词，去除"玄幻风格"干扰，让写实感更纯
chars = {
"萧尘": {
 "desc":"26岁中国男性，身形挺拔偏瘦，7.5头身，腿部占身高60%（4:6长腿比例），面容清秀带着沧桑感，皮肤下隐约浮现金色龙鳞纹路，眼神锐利，气质坚毅",
 "hair":"深黑色短发，纹理烫，发质蓬松有层次",
 "cloth":"灰色粗布劲装（短打），腰间系深色束带，袖口收紧，武侠风格但写实布衣质感"
},
"赵虎": {
 "desc":"28岁中国男性，身形高大魁梧，肩宽背阔，眉骨高耸，眼神阴鸷傲慢，嘴角带一丝邪气冷笑，反派气质",
 "hair":"油亮背头，发丝整齐服帖，稍显油腻",
 "cloth":"深色绣金纹锦衣长袍，袖口宽大，腰间束白玉腰带，富家子弟反派质感"
},
"萧天": {
 "desc":"65岁中国男性，身形瘦削挺拔，须发皆白，面容威严，双目精光四射，气质不怒自威，族长气度",
 "hair":"银白长发束成高髻，垂落缕缕银丝，胡须长而整齐",
 "cloth":"灰白色古朴长袍，绣暗纹云纹，袖宽袍长，腰束深色带，庄重威严"
},
"萧云": {
 "desc":"22岁中国男性，身形颀长挺拔，剑眉星目，眼神清冷锐利，周身气质出尘，家族第一天才",
 "hair":"墨黑长发半束，发丝顺滑垂肩，额前留几缕碎发",
 "cloth":"月白色长袍，衣袂飘飘，袖口与领口绣淡金云纹，仙气出尘但写实布料质感"
},
}

art_style = "Chinese fantasy epic, majestic xianxia atmosphere, glowing spiritual energy effects, golden dragon aura, cinematic composition, high detail"

tpl = """仿真人写实风格，男性角色三视图（正面/侧面/背面并排全身立绘），纯白干净背景，柔光均匀打光，真实肌肤质感，浅景深，高清电影质感，中性偏冷色调。

人物：{name}。{desc}，面部轮廓干净利落，下颌线清晰，眉峰微扬，眼神沉稳克制，表情中性平静。

发型：{hair}。

服装：{cloth}。

姿态：三视图站立姿势，双臂自然下垂，中性无表情，全身完整可见（从头顶到脚底），三图比例一致。

【风格指令】{art_style}

禁止：水印、logo、文字、字幕、多余人物、卡通感、塑料感、比例失调、上身过长腿过短、夸张表情、复杂背景。
"""

out=[]
for name,info in chars.items():
    p = tpl.format(name=name, desc=info['desc'], hair=info['hair'], cloth=info['cloth'], art_style=art_style)
    out.append({'name':name,'prompt':p})

with open('/tmp/three_view_optimized.txt','w') as f:
    for o in out:
        f.write(f"===== {o['name']} =====\n{o['prompt']}\n\n")
print('精修版提示词生成完成')
