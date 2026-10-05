# visual-regression-python

纯进程内的截图回归对比能力：接收基准图与候选图，输出是否变化、变化
像素占比和可下载的差异标注图；支持忽略区域、轻微渲染差异容忍、
基准版本化审批管理与批量对比。不依赖任何外部服务，图像来自本地
样本或进程内生成（Pillow）。

## 能力一览

- **稳定判定**：逐通道容忍阈值 `pixel_tolerance` + 变化面积比例阈值
  `change_ratio`（均为严格不等式，边界语义明确），输出变化像素数、
  占比与标注 PNG。
- **忽略区域**：矩形区域可配；非法/越界按区域下标拒绝，绝不静默放行。
- **容忍但不纵容**：连通域噪声过滤吞掉零星像素，位移/成片改色等结构
  性差异保留；相同输入 + 相同配置产出**逐字节一致**的差异图。
- **基准版本化审批**：`propose → approve/reject`，只追加的历史版本
  可回溯；对比始终基于某个完整版本，并发替换下读不到中间态。
- **批量对比**：多组一次提交，单组失败隔离；`success / no_diff /
  diff / failed` 四态 + 汇总计数。
- **资源上限**：字节数、宽高、像素量、批次像素预算均可配；损坏、格式
  不支持、超限分别给出可区分错误，单张坏图不会崩溃进程。

## 运行

```bash
uv sync
uv run uvicorn main:app --reload
```

交互式文档：启动后访问 `/docs`。

## 在进程内直接使用（无需 HTTP）

```python
from visual_regression.service import VisualRegressionService
from visual_regression.config import CompareConfig, ResourceLimits

svc = VisualRegressionService(
    limits=ResourceLimits(max_pixels=10_000_000),
    default_config=CompareConfig(pixel_tolerance=16, change_ratio=0.01),
)

item = svc.compare_case("case-1", candidate_png_bytes,
                        ignore_regions=[{"x": 0, "y": 0, "width": 50, "height": 20}])
print(item.status.value, item.summary)
if item.artifact_id:
    open("diff.png", "wb").write(svc.get_artifact(item.artifact_id))

# 审批式替换
svc.propose_case("case-1", new_png_bytes, note="改版", proposed_by="alice")
svc.approve_case("case-1", approved_by="reviewer")
print(svc.history("case-1"))

# 批量（单组失败不影响其余）
summary = svc.run_batch([{"case_id": "a", "candidate": png_a},
                         {"case_id": "b", "candidate": png_b}])
print(summary.success, summary.no_diff, summary.diff, summary.failed)
```

## 测试

```bash
uv run pytest
```

覆盖：阈值边界（严格大于）、逐通道容忍、连通域噪声 vs 结构性位移、
忽略区域越界定位、基准审批与并发替换、批量部分失败、资源上限/损坏/
格式错误的区分，以及 HTTP 端到端链路。

## 文档

- [判定语义与配置项](docs/configuration.md)
- [HTTP API](docs/api.md)

## 支持格式

输入：PNG、JPEG（按内容嗅探，不看扩展名）；带透明通道时合成到黑色
底色后比较。差异标注图输出：确定性 PNG。
