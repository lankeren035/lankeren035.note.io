# 参数说明



# 1. `service_kick_detector_tcp_win.ps1`

这是**服务端启动文件**，最重要。它把环境变量转成 `service_kick_detector_tcp.py` 的命令行参数。

## 1.1 工程启动参数

| 参数               |                                      默认 | 类型 | 影响   | 说明           |
| ---------------- | --------------------------------------: | -- | ---- | ------------ |
| `PROJECT_ROOT`   |                                  脚本上级目录 | 工程 | 【工程】 | 项目根目录        |
| `PYTHON`         | `D:\anaconda3\envs\football\python.exe` | 工程 | 【工程】 | Python 环境    |
| `TCP_HOST`       |                               `0.0.0.0` | 工程 | 【工程】 | 服务监听地址       |
| `TCP_PORT`       |                                 `19090` | 工程 | 【工程】 | 服务监听端口       |
| `BACKLOG`        |                                    `16` | 工程 | 【工程】 | TCP 等待连接队列   |
| `SOCKET_TIMEOUT` |                                     `0` | 工程 | 【工程】 | 接收超时；0 表示不超时 |

这些一般不用调。

---

## 1.2 模型路径参数

| 参数           |                              默认 | 类型 | 影响       | 说明    |
| ------------ | ------------------------------: | -- | -------- | ----- |
| `BALL_MODEL` |      `my_models\yolo11s.engine` | 模型 | 【效果】【效率】 | 球检测模型 |
| `POSE_MODEL` | `my_models\yolo11m-pose.engine` | 模型 | 【效果】【效率】 | 姿态模型  |

影响很大：

```text
更强球模型：球更准，但可能慢。
更强 pose 模型：脚点更稳，但也可能慢。
engine：通常比 pt 快。
```

---

## 1.3 推理效率参数

| 参数           |    默认 | 类型 | 影响       | 说明                    |
| ------------ | ----: | -- | -------- | --------------------- |
| `DEVICE`     |   `0` | 推理 | 【效率】     | GPU 编号；`cpu` 会非常慢     |
| `HALF`       |   `1` | 推理 | 【效率】     | FP16，GPU/TensorRT 下更快 |
| `BATCH`      |   `4` | 推理 | 【效率】     | YOLO 推理 batch         |
| `CHUNK`      |   `4` | 在线 | 【效率】【延迟】 | 每累计多少帧判断一次            |
| `BALL_IMGSZ` | `640` | 推理 | 【效果】【效率】 | 球模型输入尺寸               |
| `POSE_IMGSZ` | `640` | 推理 | 【效果】【效率】 | pose 输入尺寸             |

调参建议：

```text
BATCH：影响吞吐，不直接改变检测逻辑。太大可能显存高，太小吞吐差。
CHUNK：越小延迟越低，但调用更频繁；越大延迟更高，但更省调度开销。
BALL_IMGSZ：越大球更容易检测到，尤其小球/模糊球，但更慢。
POSE_IMGSZ：越大脚点可能更稳，但更慢。
```

你现在在线摄像头建议：

```powershell
$env:BATCH="4"
$env:CHUNK="4"
$env:HALF="1"
```

---

## 1.4 检测结果解析参数

| 参数                    |     默认 | 类型 | 影响       | 说明           |
| --------------------- | -----: | -- | -------- | ------------ |
| `BALL_CONF`           | `0.16` | 检测 | 【效果】     | 球框置信度        |
| `PERSON_CONF`         | `0.20` | 检测 | 【效果】     | 人体框置信度       |
| `POSE_CONF`           | `0.18` | 检测 | 【效果】     | 关键点置信度       |
| `YOLO_IOU`            | `0.50` | 检测 | 【效果】     | YOLO NMS IoU |
| `BALL_CLASS_NAMES`    |  多个球类名 | 检测 | 【效果】     | 多类别模型时过滤球类别  |
| `MAX_BALL_CANDIDATES` |    `8` | 检测 | 【效果】【效率】 | 每帧最多保留球候选    |
| `HAND_CONF`           | `0.20` | 检测 | 【效果】     | 手腕关键点阈值      |

调参重点：

```text
BALL_CONF 降低：召回运动模糊球，误检增加。
BALL_CONF 提高：误检减少，漏检增加。
POSE_CONF 降低：脚点更容易有，但脚点噪声变多。
MAX_BALL_CANDIDATES 太小：真球可能被鞋子误检挤掉。
```

