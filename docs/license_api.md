# 授权与设备接口（EXE 接入）

## 1. 激活绑定
**POST** `/api/license/activate`

请求：
```json
{
  "code": "ABCD-XXXX-XXXX",
  "device_fingerprint": "sha256:xxxx",
  "device_label": "WIN10-PC",
  "device_info": {"os":"windows","ver":"10.0.19045"}
}
```

响应：
```json
{
  "ok": true,
  "expire_at": "2026-04-16T10:00:00",
  "transfer_times_left": 1,
  "offline_hours": 24
}
```

## 2. 联网校验（获取离线 token）
**POST** `/api/license/verify`

请求：
```json
{
  "code": "ABCD-XXXX-XXXX",
  "device_fingerprint": "sha256:xxxx"
}
```

响应：
```json
{
  "ok": true,
  "token": "base64.payload.signature",
  "expires_at": "2026-03-17T11:00:00",
  "server_time": "2026-03-16T11:00:00"
}
```

## 3. 反激活（解绑设备）
**POST** `/api/license/deactivate`

请求：
```json
{
  "code": "ABCD-XXXX-XXXX",
  "device_fingerprint": "sha256:xxxx"
}
```

响应：
```json
{"ok": true}
```

## 4. 授权状态
**GET** `/api/license/status`

响应：
```json
{
  "ok": true,
  "items": [
    {
      "code": "XXXX",
      "card_type": "month",
      "expire_at": "2026-04-16T10:00:00",
      "status": 1,
      "transfer_times_left": 1,
      "device_limit": 1,
      "devices": [{"fingerprint":"sha256:xxxx","label":"WIN10-PC"}]
    }
  ]
}
```

## EXE 接入建议
- 启动时：读本地 token，验证是否过期
- 过期后：调用 `/api/license/verify` 续期
- 激活与反激活必须联网
