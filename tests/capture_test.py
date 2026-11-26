#!/usr/bin/env python3
"""Record an isolated X server and verify every pixel from the tested capture paths."""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import secrets
import select
import shutil
import subprocess
import tempfile
import time

from PIL import Image

HERE = Path(__file__).resolve().parent
RED, GREEN = (223, 75, 105), (64, 206, 155)
COLORS = {RED, GREEN, (41, 67, 94), (246, 224, 104)}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def terminate(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    for pipe in (process.stdout, process.stdin):
        if pipe:
            pipe.close()


class Session:
    def __init__(self, temp, out, stack):
        self.temp = temp
        self.out = out
        self.stack = stack
        self.probe = temp / "xprobe"
        subprocess.run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", HERE / "xprobe.c",
                        "-o", self.probe, "-lX11", "-lXext", "-lXfixes"], check=True)

    def start(self, env, command, label, **kwargs):
        log = self.stack.enter_context((self.out / (label + ".log")).open("wb"))
        process = subprocess.Popen(command, env=env, stderr=log, **kwargs)
        self.stack.callback(terminate, process)
        return process

    def number(self, process, label, timeout):
        ready = select.select([process.stdout], [], [], timeout)[0]
        value = process.stdout.readline().decode().strip() if ready else ""
        require(value.isdecimal(), f"{label} did not start correctly; see {self.out / (label + '.log')}")
        return value

    def server(self, executable, options, name, env):
        cookie = secrets.token_hex(16)
        authority = self.temp / (name + ".auth")
        authority.touch(mode=0o600)

        def authorize(display):
            subprocess.run(["xauth", "-q", "-f", authority], input=f"add {display} . {cookie}\n",
                           text=True, check=True, stdout=subprocess.DEVNULL)

        authorize(":32760")
        process = self.start(env, [executable, "-displayfd", "1", "-noreset", "-nolisten", "tcp",
                                   "-auth", authority, *options], name, stdout=subprocess.PIPE)
        display = ":" + self.number(process, name, 15)
        require(display != env.get("DISPLAY"), "Unexpected parent display reuse")
        authorize(display)
        return dict(env, DISPLAY=display, XAUTHORITY=str(authority), X11_QA_ISOLATED="1")

    def record(self, env, size, name, *, window=None, frames=24, cursor=False, wait_first_frame=False):
        dest = self.out / (name + ".mkv")
        command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-n",
                   "-f", "x11grab", "-draw_mouse", str(int(cursor)), "-framerate", "15",
                   "-probesize", "32", "-analyzeduration", "0", "-video_size", size]
        if wait_first_frame:
            command += ["-stats_period", "0.1", "-progress", "pipe:1"]
        if window:
            command += ["-window_id", window]
        command += ["-i", env["DISPLAY"], "-frames:v", str(frames), "-threads", "1",
                    "-c:v", "ffv1", "-pix_fmt", "bgr0", dest]
        process = self.start(env, command, name, stdout=subprocess.PIPE if wait_first_frame else subprocess.DEVNULL)
        if wait_first_frame:
            # FFmpeg emits this after an output frame exists, before the test window is created.
            deadline = time.monotonic() + 10
            progress = b""
            while not any(line.startswith(b"frame=") and int(line.split(b"=")[1]) > 0
                          for line in progress.split(b"\n")[:-1]):
                timeout = max(0, deadline - time.monotonic())
                require(select.select([process.stdout], [], [], timeout)[0], "Waiting for FFmpeg's first frame timed out")
                chunk = os.read(process.stdout.fileno(), 4096)
                require(chunk, f"FFmpeg ended before the first frame; see {dest.with_suffix('.log')}")
                progress += chunk
        return process, dest, size, frames

    def observe(self, env, *command):
        output = subprocess.check_output([self.probe, *command], env=env, timeout=10)
        return json.loads(output)