常用微调：

```powershell
$env:BALL_CONF="0.12"   # 球漏检多时
$env:BALL_CONF="0.20"   # 误检多时
$env:POSE_CONF="0.15"   # 脚点缺失多时
```

---

## 1.5 当前主逻辑核心参数

这些最影响踢球帧判断。

| 参数                       |     默认 | 类型  | 影响   | 说明               |
| ------------------------ | -----: | --- | ---- | ---------------- |
| `MIN_BALL_MOVE_PX`       |   `35` | 主逻辑 | 【效果】 | 球位移绝对门槛          |
| `MIN_BALL_MOVE_RATIO`    | `0.03` | 主逻辑 | 【效果】 | 球位移占画面宽度比例       |
| `MIN_BALL_SPEED_PXPF`    |    `0` | 主逻辑 | 【效果】 | 球速硬门槛，0 表示不用额外限制 |
| `FOOT_BALL_SAME_DIR_COS` | `0.35` | 主逻辑 | 【效果】 | 脚运动方向和球运动方向同向阈值  |
| `MIN_FOOT_MOVE_PX`       |   `15` | 主逻辑 | 【效果】 | 脚至少移动多少像素        |
| `BALL_SPEED_LOOKBACK`    |    `3` | 主逻辑 | 【效果】 | 向前几帧估计踢前球速       |
| `BALL_SPEED_JUMP_RATIO`  |  `1.6` | 主逻辑 | 【效果】 | 当前球速相对前面中值的突增倍数  |

主逻辑大致是：

```text
球发生大位移
+ 球速相对之前突增
+ 附近有脚
+ 脚和球运动同向
```

调参方向：

```text
漏检真实踢球：
  降低 MIN_BALL_MOVE_PX
  降低 MIN_BALL_MOVE_RATIO
  降低 FOOT_BALL_SAME_DIR_COS
  降低 MIN_FOOT_MOVE_PX
  降低 BALL_SPEED_JUMP_RATIO

误报多：
  提高 MIN_BALL_MOVE_PX
  提高 FOOT_BALL_SAME_DIR_COS
  提高 MIN_FOOT_MOVE_PX
  提高 BALL_SPEED_JUMP_RATIO
```

优先调：

```text
BALL_CONF
MIN_BALL_MOVE_PX
FOOT_BALL_SAME_DIR_COS
MIN_FOOT_MOVE_PX
BALL_SPEED_JUMP_RATIO
```

---

## 1.6 ps1 当前没有暴露，但 Python 里很重要的主逻辑参数

`service_kick_detector_tcp.py` 有，但当前 ps1 没传：

| Python 参数                     |     默认 | 类型       | 影响   | 建议       |
| ----------------------------- | -----: | -------- | ---- | -------- |
| `--contact-support-dist-norm` | `2.25` | 主逻辑      | 【效果】 | 建议加入 ps1 |
| `--ball-gap-lookback`         |    `3` | 主逻辑      | 【效果】 | 建议加入 ps1 |
| `--event-search-start-sec`    | `0.80` | 主逻辑      | 【效果】 | 建议加入 ps1 |
| `--min-event-gap-sec`         | `1.20` | 主逻辑      | 【效果】 | 建议加入 ps1 |
| `--allow-blur-fallback-early` |     关闭 | fallback | 【效果】 | 默认别开     |

建议在 ps1 里补：

```powershell
$CONTACT_SUPPORT_DIST_NORM = Use-Env "CONTACT_SUPPORT_DIST_NORM" "2.25"
$BALL_GAP_LOOKBACK = Use-Env "BALL_GAP_LOOKBACK" "3"
$EVENT_SEARCH_START_SEC = Use-Env "EVENT_SEARCH_START_SEC" "0.80"
$MIN_EVENT_GAP_SEC = Use-Env "MIN_EVENT_GAP_SEC" "1.20"

Add-Opt $ArgsList "--contact-support-dist-norm" $CONTACT_SUPPORT_DIST_NORM
Add-Opt $ArgsList "--ball-gap-lookback" $BALL_GAP_LOOKBACK
Add-Opt $ArgsList "--event-search-start-sec" $EVENT_SEARCH_START_SEC
Add-Opt $ArgsList "--min-event-gap-sec" $MIN_EVENT_GAP_SEC
```

