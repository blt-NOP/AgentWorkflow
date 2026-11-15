# 当前 API

## GET /api/health

返回 HTTP 200：

```json
{"status": "ok", "stage": "scaffold", "model_configured": false}
```

`model_configured` 仅表示地址、模型名和密钥是否均已填写，不代表服务可用。响应不包含配置值或密钥。

## POST /api/chat

请求体：

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "我关注边缘推理，希望讨论一个四周内能验证的 idea"
}
```

`session_id` 必须为 UUID；`message` 去除首尾空白后不能为空，原始长度最多 10000 个字符。无效输入返回 HTTP 422。

目前有效请求返回 HTTP 501：

```json
{
  "detail": {
    "code": "AGENT_NOT_IMPLEMENTED",
    "message": "项目框架已就绪，模型、工具与多轮记忆尚未接入；本次消息未保存。",
    "session_id": "550e8400-e29b-41d4-a716-446655440000"
  }
}
```

不调用模型、不执行工具、不保存消息。前端中的讨论编号仅在当前页面内存中存在，刷新后重建；服务端会话隔离尚未实现。

## 静态页面与接口文档

- `GET /`：讨论页面。
- `GET /static/...`：前端静态资源。
- `GET /docs`：FastAPI 交互文档。

## 后续接口设计

聊天成功响应、论文上传、会话查询和清除、执行轨迹查询将在实现业务时定义。当前不承诺这些接口已存在。
