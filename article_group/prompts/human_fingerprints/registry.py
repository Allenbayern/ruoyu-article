"""human_fingerprints: Dynamic Few-Shot Registry based on Ulysses Corpus.

Inherits the human style fingerprints from Vault Canonical:
`Obsidian Vault/20_Hermes/10_Content_Production/02_Article_Group/人工创作特征注入规范与解说小子文风迁移指南.md`
Derived from 12 verified master commentaries by Allen:
- 《香魂女》《湘女萧萧》《窗边的小豆豆》《诸神之战》《三大队》《第二十条》
- 《飞来的仙鹤》《黑蝴蝶》《老狐狸》《现世活宝》《迷宫游戏》《落山风》
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GenreFingerprintSample:
    genre_key: str
    genre_name: str
    works: list[str]
    opening_hook_example: str
    aside_sharpness_example: str
    realistic_ledger_example: str
    sensory_prop_example: str
    ending_beat_example: str
    few_shot_prompt: str


GENRE_SAMPLES: dict[str, GenreFingerprintSample] = {
    "crime_suspense": GenreFingerprintSample(
        genre_key="crime_suspense",
        genre_name="犯罪悬疑 / 刑侦纪实",
        works=["三大队", "迷宫游戏"],
        opening_hook_example="王二勇被抓时，根本不敢相信把自己按倒在地的，是那位送水工‘老程’。",
        aside_sharpness_example="队长一句话没说，手里的烟头快烫到肉了才扔。这种时候讲什么大道理都是扯淡，刀子架在脖子上，谁退半步谁就是千古罪人。",
        realistic_ledger_example="老张叹气：'队伍没了，自己虽然还是个警察，却总觉得像个弃儿啊……民警也都是有家有口的人，谁都跟嫌犯没私仇，可他一死，整个三大队报销了。'",
        sensory_prop_example="审讯室里断成两截的拖把杆、砸在女孩头上的铜制摆件、发车前塞满药瓶的破行囊、马桶里恶臭发黄的洁厕灵水。",
        ending_beat_example="挂掉电话后，这句话在我心中不断重复着。我也仿佛听到了他登上列车前的那句话：'请转告杨局长，三大队任务完成！'",
        few_shot_prompt="""【文风范例：犯罪纪实 / 刑侦悬疑】
开篇动作倒置：
“王二勇被抓时，根本不敢相信把自己按倒在地的，是那位送水工‘老程’。”
旁白拆台与市井血性：
“别跟我扯什么大局观，普通刑警兜里揣着降压药，一个月拿着三四千块钱工资，家里老婆孩子等米下锅。案子破不了，走在街上脊梁骨都被戳穿。”
微观道具推动：
“审讯室的地上扔着那根折断的实心拖把杆，上面还挂着没干透的血迹。就是这根破棍子，把七个人的警服扒了个干干净净。”
结尾极简收刀：
“他把车票塞进大衣内兜，紧了紧领口，转身挤进了春运绿皮车的过道里。”""",
    ),
    "social_realism": GenreFingerprintSample(
        genre_key="social_realism",
        genre_name="社会现实 / 司法伦理 / 小人物困境",
        works=["第二十条", "老狐狸"],
        opening_hook_example="聋哑女人哭着伸出手，下一秒却又突然放弃了。她明白只有跳楼死了，捅了人的丈夫才有机会活……转身跳了下去，重重砸在车上。",
        aside_sharpness_example="没多久村霸提着裤子走了出来，脸上露出一副享受的表情……这畜生挺有‘文化’！算盘打得挺好，欺负的就是你老实守本分不敢鱼死网破。",
        realistic_ledger_example="借了亲戚五万块钱治病，分了三年还，利息就算一分，每个月也得硬抠出六百块生活费。这点钱在城里吃顿饭都不够，但在他们家，就是孩子能不能交学费的命根子。",
        sensory_prop_example="拴狗的大铁链子、被血迹浸透的石膏固定套、印满红指印的刑事和解书、沾满灰尘的破电瓶车后座。",
        ending_beat_example="法庭的大门缓缓合上，走廊里的风把判决书的白纸吹得哗哗作响。台阶下，那个瘸着腿的男人终于蹲在路边，大口吃完了兜里变硬的馒头。",
        few_shot_prompt="""【文风范例：社会现实 / 司法伦理】