---

## 1.7 fallback 参数

| 参数                                |         默认 | 类型       | 影响   | 说明               |
| --------------------------------- | ---------: | -------- | ---- | ---------------- |
| `ENABLE_LOSS_FALLBACK`            | `1` in ps1 | fallback | 【效果】 | 球贴脚后长期丢失兜底       |
| `LOSS_REAPPEAR_SEC`               |     `0.70` | fallback | 【效果】 | 丢球多久算长期丢失        |
| `LOSS_FALLBACK_APPROACH_LOOKBACK` |        `4` | fallback | 【效果】 | 丢球前看几帧脚是否靠近球     |
| `CONTACT_PERCENTILE`              |       `35` | fallback | 【效果】 | fallback 接触自适应阈值 |
| `MOTION_PERCENTILE`               |       `85` | fallback | 【效果】 | fallback 运动自适应阈值 |
| `DIRECTION_COS_THRESH`            |     `0.15` | fallback | 【效果】 | 球是否远离脚           |
| `BALL_MOVE_CONTACT_GATE`          |     `1.50` | fallback | 【效果】 | fallback 脚球距离门槛  |

注意：

```text
ENABLE_LOSS_FALLBACK=1 是 ps1 默认开启。
blur_loss 默认不参与 early-confirm，除非传 --allow-blur-fallback-early。
```

调参建议：

```text
球踢出去后因为模糊一直检测不到：
  保持 ENABLE_LOSS_FALLBACK=1
  适当降低 LOSS_REAPPEAR_SEC，例如 0.50

误报来自球突然丢失：
  ENABLE_LOSS_FALLBACK=0
  或提高 LOSS_REAPPEAR_SEC
```

---

## 1.8 debug 参数

| 参数                      |           默认 | 类型    | 影响       | 说明                |
| ----------------------- | -----------: | ----- | -------- | ----------------- |
| `DEBUG_DETECTIONS`      |          `1` | debug | 【调试】【效率】 | 写 det jsonl       |
| `DEBUG_LOG_DIR`         | `debug_runs` | debug | 【调试】     | 输出目录              |
| `DEBUG_FULL_SESSION`    |          `1` | debug | 【调试】【效率】 | 检测到也跑完整 session   |
| `DEBUG_DECISION`        |          `1` | debug | 【调试】【效率】 | 每个 chunk 记录候选拒绝原因 |
| `DEBUG_CANDIDATE_LIMIT` |         `20` | debug | 【调试】     | 记录候选上限            |

正式摄像头必须改：

```powershell
$env:DEBUG_FULL_SESSION="0"
$env:DEBUG_DECISION="0"
```

否则：

```text
DEBUG_FULL_SESSION=1：检测到了也不提前返回。
DEBUG_DECISION=1：每个 chunk 多跑一次 detect_events，长时间运行会拖慢。
```

调试问题时再开：

```powershell
$env:DEBUG_FULL_SESSION="1"
$env:DEBUG_DECISION="1"
```

---

## 1.9 在线确认参数

| 参数                  |     默认 | 类型 | 影响       | 说明              |
| ------------------- | -----: | -- | -------- | --------------- |
| `ONLINE_WARMUP_SEC` | `0.80` | 在线 | 【效果】【延迟】 | 开始后多少秒不报        |
| `ONLINE_WAIT_SEC`   | `0.12` | 在线 | 【效果】【延迟】 | 事件后等几帧确认        |
| `STABLE_CHUNKS`     |    `1` | 在线 | 【效果】【延迟】 | 连续几个 chunk 稳定才报 |

调参：

```text
想更快：
  降低 ONLINE_WAIT_SEC
  STABLE_CHUNKS=1

想更稳：
  提高 ONLINE_WAIT_SEC
  STABLE_CHUNKS=2
```

---

## 1.10 历史包袱参数

| 参数                        |     默认 | 类型 | 影响   | 建议        |
| ------------------------- | -----: | -- | ---- | --------- |
| `MOTION_WINDOW_SEC`       | `0.24` | 历史 | 【历史】 | 当前主逻辑基本不用 |
| `MIN_VISIBLE_STEPS`       |    `2` | 历史 | 【历史】 | 当前主逻辑基本不用 |
| `BALL_MOVE_LOOKAHEAD_SEC` | `0.20` | 历史 | 【历史】 | 当前主逻辑基本不用 |
| `STRONG_BALL_MOVE_MULT`   |  `2.0` | 历史 | 【历史】 | 当前主逻辑基本不用 |

