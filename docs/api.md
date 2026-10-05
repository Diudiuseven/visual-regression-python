# HTTP API

所有图像均以 base64 编码的 PNG/JPEG 放在 JSON 字段 `candidate` 中。
服务默认挂在 `/api/v1` 前缀下；差异图通过独立的进程内下载端点获取，
对比响应本身保持 JSON。

## POST /api/v1/compare

对单个用例做截图回归对比。

```json
{
  "case_id": "home-hero",
  "candidate": "<base64 png/jpeg>",
  "version": null,
  "ignore_regions": [
    {"x": 10, "y": 20, "width": 100, "height": 40}
  ],
  "config": {
    "pixel_tolerance": 16,
    "change_ratio": 0.01,
    "min_cluster_size": 1,
    "auto_register": true
  }
}
```

- 用例首次出现时默认自动把候选图登记为基准 v1，返回 `success`，
  `baseline_version: 1`。
- `version` 省略时与最新已批准版本对比；传数字时与指定历史版本对比。
- 返回示例（有差异）：

```json
{
  "case_id": "home-hero",
  "action": "compare",
  "status": "diff",
  "baseline_version": 2,
  "artifact_id": "ab12...",
  "diff_image_url": "/api/v1/artifacts/ab12...",
  "summary": {
    "verdict": "diff",
    "changed": true,
    "changed_pixels": 64,
    "ratio": 1.0,
    "considered_pixels": 64,
    "ignored_pixels": 0,
    "cluster_count": 1
  },
  "error_code": null,
  "error": null
}
```

无差异时 `status` 为 `no_diff`，其中 `changed_pixels` / `ratio` 表示
变化像素数与变化面积比例（忽略区域之外）。

## 基准审批流

### POST /api/v1/baselines/propose
```json
{"case_id": "home-hero", "candidate": "<base64>", "note": "改版", "proposed_by": "alice"}
```
暂存一次替换，不改变当前生效基准。返回 `success`。

### POST /api/v1/baselines/approve
```json
{"case_id": "home-hero", "approved_by": "reviewer-bob"}
```
把暂存候选原子地追加为下一个版本。无暂存时返回 404
`pending_change_not_found`。

### POST /api/v1/baselines/reject
```json
{"case_id": "home-hero"}
```
丢弃暂存替换。

### GET /api/v1/baselines/{case_id}/history
返回完整版本历史（版本号、时间、备注、审批人、图像字节数）：
```json
{"case_id": "home-hero", "versions": [{"version": 1, ...}, {"version": 2, ...}]}
```

## POST /api/v1/batch

一次提交多组动作，混合 `compare / propose / approve / reject`：

```json
[
  {"case_id": "a", "candidate": "<base64>"},
  {"case_id": "b", "candidate": "<base64>", "ignore_regions": [], "config": {"change_ratio": 0.02}},
  {"action": "approve", "case_id": "b", "approved_by": "bob"}
]
```

单组失败被隔离，其他组继续执行。汇总计数：

```json
{
  "total": 3,
  "success": 1,
  "no_diff": 0,
  "diff": 1,
  "failed": 1,
  "items": [ {"status": "success", "...": "..."}, {"status": "diff", "...": "..."}, {"status": "failed", "error_code": "...", "error": "..."} ]
}
```

## GET /api/v1/artifacts/{artifact_id}

下载差异标注 PNG（`Content-Type: image/png`），可直接作为
“可下载差异图”链接。产物保存在有界 LRU 缓存中（默认 128 张），
淘汰或不存在时返回 404 `artifact_not_found`。

## GET /health

返回 `{"status": "ok"}`。
