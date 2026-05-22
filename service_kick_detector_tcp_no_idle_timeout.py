#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TCP push-stream kick-contact detection service.

用途：
- 检测端常驻内存，只加载一次 YOLO/TensorRT 模型；
- 发送端建立一个 TCP 长连接，按 Enter 后发送 start 控制包并逐帧推 JPEG 帧；
- 检测端启动时预加载模型，收到 start 后在线处理；
- 检测到踢球帧后立刻返回 JSON，但不断开连接；
- 发送端收到结果后停止本轮推流，发送 end 标记，等待下一次 Enter。

协议：
1) client -> server: uint32_be + JSON start
   start example:
   {"type":"start", "session_id":"xxx", "source":"a.mp4", "fps":30.0, "max_seconds":20, "params":{...}}
2) client -> server: repeated uint32_be + JPEG bytes
3) server -> client: uint32_be + JSON result once detected/finalized
4) client -> server: uint32_be(0) means end of current round; connection remains open
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import socket
import struct
import threading
import time
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import uuid4

import cv2
import numpy as np
from ultralytics import YOLO

from kick_common import (
    Event,
    FrameObs,
    VideoResult,
    append_observations,
    best_event,
    event_to_dict,
    frames,
    make_result,
    new_track,
    predict_batch,
)
from kick_offline import detect_events

# 与 myscripts_test/kick_online.py 保持一致，不采用 clean_v2 的激进默认值。
DEFAULT_ONLINE_WARMUP_SEC = 0.80
DEFAULT_ONLINE_WAIT_SEC = 0.55
DEFAULT_STABLE_CHUNKS = 2

OVERRIDABLE_FIELDS = {
    "ball_conf", "person_conf", "pose_conf", "yolo_iou", "max_ball_candidates", "hand_conf",
    "contact_percentile", "motion_percentile", "direction_cos_thresh", "motion_window_sec",
    "min_visible_steps", "loss_reappear_sec", "online_warmup_sec", "online_wait_sec",
    "stable_chunks", "online_chunk", "batch", "ball_imgsz", "pose_imgsz",
}


def _cfg(args: argparse.Namespace, name: str, default):
    return getattr(args, name, default)


def _finite_float(x: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        v = float(x)
    except Exception:
        return default
    return v if math.isfinite(v) else default


def _json_safe(x: Any) -> Any:
    """Convert numpy/Path/dataclass/NaN/Inf values to JSON-safe values."""
    if x is None or isinstance(x, (str, bool, int)):
        return x
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, Path):
        return str(x)
    if isinstance(x, np.ndarray):
        return _json_safe(x.tolist())
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating,)):
        v = float(x)
        return v if math.isfinite(v) else None
    if isinstance(x, dict):
        return {str(k): _json_safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_json_safe(v) for v in x]
    if hasattr(x, "__dataclass_fields__"):
        return _json_safe(asdict(x))
    return str(x)


def _confirm(
    obs: List[FrameObs],
    fps: float,
    height: int,
    state: Dict[str, object],
    args: argparse.Namespace,
    *,
    final: bool = False,
) -> Optional[Event]:
    """
    与 myscripts_test/kick_online.py 的确认逻辑一致：
    - 先调用 detect_events(obs_prefix)，不另写新规则；
    - 候选太靠近当前末尾时等待后续证据；
    - 候选跨 chunk 稳定后才允许 early stop。
    """
    if len(obs) < frames(float(_cfg(args, "online_warmup_sec", DEFAULT_ONLINE_WARMUP_SEC)), fps, 12):
        return None

    events, _, _, _ = detect_events(obs, fps, height, detail=False, args=args)
    if not events:
        state.clear()
        return None

    e = events[0]
    if final:
        return e

    wait_frames = frames(float(_cfg(args, "online_wait_sec", DEFAULT_ONLINE_WAIT_SEC)), fps, 6)
    if len(obs) - 1 - e.frame_idx < wait_frames:
        return None

    if state.get("kind") == e.kind and abs(int(state.get("frame_idx", -9999)) - e.frame_idx) <= 2:
        state["count"] = int(state.get("count", 1)) + 1
    else:
        state.update(kind=e.kind, frame_idx=e.frame_idx, count=1)

    return e if int(state["count"]) >= int(_cfg(args, "stable_chunks", DEFAULT_STABLE_CHUNKS)) else None

MAX_PACKET_BYTES = 64 * 1024 * 1024


def recv_exact(sock: socket.socket, n: int) -> bytes:
    chunks = []
    left = int(n)
    while left > 0:
        b = sock.recv(left)
        if not b:
            raise EOFError("socket closed while receiving")
        chunks.append(b)
        left -= len(b)
    return b"".join(chunks)