建议从 ps1 隐藏，别日常调。

---

# 2. `service_kick_detector_tcp.py`

这是**服务端主程序**。

## 2.1 影响效率的关键点

| 参数/逻辑                     | 影响                          |
| ------------------------- | --------------------------- |
| `batch`                   | YOLO 推理吞吐                   |
| `online_chunk`            | 判断频率和延迟                     |
| `ball_imgsz / pose_imgsz` | 模型速度和检测质量                   |
| `half`                    | GPU 推理速度                    |
| `debug_decision`          | 每个 chunk 多跑一次 detect_events |
| `debug_full_session`      | 检测到也不提前返回                   |
| `obs` 前缀不断增长              | 长 session 下 CPU 逻辑越来越慢      |

效率风险最大的是：

```text
摄像头一个 session 无限长
+ DEBUG_DECISION=1
+ 每个 chunk 都 detect_events(完整 obs)
```

建议正式运行：

```powershell
$env:DEBUG_FULL_SESSION="0"
$env:DEBUG_DECISION="0"
```

并用摄像头发送端分段：

```text
--max-seconds 60 或 120
```

---

## 2.2 影响效果的核心参数

同 ps1 中的主逻辑参数：

```text
ball_conf
pose_conf
min_ball_move_px
min_ball_move_ratio
foot_ball_same_dir_cos
min_foot_move_px
ball_speed_lookback
ball_speed_jump_ratio
contact_support_dist_norm
ball_gap_lookback
enable_loss_fallback
loss_reappear_sec
```

---

## 2.3 当前 ps1 没传但函数里有的参数

| 参数                          |      默认 | 建议     |
| --------------------------- | ------: | ------ |
| `contact_support_dist_norm` |  `2.25` | 应暴露    |
| `ball_gap_lookback`         |     `3` | 应暴露    |
| `event_search_start_sec`    |  `0.80` | 应暴露    |
| `min_event_gap_sec`         |  `1.20` | 应暴露    |
| `allow_blur_fallback_early` | `False` | 不建议默认开 |

---

# 3. `kick_common.py`

这是**模型输出解析层**，不直接判踢球，但会强烈影响后续事件判断。

## 3.1 可通过 argparse/ps1 调的关键参数

| 参数                        |     默认 | 影响       | 说明                   |
| ------------------------- | -----: | -------- | -------------------- |
| `ball_conf`               | `0.16` | 【效果】     | 过滤球框                 |
| `person_conf`             | `0.20` | 【效果】     | YOLO pose 人体框阈值      |
| `pose_conf`               | `0.18` | 【效果】     | 脚踝、膝盖关键点阈值           |
| `yolo_iou`                | `0.50` | 【效果】     | NMS                  |
| `ball_class_names`        |  多个球类名 | 【效果】     | 多类别模型筛球              |
| `max_ball_candidates`     |    `8` | 【效果】【效率】 | 每帧保留球候选              |
| `hand_conf`               | `0.20` | 【效果】     | 手腕点过滤手部干扰            |
| `batch`                   |    `4` | 【效率】     | 推理 batch             |
| `half`                    |      开 | 【效率】     | FP16                 |
| `pad_last_batch`          |      开 | 【效率】【稳定】 | TensorRT 固定 batch 更稳 |
| `ball_imgsz / pose_imgsz` |  `640` | 【效果】【效率】 | 输入尺寸                 |

---

## 3.2 文件内常量，不建议频繁调

| 常量                    |       默认 | 类型   | 说明           |
| --------------------- | -------: | ---- | ------------ |
| `TOE_EXTEND_RATIO`    |   `0.35` | 几何   | 用膝盖到脚踝方向外推脚尖 |
| `MAX_BALL_AREA_RATIO` |   `0.25` | 过滤   | 球框最大占画面比例    |
| `MAD_SCALE`           | `1.4826` | 统计   | MAD 鲁棒统计系数   |
| `VIDEO_EXTS`          |      多格式 | 工程   | 视频后缀         |
| COCO keypoint index   |       固定 | 模型格式 | 手腕、膝盖、脚踝编号   |

其中可能影响效果的是：