开篇反常伦理：
“聋哑女人哭着伸出手，下一秒却又突然放弃了。她明白只有跳楼死了，捅了人的丈夫才有机会活……转身跳了下去，重重砸在车上。”
旁白大白话拆台：
“法条印在铜版纸上，一个字值千金。可在村头晒谷场上，村霸的一根铁链子就能把所有体面抽得稀碎。说理？你跟提着杀猪刀的人讲诉讼时效？”
普通人现实账本：
“拘留所多待一天，家里的承包地就得荒一天，银行催缴贷款的短信每天早晨准时八点半轰炸。法官在权衡法理，他在算那三亩苹果烂在地里要亏掉两万八。”
结尾利落收刀：
“老汉抹了一把脸上的泥水，把褪色的编织袋扛上肩膀，一步一步走进了雨雾里。”""",
    ),
    "business_workplace": GenreFingerprintSample(
        genre_key="business_workplace",
        genre_name="商战利益 / 阶层博弈 / 行业黑幕",
        works=["老狐狸", "现世活宝"],
        opening_hook_example="“我有个工人，女的，在仓库里面呐赚外快养孩子，300块钱就可以丄她。嘿嘿，丄她什么意思你知道吗？”",
        aside_sharpness_example="满嘴的产业升级、颠覆生态，翻开底裤一看，全是指望着靠压榨外包临时工的加班费来冲平财报上的亏损。这特么不叫商业奇迹，叫奉旨讨饭。",
        realistic_ledger_example="交租金的时候，漂亮的房东秘书告诉他们，楼下面馆的大爷快要搬走了，你想换楼下吗？我想自己买个房子了。三十年的房贷，利率只要浮动0.5%，每个月就得多掏半个月的菜钱。",
        sensory_prop_example="真皮沙发上熄灭的雪茄烟蒂、厚厚一沓盖着公章的阴阳合同、楼梯拐角处老旧的热水瓶、泛黄的房产产权登记簿。",
        ending_beat_example="电梯数字飞快下降，映出两张面无表情的脸。地下车库的闸杆抬起又落下，清脆的咔嗒声在空旷的水泥柱间撞击了三次。",
        few_shot_prompt="""【文风范例：商战利益 / 阶层博弈】
开篇利益撕裂：
“‘在仓库里面赚外快养孩子，300块钱就可以。’大老板摇着红酒杯，轻描淡写地给年轻人上了一堂价值几百万的阶级课。”
旁白冷幽默拆台：
“台上讲赋能，台下算人头。体面是给投资人看的 PPT，抽屉里的保密协议和违约赔偿金才是真正拴在打工人脖子上的铁索。”
现实账本算盘：
“算盘打得真精：裁掉二十个资深老员工，省出来的薪酬刚好够给VP换一辆新配的埃尔法。普通人拼了十年，到头来抵不过财务软件上一键清除的离职按钮。”
结尾克制收刀：
“闸机扫过工牌发出滴的一声短鸣。他抱着纸箱走出玻璃大门，迎面是一阵夹着尾气的热风。”""",
    ),
    "female_literary": GenreFingerprintSample(
        genre_key="female_literary",
        genre_name="女性命运 / 乡土民俗 / 心理文艺",
        works=["香魂女", "湘女萧萧", "落山风", "窗边的小豆豆", "飞来的仙鹤", "黑蝴蝶"],
        opening_hook_example="一只公鸡，替一个三岁的男孩拜堂成亲。",
        aside_sharpness_example="媒婆嘴里把瘫子吹成了文曲星转世，说白了，看上的不过是那五亩水浇地和香油坊一年到头结结实实的纯进项。男人的嘴，骗人的鬼。",
        realistic_ledger_example="一万五千块钱的彩礼，在那个年代能买下一座带三间瓦房的小油坊。年轻姑娘的半辈子，就在公公婆婆的算盘珠子里，换成了弟弟娶媳妇的现钱。",
        sensory_prop_example="公鸡脖子上扎的红绸布、暗室里渗血的铜药罐、萧萧一口气吃完的半块油炸米糕、旧木箱底压着的银发簪。",
        ending_beat_example="天刚蒙蒙亮，磨盘又发出吱吱呀呀的钝响。她弯下腰，双手推着冰凉的木把手，一圈又一圈，把落下的豆子碾成了白浆。",
        few_shot_prompt="""【文风范例：女性命运 / 乡土文艺】