def recv_packet(sock: socket.socket) -> Optional[bytes]:
    raw_len = recv_exact(sock, 4)
    n = struct.unpack("!I", raw_len)[0]
    if n == 0:
        return None
    if n > MAX_PACKET_BYTES:
        raise ValueError(f"packet too large: {n} bytes")
    return recv_exact(sock, n)


def send_packet(sock: socket.socket, payload: bytes) -> None:
    if len(payload) > MAX_PACKET_BYTES:
        raise ValueError(f"packet too large: {len(payload)} bytes")
    sock.sendall(struct.pack("!I", len(payload)) + payload)


def send_json(sock: socket.socket, data: Dict[str, Any]) -> None:
    raw = json.dumps(_json_safe(data), ensure_ascii=False).encode("utf-8")
    send_packet(sock, raw)


def try_decode_json_packet(pkt: bytes) -> Optional[Dict[str, Any]]:
    raw = pkt.strip()
    if not raw.startswith(b"{"):
        return None
    try:
        obj = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def recv_start_packet(sock: socket.socket) -> Dict[str, Any]:
    """Wait for a start control packet on an already-open TCP connection."""
    while True:
        pkt = recv_packet(sock)
        if pkt is None:
            # Empty packet while idle: ignore and keep waiting.
            continue

        obj = try_decode_json_packet(pkt)
        if obj is None:
            raise RuntimeError("expected JSON start packet before JPEG frames")

        typ = str(obj.get("type") or obj.get("cmd") or "start").lower()
        if typ in {"start", "header"}:
            return obj
        if typ in {"close", "quit", "exit"}:
            raise EOFError("client requested close")
        # Ignore ping/unknown idle controls.


def drain_until_round_end(sock: socket.socket, max_sec: float = 30.0) -> None:
    """
    After returning a detected result, keep the connection open and discard the
    remaining frame packets until the sender sends the current-round end marker.
    """
    old_timeout = sock.gettimeout()
    end_t = time.time() + float(max_sec)
    try:
        sock.settimeout(0.2)
        while time.time() < end_t:
            try:
                pkt = recv_packet(sock)
            except socket.timeout:
                continue
            if pkt is None:
                break
            obj = try_decode_json_packet(pkt)
            if obj is not None:
                typ = str(obj.get("type") or obj.get("cmd") or "").lower()
                if typ in {"end", "stop"}:
                    break
                # Do not support pipelining a new start before ending the old round.
                continue
    finally:
        try:
            sock.settimeout(old_timeout)
        except Exception:
            pass


def make_session_args(base_args: argparse.Namespace, payload: Dict[str, Any]) -> argparse.Namespace:
    args = copy.copy(base_args)
    params = payload.get("params") or {}
    if not isinstance(params, dict):
        params = {}
    for k, v in params.items():
        kk = str(k).replace("-", "_")
        if kk in OVERRIDABLE_FIELDS and hasattr(args, kk):
            current = getattr(args, kk)
            if isinstance(current, bool):
                setattr(args, kk, bool(v))
            elif isinstance(current, int) and not isinstance(current, bool):
                setattr(args, kk, int(v))
            elif isinstance(current, float):
                setattr(args, kk, float(v))
            else:
                setattr(args, kk, v)
    return args