```text
TOE_EXTEND_RATIO：脚尖点位置。
MAX_BALL_AREA_RATIO：极近距离大球框可能被过滤。
```

一般不动。

---

# 4. `kick_offline.py`

这是**事件判断核心**。

## 4.1 当前主逻辑参数

| 参数                          |     默认 | 影响   | 说明         |
| --------------------------- | -----: | ---- | ---------- |
| `min_ball_move_px`          |   `35` | 【效果】 | 球大位移绝对阈值   |
| `min_ball_move_ratio`       | `0.03` | 【效果】 | 球位移占画面宽度比例 |
| `min_ball_speed_pxpf`       |    `0` | 【效果】 | 额外球速硬阈值    |
| `foot_ball_same_dir_cos`    | `0.35` | 【效果】 | 脚和球同向      |
| `min_foot_move_px`          |   `15` | 【效果】 | 脚运动阈值      |
| `ball_speed_lookback`       |    `3` | 【效果】 | 向前估计球速     |
| `ball_speed_jump_ratio`     |  `1.6` | 【效果】 | 球速突增倍数     |
| `contact_support_dist_norm` | `2.25` | 【效果】 | 附近脚支持      |
| `ball_gap_lookback`         |    `3` | 【效果】 | 球短暂漏检后重现   |
| `event_search_start_sec`    | `0.80` | 【效果】 | 开头忽略       |
| `min_event_gap_sec`         | `1.20` | 【效果】 | 多事件去重      |

---

## 4.2 fallback 参数

| 参数                                |                   默认 | 影响   | 说明             |
| --------------------------------- | -------------------: | ---- | -------------- |
| `enable_loss_fallback`            | Python 默认 0，ps1 默认 1 | 【效果】 | 球长期丢失 fallback |
| `loss_reappear_sec`               |               `0.70` | 【效果】 | 丢失多久算长期        |
| `loss_fallback_approach_lookback` |                  `4` | 【效果】 | 脚是否靠近球         |
| `contact_percentile`              |                 `35` | 【效果】 | fallback 接触阈值  |
| `motion_percentile`               |                 `85` | 【效果】 | fallback 运动阈值  |
| `direction_cos_thresh`            |               `0.15` | 【效果】 | 球是否远离脚         |
| `ball_move_contact_gate`          |               `1.50` | 【效果】 | fallback 脚球距离  |

---

## 4.3 历史参数

| 参数                        |     默认 | 状态                   |
| ------------------------- | -----: | -------------------- |
| `motion_window_sec`       | `0.24` | 旧 direct_motion      |
| `min_visible_steps`       |    `2` | 旧 direct_motion      |
| `ball_move_lookahead_sec` | `0.20` | 旧 ball-after-contact |
| `strong_ball_move_mult`   |  `2.0` | 当前基本不参与通过逻辑          |

---

## 4.4 效率风险

`detect_events()` 每次会：

```text
build_arrays(obs)：扫完整 obs
visible_ball_speed_events：扫完整 obs
loss_only_fallback：开启时扫完整 obs
debug_candidate：开启时再扫候选
```

所以长时间摄像头不要一个 session 无限跑。
更省事的方案是发送端分段：

```text
--max-seconds 60 或 120
--auto-continue
```

---

# 5. `mock_camera_sender_tcp_win.ps1`

这是**摄像头发送端启动脚本**。

## 5.1 工程参数

| 参数             |          默认 | 类型 | 影响        |
| -------------- | ----------: | -- | --------- |
| `HOST_IP`      | `127.0.0.1` | 工程 | 连接服务端     |
| `PORT`         |     `19090` | 工程 | 服务端端口     |
| `CAMERA_INDEX` |         `0` | 工程 | 摄像头编号     |
| `PYTHON`       |        固定路径 | 工程 | Python 环境 |

---

## 5.2 摄像头采集参数

| 参数                 |           默认 | 类型    | 影响          | 说明      |
| ------------------ | -----------: | ----- | ----------- | ------- |
| `WIDTH`            |       `1280` | 采集    | 【效果】【效率】    | 摄像头宽    |
| `HEIGHT`           |        `720` | 采集    | 【效果】【效率】    | 摄像头高    |
| `FPS`              |         `30` | 采集    | 【效果】【效率】    | 发送 FPS  |
| `JPEG_QUALITY`     |         `85` | 编码    | 【效果】【效率】    | JPEG 质量 |
| `SHOW`             |          `1` | UI    | 【效率】        | 显示预览    |
| `DEBUG_SAVE_VIDEO` |          `1` | debug | 【调试】【效率/磁盘】 | 保存发送视频  |
| `DEBUG_SAVE_DIR`   | `debug_runs` | debug | 【调试】        | 保存目录    |

