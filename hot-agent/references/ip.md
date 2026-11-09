# IP：账号自己的人设、头像、角色和声音

有固定的 IP，观众才记得住「又是这个号」。全部放在用户工作文件夹的 `热点/ip/` 里，**每样都是可选的**，缺哪样就用默认：

| 文件 | 是什么 | 谁用 | 没有时 |
|---|---|---|---|
| `ip.md` | 名字、人设、说话口气、口头禅 | `hot-script`：旁白和字幕用这个口气、第一人称写 | 中性口气 |
| `avatar.png` | 头像（正方形，脸在中间偏上） | `hot-render`：字幕条左边的圆形头像 | 不放头像（也认老位置 `热点/avatar.png`） |
| `stickers/bot1.png` … `bot7.png` | 角色拿着 7 样工具的贴纸 | `hot-render --style sticker`：替换画框边上的小机器人 | 用自带的小机器人 |
| `voice.json` | 配旁白用的 MiniMax 音色 | `hot-render`：稿子是 `voice: tts` 时配音 | 默认音色（电台男主播，语速 1.2） |

第一次用的时候问用户一次：「有没有自己的 IP（名字、人设、头像、声音）？」有就照下面建好，在 `热点/profile.md` 记一行：

图（头像、角色贴纸）有两种来法，**生图不是必须的**：