def frame_iter_from_socket(sock: socket.socket) -> Iterable[np.ndarray]:
    while True:
        pkt = recv_packet(sock)
        if pkt is None:
            break

        # Control packets may arrive between rounds; ignore stop/end here.
        obj = try_decode_json_packet(pkt)
        if obj is not None:
            typ = str(obj.get("type") or obj.get("cmd") or "").lower()
            if typ in {"end", "stop"}:
                break
            continue

        arr = np.frombuffer(pkt, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            continue
        yield frame


def process_pushed_frames_online(
    frame_iter: Iterable[np.ndarray],
    *,
    fps: float,
    ball_model: YOLO,
    pose_model: YOLO,
    args: argparse.Namespace,
    source_name: str,
    max_seconds: float = 0.0,
    max_frames: int = 0,
) -> VideoResult:
    fps = float(fps or 25.0)
    if fps <= 1e-6 or fps > 240:
        fps = 25.0

    frame_limit = 0
    if int(max_frames or 0) > 0:
        frame_limit = int(max_frames)
    elif float(max_seconds or 0.0) > 0:
        frame_limit = frames(float(max_seconds), fps, 1)

    chunk = max(1, int(args.online_chunk))
    obs: List[FrameObs] = []
    track = new_track()
    state: Dict[str, object] = {}
    ball_t = pose_t = logic_t = 0.0
    early = False
    t0 = time.time()
    w = h = 0
    batch: List[np.ndarray] = []

    def flush_batch(final_flush: bool = False) -> bool:
        nonlocal batch, w, h, ball_t, pose_t, logic_t, early
        if not batch:
            return False
        if w <= 0 or h <= 0:
            h, w = batch[0].shape[:2]

        tb = time.time()
        br = predict_batch(ball_model, batch, imgsz=args.ball_imgsz, conf=args.ball_conf, args=args)
        tp = time.time()
        pr = predict_batch(pose_model, batch, imgsz=args.pose_imgsz, conf=args.person_conf, args=args)
        te = time.time()
        ball_t += tp - tb
        pose_t += te - tp

        append_observations(obs, br, pr, ball_model, fps, w, h, track, args)
        batch = []

        tl = time.time()
        early = _confirm(obs, fps, h, state, args, final=False) is not None
        logic_t += time.time() - tl
        return early

    for frame in frame_iter:
        if frame_limit > 0 and len(obs) + len(batch) >= frame_limit:
            break
        if w <= 0 or h <= 0:
            h, w = frame.shape[:2]
        batch.append(frame)
        if len(batch) >= chunk:
            if flush_batch(False):
                break

    if not early:
        flush_batch(True)

    tl = time.time()
    events, arr, rows, stats = detect_events(obs, fps, h, detail=False, args=args)
    logic_t += time.time() - tl

    stats = dict(stats)
    stats["decision_policy"] = "tcp_push_online_stable_prefix_" + stats.get("decision_policy", "")
    stats["online_warmup_sec"] = float(_cfg(args, "online_warmup_sec", DEFAULT_ONLINE_WARMUP_SEC))
    stats["online_wait_sec"] = float(_cfg(args, "online_wait_sec", DEFAULT_ONLINE_WAIT_SEC))
    stats["stable_chunks"] = int(_cfg(args, "stable_chunks", DEFAULT_STABLE_CHUNKS))
    stats["source"] = str(source_name)
    stats["max_seconds"] = float(max_seconds or 0.0)
    stats["max_frames"] = int(frame_limit or 0)

    return make_result(
        video=Path(str(source_name or "tcp_push_stream")),
        fps=fps,
        width=w,
        height=h,
        frame_count=frame_limit,
        mode="online_tcp_push",
        early_stopped=early,
        observations=obs,
        events=events,
        arrays=arr,
        detail_rows=rows,
        stats=stats,
        timings={
            "ball_sec": ball_t,
            "pose_sec": pose_t,
            "logic_sec": logic_t,
            "total_sec": time.time() - t0,
        },
    )


def build_result_packet(session_id: str, source: str, result: VideoResult, status: str) -> Dict[str, Any]:
    event = best_event(result)
    packet: Dict[str, Any] = {
        "session_id": session_id,
        "status": status,
        "event": "kick_detected" if event else "no_event",
        "source": source,
        "mode": result.mode,
        "early_stopped": bool(result.early_stopped),
        "processed_frames": int(result.processed_frames),
        "video": {
            "fps": _finite_float(result.fps, 0.0),
            "width": int(result.width or 0),
            "height": int(result.height or 0),
            "frame_limit": int(result.frame_count or 0),
        },
        "timings": result.timings,
        "stats": result.stats,
    }

    if event is None:
        packet["kick"] = None
        return _json_safe(packet)

    idx = int(event.frame_idx)
    obs = result.observations[idx] if 0 <= idx < len(result.observations) else None
    arr = result.arrays or {}

    center = None
    if obs is not None and obs.ball_center_raw is not None:
        center = [float(obs.ball_center_raw[0]), float(obs.ball_center_raw[1])]
    elif "centers" in arr and idx < len(arr["centers"]):
        center = [float(arr["centers"][idx][0]), float(arr["centers"][idx][1])]

    foot_xy = None
    foot_label = event.nearest_foot_label
    if "foot_xy" in arr and idx < len(arr["foot_xy"]):
        fx, fy = arr["foot_xy"][idx]
        if np.isfinite(fx) and np.isfinite(fy):
            foot_xy = [float(fx), float(fy)]
    if "foot_label" in arr and idx < len(arr["foot_label"]):
        foot_label = str(arr["foot_label"][idx])

    if center is not None and foot_xy is not None:
        kick_point = [(center[0] + foot_xy[0]) * 0.5, (center[1] + foot_xy[1]) * 0.5]
    else:
        kick_point = center

    packet["kick"] = {
        "frame_idx": int(event.frame_idx),
        "frame_id": int(event.frame_id),
        "time_sec": _finite_float(event.time_sec, 0.0),
        "timestamp_ms": int(round(float(event.time_sec) * 1000.0)),
        "kind": event.kind,
        "confidence": _finite_float(event.confidence, 0.0),
        "evidence": event.evidence,
        "dist_norm": _finite_float(event.dist_norm),
        "min_foot_dist_px": _finite_float(event.min_foot_dist),
        "motion_hps": _finite_float(event.motion_hps),
        "motion_gate": _finite_float(event.motion_gate),
        "progress_px": _finite_float(event.progress_px),
        "ball": {
            "center_px": center,
            "bbox_xyxy": list(obs.ball_box) if obs is not None and obs.ball_box is not None else None,
            "conf": _finite_float(obs.ball_conf, 0.0) if obs is not None else None,
            "class": obs.ball_class if obs is not None else "",
        },
        "foot": {
            "point_px": foot_xy,
            "label": foot_label,
            "dist_px": _finite_float(event.min_foot_dist),
        },
        "kick_point": {
            "px": kick_point,
            "definition": "midpoint_between_ball_center_and_nearest_foot_when_available_else_ball_center",
        },
        "event_raw": event_to_dict(event),
    }
    return _json_safe(packet)


def warmup_model(model: YOLO, *, imgsz: int, conf: float, args: argparse.Namespace, name: str) -> None:
    dummy = np.zeros((int(imgsz), int(imgsz), 3), dtype=np.uint8)
    print(f"[TCP SERVICE] warmup {name}: imgsz={imgsz}", flush=True)
    predict_batch(model, [dummy], imgsz=int(imgsz), conf=float(conf), args=args)
    print(f"[TCP SERVICE] warmup {name} done", flush=True)


class KickTCPServer:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.model_lock = threading.Lock()
        self.stop_event = threading.Event()

        print(f"[TCP SERVICE] loading ball model: {args.ball_model}", flush=True)
        self.ball_model = YOLO(args.ball_model, task="detect")
        print(f"[TCP SERVICE] loading pose model: {args.pose_model}", flush=True)
        self.pose_model = YOLO(args.pose_model, task="pose")

        warmup_model(self.ball_model, imgsz=args.ball_imgsz, conf=args.ball_conf, args=args, name="ball")
        warmup_model(self.pose_model, imgsz=args.pose_imgsz, conf=args.person_conf, args=args, name="pose")
        print("[TCP SERVICE] models loaded and warmed up; ready", flush=True)

    def handle_client(self, conn: socket.socket, addr: Tuple[str, int]) -> None:
        print(f"[TCP SERVICE] client connected from={addr}", flush=True)
        try:
            # 长连接空闲等待 start 时不能设置超时；否则发送端等待回车超过 socket_timeout 后，
            # 检测端会误判超时并关闭连接。
            conn.settimeout(None)

            while not self.stop_event.is_set():
                session_id = uuid4().hex[:12]
                source = "tcp_push_stream"

                try:
                    conn.settimeout(None)
                    header = recv_start_packet(conn)
                except EOFError:
                    print(f"[TCP SERVICE] client disconnected from={addr}", flush=True)
                    break

                try:
                    session_id = str(header.get("session_id") or session_id)
                    source = str(header.get("source") or source)
                    fps = float(header.get("fps") or 25.0)
                    max_seconds = float(header.get("max_seconds", self.args.default_max_seconds) or 0.0)
                    max_frames = int(header.get("max_frames", 0) or 0)
                    session_args = make_session_args(self.args, header)

                    print(
                        f"[TCP SERVICE] start session={session_id} from={addr} "
                        f"source={source} fps={fps}",
                        flush=True,
                    )

                    # 开始收本轮视频帧。socket_timeout<=0 表示不限制；适合真实直播长连接。
                    active_timeout = float(self.args.socket_timeout or 0.0)
                    conn.settimeout(active_timeout if active_timeout > 0 else None)

                    # 模型在服务启动时已加载。每个 start 只复用现有模型，不重新加载。
                    with self.model_lock:
                        result = process_pushed_frames_online(
                            frame_iter_from_socket(conn),
                            fps=fps,
                            ball_model=self.ball_model,
                            pose_model=self.pose_model,
                            args=session_args,
                            source_name=source,
                            max_seconds=max_seconds,
                            max_frames=max_frames,
                        )

                    event = best_event(result)
                    status = "detected" if event is not None else "no_event"
                    packet = build_result_packet(session_id, source, result, status)
                    send_json(conn, packet)
                    print(
                        f"[TCP SERVICE] result session={session_id} "
                        f"status={status} processed={result.processed_frames} "
                        f"early={result.early_stopped}",
                        flush=True,
                    )

                    # 如果是 early stop，发送端还可能有少量帧正在路上。
                    # 结果已经返回；这里只丢弃本轮剩余包，直到发送端发 end 标记，然后继续等下一次 start。
                    if result.early_stopped:
                        # 返回结果后等待发送端发送 end，本轮结束后继续等下一次 start。
                        # 这里给一个有限 drain 时间，避免异常客户端永远不发 end 时服务卡住。
                        drain_sec = float(self.args.socket_timeout or 0.0)
                        drain_until_round_end(conn, max_sec=drain_sec if drain_sec > 0 else 10.0)

                    # 回到空闲状态，等待下一次 start，不超时。
                    conn.settimeout(None)

                except Exception as exc:
                    err = {
                        "session_id": session_id,
                        "status": "error",
                        "event": "error",
                        "source": source,
                        "error": str(exc),
                        "traceback": traceback.format_exc(limit=20),
                    }
                    try:
                        send_json(conn, err)
                    except Exception:
                        pass
                    print(f"[TCP SERVICE] error session={session_id}: {exc}", flush=True)
                    # 当前轮异常后等待发送端 end，避免残留帧污染下一轮。
                    try:
                        drain_until_round_end(conn, max_sec=2.0)
                    except Exception:
                        break
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def serve_forever(self) -> None:
        host = str(self.args.tcp_host)
        port = int(self.args.tcp_port)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            s.listen(int(self.args.backlog))
            s.settimeout(0.5)
            print(f"[TCP SERVICE] listening on tcp://{host}:{port}", flush=True)
            print("[TCP SERVICE] protocol: header JSON + JPEG frame packets; no RTSP/MediaMTX/ffmpeg needed", flush=True)
            while not self.stop_event.is_set():
                try:
                    conn, addr = s.accept()
                except socket.timeout:
                    continue
                # Demo 场景按一个发送端顺序处理，避免跨线程复用 TensorRT/YOLO engine。
                self.handle_client(conn, addr)


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser("TCP push-stream kick-contact detector")

    p.add_argument("--tcp-host", default="0.0.0.0")
    p.add_argument("--tcp-port", type=int, default=19090)
    p.add_argument("--backlog", type=int, default=16)
    p.add_argument("--socket-timeout", type=float, default=0.0, help="active receive timeout in seconds; <=0 means no timeout")
    p.add_argument("--default-max-seconds", type=float, default=20.0)

    # 模型与推理参数：默认值对齐 myscripts_test。
    p.add_argument("--ball-model", default="yolo11s.pt")
    p.add_argument("--pose-model", default="yolo11m-pose.pt")
    p.add_argument("--device", default="0")
    p.add_argument("--half", action="store_true", help="use FP16 on CUDA/TensorRT; ignored on CPU")
    p.add_argument("--batch", type=int, default=4)
    p.add_argument("--online-chunk", type=int, default=16)
    p.add_argument("--pad-last-batch", action="store_true", default=True)
    p.add_argument("--no-pad-last-batch", dest="pad_last_batch", action="store_false")
    p.add_argument("--ball-imgsz", type=int, default=640)
    p.add_argument("--pose-imgsz", type=int, default=640)
    p.add_argument("--ball-conf", type=float, default=0.16)
    p.add_argument("--person-conf", type=float, default=0.20)
    p.add_argument("--pose-conf", type=float, default=0.18)

    p.add_argument("--yolo-iou", type=float, default=0.50)
    p.add_argument("--ball-class-names", default="sports ball,ball,football,soccer ball,volleyball")
    p.add_argument("--max-ball-candidates", type=int, default=8)
    p.add_argument("--hand-conf", type=float, default=0.20)
    p.add_argument("--contact-percentile", type=float, default=35.0)
    p.add_argument("--motion-percentile", type=float, default=85.0)
    p.add_argument("--direction-cos-thresh", type=float, default=0.15)
    p.add_argument("--motion-window-sec", type=float, default=0.24)
    p.add_argument("--min-visible-steps", type=int, default=2)
    p.add_argument("--loss-reappear-sec", type=float, default=0.70)
    p.add_argument("--online-warmup-sec", type=float, default=0.80)
    p.add_argument("--online-wait-sec", type=float, default=0.55)
    p.add_argument("--stable-chunks", type=int, default=2)
    return p


def main() -> None:
    args = build_argparser().parse_args()
    server = KickTCPServer(args)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[TCP SERVICE] stopping", flush=True)
        server.stop_event.set()


if __name__ == "__main__":
    main()