调参：

```text
WIDTH/HEIGHT 越高：球更清晰，但编码、传输、推理可能更慢。
JPEG_QUALITY 越高：画质更好，包更大；越低：快但可能压坏球。
SHOW=1 会有一点 UI 开销。
DEBUG_SAVE_VIDEO=1 会占磁盘和少量 CPU。
```

正式运行建议：

```powershell
$DEBUG_SAVE_VIDEO="0"
$SHOW="0"  # 如果不需要预览
```

---

## 5.3 session 分段参数

| 参数            |  默认 | 影响   | 说明             |
| ------------- | --: | ---- | -------------- |
| `MAX_SECONDS` | `0` | 【效率】 | 0 表示无限 session |
| `MAX_FRAMES`  | `0` | 【效率】 | 0 表示不限帧        |
| `ONCE`        | `0` | 工程   | 只跑一次 session   |

你现在要摄像头一直检测，**但不想服务端前缀无限增长**，建议改：

```powershell
$MAX_SECONDS = "60"
```

或者：

```powershell
$MAX_SECONDS = "120"
```

还需要加 `auto-continue` 功能，否则每段结束会等你按键。这个脚本当前没有 `AUTO_CONTINUE`，建议补。

---

# 6. `mock_camera_sender_tcp.py`

这是摄像头发送端主逻辑。

## 6.1 argparse 参数

| 参数                   |           默认 | 影响          | 说明            |
| -------------------- | -----------: | ----------- | ------------- |
| `--host`             |  `127.0.0.1` | 工程          | 服务端地址         |
| `--port`             |      `19090` | 工程          | 服务端端口         |
| `--camera-index`     |          `0` | 工程          | 摄像头编号         |
| `--backend`          |      `dshow` | 工程          | Windows 摄像头后端 |
| `--width`            |       `1280` | 【效果】【效率】    | 采集宽度          |
| `--height`           |        `720` | 【效果】【效率】    | 采集高度          |
| `--fps`              |         `30` | 【效果】【效率】    | 采集和发送 FPS     |
| `--jpeg-quality`     |         `85` | 【效果】【效率】    | JPEG 压缩质量     |
| `--max-seconds`      |          `0` | 【效率】        | 每个 session 时长 |
| `--max-frames`       |          `0` | 【效率】        | 每个 session 帧数 |
| `--connect-timeout`  |         `10` | 工程          | TCP 连接超时      |
| `--show`             |           关闭 | 【效率】        | 显示预览          |
| `--print-every`      |         `10` | 调试          | 打印频率          |
| `--debug-save-video` |           关闭 | 【调试】【效率/磁盘】 | 保存发送视频        |
| `--debug-save-dir`   | `debug_runs` | 调试          | 保存目录          |
| `--once`             |           关闭 | 工程          | 只跑一次          |

建议新增：

```text
--auto-continue
```

否则 session 结束会停下来等输入。

---

# 7. `mock_sender_tcp_win.ps1`

这是**本地视频发送端启动脚本**，用于测试视频文件。

| 参数              |          默认 | 类型         | 影响           |
| --------------- | ----------: | ---------- | ------------ |
| `DETECTOR_HOST` | `127.0.0.1` | 工程         | 服务端 IP       |
| `DETECTOR_PORT` |     `19090` | 工程         | 服务端端口        |
| `VIDEO_DIR`     |    `videos` | 工程         | 视频目录         |
| `VIDEO`         |           空 | 工程         | 单个视频路径       |
| `JPEG_QUALITY`  |        `85` | 【效果】【效率】   | JPEG 压缩质量    |
| `MAX_SECONDS`   |        `20` | 【效率】       | 每次最多发送多少秒    |
| `MAX_FRAMES`    |         `0` | 【效率】       | 每次最多发送多少帧    |
| `REALTIME`      |         `1` | 【效率/测试真实性】 | 是否按真实 FPS 发送 |
| `ONCE`          |         `0` | 工程         | 只发一次         |

调试视频建议：

