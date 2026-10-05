# visual-regression-python

进程内截图回归对比链路：截图对比、差异定位（差异标注图）、基准版本化管理与批量执行。
整条链路只在本进程内完成，输入为本地样本图或进程内生成的图，不依赖任何外部服务。

## 快速开始

```python
from visual_regression import CompareConfig, Region, compare_images

result = compare_images(
    baseline=open("baseline.png", "rb").read(),
    candidate=open("candidate.png", "rb").read(),
    config=CompareConfig(
        tolerance=2,                       # 容忍逐通道 <=2 的零星噪声
        pixel_threshold=10,                # 允许最多 10 个变化像素
        changed_ratio_threshold=0.001,     # 允许最多 0.1% 的变化面积
        ignore_regions=(Region(0, 0, 100, 20),),  # 忽略顶部状态栏
    ),
)
print(result.changed, result.changed_ratio)
open("diff.png", "wb").write(result.diff_image)  # 差异标注图（PNG，可下载）
```

运行测试：`uv run python -m pytest tests/ -q`

## 判定语义

逐像素计算基准图与候选图 RGB 三通道的最大差值，然后：

1. **容忍（tolerance）**：差值 `> tolerance` 的像素直接计为变化；差值在
   `(0, tolerance]` 的像素，仅当其 8 邻域内同样存在差异的像素数少于
   `noise_max_neighbors`（即“零星”噪声）时才被容忍。成片颜色改变、
   整体位移这类结构性差异邻域差异密集，不会被容忍吞掉。
2. **忽略区域（ignore_regions）**：区域内的差异完全不计入判定，也不计入
   `effective_pixels`。区域越界或格式非法时抛出 `IgnoreRegionError`，
   携带 `region_index` 与 `reason` 可定位到具体区域，不会静默放行。
3. **阈值判定**：设忽略区域外的变化像素数为 `changed_pixels`、比例为
   `changed_ratio = changed_pixels / effective_pixels`。
   `changed_pixels > pixel_threshold` **或**
   `changed_ratio > changed_ratio_threshold` 任一成立即判为 `CHANGED`；
   两者都在阈值内但有变化像素为 `WITHIN_THRESHOLD`；零变化像素为 `UNCHANGED`。
4. **确定性**：同一对输入在相同配置下重复对比，输出逐字节一致的差异图
   与相同的判定结论（解码、逐像素循环、PNG 编码均为确定性实现）。

`CompareResult` 输出：`changed`（是否发生变化）、`changed_pixels`、
`effective_pixels`、`changed_ratio`、`diff_image`（PNG 字节，变化像素标红，
可直接保存/下载）。

## 配置项（CompareConfig）

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `tolerance` | `0` | 逐通道差值容忍度，差值不超过它的零星像素不计为变化 |
| `noise_max_neighbors` | `2` | 零星判定：8 邻域内差异像素数少于该值才允许被容忍 |
| `pixel_threshold` | `0` | 允许的变化像素个数上限，超过判为“有差异” |
| `changed_ratio_threshold` | `0.0` | 允许的变化面积比例上限（0~1），超过判为“有差异” |
| `ignore_regions` | `()` | 忽略区域 `Region(x, y, width, height)` 元组 |
| `max_width` / `max_height` | `8192` | 单边分辨率上限 |
| `max_pixels` | `40_000_000` | 总像素量上限 |
| `max_image_bytes` | `64 MiB` | 单张图片字节数上限 |

## 基准版本化管理（BaselineStore）

- 替换走审批式流程：`submit_replace(case_id, image, author)` 提交提案（不生效）
  → `approve(proposal_id)` 生效 / `reject(proposal_id)` 驳回。
- 每次生效生成递增版本号，旧版本永久保留：`history(case_id)` 查看全部版本，
  `get_version(case_id, version)` 回溯任意历史版本。
- 并发语义：生效是原子的，替换与对比并发进行时，任何一次 `current()` 读取
  都拿到某个完整版本快照，不会读到半更新的中间状态。

## 批量对比（run_batch）

一次提交多组 `BatchItem`，单组失败不影响其余组。每组结果四态：

| 状态 | 含义 |
| --- | --- |
| `UNCHANGED` | 完全一致，零变化像素 |
| `SUCCESS` | 有变化像素但在阈值内，对比通过 |
| `CHANGED` | 差异超出阈值 |
| `FAILED` | 对比失败（输入损坏 / 超资源上限 / 配置非法 / 基准缺失），`error` 给出原因 |

`BatchResult.summary` 给出四种状态的汇总计数。`BatchItem.baseline` 为
`None` 时从 `BaselineStore` 取该用例当前版本。

## 错误分类（均可区分）

| 异常 | 触发条件 |
| --- | --- |
| `ImageDecodeError` | 输入损坏或格式不支持 |
| `ResourceLimitError` | 超出分辨率 / 像素量 / 字节数上限 |
| `IgnoreRegionError` | 忽略区域越界或格式非法（含 `region_index` 定位） |
| `DimensionMismatchError` | 基准图与候选图尺寸不一致 |
| `BaselineNotFoundError` | 用例无基准或指定版本不存在 |
| `ProposalError` | 提案不存在或重复审批/驳回 |

资源上限在解码前后双重检查（含 Pillow 解压炸弹防护），单张超限或损坏的
图片只会使该组对比失败，不会拖垮或崩溃整个进程。
