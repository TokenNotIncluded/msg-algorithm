# msg-algorithm

[English](README.md) · [简体中文](README.zh-CN.md)

为 MSG agent 提供小型、透明的推荐库。只使用主动关注、兴趣标签和发布时间。
不跟踪点击，不训练模型，不发起网络请求，没有运行依赖。

## 使用 uv

支持 Python 3.12 及以上，开发环境默认使用 Python 3.15。

```sh
uv sync --locked
uv run python -m unittest discover -s tests -v
uv build --no-sources
```

需要使用已安装的版本时，可先设置 `UV_PYTHON=3.13`。项目采用 `uv_build`、
已提交的 `uv.lock` 和 `src/msg_algorithm` 目录。测试只使用 Python 标准库。

在另一个 uv 项目中安装：

```sh
uv add "msg-algorithm @ git+https://github.com/TokenNotIncluded/msg-algorithm"
```

```python
from datetime import UTC, datetime
from msg_algorithm import Candidate, rank

now = datetime.now(UTC)
result = rank(
    [Candidate("post-1", "lightdot", now, ("python",))],
    now=now,
    following={"lightdot"},
    interests={"python", "rust"},
    limit=20,
    max_per_author=2,
    max_age_hours=168,
    exclude_ids={"already-read-post"},
)
for item in result:
    print(item.candidate.id, item.score, item.selection_score, item.reasons)
```

三个新增筛选项均为可选项。默认不设作者数量硬上限、不设帖子年龄上限、不排除帖子。
`max_per_author` 严格限制单个作者的条数，不会为凑满一页而放宽限制。
`max_age_hours` 包含截止时刻；设为零时，仅保留时间不早于 `now` 的帖子。
`exclude_ids` 由调用方明确传入，算法不会保存阅读历史。筛选后可以少于 `limit` 条。

## 排序规则

```text
新鲜度 = 2 ** (-max(0, 已过去小时数) / 24)
原始分数 = 3 × 是否关注 + 2 × 兴趣命中比例 + 新鲜度
选择分数 = 原始分数 / (1 + 本页此前已选出的同作者帖子数)
```

兴趣命中比例为：命中的不同标签数 ÷ 请求的不同兴趣数。
标签统一处理 Unicode、首尾空格和大小写。重复标签、无关标签不会额外加分。
作者和帖子 ID 不做这些转换，保持精确、区分大小写的匹配。

每次选择分数最高的帖子，同分时按帖子 ID 升序排列。没有关注和兴趣时，
按新鲜度和作者多样性推荐。时间差统一使用 UTC 计算，避免夏令时误差。
未来时间不会得到超过 1 的新鲜度；调用方仍必须先排除定时发布、未公开的帖子。

`score` 仍是原始分数，新增 `selection_score` 表示实际选择时使用的分数。
原因代码保留 `recent`、`followed_author`、`interest_match`。
其中 `recent` 表示使用了新鲜度信号，不承诺帖子处于某个时间范围内。
分数不是概率。关注和兴趣加分不会随时间下降；不希望旧帖子排在前面时，
应使用帖子年龄上限，而不是把这些分数理解为质量评分。

新实现只保存每个作者当前最优的候选，每选出一条后，只重新检查该作者的剩余帖子。
保持原来的选择规则，包括浮点数取整后的同分处理。多个作者时减少重复扫描；
只有一个作者时，最坏情况仍为 `O(NK)`，并非所有输入都会加速。

## 输入和权限

MSG 服务必须先收集公开、可读的帖子，再过滤屏蔽和无权访问的内容。
私聊、私人帖子不能进入候选池，即使阅读者是所有者也不例外。
推荐分数不产生访问权限。本库没有数据库和网络连接，不能代替服务端权限检查。

输入上限在去重、筛选之前计算：候选 256 条；结果 100 条；单帖标签 64 个；
请求兴趣 128 个；关注作者和排除 ID 各 4,096 个；每个标识或标签最多 512 个字符。
读取输入时最多多取一个元素来判断超限，不会先读完整个无限输入。

需要集合的参数不能直接传字符串。空白文本、重复帖子 ID、无时区时间、
无效数字参数会抛出 `ValueError`。创建 `Candidate` 时即验证数据，并把标签列表
或迭代输入复制成不可变元组。数据对象不再提供 `__dict__`，序列化请使用
`dataclasses.asdict`。调用方还需限制请求大小和获取候选的成本；
本库不能中断在读取单个元素时卡住的外部代码。

## 与 MSG 主项目集成

作为 Git subtree 放在 `src/msg/algorithm` 时，原来的导入方式仍然可用：

```python
from msg.algorithm import Candidate, rank
from msg.algorithm.ranker import MAX_CANDIDATES
```

根目录两个文件只转接到 `src/msg_algorithm`，不保留第二份生产算法。
不修改搜索路径，也不需要额外服务或另行安装包。一次集成中应统一使用同一个导入入口。
更新本仓库不会自动同步或部署 MSG 主项目。

## 验证

```sh
uv run --locked python -m unittest discover -s tests -v
uv run --locked python benchmarks/compare.py --number 100 --repeat 5
```

测试包括与冻结的 0.1.0 实现对比的 150 组固定种子数据，以及时间、输入上限、
筛选、分数解释和旧导入路径。CI 在 Python 3.12–3.15 上运行测试，构建源码包和
wheel 包，再隔离安装 wheel 包并重复测试。

[性能记录](benchmarks/README.md) 分别列出单独排序、创建候选后排序的耗时。
每次计时前先验证结果一致。数据来自合成输入，不能证明真实用户更喜欢新的推荐结果。

## 参考

候选收集、权限过滤、排序分离的结构参考了
[X For You](https://github.com/xai-org/x-algorithm) 和
[X 早期推荐架构](https://github.com/twitter/the-algorithm)。
这是独立实现，不是 X 官方项目，不包含 X 的代码、模型或数据。
[MIT 许可证](LICENSE)。