```powershell
$env:REALTIME="0"   # 快速跑完整视频
```

模拟真实摄像头延迟建议：

```powershell
$env:REALTIME="1"
```

---

# 8. `mock_sender_tcp.py`

本地视频发送端。

| 参数                   |       默认 | 影响         | 说明           |
| -------------------- | -------: | ---------- | ------------ |
| `--video`            |        空 | 工程         | 指定单视频        |
| `--video-dir`        | `videos` | 工程         | 视频目录         |
| `--jpeg-quality`     |     `85` | 【效果】【效率】   | 图像压缩         |
| `--fps`              |     `25` | 【效果】       | 视频 FPS 异常时备用 |
| `--max-seconds`      |     `20` | 【效率】       | 每次发送时长       |
| `--max-frames`       |      `0` | 【效率】       | 每次发送帧数       |
| `--realtime`         |       关闭 | 【效率/测试真实性】 | 是否按 FPS 等待   |
| `--debug-save-video` |       关闭 | 【调试】       | 保存发送视频       |
| `--once`             |       关闭 | 工程         | 只发送一次        |

---

# 9. `visualize_debug_all_win.ps1`

可视化启动脚本。

| 参数          |           默认 | 类型 | 影响               |
| ----------- | -----------: | -- | ---------------- |
| `DEBUG_DIR` | `debug_runs` | 调试 | 输入 det/send 文件目录 |
| `OUT_DIR`   | `debug_runs` | 调试 | 输出目录             |
| `OVERWRITE` |          `0` | 调试 | 是否覆盖已有视频         |

不影响检测，只影响可视化。

---

# 10. `visualize_debug_session.py`

把 debug jsonl 和发送端视频合成可视化。

| 参数             |           默认 | 影响                             |
| -------------- | -----------: | ------------------------------ |
| `--debug-dir`  | `debug_runs` | 找 `det_*.jsonl` 和 `send_*.mp4` |
| `--session-id` |            空 | 只看某个 session                   |
| `--out-dir`    |            空 | 输出目录                           |
| `--overwrite`  |           关闭 | 覆盖已有可视化                        |
| `--latest`     |           关闭 | 只看最新 session                   |

不影响检测效果。

---

# 11. `tcp_packet.py`

没有调参。固定协议：

```text
4 字节长度头
+ JSON header
+ \n\n
+ JPEG bytes
```

影响效率的间接参数来自发送端：

```text
jpeg_quality
width / height
fps
```

---

# 12. `debug_trace.py`

没有检测参数。负责写：

```text
det_<session_id>.jsonl
```

影响来自：

```text
DEBUG_DETECTIONS
DEBUG_DECISION
DEBUG_FULL_SESSION
```

---

# 13. 最重要的微调参数清单

## 优先调效果

```text
BALL_CONF
POSE_CONF
MIN_BALL_MOVE_PX
MIN_BALL_MOVE_RATIO
FOOT_BALL_SAME_DIR_COS
MIN_FOOT_MOVE_PX
BALL_SPEED_JUMP_RATIO
CONTACT_SUPPORT_DIST_NORM
BALL_GAP_LOOKBACK
ENABLE_LOSS_FALLBACK
LOSS_REAPPEAR_SEC
```

## 优先调效率 / 延迟

```text
BALL_IMGSZ
POSE_IMGSZ
BATCH
CHUNK
HALF
DEBUG_FULL_SESSION
DEBUG_DECISION
摄像头 MAX_SECONDS / MAX_FRAMES
WIDTH / HEIGHT
JPEG_QUALITY
```

## 正式摄像头推荐初始配置

服务端：

```powershell
$env:DEBUG_FULL_SESSION="0"
$env:DEBUG_DECISION="0"
$env:DEBUG_DETECTIONS="0"     # 如果不需要日志
$env:ENABLE_LOSS_FALLBACK="1"
$env:BATCH="4"
$env:CHUNK="4"
$env:BALL_CONF="0.16"
```

摄像头端：

```powershell
$MAX_SECONDS="60"   # 或 120
$DEBUG_SAVE_VIDEO="0"
$SHOW="0"
```

如果你要长期稳定在线，别用无限 session。用：

```text
摄像头不关闭 + 自动分段 60～120 秒
```

比滑动窗口改动小很多，也能避免 `detect_events()` 扫完整前缀导致后期延迟升高。
