# Fedora X11 录屏回归测试

这组测试会启动自己的 X Server，在蓝色背景上显示红绿交替的窗口和移动的黄色方块。普通 X Server 用来确认录制器能采到运动和颜色。专用 X Server 用来确认同样的录制请求得到全黑像素。

## 安装测试依赖

在 Fedora 45 上，从仓库根目录运行下面的示例。测试脚本使用普通用户权限，应用 RPM 提供专用 X Server。也可以把示例中专用程序的路径换成源码构建得到的可执行文件。

```bash
sudo dnf install gcc python3-pillow libX11-devel libXext-devel libXfixes-devel \
  ffmpeg-free xorg-x11-xauth xdpyinfo xorg-x11-server-Xvfb xorg-x11-server-Xephyr
```

附加的 GStreamer 测试需要 `gstreamer1`、`gstreamer1-plugins-base` 和 `gstreamer1-plugins-good`。原生 Xorg 虚拟驱动测试需要 `bubblewrap`、`xorg-x11-server-Xorg` 和 `xorg-x11-drv-dummy`。系统已经提供兼容的 `ffmpeg` 时，使用现有命令即可，它需要支持 `x11grab` 输入和 FFV1 编解码。

## 同时验证现场画面和会话内部录屏

```bash
results=$(mktemp -d)
python3 tests/capture_test.py stock /usr/bin/Xephyr \
  --parent /usr/bin/Xvfb --out "$results/nested-stock" --gstreamer
python3 tests/capture_test.py guard /usr/libexec/x11-showcase/Xephyr \
  --parent /usr/bin/Xvfb --out "$results/nested-guard" --gstreamer
```

两次都用未修改的 Xvfb 作为外层显示器。脚本清除继承的显示授权和显示地址，让两层服务自行分配空闲的本地显示编号，为每一层生成独立的临时授权文件，在临时目录构建 C 测试程序。录制器只连接测试创建的显示器。脚本会在结束时关闭自己启动的服务。

在保护组中打开 `onsite.mkv`，可以看到外侧虚拟显示器显示的彩色运动图案。在同一目录打开 `inner-root.mkv`，可以看到专用会话内部录制的整屏。嵌套模式下宿主能看到并录下现场画面，这也是此模式的边界。

## 验证原生 Xorg 与虚拟驱动

```bash
results=$(mktemp -d)
bash tests/run-native stock /usr/libexec/Xorg /usr/lib64/xorg/modules \
  "$results/native-stock" --gstreamer
bash tests/run-native guard /usr/libexec/x11-showcase/Xorg \
  /usr/lib64/xorg/modules/drivers/dummy_drv.so "$results/native-guard" --gstreamer
```

第三个参数接受完整的 Xorg 模块目录或其中的 `drivers/dummy_drv.so`。驱动需要与被测 Xorg 的模块 ABI 兼容。脚本通过 Bubblewrap 建立独立的设备、网络和 IPC 环境，使用虚拟显示驱动，并隔离主机的 VT、GPU 和系统 D-Bus。运行此项需要内核允许当前用户创建用户命名空间。终端报告中的 `/tmp/qa-output` 对应命令指定的结果目录。真实显卡、显示输出和 VT 切换需要另行实机验证。

## 判断结果

每个结果目录必须为空或尚未创建。脚本遇到空录像、读取失败、像素不符和缺少运动图案等情况会以非零状态退出。通过后会打印 `PASS` 并保存 `report.json`。省略 `--gstreamer` 可以单独运行 FFmpeg、Xlib 和 XFixes 测试。

| 路径 | 检查内容 |
| --- | --- |
| FFmpeg x11grab | 开窗前已经开始录制、整屏、整屏带光标、指定窗口、全屏切换和隐藏后重新显示，五组共 141 帧 |
| XGetImage、XShmGetImage | 分别读取根窗口和指定窗口。共享内存先填入非零字节 |
| XFixesGetCursorImage | 普通服务应读到测试十字光标的非透明像素，保护组应读到全零 |
| GStreamer ximagesrc | 启用指针，各录制 16 帧整屏和指定窗口的原始 RGB |

保护组的内部录制在 FFV1 解码后逐帧检查 RGB 的每一个像素，`nonblack` 和 `channel_max` 均应为零。普通对照和嵌套测试中的外侧采集应同时出现红色、绿色和运动。结果目录里的 PNG 是实际录制的中间帧。此套件验证上述 X11 路径；桌面合成器、音频和物理显示设备有各自的采集路径。
