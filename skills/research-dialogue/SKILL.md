---
name: research-dialogue
description: 根据已有论文与用户资源逐轮澄清科研选题，先确认方向与条件，再讨论目标和基线；不用于保证创新性或代替实验验证。
---

# 科研选题逐轮追问

每轮围绕当前研究问题给出简短分析，区分论文已有证据与待验证假设。优先确认资源缺项，再澄清研究目标和可复现基线。
程序按下面的 questions 顺序选择第一个尚未回答的问题。已知 facts 不重复询问；answers 保存讨论答案。
外层程序会展示当前问题和选项，模型正文无需再另提问题。用户可以点击选项，也可以输入文字；不把选项当作已经验证的研究结论。
缺少材料时应说明证据不足，不能只凭题名提出有把握的创新结论。条件更正后按最新 facts 分析。
用户阅读笔记只能作为用户理解和兴趣的线索，不能当作论文原文或已被验证的研究结论。

修改下列 JSON 中的问题顺序、文本或选项，即可修改应用的提问策略；下次请求会重新读取，无需重启服务。

```json
{
  "questions": [
    {"target": "facts", "field": "direction", "question": "你目前主要关注哪个研究方向？", "options": [
      {"label": "边缘端推理", "value": "边缘端推理"}, {"label": "模型压缩", "value": "模型压缩"}, {"label": "检索增强生成", "value": "检索增强生成"}]},
    {"target": "facts", "field": "compute", "question": "你可以使用哪些计算资源？", "options": [
      {"label": "只有 CPU", "value": "CPU"}, {"label": "可以使用 GPU", "value": "GPU"}, {"label": "算力尚未确定", "value": "尚未确定"}]},
    {"target": "facts", "field": "weeks", "question": "你计划投入多少周完成最小验证？", "options": [
      {"label": "2 周", "value": 2}, {"label": "4 周", "value": 4}, {"label": "8 周", "value": 8}]},
    {"target": "facts", "field": "dataset", "question": "你目前具备哪些数据条件？", "options": [
      {"label": "使用公开数据集", "value": "公开数据集"}, {"label": "已有自己的数据", "value": "已有数据"}, {"label": "还需要寻找数据", "value": "尚无数据"}]},
    {"target": "answers", "field": "goal", "question": "你希望优先改善哪个可测量的指标？", "options": [
      {"label": "推理延迟", "value": "推理延迟"}, {"label": "模型效果", "value": "模型效果"}, {"label": "内存占用", "value": "内存占用"}]},
    {"target": "answers", "field": "baseline", "question": "针对这个目标，目前是否有可复现的对照基线？", "options": [
      {"label": "已有可复现基线", "value": "已有可复现基线"}, {"label": "需要先查找基线", "value": "需要先查找基线"}, {"label": "还不确定", "value": "还不确定"}]}
  ],
  "final_question": "根据当前目标和基线，你准备先验证哪个单一改动，并采用什么对照实验？"
}
```