def analyse(recording, black):
    process, dest, size, count = recording
    require(process.wait(timeout=25) == 0, f"Capture failed; see {dest.with_suffix('.log')}")
    width, height = map(int, size.split("x"))
    frame_bytes = width * height * 3
    data = subprocess.check_output(["ffmpeg", "-v", "error", "-i", dest, "-map", "0:v:0",
                                    "-threads", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                   timeout=30)
    require(len(data) == frame_bytes * count, f"{dest.name}: incomplete recording")
    changes, nonblack, peak = 0, 0, 0
    present = set()
    previous = None
    for index in range(count):
        frame = data[index * frame_bytes:(index + 1) * frame_bytes]
        image = Image.frombytes("RGB", (width, height), frame)
        histogram = {color: n for n, color in image.getcolors(width * height)}
        nonblack += width * height - histogram.get((0, 0, 0), 0)
        present.update(color for color in COLORS if histogram.get(color, 0) > 60)
        peak = max(peak, *(high for _, high in image.getextrema()))
        changes += previous is not None and frame != previous
        previous = frame
        if index == count // 2:
            image.save(dest.with_suffix(".png"))
    result = {"frames": count, "size": size, "nonblack": nonblack, "channel_max": peak,
              "changes": changes, "fixture_primaries": [bytes(color).hex() for color in sorted(present)]}
    print(dest.stem, result, flush=True)
    if black:
        require(nonblack == 0, f"{dest.name}: found {nonblack} nonblack pixels")
    else:
        require({RED, GREEN} <= present and changes > 2, f"{dest.name}: missing moving fixture")
    return result


def gstreamer(env, dest, window, width, height, black):
    subprocess.run(["gst-launch-1.0", "-q", "ximagesrc", f"xid={window}", "show-pointer=true",
                    "num-buffers=16", "!", "video/x-raw,framerate=15/1", "!", "videoconvert",
                    "!", "video/x-raw,format=RGB", "!", "filesink", f"location={dest}"],
                   env=env, timeout=25, check=True)
    data = dest.read_bytes()
    require(len(data) == width * height * 3 * 16, f"{dest.name}: incomplete RGB stream")
    peak = max(data)
    require(peak == 0 if black else peak > 127, f"{dest.name}: unexpected maximum {peak}")
    return {"frames": 16, "peak": peak}


def exercise(session, env, parent, black, test_gstreamer):
    report = {"mode": "guard" if black else "stock"}
    ext_info = subprocess.check_output(["xdpyinfo"], env=env, text=True, timeout=15)
    lines = {line.strip() for line in ext_info.splitlines()}
    report["extensions"] = sorted(lines & {"MIT-SHM", "Composite", "GLX", "XFIXES", "DRI3", "RENDER", "XTEST"})
    before = session.record(env, "320x240", "first-map-root", frames=36, wait_first_frame=True)
    fixture = session.start(env, [session.probe, "scene"], "fixture",
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    window = session.number(fixture, "fixture", 8)
    recordings = [(before, black),
                  (session.record(env, "320x240", "inner-root"), black),
                  (session.record(env, "320x240", "inner-root-cursor", cursor=True), black),
                  (session.record(env, "160x104", "inner-window", window=window), black)]
    if parent:
        recordings.append((session.record(parent, "400x300", "onsite"), False))

    cursor = session.observe(env, "cursor")
    require(cursor["nonzero"] == 0 if black else cursor["nonzero"] > 0, f"Unexpected cursor: {cursor}")
    report["cursor"] = cursor
    for method in ("core", "shm"):
        for name, target in (("root", "root"), ("window", window)):
            sample = session.observe(env, method, target)
            require(sample["nonblack"] == 0 if black else sample["fixture"] > 500,
                    f"Unexpected {method} {name} readback: {sample}")
            report[f"{method}-{name}"] = sample
    for recording, masked in recordings:
        report[recording[1].stem] = analyse(recording, masked)

    transitions = session.record(env, "320x240", "fullscreen-remap", frames=33)
    outer = session.record(parent, "400x300", "onsite-transitions", frames=33) if parent else None
    for command in b"fsmhms":
        fixture.stdin.write(bytes([command]))
        fixture.stdin.flush()
        time.sleep(0.24)
    report["fullscreen-remap"] = analyse(transitions, black)
    if outer:
        report["onsite-transitions"] = analyse(outer, False)
    if test_gstreamer:
        for name, target, w, h in (("screen", "0", 320, 240), ("window", window, 160, 104)):
            key = "gst-" + name
            report[key] = gstreamer(env, session.out / (key + ".rgb"), target, w, h, black)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["stock", "guard"], help="expect moving colors or fully black frames")
    parser.add_argument("server", help="Xephyr executable (or Xorg via run-native)")
    parser.add_argument("--parent", default="Xvfb", help="unmodified Xvfb executable, resolved via PATH")
    parser.add_argument("--gstreamer", action="store_true", help="also capture using GStreamer ximagesrc")
    parser.add_argument("--out", required=True, type=Path, help="new or empty output directory")
    parser.add_argument("--native-modules", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    executable = shutil.which(args.server)
    require(executable, f"Cannot find X server: {args.server}")
    args.out.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(not any(args.out.iterdir()), f"Output directory must be empty: {args.out}")
    env = {k: v for k, v in os.environ.items() if k not in
           {"DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS"}}

    with tempfile.TemporaryDirectory(prefix="x11-capture-qa-") as temp, ExitStack() as stack:
        session = Session(Path(temp), args.out.resolve(), stack)
        parent = None
        if args.native_modules:
            require(os.environ.get("X11_QA_NAMESPACE") == "1" and not any(Path(path).exists() for path in
                    ["/dev/tty0", "/dev/dri", "/run/dbus/system_bus_socket"]), "Use the run-native wrapper")
            empty = session.temp / "config.d"
            empty.mkdir()
            options = ["-config", HERE / "dummy.conf", "-configdir", empty, "-modulepath",
                       args.native_modules.resolve(), "-logfile", session.out / "Xorg.log",
                       "-seat", "xguard-qa-seat", "-novtswitch"]
            inner = session.server(executable, options, "native", env)
        else:
            xvfb = shutil.which(args.parent)
            require(xvfb, f"Cannot find stock Xvfb: {args.parent}")
            parent = session.server(xvfb, ["-screen", "0", "400x300x24"], "host", env)
            inner = session.server(executable, ["-screen", "320x240", "-no-host-grab"], "nested", parent)
        report = exercise(session, inner, parent, args.mode == "guard", args.gstreamer)
        (session.out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"PASS {args.mode}: {session.out / 'report.json'}")


if __name__ == "__main__":
    main()