- 用户自己有图：照下面的尺寸和文件名放进去就行，不花钱。
- 让脚本画：`scripts/make_ip.py` 用 [Vizluma](https://docs.vizluma.online) 生图，一张 ¥0.20，整套（定稿图 + 头像 + 7 张贴纸）约 ¥1.8。**要先有 Vizluma 的 key 和生图额度**：Vizluma 是企业开通制，不能自助注册，找对接人开通、充额度、拿 key，设成环境变量 `VIZLUMA_API_KEY`。没有 key 就别跑这个脚本，用自己的图或者跳过（sticker 风格会用自带的小机器人，头像不放）。


```
- IP：热点/ip/（小数）；旁白 tts（音色见 ip/voice.json）
```

## ip.md

照这个格式写，短一点，越具体越好：

```markdown
# IP
- 名字：小数
- 一句话：爱算数的电竞老粉，用数据跟你聊比赛
- 口气：像跟朋友聊天，句子短；会吐槽，但不阴阳怪气
- 口头禅：「数不会骗人」（一条片子最多用一次，可以不用）
- 不说：脏话、「家人们」、「宝子们」
```

写稿时的用法（`hot-script` 照做）：

- 旁白用第一人称「我」，口气照「口气」那一行；「不说」那一行里的词一个都不许出现。
- 口头禅一条片子最多一次，放在最自然的地方（通常是结尾），别硬塞。
- 人设只影响**怎么说**，不影响**说什么**：数和事实照样全部来自 `facts.json`，不为了人设编经历（「我昨晚熬夜看完」这种没发生的事不写）。
- `writing.md` 里「不要这样写」那张表照样管用，人设不是写 AI 腔的理由。

## 让脚本画（可选，要 Vizluma 额度）

在用户的工作文件夹里运行（`<hot-agent的文件夹>/scripts/make_ip.py`）：

```bash
python3 <hot-agent的文件夹>/scripts/make_ip.py ref --desc "一只戴圆眼镜的橘色小猫，穿浅灰色连帽卫衣"   # 先只出定稿图 ref.png，给用户看
python3 <hot-agent的文件夹>/scripts/make_ip.py ref --photo 已有的角色图.png                              # 已经有角色图：直接当定稿图，不花钱
python3 <hot-agent的文件夹>/scripts/make_ip.py avatar                                                    # 头像
python3 <hot-agent的文件夹>/scripts/make_ip.py stickers                                                  # 7 张贴纸，自动抠透明
python3 <hot-agent的文件夹>/scripts/make_ip.py stickers bot2 bot4                                        # 只重出不满意的那几张
```

- **先出定稿图，用户点头再出别的**：后面每张都拿 `ref.png` 当参考图，定稿图不对后面全白花。
- 每次花钱前在回复里说一句要出几张、大约多少钱。
- 画风默认和 sticker 风格搭（铅笔线稿 + 淡水彩、Q 版）；要别的画风加 `--look "画风描述"`，整套用同一句。
- 生成请求失败（超时、断连）不会自动重发：图可能已经生成并扣费，让用户先看 Vizluma 控制台的调用记录。脚本默认直连，不走系统代理（长连接走代理容易被掐断）。
- 抠图要 Pillow（`pip install pillow`）。抠完打开看一眼，身上的白被抠掉的那张重出。

## stickers/（只有 sticker 风格用）

sticker 风格的画框边上站着一个角色，每种画面拿一样工具，跟着画面蹦。换成自己的角色就画 7 张：

| 文件 | 角色手里拿着 | 出现在哪种画面 |
|---|---|---|
| `bot1.png` | 放大镜 | 大数字（number） |
| `bot2.png` | 天平 | 两边对比（compare） |
| `bot3.png` | 剪刀 | 清单（list） |
| `bot4.png` | 铅笔 | 条形图（bars） |
| `bot5.png` | 画笔 | 标题（title） |
| `bot6.png` | 相框 | 评论原话（quote） |
| `bot7.png` | 指挥棒 | 站队投票（vote） |

- 透明底 PNG，竖幅，大约 300×420 的比例，角色站着、全身、脚在图的底边附近。
- 7 张要像一套：同一个角色、同一种画风。用 `make_ip.py stickers`（要 Vizluma 额度），或者你自己的生图工具：先出一张角色定稿，后面都拿它当参考图，只改「手里拿着什么」。
- 想跟默认画风搭：提示词里写「手绘绘本插画，铅笔线稿上淡淡的水彩，低饱和，米白、暖灰、浅木色，Q 版大约 2.5 头身；纯白背景，只画角色，周围留白，没有地面、阴影和文字」。
- 生图出来是白底的，用 `hot-render/scripts/cutout.py` 抠成透明底（要 Pillow：`pip install pillow`）：

  ```bash
  python3 <hot-render的文件夹>/scripts/cutout.py 热点/ip/stickers/bot1.png bot2.png ... --batch
  ```

  抠完打开看一眼：角色的线有缺口的话，身上的白色会被一起抠掉，那张重画。
- 缺哪张，那种画面就用自带的小机器人。

## voice.json（配旁白时用）

配音用 MiniMax 的语音合成（speech-2.8-hd）。

```json
{"voice_id": "Chinese (Mandarin)_Radio_Host", "speed": 1.2}
```

| 字段 | 意思 | 默认 |
|---|---|---|
| `voice_id` | 音色。系统音色见 MiniMax 开放平台文档的「系统音色列表」；也可以填自己复刻出来的音色 id | `Chinese (Mandarin)_Radio_Host`（电台男主播） |
| `speed` | 语速，在这里设，**别后期加速**（音色会发尖） | 1.2 |
| `model` | `speech-2.8-hd`（好听）/ `speech-2.8-turbo`（便宜一点） | `speech-2.8-hd` |
| `vol`、`pitch`、`emotion` | 音量、音调、情绪，一般不用填 | — |

- **用自己的声音**：在 MiniMax 开放平台用「快速复刻」上传一段自己说话的录音（十几秒、安静、一个人说），拿到音色 id 填进 `voice_id`。复刻按次收费（第一次用这个音色合成时扣），以平台上写的价格为准。只能复刻你自己或者拿到授权的人的声音。
- **换音色先试听**：同一句开头台词，候选音色各生成一条，让用户自己听了选。一个账号定了声音就别老换。
- 密钥：环境变量 `MINIMAX_API_KEY`（在中国大陆以外用，再设 `MINIMAX_API_HOST=https://api.minimax.io`）。**别让用户把密钥贴进对话**。没有密钥也能配：`render.py` 会列出每屏要念的字，用户在 MiniMax 网页「文本转语音」里用同样的音色、语速生成，下载后按屏 id 存进 `热点/日期/voice/`（`s1.mp3`、`s2.mp3`……）再跑。
- 用户自己录的旁白也照这个名字放进 `voice/`，脚本不会覆盖。
