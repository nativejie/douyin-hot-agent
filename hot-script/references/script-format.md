# 稿子格式（script.json / facts.json）

写稿这一步产出这两个文件，下一步（出画面）只读它们，所以字段要写全。

## facts.json：所有用到的事实和数

```json
{"facts": [
  {"id": "f1", "text": "T1 3:1 战胜 KC，晋级 S16 四强", "value": "3:1",
   "source": {"name": "英雄联盟官方抖音", "url": "https://..."}, "level": "官方"},
  {"id": "f2", "text": "模拟 10 万次后 GEN 夺冠概率", "value": "49.4%",
   "source": {"calc": "calc/champ.py", "input": "S16/model/result_semi.json"}, "level": "计算"}
]}
```

- `level`：官方 / 权威媒体 / 转载或品牌自述 / 计算 / 用户自有数据 / 评论原话。
- 一条 fact 有好几个值时，`value` 写成数组：`["49.4%", "24.5%"]`，或者拆成几条。
- 用户自有数据在工作文件夹外面时，`source.input` 写相对用户工作区的路径（例：`S16/model/result_semi.json`），**不要写带本机用户名的绝对路径**；脚本里用环境变量或命令行参数传路径。
- 计算出来的数，`source.calc` 写脚本路径，**相对 `热点/今天日期/`**（例：`calc/percap.py`），脚本要能重跑出同样的数。
- 写法不同的同一个数检查脚本认得（2.80 = 2.8），差 1 万倍的单位换算也认得（20334 亿 = 2.03 万亿）；别的换算（百分比 ↔ 成数、相除得出的新数）要在 `value` 里写上换算后的值。
- 查不到的事实**不要放进来**，也不要写进稿子。

## script.json：一屏一屏的稿子

```json
{"word": "热榜原词", "angle": "角度",
 "voice": "none",
 "target_seconds": 90,
 "corner": "AI 模拟观点·仅供参考",
 "titles": {"douyin": ["≤30 字，2–3 条"], "xhs": ["≤20 字"], "bilibili": ["≤80 字"]},
 "tags": ["#话题1", "#话题2"],
 "scenes": [
  {"id": "s1", "seconds": 3,
   "visual": {"type": "number", "value": "29.9%", "from": "21.8%", "label": "LPL 夺冠概率"},
   "caption": "LPL 夺冠概率涨了",
   "narration": "",
   "facts": ["f2", "f3"]}
 ]}
```

- `voice`：`none` = 不配旁白（纯字幕 + 音乐，`narration` 全留空，信息全靠 `caption` 和画面）；`tts` = 配旁白（每屏的 `narration` 要写，`caption` 是这屏的大字重点，不是旁白全文）。配旁白时出画面那一步用 MiniMax 念 `narration`，字幕条显示正在念的那句；`narration` 里可以写 MiniMax 的标记：`<#0.4#>` 停顿（两个能念出来的字之间）、`(laughs)` `(sighs)` `(chuckle)` 这类语气声（一条片子三五处就够）、`行(hang2)` 纠正读音，字幕里会自动去掉。
- `seconds`：这一屏停多久。不配旁白时 2–4 秒；配旁白时按字数估（每秒约 5 个字），出画面时会按配音的实际长度重算。
- `caption`：屏幕上最大的那行字，**不超过 14 个字**，手机上要一眼读完。
- `facts`：这一屏用到的事实 id。**画面和字里每一个数（包括比分、日期、名次）都要能在这些 fact 里找到。**
- `corner`（可选，顶层）：全片一直挂着的角标小字，比如「AI 模拟观点·仅供参考」。
- `target_seconds`：按实际的屏数和秒数填；删了 brief 里的段，就跟着减。

### visual 的类型（出画面那一步只认这几种）

| type | 用来 | 字段 |
|---|---|---|
| `title` | 大字标题、开场、转场 | `text`（≤12 字），`sub`（可选小字） |
| `number` | 一个扎眼的数，可从旧值滚到新值 | `value`，`label`（≤12 个汉字宽，英文数字算半个；百分比屏有时会排成圆环、标签放在旁边），`from`（可选，滚动起点；不写就从 0 滚。非 0 的 `from` 会在画面上划掉显示「旧值 →」，**只能是同一个数以前的值**（例：比赛前 38.2% → 比赛后 24.5%），「假如 KC 晋级」这种反事实的数不能放 `from`，用 `compare` 左右摆）。旧值也要有出处 |
| `bars` | 排名、几项比大小 | `title`，`items: [{name, value, unit}]`（≤6 项），`highlight`（可选，高亮哪项） |
| `compare` | 两边对比（A vs B、之前 vs 之后） | `left: {name, value, note}`，`right: {name, value, note}` |
| `list` | 清单，逐条出现 | `title`，`items`（≤5 条，每条 ≤16 字） |
| `quote` | 原话卡（评论、采访、官方说法） | `text`（≤40 字），`who` |
| `vote` | 结尾站队按钮 | `question`（≤10 字），`options`（2–4 个） |

每种画面都可以加一个 `kicker`（≤ 20 字）：画面顶上的一行小字，交代背景（「四强出齐 · AI 模拟 10 万次」）。

一屏只放一件事。要讲两件事就拆成两屏。