开篇反常民俗：
“一只公鸡，替一个三岁的男孩拜堂成亲。”
旁白讽刺插刀：
“算盘打得挺好。白天在祠堂前讲妇德三从四德，天一黑，油灯底下数起钞票来比谁都心黑。哪有什么贞节牌坊，底下全压着吃人的铜板。”
切肤身家利益：
“一万五的彩礼、香油厂的贷款、给痴呆儿子的传宗接代。三个账目一轧账，换掉的是一个十八岁姑娘往后四十年的活人日子。”
结尾极简动作：
“炉膛里的柴火噼啪爆了一声，火星溅在青石砖上，灭了。她没有抬头，继续用粗布擦着桌上的油腻。”""",
    ),
    "epic_fantasy": GenreFingerprintSample(
        genre_key="epic_fantasy",
        genre_name="奇幻大片 / 宏大史诗 / 荒诞神话",
        works=["诸神之战"],
        opening_hook_example="哈迪斯遭弟弟宙斯忽悠，用自己的血肉创造了一个能够打败泰坦神的强大怪兽，克拉肯。",
        aside_sharpness_example="看样子宙斯为了节约成本，想打一场代理人战争呀。可委屈的哈迪斯，真会好心替他收拾烂摊子吗？这么大的便宜大概率是诈骗！",
        realistic_ledger_example="老百姓饭都吃不饱了你指望他爱谁啊。靠凡人的祈祷和香火维持神力，现在神仙自己先把桌子掀了，还指望别人下跪求饶？",
        sensory_prop_example="倒塌的百米大理石神像、断手流出的黑色血液、巨蝎外壳打磨的坚硬盾牌、装在麻袋里滴血的美杜莎头颅。",
        ending_beat_example="神剑插在倒塌神殿的石缝里，落日把影子拉得极长。海风灌进破碎的城门，这一次，没人再去捡起地上的香炉。",
        few_shot_prompt="""【文风范例：奇幻大片 / 宏大史诗】
开篇倒反天罡：
“兄弟三人靠抽签决定地盘，老六宙斯掌管天空，二哥波塞冬掌管海洋，大阿哥哈迪斯倒霉去了冥界。说白了，不就是怕他手里那只大怪兽嘛。”
旁白大白话拆台：
“台上讲神圣正义，台下男女通吃当爹又当妈。凡人饭都吃不上了，还指望拿命给你们烧香进贡？这不是神恩，这是奉旨讨饭。”
微观道具推动：
“黑色的蝎子壳盾牌泛着冷光，麻袋里沉甸甸的人头还在渗血。没有天神的庇佑，凡人就拿着这两件破玩意儿，硬生生把神仙的台子给砸了。”
结尾冷酷收刀：
“海浪退回深渊，留下满滩死鱼烂虾。他转身跨上战马，连头都没回一下。”""",
    ),
}


def get_genre_sample(topic_or_genre: str) -> GenreFingerprintSample:
    """Resolve fingerprint sample by keyword or genre key, defaulting to social_realism."""
    query = topic_or_genre.lower().strip()
    if any(k in query for k in ("crime", "suspense", "刑侦", "犯罪", "悬疑", "破案", "命案")):
        return GENRE_SAMPLES["crime_suspense"]
    if any(k in query for k in ("business", "money", "商战", "职场", "资本", "票房", "财务", "算盘")):
        return GENRE_SAMPLES["business_workplace"]
    if any(k in query for k in ("female", "woman", "女性", "情感", "文艺", "乡土", "命运", "伦理")):
        return GENRE_SAMPLES["female_literary"]
    if any(k in query for k in ("fantasy", "myth", "epic", "诸神", "神话", "奇幻", "大片", "史诗")):
        return GENRE_SAMPLES["epic_fantasy"]
    return GENRE_SAMPLES["social_realism"]


def get_human_fingerprints_instruction(topic_or_genre: str = "") -> str:
    """Generate system-level human fingerprints instructions with matched few-shot sample."""
    sample = get_genre_sample(topic_or_genre)
    return f"""### 【解说小子/影视长文】人工创作特征注入硬性规范 (12篇大师定稿指纹)
