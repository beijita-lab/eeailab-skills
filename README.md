# eeailab：伊伊 AI 成长实验室 Skills

`eeailab` 是一个面向 AI 时代家庭成长的开放 skill 系统。

当前已包含：

- `montessori/`：家庭蒙氏实践教练，用于帮助父母理解孩子行为、调整家庭环境、实践观察、独立、秩序、自由与纪律。
- `picturebook/`：亲子绘本创作导演，用于需求澄清、故事分镜、文案对白、绘本提示词和打印检查。

规划中的方向：

- `english-initiation/`：中国家庭英语启蒙规划；
- `blueprint/`：AI 时代通才成长蓝图；
- `ai-literacy/`：儿童与父母的 AI 综合能力；
- `money-literacy/`：儿童财商与价值理解；
- `venture-project/`：小小创业与项目制成长。

## 使用方式

在支持 skill 的 Agent 环境中触发：

```text
$eeailab-montessori
$eeailab-picturebook
```

也可以用自然语言触发：

```text
蒙氏怎么看孩子这个行为？
家庭蒙氏怎么做？
孩子不收玩具怎么办？
用 eeailab-picturebook 帮我做一本孩子收玩具的亲子绘本。
```

## 目录说明

```text
eeailab/
├── README.md
├── montessori/
│   ├── SKILL.md
│   ├── book-digest.md
│   └── cards/
└── picturebook/
    ├── SKILL.md
    ├── framework.md
    ├── cards/
    ├── templates/
    └── examples/
```

## 边界

本项目提供家庭教育和成长规划思路，不替代医疗、心理、发育评估、法律或投资建议。