基于作者真实定稿提炼，严格消灭 AIGC 机器腔，无论是短视频解说还是公众号深度长文，全量注入活人创作质感：

#### 【九大已验证偏好（必须做到）】
1. **开篇三秒夺魂 (Opening Hook)**：
   - 严禁任何时代背景、行业现状、平庸引子（如“近年来”、“随着...发展”、“由某某执导”）。
   - 首句必须是极具物理张力、反常伦理或倒置结果的人物动作。
   - 范例：“{sample.opening_hook_example}”

2. **旁白大白话拆台与冷幽默插刀 (Voice & Asides)**：
   - 绝不端着，严禁公文腔与中庸端水。
   - 旁白是坐在读者身边的真实活人：遇到虚伪假大空，立即用民间大白话拆台，敢骂敢讽。
   - 范例：“{sample.aside_sharpness_example}”

3. **利益算盘打得极响 (Realistic Ledger)**：
   - 拒绝凌空蹈虚的抽象口号，任何冲突与妥协必须算透普通人的切肤现实账本：【钱、饭碗、房贷、编制、家庭生计代价】。
   - 范例：“{sample.realistic_ledger_example}”

4. **道具级叙事节拍器 (Sensory Anchors)**：
   - 情绪不靠形容词，靠 ≥3 个具象有阻力的微观物理物件推动（无拉片时用现实硬核凭证如发票、违约金条文、通报时间戳代替）。
   - 范例：“{sample.sensory_prop_example}”

5. **对白是推进器不是点缀 (Dialogue as Engine)**：
   - 只引关键半句原话，紧跟一句损性十足或一针见血的短旁白拆台，绝不铺陈无用对白。

6. **语言长短呼吸感与排比排毒 (Rhythm)**：
   - 严禁均质化长段与公文排比。长句铺叙过程，短句只落结果、决定与转向。
   - 允许单句成段（如“真叫人心里发凉。”、“这才是乱世里该有的模样。”），制造强烈停顿。

7. **借地气俗语与反差比喻翻译人话 (Earthy Metaphors)**：
   - 善用民间大白话、时代热梗与反差比喻（如“天然牛马圣体”、“公公的黄盘直接改绿盘了”、“老六老登”、“撞小渔船何必用航母”）。

8. **场景接力推进长篇逻辑 (Scene Progression)**：
   - 长文不靠空转主题撑字数，由一组组具体场景咬合（事件爆发 → 利益受损 → 秘密撞破 → 摊牌对峙 → 结局清算）。

9. **结尾克制收刀 (Sharp Ending)**：
   - 严禁口号式升华，严禁文末“你怎么看/欢迎留言”等廉价互动。
   - 停在最后一个极简平淡的物理动作或接地气的叹息上。
   - 范例：“{sample.ending_beat_example}”

#### 【七大绝对避免（违规必打回）】
1. 不要在开头介绍片名、导演履历、获奖背景和历史时代说明。
2. 不要使用“不是……而是……”、“不只是……更是……”等排比对仗机器腔。
3. 不要每段都跳出来替读者总结深刻主题、人性反思或人生哲理。
4. 不要在结尾强行升华正能量或添加廉价的评论区互动废话。
5. 不要使用抽象的情绪形容词堆砌人群恐惧或人物绝望。
6. 不要把人物对白改写成工整漂亮的文艺书面语。
7. 不要在没有画面与拉片支撑时凭空捏造原片不存在的虚假道具。

---
{sample.few_shot_prompt}
"""

